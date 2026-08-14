"""CLI-level tests for ``read --why`` — the provenance drill flag.

Covers the exact-address gate (errors with guidance), the end-to-end
attribution through the full dispatch (asserted via --json), the collect-fold
degrade, and register parity of the why lens.

Anchors: decision/design/provenance-why-build1-scope.
"""
from __future__ import annotations

import argparse
import json

import pytest
from painted import Zoom

from engine.builder import fold_by, fold_collect, vertex
from loops.lenses.provenance import why_view
from loops.main import cmd_emit, main
from loops.provenance import replay_attribution

from .parity import assert_register_parity


@pytest.fixture
def why_vertex(tmp_path):
    v = (
        vertex("why")
        .store("./w.db")
        .loop("decision", fold_by("topic"))
        .loop("cite", fold_collect())
    )
    vpath = tmp_path / "why.vertex"
    v.write(vpath)
    with open(vpath, "a") as f:
        f.write("\nobservers {\n  alice { }\n  bob { }\n}\n")
    return vpath


def _emit(vpath, kind, *, observer="alice", **payload):
    parts = [f"{k}={v}" for k, v in payload.items()]
    ns = argparse.Namespace(
        vertex=None, kind=kind, parts=parts, observer=observer, dry_run=False,
    )
    return cmd_emit(ns, vertex_path=vpath)


def _seed(vpath):
    # design/a folded over three emits by two observers: status open→review→open,
    # message set once (persists), label set then cleared.
    assert _emit(vpath, "decision", topic="design/a", message="body",
                 status="open", label="draft") == 0
    assert _emit(vpath, "decision", topic="design/a", status="review",
                 observer="bob") == 0
    assert _emit(vpath, "decision", topic="design/a", status="open", label="") == 0
    # a second key + a collect kind for the degrade path. The cites carry a
    # resolvable ref: a zero-address cite refuses since r1 remediation
    # (finding:chw-s4-raw-emit-empty-cite).
    assert _emit(vpath, "decision", topic="design/b", message="beta") == 0
    assert _emit(vpath, "cite", context="c1", ref="decision/design/a") == 0
    assert _emit(vpath, "cite", context="c2", ref="decision/design/a",
                 observer="bob") == 0


def _why_json(capsys, vpath, *argv):
    capsys.readouterr()
    rc = main(["read", str(vpath), *argv, "--why", "--json"])
    out = capsys.readouterr().out
    return rc, json.loads(out)


class TestNativeNumericKeyWhy:
    """finding:chw-sol-r5-provenance-key-lookup (arbiter: unify the
    stringification only). A native JSON numeric ``0`` fold key keys the
    replayed fold STATE by int ``0`` while the CLI address carries ``"0"``
    — the provenance lookup missed the entry and ``--why`` answered exit 0
    with ``fields: []``. The shared projection (``loops.foldkey``) now
    meets it. Engine fold semantics untouched; native-vs-string identity
    is deliberately held at thread:fold-key-identity-native-vs-string."""

    @pytest.fixture
    def zero_why_vertex(self, tmp_path):
        from .builders import StorePopulator

        v = (
            vertex("zerowhy")
            .store("./zw.db")
            .loop("decision", fold_by("topic"))
        )
        vpath = tmp_path / "zerowhy.vertex"
        v.write(vpath)
        (
            StorePopulator(tmp_path / "zw.db", observer="alice")
            .emit("decision", topic=0, status="open", message="zero body")
            .emit("decision", topic=0, status="resolved")
            .done()
        )
        return vpath

    def test_why_on_native_zero_key_attributes_fields(
        self, zero_why_vertex, capsys,
    ):
        # Sol's reproduction, inverted: fields and attribution come back.
        rc, d = _why_json(capsys, zero_why_vertex, "decision/0")
        assert rc == 0
        assert d["mode"] == "upsert"
        assert d["total_facts"] == 2
        fields = {f["field"]: f for f in d["fields"]}
        assert fields  # the defect answered fields: [] here
        assert fields["message"]["value"] == "zero body"
        assert fields["status"]["value"] == "resolved"
        # supersession history survives the projection too
        assert [p["value"] for p in fields["status"]["priors"]] == ["open"]
        assert fields["status"]["setter"]["index"] == 2


