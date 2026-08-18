"""arrival — the append-only log that holds canonical custody for a store.

Slice 0 of the arrival substrate (design fact
``decision:design/arrival-slice0-record-grammar``; the wire format is written
out in ``docs/dev/arrival-slice0-record-grammar-2026-08-17.md``). One file per
store, ``<name>.arrival``, one JSON object per line. A record's position in
that file — its **ordinal** — is its identity coordinate, paired with the
**lineage** the genesis record opens. Everything derived from the log is a
projection and is never authoritative.

What slice 0 delivered: the record grammar, genesis minting, append under an
interprocess lock, read by ordinal, the walk with density and chain
verification, torn-tail truncation, corrupt-interior refusal, and the resume
mark. Cut A (decision:design/arrival-sliceA-authority) added the authority
half: the genesis carries the founding public key, self-signed at ordinal 0,
and :func:`verify_authorship` resolves every verifying key from a
``(lineage, ordinal)`` coordinate in the log — never from any artifact
outside it. Projection re-derivation, declared projection orders, and audit
re-basing are later slices and are not here.

Two postures carry over from the existing store and are load-bearing:

* **Truncate only what was never complete, and only at the tail.** A final
  line with no ``\\n`` is an interrupted append; anything else that fails to
  decode, fails its ``rh``, breaks the ordinal succession, or breaks the
  ``prev`` link is corruption, and the answer is a human look rather than a
  silent delete — the posture ``ceremony.IntentCorrupt`` already takes. On a
  file that is the only copy, silent recovery is data loss with extra steps.
* **The writer truncates, the reader never does.** Reads take no lock, so a
  reader cannot distinguish "torn" from "an append is in flight right now";
  it sees a complete newline-terminated record or it sees nothing yet. Only
  the appender, holding the lock and knowing no append is in progress, may
  conclude a tail is torn and cut it.

Known limitation, stated rather than discovered: ``fcntl.flock`` is advisory
and its behaviour over NFS and some network filesystems is unreliable. The
concurrency contract below holds on a local POSIX filesystem. A store on a
network mount is out of contract.
"""

from __future__ import annotations

import base64
import binascii
import contextlib
import fcntl
import hashlib
import json
import math
import os
import time
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import NoReturn, TypeGuard

import rfc8785
from ulid import ULID

__all__ = [
    "ARRIVAL_SUFFIX",
    "LOCK_SUFFIX",
    "TMP_SUFFIX",
    "GRAMMAR_VERSION",
    "GENESIS_KIND",
    "KEY_INTRODUCTION_KIND",
    "RECORD_FIELDS",
    "ArrivalError",
    "ArrivalGrammarError",
    "ArrivalCorrupt",
    "GenesisRefused",
    "AppendRejected",
    "AuthorshipUnverified",
    "ArrivalLog",
    "KeyResolution",
    "ResumeMark",
    "Verify",
    "build_record",
    "verify_authorship",
    "arrival_path_for",
    "lock_path_for",
    "tmp_path_for",
    "content_commitment",
    "record_hash",
    "encode_record",
    "decode_record",
    "mint_lineage",
]

ARRIVAL_SUFFIX = ".arrival"
LOCK_SUFFIX = ".lock"
TMP_SUFFIX = ".tmp"

GRAMMAR_VERSION = 1
GENESIS_KIND = "genesis"

# The kind that introduces a key into the log's own registry. Its body names
# the observer the key speaks for and the key itself; the record must be
# signed by a key that is ALREADY valid at its ordinal, which is what makes
# the registry a chain of custody rather than a mutable table.
KEY_INTRODUCTION_KIND = "key"

# Emitted key order. Transport encoding, not canonicalization — the same
# posture ``jsonl_codec._dump`` documents; canonicalization for hashing is JCS
# and is independent of the order bytes come out in. ``rh`` is last purely as
# a reading convenience: it cannot cover itself, so it is computed over the
# object with ``rh`` removed.
RECORD_FIELDS = ("v", "lin", "ord", "prev", "at", "k", "observer", "origin", "body")
_SIG = "sig"
_RH = "rh"
_ALLOWED = frozenset((*RECORD_FIELDS, _SIG, _RH))

# JCS (RFC 8785) numeric domain — mirrors the guard ``jsonl_codec`` puts at
# its own gate. An integer outside it is not canonicalizable, so a record
# carrying one cannot be hashed: refuse at the codec rather than detonate
# inside the hasher.
_JCS_INT_MAX = 2**53 - 1
_JCS_INT_MIN = -(2**53) + 1

# Reverse scan granularity for finding a line boundary. Chunked so the scan
# never loads the whole log and never gives up as a function of line length.
_CHUNK = 64 * 1024

_HEX = frozenset("0123456789abcdef")

# A signer is injected, never imported: engine does not depend on ``sign``.
# Shape matches the store's ``fact_signer`` — (observer, commitment digest
# hex) -> signature, or None when that observer has no key.
Signer = Callable[[str, str], "str | None"]

# Verification is injected under the same posture. Shape: (public key in the
# ratified wire format, signature, commitment digest hex) -> bool. The
# composing layer supplies the algorithm and the domain-separation prefix;
# this module supplies WHICH key may speak at WHICH position, and nothing
# about how a signature is checked.
Verify = Callable[[str, str, str], bool]

# The ratified key wire format: an Ed25519 public key as raw-32-byte base64,
# copy-identical to the composing layer's on-disk public-key file. The
# grammar pins the shape (so a malformed key is refused at the append site);
# the algorithm stays the injected verifier's business.
_KEY_RAW_LEN = 32


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class ArrivalError(Exception):
    """Base for every refusal the arrival log raises."""


class ArrivalGrammarError(ArrivalError, ValueError):
    """A record object does not match the grammar.

    Raised in BOTH directions from one validator: an encode is held to the
    same domain a decode enforces, so a wrongly typed field fails at the
    append site, where it is attributable, rather than becoming a durable
    line that bricks every later open.
    """


class ArrivalCorrupt(ArrivalError):
    """A complete record in the log is not intact, and the log refuses.

    Corruption is anything a complete line can be wrong about: it fails to
    decode, its ``rh`` does not recompute, its ordinal breaks the dense
    succession, or its ``prev`` does not name its predecessor. None of it is
    a state an appender can produce, so it is evidence of a torn write that
    somehow survived, of an out-of-band edit, or of tampering — and the safe
    answer is a human look, not a silent skip or a truncation.

    ``ordinal`` names where the walk stopped: the ordinal the record was
    expected to carry, so the human has a place to start reading.
    """

    def __init__(self, message: str, ordinal: int) -> None:
        super().__init__(f"arrival log corrupt at ordinal {ordinal}: {message}")
        self.ordinal = ordinal


class GenesisRefused(ArrivalError):
    """A lineage cannot be opened, or a file cannot be read as an arrival log.

    Three shapes, all refusals rather than repairs: the arrival file already
    exists (a lineage is minted exactly once, and overwriting one destroys a
    store); the genesis carries no signature (genesis is the lineage's
    attestation root — the existing unsignable-genesis rule, carried across);
    or the file's first record is not a valid genesis, in which case the file
    is not an arrival log and there is nothing to infer. Identity is never
    read out of content: position 0 is structural and cannot be forged into
    existence by appending.
    """


