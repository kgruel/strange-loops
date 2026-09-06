"""Frozen-member aggregate planning and pure composition for SDK reads.

This module deliberately owns no legacy reader or store path.  Every
descriptor occurrence is captured through ``engine.arrival_aggregate`` and
composition consumes only those retained snapshots plus frozen definitions.
"""

from __future__ import annotations

import hashlib
import os
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from atoms import ByKey, totalize
from engine.arrival_aggregate import (
    AggregateCapture,
    AggregateCaptureRefused,
    AggregateMember,
    AggregatePlanNode,
    CapturedDefinition,
    DefinitionEvidence,
    OccurrenceIdentity,
    OccurrenceStep,
    capture_aggregate,
)
from engine.arrival_consumer import OpenedRead
from engine.arrival_contract import Fact, FactRequest, Tick, TickRequest
from engine.arrival_registry import BackendRegistry, descriptor_for
from engine.compiler import compile_vertex
from engine.composition import merge_fold_specs
from engine.observer import observer_matches
from lang import parse_vertex, resolve_vertex


def _loops_home() -> Path:
    if home := os.environ.get("LOOPS_HOME"):
        return Path(home)
    return Path(os.environ.get("XDG_CONFIG_HOME", str(Path.home() / ".config"))) / "loops"


def _identity_key(identity: OccurrenceIdentity) -> tuple[object, ...]:
    return (identity.path, identity.locator, identity.role)


def _member_key(member: AggregateMember) -> tuple[object, ...]:
    return (member.identity.path, member.identity.locator, member.identity.role)


def _path_key(path: tuple[OccurrenceStep, ...]) -> tuple[tuple[str, int, str], ...]:
    return tuple((step.relation, step.ordinal, step.label) for step in path)


def _kind_target(kind: str, specs: dict[str, Any]) -> str | None:
    if kind in specs:
        return kind
    prefix, separator, _rest = kind.partition(".")
    return prefix if separator and prefix in specs else None


@dataclass(frozen=True)
class _Observation:
    member: AggregateMember
    fact: Fact


@dataclass(frozen=True)
class _Stream:
    member: AggregateMember
    facts: tuple[Fact, ...]


class _Resolver:
    """Exact-byte local planner invoked from each frozen effective AST."""

    def _node(
        self, path: Path, occurrence: tuple[OccurrenceStep, ...], role: str = "member"
    ) -> AggregatePlanNode:
        resolved = path.resolve()
        try:
            raw = resolved.read_bytes()
        except OSError as exc:
            raise AggregateCaptureRefused(f"aggregate member is unavailable: {resolved}") from exc
        try:
            ast = parse_vertex(raw.decode("utf-8"), path=resolved)
        except UnicodeDecodeError as exc:
            raise AggregateCaptureRefused(f"aggregate member is not UTF-8: {resolved}") from exc
        return AggregatePlanNode(
            path=occurrence,
            locator=resolved,
            local_ast=ast,
            definition=DefinitionEvidence(
                locator=str(resolved),
                sha256="sha256:" + hashlib.sha256(raw).hexdigest(),
            ),
            descriptor=descriptor_for(ast, resolved),
            role=role,
        )

    def root(self, path: Path) -> AggregatePlanNode:
        return self._node(path, (), role="root")

    def children(
        self, node: AggregatePlanNode, effective_ast: Any
    ) -> tuple[AggregatePlanNode, ...]:
        if effective_ast.combine is not None:
            children: list[AggregatePlanNode] = []
            for ordinal, entry in enumerate(effective_ast.combine):
                member = resolve_vertex(entry.name, _loops_home())
                if not member.is_absolute():
                    member = node.locator.parent / member
                if not member.exists():
                    raise AggregateCaptureRefused(
                        f"declared aggregate member is missing: {member.resolve()}"
                    )
                children.append(
                    self._node(
                        member,
                        node.path
                        + (OccurrenceStep("combine", ordinal, entry.alias or entry.name),),
                    )
                )
            return tuple(children)
        if effective_ast.discover is not None:
            return tuple(
                self._node(
                    child,
                    node.path + (OccurrenceStep("discover", ordinal, child.name),),
                )
                for ordinal, child in enumerate(
                    sorted(node.locator.parent.glob(effective_ast.discover))
                )
                if child.suffix == ".vertex" and child.resolve() != node.locator.resolve()
            )
        return ()


