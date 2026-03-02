from __future__ import annotations

import ast
from dataclasses import is_dataclass
from pathlib import Path

import pytest


def _module_name_for_file(src_root: Path, py_file: Path) -> str:
    rel = py_file.relative_to(src_root).with_suffix("")
    return ".".join(rel.parts)


def _resolve_relative_module(current_pkg: str, *, level: int, module: str | None) -> str:
    """Resolve an ast.ImportFrom into an absolute module path.

    Examples (current_pkg="painted.views"):
      - from ._components import x      => painted.views._components
      - from ..app import Surface       => painted.app
    """
    if level <= 0:
        return module or ""

    pkg_parts = current_pkg.split(".") if current_pkg else []
    up = level - 1
    base_parts = pkg_parts[: max(0, len(pkg_parts) - up)]
    base = ".".join(base_parts)
    if not module:
        return base
    return f"{base}.{module}" if base else module


def _iter_imported_modules(src_root: Path, py_file: Path) -> set[str]:
    tree = ast.parse(py_file.read_text(encoding="utf-8"), filename=str(py_file))
    current_mod = _module_name_for_file(src_root, py_file)
    current_pkg = current_mod.rsplit(".", 1)[0] if "." in current_mod else current_mod

    imported: set[str] = set()

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                imported.add(alias.name)
        elif isinstance(node, ast.ImportFrom):
            base = _resolve_relative_module(current_pkg, level=node.level, module=node.module)
            if node.module is not None:
                imported.add(base)
            else:
                # from .. import foo, bar
                for alias in node.names:
                    imported.add(f"{base}.{alias.name}" if base else alias.name)

    return imported


def _assert_no_imports(py_file: Path, forbidden_prefixes: set[str]) -> None:
    painted_src = Path(__file__).resolve().parents[2] / "src"
    imported = _iter_imported_modules(painted_src, py_file)

    forbidden = []
    for mod in sorted(imported):
        if any(mod == p or mod.startswith(f"{p}.") for p in forbidden_prefixes):
            forbidden.append(mod)

    assert not forbidden, f"{py_file} imports forbidden modules: {forbidden}"


def test_block_defensively_freezes_rows() -> None:
    from painted.block import Block
    from painted.cell import Cell, Style

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
        if (
            isinstance(decorator, ast.Call)
            and isinstance(decorator.func, ast.Name)
            and decorator.func.id == "dataclass"
        ):
            for kw in decorator.keywords:
                if (
                    kw.arg == "frozen"
                    and isinstance(kw.value, ast.Constant)
                    and kw.value.value is True
                ):
                    return True
            return False
    return None


def test_state_dataclasses_declared_frozen() -> None:
    painted_root = Path(__file__).resolve().parents[2] / "src" / "painted"

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

    for py_file in painted_root.rglob("*.py"):
        tree = ast.parse(py_file.read_text(encoding="utf-8"), filename=str(py_file))
        for node in tree.body:
            if not isinstance(node, ast.ClassDef):
                continue

            if node.name.endswith("State") or node.name in must_be_frozen:
                frozen = _dataclass_frozen_from_decorators(node)
                assert frozen is True, (
                    f"{py_file}: class {node.name} must be @dataclass(frozen=True)"
                )


def test_block_rows_private_not_accessed_outside_block() -> None:
    painted_root = Path(__file__).resolve().parents[2] / "src" / "painted"
    block_py = painted_root / "block.py"

    for py_file in painted_root.rglob("*.py"):
        if py_file == block_py:
            continue
        assert "._rows" not in py_file.read_text(encoding="utf-8"), (
            f"{py_file} accesses Block._rows directly"
        )


def test_runtime_state_dataclasses_are_frozen() -> None:
    from painted._components.data_explorer import DataExplorerState
    from painted._components.list_view import ListState
    from painted._components.progress import ProgressState
    from painted._components.spinner import SpinnerState
    from painted._components.table import TableState
    from painted._components.text_input import TextInputState
    from painted.borders import BorderChars
    from painted.cell import Cell, Style
    from painted.cursor import Cursor
    from painted.fidelity import CliContext
    from painted.focus import Focus
    from painted.icon_set import IconSet
    from painted.palette import Palette
    from painted.region import Region
    from painted.search import Search
    from painted.span import Line, Span
    from painted.viewport import Viewport

    for cls in (
        Region,
        Cell,
        Style,
        Span,
        Line,
        BorderChars,
        Focus,
        Search,
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


def test_primitives_do_not_import_tui() -> None:
    painted_root = Path(__file__).resolve().parents[2] / "src" / "painted"
    for py_file in (painted_root / "cell.py", painted_root / "span.py", painted_root / "block.py"):
        _assert_no_imports(py_file, {"painted.tui"})


def test_views_do_not_import_app() -> None:
    painted_root = Path(__file__).resolve().parents[2] / "src" / "painted"
    view_files: list[Path] = []
    view_files.extend(sorted((painted_root / "_components").rglob("*.py")))
    view_files.append(painted_root / "_lens.py")
    view_files.append(painted_root / "big_text.py")
    view_files.append(painted_root / "views" / "__init__.py")

    for py_file in view_files:
        _assert_no_imports(py_file, {"painted.app"})


def test_tui_does_not_import_views() -> None:
    painted_root = Path(__file__).resolve().parents[2] / "src" / "painted"
    for py_file in sorted((painted_root / "tui").rglob("*.py")):
        _assert_no_imports(py_file, {"painted.views"})


def test_public_modules_do_not_import_private_symbols_from_siblings() -> None:
    """Public modules may use internal modules, but not private sibling symbols.

    Exception: `painted._color` is the shared internal for color conversions.
    """
    painted_root = Path(__file__).resolve().parents[2] / "src" / "painted"
    src_root = painted_root.parent

    def imported_private_symbols(py_file: Path) -> list[str]:
        tree = ast.parse(py_file.read_text(encoding="utf-8"), filename=str(py_file))
        current_mod = _module_name_for_file(src_root, py_file)
        current_pkg = current_mod.rsplit(".", 1)[0] if "." in current_mod else current_mod

        bad: list[str] = []
        for node in ast.walk(tree):
            if not isinstance(node, ast.ImportFrom):
                continue
            base = _resolve_relative_module(current_pkg, level=node.level, module=node.module)
            for alias in node.names:
                if alias.name.startswith("_") and base != "painted._color":
                    bad.append(f"{base}:{alias.name}")
        return bad

    violations: list[str] = []
    for py_file in sorted(painted_root.rglob("*.py")):
        if py_file.name.startswith("_") and py_file.name != "__init__.py":
            continue
        for item in imported_private_symbols(py_file):
            violations.append(f"{py_file.relative_to(src_root)} imports {item}")

    assert not violations, "Public modules import private sibling symbols:\n" + "\n".join(
        violations
    )
