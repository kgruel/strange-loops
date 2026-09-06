"""Pure declaration-history checks for Arrival boundary consumption edges.

The supported Arrival runtime rebuilds current fold state from facts, but old
owned ticks remain reset/count/period edges.  This module establishes that a
current consumer has one continuous declared role for each edge it will use.
It deliberately performs no custody, projection, signing, or source execution.
"""

from __future__ import annotations

import copy
import hashlib
import re
from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from lang.document import (
    DECL_GENESIS,
    DECL_KIND_DEFINED,
    DECL_LENS_DEFINED,
    DECL_SOURCE_DEFINED,
    DECL_VERTEX_DEFINED,
    DECLARATION_PROTOCOL_VERSION,
    DEFINED_TO_TOMBSTONE,
    is_internal_kind,
)

from .arrival_contract import DeclarationAnchor, Fact, Tick
from .declaration import (
    DeclarationResolutionError,
    UnadoptedLineage,
    UnsupportedProtocol,
)

__all__ = [
    "BoundaryContinuityConflict",
    "BoundaryContinuityIssue",
    "BoundaryContinuityResult",
    "DeclarationDocumentRevision",
    "analyze_boundary_continuity",
    "collect_verified_parameter_rows",
    "declaration_document_revisions",
]


BoundaryContinuityReason = Literal[
    "prior-incarnation",
    "ambiguous-tick-role",
    "unproven-loop-role",
    "unproven-generated-incarnation",
    "invalid-projection-shape",
    "runtime-namespace-mismatch",
    "reserved-runtime-name",
]


@dataclass(frozen=True)
class BoundaryContinuityIssue:
    """Stable, payload-free evidence for one refused continuity claim."""

    reason: BoundaryContinuityReason
    vertex_name: str
    loop_name: str | None = None
    tick_id: str | None = None
    tick_ordinal: int | None = None
    tick_seq: int | None = None
    declaration_fact_id: str | None = None
    declaration_ordinal: int | None = None
    detail: str = ""


class BoundaryContinuityConflict(Exception):
    """The bounded declaration/tick evidence cannot license current replay."""

    def __init__(self, issue: BoundaryContinuityIssue) -> None:
        super().__init__(issue.detail or issue.reason.replace("-", " "))
        self.issue = issue
        self.tick_id = issue.tick_id
        self.ordinal = issue.tick_ordinal
        self.fact_id = issue.declaration_fact_id
        self.vertex = issue.vertex_name


@dataclass(frozen=True)
class BoundaryContinuityResult:
    """The target namespace established by the analyzed document history."""

    provable_names: frozenset[str]
    has_unknown_generators: bool
    vertex_name: str
    has_vertex_boundary: bool


@dataclass(frozen=True)
class DeclarationDocumentRevision:
    """One atomically observable own-declaration namespace revision."""

    arrival_ordinal: int | None
    fact_ids: tuple[str, ...]
    document_fact_ids: tuple[tuple[str, str, str], ...]
    documents: tuple[Mapping[str, Any], ...]
    proposed: bool = False


@dataclass(frozen=True)
class _Namespace:
    names: frozenset[str]
    unknown_generator: bool
    vertex_name: str
    has_vertex_boundary: bool

    def membership(self, name: str) -> Literal["present", "absent", "unknown"]:
        if name in self.names:
            return "present"
        return "unknown" if self.unknown_generator else "absent"


_TOMBSTONE_TO_DEFINED = {
    tombstone: defined for defined, tombstone in DEFINED_TO_TOMBSTONE.items()
}
_DEFINED_KINDS = frozenset(DEFINED_TO_TOMBSTONE) | {
    DECL_LENS_DEFINED,
    DECL_VERTEX_DEFINED,
}
_ENV_VALUE = re.compile(r"\$[A-Za-z_][A-Za-z0-9_]*\Z")


def _copy_documents(
    documents: Sequence[Mapping[str, Any]],
) -> tuple[Mapping[str, Any], ...]:
    return tuple(copy.deepcopy(dict(document)) for document in documents)