class AggregateRead:
    """Pure composition view over one closeable, sequential member capture."""

    def __init__(self, capture: AggregateCapture) -> None:
        self.capture = capture
        self._definitions = {
            _identity_key(definition.identity): definition for definition in capture.definitions
        }
        self._members = {_member_key(member): member for member in capture.members}
        self._spec_cache: dict[tuple[object, ...], dict[str, Any]] = {}
        self._stream_cache: dict[tuple[object, ...], tuple[_Stream, ...]] = {}

    @property
    def root(self) -> CapturedDefinition:
        return self.capture.definitions[0]

    def member_evidence(self) -> list[dict[str, Any]]:
        return [
            {
                "path": [
                    {"relation": step.relation, "ordinal": step.ordinal, "label": step.label}
                    for step in member.identity.path
                ],
                "locator": member.identity.locator,
                "declaration_identity": member.identity.declaration_identity,
                "role": member.identity.role,
                "definition": {
                    "locator": member.definition.locator,
                    "sha256": member.definition.sha256,
                },
                "basis": member.basis,
            }
            for member in self.capture.members
        ]

    def definition_evidence(self) -> list[dict[str, Any]]:
        return [
            {
                "path": [
                    {"relation": step.relation, "ordinal": step.ordinal, "label": step.label}
                    for step in definition.identity.path
                ],
                "locator": definition.identity.locator,
                "role": definition.identity.role,
                "local_definition": {
                    "locator": definition.local_definition.locator,
                    "sha256": definition.local_definition.sha256,
                },
                "basis": definition.basis,
                "children": [
                    {
                        "path": [
                            {
                                "relation": step.relation,
                                "ordinal": step.ordinal,
                                "label": step.label,
                            }
                            for step in child.path
                        ],
                        "locator": child.locator,
                        "role": child.role,
                    }
                    for child in definition.children
                ],
            }
            for definition in self.capture.definitions
        ]

    def specs(self, definition: CapturedDefinition | None = None) -> dict[str, Any]:
        definition = self.root if definition is None else definition
        key = _identity_key(definition.identity)
        cached = self._spec_cache.get(key)
        if cached is not None:
            return cached
        child_specs = [
            (child.locator, self.specs(self._definitions[_identity_key(child)]))
            for child in definition.children
        ]
        own = compile_vertex(definition.effective_declaration)
        inherited = merge_fold_specs(child_specs, override_kinds=frozenset(own))
        result = {**inherited, **own}
        self._spec_cache[key] = result
        return result

    def _facts(self, member: AggregateMember) -> tuple[Fact, ...]:
        return member.snapshot.facts(
            FactRequest(limit=None, include_internal=False, order="oldest")
        ).items

    def streams(self, definition: CapturedDefinition | None = None) -> tuple[_Stream, ...]:
        definition = self.root if definition is None else definition
        key = _identity_key(definition.identity)
        cached = self._stream_cache.get(key)
        if cached is not None:
            return cached
        children = tuple(
            stream
            for child in definition.children
            for stream in self.streams(self._definitions[_identity_key(child)])
        )
        identity = definition.identity
        overlay = self._members.get((identity.path, identity.locator, "own-overlay"))
        member = self._members.get((identity.path, identity.locator, identity.role))
        if overlay is not None:
            own_specs = compile_vertex(definition.effective_declaration)
            shadowed = set(own_specs)
            retained_children = tuple(
                _Stream(
                    child.member,
                    tuple(
                        fact
                        for fact in child.facts
                        if _kind_target(fact.kind, own_specs) not in shadowed
                    ),
                )
                for child in children
            )
            result = retained_children + (
                _Stream(
                    overlay,
                    tuple(
                        fact
                        for fact in self._facts(overlay)
                        if _kind_target(fact.kind, own_specs) in shadowed
                    ),
                ),
            )
        elif member is not None:
            result = children + (_Stream(member, self._facts(member)),)
        else:
            result = children
        self._stream_cache[key] = result
        return result

    def observations(
        self, *, observer: str | None = None
    ) -> tuple[_Observation, ...]:
        return tuple(
            _Observation(stream.member, fact)
            for stream in self.streams()
            for fact in stream.facts
            if observer is None or observer_matches(fact.observer, observer)
        )

    def _eligible_members(
        self, definition: CapturedDefinition, kind: str
    ) -> tuple[AggregateMember, ...]:
        """Structural member axis after overlay selection, before row filters."""
        identity = definition.identity
        overlay = self._members.get((identity.path, identity.locator, "own-overlay"))
        direct_specs = compile_vertex(definition.effective_declaration)
        if overlay is not None and _kind_target(kind, direct_specs) is not None:
            # Empty own data still shadows descendants for its declared kind.
            return (overlay,)
        children = tuple(
            member
            for child in definition.children
            for member in self._eligible_members(self._definitions[_identity_key(child)], kind)
        )
        member = self._members.get((identity.path, identity.locator, identity.role))
        if member is not None:
            return children + (member,)
        return children

    def ordered_for_kind(self, kind: str, *, observer: str | None = None) -> list[Fact]:
        specs = self.specs()
        eligible = self._eligible_members(self.root, kind)
        eligible_keys = {_member_key(member) for member in eligible}
        selected = [
            observation
            for observation in self.observations(observer=observer)
            if _member_key(observation.member) in eligible_keys
            and _kind_target(observation.fact.kind, specs) == kind
        ]
        if len(eligible_keys) <= 1:
            return [item.fact for item in selected]
        selected.sort(
            key=lambda item: (
                _path_key(item.member.identity.path),
                item.member.identity.locator,
                item.member.identity.role,
                item.fact.arrival_ordinal,
                item.fact.arrival_seq,
            )
        )
        ordered = totalize(
            selected,
            ByKey("ts"),
            get_field=lambda item, field: (
                item.fact.ts if field == "ts" else item.fact.payload.get(field)
            ),
            get_id=lambda item: item.fact.id,
        )
        return [item.fact for item in ordered]

    def all_events(
        self, *, start: float, end: float
    ) -> list[tuple[str, AggregateMember, Fact | Tick]]:
        events: list[tuple[str, AggregateMember, Fact | Tick]] = []
        for member in self.capture.members:
            for fact in self._facts(member):
                if start <= fact.ts <= end:
                    events.append(("fact", member, fact))
            for tick in member.snapshot.ticks(TickRequest(since=start, until=end)):
                events.append(("tick", member, tick))
        if len(self.capture.members) <= 1:
            events.sort(
                key=lambda item: (
                    item[2].ts,
                    item[2].arrival_ordinal,
                    item[2].arrival_seq,
                    item[2].id,
                )
            )
        else:
            events.sort(
                key=lambda item: (
                    item[2].ts,
                    item[2].id,
                    _path_key(item[1].identity.path),
                    item[1].identity.locator,
                    item[1].identity.role,
                    item[2].arrival_ordinal,
                    item[2].arrival_seq,
                )
            )
        return events


