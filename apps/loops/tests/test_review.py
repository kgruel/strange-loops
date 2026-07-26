"""Canonical review projection — ``read --review`` (0.9.0 S4).

A deterministic, diffable JSON snapshot of folded state: kind-key-sorted rows
carrying only the emit-derived whitelist + a verbatim signature, under a header
disclosing the read's cursor position, declaration generation, and seal cut.

Tiers:

- End-to-end (``Test*EndToEnd``, ``TestHeaderContract``, ``TestGuards``): drive
  the real ``read`` router through ``fold._run_review`` against scratch stores
  (``StorePopulator`` for unsigned facts, raw sqlite for signed/precise-ts
  control — the convention test_fold_cut_provenance.py uses).
- Encoder unit (``TestToReview``): ``surface.to_review`` over hand-built
  ``FoldState`` — sort + whitelist + signature threading with no store.
- Engine unit (``TestDeclarationGeneration``, ``TestFactSignatures``):
  ``engine.declaration_generation`` / ``engine.fact_signatures`` directly,
  including the adopted-store ``decl_head`` and pre-genesis honesty.

The projection stops short of SPEC §10 (no witness-ordered every-row stream, no
JCS byte determinism, no rebuild round-trip, no chain) — gated on
GlobalReceiptPosition + loops-go (arbiter S4-F4). These tests assert the REVIEW
property "same folded state -> same bytes", never interchange canonicalization.
"""

from __future__ import annotations

import hashlib
import dataclasses
import json
import sqlite3

import pytest
from atoms import Edge, Fact, FoldItem, FoldSection, FoldState

from engine import declaration_generation, fact_signatures
from engine.builder import fold_by, fold_collect, vertex
from engine.sqlite_store import SqliteStore, gen_id
from loops.cli.invocation import Invocation
from loops.cli.output import BufferReporter
from loops.cli.views import read as read_view
from loops.surface import REVIEW_EXCLUDED_FIELDS, to_review

from .builders import StorePopulator


def ctx(reporter: BufferReporter | None = None, *, isatty: bool = False) -> Invocation:
    return Invocation(reporter=reporter or BufferReporter(), isatty=isatty)


def _run(vpath, argv, *, isatty=False) -> tuple[int, BufferReporter]:
    r = BufferReporter()
    rc = read_view.run([str(vpath), *argv], ctx(r, isatty=isatty))
    return rc, r


def _review(vpath, argv=(), *, isatty=False) -> dict:
    """Run ``read --review`` and return the parsed ``{review, rendered_at}``."""
    rc, r = _run(vpath, ["--review", *argv], isatty=isatty)
    assert rc == 0, r.err_text
    return json.loads(r.out_lines[0])


def _append(store, kind, ts, *, fid=None, observer="kyle", signature=None, **payload):
    conn = sqlite3.connect(str(store))
    fid = fid or gen_id()
    conn.execute(
        "INSERT INTO facts (id, kind, ts, observer, origin, payload, signature) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (fid, kind, ts, observer, "", json.dumps(payload), signature),
    )
    conn.commit()
    conn.close()
    return fid


def _append_tick(store, name, ts, *, fact_cursor=None):
    conn = sqlite3.connect(str(store))
    tid = gen_id()
    conn.execute(
        "INSERT INTO ticks (id, name, ts, since, origin, payload, fact_cursor) "
        "VALUES (?, ?, ?, 0.0, '', '{}', ?)",
        (tid, name, ts, fact_cursor),
    )
    conn.commit()
    conn.close()
    return tid


