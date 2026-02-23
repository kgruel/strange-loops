#!/usr/bin/env python3
"""Theme Carnival — interactive theme explorer with live switching.

A fun demo showcasing runtime theme switching. See how the same UI
looks with different color palettes, all changing instantly.

Run: uv run python demos/apps/theme_carnival.py
Keys: 1-6 jump to theme, ←/→ cycle, ↑/↓ scroll, q quit
Mouse: scroll wheel to scroll
"""

import asyncio
from fidelis import Style, Block, pad, join_vertical, join_horizontal, join_responsive, Viewport, vslice
from fidelis.tui import Surface
from fidelis.themes import (
    Theme,
    current_theme,
    use_theme,
    list_themes,
)
from fidelis.widgets import SpinnerState, spinner, ProgressState, progress_bar
from fidelis._mouse import MouseEvent


class ThemeCarnival(Surface):
    """Interactive theme explorer with live preview."""

    def __init__(self):
        super().__init__(enable_mouse=True)
        self.theme_names = list_themes()
        self.theme_index = 0
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

    def _build_content(self, theme: "Theme", panel_width: int, full_width: int) -> Block:
        """Build the scrollable content area as a Block."""
        bg = theme.bg_base
        sections: list[Block] = []

        # Current theme display
        theme_label = f"Current: {theme.name.upper()}"
        sections.append(Block.text(theme_label, Style(fg=theme.accent, bold=True, bg=bg)))
        sections.append(Block.empty(panel_width, 1, Style(bg=bg)))  # blank line

        # Status section
        sections.append(Block.text("Status:", Style(fg=theme.text, dim=True, bg=bg)))
        connected_block = Block.text("● Connected", Style(fg=theme.success, bg=bg))
        error_block = Block.text("✕ Error", Style(fg=theme.error, bg=bg))
        warning_block = Block.text("⚡ Warning", Style(fg=theme.warning, bg=bg))
        spin_block = spinner(self.spinner_state, style=Style(fg=theme.warning, bg=bg))
        status_row = join_responsive(
            connected_block, error_block, warning_block, spin_block,
            available_width=panel_width - 2,
            gap=2
        )
        sections.append(pad(status_row, left=2))
        sections.append(Block.empty(panel_width, 1, Style(bg=bg)))

        # Log levels section
        sections.append(Block.text("Log Levels:", Style(fg=theme.text, dim=True, bg=bg)))
        levels = [
            ("ERROR", "error", "something went wrong"),
            ("WARN ", "warn", "a warning appeared"),
            ("INFO ", "info", "normal operation"),
            ("DEBUG", "debug", "verbose output"),
        ]
        for label, level, msg in levels:
            level_style = theme.level_style(level)
            label_block = Block.text(label, Style(fg=level_style.fg, bold=level_style.bold, dim=level_style.dim, bg=bg))
            msg_block = Block.text(" " + msg, Style(fg=theme.text, bg=bg))
            row = join_horizontal(label_block, msg_block)
            sections.append(pad(row, left=2))
        sections.append(Block.empty(panel_width, 1, Style(bg=bg)))

        # Progress bar section
        sections.append(Block.text("Progress:", Style(fg=theme.text, dim=True, bg=bg)))
        pbar_width = max(10, panel_width - 12)
        pbar = progress_bar(
            ProgressState(value=self.progress_value),
            width=pbar_width,
            filled_style=Style(fg=theme.success, bg=bg),
            empty_style=Style(dim=True, bg=bg),
        )
        pct = int(self.progress_value * 100)
        pct_block = Block.text(f" {pct:3d}%", Style(fg=theme.text, bg=bg))
        pbar_row = join_horizontal(pbar, pct_block)
        sections.append(pad(pbar_row, left=2))
        sections.append(Block.empty(panel_width, 1, Style(bg=bg)))

        # Buttons section
        sections.append(Block.text("Actions:", Style(fg=theme.text, dim=True, bg=bg)))
        btn_accent = Style(fg=theme.primary, bg=theme.bg_emphasis, bold=True)
        btn_style = Style(fg=theme.text, bg=theme.bg_emphasis)
        btn_danger = Style(fg=theme.error, bg=theme.bg_emphasis)
        save_btn = Block.text(" Save ", btn_accent)
        cancel_btn = Block.text(" Cancel ", btn_style)
        delete_btn = Block.text(" Delete ", btn_danger)
        buttons_row = join_responsive(
            save_btn, cancel_btn, delete_btn,
            available_width=panel_width - 2,
            gap=2
        )
        sections.append(pad(buttons_row, left=2))
        sections.append(Block.empty(panel_width, 1, Style(bg=bg)))

        # Selection section
        sections.append(Block.text("Selection:", Style(fg=theme.text, dim=True, bg=bg)))
        items = ["Apple", "Banana", "Cherry"]
        item_width = min(panel_width - 6, 20)
        for i, item in enumerate(items):
            if i == 1:  # Highlight middle item
                prefix = Block.text("▸ ", Style(fg=theme.accent, bold=True, bg=bg))
                # Pad item text to item_width
                item_text = item.ljust(item_width)
                item_block = Block.text(item_text, Style(fg=theme.text, bg=theme.bg_emphasis))
                row = join_horizontal(prefix, item_block)
            else:
                prefix = Block.text("  ", Style(bg=bg))
                item_block = Block.text(item, Style(fg=theme.text, bg=bg))
                row = join_horizontal(prefix, item_block)
            sections.append(pad(row, left=2))
        sections.append(Block.empty(panel_width, 1, Style(bg=bg)))

        # Palette section
        sections.append(Block.text("Palette:", Style(fg=theme.text, dim=True, bg=bg)))
        palette_blocks = [
            Block.text("██", Style(fg=theme.primary, bg=bg)),
            Block.text("██", Style(fg=theme.accent, bg=bg)),
            Block.text("██", Style(fg=theme.success, bg=bg)),
            Block.text("██", Style(fg=theme.warning, bg=bg)),
            Block.text("██", Style(fg=theme.error, bg=bg)),
        ]
        palette_row = join_responsive(
            *palette_blocks,
            available_width=panel_width - 2,
            gap=1
        )
        sections.append(pad(palette_row, left=2))
        sections.append(Block.empty(panel_width, 1, Style(bg=bg)))

        # Theme selector section
        sections.append(Block.text("Themes:", Style(fg=theme.text, bold=True, bg=bg)))

        def theme_column(names: list[str], start_num: int) -> Block:
            lines = []
            for i, name in enumerate(names):
                num = start_num + i
                is_current = name == theme.name
                prefix = "▸" if is_current else " "
                style = Style(fg=theme.accent, bold=True, bg=bg) if is_current else Style(fg=theme.text, bg=bg)
                lines.append(Block.text(f"{prefix} {num}. {name.capitalize()}", style))
            return join_vertical(*lines) if lines else Block.empty(0, 0, Style(bg=bg))

        col1 = theme_column(self.theme_names[:3], 1)
        col2 = theme_column(self.theme_names[3:6], 4)
        theme_cols = join_responsive(
            col1, col2,
            available_width=full_width - 12,
            gap=4
        )
        sections.append(pad(theme_cols, left=2))

        return join_vertical(*sections)

    def render(self) -> None:
        theme = current_theme()
        w, h = self._buf.width, self._buf.height
        bg = theme.bg_base

        # Clear background
        self._buf.fill(0, 0, w, h, " ", Style(bg=bg))

        # Title bar (fixed, row 0)
        title = f"  Theme Carnival  "
        self._buf.fill(0, 0, w, 1, " ", theme.header_base)
        self._buf.put_text(2, 0, title, Style(fg=theme.primary, bold=True, bg=theme.bg_subtle))

        keys_hint = "[1-6] switch  [←/→] cycle  [↑/↓] scroll  [q] quit"
        hint_x = max(len(title) + 4, w - len(keys_hint) - 2)
        self._buf.put_text(hint_x, 0, keys_hint, Style(fg=theme.muted, bg=theme.bg_subtle))

        # Footer (fixed, last row)
        self._buf.fill(0, h - 1, w, 1, " ", theme.header_base)
        footer = f"Theme {self.theme_index + 1}/{len(self.theme_names)}"
        self._buf.put_text(2, h - 1, footer, theme.footer_dim.merge(Style(bg=theme.bg_subtle)))

        # Content area dimensions
        content_start_y = 2  # After title bar + gap
        content_height = h - 3  # Between title bar and footer
        panel_x = 4
        panel_width = max(20, w - 8)

        # Build scrollable content
        content = self._build_content(theme, panel_width, w)

        # Update viewport dimensions
        self.viewport = self.viewport.with_visible(content_height).with_content(content.height)

        # Slice content for current scroll position
        visible_content = vslice(content, self.viewport.offset, content_height)

        # Paint content to buffer
        visible_content.paint(self._buf, panel_x, content_start_y)

        # Scroll indicator in footer
        if self.viewport.can_scroll:
            scroll_pct = int(100 * self.viewport.offset / max(1, self.viewport.max_offset)) if self.viewport.max_offset > 0 else 0
            if self.viewport.is_at_top:
                indicator = "↓ more"
            elif self.viewport.is_at_bottom:
                indicator = "↑ more"
            else:
                indicator = f"↑↓ {scroll_pct}%"
            self._buf.put_text(w - len(indicator) - 2, h - 1, indicator, Style(fg=theme.muted, bg=theme.bg_subtle))

    def on_key(self, key: str) -> None:
        if key == "q":
            self.quit()
        elif key in "123456":
            idx = int(key) - 1
            if idx < len(self.theme_names):
                self.theme_index = idx
                use_theme(self.theme_names[idx])
        elif key == "right":
            self.theme_index = (self.theme_index + 1) % len(self.theme_names)
            use_theme(self.theme_names[self.theme_index])
        elif key == "left":
            self.theme_index = (self.theme_index - 1) % len(self.theme_names)
            use_theme(self.theme_names[self.theme_index])
        # Scroll navigation
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
    asyncio.run(ThemeCarnival().run())