class AuthorshipUnverified(ArrivalError):
    """A signed record's authorship cannot be established from the log.

    Raised by :func:`verify_authorship` when a signature fails to verify
    under every key that is valid for its observer at its position — the
    ruled rule: a key is valid at position N iff it was introduced at a
    position < N, or N is the genesis position and the record is
    self-certifying. A failure is evidence of a forged signature, a key
    introduction that never happened, or a self-certification attempted
    above ordinal 0 — never a state this module's own writers can produce.

    ``ordinal`` names the record whose authorship failed.
    """

    def __init__(self, message: str, ordinal: int) -> None:
        super().__init__(f"authorship unverified at ordinal {ordinal}: {message}")
        self.ordinal = ordinal


class AppendRejected(ArrivalError):
    """A candidate record does not follow the log's head.

    Append validates, it does not assign: the coordinate is written into the
    record, so a candidate whose ``ord`` is not the head's plus one, whose
    ``lin`` is not the log's lineage, or whose ``prev`` does not name the
    head's ``rh`` is refused before a byte is written. A rejected append
    leaves the log exactly as it was.
    """


# ---------------------------------------------------------------------------
# Path arithmetic
# ---------------------------------------------------------------------------


def arrival_path_for(base: Path | str) -> Path:
    """The arrival log for a store base path: ``<name>.arrival``.

    Suffix appended to the full name, never ``with_suffix`` — the residence
    and ceremony sidecar helpers do the same, so ``alcove.db`` and ``alcove``
    do not collapse onto one arrival path.
    """
    base = Path(base)
    return base.parent / (base.name + ARRIVAL_SUFFIX)


def lock_path_for(arrival_path: Path | str) -> Path:
    """The append-exclusion lock beside a log: ``<name>.arrival.lock``.

    Distinct from the index quarantine lock in ``jsonl_store``: different
    resource, different holder, and the two must not be confused.
    """
    arrival_path = Path(arrival_path)
    return arrival_path.parent / (arrival_path.name + LOCK_SUFFIX)


def tmp_path_for(arrival_path: Path | str) -> Path:
    """The genesis staging path: ``<name>.arrival.tmp``.

    Genesis only. It is the mutex for minting — the process that wins
    ``O_EXCL`` on this path is the one allowed to publish — so it is a fixed
    name rather than a per-process temp file.
    """
    arrival_path = Path(arrival_path)
    return arrival_path.parent / (arrival_path.name + TMP_SUFFIX)


def mint_lineage() -> str:
    """A fresh lineage id. ULID, the repo's id species."""
    return str(ULID())


# ---------------------------------------------------------------------------
# Grammar: validation, hashing, codec
# ---------------------------------------------------------------------------


def _canonical_bytes(obj: dict) -> bytes:
    """Canonical encoding for hashing: JCS, RFC 8785.

    The same canonicalization every commitment in this codebase hashes
    through. It is a total function on the JSON value, so any conforming
    implementation in any language derives the same bytes — which is what a
    cross-language conformance oracle needs and why JCS was adopted.
    """
    return rfc8785.dumps(obj)


def _bad(message: str) -> NoReturn:
    """Refuse a record. ``NoReturn`` is load-bearing, not decoration: the
    validators below call this instead of raising inline, and without it a
    reader — human or type checker — cannot see that the checks are total,
    so every subsequent use of the value looks conditional."""
    raise ArrivalGrammarError(message)


def _is_int(value: object) -> TypeGuard[int]:
    """A JSON integer. ``bool`` is excluded: ``True`` is an ``int`` in Python
    and would silently pass an ordinal check while encoding as ``true``."""
    return isinstance(value, int) and not isinstance(value, bool)


def _check_hex(value: object, field: str) -> None:
    if not isinstance(value, str) or len(value) != 64 or not set(value) <= _HEX:
        _bad(f"{field} must be a 64-char lowercase sha256 hex digest, got {value!r}")


def _check_jcs_number(value: object, field: str) -> None:
    """Hold a number to what JCS can canonicalize.

    Integers outside the 2^53 domain and non-finite floats have no canonical
    form, so a record carrying one could never be hashed.
    """
    if _is_int(value):
        if not _JCS_INT_MIN <= value <= _JCS_INT_MAX:
            _bad(f"{field} {value} is outside the JCS integer domain")
        return
    if isinstance(value, float):
        if not math.isfinite(value):
            _bad(f"{field} must be a finite number, got {value!r}")
        return
    _bad(f"{field} must be a number, got {type(value).__name__}")


def _check_body(body: object) -> None:
    """``body`` is a JSON object, and one JCS can canonicalize.

    A named departure from the line codec, which carries payload as verbatim
    TEXT so that two custody holders cannot disagree byte-wise. In the
    arrival model there is no second copy — the log IS the store — so there
    is no other byte-form to disagree with, and JCS defines the canonical
    bytes. Keeping the body an opaque string would double every escape,
    make the file unreadable by eye, and leave the canonical bytes defined
    by whichever encoder happened to produce the string.
    """
    if not isinstance(body, dict):
        _bad(f"body must be a JSON object, got {type(body).__name__}")
    try:
        _canonical_bytes(body)
    except Exception as exc:  # rfc8785 raises its own family
        _bad(f"body is not canonicalizable under JCS: {exc}")


def _validate(record: object, *, require_rh: bool) -> None:
    """The one grammar validator, run in both directions.

    ``require_rh`` is False while building a record (``rh`` is computed from
    the validated object) and True for anything read back off disk.

    Takes ``object``, not ``dict``, and the annotation is doing real work:
    :func:`decode_record` hands this whatever ``json.loads`` produced, which
    may be a list or a string, and the first check below is what refuses
    those. Narrowing the signature to ``dict`` would make that check look
    dead to a reader and to a type checker while it stayed live at runtime.
    """
    if not isinstance(record, dict):
        _bad(f"a record must be a JSON object, got {type(record).__name__}")

    unknown = sorted(set(record) - _ALLOWED)
    if unknown:
        _bad(f"unknown record field(s): {', '.join(unknown)}")
    missing = [f for f in RECORD_FIELDS if f not in record]
    if missing:
        _bad(f"missing record field(s): {', '.join(missing)}")
    if require_rh and _RH not in record:
        _bad("missing record field: rh")

    if not _is_int(record["v"]) or record["v"] != GRAMMAR_VERSION:
        _bad(f"unsupported grammar version {record['v']!r} (this build writes {GRAMMAR_VERSION})")

    if not isinstance(record["lin"], str) or not record["lin"]:
        _bad("lin must be a non-empty string")

    if not _is_int(record["ord"]) or record["ord"] < 0:
        _bad(f"ord must be an integer >= 0, got {record['ord']!r}")
    _check_jcs_number(record["ord"], "ord")

    # prev is null exactly at ordinal 0 and a digest everywhere else. Both
    # directions are checked: a genesis carrying a prev is as wrong as a
    # successor carrying none.
    if record["ord"] == 0:
        if record["prev"] is not None:
            _bad("prev must be null at ordinal 0")
    else:
        _check_hex(record["prev"], "prev")

    _check_jcs_number(record["at"], "at")

    if not isinstance(record["k"], str) or not record["k"]:
        _bad("k must be a non-empty string")
    if not isinstance(record["observer"], str) or not record["observer"]:
        _bad("observer must be a non-empty string")
    if not isinstance(record["origin"], str):
        _bad(f"origin must be a string (may be empty), got {type(record['origin']).__name__}")

    _check_body(record["body"])

    # Absent, never null: a record with no signature and a record with
    # ``"sig":null`` must not both be spellable, or they hash differently
    # while meaning the same thing.
    if _SIG in record and (not isinstance(record[_SIG], str) or not record[_SIG]):
        _bad("sig, when present, must be a non-empty string")

    if _RH in record:
        _check_hex(record[_RH], "rh")


