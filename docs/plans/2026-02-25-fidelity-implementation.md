# Fidelity-Aware Style Resolution — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Replace ComponentTheme + themes/ with Palette (5 semantic Style roles) and IconSet (glyph vocabulary), both ambient via ContextVar, with run_cli bridging capability detection to ambient defaults.

**Architecture:** ComponentTheme splits along its two axes — color/style becomes Palette, glyphs become IconSet. Both use the same ContextVar + kwarg escape hatch pattern ComponentTheme already uses. Views that consume color (progress_bar, sparkline) get `palette` kwarg; views that consume glyphs (tree_lens, chart_lens, spinner, progress_bar, sparkline) get `icons` kwarg. themes/ (0 consumers in component rendering) is deleted entirely.

**Tech Stack:** Python 3.11+, dataclasses (frozen), contextvars. No new dependencies.

**Design doc:** `docs/plans/2026-02-24-fidelity-design.md`

---

### Task 1: Create Palette type + ContextVar + presets

**Files:**
- Create: `src/painted/palette.py`
- Test: `tests/test_palette.py`

**Step 1: Write the failing tests**

```python
# tests/test_palette.py
"""Palette: semantic Style roles with ContextVar delivery."""
from __future__ import annotations

import pytest

from painted.cell import Style
from painted.palette import (
    Palette,
    DEFAULT_PALETTE,
    MONO_PALETTE,
    NORD_PALETTE,
    current_palette,
    use_palette,
    reset_palette,
)


def test_palette_is_frozen():
    p = Palette()
    with pytest.raises(AttributeError):
        p.accent = Style()  # type: ignore[misc]


def test_default_palette_roles_are_styles():
    p = DEFAULT_PALETTE
    for role in ("success", "warning", "error", "accent", "muted"):
        assert isinstance(getattr(p, role), Style)


def test_mono_palette_has_no_colors():
    """MONO_PALETTE uses modifiers only — no fg/bg."""
    p = MONO_PALETTE
    for role in ("success", "warning", "error", "accent", "muted"):
        s = getattr(p, role)
        assert s.fg is None, f"MONO_PALETTE.{role} should not set fg"
        assert s.bg is None, f"MONO_PALETTE.{role} should not set bg"


def test_mono_palette_roles_differ():
    """Each MONO_PALETTE role must be visually distinguishable."""
    p = MONO_PALETTE
    styles = {getattr(p, r) for r in ("success", "warning", "error", "accent", "muted")}
    # At least 4 distinct styles (muted=dim may overlap if another uses dim alone)
    assert len(styles) >= 4


def test_context_var_default():
    reset_palette()
    assert current_palette() is DEFAULT_PALETTE


def test_use_palette_sets_context():
    reset_palette()
    use_palette(MONO_PALETTE)
    assert current_palette() is MONO_PALETTE
    reset_palette()


def test_reset_palette_restores_default():
    use_palette(MONO_PALETTE)
    reset_palette()
    assert current_palette() is DEFAULT_PALETTE


def test_palette_compose_with_merge():
    """Views compose palette roles with structural emphasis via Style.merge."""
    p = DEFAULT_PALETTE
    composed = p.accent.merge(Style(bold=True))
    assert composed.fg == p.accent.fg
    assert composed.bold is True
```

**Step 2: Run tests to verify they fail**

Run: `uv run --package painted pytest tests/test_palette.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'painted.palette'`

**Step 3: Write minimal implementation**

```python
# src/painted/palette.py
"""Palette: semantic Style roles for aesthetic personalization.

5 roles mapping to Style (not Color) — carries both color and modifier
fallbacks for monochrome output.

Usage:
    from painted.palette import current_palette, use_palette, MONO_PALETTE

    p = current_palette()
    fill_style = p.accent.merge(Style(bold=True))

    # Override ambient palette
    use_palette(MONO_PALETTE)
"""

from __future__ import annotations

from contextvars import ContextVar
from dataclasses import dataclass, field

from .cell import Style


@dataclass(frozen=True)
class Palette:
    """Semantic style roles for aesthetic personalization.

    Each role is a Style (not a Color) so that monochrome palettes can
    use modifiers (bold, reverse, dim) for differentiation.
    """

    success: Style = field(default_factory=lambda: Style(fg="green"))
    warning: Style = field(default_factory=lambda: Style(fg="yellow"))
    error: Style = field(default_factory=lambda: Style(fg="red"))
    accent: Style = field(default_factory=lambda: Style(fg="cyan"))
    muted: Style = field(default_factory=lambda: Style(dim=True))


# --- Presets ---

DEFAULT_PALETTE = Palette()

NORD_PALETTE = Palette(
    success=Style(fg=108),
    warning=Style(fg=179),
    error=Style(fg=174),
    accent=Style(fg=110),
    muted=Style(fg=60),
)

MONO_PALETTE = Palette(
    success=Style(bold=True),
    warning=Style(underline=True),
    error=Style(bold=True, reverse=True),
    accent=Style(bold=True),
    muted=Style(dim=True),
)

# --- ContextVar delivery ---

_palette: ContextVar[Palette] = ContextVar("palette", default=DEFAULT_PALETTE)


def current_palette() -> Palette:
    """Get the ambient palette."""
    return _palette.get()


def use_palette(palette: Palette) -> None:
    """Set the ambient palette for the current context."""
    _palette.set(palette)


def reset_palette() -> None:
    """Reset to the default palette."""
    _palette.set(DEFAULT_PALETTE)
```