def _empty_store(path):
    SqliteStore(
        path=path, serialize=lambda f: f.to_dict(), deserialize=Fact.from_dict,
    ).close()


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def review_vertex(tmp_path):
    """Pre-genesis store: decision(by topic) + thread(by name) + log(collect)."""
    v = (
        vertex("proj")
        .store("./p.db")
        .loop("decision", fold_by("topic"))
        .loop("thread", fold_by("name"))
        .loop("log", fold_collect("items", max_items=50))
    )
    vpath = tmp_path / "proj.vertex"
    v.write(vpath)
    db = tmp_path / "p.db"
    (
        StorePopulator(db, observer="kyle")
        .emit("decision", ts=100.0, topic="auth", message="JWT over sessions")
        .emit("decision", ts=200.0, topic="store", message="sqlite WAL")
        .emit("thread", ts=300.0, name="cli-work", status="open")
        .emit("log", ts=400.0, message="one")
        .emit("log", ts=500.0, message="two")
        .done()
    )
    return vpath, db


# ---------------------------------------------------------------------------
# Determinism — the core review property
# ---------------------------------------------------------------------------


class TestDeterminismEndToEnd:
    def test_two_reads_byte_identical_review(self, review_vertex):
        vpath, _ = review_vertex
        a = _review(vpath)
        b = _review(vpath)
        assert json.dumps(a["review"], sort_keys=True) == json.dumps(
            b["review"], sort_keys=True
        )

    def test_rendered_at_is_the_only_volatile_field(self, review_vertex):
        vpath, _ = review_vertex
        a = _review(vpath)
        b = _review(vpath)
        # rendered_at lives OUTSIDE `review` and is the sole render-time field.
        assert set(a.keys()) == {"review", "rendered_at"}
        assert a["review"] == b["review"]

    def test_facts_sorted_by_kind_key_id(self, review_vertex):
        vpath, _ = review_vertex
        facts = _review(vpath)["review"]["facts"]
        keyed = [(f["kind"], f["key"] or "", f["id"] or "") for f in facts]
        assert keyed == sorted(keyed)


class TestSortStabilityAcrossEmitOrder:
    """The (kind,key) sort makes the projection order emit-order-independent —
    the gap that makes plain ``--json`` (faithful fold order) unfit for review."""

    def _emit(self, tmp_path, name, order):
        v = vertex("s").store(f"./{name}.db").loop("decision", fold_by("topic"))
        vpath = tmp_path / f"{name}.vertex"
        v.write(vpath)
        db = tmp_path / f"{name}.db"
        pop = StorePopulator(db, observer="kyle")
        for i, topic in enumerate(order):
            pop.emit("decision", ts=100.0 + i, topic=topic, message=topic)
        pop.done()
        return vpath

    def test_review_order_stable_but_fold_order_differs(self, tmp_path):
        v1 = self._emit(tmp_path, "one", ["a", "b", "c"])
        v2 = self._emit(tmp_path, "two", ["c", "b", "a"])
        keys1 = [f["key"] for f in _review(v1)["review"]["facts"]]
        keys2 = [f["key"] for f in _review(v2)["review"]["facts"]]
        assert keys1 == keys2 == ["a", "b", "c"]

        # Contrast: plain --json (Surface fold order) preserves emit order, so
        # the two logically-identical stores diff spuriously — the gap review
        # closes.
        def _json_keys(vp):
            rc, r = _run(vp, ["--json", "--kind", "decision"])
            assert rc == 0, r.err_text
            rows = json.loads(r.out_lines[0])["rows"]
            return [row["key"] for row in rows]

        assert _json_keys(v1) != _json_keys(v2)


class TestVolatileExclusionUnderCite:
    def test_new_ref_does_not_change_the_targets_review_row(self, review_vertex):
        vpath, db = review_vertex
        before = _review(vpath)["review"]["facts"]
        target = next(f for f in before if f["kind"] == "decision" and f["key"] == "auth")

        # A later fact refs decision:auth — bumps its inbound/salience in the
        # Surface, which a review row must NOT carry.
        StorePopulator(db, observer="kyle").emit(
            "decision", ts=600.0, topic="later", message="cites auth",
            ref="decision:auth",
        ).done()

        after = _review(vpath)["review"]["facts"]
        target_after = next(
            f for f in after if f["kind"] == "decision" and f["key"] == "auth"
        )
        assert target_after == target  # byte-identical: no volatile drift
        # The only change is the added row.
        assert len(after) == len(before) + 1
        assert any(f["key"] == "later" for f in after)


