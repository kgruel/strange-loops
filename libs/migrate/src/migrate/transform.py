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
from typing import TYPE_CHECKING

from engine.arrival import KEY_INTRODUCTION_KIND, Signer, content_commitment
from engine.arrival_body import (
    body_of_batch,
    body_of_fact_row,
    body_of_tick_row,
)
from engine.arrival_contract import RecordDraft
from lang import ObserverDecl, VertexFile, parse_vertex, parse_vertex_file

from .legacy_ids import FactRow, Transform, identity
from .legacy_jsonl import (
    _BATCH,
    _BATCH_KEYS,
    _MIN_BATCH_ROWS,
    _ROWS,
    _SPEC,
    FACT_FIELDS,
    FACT_NULLABLE,
    TICK_FIELDS,
    TICK_NULLABLE,
    JsonlCodecError,
    load_line,
    row_object_fault,
)
from .legacy_sqlite import (
    open_legacy_sqlite,
    read_facts,
    read_ticks,
)
from .refusals import LegacySourceRefused

__all__ = [
    "GenesisRequirements",
    "TransformExceptions",
    "TransformResult",
    "transform",
]


@dataclass(frozen=True)
class GenesisRequirements:
    """Requirements for minting the Arrival log's genesis record (ordinal 0)."""

    custodian: str
    key: str


@dataclass(frozen=True)
class TransformExceptions:
    """Exception edges encountered during transformation (§G.3).

    Location claims about what the declaration and legacy source cover:
    - keyless_declared_observers: declared in .vertex with key=None (skipped from key introductions).
    - undeclared_row_observers: observed in migrated rows but absent from .vertex observers.
    """

    keyless_declared_observers: tuple[str, ...]
    undeclared_row_observers: tuple[str, ...]


@dataclass(frozen=True)
class TransformResult:
    """Output of legacy store transformation."""

    drafts: tuple[RecordDraft, ...]
    exceptions: TransformExceptions
    genesis: GenesisRequirements


