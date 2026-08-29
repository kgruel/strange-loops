"""Opt-in admission verification — slice D §D4, arm 1 as redesigned.

The claim under test, exactly as the design states it: **every ADMITTED
signed fact row's authorship claim verifies under the SOURCE's own key
history.** Source self-consistency, not target-operator trust.

Everything here turns on the word *admitted*. Merge dedups before it
appends, so the set the claim is about is the post-dedup remainder — which
is why G-D4-1 and G-D4-2 are the same shape with the dedup flipped, and why
G-D4-4 exists beside G-D4-2: paired, they pin the SELECTIVE boundary
(``key_registry`` verifies registry-forming envelopes and no others) from
both sides.

The signer kit is keyed, unlike ``conftest``'s ``stub_sign`` — the whole
subject is which KEY a signature verifies under, and a key-blind stand-in
cannot express a forgery. Deterministic, still no crypto dependency: the
library takes an injected ``Verify`` and never imports one.
"""

from __future__ import annotations

import base64
import hashlib
import json
import sqlite3
from pathlib import Path

import pytest
from engine.arrival import KEY_INTRODUCTION_KIND, ArrivalLog
from engine.arrival_store import ensure_arrival_index
from engine.sqlite_store import fact_commitment_hash

from store.merge import AdmissionUnverified, merge_store

_TS = 1700000000.0


# --- the keyed stub kit -------------------------------------------------------


def key_of(name: str) -> str:
    """A shape-valid raw-32-byte base64 key, one per name."""
    return base64.b64encode(name.encode().ljust(32, b".")).decode()


def sign_with(key: str, digest: str) -> str:
    return "sig:" + hashlib.sha256(f"{key}/{digest}".encode()).hexdigest()


def signer_holding(key: str):
    """The injected signer shape ``ArrivalLog`` takes: ``(observer, digest)``."""
    return lambda _observer, digest: sign_with(key, digest)


def verify(key: str, signature: str, digest: str) -> bool:
    """The injected ``Verify`` shape: ``(key, signature, digest) -> bool``."""
    return signature == sign_with(key, digest)


KYLE = key_of("kyle")
ANA = key_of("ana")
MALLORY = key_of("mallory")


# --- fixtures the gates build sources out of ----------------------------------


def fact_body(ident, message, *, observer="kyle", signed_by=None, ts=_TS):
    """One fact record body, its CARRIED signature computed if asked for.

    ``signed_by`` is the key the authorship claim is made with — the live
    emit path's commitment, so a real key produces a claim that verifies and
    a foreign one produces a forgery indistinguishable in shape.
    """
    payload = json.dumps({"message": message})
    body = {
        "id": ident,
        "kind": "note",
        "ts": ts,
        "observer": observer,
        "origin": "",
        "payload": payload,
    }
    if signed_by is not None:
        body["signature"] = sign_with(
            signed_by, fact_commitment_hash("note", ts, observer, "", payload)
        )
    return body


def minted(tmp_path, name, *, observer="kyle", key=KYLE) -> ArrivalLog:
    return ArrivalLog.mint(
        tmp_path / f"{name}.arrival",
        observer=observer,
        signer=signer_holding(key),
        key=key,
    )


def indexed(log: ArrivalLog, tmp_path, name) -> Path:
    ensure_arrival_index(log.path)
    return tmp_path / f"{name}.db"


def arrival_source(tmp_path, name, facts=(), *, envelope_key=None):
    """A minted, indexed arrival store holding ``facts`` as fact records."""
    log = minted(tmp_path, name)
    for body in facts:
        log.append(
            "fact",
            body,
            observer=body["observer"],
            at=body["ts"],
            signer=None if envelope_key is None else signer_holding(envelope_key),
        )
    return log, indexed(log, tmp_path, name)


def ids(db) -> list[str]:
    conn = sqlite3.connect(str(db))
    try:
        return sorted(r[0] for r in conn.execute("SELECT id FROM facts"))
    finally:
        conn.close()


def records(log_path):
    return list(ArrivalLog(log_path).walk())


