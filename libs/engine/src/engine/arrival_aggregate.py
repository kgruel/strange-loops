"""Closeable, per-member Arrival capture for later aggregate composition.

This module captures evidence only.  It does not invent a common head, merge
rows, select a fold order, or open a legacy store.  Topology expansion is
injected so locator/name discovery remains a consumer concern.
"""

from __future__ import annotations

from collections.abc import Sequence
from contextlib import suppress
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Protocol

from lang import documents_to_vertex, vertex_to_documents

from .arrival_consumer import OpenedRead, open_read
from .arrival_contract import FactRequest, ReadBasis, StoreDescriptor
from .arrival_registry import BackendRegistry
from .declaration import (
    RuntimeEpoch,
    Unhistorized,
    effective_declaration_from_documents,
    resolve_declaration_documents_from_snapshot,
)

__all__ = [
    "AggregateCapture",
    "AggregateCaptureRefused",
    "CapturedDefinition",
    "AggregateCycle",
    "AggregateMember",
    "AggregatePlanNode",
    "AggregateTopologyResolver",
    "DefinitionEvidence",
    "MemberIdentity",
    "OccurrenceIdentity",
    "OccurrenceStep",
    "capture_aggregate",
]


def _detached(ast: Any) -> Any:
    """Reconstruct a private AST from canonical declaration documents."""
    if not hasattr(ast, "loops"):
        return ast
    return documents_to_vertex(
        vertex_to_documents(ast),
        path=ast.path,
        store=ast.store,
        store_backend=ast.store_backend,
        store_location=ast.store_location,
    )


@dataclass(frozen=True)
class OccurrenceStep:
    """One ordered edge in a composition occurrence path."""

    relation: str
    ordinal: int
    label: str


@dataclass(frozen=True)
class DefinitionEvidence:
    """Frozen local definition bytes selected during topology planning."""

    locator: str
    sha256: str


@dataclass(frozen=True)
class AggregatePlanNode:
    """One already-resolved composition occurrence supplied by a planner.

    ``role`` is ``root`` for the invocation root and ``member`` for a selected
    child. An own-store discover overlay is emitted from the captured parent
    resource, rather than represented here as a recursive child.
    """

    path: tuple[OccurrenceStep, ...]
    locator: Path
    local_ast: Any
    definition: DefinitionEvidence
    descriptor: StoreDescriptor | None
    role: str = "member"


@dataclass(frozen=True)
class MemberIdentity:
    """Occurrence identity; deliberately not a lineage or store-path key."""

    path: tuple[OccurrenceStep, ...]
    locator: str
    declaration_identity: str | None
    role: str


@dataclass(frozen=True)
class OccurrenceIdentity:
    """Topology identity before a descriptor snapshot supplies declaration identity."""

    path: tuple[OccurrenceStep, ...]
    locator: str
    role: str


class AggregateCaptureRefused(Exception):
    """Capture could not produce a complete aggregate membership vector."""


class AggregateCycle(AggregateCaptureRefused):
    """A composition locator reappeared on the active expansion stack."""


class AggregateTopologyResolver(Protocol):
    """Pure/planner-owned expansion of one already selected definition."""

    def children(
        self, node: AggregatePlanNode, effective_ast: Any
    ) -> Sequence[AggregatePlanNode]: ...


@dataclass(frozen=True)
class AggregateMember:
    """One retained descriptor occurrence and its independently captured basis."""

    identity: MemberIdentity
    definition: DefinitionEvidence
    basis: ReadBasis
    effective_declaration: Any
    snapshot: Any
    runtime_epoch: RuntimeEpoch = RuntimeEpoch("strict", None)


@dataclass(frozen=True)
class CapturedDefinition:
    """Frozen local/effective definition evidence and ordered child topology."""

    identity: OccurrenceIdentity
    local_definition: DefinitionEvidence
    effective_declaration: Any
    basis: ReadBasis | None
    children: tuple[OccurrenceIdentity, ...]


class _CapturedNode:
    """Mutable resource owner; structural capture evidence stays frozen."""

    __slots__ = ("node", "opened", "effective_declaration", "declaration_identity")

    def __init__(
        self,
        node: AggregatePlanNode,
        opened: OpenedRead,
        effective_declaration: Any,
        declaration_identity: str | None,
    ) -> None:
        self.node = node
        self.opened = opened
        self.effective_declaration = effective_declaration
        self.declaration_identity = declaration_identity

    def close(self) -> None:
        self.opened.close()


