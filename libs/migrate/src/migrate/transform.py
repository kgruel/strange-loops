"""Migration sidecar transformer: legacy rows -> Arrival record drafts.

Deterministic mapping of legacy store contents (JSONL lines or SQLite tables)
into an ordered, deterministic sequence of arrival record drafts (:class:`RecordDraft`)
ready for ingestion by the Arrival sink via standard contract append operations.

Security and Authority Model: Why Migrated Records are OUTER-UNSIGNED
---------------------------------------------------------------------
The migration sidecar holds only one private key: the vertex's own self-observer key.
The ``.vertex`` observers block carries public keys for observers.
Under the wire-v1 pin (:data:`decision:design/arrival-wire-v1-pin`), an ordinary fact
or batch record's envelope ``observer`` field is the author echo, and
``verify_authorship`` verifies an envelope's signature strictly against keys valid
for that record's own envelope observer (:mod:`engine.arrival`).

The sidecar cannot sign a migrated fact or batch envelope without either forging
an authorship claim or misrepresenting the envelope observer as the custodian.
It does not have to. Unsigned ordinary records are completely legal under Arrival
protocol and are skipped by the authority walk (:mod:`engine.arrival`, lines 2044-2045).
Only genesis and key introductions are structurally required to carry an envelope signature.

Crucially:
- The authored fact inner signature rides in the row body verbatim (byte-for-byte),
  never re-serialized, never re-signed.
- Key introductions establish the key registry for FUTURE live writes to the migrated
  store — they do NOT validate migrated content.
- A reader who assumes key introductions validate migrated legacy content has the
  security model backwards: legacy content authorship is proven by inner fact-domain
  signatures verified by the existing fact verifier.
- The custody claim over the migration as a whole is established by the signed genesis
  minted under the custodian plus the bootstrap witness receipt.

Ordering and Authority Clause
-----------------------------
1. Genesis (ordinal 0): minted by the sink / wrapper under the custodian key.
2. Key introductions (ordinals 1..k): one per declared observer carrying a public key
   (excluding the custodian, who is established at ordinal 0). Each introduction draft
   names ``observer = custodian`` and is signed by the custodian, satisfying the Arrival
   authority clause (:mod:`engine.arrival`, lines 1962-1970).
3. Migrated records (ordinals k+1..): fact, batch, and tick records in ruled source order,
   outer-unsigned (``signature = None``).

Native Tick Conversion (M-4)
----------------------------
Legacy ticks convert to native Arrival ``tick`` records (not ``tick.<name>`` facts).
The tick's signed envelope and chain fields ride byte-for-byte in the tick body so
original signatures verify. The tick record's envelope observer is the destination log's
genesis observer (the custodian), per the wire-v1 pin.

Group Grammar and Seam Defense
------------------------------
- One legal single-observer legacy batch line -> ONE Arrival batch record (:class:`RecordDraft`).
- One flat fact row -> ONE Arrival fact record.
- The transformer never regroups or splits batches (backend contract §04).
- Defective legacy lines (mixed-observer batches, absent-observer batches, codec-invalid rows)
  are refused with typed :class:`LegacySourceRefused` exceptions (defense at the seam).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from engine.arrival import (
    KEY_INTRODUCTION_KIND,
    Signer,
    _key_shape_fault,
    content_commitment,
)
from engine.arrival_body import (
    body_of_batch,
    body_of_fact_row,
    body_of_tick_row,
)
from engine.arrival_contract import RecordDraft
from lang import ObserverDecl, VertexFile, parse_vertex, parse_vertex_file

from .legacy_ids import FactRow, Transform, identity
from .legacy_source import BatchUnit, FlatFactUnit, LegacySource, TickUnit
from .refusals import (
    BatchRegroupRefused,
    DeclarationKeyRefused,
    MissingCustodianKeyRefused,
)

__all__ = [
    "GenesisRequirements",
    "DroppedUnit",
    "TransformExceptions",
    "TransformResult",
    "coerce_vertex",
    "transform",
]


@dataclass(frozen=True)
class GenesisRequirements:
    """Requirements for minting the Arrival log's genesis record (ordinal 0)."""

    custodian: str
    key: str