**Step 4: Run tests to verify they pass**

Run: `uv run --package painted pytest tests/test_palette.py -v`
Expected: PASS (all 8 tests)

**Step 5: Add Palette to architecture invariants**

Edit `tests/test_architecture_invariants.py`:
- Add `"Palette"` to the `must_be_frozen` set in `test_state_dataclasses_declared_frozen`
- Add `from painted.palette import Palette` and include `Palette` in the runtime frozen check tuple in `test_runtime_state_dataclasses_are_frozen`

**Step 6: Run full test suite**

Run: `uv run --package painted pytest tests/ -q`
Expected: All pass (439 + new tests)

**Step 7: Commit**

```bash
git add src/painted/palette.py tests/test_palette.py tests/test_architecture_invariants.py
git commit -m "Add Palette type with ContextVar delivery and presets"
```

---

### Task 2: Create IconSet type + ContextVar

**Files:**
- Create: `src/painted/icon_set.py`
- Test: `tests/test_icon_set.py`

**Step 1: Write the failing tests**

```python
# tests/test_icon_set.py
"""IconSet: glyph vocabulary with ContextVar delivery."""
from __future__ import annotations

import pytest

from painted.icon_set import (
    IconSet,
    ASCII_ICONS,
    current_icons,
    use_icons,
    reset_icons,
)


def test_icon_set_is_frozen():
    icons = IconSet()
    with pytest.raises(AttributeError):
        icons.check = "X"  # type: ignore[misc]


def test_default_icon_set_uses_unicode():
    icons = IconSet()
    assert icons.check == "✓"
    assert icons.cross == "✗"
    assert "█" in icons.progress_fill


def test_ascii_icons_are_ascii_safe():
    for field_name in ("check", "cross", "progress_fill", "progress_empty",
                       "tree_branch", "tree_last", "tree_indent"):
        val = getattr(ASCII_ICONS, field_name)
        assert all(ord(c) < 128 for c in val), f"ASCII_ICONS.{field_name} has non-ASCII"


def test_sparkline_chars_length():
    """Sparkline needs 8 levels for proper resolution."""
    icons = IconSet()
    assert len(icons.sparkline) == 8
    assert len(ASCII_ICONS.sparkline) == 8


def test_context_var_default():
    reset_icons()
    default = current_icons()
    assert default.check == "✓"


def test_use_icons_sets_context():
    reset_icons()
    use_icons(ASCII_ICONS)
    assert current_icons() is ASCII_ICONS
    reset_icons()


def test_reset_icons_restores_default():
    use_icons(ASCII_ICONS)
    reset_icons()
    assert current_icons().check == "✓"
```

**Step 2: Run tests to verify they fail**

Run: `uv run --package painted pytest tests/test_icon_set.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'painted.icon_set'`

**Step 3: Write minimal implementation**

Port fields from `Icons` in `component_theme.py` (lines 31-61), renamed per design doc. The `sparkline` field changes from `str` to `tuple[str, ...]` for consistency with the design doc and to match how it's actually consumed (indexed by level).

```python
# src/painted/icon_set.py
"""IconSet: glyph vocabulary for view rendering.

Replaces ComponentTheme.Icons. Style fields removed (those move to Palette).

Usage:
    from painted.icon_set import current_icons, use_icons, ASCII_ICONS

    icons = current_icons()
    fill = icons.progress_fill
"""

from __future__ import annotations

from contextvars import ContextVar
from dataclasses import dataclass
from typing import Sequence


@dataclass(frozen=True)
class IconSet:
    """Named glyph slots for view rendering.

    Covers both capability adaptation (ASCII fallback) and user preference
    (DOTS vs BRAILLE spinner frames).
    """

    # Spinner frames
    spinner: Sequence[str] = ("⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏")

    # Progress bar
    progress_fill: str = "█"
    progress_empty: str = "░"

    # Tree branches
    tree_branch: str = "├─ "
    tree_last: str = "└─ "
    tree_indent: str = "│  "
    tree_space: str = "   "

    # Status indicators
    check: str = "✓"
    cross: str = "✗"

    # Sparkline (8 levels, low to high)
    sparkline: tuple[str, ...] = ("▁", "▂", "▃", "▄", "▅", "▆", "▇", "█")

    # Bar chart
    bar_fill: str = "█"
    bar_empty: str = "░"


ASCII_ICONS = IconSet(
    spinner=("-", "\\", "|", "/"),
    progress_fill="#",
    progress_empty="-",
    tree_branch="+-- ",
    tree_last="`-- ",
    tree_indent="|   ",
    tree_space="    ",
    check="[x]",
    cross="[!]",
    sparkline=("_", ".", "-", "~", "^", "*", "#", "@"),
    bar_fill="#",
    bar_empty="-",
)