def _document_map(
    documents: Sequence[Mapping[str, Any]],
) -> dict[tuple[str, str], dict[str, Any]]:
    mapped: dict[tuple[str, str], dict[str, Any]] = {}
    for document in documents:
        kind = document["kind"]
        subject = document["subject"]
        mapped[(kind, subject)] = copy.deepcopy(dict(document))
    return mapped


def _documents_tuple(
    mapped: Mapping[tuple[str, str], Mapping[str, Any]],
) -> tuple[Mapping[str, Any], ...]:
    return tuple(copy.deepcopy(dict(document)) for document in mapped.values())


def declaration_document_revisions(
    anchor: DeclarationAnchor,
    facts: Sequence[Fact],
    *,
    target_documents: Sequence[Mapping[str, Any]] | None = None,
) -> tuple[DeclarationDocumentRevision, ...]:
    """Return genesis, own-overlay groups, and an optional proposed target.

    Foreign declaration rows are intentionally excluded before any caller can
    inspect their source paths.  Rows sharing an Arrival ordinal are applied in
    sequence and exposed as one observable revision.
    """
    internal = sorted(
        (fact for fact in facts if is_internal_kind(fact.kind)),
        key=lambda fact: (fact.arrival_ordinal, fact.arrival_seq),
    )
    if anchor.own_lineage is None:
        if any(fact.kind == DECL_GENESIS for fact in internal):
            raise UnadoptedLineage(
                "declaration genesis rows occur without an own-lineage marker"
            )
        raise DeclarationResolutionError(
            "boundary continuity requires a historized own declaration"
        )
    genesis = anchor.genesis
    if (
        genesis is None
        or genesis.id != anchor.own_lineage
        or genesis.kind != DECL_GENESIS
    ):
        raise DeclarationResolutionError(
            "own-lineage declaration marker has no matching genesis"
        )
    protocol = genesis.payload.get("protocol", 1)
    if protocol > DECLARATION_PROTOCOL_VERSION:
        raise UnsupportedProtocol(
            f"genesis protocol {protocol} exceeds supported "
            f"{DECLARATION_PROTOCOL_VERSION}"
        )

    mapped = _document_map(genesis.payload.get("documents", ()))
    revisions = [
        DeclarationDocumentRevision(
            arrival_ordinal=genesis.arrival_ordinal,
            fact_ids=(genesis.id,),
            document_fact_ids=(),
            documents=_documents_tuple(mapped),
        )
    ]
    grouped: dict[int, list[Fact]] = {}
    for fact in internal:
        if fact.kind == DECL_GENESIS:
            continue
        if fact.arrival_ordinal < genesis.arrival_ordinal:
            # A self-scoped overlay cannot establish a runtime definition
            # before the declaration genesis that licenses its lineage.
            continue
        payload = fact.payload
        if payload.get("lineage") != anchor.own_lineage:
            continue
        if fact.kind not in _DEFINED_KINDS and fact.kind not in _TOMBSTONE_TO_DEFINED:
            continue
        grouped.setdefault(fact.arrival_ordinal, []).append(fact)

    for ordinal in sorted(grouped):
        group = grouped[ordinal]
        for fact in group:
            payload = fact.payload
            subject = payload.get("subject")
            if fact.kind in _TOMBSTONE_TO_DEFINED:
                mapped.pop((_TOMBSTONE_TO_DEFINED[fact.kind], subject), None)
            else:
                mapped[(fact.kind, subject)] = {
                    "kind": fact.kind,
                    "subject": subject,
                    "payload": copy.deepcopy(payload.get("payload", {})),
                }
        revisions.append(
            DeclarationDocumentRevision(
                arrival_ordinal=ordinal,
                fact_ids=tuple(fact.id for fact in group),
                document_fact_ids=tuple(
                    (fact.kind, str(fact.payload.get("subject")), fact.id)
                    for fact in group
                ),
                documents=_documents_tuple(mapped),
            )
        )

    if target_documents is not None:
        target = _copy_documents(target_documents)
        if not revisions or target != revisions[-1].documents:
            revisions.append(
                DeclarationDocumentRevision(
                    arrival_ordinal=None,
                    fact_ids=(),
                    document_fact_ids=(),
                    documents=target,
                    proposed=True,
                )
            )
    return tuple(revisions)