# ---------------------------------------------------------------------------
# Whitelist — emit-derived fields only
# ---------------------------------------------------------------------------


class TestWhitelistEndToEnd:
    def test_no_forbidden_keys_in_rows(self, review_vertex):
        vpath, _ = review_vertex
        forbidden = set(REVIEW_EXCLUDED_FIELDS)
        for row in _review(vpath)["review"]["facts"]:
            assert forbidden.isdisjoint(row.keys()), row

    def test_rows_carry_the_included_whitelist(self, review_vertex):
        vpath, _ = review_vertex
        row = _review(vpath)["review"]["facts"][0]
        assert set(row.keys()) == {
            "kind", "key", "key_field", "payload", "id", "ts",
            "observer", "origin", "n", "refs", "edges", "signature",
        }

    def test_no_window_or_schema_at_review_top(self, review_vertex):
        vpath, _ = review_vertex
        review = _review(vpath)["review"]
        assert "window" not in review
        assert "schema" not in review


# ---------------------------------------------------------------------------
# Signatures — verbatim, null-on-unsigned
# ---------------------------------------------------------------------------


class TestSignaturesEndToEnd:
    @pytest.fixture
    def signed_mix(self, tmp_path):
        v = vertex("sig").store("./sig.db").loop("decision", fold_by("topic"))
        vpath = tmp_path / "sig.vertex"
        v.write(vpath)
        db = tmp_path / "sig.db"
        _empty_store(db)
        signed_id = _append(
            db, "decision", 100.0, topic="signed", message="m",
            signature="SIG-VERBATIM-abc123",
        )
        unsigned_id = _append(db, "decision", 200.0, topic="bare", message="m")
        return vpath, db, signed_id, unsigned_id

    def test_signed_row_carries_verbatim_column(self, signed_mix):
        vpath, db, signed_id, unsigned_id = signed_mix
        facts = _review(vpath)["review"]["facts"]
        by_id = {f["id"]: f for f in facts}
        assert by_id[signed_id]["signature"] == "SIG-VERBATIM-abc123"
        assert by_id[unsigned_id]["signature"] is None

    def test_signature_equals_direct_select_no_recompute(self, signed_mix):
        vpath, db, signed_id, _ = signed_mix
        facts = _review(vpath)["review"]["facts"]
        review_sig = next(f for f in facts if f["id"] == signed_id)["signature"]
        conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
        stored = conn.execute(
            "SELECT signature FROM facts WHERE id=?", (signed_id,)
        ).fetchone()[0]
        conn.close()
        assert review_sig == stored


class TestFactSignatures:
    def test_pre_signature_store_all_none(self, tmp_path):
        db = tmp_path / "old.db"
        conn = sqlite3.connect(str(db))
        conn.execute("CREATE TABLE facts (id TEXT PRIMARY KEY, kind TEXT)")
        conn.execute("INSERT INTO facts (id, kind) VALUES ('X', 'decision')")
        conn.commit()
        conn.close()
        assert fact_signatures(db, ["X"]) == {"X": None}

    def test_empty_ids_and_dedupe(self, tmp_path):
        db = tmp_path / "e.db"
        _empty_store(db)
        _append(db, "decision", 1.0, fid="A", topic="a", signature="s")
        assert fact_signatures(db, []) == {}
        got = fact_signatures(db, ["A", "A", "MISSING"])
        assert got == {"A": "s", "MISSING": None}


# ---------------------------------------------------------------------------
# Header — cursor / declaration / cut disclosure
# ---------------------------------------------------------------------------


