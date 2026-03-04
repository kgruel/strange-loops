"""Tests for FoldState — the typed fold output contract."""

from atoms import FoldItem, FoldSection, FoldState


class TestFoldItem:
    def test_basic_construction(self):
        item = FoldItem(payload={"topic": "auth", "position": "JWT"}, ts=1000.0, observer="kyle")
        assert item.payload["topic"] == "auth"
        assert item.ts == 1000.0
        assert item.observer == "kyle"
        assert item.origin == ""

    def test_defaults(self):
        item = FoldItem(payload={"x": 1})
        assert item.ts is None
        assert item.observer == ""
        assert item.origin == ""

    def test_frozen(self):
        item = FoldItem(payload={"x": 1})
        try:
            item.ts = 999.0  # type: ignore[misc]
            assert False, "Should raise"
        except AttributeError:
            pass

    def test_payload_is_not_frozen(self):
        """Payload dict itself is mutable (unlike Fact which wraps in MappingProxyType).
        FoldState is ephemeral — computed on demand, not persisted. Freezing the
        dataclass prevents reassignment; payload mutability is acceptable."""
        item = FoldItem(payload={"x": 1})
        item.payload["y"] = 2
        assert item.payload["y"] == 2


class TestFoldSection:
    def test_leaf_section(self):
        items = (
            FoldItem(payload={"topic": "auth"}, ts=1000.0, observer="kyle"),
            FoldItem(payload={"topic": "storage"}, ts=2000.0, observer="kyle"),
        )
        section = FoldSection(kind="decision", items=items, fold_type="by", key_field="topic")
        assert section.count == 2
        assert not section.is_empty
        assert section.kind == "decision"

    def test_empty_section(self):
        section = FoldSection(kind="task")
        assert section.count == 0
        assert section.is_empty

    def test_nested_sections(self):
        child1 = FoldSection(
            kind="decision",
            items=(FoldItem(payload={"topic": "auth"}),),
            fold_type="by",
            key_field="topic",
        )
        child2 = FoldSection(kind="thread")  # empty
        parent = FoldSection(kind="project", sections=(child1, child2))
        assert parent.count == 0  # parent has no direct items
        assert not parent.is_empty  # child1 has items

    def test_nested_all_empty(self):
        child1 = FoldSection(kind="decision")
        child2 = FoldSection(kind="thread")
        parent = FoldSection(kind="project", sections=(child1, child2))
        assert parent.is_empty

    def test_defaults(self):
        section = FoldSection(kind="test")
        assert section.items == ()
        assert section.sections == ()
        assert section.fold_type == "collect"
        assert section.key_field is None


class TestFoldState:
    def test_basic_construction(self):
        section = FoldSection(
            kind="decision",
            items=(FoldItem(payload={"topic": "auth"}, ts=1000.0, observer="kyle"),),
            fold_type="by",
            key_field="topic",
        )
        state = FoldState(sections=(section,), vertex="project")
        assert state.vertex == "project"
        assert len(state.sections) == 1
        assert not state.is_empty

    def test_empty_state(self):
        state = FoldState(sections=(), vertex="empty")
        assert state.is_empty

    def test_multiple_sections(self):
        decisions = FoldSection(
            kind="decision",
            items=(FoldItem(payload={"topic": "auth"}),),
            fold_type="by",
            key_field="topic",
        )
        threads = FoldSection(
            kind="thread",
            items=(FoldItem(payload={"name": "store-ops", "status": "open"}),),
            fold_type="by",
            key_field="name",
        )
        changes = FoldSection(
            kind="change",
            items=(
                FoldItem(payload={"summary": "big refactor"}, ts=3000.0),
                FoldItem(payload={"summary": "small fix"}, ts=2000.0),
            ),
            fold_type="collect",
        )
        state = FoldState(sections=(decisions, threads, changes), vertex="project")
        assert len(state.sections) == 3
        assert state.sections[0].kind == "decision"
        assert state.sections[2].count == 2

    def test_import_from_atoms(self):
        """Contract: lens authors can import from atoms without engine."""
        from atoms import FoldItem, FoldSection, FoldState
        assert FoldItem is not None
        assert FoldSection is not None
        assert FoldState is not None

    def test_frozen(self):
        state = FoldState(sections=(), vertex="test")
        try:
            state.vertex = "other"  # type: ignore[misc]
            assert False, "Should raise"
        except AttributeError:
            pass
