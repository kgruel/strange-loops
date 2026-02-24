from __future__ import annotations

import ast
from dataclasses import is_dataclass
from pathlib import Path

import pytest


def test_block_defensively_freezes_rows() -> None:
    from fidelis.block import Block
    from fidelis.cell import Cell, Style

    style = Style()
    rows = [[Cell("a", style), Cell("b", style)]]

    block = Block(rows, width=2)

    # Mutate the caller-owned list-of-lists after construction: must not affect Block.
    rows[0][0] = Cell("x", style)
    rows.append([Cell("y", style), Cell("z", style)])

    assert block.height == 1
    assert [c.char for c in block.row(0)] == ["a", "b"]

    assert isinstance(block._rows, tuple)
    assert isinstance(block._rows[0], tuple)
    assert isinstance(block.row(0), tuple)

    with pytest.raises(TypeError):
        block.row(0)[0] = Cell("q", style)  # type: ignore[misc]

    with pytest.raises(AttributeError):
        block.width = 3  # type: ignore[misc]


def _dataclass_frozen_from_decorators(class_def: ast.ClassDef) -> bool | None:
    for decorator in class_def.decorator_list:
        if isinstance(decorator, ast.Name) and decorator.id == "dataclass":
            return False
        if isinstance(decorator, ast.Call) and isinstance(decorator.func, ast.Name) and decorator.func.id == "dataclass":
            for kw in decorator.keywords:
                if kw.arg == "frozen" and isinstance(kw.value, ast.Constant) and kw.value.value is True:
                    return True
            return False
    return None


def test_state_dataclasses_declared_frozen() -> None:
    fidelis_root = Path(__file__).resolve().parents[1] / "src" / "fidelis"

    must_be_frozen = {
        "Region",
        "Cell",
        "Style",
        "Span",
        "Line",
        "BorderChars",
        "Focus",
        "Search",
        "Lens",
        "Cursor",
        "Viewport",
        "CliContext",
        "Palette",
        "IconSet",
    }

    for py_file in fidelis_root.rglob("*.py"):
        tree = ast.parse(py_file.read_text(encoding="utf-8"), filename=str(py_file))
        for node in tree.body:
            if not isinstance(node, ast.ClassDef):
                continue

            if node.name.endswith("State") or node.name in must_be_frozen:
                frozen = _dataclass_frozen_from_decorators(node)
                assert frozen is True, f"{py_file}: class {node.name} must be @dataclass(frozen=True)"


def test_block_rows_private_not_accessed_outside_block() -> None:
    fidelis_root = Path(__file__).resolve().parents[1] / "src" / "fidelis"
    block_py = fidelis_root / "block.py"

    for py_file in fidelis_root.rglob("*.py"):
        if py_file == block_py:
            continue
        assert "._rows" not in py_file.read_text(encoding="utf-8"), f"{py_file} accesses Block._rows directly"


def test_runtime_state_dataclasses_are_frozen() -> None:
    from fidelis.borders import BorderChars
    from fidelis.cell import Cell, Style
    from fidelis._components.data_explorer import DataExplorerState
    from fidelis._components.list_view import ListState
    from fidelis._components.progress import ProgressState
    from fidelis._components.spinner import SpinnerState
    from fidelis._components.table import TableState
    from fidelis._components.text_input import TextInputState
    from fidelis.cursor import Cursor
    from fidelis.fidelity import CliContext
    from fidelis.focus import Focus
    from fidelis.region import Region
    from fidelis.search import Search
    from fidelis.span import Line, Span
    from fidelis.viewport import Viewport
    from fidelis._lens import Lens
    from fidelis.icon_set import IconSet
    from fidelis.palette import Palette

    for cls in (
        Region,
        Cell,
        Style,
        Span,
        Line,
        BorderChars,
        Focus,
        Search,
        Lens,
        Cursor,
        Viewport,
        CliContext,
        Palette,
        IconSet,
        SpinnerState,
        ProgressState,
        ListState,
        TextInputState,
        TableState,
        DataExplorerState,
    ):
        assert is_dataclass(cls)
        assert cls.__dataclass_params__.frozen is True