@dataclass(frozen=True)
class DroppedUnit:
    """A legacy record unit dropped entirely by a transform rule (§I.1)."""

    coordinate: int
    kind: str
    rule: str
    fact_kinds: tuple[str, ...] = ()
    observers: tuple[str, ...] = ()


@dataclass(frozen=True)
class TransformExceptions:
    """Exception edges encountered during transformation (§G.3).

    Location claims about what the declaration and legacy source cover:
    - keyless_declared_observers: declared in .vertex with key=None
      (skipped from key introductions).
    - undeclared_row_observers: observed in migrated rows but absent from .vertex observers.
    - dropped_units: units dropped entirely by a transform rule.
    """

    keyless_declared_observers: tuple[str, ...]
    undeclared_row_observers: tuple[str, ...]
    dropped_units: tuple[DroppedUnit, ...] = ()


@dataclass(frozen=True)
class TransformResult:
    """Output of legacy store transformation."""

    drafts: tuple[RecordDraft, ...]
    exceptions: TransformExceptions
    genesis: GenesisRequirements


def coerce_vertex(vertex: VertexFile | Path | str) -> VertexFile:
    """Explicit helper to coerce Path, str, or VertexFile into a VertexFile at the call boundary."""
    if isinstance(vertex, VertexFile):
        return vertex
    if isinstance(vertex, Path):
        return parse_vertex_file(vertex)
    if isinstance(vertex, str):
        p = Path(vertex)
        if p.exists() and p.is_file():
            return parse_vertex_file(p)
        return parse_vertex(vertex)
    raise TypeError(f"vertex must be VertexFile, Path, or str, got {type(vertex).__name__}")