def assert_whole_log_verifier_refuses(log: ArrivalLog) -> None:
    """The fixture really does carry a bad ordinary envelope.

    Without this, a G-D4-2 case would pass for the wrong reason — a merge
    that succeeds over an envelope that was fine all along proves nothing
    about selectivity. ``verify_authorship`` is the verb that DOES verify
    every envelope, so its refusal is the independent witness that the
    envelope ``key_registry`` skipped is genuinely unverifiable.
    """
    from engine.arrival import AuthorshipUnverified, verify_authorship

    with pytest.raises(AuthorshipUnverified):
        verify_authorship(log, verify)


# --- G-D4-1 — a forged carried signature on an ADMITTED row refuses -----------


class TestForgedCarriedSignature:
    def test_an_admitted_row_signed_by_a_foreign_key_refuses(self, tmp_path):
        """G-D4-1. The row is admitted, so its claim is in scope; the claim
        does not verify under any key the source's log made valid for its
        observer; the merge refuses and appends nothing."""
        _, target_db = arrival_source(tmp_path, "t")
        _, source_db = arrival_source(
            tmp_path, "s", facts=[fact_body("01FORGED", "x", signed_by=MALLORY)]
        )
        before = records(tmp_path / "t.arrival")

        with pytest.raises(AdmissionUnverified, match="01FORGED") as exc:
            merge_store(target_db, source_db, verify=verify)

        assert "source self-consistency" in str(exc.value)
        assert records(tmp_path / "t.arrival") == before
        assert ids(target_db) == []

    def test_the_same_row_signed_by_the_logs_own_key_admits(self, tmp_path):
        """The discriminating half: identical fixture, real signature."""
        _, target_db = arrival_source(tmp_path, "t")
        _, source_db = arrival_source(
            tmp_path, "s", facts=[fact_body("01REAL", "x", signed_by=KYLE)]
        )

        result = merge_store(target_db, source_db, verify=verify)

        assert result.facts_added == 1
        assert ids(target_db) == ["01REAL"]

    def test_the_same_forgery_admits_when_no_verifier_is_passed(self, tmp_path):
        """The parameter is OPT-IN, and this is what that costs: without it
        the forgery enters, exactly as every merge before this cut."""
        _, target_db = arrival_source(tmp_path, "t")
        _, source_db = arrival_source(
            tmp_path, "s", facts=[fact_body("01FORGED", "x", signed_by=MALLORY)]
        )

        assert merge_store(target_db, source_db).facts_added == 1
        assert ids(target_db) == ["01FORGED"]

    def test_a_key_introduced_only_LATER_does_not_verify_the_row(self, tmp_path):
        """The placement clause reaches carried signatures too: ana's key is
        introduced at ordinal 2, so a row that arrived at ordinal 1 claiming
        it is unverified — validity is strictly-after, everywhere."""
        _, target_db = arrival_source(tmp_path, "t")
        log = minted(tmp_path, "s")
        body = fact_body("01EARLY", "x", observer="ana", signed_by=ANA)
        log.append("fact", body, observer="ana", at=body["ts"])  # ordinal 1
        log.append(
            KEY_INTRODUCTION_KIND,
            {"observer": "ana", "key": ANA},
            observer="kyle",
            signer=signer_holding(KYLE),
        )  # ordinal 2
        source_db = indexed(log, tmp_path, "s")

        with pytest.raises(AdmissionUnverified, match="01EARLY"):
            merge_store(target_db, source_db, verify=verify)

    def test_a_row_verified_by_an_introduced_key_admits(self, tmp_path):
        """The same fixture in the legal order: introduce, then speak."""
        _, target_db = arrival_source(tmp_path, "t")
        log = minted(tmp_path, "s")
        log.append(
            KEY_INTRODUCTION_KIND,
            {"observer": "ana", "key": ANA},
            observer="kyle",
            signer=signer_holding(KYLE),
        )  # ordinal 1
        body = fact_body("01LATE", "x", observer="ana", signed_by=ANA)
        log.append("fact", body, observer="ana", at=body["ts"])  # ordinal 2
        source_db = indexed(log, tmp_path, "s")

        assert merge_store(target_db, source_db, verify=verify).facts_added == 1
        assert ids(target_db) == ["01LATE"]

    def test_a_key_valid_for_ANOTHER_observer_does_not_verify_the_row(
        self, tmp_path
    ):
        """Keys are bound to observers: ana's real key, a row claiming to be
        kyle's. The signature is real; the authorship is not."""
        _, target_db = arrival_source(tmp_path, "t")
        log = minted(tmp_path, "s")
        log.append(
            KEY_INTRODUCTION_KIND,
            {"observer": "ana", "key": ANA},
            observer="kyle",
            signer=signer_holding(KYLE),
        )
        body = fact_body("01WRONGOBS", "x", observer="kyle", signed_by=ANA)
        log.append("fact", body, observer="kyle", at=body["ts"])
        source_db = indexed(log, tmp_path, "s")

        with pytest.raises(AdmissionUnverified, match="01WRONGOBS"):
            merge_store(target_db, source_db, verify=verify)