def collect_verified_parameter_rows(
    anchor: DeclarationAnchor,
    facts: Sequence[Fact],
    *,
    target_documents: Sequence[Mapping[str, Any]],
    base_dir: Path,
) -> dict[str, tuple[Mapping[str, str], ...]]:
    """Read, hash, and parse own historical pinned parameter snapshots.

    Missing, changed, unpinned, or malformed historical inputs remain unknown;
    they do not poison an unrelated direct loop.  Current runtime pin checks
    remain a separate existing gate.
    """
    from .compiler import parse_source_params_bytes

    verified: dict[str, tuple[Mapping[str, str], ...]] = {}
    revisions = declaration_document_revisions(
        anchor, facts, target_documents=target_documents
    )
    for revision in revisions:
        for document in revision.documents:
            if document.get("kind") != DECL_SOURCE_DEFINED:
                continue
            payload = document.get("payload", {})
            if payload.get("form") != "template" or payload.get("loop") is None:
                continue
            from_document = payload.get("from")
            if not isinstance(from_document, Mapping):
                continue
            pin = from_document.get("params_sha256")
            path_text = from_document.get("path")
            if not isinstance(pin, str) or not isinstance(path_text, str):
                continue
            if pin in verified:
                continue
            path = Path(path_text)
            candidate = path if path.is_absolute() else base_dir / path
            try:
                data = candidate.read_bytes()
                if hashlib.sha256(data).hexdigest() != pin:
                    continue
                rows = parse_source_params_bytes(data, source=candidate)
            except (OSError, UnicodeError, ValueError):
                continue
            verified[pin] = tuple(dict(row.values) for row in rows)
    return verified


def _literal_kind(value: object) -> tuple[str | None, bool]:
    if not isinstance(value, str) or not value:
        return None, False
    if value.startswith("$$"):
        return value[1:], False
    if _ENV_VALUE.fullmatch(value):
        return None, True
    return value, False


def _namespace(
    documents: Sequence[Mapping[str, Any]],
    verified_params: Mapping[str, Sequence[Mapping[str, str]]],
) -> _Namespace:
    names = {"cite"}
    unknown = False
    vertex_name: str | None = None
    has_vertex_boundary = False
    for document in documents:
        kind = document.get("kind")
        subject = document.get("subject")
        payload = document.get("payload", {})
        if kind == DECL_VERTEX_DEFINED:
            candidate = payload.get("name")
            if not isinstance(candidate, str) or not candidate:
                raise DeclarationResolutionError(
                    "vertex declaration has no explicit runtime name"
                )
            vertex_name = candidate
            has_vertex_boundary = bool(payload.get("boundary", ()))
        elif kind == DECL_KIND_DEFINED and isinstance(subject, str):
            names.add(subject)
        elif kind == DECL_SOURCE_DEFINED:
            if payload.get("form") != "template" or payload.get("loop") is None:
                continue
            rows: list[Mapping[str, str]] = []
            for param in payload.get("params", ()):
                if isinstance(param, Mapping) and isinstance(param.get("values"), Mapping):
                    rows.append(param["values"])
            from_document = payload.get("from")
            if isinstance(from_document, Mapping):
                pin = from_document.get("params_sha256")
                if isinstance(pin, str) and pin in verified_params:
                    rows.extend(verified_params[pin])
                else:
                    unknown = True
            for row in rows:
                literal, indirect = _literal_kind(row.get("kind"))
                if literal is not None:
                    names.add(literal)
                unknown = unknown or indirect
    if vertex_name is None:
        raise DeclarationResolutionError(
            "declaration documents have no vertex identity"
        )
    return _Namespace(
        names=frozenset(names),
        unknown_generator=unknown,
        vertex_name=vertex_name,
        has_vertex_boundary=has_vertex_boundary,
    )