# --- ContextVar delivery ---

_DEFAULT_ICONS = IconSet()

_icons: ContextVar[IconSet] = ContextVar("icons", default=_DEFAULT_ICONS)


def current_icons() -> IconSet:
    """Get the ambient icon set."""
    return _icons.get()


def use_icons(icons: IconSet) -> None:
    """Set the ambient icon set for the current context."""
    _icons.set(icons)


def reset_icons() -> None:
    """Reset to the default icon set."""
    _icons.set(_DEFAULT_ICONS)
```

**Note on sparkline field type change:** The existing `Icons.sparkline` is a `str` (`"▁▂▃▄▅▆▇█"`), but consumers index into it character-by-character. The new `IconSet.sparkline` is `tuple[str, ...]` for explicit indexing. Consumers that do `chars[i]` work identically with both types. The `_sparkline_core.py` module already accepts the chars parameter and indexes into it — verify it works with tuples too.

**Step 4: Run tests to verify they pass**

Run: `uv run --package painted pytest tests/test_icon_set.py -v`
Expected: PASS (all 7 tests)

**Step 5: Add IconSet to architecture invariants**

Edit `tests/test_architecture_invariants.py`:
- Add `"IconSet"` to the `must_be_frozen` set
- Add `from painted.icon_set import IconSet` and include in runtime frozen check tuple

**Step 6: Run full test suite**

Run: `uv run --package painted pytest tests/ -q`
Expected: All pass

**Step 7: Commit**

```bash
git add src/painted/icon_set.py tests/test_icon_set.py tests/test_architecture_invariants.py
git commit -m "Add IconSet type with ContextVar delivery and ASCII fallback"
```

---

### Task 3: Update progress_bar and sparkline to use Palette + IconSet

**Files:**
- Modify: `src/painted/_components/progress.py`
- Modify: `src/painted/_components/sparkline.py`
- Create: `tests/test_progress_bar.py`
- Create: `tests/test_sparkline_themed.py`

This is the critical task — the two views that use color switch from `theme: ComponentTheme` to `palette: Palette | None` + `icons: IconSet | None`. The `theme` kwarg is removed (clean break at 0.1.0).

**Step 1: Write failing tests for progress_bar**

```python
# tests/test_progress_bar.py
"""Progress bar rendering with Palette and IconSet."""
from __future__ import annotations

from painted.cell import Style
from painted._components.progress import ProgressState, progress_bar
from painted.palette import Palette, MONO_PALETTE, DEFAULT_PALETTE, current_palette, use_palette, reset_palette
from painted.icon_set import IconSet, ASCII_ICONS, current_icons, use_icons, reset_icons


def test_progress_bar_default_no_args():
    """progress_bar with no palette/icons uses ambient defaults."""
    reset_palette()
    reset_icons()
    state = ProgressState(value=0.5)
    block = progress_bar(state, width=10)
    assert block.width == 10
    assert block.height == 1


def test_progress_bar_explicit_palette():
    state = ProgressState(value=0.5)
    block = progress_bar(state, width=10, palette=MONO_PALETTE)
    row = block.row(0)
    filled_cell = row[0]
    # MONO_PALETTE.accent is Style(bold=True) — fill should include bold
    # (merged with structural emphasis)
    assert filled_cell.style.bold is True


def test_progress_bar_explicit_icons():
    state = ProgressState(value=0.5)
    block = progress_bar(state, width=10, icons=ASCII_ICONS)
    row = block.row(0)
    assert row[0].char == "#"  # ASCII_ICONS.progress_fill
    assert row[-1].char == "-"  # ASCII_ICONS.progress_empty


def test_progress_bar_ambient_palette():
    """Ambient palette flows through without explicit kwarg."""
    reset_palette()
    use_palette(MONO_PALETTE)
    state = ProgressState(value=1.0)
    block = progress_bar(state, width=4)
    row = block.row(0)
    # All filled, should use MONO_PALETTE.accent
    assert row[0].style.bold is True
    reset_palette()