# --- G-D4-2 — a bad envelope on a DEDUPLICATED record does not refuse ---------


class TestVerificationCoversExactlyTheAdmissionSet:
    def test_a_bad_envelope_on_an_all_deduped_record_still_merges(self, tmp_path):
        """G-D4-2. The source's second record has an envelope signature no
        key verifies AND a forged carried signature — and every row it
        carries is already in the target, so it is admitted by nothing. The
        merge succeeds on the rows that ARE admitted.

        This is what the selective walk buys: a whole-log verifier would
        refuse here, over a record this merge does not admit.
        """
        held = fact_body("01HELD", "held", signed_by=MALLORY)
        _, target_db = arrival_source(tmp_path, "t", facts=[held])

        log = minted(tmp_path, "s")
        fresh = fact_body("01FRESH", "fresh", signed_by=KYLE)
        log.append("fact", fresh, observer="kyle", at=fresh["ts"])
        # Same bytes the target holds (so it dedups), riding under an
        # envelope signed by a key valid for nobody.
        log.append(
            "fact",
            held,
            observer="kyle",
            at=held["ts"],
            signer=signer_holding(MALLORY),
        )
        source_db = indexed(log, tmp_path, "s")
        assert_whole_log_verifier_refuses(log)

        result = merge_store(target_db, source_db, verify=verify)

        assert (result.facts_added, result.facts_skipped) == (1, 1)
        assert ids(target_db) == ["01FRESH", "01HELD"]

    def test_a_forged_carried_signature_on_a_deduped_row_does_not_refuse(
        self, tmp_path
    ):
        """The row-level twin of the gate above: the forgery is already in
        the target, so this merge admits it from nowhere and makes no claim
        about it. Admitting is where the claim attaches — not holding."""
        forged = fact_body("01OLD", "old", signed_by=MALLORY)
        _, target_db = arrival_source(tmp_path, "t", facts=[forged])
        _, source_db = arrival_source(
            tmp_path,
            "s",
            facts=[forged, fact_body("01NEW", "new", signed_by=KYLE)],
        )

        result = merge_store(target_db, source_db, verify=verify)

        assert (result.facts_added, result.facts_skipped) == (1, 1)
        assert ids(target_db) == ["01NEW", "01OLD"]

    def test_a_bad_ordinary_envelope_on_an_ADMITTED_record_does_not_refuse(
        self, tmp_path
    ):
        """The boundary stated positively: an ordinary record's envelope is
        never the admission claim, admitted or not. The row's own carried
        signature is, and it verifies."""
        _, target_db = arrival_source(tmp_path, "t")
        source_log, source_db = arrival_source(
            tmp_path,
            "s",
            facts=[fact_body("01OK", "x", signed_by=KYLE)],
            envelope_key=MALLORY,
        )
        assert_whole_log_verifier_refuses(source_log)

        assert merge_store(target_db, source_db, verify=verify).facts_added == 1
        assert ids(target_db) == ["01OK"]


# --- G-D4-3 — split batch, and the legacy no-claim ----------------------------


