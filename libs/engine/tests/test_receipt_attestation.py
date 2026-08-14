"""Write-receipt attestation — persisted signature state on Receipt (S4).

Contract (LIBS_CHANGES P1, write-receipt-vs-temporal-query): the receipt's
attestation is populated FROM THE COMMITTED ROW, never from "keys exist
locally" inference. A per-observer signer returning None must surface as
signed=False even when signing is configured; conversely two observers under
the SAME configuration must get different attestations when the committed
rows differ — the case that kills any config-inference implementation.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from atoms import Fact
from engine import FactAttestation, SqliteStore, TickAttestation, Vertex
from engine.jsonl_store import JsonlStore


def _fake_signer_for(signing_observers: set[str]):
    """A per-observer fact signer: signs only the named observers.

    Deterministic fake scheme — signature is 'sig:' + digest, verifiable by
    the matching fake verifier below. Configuration-wise, signing IS
    configured for every observer (the callable exists); the per-observer
    None return is the honesty case the contract names.
    """

    def signer(observer: str, digest: str) -> str | None:
        if observer in signing_observers:
            return f"sig:{digest}"
        return None

    return signer


def _fake_verifier(observer: str, signature: str, digest: str) -> bool:
    return signature == f"sig:{digest}"


def _store(tmp_path: Path, canonical: str, **kw):
    ser = lambda f: f.to_dict()  # noqa: E731
    if canonical == "jsonl":
        return JsonlStore(
            path=tmp_path / "v.db", log_path=tmp_path / "v.jsonl",
            serialize=ser, deserialize=Fact.from_dict, **kw,
        )
    return SqliteStore(
        path=tmp_path / "v.db", serialize=ser,
        deserialize=Fact.from_dict, **kw,
    )


def _vertex(store) -> Vertex:
    v = Vertex("t", store=store)
    v.register("note", {}, lambda s, p: {**s, **p})
    return v


@pytest.fixture(params=["sqlite", "jsonl"])
def canonical(request):
    return request.param


class TestFactAttestation:
    def test_signed_store_signing_observer_signed_true_and_row_verifies(
        self, tmp_path, canonical,
    ):
        """Oracle 1: signed=True AND the committed row verifies via the
        verify machinery — cross-checked, not the receipt's own claim."""
        store = _store(tmp_path, canonical,
                       fact_signer=_fake_signer_for({"alice"}))
        v = _vertex(store)
        receipt = v.receive_receipt(Fact.of("note", "alice", n=1))

        assert receipt.stored
        assert receipt.attestation == FactAttestation(
            signed=True, observer="alice"
        )
        report = store.verify_facts(verifier=_fake_verifier)
        assert report["ok"] is True
        assert report["signed"] == 1
        assert report["sig_checked"] is True

    def test_configured_but_none_signer_is_signed_false(
        self, tmp_path, canonical,
    ):
        """Oracle 2 + 5 (mutation check): signing is CONFIGURED (the signer
        callable is wired) but returns None for bob — the committed row is
        unsigned and the receipt must say so. In the same store alice's row
        IS signed under identical configuration: any implementation reading
        configuration instead of the committed row returns the same answer
        for both observers and fails one of these assertions."""
        store = _store(tmp_path, canonical,
                       fact_signer=_fake_signer_for({"alice"}))
        v = _vertex(store)

        r_alice = v.receive_receipt(Fact.of("note", "alice", n=1))
        r_bob = v.receive_receipt(Fact.of("note", "bob", n=2))

        assert r_alice.attestation.signed is True
        assert r_bob.attestation == FactAttestation(
            signed=False, observer="bob"
        )
        # The committed rows agree — attestation mirrors the store, both ways.
        assert store.fact_signature(r_alice.fact_id) is not None
        assert store.fact_signature(r_bob.fact_id) is None

    def test_unsigned_store_signed_false(self, tmp_path, canonical):
        """Oracle 3: no signer at all → committed row unsigned → signed=False
        (a positive claim from the row, distinct from attestation=None)."""
        store = _store(tmp_path, canonical)
        v = _vertex(store)
        receipt = v.receive_receipt(Fact.of("note", "alice", n=1))
        assert receipt.attestation == FactAttestation(
            signed=False, observer="alice"
        )

    def test_storeless_vertex_attestation_is_none(self):
        """Tri-state: no store → attestation None (unknown), never a claim."""
        v = Vertex("t")
        v.register("note", {}, lambda s, p: {**s, **p})
        receipt = v.receive_receipt(Fact.of("note", "alice", n=1))
        assert receipt.attestation is None
        assert receipt.tick_attestation is None

    def test_gate_rejection_attestation_is_none(self, tmp_path, canonical):
        """Rejected write commits nothing — nothing to attest."""
        from engine import Grant

        store = _store(tmp_path, canonical)
        v = _vertex(store)
        receipt = v.receive_receipt(
            Fact.of("note", "alice", n=1),
            Grant(potential=frozenset({"other"})),
        )
        assert receipt.stored is False
        assert receipt.attestation is None