def _issue(
    reason: BoundaryContinuityReason,
    *,
    vertex: str,
    loop: str | None = None,
    tick: Tick | None = None,
    revision: DeclarationDocumentRevision | None = None,
    declaration_fact_id: str | None = None,
    declaration_kind: str | None = None,
    detail: str,
) -> BoundaryContinuityConflict:
    return BoundaryContinuityConflict(
        BoundaryContinuityIssue(
            reason=reason,
            vertex_name=vertex,
            loop_name=loop,
            tick_id=tick.id if tick is not None else None,
            tick_ordinal=tick.arrival_ordinal if tick is not None else None,
            tick_seq=tick.arrival_seq if tick is not None else None,
            declaration_fact_id=(
                declaration_fact_id
                if declaration_fact_id is not None
                else _revision_fact_id(revision, loop, declaration_kind)
            ),
            declaration_ordinal=(
                revision.arrival_ordinal if revision is not None else None
            ),
            detail=detail,
        )
    )


def _revision_fact_id(
    revision: DeclarationDocumentRevision | None,
    loop_name: str | None,
    declaration_kind: str | None,
) -> str | None:
    if revision is None:
        return None
    if not revision.document_fact_ids:
        # Genesis is the one row that establishes every seed document.
        return revision.fact_ids[0] if len(revision.fact_ids) == 1 else None
    if declaration_kind is not None:
        for kind, _subject, fact_id in reversed(revision.document_fact_ids):
            if kind == declaration_kind:
                return fact_id
        return None
    if loop_name is not None:
        loop_kinds = {
            DECL_KIND_DEFINED,
            DEFINED_TO_TOMBSTONE[DECL_KIND_DEFINED],
        }
        for kind, subject, fact_id in reversed(revision.document_fact_ids):
            if kind in loop_kinds and subject == loop_name:
                return fact_id
    return None


