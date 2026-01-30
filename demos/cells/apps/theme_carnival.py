#!/usr/bin/env python3
"""Theme Carnival — interactive theme explorer with live switching.

A fun demo showcasing runtime theme switching. See how the same UI
looks with different color palettes, all changing instantly.

Run: uv run python demos/cells/apps/theme_carnival.py
Keys: 1-6 jump to theme, ←/→ cycle, q quit
"""

import asyncio
from cells import Style, Block, Line, Span, border, pad, join_vertical, join_horizontal, join_responsive
from cells.tui import Surface
from cells.themes import (
    Theme,
    current_theme,
    use_theme,
    list_themes,
    get_theme,
)
from cells.widgets import SpinnerState, spinner, ProgressState, progress_bar


class ThemeCarnival(Surface):
    """Interactive theme explorer with live preview."""

    def __init__(self):
        super().__init__()
        self.theme_names = list_themes()
        self.theme_index = 0
        self.spinner_state = SpinnerState()
        self.progress_value = 0.0
        self.progress_direction = 1
        self.frame = 0

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

    def render(self) -> None:
        theme = current_theme()
        w, h = self._buf.width, self._buf.height
        bg = theme.bg_base  # Main background for all content

        # Clear background
        self._buf.fill(0, 0, w, h, " ", Style(bg=bg))

        # Title bar
        title = f"  Theme Carnival  "
        self._buf.fill(0, 0, w, 1, " ", theme.header_base)
        self._buf.put_text(2, 0, title, Style(fg=theme.primary, bold=True, bg=theme.bg_subtle))

        keys_hint = "[1-6] switch  [←/→] cycle  [q] quit"
        hint_x = max(len(title) + 4, w - len(keys_hint) - 2)
        self._buf.put_text(hint_x, 0, keys_hint, Style(fg=theme.muted, bg=theme.bg_subtle))

        # Main content area
        content_y = 3
        panel_x = 4
        panel_width = max(20, w - 8)

        # Current theme display
        theme_label = f"Current: {theme.name.upper()}"
        self._buf.put_text(panel_x, content_y, theme_label, Style(fg=theme.accent, bold=True, bg=bg))
        content_y += 2

        # Status indicators row — using join_responsive
        self._buf.put_text(panel_x, content_y, "Status:", Style(fg=theme.text, dim=True, bg=bg))
        content_y += 1

        # Build status indicator blocks
        connected_block = Block.text("● Connected", Style(fg=theme.success, bg=bg))
        error_block = Block.text("✕ Error", Style(fg=theme.error, bg=bg))
        warning_block = Block.text("⚡ Warning", Style(fg=theme.warning, bg=bg))
        spin_block = spinner(self.spinner_state, style=Style(fg=theme.warning, bg=bg))

        status_row = join_responsive(
            connected_block, error_block, warning_block, spin_block,
            available_width=panel_width - 2,
            gap=2
        )
        status_row.paint(self._buf, panel_x + 2, content_y)
        content_y += status_row.height + 1

        # Log levels
        self._buf.put_text(panel_x, content_y, "Log Levels:", Style(fg=theme.text, dim=True, bg=bg))
        content_y += 1

        levels = [
            ("ERROR", "error", "something went wrong"),
            ("WARN ", "warn", "a warning appeared"),
            ("INFO ", "info", "normal operation"),
            ("DEBUG", "debug", "verbose output"),
        ]

        for label, level, msg in levels:
            level_style = theme.level_style(level)
            # Merge background into level style
            self._buf.put_text(panel_x + 2, content_y, label, Style(fg=level_style.fg, bold=level_style.bold, dim=level_style.dim, bg=bg))
            self._buf.put_text(panel_x + 8, content_y, msg, Style(fg=theme.text, bg=bg))
            content_y += 1

        content_y += 1

        # Progress bar
        self._buf.put_text(panel_x, content_y, "Progress:", Style(fg=theme.text, dim=True, bg=bg))
        content_y += 1

        pbar_width = max(10, panel_width - 12)
        pbar = progress_bar(
            ProgressState(value=self.progress_value),
            width=pbar_width,
            filled_style=Style(fg=theme.success, bg=bg),
            empty_style=Style(dim=True, bg=bg),
        )
        pbar.paint(self._buf, panel_x + 2, content_y)
        pct = int(self.progress_value * 100)
        self._buf.put_text(panel_x + 4 + pbar_width, content_y, f"{pct:3d}%", Style(fg=theme.text, bg=bg))
        content_y += 2

        # Buttons — using join_responsive
        self._buf.put_text(panel_x, content_y, "Actions:", Style(fg=theme.text, dim=True, bg=bg))
        content_y += 1

        # Button styles
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
        buttons_row.paint(self._buf, panel_x + 2, content_y)
        content_y += buttons_row.height + 1

        # Selection highlight demo
        self._buf.put_text(panel_x, content_y, "Selection:", Style(fg=theme.text, dim=True, bg=bg))
        content_y += 1

        items = ["Apple", "Banana", "Cherry"]
        item_width = min(panel_width - 6, 20)
        for i, item in enumerate(items):
            if i == 1:  # Highlight middle item
                self._buf.put_text(panel_x + 2, content_y, "▸", Style(fg=theme.accent, bold=True, bg=bg))
                self._buf.fill(panel_x + 4, content_y, item_width, 1, " ", theme.selection_highlight)
                self._buf.put_text(panel_x + 4, content_y, item, Style(fg=theme.text, bg=theme.bg_emphasis))
            else:
                self._buf.put_text(panel_x + 4, content_y, item, Style(fg=theme.text, bg=bg))
            content_y += 1

        content_y += 1

        # Palette preview — using join_responsive
        self._buf.put_text(panel_x, content_y, "Palette:", Style(fg=theme.text, dim=True, bg=bg))
        content_y += 1

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
        palette_row.paint(self._buf, panel_x + 2, content_y)
        content_y += palette_row.height + 1

        # Theme selector at bottom — using join_responsive
        selector_y = max(content_y + 1, h - 5)
        self._buf.put_text(4, selector_y, "Themes:", Style(fg=theme.text, bold=True, bg=bg))
        selector_y += 1

        # Build theme columns as blocks
        def theme_column(names: list[str], start_num: int) -> Block:
            lines = []
            for i, name in enumerate(names):
                num = start_num + i
                is_current = name == theme.name
                prefix = "▸" if is_current else " "
                style = Style(fg=theme.accent, bold=True, bg=bg) if is_current else Style(fg=theme.text, bg=bg)
                lines.append(Block.text(f"{prefix} {num}. {name.capitalize()}", style))
            return join_vertical(*lines) if lines else Block.empty(0, 0)

        col1 = theme_column(self.theme_names[:3], 1)
        col2 = theme_column(self.theme_names[3:6], 4)

        theme_cols = join_responsive(
            col1, col2,
            available_width=w - 12,
            gap=4
        )
        theme_cols.paint(self._buf, 6, selector_y)

        # Footer
        self._buf.fill(0, h - 1, w, 1, " ", theme.header_base)
        footer = f"Theme {self.theme_index + 1}/{len(self.theme_names)}"
        self._buf.put_text(2, h - 1, footer, theme.footer_dim.merge(Style(bg=theme.bg_subtle)))

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


if __name__ == "__main__":
    asyncio.run(ThemeCarnival().run())