def _key_shape_fault(value: object) -> str | None:
    """Why ``value`` is not a well-formed public key, or None when it is.

    Shape only — raw-32-byte base64, the ratified wire format. Whether a
    signature actually verifies under it is the injected verifier's answer
    (:func:`verify_authorship`); the grammar refuses what could never be a
    key so a malformed one fails at the append site rather than bricking
    verification later.
    """
    if not isinstance(value, str) or not value:
        return f"key must be a non-empty string, got {type(value).__name__}"
    try:
        raw = base64.b64decode(value, validate=True)
    except (binascii.Error, ValueError) as exc:
        return f"key is not valid base64: {exc}"
    if len(raw) != _KEY_RAW_LEN:
        return f"key must decode to {_KEY_RAW_LEN} bytes, got {len(raw)}"
    return None


def _placement_fault(record: dict, ordinal: int) -> str | None:
    """Why ``record`` may not sit at ``ordinal``, or None when it may.

    One rule stated once, in both directions: **the genesis kind belongs at
    ordinal 0 and nowhere else.** At 0 a record must satisfy every genesis
    rule; above 0 it must not claim to be a genesis at all. A key
    introduction (:data:`KEY_INTRODUCTION_KIND`) is held to its structural
    rules at any ordinal it appears: signed, and a body naming an observer
    and a well-formed key.

    Structural rules only, deliberately: whether the genesis signature
    verifies against ``body["key"]`` — self-certification — and whether an
    introduction's signer was valid at its position are cryptographic
    questions, answered by :func:`verify_authorship` with an injected
    verifier. This function stays pure so every caller (walk, append, open)
    can run it without carrying one.

    This exists as one function because the two directions were previously
    checked in four places with three different sets of rules, and the gaps
    between them were exactly the holes: a forged unsigned genesis walked
    clean because only :meth:`ArrivalLog.genesis` demanded a signature, and
    a second genesis could be appended at an interior ordinal because
    nothing checked the kind on the way in. Callers differ only in the error
    class they raise — opening a file that is not an arrival log, walking one
    that has been tampered with, and refusing an append are three different
    conversations about the same rule.
    """
    if ordinal == 0:
        if record["k"] != GENESIS_KIND:
            return f"first record has kind {record['k']!r}, not a genesis"
        if record["ord"] != 0:
            return f"first record carries ord {record['ord']!r}, not 0"
        if record["prev"] is not None:
            return "first record carries a prev — genesis opens the chain"
        if _SIG not in record:
            return (
                "genesis carries no signature — genesis is the lineage's "
                "attestation root"
            )
        claimed = record["body"].get("lineage")
        if claimed != record["lin"]:
            return (
                f"genesis is not self-naming — body claims lineage {claimed!r} "
                f"but the coordinate says {record['lin']!r}"
            )
        key_fault = _key_shape_fault(record["body"].get("key"))
        if key_fault is not None:
            return (
                f"genesis carries no well-formed founding key ({key_fault}) — "
                "a live-store genesis introduces the founding public key at "
                "ordinal 0; a keyless genesis belongs to the migration "
                "sidecar, not to this grammar"
            )
        return None
    if record["k"] == GENESIS_KIND:
        return (
            f"a genesis at ordinal {ordinal} — the genesis kind belongs at "
            "ordinal 0 and nowhere else, and a lineage is opened once"
        )
    if record["k"] == KEY_INTRODUCTION_KIND:
        if _SIG not in record:
            return (
                "a key introduction carries no signature — an introduction "
                "is vouched for by a key that is already valid, never "
                "self-certifying above ordinal 0"
            )
        named = record["body"].get("observer")
        if not isinstance(named, str) or not named:
            return "a key introduction's body must name the observer the key speaks for"
        key_fault = _key_shape_fault(record["body"].get("key"))
        if key_fault is not None:
            return f"a key introduction's body carries no well-formed key: {key_fault}"
    return None


def _authority_fault(record: dict, lineage: str) -> str | None:
    """Why ``record`` may not be ADOPTED AS AN AUTHORITY, or None when it may.

    An authority is an existing on-disk record the code takes as a starting
    point and derives from: the head an append chains onto, the anchor a
    resume walk continues from. Reading a record forward and adopting one as
    a premise are different acts, and only the first was ever checked —
    twice, review found the same residual shape, because a rule enforced on
    the way past a record says nothing about a record you never walked to.

    So: validate at every adoption site, not at a proxy for it. A record may
    be adopted when it decodes and its ``rh`` recomputes (the caller's
    :func:`decode_record` established that), when it may sit at the ordinal
    it claims (:func:`_placement_fault`), and when it belongs to this log's
    lineage.

    What adoption does NOT establish, and deliberately: that the record
    chains back to genesis, or that its claimed ordinal matches its physical
    position in the file. Both need a walk of the whole prefix, which is the
    O(n) cost these O(1) paths exist to avoid. The residual is narrow —
    density is re-checked from the adopted record onward, so a hostile
    coordinate is refused one record later — and :meth:`ArrivalLog.walk` is
    the integrity statement whenever the whole file is the question.
    """
    fault = _placement_fault(record, record["ord"])
    if fault is not None:
        return fault
    if record["lin"] != lineage:
        return (
            f"record claims lineage {record['lin']!r}, "
            f"but this log's lineage is {lineage!r}"
        )
    return None


def content_commitment(
    k: str, at: float, observer: str, origin: str, body: dict
) -> str:
    """The digest a signature covers: sha256 over JCS of the five content
    fields.

    Content only. The coordinate, ``prev``, ``rh``, and ``sig`` itself are
    all outside it — the first three because they are custody context rather
    than authored content, the last because a signature cannot sign itself.
    That exclusion is what makes a signature transport-stable: any store
    holding the record re-derives the same digest and verifies authorship
    against the observer registry without trusting the sender.
    """
    envelope = {"k": k, "at": at, "observer": observer, "origin": origin, "body": body}
    return hashlib.sha256(_canonical_bytes(envelope)).hexdigest()


