"""Aggregate capture keeps occurrence evidence without a synthetic common head."""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest
from atoms import Fact as AtomFact
from lang import genesis_payload, parse_vertex, parse_vertex_file

from engine.arrival import ArrivalLog
from engine.arrival_aggregate import (
    AggregateCycle,
    AggregatePlanNode,
    DefinitionEvidence,
    OccurrenceStep,
    capture_aggregate,
)
from engine.arrival_contract import Profile, StoreDescriptor
from engine.arrival_registry import BackendRegistry, descriptor_for
from engine.arrival_store import ArrivalStore
from engine.residence import index_path_for


def _node(path: Path, *, path_steps: tuple[OccurrenceStep, ...], role: str = "member"):
    ast = parse_vertex_file(path)
    return AggregatePlanNode(
        path=path_steps,
        locator=path,
        local_ast=ast,
        definition=DefinitionEvidence(
            locator=str(path), sha256="sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()
        ),
        descriptor=descriptor_for(ast, path),
        role=role,
    )


def _mint_declared(
    tmp_path: Path,
    name: str,
    source: str,
    *,
    signer,
    key: str,
    documents: list[dict] | None = None,
) -> tuple[Path, ArrivalLog]:
    log = ArrivalLog.mint(tmp_path / f"{name}.arrival", observer="kyle", signer=signer, key=key)
    vertex = tmp_path / f"{name}.vertex"
    vertex.write_text(
        source.replace("{log}", str(log.path)).replace("{lineage}", log.lineage()),
        encoding="utf-8",
    )
    store = ArrivalStore(
        path=index_path_for(log.path),
        log_path=log.path,
        serialize=lambda fact: fact.to_dict(),
        deserialize=AtomFact.from_dict,
        fact_signer=signer,
    )
    try:
        store.absorb_genesis(
            documents
            if documents is not None
            else genesis_payload(parse_vertex_file(vertex))["documents"],
            observer="kyle",
            fact_signer=signer,
        )
    finally:
        store.close()
    return vertex, log


class _FilesystemResolver:
    def __init__(self) -> None:
        self.seen: list[tuple[str, str | None]] = []

    def children(self, node, effective_ast):
        self.seen.append((node.locator.name, effective_ast.discover))
        if effective_ast.discover is None:
            return ()
        return tuple(
            _node(
                path,
                path_steps=node.path
                + (OccurrenceStep("discover", ordinal, path.name),),
            )
            for ordinal, path in enumerate(sorted(node.locator.parent.glob(effective_ast.discover)))
            if path.suffix == ".vertex" and path.resolve() != node.locator.resolve()
        )


def test_descriptor_root_effectively_plain_retains_its_member(
    tmp_path, keys, signer, monkeypatch
):
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    root, log = _mint_declared(
        tmp_path, "root",
        'name "root"\nstore "{log}" backend="file" lineage="{lineage}" role="authority"\n'
        'loops { note { fold { n "count" } } }\n',
        signer=signer, key=keys.public,
    )
    root.write_text(root.read_text() + 'discover "children/*.vertex"\n')
    resolver = _FilesystemResolver()
    with capture_aggregate(
        BackendRegistry.with_builtin_backends(),
        _node(root, path_steps=(), role="root"), resolver,
    ) as capture:
        assert len(capture.members) == 1
        assert capture.members[0].basis.lineage == log.lineage()
        assert capture.members[0].identity.role == "root"
        assert capture.definitions[0].children == ()
        assert resolver.seen == [("root.vertex", None)]


