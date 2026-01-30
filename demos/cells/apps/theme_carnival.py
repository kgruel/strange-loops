#!/usr/bin/env python3
"""Theme Carnival — interactive theme explorer with live switching.

A fun demo showcasing runtime theme switching. See how the same UI
looks with different color palettes, all changing instantly.

Run: uv run python demos/cells/apps/theme_carnival.py
Keys: 1-6 jump to theme, ←/→ cycle, q quit
"""

import asyncio
from cells import Style, Block, Line, Span, border, pad, join_vertical, join_horizontal
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

        # Clear background
        self._buf.fill(0, 0, w, h, " ", Style(bg=theme.bg_base))

        # Title bar
        title = f"  Theme Carnival  "
        self._buf.fill(0, 0, w, 1, " ", theme.header_base)
        self._buf.put_text(2, 0, title, Style(fg=theme.primary, bold=True, bg=theme.bg_subtle))

        keys_hint = "[1-6] switch  [←/→] cycle  [q] quit"
        self._buf.put_text(w - len(keys_hint) - 2, 0, keys_hint, Style(fg=theme.muted, bg=theme.bg_subtle))

        # Main content area
        content_y = 3

        # Current theme display
        theme_label = f"Current: {theme.name.upper()}"
        self._buf.put_text(4, content_y, theme_label, Style(fg=theme.accent, bold=True))
        content_y += 2

        # Preview panel
        panel_x = 4
        panel_width = min(50, w - 8)

        # Status indicators row
        self._buf.put_text(panel_x, content_y, "Status:", Style(fg=theme.text, dim=True))
        content_y += 1

        # Connected indicator
        self._buf.put_text(panel_x + 2, content_y, "●", theme.header_connected)
        self._buf.put_text(panel_x + 4, content_y, "Connected", Style(fg=theme.text))

        # Error indicator
        self._buf.put_text(panel_x + 16, content_y, "✕", theme.header_error)
        self._buf.put_text(panel_x + 18, content_y, "Error", Style(fg=theme.text))

        # Warning indicator
        self._buf.put_text(panel_x + 28, content_y, "⚡", theme.header_spinner)
        self._buf.put_text(panel_x + 30, content_y, "Warning", Style(fg=theme.text))

        # Spinner
        spin_block = spinner(self.spinner_state, style=Style(fg=theme.warning))
        spin_block.paint(self._buf, panel_x + 42, content_y)

        content_y += 2

        # Log levels
        self._buf.put_text(panel_x, content_y, "Log Levels:", Style(fg=theme.text, dim=True))
        content_y += 1

        levels = [
            ("ERROR", "error", "something went wrong"),
            ("WARN ", "warn", "a warning appeared"),
            ("INFO ", "info", "normal operation"),
            ("DEBUG", "debug", "verbose output"),
        ]

        for label, level, msg in levels:
            level_style = theme.level_style(level)
            self._buf.put_text(panel_x + 2, content_y, label, level_style)
            self._buf.put_text(panel_x + 8, content_y, msg, Style(fg=theme.text))
            content_y += 1

        content_y += 1

        # Progress bar
        self._buf.put_text(panel_x, content_y, "Progress:", Style(fg=theme.text, dim=True))
        content_y += 1

        pbar = progress_bar(
            ProgressState(value=self.progress_value),
            width=panel_width - 8,
            filled_style=Style(fg=theme.success),
            empty_style=Style(dim=True),
        )
        pbar.paint(self._buf, panel_x + 2, content_y)
        pct = int(self.progress_value * 100)
        self._buf.put_text(panel_x + panel_width - 4, content_y, f"{pct:3d}%", Style(fg=theme.text))
        content_y += 2

        # Buttons
        self._buf.put_text(panel_x, content_y, "Actions:", Style(fg=theme.text, dim=True))
        content_y += 1

        # Button styles
        btn_style = Style(fg=theme.text, bg=theme.bg_emphasis)
        btn_accent = Style(fg=theme.primary, bg=theme.bg_emphasis, bold=True)
        btn_danger = Style(fg=theme.error, bg=theme.bg_emphasis)

        self._buf.put_text(panel_x + 2, content_y, " Save ", btn_accent)
        self._buf.put_text(panel_x + 10, content_y, " Cancel ", btn_style)
        self._buf.put_text(panel_x + 20, content_y, " Delete ", btn_danger)
        content_y += 2

        # Selection highlight demo
        self._buf.put_text(panel_x, content_y, "Selection:", Style(fg=theme.text, dim=True))
        content_y += 1

        items = ["Apple", "Banana", "Cherry"]
        for i, item in enumerate(items):
            if i == 1:  # Highlight middle item
                self._buf.put_text(panel_x + 2, content_y, "▸", theme.selection_cursor)
                self._buf.fill(panel_x + 4, content_y, panel_width - 6, 1, " ", theme.selection_highlight)
                self._buf.put_text(panel_x + 4, content_y, item, Style(fg=theme.text, bg=theme.bg_emphasis))
            else:
                self._buf.put_text(panel_x + 4, content_y, item, Style(fg=theme.text))
            content_y += 1

        content_y += 1

        # Palette preview
        self._buf.put_text(panel_x, content_y, "Palette:", Style(fg=theme.text, dim=True))
        content_y += 1

        palette_items = [
            ("primary", theme.primary),
            ("accent", theme.accent),
            ("success", theme.success),
            ("warning", theme.warning),
            ("error", theme.error),
        ]
        x_offset = panel_x + 2
        for name, color in palette_items:
            self._buf.put_text(x_offset, content_y, "██", Style(fg=color))
            x_offset += 3

        content_y += 2

        # Theme selector at bottom
        selector_y = h - 5
        self._buf.put_text(4, selector_y, "Themes:", Style(fg=theme.text, bold=True))
        selector_y += 1

        # Two columns of themes
        col1_x = 6
        col2_x = 24
        themes_col1 = self.theme_names[:3]
        themes_col2 = self.theme_names[3:6]

        for i, name in enumerate(themes_col1):
            num = i + 1
            is_current = name == theme.name
            prefix = "▸" if is_current else " "
            style = Style(fg=theme.accent, bold=True) if is_current else Style(fg=theme.text)
            self._buf.put_text(col1_x, selector_y + i, f"{prefix} {num}. {name.capitalize()}", style)

        for i, name in enumerate(themes_col2):
            num = i + 4
            is_current = name == theme.name
            prefix = "▸" if is_current else " "
            style = Style(fg=theme.accent, bold=True) if is_current else Style(fg=theme.text)
            self._buf.put_text(col2_x, selector_y + i, f"{prefix} {num}. {name.capitalize()}", style)

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