def test_progress_bar_style_overrides_palette():
    """Explicit filled_style takes precedence over palette."""
    custom = Style(fg="magenta")
    state = ProgressState(value=1.0)
    block = progress_bar(state, width=4, filled_style=custom)
    assert block.row(0)[0].style.fg == "magenta"
```

**Step 2: Run tests to verify they fail**

Run: `uv run --package painted pytest tests/test_progress_bar.py -v`
Expected: FAIL — progress_bar doesn't accept `palette` or `icons` kwargs yet

**Step 3: Implement progress_bar changes**

Modify `src/painted/_components/progress.py`:
- Remove `from ..component_theme import ComponentTheme` (TYPE_CHECKING import, line 12)
- Replace `theme: "ComponentTheme | None" = None` with `palette: "Palette | None" = None` and `icons: "IconSet | None" = None`
- Resolve via `p = palette or current_palette()` and `ic = icons or current_icons()`
- Fill style: `filled_style or p.accent.merge(Style(bold=True))`
- Empty style: `empty_style or p.muted`
- Fill char: `filled_char or ic.progress_fill`
- Empty char: `empty_char or ic.progress_empty`

The full function becomes:

```python
def progress_bar(
    state: ProgressState,
    width: int,
    *,
    filled_style: Style | None = None,
    empty_style: Style | None = None,
    filled_char: str | None = None,
    empty_char: str | None = None,
    palette: "Palette | None" = None,
    icons: "IconSet | None" = None,
) -> Block:
    """Render a horizontal progress bar.

    Args:
        state: Current progress state (0.0-1.0).
        width: Width in characters.
        filled_style: Style for filled portion. Defaults to palette.accent + bold.
        empty_style: Style for empty portion. Defaults to palette.muted.
        filled_char: Character for filled portion. Defaults to icons.progress_fill.
        empty_char: Character for empty portion. Defaults to icons.progress_empty.
        palette: Optional Palette override (uses ambient if None).
        icons: Optional IconSet override (uses ambient if None).

    Returns:
        Block with rendered progress bar.
    """
    from ..palette import Palette, current_palette
    from ..icon_set import current_icons

    p = palette or current_palette()
    ic = icons or current_icons()

    filled_char = filled_char or ic.progress_fill
    empty_char = empty_char or ic.progress_empty
    filled_style = filled_style or p.accent.merge(Style(bold=True))
    empty_style = empty_style or p.muted

    filled_count = round(state.value * width)
    empty_count = width - filled_count

    cells = (
        [Cell(filled_char, filled_style)] * filled_count
        + [Cell(empty_char, empty_style)] * empty_count
    )
    return Block([cells], width)
```

The TYPE_CHECKING imports change to:
```python
if TYPE_CHECKING:
    from ..palette import Palette
    from ..icon_set import IconSet
```

**Step 4: Run progress_bar tests**

Run: `uv run --package painted pytest tests/test_progress_bar.py -v`
Expected: PASS

**Step 5: Write failing tests for sparkline**

```python
# tests/test_sparkline_themed.py
"""Sparkline rendering with Palette and IconSet."""
from __future__ import annotations

from painted.cell import Style
from painted._components.sparkline import sparkline, sparkline_with_range
from painted.palette import MONO_PALETTE, reset_palette, use_palette
from painted.icon_set import ASCII_ICONS, reset_icons, use_icons


def test_sparkline_default():
    reset_palette()
    reset_icons()
    block = sparkline([1, 2, 3], width=3)
    assert block.width == 3
    assert block.height == 1


def test_sparkline_explicit_palette():
    block = sparkline([1, 2, 3], width=3, palette=MONO_PALETTE)
    # MONO_PALETTE.muted is Style(dim=True) — default sparkline style
    assert block.row(0)[0].style.dim is True
    assert block.row(0)[0].style.fg is None


def test_sparkline_explicit_icons():
    block = sparkline([0, 50, 100], width=3, icons=ASCII_ICONS)
    row = block.row(0)
    # ASCII sparkline chars: ("_", ".", "-", "~", "^", "*", "#", "@")
    # All chars should be from ASCII set
    for cell in row:
        assert ord(cell.char) < 128


def test_sparkline_ambient_icons():
    reset_icons()
    use_icons(ASCII_ICONS)
    block = sparkline([0, 50, 100], width=3)
    row = block.row(0)
    for cell in row:
        assert ord(cell.char) < 128
    reset_icons()


def test_sparkline_with_range_palette():
    block = sparkline_with_range(
        [10, 50, 90], width=3,
        min_val=0, max_val=100,
        palette=MONO_PALETTE,
    )
    assert block.row(0)[0].style.dim is True