class TestTickAttestation:
    def _boundary_vertex(self, store) -> Vertex:
        v = Vertex("t", store=store)
        v.register(
            "note", {}, lambda s, p: {**s, **p}, boundary="note.close",
        )
        return v

    def test_tick_fired_receive_exposes_committed_tick_attestation(
        self, tmp_path, canonical,
    ):
        """Oracle 4: a receive that fires a boundary reports the committed
        tick row's signature/chain state."""
        store = _store(
            tmp_path, canonical,
            fact_signer=_fake_signer_for({"alice"}),
            tick_signer=lambda digest: f"sig:{digest}",
        )
        v = self._boundary_vertex(store)
        v.receive_receipt(Fact.of("note", "alice", n=1))
        receipt = v.receive_receipt(Fact.of("note.close", "alice"))

        assert receipt.tick is not None
        assert receipt.tick_attestation == TickAttestation(
            signed=True, chained=True,
        )
        # Cross-check against the verify machinery walking committed rows.
        report = store.verify_chain(
            verifier=lambda sig, digest: sig == f"sig:{digest}",
        )
        assert report["ok"] is True
        assert report["signed"] == 1

    def test_unsigned_tick_reports_signed_false(self, tmp_path, canonical):
        """No tick signer → committed tick row unsigned → honest False
        (floor not tripped: the store has no prior signed tick)."""
        store = _store(tmp_path, canonical)
        v = self._boundary_vertex(store)
        v.receive_receipt(Fact.of("note", "alice", n=1))
        receipt = v.receive_receipt(Fact.of("note.close", "alice"))

        assert receipt.tick is not None
        assert receipt.tick_attestation == TickAttestation(
            signed=False, chained=True,
        )

    def test_no_tick_no_tick_attestation(self, tmp_path, canonical):
        store = _store(tmp_path, canonical)
        v = self._boundary_vertex(store)
        receipt = v.receive_receipt(Fact.of("note", "alice", n=1))
        assert receipt.tick is None
        assert receipt.tick_attestation is None


# ---------------------------------------------------------------------------
# SOL-R4-02 / SOL-R4-03 — committed-row EXISTENCE honesty
# ---------------------------------------------------------------------------