def transform(
    source: Path | str,
    vertex: VertexFile | Path | str,
    rule: Transform | None = None,
    *,
    signer: Signer | None = None,
    custodian: str | None = None,
    custodian_key: str | None = None,
) -> TransformResult:
    """Transform legacy store rows into an ordered, deterministic sequence of arrival record drafts.

    Args:
        source: Path to legacy .jsonl or .sqlite store.
        vertex: Parsed VertexFile, Path to .vertex file, or .vertex KDL text.
        rule: Deterministic per-fact transform rule (defaults to identity()).
        signer: Injected Signer for custodian signatures on key introductions.
        custodian: Custodian observer name override (defaults to vertex.name).
        custodian_key: Custodian public key override (defaults to declared key for custodian).

    Returns:
        TransformResult containing:
        - drafts: tuple of RecordDraft objects (key introductions followed by migrated records).
        - exceptions: TransformExceptions tracking §G.3 edges (keyless declared, undeclared in rows).
        - genesis: GenesisRequirements naming the custodian identity and founding public key.

    Raises:
        FileNotFoundError: If source does not exist.
        LegacySourceRefused: If source contains codec-invalid lines, mixed-observer batches,
            or absent-observer batches.
        ValueError: If custodian public key cannot be resolved from declaration.
    """
    source_path = Path(source).resolve()
    if not source_path.exists():
        raise FileNotFoundError(f"Legacy source not found: {source_path}")

    # 1. Resolve vertex declaration
    if isinstance(vertex, VertexFile):
        vf = vertex
    elif isinstance(vertex, Path):
        vf = parse_vertex_file(vertex)
    elif isinstance(vertex, str):
        p = Path(vertex)
        if p.exists() and p.is_file():
            vf = parse_vertex_file(p)
        else:
            vf = parse_vertex(vertex)
    else:
        raise TypeError(f"vertex must be VertexFile, Path, or str, got {type(vertex).__name__}")

    # 2. Resolve transform rule
    t_rule = rule if rule is not None else identity()

    # 3. Resolve custodian and founding key
    cust_name = custodian or vf.name
    decl_map: dict[str, ObserverDecl] = {
        o.name: o for o in (vf.observers or ())
    }
    cust_decl = decl_map.get(cust_name)
    cust_k = custodian_key or (cust_decl.key if cust_decl else None)
    if cust_k is None:
        raise ValueError(
            f"Custodian {cust_name!r} has no public key declared in .vertex observers block"
        )
    genesis_req = GenesisRequirements(custodian=cust_name, key=cust_k)

    # 4. Build key introduction drafts and track keyless declared observers (§G.3 edge 1)
    drafts: list[RecordDraft] = []
    keyless_declared: list[str] = []
    declared_names = set(decl_map.keys())

    for decl in (vf.observers or ()):
        if decl.name == cust_name:
            # Genesis at ordinal 0 establishes custodian's founding key
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
        sig = signer(cust_name, commitment) if signer is not None else None
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

    # 5. Transform source rows in ruled source order
    seen_observers: set[str] = set()

    with source_path.open("rb") as f_peek:
        header = f_peek.read(16)
    is_sqlite = header.startswith(b"SQLite format 3\x00") or source_path.suffix in (".sqlite", ".db")

    if is_sqlite:
        conn = open_legacy_sqlite(source_path)
        try:
            # Facts in rowid order
            for fr in read_facts(conn):
                if fr.observer:
                    seen_observers.add(fr.observer)
                mapped = t_rule.map_fact(fr)
                if mapped is None:
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

            # Ticks in rowid order (M-4 native tick records)
            for t_dict in read_ticks(conn):
                tick_tuple = (
                    t_dict["id"],
                    t_dict["name"],
                    t_dict["ts"],
                    t_dict.get("since"),
                    t_dict["origin"],
                    t_dict["payload"],
                    t_dict.get("prev_hash"),
                    t_dict.get("window_start"),
                    t_dict.get("fact_cursor"),
                    t_dict.get("window_hash"),
                    t_dict.get("signature"),
                )
                body = body_of_tick_row(tick_tuple)
                drafts.append(
                    RecordDraft(
                        kind="tick",
                        authored_at=t_dict["ts"],
                        observer=cust_name,
                        origin=t_dict["origin"],
                        body=body,
                        signature=None,
                    )
                )
        finally:
            conn.close()

    else:
        # JSONL line order
        codec_invalid_lines: list[tuple[int, str]] = []
        mixed_observer_lines: list[tuple[int, tuple[str, ...], int]] = []
        absent_observer_lines: list[tuple[int, int, tuple[str, ...]]] = []

        with source_path.open("r", encoding="utf-8") as f:
            for lineno, line in enumerate(f, start=1):
                if not line.strip():
                    continue
                try:
                    obj = load_line(line)
                except JsonlCodecError as exc:
                    codec_invalid_lines.append((lineno, str(exc)))
                    continue

                t = obj.get("t")
                if t == "fact":
                    fault = row_object_fault(
                        obj,
                        t="fact",
                        frame="line",
                        fields=FACT_FIELDS,
                        allowed=_SPEC["fact"].allowed,
                        nullable=FACT_NULLABLE,
                    )
                    if fault is not None:
                        codec_invalid_lines.append((lineno, fault))
                        continue
                    obs = obj["observer"]
                    if obs:
                        seen_observers.add(obs)
                    fr = FactRow(
                        id=obj["id"],
                        kind=obj["kind"],
                        ts=obj["ts"],
                        observer=obs,
                        origin=obj["origin"],
                        payload=obj["payload"],
                        signature=obj.get("signature"),
                    )
                    mapped = t_rule.map_fact(fr)
                    if mapped is None:
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

                elif t == "tick":
                    fault = row_object_fault(
                        obj,
                        t="tick",
                        frame="line",
                        fields=TICK_FIELDS,
                        allowed=_SPEC["tick"].allowed,
                        nullable=TICK_NULLABLE,
                    )
                    if fault is not None:
                        codec_invalid_lines.append((lineno, fault))
                        continue
                    tick_tuple = (
                        obj["id"],
                        obj["name"],
                        obj["ts"],
                        obj.get("since"),
                        obj["origin"],
                        obj["payload"],
                        obj.get("prev_hash"),
                        obj.get("window_start"),
                        obj.get("fact_cursor"),
                        obj.get("window_hash"),
                        obj.get("signature"),
                    )
                    body = body_of_tick_row(tick_tuple)
                    drafts.append(
                        RecordDraft(
                            kind="tick",
                            authored_at=obj["ts"],
                            observer=cust_name,
                            origin=obj["origin"],
                            body=body,
                            signature=None,
                        )
                    )

                elif t == _BATCH:
                    # 1. Envelope validation
                    unknown_env = sorted(set(obj) - _BATCH_KEYS)
                    if unknown_env:
                        codec_invalid_lines.append((lineno, f"unknown field(s) in batch line: {unknown_env}"))
                        continue
                    rows = obj.get(_ROWS)
                    if not isinstance(rows, list):
                        codec_invalid_lines.append(
                            (
                                lineno,
                                f"batch field 'rows' must be an array of fact records, got {type(rows).__name__}",
                            )
                        )
                        continue
                    if len(rows) < _MIN_BATCH_ROWS:
                        codec_invalid_lines.append(
                            (
                                lineno,
                                f"batch must carry at least {_MIN_BATCH_ROWS} rows, got {len(rows)} — "
                                "a 1-row batch is a second spelling of a plain fact line, and an empty one encodes nothing",
                            )
                        )
                        continue

                    # 2. Rows validation
                    batch_fault: str | None = None
                    seen_ids: set[str] = set()
                    absent_count = 0
                    present_observers: set[str] = set()
                    for i, elem in enumerate(rows):
                        if not isinstance(elem, dict):
                            batch_fault = f"batch row {i} must be a JSON object, got {type(elem).__name__}"
                            break
                        elem_t = elem.get("t")
                        if elem_t == _BATCH:
                            batch_fault = f"batch row {i} is a nested batch — batches do not nest"
                            break
                        if elem_t == "tick":
                            batch_fault = (
                                f"batch row {i} is a tick record — ticks are minted one-at-a-time and chain-linked, never batched"
                            )
                            break
                        if elem_t != "fact":
                            batch_fault = f"batch row {i} has unknown record discriminator t={elem_t!r}"
                            break
                        fault = row_object_fault(
                            elem,
                            t="fact",
                            frame="line",
                            fields=FACT_FIELDS,
                            allowed=_SPEC["fact"].allowed,
                            nullable=FACT_NULLABLE,
                            skip_fields=frozenset({"observer"}),
                        )
                        if fault is not None:
                            batch_fault = fault
                            break
                        if "observer" not in elem or elem["observer"] is None:
                            absent_count += 1
                        else:
                            obs_val = elem["observer"]
                            if not isinstance(obs_val, str):
                                batch_fault = f"fact field 'observer' must be a string, got {type(obs_val).__name__}"
                                break
                            present_observers.add(obs_val)

                        row_id = elem["id"]
                        if row_id in seen_ids:
                            batch_fault = f"duplicate id {row_id!r} within one batch"
                            break
                        seen_ids.add(row_id)

                    if batch_fault is not None:
                        codec_invalid_lines.append((lineno, batch_fault))
                        continue

                    # 3. Observer conditions
                    if len(present_observers) > 1:
                        mixed_observer_lines.append(
                            (lineno, tuple(sorted(present_observers)), absent_count)
                        )
                        continue
                    if absent_count > 0:
                        absent_observer_lines.append(
                            (lineno, absent_count, tuple(sorted(present_observers)))
                        )
                        continue

                    # 4. Valid single-observer batch
                    batch_obs = next(iter(present_observers))
                    seen_observers.add(batch_obs)

                    mapped_rows: list[FactRow] = []
                    for elem in rows:
                        fr = FactRow(
                            id=elem["id"],
                            kind=elem["kind"],
                            ts=elem["ts"],
                            observer=elem["observer"],
                            origin=elem["origin"],
                            payload=elem["payload"],
                            signature=elem.get("signature"),
                        )
                        mf = t_rule.map_fact(fr)
                        if mf is not None:
                            mapped_rows.append(mf)

                    if not mapped_rows:
                        continue
                    if len(mapped_rows) == 1:
                        r = mapped_rows[0]
                        row_tuple = (r.id, r.kind, r.ts, r.observer, r.origin, r.payload, r.signature)
                        body = body_of_fact_row(row_tuple)
                        drafts.append(
                            RecordDraft(
                                kind="fact",
                                authored_at=r.ts,
                                observer=r.observer,
                                origin=r.origin,
                                body=body,
                                signature=None,
                            )
                        )
                    else:
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

                else:
                    codec_invalid_lines.append((lineno, f"unknown record discriminator t={t!r}"))
                    continue

        if codec_invalid_lines or mixed_observer_lines or absent_observer_lines:
            raise LegacySourceRefused(
                codec_invalid_lines=codec_invalid_lines,
                mixed_observer_lines=mixed_observer_lines,
                absent_observer_lines=absent_observer_lines,
                source=str(source_path),
            )

    # 6. Build exception report (§G.3 edges)
    undeclared_observers = tuple(sorted(seen_observers - declared_names))
    exceptions = TransformExceptions(
        keyless_declared_observers=tuple(keyless_declared),
        undeclared_row_observers=undeclared_observers,
    )

    return TransformResult(
        drafts=tuple(drafts),
        exceptions=exceptions,
        genesis=genesis_req,
    )