class TestMergedIdentityReplay:
    """decision:design/fold-key-string-projection (supersedes the r6 tie
    rule finding:chw-sol-r6-f1-replay-identity-switch): a fold key's
    identity is its string projection, applied by the ENGINE at the fold
    boundary. Native ``0`` and string ``"0"`` are therefore ONE entry —
    there is no winning/losing item and no tie to resolve. Every fact
    projecting to the address contributes; per-field last-write-wins, so
    emission order legitimately shapes values and prior chains. Contract
    unchanged: --why explains exactly the row read renders."""

    def _vertex_with(self, tmp_path, emit_order):
        from .builders import StorePopulator

        tmp_path.mkdir(parents=True, exist_ok=True)
        v = (
            vertex("dual")
            .store("./d.db")
            .loop("decision", fold_by("topic"))
        )
        vpath = tmp_path / "dual.vertex"
        v.write(vpath)
        pop = StorePopulator(tmp_path / "d.db", observer="alice")
        for which in emit_order:
            if which == "native":
                pop.emit(
                    "decision", topic=0,
                    status="native-open", native_only="N",
                )
            else:
                pop.emit("decision", topic="0", status="s-open",
                         message="string body")
                pop.emit("decision", topic="0", status="s-done")
        pop.done()
        return vpath

    def _why(self, capsys, vpath):
        rc, d = _why_json(capsys, vpath, "decision/0")
        assert rc == 0
        return d

    def test_native_and_string_fold_into_one_entry_all_facts_attributed(
        self, tmp_path, capsys,
    ):
        d = self._why(capsys, self._vertex_with(tmp_path, ("native", "string")))
        # All three facts fold into the single string-projected entry.
        assert d["total_facts"] == 3
        fields = {f["field"]: f for f in d["fields"]}
        # Both items' fields coexist on the merged entry...
        assert fields["native_only"]["value"] == "N"
        assert fields["message"]["value"] == "string body"
        # ...and the shared field carries the full supersession chain.
        assert fields["status"]["value"] == "s-done"
        assert [p["value"] for p in fields["status"]["priors"]] == [
            "s-open", "native-open",
        ]

    def test_last_write_wins_follows_emission_order(self, tmp_path, capsys):
        d = self._why(capsys, self._vertex_with(tmp_path, ("string", "native")))
        assert d["total_facts"] == 3
        fields = {f["field"]: f for f in d["fields"]}
        # Reversed order, reversed outcome for the shared field — order is
        # semantic under last-write-wins, not an attribution defect.
        assert fields["status"]["value"] == "native-open"
        assert [p["value"] for p in fields["status"]["priors"]] == [
            "s-done", "s-open",
        ]
        # Fields only one item carries are order-independent.
        assert fields["native_only"]["value"] == "N"
        assert fields["message"]["value"] == "string body"


# --- Exact-address gate ----------------------------------------------------


class TestAddressGate:
    def test_no_address_errors(self, why_vertex, capsys):
        _seed(why_vertex)
        capsys.readouterr()
        rc = main(["read", str(why_vertex), "--why"])
        err = capsys.readouterr().err
        assert rc == 2
        assert "exact kind/key address" in err

    def test_bare_kind_errors(self, why_vertex, capsys):
        _seed(why_vertex)
        capsys.readouterr()
        rc = main(["read", str(why_vertex), "--kind", "decision", "--why"])
        assert rc == 2
        assert "exact kind/key address" in capsys.readouterr().err

    def test_prefix_key_errors(self, why_vertex, capsys):
        _seed(why_vertex)
        capsys.readouterr()
        rc = main(["read", str(why_vertex), "--kind", "decision",
                   "--key", "design/", "--why"])
        err = capsys.readouterr().err
        assert rc == 2
        assert "EXACT fold key" in err

    def test_comma_or_key_errors(self, why_vertex, capsys):
        _seed(why_vertex)
        capsys.readouterr()
        rc = main(["read", str(why_vertex), "--kind", "decision",
                   "--key", "design/a,design/b", "--why"])
        assert rc == 2
        assert "exact kind/key address" in capsys.readouterr().err


# --- End-to-end attribution via --json -------------------------------------


class TestAttributionJson:
    def test_upsert_attribution_shape(self, why_vertex, capsys):
        _seed(why_vertex)
        rc, d = _why_json(capsys, why_vertex, "decision/design/a")
        assert rc == 0
        assert d["mode"] == "upsert"
        assert d["kind"] == "decision" and d["key"] == "design/a"
        assert d["total_facts"] == 3
        fields = {f["field"]: f for f in d["fields"]}
        # status: open→review→open — current from fact 3, history newest-first.
        assert fields["status"]["value"] == "open"
        assert fields["status"]["setter"]["index"] == 3
        assert [p["value"] for p in fields["status"]["priors"]] == ["review", "open"]
        # message persisted from fact 1 (never re-supplied under merge).
        assert fields["message"]["value"] == "body"
        assert fields["message"]["setter"]["index"] == 1
        # label cleared to "" by fact 3's sentinel.
        assert fields["label"]["value"] == ""
        assert fields["label"]["setter"]["index"] == 3

    def test_observers_carried(self, why_vertex, capsys):
        _seed(why_vertex)
        _, d = _why_json(capsys, why_vertex, "decision/design/a")
        assert set(d["observers"]) == {"alice", "bob"}
        fields = {f["field"]: f for f in d["fields"]}
        assert fields["status"]["priors"][0]["setter"]["observer"] == "bob"  # review

    def test_collect_degrade(self, why_vertex, capsys):
        _seed(why_vertex)
        rc, d = _why_json(capsys, why_vertex, "cite/any")
        assert rc == 0
        assert d["mode"] == "collect"
        assert d["fields"] == []
        assert d["total_facts"] == 2
        assert [f["context"] for f in d["facts"]] == ["c1", "c2"]

    def test_missing_key_is_empty(self, why_vertex, capsys):
        _seed(why_vertex)
        rc, d = _why_json(capsys, why_vertex, "decision/design/nope")
        assert rc == 0
        assert d["mode"] == "empty"
        assert d["total_facts"] == 0