class TestSplitBatchAndLegacySource:
    def test_a_partly_deduped_batchs_survivors_are_verified_and_admitted(
        self, tmp_path
    ):
        """G-D4-3, first half. Verification is per-ROW, so a batch that
        dedups down to a remainder needs no special case: the remainder is
        simply the rows in the admission set."""
        from engine.arrival_body import body_of_batch

        held_payload = json.dumps({"message": "shared"})
        held_sig = sign_with(
            KYLE, fact_commitment_hash("note", _TS, "kyle", "", held_payload)
        )
        already = fact_body("01CER0", "shared", signed_by=KYLE)
        _, target_db = arrival_source(tmp_path, "t", facts=[already])

        rows = [
            ("01CER0", "note", _TS, "kyle", "", held_payload, held_sig),
            (
                "01CER1",
                "note",
                _TS,
                "kyle",
                "",
                json.dumps({"message": "survivor"}),
                sign_with(
                    KYLE,
                    fact_commitment_hash(
                        "note", _TS, "kyle", "", json.dumps({"message": "survivor"})
                    ),
                ),
            ),
        ]
        log = minted(tmp_path, "s")
        log.append("batch", body_of_batch(rows), observer="kyle")
        source_db = indexed(log, tmp_path, "s")

        result = merge_store(target_db, source_db, verify=verify)

        assert (result.facts_added, result.facts_skipped) == (1, 1)
        assert ids(target_db) == ["01CER0", "01CER1"]

    def test_a_forged_survivor_in_a_split_batch_refuses(self, tmp_path):
        """Same split, forged remainder: the batch's atomicity buys the
        forgery nothing, because the claim is attached per row."""
        from engine.arrival_body import body_of_batch

        held_payload = json.dumps({"message": "shared"})
        already = fact_body("01CER0", "shared", signed_by=KYLE)
        _, target_db = arrival_source(tmp_path, "t", facts=[already])

        survivor_payload = json.dumps({"message": "survivor"})
        rows = [
            (
                "01CER0",
                "note",
                _TS,
                "kyle",
                "",
                held_payload,
                already["signature"],
            ),
            (
                "01CER1",
                "note",
                _TS,
                "kyle",
                "",
                survivor_payload,
                sign_with(
                    MALLORY,
                    fact_commitment_hash("note", _TS, "kyle", "", survivor_payload),
                ),
            ),
        ]
        log = minted(tmp_path, "s")
        log.append("batch", body_of_batch(rows), observer="kyle")
        source_db = indexed(log, tmp_path, "s")
        before = records(tmp_path / "t.arrival")

        with pytest.raises(AdmissionUnverified, match="01CER1"):
            merge_store(target_db, source_db, verify=verify)
        assert records(tmp_path / "t.arrival") == before

    def test_a_legacy_source_with_no_arrival_log_admits_with_no_claim(
        self, tmp_path
    ):
        """G-D4-3, second half — the ruled D4-Q1 posture. A transport ``.db``
        carries rows and no key history; there is nothing to verify the
        carried signatures against, so they are admitted UNVERIFIED and the
        merge says so by making no claim, rather than refusing a source
        whose only fault is its shape.

        The signature here is forged, and it lands: that is the honest cost
        of the no-claim arm, made visible.
        """
        from engine.sqlite_store import SqliteStore

        _, target_db = arrival_source(tmp_path, "t")
        source_db = tmp_path / "legacy.db"
        store: SqliteStore = SqliteStore(
            path=source_db, serialize=lambda d: d, deserialize=lambda d: d
        )
        body = fact_body("01LEGACY", "x", signed_by=MALLORY)
        store._conn.execute(
            "INSERT INTO facts (id, kind, ts, observer, origin, payload, "
            "signature, arrival_ordinal, arrival_seq) VALUES (?,?,?,?,?,?,?,?,?)",
            (
                body["id"], body["kind"], body["ts"], body["observer"],
                body["origin"], body["payload"], body["signature"], 1, 0,
            ),
        )
        store._conn.commit()
        store.close()

        result = merge_store(target_db, source_db, verify=verify)

        assert result.facts_added == 1
        assert ids(target_db) == ["01LEGACY"]


# --- G-D4-4 — a forged key introduction refuses -------------------------------