def record_hash(record: dict) -> str:
    """``rh``: sha256 over JCS of the whole record with ``rh`` removed.

    Covers the coordinate and the signature, which is how the coordinate is
    tamper-evident without being signed, and how ``prev`` gets something to
    point at.
    """
    return hashlib.sha256(
        _canonical_bytes({key: value for key, value in record.items() if key != _RH})
    ).hexdigest()


def _no_duplicate_keys(pairs: list[tuple[str, object]]) -> dict:
    """JSON's last-wins duplicate resolution would let one line carry two
    ordinals and a reader silently pick one. Reject instead."""
    seen: dict = {}
    for key, value in pairs:
        if key in seen:
            _bad(f"duplicate key {key!r} in one JSON object")
        seen[key] = value
    return seen


def build_record(
    *,
    lin: str,
    ordinal: int,
    prev: str | None,
    k: str,
    body: dict,
    observer: str,
    origin: str = "",
    at: float | None = None,
    sig: str | None = None,
) -> dict:
    """Assemble one validated record, ``rh`` computed and last.

    ``at`` is wall clock at append. It is authored content and rides inside
    the signed envelope — an unsigned timestamp is a claim anyone downstream
    can rewrite. It is never an ordering input: nothing sorts by it and no
    later slice's declared orders may name it.
    """
    record: dict = {
        "v": GRAMMAR_VERSION,
        "lin": lin,
        "ord": ordinal,
        "prev": prev,
        "at": time.time() if at is None else at,
        "k": k,
        "observer": observer,
        "origin": origin,
        "body": body,
    }
    if sig is not None:
        record[_SIG] = sig
    _validate(record, require_rh=False)
    record[_RH] = record_hash(record)
    return record


def encode_record(record: dict) -> str:
    """One line, no trailing newline.

    ``ensure_ascii`` keeps the line 7-bit and free of raw U+2028/U+2029,
    ``allow_nan=False`` refuses the non-JSON float constants, and
    ``separators`` drops insignificant whitespace. Together they are why
    newline framing is safe rather than merely conventional: no encoded
    record can contain a raw newline, so a ``\\n`` in the file is
    unambiguously a boundary.
    """
    _validate(record, require_rh=True)
    if record[_RH] != record_hash(record):
        _bad("rh does not match the record it is attached to")
    ordered = {key: record[key] for key in RECORD_FIELDS}
    if _SIG in record:
        ordered[_SIG] = record[_SIG]
    ordered[_RH] = record[_RH]
    return json.dumps(ordered, ensure_ascii=True, allow_nan=False, separators=(",", ":"))


def decode_record(line: str | bytes) -> dict:
    """Decode one line and hold it to the grammar, ``rh`` included.

    Raises :class:`ArrivalGrammarError`. The caller decides what a failure
    means — the walk turns it into :class:`ArrivalCorrupt` with a coordinate
    attached, because at that point there is a position to name.
    """
    if isinstance(line, bytes):
        try:
            line = line.decode("utf-8")
        except UnicodeError as exc:
            _bad(f"line is not valid UTF-8: {exc}")
    try:
        record = json.loads(line, object_pairs_hook=_no_duplicate_keys)
    except ValueError as exc:
        if isinstance(exc, ArrivalGrammarError):
            raise
        _bad(f"line is not valid JSON: {exc}")
    _validate(record, require_rh=True)
    if record[_RH] != record_hash(record):
        _bad("rh does not recompute — the record's bytes have changed")
    return record


# ---------------------------------------------------------------------------
# Resume mark
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ResumeMark:
    """Where a reader stopped: three fields, trusted only when all agree.

    ``arrival_offset`` is the byte just past the last consumed record's
    ``\\n``; ``arrival_ordinal`` is that record's ``ord``. The ordinal is the
    field the old byte-offset custody could not carry, and it is why a mark
    is checkable against the log alone with no projection consulted — the
    property that lets a later slice rebuild projections from nothing. It is
    also why the two row counts the old custody kept dissolve: the ordinal is
    dense, so "how many records precede this one" is ``ord``, by
    construction.

    A mark that fails any check is discarded and the reader restarts from
    ordinal 0. Discarding is cheap and always safe — it costs a re-read,
    never data — which is why a mark may be dropped silently where a corrupt
    record may not.
    """

    arrival_lineage: str
    arrival_offset: int
    arrival_ordinal: int


# ---------------------------------------------------------------------------
# The log
# ---------------------------------------------------------------------------