# --- Register parity of the why lens ---------------------------------------


def _prov_fixture():
    facts = [
        {"_ts": 1736850000.0, "_observer": "alice", "topic": "design/a",
         "message": "body", "status": "open"},
        {"_ts": 1736853600.0, "_observer": "bob", "topic": "design/a",
         "status": "review"},
        {"_ts": 1736942400.0, "_observer": "alice", "topic": "design/a",
         "status": "open"},
    ]
    from atoms.fold import Upsert

    return replay_attribution(
        Upsert(target="s", key="topic"), facts,
        kind="decision", key="design/a", key_field="topic",
    )


def test_narrow_tty_wraps_long_value_no_dropped_tail():
    # Review finding 1: a long field value must WRAP into a hanging block on a
    # narrow TTY, never hard-clip mid-token. The whole value survives across
    # lines and no rendered line exceeds the width.
    from atoms.fold import Upsert

    from .helpers import block_to_text

    long_msg = (
        "this is a deliberately long decision body that exceeds a narrow "
        "terminal width so it must wrap across multiple hanging-indented lines "
        "instead of clipping its tail off the right edge unicorn-sentinel-tail"
    )
    facts = [{"_ts": 1736850000.0, "_observer": "alice", "topic": "design/a",
              "message": long_msg}]
    prov = replay_attribution(
        Upsert(target="s", key="topic"), facts,
        kind="decision", key="design/a", key_field="topic",
    )
    width = 48
    text = block_to_text(why_view(prov, Zoom.SUMMARY, width),
                         use_ansi=False)
    lines = text.splitlines()
    assert all(len(ln) <= width for ln in lines), "a line overflowed the width"
    # Every word of the value survives (the tail sentinel especially).
    collapsed = " ".join(text.split())
    for word in long_msg.split():
        assert word in collapsed, f"dropped word: {word}"
    assert "unicorn-sentinel-tail" in collapsed


def test_piped_why_keeps_long_value_on_one_line():
    # The agent channel is information-faithful and never wraps — width=None.
    from atoms.fold import Upsert

    from .helpers import block_to_text

    long_msg = "x" * 200 + " endtail"
    facts = [{"_ts": 1736850000.0, "_observer": "alice", "topic": "design/a",
              "message": long_msg}]
    prov = replay_attribution(
        Upsert(target="s", key="topic"), facts,
        kind="decision", key="design/a", key_field="topic",
    )
    text = block_to_text(why_view(prov, Zoom.SUMMARY, None),
                         use_ansi=False)
    # The value line is not wrapped: message value + attribution on one line.
    msg_line = next(ln for ln in text.splitlines() if "message =" in ln)
    assert "endtail" in msg_line
    assert "fact 1/1" in msg_line


def test_why_register_parity():
    prov = _prov_fixture()
    # load-bearing: address, counts, both observers, the current field values.
    assert_register_parity(
        why_view, prov,
        load_bearing=["design/a", "decision", "3 facts", "alice", "bob",
                      "review", "body"],
        zoom=Zoom.DETAILED,
    )


def test_why_trace_register_parity():
    # P2: the -v chronological trace content — changed fields, the status
    # transition value, and the fold-depth counter (×n = facts folded so far,
    # the spine-wide meaning) — must land on BOTH registers (connector chrome
    # may differ, the trace information may not).
    prov = _prov_fixture()
    assert_register_parity(
        why_view, prov,
        load_bearing=["alice", "bob", "message", "status→review", "×2"],
        zoom=Zoom.DETAILED,
    )


class TestCaseVariantKey:
    def test_case_variant_key_still_attributes_fields(self, why_vertex, capsys):
        """Regression: the case-folded source-facts fallback found the facts,
        but replay ran under the user's variant key and attributed ZERO
        fields. The canonical key must drive the replay too."""
        assert _emit(why_vertex, "decision", topic="Design/Mixed",
                     message="cased body", status="open") == 0
        rc, d = _why_json(capsys, why_vertex, "decision/design/mixed")
        assert rc == 0
        assert d["key"] == "Design/Mixed"  # canonicalized
        assert d["total_facts"] == 1
        fields = {f["field"]: f for f in d["fields"]}
        assert fields["message"]["value"] == "cased body"
        assert fields["status"]["value"] == "open"


def test_why_view_degenerate_width_does_not_crash(why_vertex, capsys):
    """Regression: why_view(width=0) crashed in wrap_hanging via
    textwrap.wrap(text, 0). Only None is unbounded; degenerate concrete
    widths clamp instead of raising."""
    from loops.provenance import replay_attribution
    from atoms.fold import Upsert

    facts = [{"topic": "design/w", "message": "m", "ts": 0, "observer": "o"}]
    prov = replay_attribution(
        Upsert(target="s", key="topic"), facts, kind="decision", key="design/w",
        key_field="topic",
    )
    for w in (0, 1, 5):
        assert why_view(prov, Zoom.SUMMARY, w) is not None