class TestHeaderContract:
    def test_head_cursor_shape(self, review_vertex):
        vpath, _ = review_vertex
        header = _review(vpath)["review"]["header"]
        cur = header["cursor"]
        assert cur["mode"] == "witness"
        assert cur["address"] == "head"
        assert cur["head"] is True
        assert cur["status"] == "file-pre-genesis"
        assert cur["unadopted"] is True
        assert cur["portable"] is False
        assert cur["durable_handle"] is None
        assert "fact_id" in cur and "seq" in cur

    def test_header_vertex_name(self, review_vertex):
        vpath, _ = review_vertex
        assert _review(vpath)["review"]["header"]["vertex"] == "proj"

    def test_declaration_header_pre_genesis(self, review_vertex):
        vpath, _ = review_vertex
        decl = _review(vpath)["review"]["header"]["declaration"]
        assert decl["status"] == "file-pre-genesis"
        assert decl["lineage"] is None
        assert decl["decl_head"] is None
        assert decl["review_fingerprint"].startswith("sha256:")

    def test_cut_header_present(self, review_vertex):
        vpath, _ = review_vertex
        cut = _review(vpath)["review"]["header"]["cut"]
        assert cut["available"] is True
        assert cut["mode"] == "head"

    def test_at_cursor_carries_witness_position(self, review_vertex):
        vpath, _ = review_vertex
        header = _review(vpath, ["--at", "seq:2"])["review"]["header"]
        cur = header["cursor"]
        assert cur["mode"] == "witness"
        assert cur["address"] == "seq:2"
        assert cur["seq"] == 2
        assert cur.get("head") is None  # not a head read
        assert header["cut"]["mode"] == "witness"

    def test_as_of_cursor_has_no_witness_cut(self, review_vertex):
        vpath, _ = review_vertex
        header = _review(vpath, ["--as-of", "30d"])["review"]["header"]
        assert header["cursor"]["mode"] == "as_of"
        assert header["cut"]["available"] is False
        assert "no witness-anchored cut" in header["cut"]["reason"]


# ---------------------------------------------------------------------------
# Declaration generation — engine unit
# ---------------------------------------------------------------------------


class TestDeclarationGeneration:
    def test_pre_genesis_shape(self, review_vertex):
        vpath, _ = review_vertex
        gen = declaration_generation(vpath)
        assert gen["status"] == "file-pre-genesis"
        assert gen["lineage"] is None
        assert gen["decl_head"] is None
        assert gen["review_fingerprint"].startswith("sha256:")

    def test_fingerprint_stable_across_reads(self, review_vertex):
        vpath, _ = review_vertex
        assert (
            declaration_generation(vpath)["review_fingerprint"]
            == declaration_generation(vpath)["review_fingerprint"]
        )

    def test_semantic_edit_changes_fingerprint(self, review_vertex):
        vpath, _ = review_vertex
        before = declaration_generation(vpath)["review_fingerprint"]
        vpath.write_text(
            vpath.read_text().replace(
                "loops {", 'loops {\n  hypothesis { fold { items "by" "name" } }',
            )
        )
        after = declaration_generation(vpath)["review_fingerprint"]
        assert before != after

    def test_cosmetic_edit_does_not_churn_fingerprint(self, review_vertex):
        vpath, _ = review_vertex
        before = declaration_generation(vpath)["review_fingerprint"]
        vpath.write_text(vpath.read_text() + "\n// a trailing comment\n\n")
        after = declaration_generation(vpath)["review_fingerprint"]
        assert before == after

    def test_adopted_store_surfaces_lineage_and_decl_head(self, tmp_path):
        from lang import parse_vertex_file
        from lang.document import vertex_to_documents

        v = vertex("ad").store("./ad.db").loop("decision", fold_by("topic"))
        vpath = tmp_path / "ad.vertex"
        v.write(vpath)
        db = tmp_path / "ad.db"
        ast = parse_vertex_file(vpath)
        docs = [d.as_json() for d in vertex_to_documents(ast)]
        receipt = SqliteStore(
            path=db, serialize=lambda f: f.to_dict(), deserialize=Fact.from_dict,
        ).absorb_genesis(
            docs, observer="ad",
            fact_signer=lambda observer, digest: f"sig:{digest}",
        )
        lineage = receipt["lineage"]

        gen = declaration_generation(vpath)
        assert gen["status"] == "store"
        assert gen["lineage"] == lineage
        # Genesis-only store: the declaration head IS the genesis id.
        assert gen["decl_head"] == lineage