class TestCommittedRowExistence:
    """SOL-R4-02: read-back must distinguish row-with-NULL-signature from
    ROW ABSENT. A store that eats the row (AFTER INSERT delete trigger)
    must roll back and raise a typed refusal — never mint a stored=True
    receipt for no committed row. Facts AND ticks, sqlite AND jsonl."""

    @staticmethod
    def _delete_trigger(store, table: str):
        store._conn.execute(
            f"CREATE TRIGGER eat_{table} AFTER INSERT ON {table} "
            f"BEGIN DELETE FROM {table} WHERE id = NEW.id; END"
        )

    def test_fact_delete_trigger_refuses_typed(self, tmp_path, canonical):
        from engine.sqlite_store import CommittedRowMissing

        store = _store(tmp_path, canonical)
        self._delete_trigger(store, "facts")
        with pytest.raises(CommittedRowMissing):
            store.append_attested(Fact.of("note", "kyle", n=1))
        count = store._conn.execute("SELECT COUNT(*) FROM facts").fetchone()[0]
        assert count == 0
        if canonical == "jsonl":
            # Refusal before any log byte — the canonical log is untouched.
            assert not (tmp_path / "v.jsonl").exists() or (
                tmp_path / "v.jsonl"
            ).stat().st_size == 0
        store.close()

    def test_tick_delete_trigger_refuses_typed(self, tmp_path, canonical):
        from datetime import datetime, timezone

        from engine import Tick
        from engine.sqlite_store import CommittedRowMissing

        store = _store(tmp_path, canonical)
        self._delete_trigger(store, "ticks")
        tick = Tick(
            name="t", ts=datetime.now(timezone.utc), payload={}, origin="v"
        )
        with pytest.raises(CommittedRowMissing):
            store.append_tick(tick)
        count = store._conn.execute("SELECT COUNT(*) FROM ticks").fetchone()[0]
        assert count == 0
        if canonical == "jsonl":
            assert not (tmp_path / "v.jsonl").exists() or (
                tmp_path / "v.jsonl"
            ).stat().st_size == 0
        store.close()

    def test_store_still_usable_after_refusal(self, tmp_path, canonical):
        from engine.sqlite_store import CommittedRowMissing

        store = _store(tmp_path, canonical)
        self._delete_trigger(store, "facts")
        with pytest.raises(CommittedRowMissing):
            store.append_attested(Fact.of("note", "kyle", n=1))
        store._conn.execute("DROP TRIGGER eat_facts")
        fact_id, sig = store.append_attested(Fact.of("note", "kyle", n=2))
        assert store.fact_signature(fact_id) is None is sig
        store.close()


class TestJsonlLogDerivesFromCommittedIndex:
    """SOL-R4-03: the JSONL log must serialize the COMMITTED index row —
    a trigger-mutated row may not diverge from what enters the log."""

    def test_signature_nulling_trigger_log_matches_index(self, tmp_path):
        import json as _json

        from engine.canonical_audit import audit_agreement

        store = _store(tmp_path, "jsonl")
        store._ensure_fact_signature_column()
        store._conn.execute(
            "CREATE TRIGGER strip_sig AFTER INSERT ON facts "
            "BEGIN UPDATE facts SET signature = NULL WHERE id = NEW.id; END"
        )
        fact_id, committed = store.append_attested(
            Fact.of("note", "kyle", n=1), signature_override="sig:forced"
        )
        # Receipt reports the committed row (already true since R3)...
        assert committed is None
        assert store.fact_signature(fact_id) is None
        # ...and the canonical log now derive-matches the index: the line
        # carries no signature either (codec: absent, not null).
        last = (tmp_path / "v.jsonl").read_text().splitlines()[-1]
        assert _json.loads(last).get("signature") is None
        store.close()
        report = audit_agreement(tmp_path / "v.jsonl")
        assert report.ok, report

    def test_untriggered_append_still_logs_signature(self, tmp_path):
        import json as _json

        from engine.canonical_audit import audit_agreement

        store = _store(
            tmp_path, "jsonl", fact_signer=_fake_signer_for({"kyle"})
        )
        fact_id, committed = store.append_attested(Fact.of("note", "kyle", n=1))
        assert committed is not None
        last = (tmp_path / "v.jsonl").read_text().splitlines()[-1]
        assert _json.loads(last)["signature"] == committed
        store.close()
        assert audit_agreement(tmp_path / "v.jsonl").ok