class ArrivalLog:
    """One arrival log, addressed by its path.

    Cheap to construct and holds no open file: every operation opens what it
    needs. Appends across processes are mutually exclusive, enforced by an
    advisory ``LOCK_EX`` on ``<name>.arrival.lock`` held for the whole
    read-head, validate, write, fsync sequence. Reads take no lock and are
    safe at any time against a concurrent append.

    Exclusion rather than lock-free ``O_APPEND`` is forced by the addressing
    scheme, not chosen for convenience: the ordinal follows from the head, so
    correctness requires reading the head and writing to be indivisible. Two
    processes that both read head ``ord=7`` would both write ``ord=8``, and a
    duplicate coordinate is a corrupt interior that refuses forever.

    ``flock`` specifically because it is released when the holding process
    dies. A crashed writer must not wedge the store, which is the opposite of
    what an ``O_EXCL`` lock file would give — that behaviour is right for the
    one-shot genesis gate and wrong for an operation that runs constantly.
    """

    def __init__(self, path: Path | str) -> None:
        self.path = Path(path)
        self.lock_path = lock_path_for(self.path)
        self.tmp_path = tmp_path_for(self.path)
        # Memo for :meth:`_lineage_from`, keyed on the genesis line's bytes.
        self._genesis_line: bytes | None = None
        self._genesis_lineage: str | None = None

    # -- minting -------------------------------------------------------

    @classmethod
    def mint(
        cls,
        path: Path | str,
        *,
        observer: str,
        signer: Signer,
        key: str,
        origin: str = "",
        lineage: str | None = None,
        at: float | None = None,
    ) -> ArrivalLog:
        """Open a new lineage: write genesis and publish it atomically.

        The genesis record is self-naming — the lineage id it carries is the
        one its own coordinate ``(lin, 0)`` opens — and it must be signed:
        genesis is the lineage's attestation root, and the signature is over
        the ACTUAL final body, so the body is assembled first and signed
        second. The body is ``{protocol, lineage, key}`` and nothing else
        (decision:design/arrival-sliceA-authority §2.3): ``key`` is the
        founding PUBLIC key in the ratified wire format, self-signed at
        ordinal 0 — the anchor every later authorship answer resolves back
        to. The document set is movement 2, records at ordinal >= 1; era
        pins dissolve under the dense ordinal; containment claims belong to
        the migration sidecar's genesis, never to a live store's.

        ``key`` and ``signer`` must correspond — the grammar checks the
        key's shape here, and :func:`verify_authorship` is where the
        self-certification is cryptographically established. A mint whose
        signer does not hold ``key`` produces a log the verifier refuses at
        ordinal 0.

        Staging wins ``O_EXCL`` on ``<name>.arrival.tmp`` FIRST and only then
        checks for an existing log. That order is what makes minting a race
        safe: the tmp path is the mutex, so the existence check happens with
        the mutex held. Checking before creating would leave a window where
        both processes see no log and the second one's rename destroys the
        first one's store.

        The directory is fsync'd once, here. The file's own fsync is not
        enough at creation: an fsync'd file whose directory entry never
        reached disk is a store that vanishes on power loss, and unlike the
        old design there is no second copy to re-export from. Per-append
        directory fsync is not needed — the entry already exists and only the
        file's size and content change after this.
        """
        log = cls(path)
        log.path.parent.mkdir(parents=True, exist_ok=True)

        key_fault = _key_shape_fault(key)
        if key_fault is not None:
            raise GenesisRefused(
                f"genesis founding key is malformed ({key_fault}) — the "
                "ratified wire format is a raw-32-byte base64 public key"
            )
        lin = mint_lineage() if lineage is None else lineage
        body = {"protocol": GRAMMAR_VERSION, "lineage": lin, "key": key}
        at = time.time() if at is None else at
        sig = signer(observer, content_commitment(GENESIS_KIND, at, observer, origin, body))
        if not sig:
            raise GenesisRefused(
                f"genesis for lineage {lin} is unsigned — genesis is the lineage's "
                f"attestation root and observer {observer!r} produced no signature"
            )
        line = encode_record(
            build_record(
                lin=lin, ordinal=0, prev=None, k=GENESIS_KIND, body=body,
                observer=observer, origin=origin, at=at, sig=sig,
            )
        )

        try:
            fd = os.open(str(log.tmp_path), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
        except FileExistsError as exc:
            raise GenesisRefused(
                f"{log.tmp_path} exists — another process is minting this lineage, "
                "or a previous mint died mid-flight and left staging behind"
            ) from exc
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                # The existence check runs with the staging mutex held, which
                # is what makes it authoritative rather than a fast path.
                if log.path.exists():
                    raise GenesisRefused(
                        f"{log.path} already exists — a lineage is minted once, and "
                        "publishing over an existing log would destroy a store"
                    )
                fh.write(line + "\n")
                fh.flush()
                os.fsync(fh.fileno())
            log.tmp_path.replace(log.path)
        except BaseException:
            # The staging create won, but the bytes never became durable —
            # leave zero residue behind the failed mint.
            with contextlib.suppress(OSError):
                log.tmp_path.unlink()
            raise
        _fsync_dir(log.path.parent)
        return log

    # -- reading -------------------------------------------------------

    def exists(self) -> bool:
        return self.path.exists()

    def _size(self) -> int:
        try:
            return self.path.stat().st_size
        except OSError:
            return 0

    def genesis(self) -> dict:
        """The record at ordinal 0, validated as a genesis.

        A file whose first record is not a valid genesis is not an arrival
        log and opening it refuses. There is no inference of identity from
        content: the singleton heuristic that guessed a store's lineage from
        its rows was a hijack vector, and here the hazard dissolves rather
        than being defended against, because position 0 is structural.
        """
        try:
            with self.path.open("rb") as fh:
                return self._validated_genesis(fh.readline())
        except FileNotFoundError as exc:
            raise GenesisRefused(f"{self.path} does not exist") from exc

    def _lineage_from(self, fh) -> str:
        """The validated lineage, memoized on the genesis LINE BYTES.

        The append path needs the lineage on every write, and re-deriving it
        costs a JSON decode, an ``rh`` recompute and the genesis checks —
        about a tenth of an append, which is worth not paying twice for the
        same bytes.

        **A cache hit is not a skipped validation.** The key is the exact
        line the validated answer was derived from, so a hit means "these
        bytes already passed, and validating them again is a pure function
        returning the same result". That is the only cache shape allowed
        here: the standing lesson of this module is that an adopted
        authority gets validated at the adoption site, and a cache keyed on
        anything weaker than the content — a path, an inode, an mtime —
        would be a way to skip that. Reading the line to compare it costs
        about 0.1 µs against the 15 µs it saves, so the strong key is also
        the cheap one.

        Staleness therefore cannot bite: the instance may outlive a
        truncation, a re-mint at the same path, or a foreign edit, and every
        one of those changes the bytes, misses, and revalidates. A
        replacement whose genesis is byte-identical opens the same lineage,
        so the cached answer is still the right one.
        """
        fh.seek(0)
        raw = fh.readline()
        # Snapshot both fields before comparing: a torn read across threads
        # then misses and revalidates rather than pairing one entry's key
        # with another's value.
        cached_line, cached_lineage = self._genesis_line, self._genesis_lineage
        if raw == cached_line and cached_lineage is not None:
            return cached_lineage
        lineage = self._validated_genesis(raw)["lin"]
        self._genesis_lineage = lineage
        self._genesis_line = raw  # published last, so the key implies the value
        return lineage

    def _validated_genesis(self, raw: bytes) -> dict:
        """Decode one raw line and hold it to every genesis rule."""
        if not raw.endswith(b"\n"):
            raise GenesisRefused(
                f"{self.path} holds no complete first record — not an arrival log"
            )
        try:
            record = decode_record(raw[:-1])
        except ArrivalGrammarError as exc:
            raise GenesisRefused(f"{self.path}: first record is not readable: {exc}") from exc
        fault = _placement_fault(record, 0)
        if fault is not None:
            raise GenesisRefused(f"{self.path}: {fault}")
        return record

    def lineage(self) -> str:
        """The lineage this log's genesis opens."""
        return self.genesis()["lin"]

    def walk(self) -> Iterator[dict]:
        """Every complete record in order, fully verified.

        Verifies, per record: that it decodes, that its ``rh`` recomputes
        (inside :func:`decode_record`), that it may sit where it sits — the
        full genesis rules at ordinal 0 and no genesis kind above it, via
        :func:`_placement_fault` — that its lineage matches the genesis's,
        that its ordinal is the next one — dense and ascending from 0, so a
        gap or a repeat is caught — and that its ``prev`` names its
        predecessor's ``rh``. Any failure raises :class:`ArrivalCorrupt`
        naming the ordinal. Nothing is skipped and nothing is truncated.

        The genesis rules are enforced HERE and not only in
        :meth:`genesis`, because a walk that trusted position 0 without
        judging it would read a forged unsigned genesis clean — and
        :meth:`read` and :meth:`head` both reach their answer through this
        walk, so the check has to live on the path they share.

        A trailing line with no ``\\n`` ends the walk without complaint. The
        reader holds no lock, so it cannot tell an interrupted append from
        one that is in flight this instant, and it must assume the kinder of
        the two.

        **This is a generator: calling it validates nothing.** Every check
        above runs as records are pulled, so ``log.walk()`` on its own is
        not an integrity test and must not be used as one — ``list(...)``
        it, or iterate it to the end. The laziness is deliberate (a caller
        reading the first ten records of a large log should not pay for the
        rest), and it is worth naming because "I called walk and it did not
        raise" is a natural and wrong way to read this code.
        """
        if not self.path.exists():
            return
        with self.path.open("rb") as fh:
            # lineage=None means "not established yet" — the record at
            # ordinal 0 names it, and every record after is held to it.
            yield from self._verify_from(fh, expected=0, prev=None, lineage=None)

    def _verify_from(
        self, fh, *, expected: int, prev: str | None, lineage: str | None
    ) -> Iterator[dict]:
        """The per-record verification loop — the one home for it.

        :meth:`walk` and :meth:`_walk_tail` differ only in where they start
        and how the lineage is established; every rule applied to a record
        is the same, and it lives here so it cannot be added to one path and
        forgotten on the other. It was duplicated for two review rounds, and
        both rounds had to patch the same check twice.

        ``lineage`` is None only for a walk from ordinal 0, where the
        genesis names it. A resume passes the genesis's lineage in, so the
        anchor cannot decide what the rest of the file is checked against.
        """
        for raw in fh:
            if not raw.endswith(b"\n"):
                return  # in flight, or torn — either way not the reader's to judge
            try:
                record = decode_record(raw[:-1])
            except ArrivalGrammarError as exc:
                raise ArrivalCorrupt(str(exc), expected) from exc
            fault = _placement_fault(record, expected)
            if fault is not None:
                raise ArrivalCorrupt(fault, expected)
            if lineage is None:
                lineage = record["lin"]
            elif record["lin"] != lineage:
                raise ArrivalCorrupt(
                    f"record claims lineage {record['lin']!r}, "
                    f"but this log's lineage is {lineage!r}",
                    expected,
                )
            if record["ord"] != expected:
                raise ArrivalCorrupt(
                    f"ordinal succession broken: found ord {record['ord']!r} "
                    f"where {expected} was due",
                    expected,
                )
            if record["prev"] != prev:
                raise ArrivalCorrupt(
                    f"prev names {record['prev']!r}, "
                    f"but the preceding record's rh is {prev!r}",
                    expected,
                )
            yield record
            expected += 1
            prev = record[_RH]

    def read(self, ordinal: int) -> dict:
        """The record at ``ordinal``, reached by a verified walk.

        The walk is the only way in on purpose: reading a coordinate means
        having established that everything before it is intact, because a
        record whose predecessors do not chain is not at the coordinate it
        claims.
        """
        if not _is_int(ordinal) or ordinal < 0:
            raise ArrivalError(f"ordinal must be an integer >= 0, got {ordinal!r}")
        for record in self.walk():
            if record["ord"] == ordinal:
                return record
        raise ArrivalError(f"{self.path} holds no record at ordinal {ordinal}")

    def head(self) -> dict:
        """The record at the highest ordinal currently in the log."""
        record = None
        for record in self.walk():  # noqa: B007 — the last one is the answer
            pass
        if record is None:
            raise GenesisRefused(f"{self.path} holds no complete record")
        return record

    def _tail_record(self) -> dict:
        """The last complete record, found by reverse scan rather than walk.

        Append needs the head and nothing else, and it needs it in constant
        time: walking the whole log on every append would make ingest
        quadratic. The record's own ``rh`` still recomputes here, so a tail
        that has been edited is caught; whole-log density and chain
        verification stay :meth:`walk`'s job.

        The head is ADOPTED AS AN AUTHORITY — the next record's coordinate
        and ``prev`` are derived from it — so it is validated as one
        (:func:`_authority_fault`), and the genesis is read first to
        establish what this log's lineage actually is. Without that, a log
        whose ordinal-0 record is an unsigned or foreign genesis kept
        accepting appends and growing, which is worse than a refused write:
        honest-looking records accumulating on top of a tampered one is
        exactly what makes the tamper hard to see later.
        """
        size = self._size()
        if size == 0:
            raise GenesisRefused(f"{self.path} is empty — mint a genesis first")
        with self.path.open("rb") as fh:
            # One handle for both reads. The genesis line is read on every
            # append through the handle already open for the tail, and its
            # validation is memoized on those bytes (:meth:`_lineage_from`)
            # — so the check still runs against what is on disk right now.
            lineage = self._lineage_from(fh)
            fh.seek(size - 1)
            if fh.read(1) != b"\n":
                raise ArrivalError(
                    f"{self.path} ends mid-record — truncate the torn tail first"
                )
            start = _last_newline_before(fh, size - 1)
            fh.seek(start)
            raw = fh.read(size - 1 - start)
        try:
            record = decode_record(raw)
        except ArrivalGrammarError as exc:
            raise ArrivalCorrupt(str(exc), -1) from exc
        fault = _authority_fault(record, lineage)
        if fault is not None:
            raise ArrivalCorrupt(f"cannot append onto this head: {fault}", record["ord"])
        return record

    # -- resume --------------------------------------------------------

    def resume_offset(self, mark: ResumeMark | None) -> int:
        """The byte offset ``mark`` licenses, or 0 when it does not.

        The checks live in :meth:`_anchor_for`, which is where the anchor is
        actually adopted; this is the offset-only view of its answer.
        Rejection is not an error — the reader restarts from ordinal 0.
        """
        adopted = self._anchor_for(mark)
        return 0 if adopted is None else adopted[0]

    def _anchor_for(self, mark: ResumeMark | None) -> tuple[int, dict, str] | None:
        """Adopt ``mark``'s anchor, or None when the mark cannot be trusted.

        The single adoption site for the resume path: it reads the anchor
        once and applies every check, and both :meth:`resume_offset` and
        :meth:`walk_from` consume its answer. They used to validate and
        re-read separately, which meant the place where the anchor actually
        became an authority was not the place the checks lived — the proxy
        shape behind two rounds of findings.

        Five checks, all of which must hold:

        1. The mark's lineage is this log's. A mark from another lineage is
           not stale, it is a mark about a different file, and pointing it
           here is meaningless.
        2. The offset is an integer inside ``0..size``. A negative offset is
           not a seek position to try, it is metadata that cannot be true.
        3. It lands strictly on a record boundary.
        4. The record ending there carries the ordinal the mark claims.
        5. That record may be adopted as an authority
           (:func:`_authority_fault`) — its own lineage is the genesis's,
           and it may sit where it claims to sit. Without the first half, a
           crafted interior record with a foreign lineage and a recomputing
           ``rh`` becomes the anchor and the tail walk verifies the rest of
           the file against the attacker's lineage. Without the second, a
           record the full walk refuses becomes a legal place to resume
           from, and the resume path consumes straight past corruption the
           read path stops at.

        What these do NOT establish is in :func:`_authority_fault`: the
        anchor is checked for self-consistency, never for chaining back to
        genesis. The mark is a cheap boundary check; :meth:`walk` is the
        integrity statement.

        Returns ``(offset, anchor, lineage)``, the lineage always the
        genesis's and never the anchor's.
        """
        if mark is None:
            return None
        if not self.path.exists():
            return None
        try:
            lineage = self.lineage()
        except (GenesisRefused, ArrivalError):
            return None
        if mark.arrival_lineage != lineage:
            return None
        if not _is_int(mark.arrival_offset) or not _is_int(mark.arrival_ordinal):
            return None
        if mark.arrival_offset == 0:
            return None  # nothing consumed; identical to a fresh start
        if not 0 <= mark.arrival_offset <= self._size():
            return None
        anchor = self._record_ending_at(mark.arrival_offset)
        if anchor is None or anchor["ord"] != mark.arrival_ordinal:
            return None
        if _authority_fault(anchor, lineage) is not None:
            return None
        return mark.arrival_offset, anchor, lineage

    def _record_ending_at(self, offset: int) -> dict | None:
        """The record whose ``\\n`` is the byte before ``offset``, or None
        when the offset is not a boundary or the record does not decode."""
        with self.path.open("rb") as fh:
            fh.seek(offset - 1)
            if fh.read(1) != b"\n":
                return None
            start = _last_newline_before(fh, offset - 1)
            fh.seek(start)
            raw = fh.read(offset - 1 - start)
        try:
            return decode_record(raw)
        except ArrivalGrammarError:
            return None

    def walk_from(self, mark: ResumeMark | None) -> tuple[int, Iterator[dict]]:
        """Resume a consumption: the ordinal resumed at, and the records after.

        Returns ``(0, walk())`` whenever the mark is rejected, so a caller
        that persists progress learns it is starting over instead of
        discovering it by ordinal.
        """
        adopted = self._anchor_for(mark)
        if adopted is None:
            return 0, self.walk()
        offset, anchor, lineage = adopted
        # The lineage comes from the GENESIS, never from the anchor. An
        # anchor is a record found at a byte offset a caller supplied, and
        # letting it name the lineage would let it decide what the rest of
        # the walk is checked against.
        return anchor["ord"] + 1, self._walk_tail(offset, anchor, lineage)

    def _walk_tail(self, offset: int, anchor: dict, lineage: str) -> Iterator[dict]:
        """:meth:`walk`'s verification, started from a validated anchor.

        Literally the same rules, not merely the same list of them: both
        paths run :meth:`_verify_from`, and only the starting point differs.
        ``lineage`` is the log's, established from its genesis by the
        caller, so the anchor never decides what the rest is checked
        against.
        """
        with self.path.open("rb") as fh:
            fh.seek(offset)
            yield from self._verify_from(
                fh, expected=anchor["ord"] + 1, prev=anchor[_RH], lineage=lineage
            )

    # -- appending -----------------------------------------------------

    def append(
        self,
        k: str,
        body: dict,
        *,
        observer: str,
        origin: str = "",
        at: float | None = None,
        signer: Signer | None = None,
    ) -> dict:
        """Append one record at the next coordinate; return it.

        The coordinate is read off the head under the lock and written into
        the record, then validated by the same gate
        :meth:`append_record` uses. Ordinary records may be unsigned; only
        genesis must carry a signature.
        """

        return self.append_marked(
            k, body, observer=observer, origin=origin, at=at, signer=signer
        )[0]

    def append_marked(
        self,
        k: str,
        body: dict,
        *,
        observer: str,
        origin: str = "",
        at: float | None = None,
        signer: Signer | None = None,
    ) -> tuple[dict, ResumeMark]:
        """:meth:`append`, also returning the mark that resumes just past it.

        The mark's offset is read under the append lock — the byte just past
        this record's newline, exact by construction rather than a size read
        that a concurrent append could land inside. A consumer that indexes
        the record it just wrote persists this mark and later resumes
        through :meth:`walk_from`, which re-validates the anchor at the
        adoption site.
        """

        def build(headr: dict) -> dict:
            at_ = time.time() if at is None else at
            sig = (
                signer(observer, content_commitment(k, at_, observer, origin, body))
                if signer is not None
                else None
            )
            return build_record(
                lin=headr["lin"], ordinal=headr["ord"] + 1, prev=headr[_RH],
                k=k, body=body, observer=observer, origin=origin, at=at_,
                sig=sig or None,
            )

        record, offset = self._append_under_lock(build)
        return record, ResumeMark(
            arrival_lineage=record["lin"],
            arrival_offset=offset,
            arrival_ordinal=record["ord"],
        )

    def append_record(self, record: dict) -> dict:
        """Append a record that already carries its coordinate.

        The primitive the grammar describes: append VALIDATES, it never
        assigns. A candidate assembled elsewhere — carried in from another
        store, replayed, rebuilt — passes through exactly the same head
        checks that :meth:`append` does. ``rh`` may be
        omitted and is then computed over the validated object; supplied, it
        must match, so a candidate carried in with its own digest is checked
        rather than trusted.
        """

        def build(_head: dict) -> dict:
            candidate = dict(record)
            if _RH not in candidate:
                _validate(candidate, require_rh=False)
                candidate[_RH] = record_hash(candidate)
            return candidate

        return self._append_under_lock(build)[0]

    def _append_under_lock(self, build: Callable[[dict], dict]) -> tuple[dict, int]:
        """The whole write sequence, indivisible. Returns the record and the
        byte offset just past its newline, both read under the lock.

        Acquire, truncate any torn tail, read the head, build, validate,
        encode, write, fsync, release. Truncation lives here and only here:
        the lock is what makes "no append is in progress" knowable, and it is
        the only condition under which an unterminated tail can be called
        torn instead of in flight.

        fsync and not merely flush: the record must outlive a power cut, not
        merely a process crash. That was strong reasoning when the line was
        one of two copies; it is not optional now that it is the only one.
        """
        self.lock_path.parent.mkdir(parents=True, exist_ok=True)
        with self.lock_path.open("ab") as lock_fh:
            fcntl.flock(lock_fh.fileno(), fcntl.LOCK_EX)
            self._truncate_torn_tail()
            head = self._tail_record()
            record = build(head)
            self._check_follows(record, head)
            line = encode_record(record)  # the grammar gate, rh included
            with self.path.open("ab") as fh:
                fh.write((line + "\n").encode("utf-8"))
                fh.flush()
                os.fsync(fh.fileno())
                return record, fh.tell()

    @staticmethod
    def _check_follows(record: dict, head: dict) -> None:
        """The head checks, plus placement. Refuse before a byte is written.

        Placement is checked on the way IN as well as on the way out
        (:meth:`walk`) because the two catch different things: the walk
        catches a file someone hand-wrote, and this catches a caller — every
        append funnels through here, so ``append`` and ``append_record``
        are both covered.
        """
        if record["lin"] != head["lin"]:
            raise AppendRejected(
                f"candidate claims lineage {record['lin']!r}, "
                f"but this log's lineage is {head['lin']!r}"
            )
        if record["ord"] != head["ord"] + 1:
            raise AppendRejected(
                f"candidate carries ord {record['ord']!r}, "
                f"but the head is at {head['ord']} so {head['ord'] + 1} is due"
            )
        if record["prev"] != head[_RH]:
            raise AppendRejected(
                f"candidate's prev names {record['prev']!r}, "
                f"but the head's rh is {head[_RH]!r}"
            )
        fault = _placement_fault(record, record["ord"])
        if fault is not None:
            raise AppendRejected(f"candidate refused: {fault}")

    def _truncate_torn_tail(self) -> int:
        """Drop an unterminated final record. Returns the bytes cut.

        MUST be called with the append lock held — see
        :meth:`_append_under_lock`. Truncation, not skipping: partial bytes
        left at the tail would be concatenated onto by the next append, and
        the result would be a corrupt interior that refuses forever.
        """
        size = self._size()
        if size == 0:
            return 0
        with self.path.open("rb") as fh:
            fh.seek(size - 1)
            if fh.read(1) == b"\n":
                return 0
            cut = _last_newline_before(fh, size)
        # cut is 0 when the whole file is one partial record.
        with self.path.open("r+b") as fh:
            fh.truncate(cut)
            fh.flush()
            os.fsync(fh.fileno())
        return size - cut

    def truncate_torn_tail(self) -> int:
        """Take the lock and drop an unterminated final record.

        The public spelling, for an opener that wants the log made
        appendable without appending. Same rule: only the tail, only what
        was never complete, only under the lock.
        """
        self.lock_path.parent.mkdir(parents=True, exist_ok=True)
        with self.lock_path.open("ab") as lock_fh:
            fcntl.flock(lock_fh.fileno(), fcntl.LOCK_EX)
            return self._truncate_torn_tail()


# ---------------------------------------------------------------------------
# Authorship — the first verifier
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class KeyResolution:
    """Where one verified signature's key came from — a coordinate, always.

    One row per verified signature, and the row IS the exclusivity claim
    made checkable: ``key`` was resolved from ``(introduced_lineage,
    introduced_ordinal)`` in the log, and from nowhere else. ``ordinal`` is
    the record whose signature the key verified; ``observer`` is who the
    log says that key speaks for.
    """

    ordinal: int
    observer: str
    key: str
    introduced_lineage: str
    introduced_ordinal: int


def verify_authorship(log: ArrivalLog, verify: Verify) -> tuple[KeyResolution, ...]:
    """Verify every signature in the log, resolving keys from the log alone.

    The ruled rule, implemented verbatim (decision:design/arrival-sliceA-
    authority): **a key is valid at position N iff it was introduced at a
    position < N, or N is the genesis position and the record is
    self-certifying.** Self-certification is legal at ordinal 0 and nowhere
    else — the genesis signature must verify against its own
    ``body["key"]``, which is what turns a self-naming genesis into a
    self-certifying one. A key introduction at ordinal >= 1
    (:data:`KEY_INTRODUCTION_KIND`) is a record whose body names an
    observer and a key, signed by a key already valid for the INTRODUCING
    record's observer; only after that signature verifies does the named
    key join the registry, at the introduction's own ordinal.

    Keys are bound to observers, not free-floating (an instantiation
    decision recorded in the slice-A design fact): the genesis key speaks
    for the genesis record's observer, an introduced key for the observer
    its body names. A record's signature is tried against every key valid
    for that record's OWN observer at its position — observer-agnostic
    resolution would let one observer's record verify under another's key,
    and authorship would stop being an answer.

    Resolution consults the log and nothing else — no registry file, no
    projection, no artifact beside the log (the ruled exclusivity claim).
    ``verify`` is injected, never imported, same posture as :data:`Signer`.

    Walks the whole log via :meth:`ArrivalLog.walk`, so structural
    integrity is established for free; this is an O(n) surface where the
    whole file is the question. Unsigned non-genesis records make no
    authorship claim and produce no row. Returns one
    :class:`KeyResolution` per verified signature, in log order; raises
    :class:`AuthorshipUnverified` on the first signature that no valid key
    verifies.
    """
    # observer -> [(key, introduced_ordinal)] in introduction order.
    registry: dict[str, list[tuple[str, int]]] = {}
    rows: list[KeyResolution] = []

    for record in log.walk():
        ordinal = record["ord"]
        # The walk holds every record to the genesis's lineage, so this is
        # one value for the whole loop; re-read per record for simplicity.
        lineage = record["lin"]

        if ordinal == 0:
            # Genesis: self-certifying, and only here. The walk already held
            # it to every structural genesis rule, key shape included.
            key = record["body"]["key"]
            digest = _commitment_of(record)
            if not verify(key, record[_SIG], digest):
                raise AuthorshipUnverified(
                    "genesis signature does not verify against the founding "
                    "key its own body carries — the log is not "
                    "self-certifying",
                    0,
                )
            registry[record["observer"]] = [(key, 0)]
            rows.append(
                KeyResolution(
                    ordinal=0,
                    observer=record["observer"],
                    key=key,
                    introduced_lineage=record["lin"],
                    introduced_ordinal=0,
                )
            )
            continue

        if _SIG in record:
            rows.append(_resolve(record, registry, lineage, verify))
        if record["k"] == KEY_INTRODUCTION_KIND:
            # The signature just verified under an already-valid key (the
            # placement rules make an unsigned introduction unspellable),
            # so the named key joins the registry at THIS ordinal: valid
            # strictly after it, per the ruled clause.
            named = record["body"]["observer"]
            registry.setdefault(named, []).append((record["body"]["key"], ordinal))

    return tuple(rows)


def _resolve(
    record: dict,
    registry: dict[str, list[tuple[str, int]]],
    lineage: str,
    verify: Verify,
) -> KeyResolution:
    """Resolve the key that verifies ``record``'s signature, or refuse.

    Tries, in introduction order, every key the log introduced for this
    record's observer at a position strictly before the record's own. The
    record's own body is deliberately never consulted — that would be
    self-certification above ordinal 0, which the ruled rule forbids.
    """
    ordinal = record["ord"]
    digest = _commitment_of(record)
    candidates = [
        (key, introduced)
        for key, introduced in registry.get(record["observer"], [])
        if introduced < ordinal
    ]
    for key, introduced in candidates:
        if verify(key, record[_SIG], digest):
            return KeyResolution(
                ordinal=ordinal,
                observer=record["observer"],
                key=key,
                introduced_lineage=lineage,
                introduced_ordinal=introduced,
            )
    if not candidates:
        raise AuthorshipUnverified(
            f"no key valid for observer {record['observer']!r} at this "
            "position — a key is valid at N only when introduced at a "
            "position strictly before N",
            ordinal,
        )
    raise AuthorshipUnverified(
        f"signature verifies under none of the {len(candidates)} key(s) the "
        f"log introduced for observer {record['observer']!r} before this "
        "position",
        ordinal,
    )


def _commitment_of(record: dict) -> str:
    """The content commitment a record's signature covers."""
    return content_commitment(
        record["k"], record["at"], record["observer"], record["origin"],
        record["body"],
    )


# ---------------------------------------------------------------------------
# Byte helpers
# ---------------------------------------------------------------------------


def _last_newline_before(fh, end: int) -> int:
    """Byte offset just past the last ``\\n`` strictly before ``end``.

    Scans backwards in chunks — never loads the whole log, and never gives up
    as a function of line length. 0 when there is none.
    """
    pos = end
    while pos > 0:
        start = max(0, pos - _CHUNK)
        fh.seek(start)
        chunk = fh.read(pos - start)
        idx = chunk.rfind(b"\n")
        if idx != -1:
            return start + idx + 1
        pos = start
    return 0


def _fsync_dir(directory: Path) -> None:
    """fsync a directory so a newly created entry survives a power cut."""
    fd = os.open(str(directory), os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)