def test_sparkline_style_overrides_palette():
    custom = Style(fg="magenta")
    block = sparkline([1, 2, 3], width=3, style=custom, palette=MONO_PALETTE)
    assert block.row(0)[0].style.fg == "magenta"
```

**Step 6: Implement sparkline changes**

Modify `src/painted/_components/sparkline.py`:
- Remove `from ..component_theme import ComponentTheme, component_theme` (line 19)
- Replace `theme: ComponentTheme | None = None` with `palette: "Palette | None" = None` and `icons: "IconSet | None" = None` in both `sparkline()` and `sparkline_with_range()`
- Replace `t = theme or component_theme()` with `p = palette or current_palette()` and `ic = icons or current_icons()`
- `style = style or p.muted`
- `chars = ic.sparkline`

**Important:** The `_sparkline_core.sparkline_text()` function receives `chars` as a parameter. Currently `Icons.sparkline` is a `str` (e.g., `"▁▂▃▄▅▆▇█"`). The new `IconSet.sparkline` is a `tuple[str, ...]`. Verify `_sparkline_core.py` indexes into `chars` with `chars[i]` — this works identically for both `str` and `tuple[str, ...]`. If it does string slicing or concatenation on `chars`, that will need adjustment.

Check: `src/painted/_sparkline_core.py` — look at how `chars` is used.

**Step 7: Run sparkline tests**

Run: `uv run --package painted pytest tests/test_sparkline_themed.py -v`
Expected: PASS

**Step 8: Run full test suite**

Run: `uv run --package painted pytest tests/ -q`
Expected: All pass. Existing tests that don't pass `theme=` should still work (ambient defaults match old hardcoded defaults).

**Step 9: Commit**

```bash
git add src/painted/_components/progress.py src/painted/_components/sparkline.py \
        tests/test_progress_bar.py tests/test_sparkline_themed.py
git commit -m "Update progress_bar and sparkline to use Palette + IconSet"
```

---

### Task 4: Update tree_lens, chart_lens, and spinner to use IconSet

**Files:**
- Modify: `src/painted/_lens.py` (lines 310-316 `_get_tree_icons`, lines 325 `tree_lens`, lines 525-531 `_get_chart_icons`, lines 539 `chart_lens`)
- Modify: `src/painted/_components/spinner.py` (lines 41-73)
- Test: `tests/test_icon_set_views.py`

These views use only glyphs from ComponentTheme (no color roles). They switch from `theme: ComponentTheme` to `icons: IconSet | None`.

**Step 1: Write failing tests**

```python
# tests/test_icon_set_views.py
"""Views that consume IconSet for glyph vocabulary."""
from __future__ import annotations

from painted.cell import Style
from painted.icon_set import ASCII_ICONS, IconSet, reset_icons, use_icons
from painted._components.spinner import SpinnerState, spinner, DOTS
from painted.views import tree_lens, chart_lens


def test_spinner_ambient_icons():
    reset_icons()
    use_icons(ASCII_ICONS)
    state = SpinnerState()
    block = spinner(state)
    # ASCII spinner: ("-", "\\", "|", "/") — frame 0 is "-"
    assert block.row(0)[0].char == "-"
    reset_icons()


def test_spinner_explicit_icons():
    state = SpinnerState()
    block = spinner(state, icons=ASCII_ICONS)
    assert block.row(0)[0].char == "-"


def test_spinner_style_kwarg_still_works():
    state = SpinnerState()
    block = spinner(state, style=Style(fg="red"))
    assert block.row(0)[0].style.fg == "red"


def test_tree_lens_explicit_icons():
    data = {"root": {"child": "leaf"}}
    block = tree_lens(data, zoom=2, width=40, icons=ASCII_ICONS)
    text = "".join(c.char for c in block.row(1))
    # ASCII tree uses "+-- " for branches
    assert "+--" in text or "`--" in text


def test_chart_lens_explicit_icons():
    data = [10, 20, 30, 40, 50]
    block = chart_lens(data, zoom=1, width=10, icons=ASCII_ICONS)
    row = block.row(0)
    # ASCII sparkline chars should all be ASCII
    for cell in row:
        assert ord(cell.char) < 128
