#!/usr/bin/env python3
"""Palette Carnival — interactive Palette explorer with live switching.

A demo showcasing runtime palette switching. `Palette` is a small set of
semantic Style roles used by view components (progress bar, sparkline, etc.).

Run: `uv run python demos/apps/theme_carnival.py`
Keys: 1-3 jump to palette, ←/→ cycle, ↑/↓ scroll, q quit
Mouse: scroll wheel to scroll
"""

from __future__ import annotations

import asyncio

from painted import (
    Block,
    DEFAULT_PALETTE,
    MONO_PALETTE,
    NORD_PALETTE,
    Palette,
    Style,
    Viewport,
    current_palette,
    join_horizontal,
    join_responsive,
    join_vertical,
    pad,
    use_palette,
    vslice,
)
from painted.mouse import MouseEvent
from painted.tui import Surface
from painted.views import ProgressState, SpinnerState, progress_bar, spinner


class PaletteCarnival(Surface):
    """Interactive palette explorer with live preview."""

    def __init__(self) -> None:
        super().__init__(enable_mouse=True)
        self.palettes: list[tuple[str, Palette]] = [
            ("default", DEFAULT_PALETTE),
            ("nord", NORD_PALETTE),
            ("mono", MONO_PALETTE),
        ]
        self.palette_index = 0
        use_palette(self.palettes[self.palette_index][1])

        self.spinner_state = SpinnerState()
        self.progress_value = 0.0
        self.progress_direction = 1
        self.frame = 0
        self.viewport = Viewport()

    def update(self) -> None:
        """Animate spinner and progress bar."""
        self.frame += 1

        # Spinner ticks every 6 frames
        if self.frame % 6 == 0:
            self.spinner_state = self.spinner_state.tick()
            self.mark_dirty()

        # Progress bar bounces back and forth
        if self.frame % 3 == 0:
            self.progress_value += 0.02 * self.progress_direction
            if self.progress_value >= 1.0:
                self.progress_value = 1.0
                self.progress_direction = -1
            elif self.progress_value <= 0.0:
                self.progress_value = 0.0
                self.progress_direction = 1
            self.mark_dirty()

    def _build_content(self, palette: Palette, panel_width: int, full_width: int) -> Block:
        """Build the scrollable content area as a Block."""
        sections: list[Block] = []

        name, _ = self.palettes[self.palette_index]

        sections.append(Block.text(f"Current: {name.upper()}", palette.accent.merge(Style(bold=True))))
        sections.append(Block.empty(panel_width, 1))

        sections.append(Block.text("Status:", palette.muted))
        connected_block = Block.text("● Connected", palette.success)
        error_block = Block.text("✕ Error", palette.error)
        warning_block = Block.text("⚡ Warning", palette.warning)
        spin_block = spinner(self.spinner_state, style=palette.warning)
        status_row = join_responsive(
            connected_block,
            error_block,
            warning_block,
            spin_block,
            available_width=panel_width - 2,
            gap=2,
        )
        sections.append(pad(status_row, left=2))
        sections.append(Block.empty(panel_width, 1))

        sections.append(Block.text("Levels:", palette.muted))
        levels = [
            ("ERROR", palette.error.merge(Style(bold=True)), "something went wrong"),
            ("WARN ", palette.warning, "a warning appeared"),
            ("INFO ", Style(), "normal operation"),
            ("DEBUG", palette.muted, "verbose output"),
        ]
        for label, level_style, msg in levels:
            sections.append(pad(join_horizontal(Block.text(label, level_style), Block.text(" " + msg, Style())), left=2))
        sections.append(Block.empty(panel_width, 1))

        sections.append(Block.text("Progress:", palette.muted))
        pbar_width = max(10, panel_width - 12)
        pbar = progress_bar(
            ProgressState(value=self.progress_value),
            width=pbar_width,
            filled_style=palette.success.merge(Style(bold=True)),
            empty_style=palette.muted,
        )
        pct = int(self.progress_value * 100)
        sections.append(pad(join_horizontal(pbar, Block.text(f" {pct:3d}%", Style())), left=2))
        sections.append(Block.empty(panel_width, 1))

        sections.append(Block.text("Actions:", palette.muted))
        save_btn = Block.text(" Save ", palette.accent.merge(Style(bold=True)))
        cancel_btn = Block.text(" Cancel ", Style())
        delete_btn = Block.text(" Delete ", palette.error)
        sections.append(
            pad(
                join_responsive(
                    save_btn,
                    cancel_btn,
                    delete_btn,
                    available_width=panel_width - 2,
                    gap=2,
                ),
                left=2,
            )
        )
        sections.append(Block.empty(panel_width, 1))

        sections.append(Block.text("Selection:", palette.muted))
        items = ["Apple", "Banana", "Cherry"]
        item_width = min(panel_width - 6, 20)
        for i, item in enumerate(items):
            if i == 1:
                prefix = Block.text("▸ ", palette.accent.merge(Style(bold=True)))
                item_block = Block.text(item.ljust(item_width), Style())
            else:
                prefix = Block.text("  ", Style())
                item_block = Block.text(item, Style())
            sections.append(pad(join_horizontal(prefix, item_block), left=2))
        sections.append(Block.empty(panel_width, 1))

        sections.append(Block.text("Palette:", palette.muted))
        palette_blocks = [
            Block.text(" success ", palette.success),
            Block.text(" warning ", palette.warning),
            Block.text(" error ", palette.error),
            Block.text(" accent ", palette.accent),
            Block.text(" muted ", palette.muted),
        ]
        sections.append(
            pad(
                join_responsive(
                    *palette_blocks,
                    available_width=panel_width - 2,
                    gap=1,
                ),
                left=2,
            )
        )
        sections.append(Block.empty(panel_width, 1))

        sections.append(Block.text("Palettes:", palette.accent.merge(Style(bold=True))))
        lines = []
        for i, (pname, _) in enumerate(self.palettes):
            prefix = "▸" if i == self.palette_index else " "
            style = palette.accent.merge(Style(bold=True)) if i == self.palette_index else Style()
            lines.append(Block.text(f"{prefix} {i + 1}. {pname}", style))
        sections.append(pad(join_vertical(*lines), left=2))

        return join_vertical(*sections)

    def render(self) -> None:
        palette = current_palette()
        w, h = self._buf.width, self._buf.height

        self._buf.fill(0, 0, w, h, " ", Style())

        title = "  Palette Carnival  "
        self._buf.fill(0, 0, w, 1, " ", Style())
        self._buf.put_text(2, 0, title, palette.accent.merge(Style(bold=True)))

        keys_hint = "[1-3] switch  [←/→] cycle  [↑/↓] scroll  [q] quit"
        hint_x = max(len(title) + 4, w - len(keys_hint) - 2)
        self._buf.put_text(hint_x, 0, keys_hint, palette.muted)

        self._buf.fill(0, h - 1, w, 1, " ", Style())
        footer = f"Palette {self.palette_index + 1}/{len(self.palettes)}"
        self._buf.put_text(2, h - 1, footer, palette.muted)

        content_start_y = 2
        content_height = h - 3
        panel_x = 4
        panel_width = max(20, w - 8)

        content = self._build_content(palette, panel_width, w)
        self.viewport = self.viewport.with_visible(content_height).with_content(content.height)
        visible_content = vslice(content, self.viewport.offset, content_height)
        visible_content.paint(self._buf, panel_x, content_start_y)

        if self.viewport.can_scroll:
            scroll_pct = (
                int(100 * self.viewport.offset / max(1, self.viewport.max_offset))
                if self.viewport.max_offset > 0
                else 0
            )
            if self.viewport.is_at_top:
                indicator = "↓ more"
            elif self.viewport.is_at_bottom:
                indicator = "↑ more"
            else:
                indicator = f"↑↓ {scroll_pct}%"
            self._buf.put_text(w - len(indicator) - 2, h - 1, indicator, palette.muted)

    def on_key(self, key: str) -> None:
        if key == "q":
            self.quit()
        elif key in "123":
            idx = int(key) - 1
            if idx < len(self.palettes):
                self.palette_index = idx
                use_palette(self.palettes[idx][1])
        elif key == "right":
            self.palette_index = (self.palette_index + 1) % len(self.palettes)
            use_palette(self.palettes[self.palette_index][1])
        elif key == "left":
            self.palette_index = (self.palette_index - 1) % len(self.palettes)
            use_palette(self.palettes[self.palette_index][1])
        elif key == "up":
            self.viewport = self.viewport.scroll(-1)
        elif key == "down":
            self.viewport = self.viewport.scroll(1)
        elif key == "page_up":
            self.viewport = self.viewport.page_up()
        elif key == "page_down":
            self.viewport = self.viewport.page_down()
        elif key == "home":
            self.viewport = self.viewport.home()
        elif key == "end":
            self.viewport = self.viewport.end()

    def on_mouse(self, event: MouseEvent) -> None:
        if event.is_scroll:
            self.viewport = self.viewport.scroll(event.scroll_delta)


if __name__ == "__main__":
    asyncio.run(PaletteCarnival().run())