# ---------------------------------------------------------------------------
# Aggregate degradation — no witness head, honest cursor/cut
# ---------------------------------------------------------------------------


class TestAggregateDegradation:
    def test_aggregate_does_not_crash_and_degrades(self, tmp_path, review_vertex):
        member_vpath, _ = review_vertex
        agg = tmp_path / "agg.vertex"
        agg.write_text(f'name "agg"\ncombine {{\n  vertex "{member_vpath}"\n}}\n')
        out = _review(agg)
        header = out["review"]["header"]
        assert header["cursor"] is None
        assert header["cut"]["available"] is False
        assert "aggregate vertex" in header["cut"]["reason"]
        assert header["declaration"]["decl_head"] is None


# ---------------------------------------------------------------------------
# Read-purity — the projection writes nothing (S2 precondition)
# ---------------------------------------------------------------------------


class TestReadPurity:
    def test_store_byte_stable_across_review(self, review_vertex):
        vpath, db = review_vertex
        before = db.read_bytes()
        _review(vpath)
        _review(vpath, ["--at", "seq:1"])
        assert db.read_bytes() == before

    def test_no_fts_tables_created(self, review_vertex):
        vpath, db = review_vertex
        _review(vpath)
        conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
        tables = {
            r[0]
            for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
        conn.close()
        assert "facts_fts" not in tables
        assert "fts_state" not in tables


# ---------------------------------------------------------------------------
# Evidence binding (sol P1-a): header claims and rendered rows describe the
# SAME position. Supersedes the earlier "resolve the disclosure after the
# fetch" ordering, which narrowed the window but could not close it.
# ---------------------------------------------------------------------------


class TestReviewEvidenceBinding:
    @pytest.fixture
    def sealed_vertex(self, tmp_path):
        v = vertex("seal").store("./seal.db").loop("decision", fold_by("topic"))
        vpath = tmp_path / "seal.vertex"
        v.write(vpath)
        db = tmp_path / "seal.db"
        _empty_store(db)
        return vpath, db

    def test_cursor_matches_the_rows_under_concurrent_write(
        self, sealed_vertex, monkeypatch
    ):
        """A fact lands while the review is being taken. The header must
        describe the rows that were rendered — not a head that moved past them.

        Under the old ordering the header reported seq=2 / sealed_to_head=False
        for a fold containing only fact 1: a cursor advertising content the
        projection did not include. The fold is now PINNED to the resolved
        position, so the late write is outside both.
        """
        vpath, db = sealed_vertex
        f1 = _append(db, "decision", 100.0, topic="a", message="alpha")
        _append_tick(db, "seal", 150.0, fact_cursor=f1)
        # The store is now exactly sealed_to_head=True at head f1.

        import loops.commands.fetch as fetch_mod

        real = fetch_mod.fetch_fold

        def fetch_with_concurrent_write(*args, **kwargs):
            state = real(*args, **kwargs)
            _append(db, "decision", 200.0, topic="b", message="beta")
            return state

        monkeypatch.setattr(fetch_mod, "fetch_fold", fetch_with_concurrent_write)

        out = _review(vpath)
        header = out["review"]["header"]
        facts = out["review"]["facts"]

        # The late fact is in neither the rows nor the cursor — one moment,
        # described once.
        assert not any(f["key"] == "b" for f in facts)
        assert header["cursor"]["fact_id"] == f1
        assert header["cursor"]["seq"] == 1
        # And the seal claim is the one that was true AT that position.
        assert header["cut"]["sealed_to_head"] is True
        assert header["cut"]["facts_beyond_seal"] == 0

    def test_cursor_never_exceeds_the_rendered_rows(self, sealed_vertex):
        """The invariant behind the case above, stated directly: no rendered
        fact id may postdate the disclosed cursor, and the cursor must name a
        position the projection actually reached."""
        vpath, db = sealed_vertex
        f1 = _append(db, "decision", 100.0, topic="a", message="alpha")
        f2 = _append(db, "decision", 200.0, topic="b", message="beta")

        out = _review(vpath)
        header = out["review"]["header"]
        rendered = {f["id"] for f in out["review"]["facts"]}

        assert rendered == {f1, f2}
        assert header["cursor"]["fact_id"] == f2  # head == newest rendered
        assert max(rendered) <= header["cursor"]["fact_id"]

    def test_declaration_resolves_at_the_folded_position(self, sealed_vertex):
        """The fingerprint and decl_head come from the same position as the
        rows — the second half of the P1-a split (fingerprint D1 with
        decl_head D2)."""
        from engine import declaration_generation

        from loops.cli import witness_address

        vpath, db = sealed_vertex
        _append(db, "decision", 100.0, topic="a", message="alpha")

        out = _review(vpath)
        header = out["review"]["header"]
        position, _cursor, _cut = witness_address.resolve_review_head_position(vpath)
        expected = declaration_generation(vpath, at=position)

        assert header["declaration"]["review_fingerprint"] == expected[
            "review_fingerprint"]
        assert header["declaration"]["decl_head"] == expected["decl_head"]

    def test_evidence_object_carries_every_disclosed_field(self, sealed_vertex):
        """The renderer's header is a projection of ReviewEvidence and nothing
        else — the property Rule 10 enforces structurally."""
        from loops.cli.views.fold import ReviewEvidence

        vpath, db = sealed_vertex
        _append(db, "decision", 100.0, topic="a", message="alpha")

        out = _review(vpath)
        fields = {f.name for f in dataclasses.fields(ReviewEvidence)}
        for disclosed in out["review"]["header"]:
            assert disclosed in fields, (
                f"header key {disclosed!r} is not carried by ReviewEvidence — "
                "it must be captured with the rows, not resolved at render time"
            )


# ---------------------------------------------------------------------------
# Router / combo guards — honor-or-refuse
# ---------------------------------------------------------------------------


class TestGuards:
    @pytest.mark.parametrize(
        "argv",
        [
            # Different read / operation.
            ["--review", "--facts"],
            ["--review", "--why", "decision/auth"],
            ["--review", "--diff", "seq:1..seq:2"],
            ["--review", "--ticks"],
            # Reshaping Surface transforms / selectors / walk / lens.
            ["--review", "--lens", "graph"],
            ["--review", "--match", "auth"],
            ["--review", "--fields", "topic"],
            ["--review", "--limit", "5"],
            ["--review", "--count"],
            ["--review", "--by", "kind"],
            ["--review", "--refs", "2"],
            ["--review", "--full"],
            # Previously LEAKING flags the blacklist form silently ignored —
            # the drift the whitelist closes (arbiter capstone P2).
            ["--review", "--last", "5"],
            ["--review", "--all"],
            ["--review", "--edge", "ref"],
            # Delivery modes --review cannot honor.
            ["--review", "--live"],
            ["--review", "-i"],
            # Filtering predicates that ride in the positional bucket.
            ["--review", "status=open"],
            ["--review", "observer=kyle"],
        ],
    )
    def test_refused_combos(self, review_vertex, argv):
        vpath, _ = review_vertex
        rc, r = _run(vpath, argv)
        assert rc == 2
        assert "review" in r.err_text.lower()

    def test_all_refusal_teaches_redundancy(self, review_vertex):
        vpath, _ = review_vertex
        rc, r = _run(vpath, ["--review", "--all"])
        assert rc == 2
        assert "redundant" in r.err_text.lower()
        assert "always shows everything" in r.err_text.lower()

    def test_facts_since_routes_away_refused(self, review_vertex):
        vpath, _ = review_vertex
        rc, r = _run(vpath, ["--review", "--facts", "--since", "7d"])
        assert rc == 2
        assert "review" in r.err_text.lower()

    @pytest.mark.parametrize(
        "argv,expect_kinds",
        [
            (["--review", "--kind", "decision"], {"decision"}),
            (["--review", "--key", "auth"], {"decision"}),
        ],
    )
    def test_kind_and_key_still_honored(self, review_vertex, argv, expect_kinds):
        vpath, _ = review_vertex
        rc, r = _run(vpath, argv)
        assert rc == 0, r.err_text
        facts = json.loads(r.out_lines[0])["review"]["facts"]
        assert facts  # scoping narrowed, did not empty
        assert {f["kind"] for f in facts} == expect_kinds

    @pytest.mark.parametrize(
        "argv",
        [
            ["--review"],                       # bare
            ["--review", "--json"],             # review IS json — composes
            ["--review", "--plain"],            # display global — composes
            ["--review", "-q"],                 # zoom — composes (no reshape)
            ["--review", "-v"],
            ["--review", "--static"],           # review IS a static one-shot
            ["--review", "--at", "seq:2"],      # addressing — composes
            ["--review", "--as-of", "30d"],
            ["--review", "--kind", "decision", "--at", "seq:2"],  # combo
        ],
    )
    def test_compose_set_accepted(self, review_vertex, argv):
        vpath, _ = review_vertex
        rc, r = _run(vpath, argv)
        assert rc == 0, r.err_text
        assert "review" in json.loads(r.out_lines[0])

    def test_guard_is_whitelist_shaped_future_flag_refuses(self):
        """Anti-drift canary: a flag the compose-set has NEVER heard of refuses
        by default. If the guard ever reverts to a blacklist, this fails —
        the whitelist property itself is pinned, not a fixed flag list."""
        from loops.cli.views import fold

        parser = fold._build_parser()
        parser.add_argument("--future-thing", default=None)
        args = parser.parse_intermixed_args(
            ["v", "--review", "--future-thing", "x"]
        )
        bad = fold._review_incompatible_flag(
            args, parser, refs_depth=0, where={}, observer=None,
        )
        assert bad == "--future-thing"

    def test_clean_review_read_passes_the_guard(self):
        from loops.cli.views import fold

        parser = fold._build_parser()
        args = parser.parse_intermixed_args(
            ["v", "--review", "--kind", "decision", "--at", "seq:2", "--json"]
        )
        bad = fold._review_incompatible_flag(
            args, parser, refs_depth=0, where={}, observer=None,
        )
        assert bad is None


# ---------------------------------------------------------------------------
# Encoder unit — surface.to_review over a hand-built FoldState
# ---------------------------------------------------------------------------


def _state() -> FoldState:
    return FoldState(
        vertex="v",
        sections=(
            FoldSection(
                kind="decision",
                key_field="topic",
                fold_type="by",
                items=(
                    FoldItem(
                        payload={"topic": "b", "message": "beta"},
                        id="01ID_B", ts=2.0, observer="kyle", origin="", n=1,
                        refs=("thread:x", "decision:a"),
                        edges=(Edge(predicate="stakeholder", address="peer:z"),),
                    ),
                    FoldItem(
                        payload={"topic": "a", "message": "alpha"},
                        id="01ID_A", ts=1.0, observer="kyle", origin="", n=3,
                    ),
                ),
            ),
            FoldSection(
                kind="log",
                key_field=None,
                fold_type="collect",
                items=(
                    FoldItem(payload={"message": "one"}, id="01LOG_2", ts=5.0),
                    FoldItem(payload={"message": "two"}, id="01LOG_1", ts=6.0),
                ),
            ),
        ),
    )


class TestToReview:
    def test_sorted_by_kind_key_then_id(self):
        out = to_review(_state(), header={}, signatures={})
        seq = [(f["kind"], f["key"], f["id"]) for f in out["facts"]]
        assert seq == [
            ("decision", "a", "01ID_A"),
            ("decision", "b", "01ID_B"),
            ("log", None, "01LOG_1"),  # keyless: ordered by id
            ("log", None, "01LOG_2"),
        ]

    def test_keyed_key_is_the_fold_value(self):
        out = to_review(_state(), header={}, signatures={})
        a = next(f for f in out["facts"] if f["id"] == "01ID_A")
        assert a["key"] == "a"
        assert a["key_field"] == "topic"
        assert a["n"] == 3

    def test_keyless_key_is_none(self):
        out = to_review(_state(), header={}, signatures={})
        log = next(f for f in out["facts"] if f["kind"] == "log")
        assert log["key"] is None
        assert log["key_field"] is None

    def test_refs_and_edges_sorted(self):
        out = to_review(_state(), header={}, signatures={})
        b = next(f for f in out["facts"] if f["id"] == "01ID_B")
        assert b["refs"] == ["decision:a", "thread:x"]  # sorted
        assert b["edges"] == [{"predicate": "stakeholder", "address": "peer:z"}]

    def test_signatures_threaded_by_id(self):
        out = to_review(
            _state(), header={}, signatures={"01ID_A": "SIGA", "01ID_B": None},
        )
        a = next(f for f in out["facts"] if f["id"] == "01ID_A")
        b = next(f for f in out["facts"] if f["id"] == "01ID_B")
        log = next(f for f in out["facts"] if f["kind"] == "log")
        assert a["signature"] == "SIGA"
        assert b["signature"] is None
        assert log["signature"] is None  # id absent from map

    def test_whitelist_only(self):
        out = to_review(_state(), header={}, signatures={})
        forbidden = set(REVIEW_EXCLUDED_FIELDS)
        for row in out["facts"]:
            assert forbidden.isdisjoint(row.keys())

    def test_header_passthrough_and_version(self):
        out = to_review(_state(), header={"vertex": "v"}, signatures={})
        assert out["header"] == {"vertex": "v"}
        assert out["review_version"] == 1

    def test_byte_identical_across_two_encodes(self):
        h = {"vertex": "v", "cursor": None}
        a = to_review(_state(), header=h, signatures={"01ID_A": "s"})
        b = to_review(_state(), header=h, signatures={"01ID_A": "s"})
        assert json.dumps(a, sort_keys=True) == json.dumps(b, sort_keys=True)

    def test_payload_keys_sorted_and_nested_stable(self):
        state = FoldState(
            vertex="v",
            sections=(
                FoldSection(
                    kind="decision", key_field="topic", fold_type="by",
                    items=(
                        FoldItem(
                            payload={"topic": "z", "b": 1, "a": {"y": 2, "x": 1}},
                            id="01Z",
                        ),
                    ),
                ),
            ),
        )
        out = to_review(state, header={}, signatures={})
        blob = json.dumps(out, sort_keys=True)
        # sort_keys end-to-end: nested dict order is stable regardless of input.
        assert json.loads(blob)["facts"][0]["payload"]["a"] == {"x": 1, "y": 2}


def test_sha256_recipe_matches_engine(review_vertex):
    """The declaration fingerprint is sha256 over the canonical document
    projection — documented recipe, reproducible outside the engine."""
    from lang import parse_vertex_file
    from lang.document import vertex_to_documents

    vpath, _ = review_vertex
    ast = parse_vertex_file(vpath)
    canonical = json.dumps(
        [d.as_json() for d in vertex_to_documents(ast)],
        sort_keys=True, separators=(",", ":"),
    )
    expected = "sha256:" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    assert declaration_generation(vpath)["review_fingerprint"] == expected