class AggregateCapture:
    """All retained member snapshots for one sequential aggregate observation."""

    __slots__ = ("_members", "_definitions", "_nodes", "_closed")

    def __init__(
        self,
        members: tuple[AggregateMember, ...],
        definitions: tuple[CapturedDefinition, ...],
        nodes: tuple[_CapturedNode, ...],
    ) -> None:
        self._members = members
        self._definitions = definitions
        self._nodes = nodes
        self._closed = False

    @property
    def members(self) -> tuple[AggregateMember, ...]:
        """Detached member evidence; a caller cannot mutate capture topology."""
        return tuple(
            replace(member, effective_declaration=_detached(member.effective_declaration))
            for member in self._members
        )

    @property
    def definitions(self) -> tuple[CapturedDefinition, ...]:
        """Detached frozen definitions; nested AST maps stay capture-private."""
        return tuple(
            replace(definition, effective_declaration=_detached(definition.effective_declaration))
            for definition in self._definitions
        )

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        first_error: BaseException | None = None
        for node in reversed(self._nodes):
            try:
                node.close()
            except BaseException as exc:  # preserve every remaining close
                if first_error is None:
                    first_error = exc
        if first_error is not None:
            raise first_error

    def __enter__(self) -> AggregateCapture:
        return self

    def __exit__(self, *_unused: object) -> None:
        self.close()


def _effective_declaration(node: AggregatePlanNode, opened: OpenedRead) -> tuple[Any, str | None]:
    facts = opened.snapshot.facts(
        FactRequest(limit=None, kind="_decl", include_internal=True, order="oldest")
    ).items
    documents = resolve_declaration_documents_from_snapshot(
        opened.snapshot.declaration_anchor, facts
    )
    if documents is None:
        raise AggregateCaptureRefused(
            f"descriptor occurrence {node.locator} has no adopted declaration"
        )
    rows = documents.documents if isinstance(documents, Unhistorized) else documents
    return (
        effective_declaration_from_documents(rows, node.local_ast),
        opened.snapshot.declaration_anchor.own_lineage,
    )


def _member(
    captured: _CapturedNode, *, role: str
) -> AggregateMember:
    node = captured.node
    return AggregateMember(
        identity=MemberIdentity(
            path=node.path,
            locator=str(node.locator),
            declaration_identity=captured.declaration_identity,
            role=role,
        ),
        definition=node.definition,
        basis=captured.opened.basis,
        effective_declaration=captured.effective_declaration,
        snapshot=captured.opened.snapshot,
        runtime_epoch=captured.opened.runtime_epoch(),
    )


def _occurrence(node: AggregatePlanNode, *, role: str | None = None) -> OccurrenceIdentity:
    return OccurrenceIdentity(node.path, str(node.locator), node.role if role is None else role)


def capture_aggregate(
    registry: BackendRegistry,
    root: AggregatePlanNode,
    resolver: AggregateTopologyResolver,
    *,
    opened_root: OpenedRead | None = None,
) -> AggregateCapture:
    """Capture every resolver-selected descriptor occurrence sequentially.

    A descriptor's topology is expanded only from its effective declaration at
    that node's bounded head. Storeless nodes expand from their frozen local
    AST. Each current snapshot remains open until the returned capture closes.
    """
    captured_nodes: list[_CapturedNode] = []
    members: list[AggregateMember] = []
    definitions: list[CapturedDefinition | None] = []
    active: list[Path] = []

    def visit(node: AggregatePlanNode) -> CapturedDefinition:
        locator = node.locator.resolve()
        if locator in active:
            chain = " -> ".join(str(path) for path in (*active, locator))
            raise AggregateCycle(f"composition cycle: {chain}")
        active.append(locator)
        definition_index = len(definitions)
        definitions.append(None)
        try:
            if node.descriptor is None:
                if getattr(node.local_ast, "store", None) is not None:
                    raise AggregateCaptureRefused(
                        "aggregate occurrence "
                        f"{node.locator} has storage without an explicit Arrival descriptor"
                    )
                effective = _detached(node.local_ast)
                basis = None
            else:
                opened = opened_root if node is root and opened_root is not None else open_read(
                    registry, node.descriptor
                )
                try:
                    effective, declaration_identity = _effective_declaration(node, opened)
                except BaseException:
                    with suppress(BaseException):
                        opened.close()
                    raise
                captured = _CapturedNode(
                    node, opened, _detached(effective), declaration_identity
                )
                captured_nodes.append(captured)
                effective = captured.effective_declaration
                basis = captured.opened.basis
                # Discover's own descriptor is a retained overlay role on this
                # exact resource, never a recursive self-child or second open.
                if effective.discover is not None:
                    members.append(_member(captured, role="own-overlay"))
                elif node.role != "root" or effective.combine is None:
                    # A descriptor root may resolve to a plain declaration
                    # even when its local ingress still describes composition.
                    # It remains a leaf occurrence of its own captured store.
                    members.append(_member(captured, role=node.role))
            child_definitions = tuple(
                visit(child) for child in resolver.children(node, effective)
            )
            definition = CapturedDefinition(
                identity=_occurrence(node),
                local_definition=node.definition,
                effective_declaration=effective,
                basis=basis,
                children=tuple(child.identity for child in child_definitions),
            )
            definitions[definition_index] = definition
            return definition
        finally:
            active.pop()

    try:
        visit(root)
        return AggregateCapture(
            tuple(members),
            tuple(definition for definition in definitions if definition is not None),
            tuple(captured_nodes),
        )
    except BaseException:
        for node in reversed(captured_nodes):
            with suppress(BaseException):
                node.close()
        raise