```

**Step 2: Run tests to verify they fail**

Run: `uv run --package painted pytest tests/test_icon_set_views.py -v`
Expected: FAIL — views don't accept `icons` kwarg

**Step 3: Implement changes**

**spinner.py** — Modify `src/painted/_components/spinner.py`:
- Remove TYPE_CHECKING import of ComponentTheme (line 13)
- Replace `theme: "ComponentTheme | None" = None` with `icons: "IconSet | None" = None`
- Resolve: `ic = icons or current_icons()`
- Frame selection: `if ic is not current default and state.frames is DOTS: frames = ic.spinner`
- Keep `style` kwarg as-is (spinner style is caller's choice per design doc — "caller chooses role")

**_lens.py** — Modify `src/painted/_lens.py`:
- Remove TYPE_CHECKING import of ComponentTheme (line 16)
- Replace `_get_tree_icons(theme)` to accept `icons: IconSet | None`:
  ```python
  def _get_tree_icons(icons: "IconSet | None") -> tuple[str, str, str, str]:
      from .icon_set import current_icons
      ic = icons or current_icons()
      return ic.tree_branch, ic.tree_last, ic.tree_indent, ic.tree_space
  ```
- Replace `theme: "ComponentTheme | None" = None` with `icons: "IconSet | None" = None` in `tree_lens()` signature (line 325)
- Same pattern for `_get_chart_icons` and `chart_lens()`:
  ```python
  def _get_chart_icons(icons: "IconSet | None") -> tuple[str | tuple[str, ...], str, str]:
      from .icon_set import current_icons
      ic = icons or current_icons()
      return ic.sparkline, ic.bar_fill, ic.bar_empty
  ```
- Replace `theme` with `icons` in `chart_lens()` signature (line 539)

**Note on sparkline chars type:** `_get_chart_icons` currently returns `str` for sparkline chars. The new `IconSet.sparkline` is `tuple[str, ...]`. The return type annotation needs to accommodate this. Check all call sites of `_get_chart_icons` — both `_chart_sparkline_themed()` and `_chart_bars_themed()` — to ensure they work with tuple.

**Step 4: Run tests**

Run: `uv run --package painted pytest tests/test_icon_set_views.py -v`
Expected: PASS

**Step 5: Run full test suite**

Run: `uv run --package painted pytest tests/ -q`
Expected: All pass. Existing tests don't pass `theme=` so they use ambient defaults (same values as before).

**Step 6: Commit**

```bash
git add src/painted/_components/spinner.py src/painted/_lens.py tests/test_icon_set_views.py
git commit -m "Update spinner, tree_lens, chart_lens to use IconSet"
```

---

### Task 5: Add _setup_defaults() bridge in run_cli

**Files:**
- Modify: `src/painted/fidelity.py` (add `_setup_defaults` after `detect_context`, call from `CliRunner._dispatch`)
- Test: `tests/test_fidelity_defaults.py`

**Step 1: Write failing tests**

```python
# tests/test_fidelity_defaults.py
"""run_cli sets ambient IconSet from resolved context.

Palette is never auto-set — it's a deliberate aesthetic choice.
"""
from __future__ import annotations

from painted.fidelity import CliContext, Format, OutputMode, Zoom
from painted.fidelity import _setup_defaults
from painted.palette import current_palette, reset_palette, DEFAULT_PALETTE
from painted.icon_set import current_icons, reset_icons, ASCII_ICONS, IconSet


def test_plain_format_sets_ascii_icons():
    reset_palette()
    reset_icons()
    ctx = CliContext(
        zoom=Zoom.SUMMARY,
        mode=OutputMode.STATIC,
        format=Format.PLAIN,
        is_tty=False,
        width=80,
        height=24,
    )
    _setup_defaults(ctx)
    assert current_icons() is ASCII_ICONS
    # Palette is NOT auto-set — stays at default
    assert current_palette() is DEFAULT_PALETTE
    reset_palette()
    reset_icons()


def test_ansi_format_keeps_default_icons():
    reset_palette()
    reset_icons()
    ctx = CliContext(
        zoom=Zoom.SUMMARY,
        mode=OutputMode.STATIC,
        format=Format.ANSI,
        is_tty=True,
        width=80,
        height=24,
    )
    _setup_defaults(ctx)
    # Both stay at defaults
    assert current_palette() is DEFAULT_PALETTE
    assert current_icons().check == IconSet().check  # unicode default
    reset_palette()
    reset_icons()
```

**Step 2: Run tests to verify they fail**

Run: `uv run --package painted pytest tests/test_fidelity_defaults.py -v`
Expected: FAIL — `_setup_defaults` doesn't exist

**Step 3: Implement _setup_defaults**

Add to `src/painted/fidelity.py` after `detect_context()` (after line 127):

```python
def _setup_defaults(ctx: CliContext) -> None:
    """Set ambient IconSet from resolved runtime context.

    Palette is never auto-set — it's a deliberate aesthetic choice.
    MONO_PALETTE exists for explicit opt-in (e.g., low-vision, e-ink),
    not as a Format.PLAIN default.
    """
    from .icon_set import use_icons, ASCII_ICONS

    if ctx.format == Format.PLAIN:
        use_icons(ASCII_ICONS)