def analyze_boundary_continuity(
    anchor: DeclarationAnchor,
    facts: Sequence[Fact],
    ticks: Sequence[Tick],
    *,
    target_documents: Sequence[Mapping[str, Any]],
    verified_params: Mapping[str, Sequence[Mapping[str, str]]] | None = None,
    compiled_loop_names: Collection[str] | None = None,
) -> BoundaryContinuityResult:
    """Validate every owned edge consumed by the target declaration."""
    verified = verified_params or {}
    revisions = declaration_document_revisions(
        anchor, facts, target_documents=target_documents
    )
    namespaces = tuple(_namespace(revision.documents, verified) for revision in revisions)
    target = namespaces[-1]

    if target.vertex_name in target.names:
        raise _issue(
            "reserved-runtime-name",
            vertex=target.vertex_name,
            loop=target.vertex_name,
            detail=(
                f"loop name {target.vertex_name!r} is reserved for the vertex "
                "boundary role"
            ),
        )

    if compiled_loop_names is not None:
        compiled = frozenset(compiled_loop_names)
        missing = target.names - compiled
        extra = compiled - target.names
        if missing or (extra and not target.unknown_generator):
            parts = []
            if missing:
                parts.append(f"missing {sorted(missing)!r}")
            if extra:
                parts.append(f"unproved {sorted(extra)!r}")
            raise _issue(
                "runtime-namespace-mismatch",
                vertex=target.vertex_name,
                detail="compiled runtime namespace disagrees with declaration: "
                + "; ".join(parts),
            )

    own_declaration_facts = tuple(
        fact
        for fact in facts
        if (
            fact.kind == DECL_GENESIS
            and fact.id == anchor.own_lineage
        )
        or (
            is_internal_kind(fact.kind)
            and fact.payload.get("lineage") == anchor.own_lineage
        )
    )
    own_declaration_by_ordinal = {
        fact.arrival_ordinal: fact for fact in own_declaration_facts
    }
    owned_ticks = tuple(tick for tick in ticks if tick.origin == target.vertex_name)
    for tick in owned_ticks:
        if tick.arrival_ordinal in own_declaration_by_ordinal:
            fact = own_declaration_by_ordinal[tick.arrival_ordinal]
            conflicting = DeclarationDocumentRevision(
                arrival_ordinal=fact.arrival_ordinal,
                fact_ids=(fact.id,),
                document_fact_ids=(
                    (fact.kind, str(fact.payload.get("subject")), fact.id),
                ),
                documents=(),
            )
            raise _issue(
                "invalid-projection-shape",
                vertex=target.vertex_name,
                loop=tick.name,
                tick=tick,
                revision=conflicting,
                declaration_fact_id=fact.id,
                detail=(
                    "owned tick shares an Arrival ordinal with an own-lineage "
                    "declaration fact"
                ),
            )

    genesis_ordinal = revisions[0].arrival_ordinal

    def revision_at_tick(tick: Tick) -> int | None:
        if genesis_ordinal is None or tick.arrival_ordinal < genesis_ordinal:
            return None
        selected: int | None = None
        for index, revision in enumerate(revisions):
            if revision.proposed:
                break
            ordinal = revision.arrival_ordinal
            if ordinal is not None and ordinal <= tick.arrival_ordinal:
                selected = index
        return selected

    for tick in owned_ticks:
        start = revision_at_tick(tick)
        if tick.name == target.vertex_name and target.has_vertex_boundary:
            if start is None:
                raise _issue(
                    "ambiguous-tick-role",
                    vertex=target.vertex_name,
                    loop=tick.name,
                    tick=tick,
                    detail="vertex-period tick predates declaration genesis",
                )
            if namespaces[start].vertex_name != target.vertex_name:
                raise _issue(
                    "ambiguous-tick-role",
                    vertex=target.vertex_name,
                    loop=tick.name,
                    tick=tick,
                    revision=revisions[start],
                    declaration_kind=DECL_VERTEX_DEFINED,
                    detail="vertex-period tick was received under another vertex identity",
                )
            for index in range(start, len(revisions)):
                if namespaces[index].vertex_name != target.vertex_name:
                    raise _issue(
                        "prior-incarnation",
                        vertex=target.vertex_name,
                        loop=tick.name,
                        tick=tick,
                        revision=revisions[index],
                        declaration_kind=DECL_VERTEX_DEFINED,
                        detail=(
                            f"vertex-period tick {tick.id!r} crosses a declaration "
                            "vertex identity discontinuity"
                        ),
                    )
            at_receipt = namespaces[start].membership(tick.name)
            if at_receipt != "absent":
                raise _issue(
                    "ambiguous-tick-role",
                    vertex=target.vertex_name,
                    loop=tick.name,
                    tick=tick,
                    revision=revisions[start],
                    detail=(
                        "vertex-name tick had a present or unprovable same-name "
                        "loop role at receipt"
                    ),
                )

            # A current vertex boundary consumes this as a vertex-period edge.
            # Current C5/runtime namespace checks separately prevent an actual
            # same-name loop, so do not also reinterpret it as a loop edge.
            continue
        if tick.name == target.vertex_name:
            # With no current vertex-boundary consumer, the saved period value
            # has no supported detached-runtime effect.  Keep the row as
            # evidence and re-check it if a later proposal adds that consumer.
            continue

        target_membership = target.membership(tick.name)
        if target_membership == "absent":
            continue
        if start is None:
            raise _issue(
                "unproven-loop-role",
                vertex=target.vertex_name,
                loop=tick.name,
                tick=tick,
                detail="owned loop tick predates declaration genesis",
            )
        for index in range(start, len(revisions)):
            if namespaces[index].vertex_name != target.vertex_name:
                raise _issue(
                    "unproven-loop-role" if index == start else "prior-incarnation",
                    vertex=target.vertex_name,
                    loop=tick.name,
                    tick=tick,
                    revision=revisions[index],
                    detail=(
                        f"owned tick {tick.id!r} crosses a declaration vertex "
                        "identity discontinuity"
                    ),
                )
            membership = namespaces[index].membership(tick.name)
            if membership == "present":
                continue
            if membership == "absent":
                reason: BoundaryContinuityReason = (
                    "unproven-loop-role" if index == start else "prior-incarnation"
                )
            else:
                reason = "unproven-generated-incarnation"
            raise _issue(
                reason,
                vertex=target.vertex_name,
                loop=tick.name,
                tick=tick,
                revision=revisions[index],
                detail=(
                    f"owned tick {tick.id!r} cannot be consumed by current loop "
                    f"{tick.name!r}: declared membership became {membership}"
                ),
            )

    return BoundaryContinuityResult(
        provable_names=target.names,
        has_unknown_generators=target.unknown_generator,
        vertex_name=target.vertex_name,
        has_vertex_boundary=target.has_vertex_boundary,
    )