@contextmanager
def open_aggregate_read(
    target: Path,
    *,
    registry: BackendRegistry | None = None,
    opened_root: OpenedRead | None = None,
) -> Iterator[AggregateRead]:
    """Plan exact local topology, then retain all descriptor snapshots."""
    resolver = _Resolver()
    capture = capture_aggregate(
        registry if registry is not None else BackendRegistry.with_builtin_backends(),
        resolver.root(target),
        resolver,
        opened_root=opened_root,
    )
    try:
        yield AggregateRead(capture)
    finally:
        capture.close()


def is_local_aggregate(target: Path) -> bool:
    """Whether the locator bytes declare a composition root before any open."""
    if target.suffix.lower() != ".vertex":
        return False
    try:
        ast = parse_vertex(target.read_text(encoding="utf-8"), path=target)
    except Exception:
        return False
    return ast.combine is not None or ast.discover is not None


def has_local_descriptor_aggregate(target: Path) -> bool:
    """Route a *storeless* local composition with Arrival descendants.

    A descriptor-bearing root must first open its ledger and resolve the
    adopted declaration at a bounded head.  Its locator can be ahead of (or
    behind) that declaration, so using local ``combine``/``discover`` here
    would silently change the execution shape before adoption.  Storeless
    roots have no adopted declaration to consult; their local topology is the
    honest planner input and this predicate keeps their Arrival descendants
    out of the legacy reader.
    """
    root = target.resolve()
    if root.suffix.lower() != ".vertex" or not root.exists():
        return False
    try:
        root_ast = parse_vertex(root.read_text(encoding="utf-8"), path=root)
    except Exception:
        return False
    if descriptor_for(root_ast, root) is not None:
        return False
    if root_ast.combine is None and root_ast.discover is None:
        return False

    seen: set[Path] = set()

    def visit(path: Path) -> bool:
        path = path.resolve()
        if path in seen or not path.exists():
            return False
        seen.add(path)
        try:
            ast = parse_vertex(path.read_text(encoding="utf-8"), path=path)
        except Exception:
            return False
        if descriptor_for(ast, path) is not None:
            return True
        if ast.combine is not None:
            for entry in ast.combine:
                child = resolve_vertex(entry.name, _loops_home())
                if not child.is_absolute():
                    child = path.parent / child
                if visit(child):
                    return True
        elif ast.discover is not None:
            for child in path.parent.glob(ast.discover):
                if child.suffix == ".vertex" and child.resolve() != path and visit(child):
                    return True
        return False

    return visit(root)