class TestForgedKeyIntroduction:
    def test_an_introduction_no_valid_key_signs_refuses_the_merge(self, tmp_path):
        """G-D4-4. Every admitted row here is ORDINARY and unsigned — the
        merge would have nothing to check row-side — and it still refuses,
        because the source's key history is what any check would be against.

        Paired with G-D4-2 this pins the selective boundary exactly:
        registry-forming envelopes are verified, ordinary ones are not.
        """
        _, target_db = arrival_source(tmp_path, "t")
        log = minted(tmp_path, "s")
        log.append(
            KEY_INTRODUCTION_KIND,
            {"observer": "ana", "key": ANA},
            observer="kyle",
            signer=signer_holding(MALLORY),  # valid for nobody
        )
        body = fact_body("01PLAIN", "x")  # no carried signature
        log.append("fact", body, observer="kyle", at=body["ts"])
        source_db = indexed(log, tmp_path, "s")
        before = records(tmp_path / "t.arrival")

        with pytest.raises(AdmissionUnverified, match="key history") as exc:
            merge_store(target_db, source_db, verify=verify)

        assert "source self-consistency" in str(exc.value)
        assert records(tmp_path / "t.arrival") == before
        assert ids(target_db) == []

    def test_the_same_source_merges_when_the_introduction_is_real(self, tmp_path):
        """The discriminating half: only the introduction's signer changes."""
        _, target_db = arrival_source(tmp_path, "t")
        log = minted(tmp_path, "s")
        log.append(
            KEY_INTRODUCTION_KIND,
            {"observer": "ana", "key": ANA},
            observer="kyle",
            signer=signer_holding(KYLE),
        )
        body = fact_body("01PLAIN", "x")
        log.append("fact", body, observer="kyle", at=body["ts"])
        source_db = indexed(log, tmp_path, "s")

        assert merge_store(target_db, source_db, verify=verify).facts_added == 1
        assert ids(target_db) == ["01PLAIN"]

    def test_a_genesis_that_does_not_self_certify_refuses(self, tmp_path):
        """The other registry-forming record. The source's log names one key
        and was signed with another, so nothing it says about authorship is
        checkable and no row of it is admitted."""
        _, target_db = arrival_source(tmp_path, "t")
        log = ArrivalLog.mint(
            tmp_path / "s.arrival",
            observer="kyle",
            signer=signer_holding(MALLORY),
            key=KYLE,
        )
        body = fact_body("01ANY", "x")
        log.append("fact", body, observer="kyle", at=body["ts"])
        source_db = indexed(log, tmp_path, "s")

        with pytest.raises(AdmissionUnverified, match="key history"):
            merge_store(target_db, source_db, verify=verify)
        assert ids(target_db) == []


# --- the surrounding posture --------------------------------------------------


class TestVerificationPosture:
    def test_unsigned_admitted_rows_admit_making_no_claim(self, tmp_path):
        """Era-aware: a pre-signature row carries no authorship claim, so
        there is none to fail. Verifying nothing is honest; treating an
        absent signature as a failed one is not."""
        _, target_db = arrival_source(tmp_path, "t")
        _, source_db = arrival_source(
            tmp_path,
            "s",
            facts=[fact_body("01BARE", "x"), fact_body("01SIGNED", "y", signed_by=KYLE)],
        )

        assert merge_store(target_db, source_db, verify=verify).facts_added == 2
        assert ids(target_db) == ["01BARE", "01SIGNED"]

    def test_a_dry_run_verifies_rather_than_reporting_clean_counts(self, tmp_path):
        """A dry run answers "what would this merge do". Reporting a clean
        count for a merge that would refuse is a wrong answer."""
        _, target_db = arrival_source(tmp_path, "t")
        _, source_db = arrival_source(
            tmp_path, "s", facts=[fact_body("01FORGED", "x", signed_by=MALLORY)]
        )

        with pytest.raises(AdmissionUnverified):
            merge_store(target_db, source_db, dry_run=True, verify=verify)

    def test_a_verifier_on_a_sqlite_target_refuses_rather_than_being_ignored(
        self, tmp_path
    ):
        """The sqlite arm decides its admission set inside INSERT OR IGNORE
        and is held byte-identical by a seam rule, so it has no admission set
        to verify. Accepting the verifier and skipping the work would report
        a verification that never ran."""
        from engine.sqlite_store import SqliteStore

        paths = []
        for name in ("t", "s"):
            path = tmp_path / f"{name}.db"
            SqliteStore(
                path=path, serialize=lambda d: d, deserialize=lambda d: d
            ).close()
            paths.append(path)

        with pytest.raises(ValueError, match="admission verification"):
            merge_store(paths[0], paths[1], verify=verify)

        # Without it, that same merge is untouched.
        assert merge_store(paths[0], paths[1]).facts_added == 0