```

Call it from `CliRunner._dispatch()` at the start (before line 277):

```python
def _dispatch(self, ctx: CliContext) -> int:
    """Dispatch to appropriate output mechanism."""
    _setup_defaults(ctx)
    # ... rest unchanged
```

**Step 4: Run tests**

Run: `uv run --package painted pytest tests/test_fidelity_defaults.py -v`
Expected: PASS

**Step 5: Run full test suite**

Run: `uv run --package painted pytest tests/ -q`
Expected: All pass

**Step 6: Commit**

```bash
git add src/painted/fidelity.py tests/test_fidelity_defaults.py
git commit -m "Add _setup_defaults bridge: run_cli sets ambient palette/icons"
```

---

### Task 6: Delete themes/ and ComponentTheme

**Files:**
- Delete: `src/painted/themes/__init__.py` (323 LOC)
- Delete: `src/painted/component_theme.py` (136 LOC)
- Modify: `src/painted/__init__.py` (remove ComponentTheme exports, add Palette/IconSet)
- Modify: `src/painted/views/__init__.py` (add Palette/IconSet re-exports)
- Modify: `demos/apps/theme_carnival.py` (the only themes/ consumer — update or delete)

**Step 1: Remove ComponentTheme imports from all view modules**

At this point, Tasks 3 and 4 have already removed the `theme: ComponentTheme` kwarg from all view functions. Verify no remaining references:

Run: `grep -r "component_theme\|ComponentTheme" src/painted/ --include="*.py"`

Expected: Only hits in `component_theme.py` itself and `__init__.py` (the re-exports). If any view module still references it, fix that first.

**Step 2: Delete the files**

```bash
rm src/painted/themes/__init__.py
rmdir src/painted/themes/
rm src/painted/component_theme.py
```

**Step 3: Update `src/painted/__init__.py`**

Remove lines 57-67 (ComponentTheme imports) and lines 116-125 (ComponentTheme `__all__` entries).

Replace with Palette and IconSet exports:

```python
# Aesthetic
from .palette import (
    Palette,
    DEFAULT_PALETTE,
    NORD_PALETTE,
    MONO_PALETTE,
    current_palette,
    use_palette,
    reset_palette,
)
from .icon_set import (
    IconSet,
    ASCII_ICONS,
    current_icons,
    use_icons,
    reset_icons,
)
```

And the corresponding `__all__` entries:

```python
    # Aesthetic
    "Palette",
    "DEFAULT_PALETTE",
    "NORD_PALETTE",
    "MONO_PALETTE",
    "current_palette",
    "use_palette",
    "reset_palette",
    "IconSet",
    "ASCII_ICONS",
    "current_icons",
    "use_icons",
    "reset_icons",
```

Update the module docstring to replace the component theming lines with:

```python
# For aesthetic customization:
#     from painted import current_palette, use_palette, MONO_PALETTE
#     from painted import current_icons, use_icons, ASCII_ICONS
```

Remove the `painted.themes` reference from the docstring (line 13).

**Step 4: Handle theme_carnival.py demo**

`demos/apps/theme_carnival.py` is the only consumer of `painted.themes`. Options:
- Delete it (it demos the system being deleted)
- Rewrite it to use Palette (show Palette switching instead of Theme switching)

Rewrite is better — it becomes the Palette demo. The core idea (runtime aesthetic switching) still applies, just with a simpler type. Update imports and rendering to use `Palette` roles instead of `Theme` computed properties. This is a demo, not library code — exact implementation left to the implementer but the shape is:

```python
from painted import current_palette, use_palette, Palette, DEFAULT_PALETTE, NORD_PALETTE, MONO_PALETTE
# Show palette switching in a simple TUI
```

**Step 5: Run full test suite**

Run: `uv run --package painted pytest tests/ -q`

Expected: All pass. If any test imported ComponentTheme or themes, it will fail — fix those. (The explore agent found zero test references to either, so this should be clean.)

**Step 6: Commit**

```bash
git add -A  # captures deletions + modifications
git commit -m "Delete themes/ and ComponentTheme, export Palette + IconSet from top level"
```

---

### Task 7: Update remaining demos

**Files:**
- Modify: Any demo files that reference `ComponentTheme`, `component_theme()`, `use_component_theme()`, or `Icons`
- Check: `demos/` directory for all theming references

**Step 1: Audit demo references**

Run: `grep -r "component_theme\|ComponentTheme\|use_component_theme\|Icons\b" demos/ --include="*.py"`

For each hit, update to use `Palette`/`IconSet` equivalents:
- `component_theme()` → `current_palette()` / `current_icons()` depending on usage
- `use_component_theme(ASCII_COMPONENT_THEME)` → `use_palette(MONO_PALETTE)` + `use_icons(ASCII_ICONS)`
- `theme.accent` → `current_palette().accent`
- `theme.icons.spinner` → `current_icons().spinner`

**Step 2: Run demos manually to verify they render**

Run a representative demo: `uv run python demos/tour.py` (if it uses theming)

**Step 3: Run full test suite**

Run: `uv run --package painted pytest tests/ -q`
Expected: All pass

**Step 4: Commit**

```bash
git add demos/
git commit -m "Update demos to use Palette + IconSet"
```

---

### Task 8: Update docs and CLAUDE.md

**Files:**
- Modify: `CLAUDE.md` (replace ComponentTheme/Icons/themes references with Palette/IconSet)
- Modify: `HANDOFF.md` (update current state, mark fidelity implementation as complete)
- Modify: `LOG.md` (add session entry)
- Modify: `docs/guides/` (any guide referencing ComponentTheme or themes)

**Step 1: Update CLAUDE.md**

In the Source Layout section, replace:
```
  component_theme.py  # ComponentTheme, Icons, ContextVar
  themes/             # Runtime theme switching (app-level)