def test_descriptor_discover_expands_bounded_effective_definition_not_local_cache(
    tmp_path: Path, keys, signer, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    effective_dir = tmp_path / "effective"
    cached_dir = tmp_path / "cached"
    effective_dir.mkdir()
    cached_dir.mkdir()
    right, _right_log = _mint_declared(
        effective_dir,
        "right",
        'name "right"\nstore "{log}" backend="file" lineage="{lineage}" role="authority"\n'
        'loops { note { fold { n "count" } } }\n',
        signer=signer,
        key=keys.public,
    )
    wrong, _wrong_log = _mint_declared(
        cached_dir,
        "wrong",
        'name "wrong"\nstore "{log}" backend="file" lineage="{lineage}" role="authority"\n'
        'loops { note { fold { n "count" } } }\n',
        signer=signer,
        key=keys.public,
    )
    root_log = ArrivalLog.mint(
        tmp_path / "root.arrival", observer="kyle", signer=signer, key=keys.public
    )
    root = tmp_path / "root.vertex"
    root.write_text(
        f'name "root"\nstore "{root_log.path}" backend="file" '
        f'lineage="{root_log.lineage()}" role="authority"\n'
        'discover "cached/*.vertex"\nloops { note { fold { n "count" } } }\n',
        encoding="utf-8",
    )
    effective_root = parse_vertex(
        f'name "root"\nstore "{root_log.path}" backend="file" '
        f'lineage="{root_log.lineage()}" role="authority"\n'
        'discover "effective/*.vertex"\nloops { note { fold { n "count" } } }\n',
        path=root,
    )
    store = ArrivalStore(
        path=index_path_for(root_log.path),
        log_path=root_log.path,
        serialize=lambda fact: fact.to_dict(),
        deserialize=AtomFact.from_dict,
        fact_signer=signer,
    )
    try:
        store.absorb_genesis(
            genesis_payload(effective_root)["documents"], observer="kyle", fact_signer=signer
        )
    finally:
        store.close()

    import engine.arrival_aggregate as aggregate

    original_open = aggregate.open_read
    opened_locations: list[str] = []

    def counted_open(registry, descriptor, **kwargs):
        opened_locations.append(descriptor.location)
        return original_open(registry, descriptor, **kwargs)

    monkeypatch.setattr(aggregate, "open_read", counted_open)
    resolver = _FilesystemResolver()
    with capture_aggregate(
        BackendRegistry.with_builtin_backends(),
        _node(root, path_steps=(), role="root"),
        resolver,
    ) as capture:
        assert [member.identity.role for member in capture.members] == [
            "own-overlay", "member"
        ]
        assert [member.identity.locator for member in capture.members] == [
            str(root), str(right)
        ]
        assert opened_locations == [str(root_log.path), str(_right_log.path)]
        assert str(_wrong_log.path) not in opened_locations
        assert resolver.seen[0] == ("root.vertex", "effective/*.vertex")
        assert [definition.identity.locator for definition in capture.definitions] == [
            str(root), str(right)
        ]
        assert capture.definitions[0].children == (capture.definitions[1].identity,)
        detached = capture.definitions
        detached[0].effective_declaration.loops.clear()
        assert "note" in capture.definitions[0].effective_declaration.loops

    outer = tmp_path / "outer.vertex"
    outer.write_text(
        'name "outer"\nloops { own { fold { n "count" } } }\n', encoding="utf-8"
    )
    outer_node = _node(outer, path_steps=(), role="root")
    nested_root = _node(
        root, path_steps=(OccurrenceStep("combine", 0, "nested-root"),), role="member"
    )

    class NestedResolver:
        def children(self, node, effective_ast):
            if node is outer_node:
                return (nested_root,)
            return resolver.children(node, effective_ast)

    opened_locations.clear()
    with capture_aggregate(
        BackendRegistry.with_builtin_backends(), outer_node, NestedResolver()
    ) as capture:
        assert [member.identity.role for member in capture.members] == [
            "own-overlay", "member"
        ]
        assert [member.identity.locator for member in capture.members] == [
            str(root), str(right)
        ]
        assert "own" in capture.definitions[0].effective_declaration.loops
        assert capture.definitions[0].children == (capture.definitions[1].identity,)


def test_capture_cycle_uses_active_stack_without_global_occurrence_dedup(tmp_path: Path):
    left = tmp_path / "left.vertex"
    right = tmp_path / "right.vertex"
    left.write_text("left", encoding="utf-8")
    right.write_text("right", encoding="utf-8")
    left_node = AggregatePlanNode(
        (), left, object(), DefinitionEvidence(str(left), "sha256:left"), None, "root"
    )
    right_node = AggregatePlanNode(
        (OccurrenceStep("combine", 0, "right"),),
        right,
        object(),
        DefinitionEvidence(str(right), "sha256:right"),
        None,
    )

    class CycleResolver:
        def children(self, node, _effective):
            return (right_node,) if node.locator == left else (left_node,)

    with pytest.raises(AggregateCycle, match="composition cycle"):
        capture_aggregate(BackendRegistry(), left_node, CycleResolver())


def test_capture_keeps_repeated_same_lineage_occurrences_and_closes_each(
    tmp_path: Path, keys, signer, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    child, _log = _mint_declared(
        tmp_path,
        "child",
        'name "child"\nstore "{log}" backend="file" lineage="{lineage}" role="authority"\n'
        'loops { note { fold { n "count" } } }\n',
        signer=signer,
        key=keys.public,
    )
    root_path = tmp_path / "root.vertex"
    root_path.write_text("root", encoding="utf-8")
    root = AggregatePlanNode(
        (), root_path, object(), DefinitionEvidence(str(root_path), "sha256:root"), None, "root"
    )
    first = _node(child, path_steps=(OccurrenceStep("combine", 0, "one"),))
    second = _node(child, path_steps=(OccurrenceStep("combine", 1, "two"),))

    class RepeatedResolver:
        def children(self, node, _effective):
            return (first, second) if node is root else ()

    import engine.arrival_aggregate as aggregate

    original_open = aggregate.open_read
    opened = []

    def tracked_open(registry, descriptor, **kwargs):
        value = original_open(registry, descriptor, **kwargs)
        opened.append(value)
        return value

    monkeypatch.setattr(aggregate, "open_read", tracked_open)
    with capture_aggregate(
        BackendRegistry.with_builtin_backends(), root, RepeatedResolver()
    ) as capture:
        assert len(capture.members) == 2
        assert [member.identity.path for member in capture.members] == [first.path, second.path]
        assert (
            capture.members[0].identity.declaration_identity
            == capture.members[1].identity.declaration_identity
        )
    assert len(opened) == 2 and all(value._closed for value in opened)


def test_capture_closes_prior_member_when_later_open_refuses(
    tmp_path: Path, keys, signer, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    child, _log = _mint_declared(
        tmp_path,
        "child",
        'name "child"\nstore "{log}" backend="file" lineage="{lineage}" role="authority"\n'
        'loops { note { fold { n "count" } } }\n',
        signer=signer,
        key=keys.public,
    )
    root_path = tmp_path / "root.vertex"
    root_path.write_text("root", encoding="utf-8")
    root = AggregatePlanNode(
        (), root_path, object(), DefinitionEvidence(str(root_path), "sha256:root"), None, "root"
    )
    first = _node(child, path_steps=(OccurrenceStep("combine", 0, "good"),))
    refused = AggregatePlanNode(
        (OccurrenceStep("combine", 1, "bad"),),
        tmp_path / "bad.vertex",
        object(),
        DefinitionEvidence(str(tmp_path / "bad.vertex"), "sha256:bad"),
        StoreDescriptor("missing", "opaque:bad", role=Profile.AUTHORITY),
    )

    class RefusingResolver:
        def children(self, node, _effective):
            return (first, refused) if node is root else ()

    import engine.arrival_aggregate as aggregate

    original_open = aggregate.open_read
    opened = []

    def tracked_open(registry, descriptor, **kwargs):
        value = original_open(registry, descriptor, **kwargs)
        opened.append(value)
        return value

    monkeypatch.setattr(aggregate, "open_read", tracked_open)
    with pytest.raises(Exception, match="no adapter registered"):
        capture_aggregate(BackendRegistry.with_builtin_backends(), root, RefusingResolver())
    assert len(opened) == 1 and opened[0]._closed is True


def test_storeless_empty_membership_retains_only_definition_evidence(tmp_path: Path):
    root_path = tmp_path / "empty.vertex"
    root_path.write_text(
        'name "empty"\ndiscover "children/*.vertex"\n', encoding="utf-8"
    )
    root = _node(root_path, path_steps=(), role="root")

    with capture_aggregate(BackendRegistry(), root, _FilesystemResolver()) as capture:
        assert capture.members == ()
        assert len(capture.definitions) == 1
        assert capture.definitions[0].local_definition == root.definition
        assert capture.definitions[0].effective_declaration == root.local_ast
        assert capture.definitions[0].children == ()