def transform(
    source: Path | str,
    vertex: VertexFile,
    rule: Transform | None = None,
    *,
    signer: Signer,
) -> TransformResult:
    """Transform legacy store rows into an ordered, deterministic sequence of arrival record drafts.

    The custodian identity is derived from the custody self-observer definition
    (the vertex file stem, as custody/signing.py defines it).

    Args:
        source: Path to legacy .jsonl or .sqlite store.
        vertex: Parsed VertexFile declaration. Use :func:`coerce_vertex` to parse from path/str.
        rule: Deterministic per-fact transform rule (defaults to identity()).
        signer: Required injected Signer for custodian signatures on key introductions.

    Returns:
        TransformResult containing:
        - drafts: tuple of RecordDraft objects (key introductions followed by migrated records).
        - exceptions: TransformExceptions tracking §G.3 edges and dropped units.
        - genesis: GenesisRequirements naming the custodian identity and founding public key.

    Raises:
        TypeError: If vertex is not a VertexFile.
        FileNotFoundError: If source does not exist.
        LegacySourceRefused: If source contains codec-invalid lines, mixed-observer batches,
            or absent/empty-observer rows.
        MissingCustodianKeyRefused: If custodian public key cannot be resolved from declaration.
        DeclarationKeyRefused: If any declared observer key has an invalid shape.
        BatchRegroupRefused: If a transform rule drops some but not all rows of a batch group.
    """
    if not isinstance(vertex, VertexFile):
        raise TypeError(
            f"vertex must be VertexFile, got {type(vertex).__name__}. "
            "Use coerce_vertex() to parse from a Path or str at the call boundary."
        )

    t_rule = rule if rule is not None else identity()

    cust_name = vertex.path.stem if vertex.path is not None else vertex.name
    decl_map: dict[str, ObserverDecl] = {
        o.name: o for o in (vertex.observers or ())
    }
    cust_decl = decl_map.get(cust_name)
    cust_k = cust_decl.key if cust_decl else None
    if cust_k is None:
        raise MissingCustodianKeyRefused(
            f"Custodian {cust_name!r} has no public key declared in .vertex observers block"
        )

    # Validate declared key shapes (F5)
    cust_key_fault = _key_shape_fault(cust_k)
    if cust_key_fault is not None:
        raise DeclarationKeyRefused(
            "Migration refused: declaration carries a key of the wrong shape for "
            f"custodian {cust_name!r}: {cust_key_fault}"
        )

    for decl in (vertex.observers or ()):
        if decl.key is not None:
            fault = _key_shape_fault(decl.key)
            if fault is not None:
                raise DeclarationKeyRefused(
                    "Migration refused: declaration carries a key of the wrong shape for "
                    f"{decl.name!r}: {fault}"
                )

    genesis_req = GenesisRequirements(custodian=cust_name, key=cust_k)

    drafts: list[RecordDraft] = []
    keyless_declared: list[str] = []
    declared_names = set(decl_map.keys())

    # Build key introduction drafts
    for decl in (vertex.observers or ()):
        if decl.name == cust_name:
            continue
        if not decl.key:
            keyless_declared.append(decl.name)
            continue
        body = {"observer": decl.name, "key": decl.key}
        commitment = content_commitment(
            KEY_INTRODUCTION_KIND,
            0.0,
            cust_name,
            "",
            body,
        )
        sig = signer(cust_name, commitment)
        drafts.append(
            RecordDraft(
                kind=KEY_INTRODUCTION_KIND,
                authored_at=0.0,
                observer=cust_name,
                origin="",
                body=body,
                signature=sig,
            )
        )

    # Read legacy source via shared validated stream layer
    src = LegacySource.read(source)

    seen_observers: set[str] = set()
    dropped_units: list[DroppedUnit] = []

    for unit in src.units:
        if isinstance(unit, FlatFactUnit):
            seen_observers.add(unit.row.observer)
            mapped = t_rule.map_fact(unit.row)
            if mapped is None:
                dropped_units.append(
                    DroppedUnit(
                        coordinate=unit.coordinate,
                        kind="fact",
                        rule=t_rule.rule,
                        fact_kinds=(unit.row.kind,),
                        observers=(unit.row.observer,),
                    )
                )
                continue
            row_tuple = (
                mapped.id,
                mapped.kind,
                mapped.ts,
                mapped.observer,
                mapped.origin,
                mapped.payload,
                mapped.signature,
            )
            body = body_of_fact_row(row_tuple)
            drafts.append(
                RecordDraft(
                    kind="fact",
                    authored_at=mapped.ts,
                    observer=mapped.observer,
                    origin=mapped.origin,
                    body=body,
                    signature=None,
                )
            )

        elif isinstance(unit, BatchUnit):
            seen_observers.add(unit.observer)
            mapped_rows: list[FactRow] = []
            for r in unit.rows:
                mf = t_rule.map_fact(r)
                if mf is not None:
                    mapped_rows.append(mf)

            if not mapped_rows:
                dropped_units.append(
                    DroppedUnit(
                        coordinate=unit.coordinate,
                        kind="batch",
                        rule=t_rule.rule,
                        fact_kinds=tuple(r.kind for r in unit.rows),
                        observers=tuple(r.observer for r in unit.rows),
                    )
                )
                continue

            if len(mapped_rows) != len(unit.rows):
                raise BatchRegroupRefused(
                    f"Transform rule {t_rule.rule!r} dropped {len(unit.rows) - len(mapped_rows)} "
                    f"of {len(unit.rows)} rows in batch at line {unit.coordinate}. "
                    "Dropping partial batch rows is refused: the sidecar cannot re-decide a "
                    "ceremony's composition (refuse-not-split)."
                )

            first = mapped_rows[0]
            row_tuples = [
                (r.id, r.kind, r.ts, r.observer, r.origin, r.payload, r.signature)
                for r in mapped_rows
            ]
            body = body_of_batch(row_tuples)
            drafts.append(
                RecordDraft(
                    kind="batch",
                    authored_at=first.ts,
                    observer=first.observer,
                    origin=first.origin,
                    body=body,
                    signature=None,
                )
            )

        elif isinstance(unit, TickUnit):
            body = body_of_tick_row(unit.tuple_form)
            drafts.append(
                RecordDraft(
                    kind="tick",
                    authored_at=unit.ts,
                    observer=cust_name,
                    origin=unit.origin,
                    body=body,
                    signature=None,
                )
            )

    undeclared_observers = tuple(sorted(seen_observers - declared_names))
    exceptions = TransformExceptions(
        keyless_declared_observers=tuple(keyless_declared),
        undeclared_row_observers=undeclared_observers,
        dropped_units=tuple(dropped_units),
    )

    return TransformResult(
        drafts=tuple(drafts),
        exceptions=exceptions,
        genesis=genesis_req,
    )