```
with:
```
  palette.py          # Palette (5 Style roles), ContextVar, presets
  icon_set.py         # IconSet (glyph vocabulary), ContextVar, ASCII fallback
```

In the Key Types section, replace the ComponentTheme/Icons entries with:

| Type | Purpose |
|------|---------|
| `Palette` | 5 semantic Style roles (success, warning, error, accent, muted), ContextVar |
| `IconSet` | Named glyph slots (spinner, progress, tree, sparkline), ContextVar |

In the Package Structure section, update the import examples:

```python
from painted import Palette, IconSet, current_palette, use_palette  # Aesthetic
```

Remove references to `painted.themes`, `ComponentTheme`, `Icons`.

**Step 2: Update HANDOFF.md**

Update the "Current State" and "Completed" sections to reflect the implementation.

**Step 3: Add LOG.md entry**

Add a session entry documenting what was implemented.

**Step 4: Update docs/guides/ if needed**

Run: `grep -r "ComponentTheme\|component_theme\|themes" docs/guides/ --include="*.md"`

Update any references found.

**Step 5: Run docgen check**

Run: `uv run python -m tools.docgen --check --roots docs/guides`

If any extracted snippets reference deleted modules, update the guide source.

**Step 6: Commit**

```bash
git add CLAUDE.md HANDOFF.md LOG.md docs/
git commit -m "Update docs for Palette + IconSet (fidelity implementation)"
```

---

## Summary of Changes

| File | Action | LOC Delta (est.) |
|------|--------|-----------------|
| `src/painted/palette.py` | Create | +65 |
| `src/painted/icon_set.py` | Create | +80 |
| `src/painted/component_theme.py` | Delete | -136 |
| `src/painted/themes/__init__.py` | Delete | -323 |
| `src/painted/_components/progress.py` | Modify | ~0 (swap theme→palette+icons) |
| `src/painted/_components/sparkline.py` | Modify | ~0 (swap theme→palette+icons) |
| `src/painted/_components/spinner.py` | Modify | ~0 (swap theme→icons) |
| `src/painted/_lens.py` | Modify | ~0 (swap theme→icons) |
| `src/painted/fidelity.py` | Modify | +10 (_setup_defaults) |
| `src/painted/__init__.py` | Modify | ~0 (swap exports) |
| `tests/test_palette.py` | Create | +70 |
| `tests/test_icon_set.py` | Create | +55 |
| `tests/test_progress_bar.py` | Create | +50 |
| `tests/test_sparkline_themed.py` | Create | +50 |
| `tests/test_icon_set_views.py` | Create | +45 |
| `tests/test_fidelity_defaults.py` | Create | +40 |
| **Net** | | **~-315 deleted, +465 added** (~+150 net, mostly tests) |

## Risks and Mitigations

1. **sparkline chars type change** (str → tuple): The `_sparkline_core.py` module receives `chars` as a parameter. If it uses string concatenation or slicing on chars, the tuple type will break. **Mitigation:** Check `_sparkline_core.py` during Task 3; if it does `chars[i]` (indexing), it works for both types. If it does `chars[start:end]`, tuple slicing also works. Only `chars + "x"` concatenation would break.

2. **Demo breakage** (theme_carnival): The only meaningful consumer of the deleted code. **Mitigation:** Rewrite in Task 6, verify it runs.

3. **External consumers** (loops monorepo): The `cells-to-painted` migration is in review. If it references ComponentTheme, it will need updating. **Mitigation:** Check after merge; the migration should have converted to whatever painted exports.

4. **Architecture invariant test** picks up Palette/IconSet automatically via the `*State` suffix heuristic — but these don't end in `State`. **Mitigation:** Explicitly add to `must_be_frozen` set in Tasks 1 and 2.
