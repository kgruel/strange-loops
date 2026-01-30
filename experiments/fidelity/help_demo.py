"""Help text at different fidelity levels.

Demonstrates Concept 1: same HelpData rendered at 4 levels:
- Level 0 (-q): One line — name: brief
- Level 1 (default): Standard --help output
- Level 2 (-v): Styled sections with borders
- Level 3 (-vv): Interactive TUI with section navigation

Run:
    uv run python experiments/fidelity/help_demo.py       # Level 1
    uv run python experiments/fidelity/help_demo.py -q    # Level 0
    uv run python experiments/fidelity/help_demo.py -v    # Level 2
    uv run python experiments/fidelity/help_demo.py -vv   # Level 3
"""

from __future__ import annotations

import asyncio
import sys
from dataclasses import dataclass

from cells import (
    Block,
    Style,
    border,
    join_vertical,
    join_horizontal,
    pad,
    ROUNDED,
    print_block,
)
from cells.tui import Surface
from cells.widgets import ListState, list_view

from .common import Fidelity, parse_fidelity, is_interactive, terminal_width


@dataclass(frozen=True)
class OptionHelp:
    """A single command-line option."""

    flags: str  # e.g., "-v, --verbose"
    description: str
    default: str | None = None


@dataclass(frozen=True)
class Example:
    """A usage example."""

    command: str
    description: str


@dataclass(frozen=True)
class HelpData:
    """Complete help content for a command."""

    name: str
    brief: str
    usage: str
    options: list[OptionHelp]
    examples: list[Example]
    notes: str | None = None


# Sample data for demonstration
SAMPLE_HELP = HelpData(
    name="deploy",
    brief="Deploy services to target environments",
    usage="deploy [options] <service>",
    options=[
        OptionHelp("-e, --env", "Target environment", "staging"),
        OptionHelp("-r, --replicas", "Number of replicas", "1"),
        OptionHelp("-t, --timeout", "Deployment timeout in seconds", "300"),
        OptionHelp("-d, --dry-run", "Show what would happen without executing"),
        OptionHelp("-f, --force", "Force deployment even if checks fail"),
        OptionHelp("-q, --quiet", "Minimal output"),
        OptionHelp("-v, --verbose", "Increase fidelity (-v, -vv)"),
    ],
    examples=[
        Example("deploy api", "Deploy api service to default environment"),
        Example("deploy -e prod api", "Deploy api to production"),
        Example("deploy -r 3 --dry-run api", "Preview 3-replica deployment"),
    ],
    notes="Environment can also be set via DEPLOY_ENV. "
    "Use 'deploy list' to see available services.",
)


def render_minimal(data: HelpData, width: int) -> Block:
    """Level 0: One line — name: brief."""
    text = f"{data.name}: {data.brief}"
    if len(text) > width:
        text = text[: width - 1] + "…"
    return Block.text(text, Style())


def render_standard(data: HelpData, width: int) -> Block:
    """Level 1: Standard --help output."""
    lines: list[str] = []

    lines.append(f"{data.brief}")
    lines.append("")
    lines.append(f"Usage: {data.usage}")
    lines.append("")
    lines.append("Options:")

    # Calculate column width for alignment
    max_flags = max(len(opt.flags) for opt in data.options)
    col_width = min(max_flags + 2, 24)

    for opt in data.options:
        flags = opt.flags.ljust(col_width)
        desc = opt.description
        if opt.default:
            desc += f" (default: {opt.default})"
        lines.append(f"  {flags}{desc}")

    if data.examples:
        lines.append("")
        lines.append("Examples:")
        for ex in data.examples:
            lines.append(f"  {ex.command}")
            lines.append(f"      {ex.description}")

    if data.notes:
        lines.append("")
        lines.append(data.notes)

    return Block.text("\n".join(lines), Style(), width=width)


def render_styled(data: HelpData, width: int) -> Block:
    """Level 2: Styled sections with borders."""
    sections: list[Block] = []

    # Title
    title_style = Style(bold=True, fg="cyan")
    title = Block.text(f"  {data.name}  ", title_style)

    # Usage section
    usage_content = Block.text(data.usage, Style(fg="green"))
    usage_box = border(usage_content, title="Usage", chars=ROUNDED)
    sections.append(usage_box)

    # Options section
    option_lines: list[Block] = []
    flag_style = Style(bold=True, fg="yellow")
    desc_style = Style()
    default_style = Style(dim=True)

    for opt in data.options:
        flag_block = Block.text(opt.flags.ljust(18), flag_style)
        desc_text = opt.description
        if opt.default:
            desc_text += f" [{opt.default}]"
        desc_block = Block.text(desc_text, desc_style if not opt.default else default_style)
        row = join_horizontal(flag_block, desc_block)
        option_lines.append(row)

    options_content = join_vertical(*option_lines)
    options_box = border(options_content, title="Options", chars=ROUNDED)
    sections.append(options_box)

    # Examples section
    if data.examples:
        example_lines: list[Block] = []
        cmd_style = Style(fg="green")
        ex_desc_style = Style(dim=True)

        for ex in data.examples:
            cmd = Block.text(f"$ {ex.command}", cmd_style)
            desc = Block.text(f"  {ex.description}", ex_desc_style)
            example_lines.append(cmd)
            example_lines.append(desc)

        examples_content = join_vertical(*example_lines)
        examples_box = border(examples_content, title="Examples", chars=ROUNDED)
        sections.append(examples_box)

    # Notes section
    if data.notes:
        notes_content = Block.text(data.notes, Style(italic=True))
        notes_box = border(notes_content, title="Notes", chars=ROUNDED)
        sections.append(notes_box)

    return join_vertical(*sections, gap=1)


class HelpSurface(Surface):
    """Level 3: Interactive TUI for help navigation."""

    SECTIONS = ["Usage", "Options", "Examples", "Notes"]

    def __init__(self, data: HelpData):
        super().__init__()
        self._data = data
        self._list_state = ListState(
            selected=0,
            scroll_offset=0,
            item_count=len(self.SECTIONS),
        )
        self._width = 80
        self._height = 24

    def layout(self, width: int, height: int) -> None:
        self._width = width
        self._height = height

    def render(self) -> None:
        if self._buf is None:
            return

        self._buf.fill(0, 0, self._width, self._height, " ", Style())

        # Title bar
        title_style = Style(bold=True, fg="cyan", reverse=True)
        title_text = f" {self._data.name} - Help "
        title_text = title_text.center(self._width)
        title_block = Block.text(title_text, title_style)
        title_block.paint(self._buf, 0, 0)

        # Split: section list on left, content on right
        list_width = 20
        content_width = self._width - list_width - 3  # gap

        # Section list
        section_items = [
            (s, Style(fg="white" if i == self._list_state.selected else "default"))
            for i, s in enumerate(self.SECTIONS)
        ]
        list_block = self._render_section_list(list_width)
        list_box = border(list_block, title="Sections", chars=ROUNDED)
        list_box.paint(self._buf, 0, 2)

        # Content area
        content_block = self._render_selected_section(content_width)
        content_box = border(
            content_block,
            title=self.SECTIONS[self._list_state.selected],
            chars=ROUNDED,
        )
        content_box.paint(self._buf, list_width + 3, 2)

        # Footer
        footer_style = Style(dim=True)
        footer_text = " j/k: navigate  q: quit "
        footer_block = Block.text(footer_text, footer_style)
        footer_block.paint(self._buf, 0, self._height - 1)

    def _render_section_list(self, width: int) -> Block:
        """Render the section navigation list."""
        lines: list[Block] = []
        for i, section in enumerate(self.SECTIONS):
            if i == self._list_state.selected:
                style = Style(bold=True, fg="cyan", reverse=True)
                prefix = "▸ "
            else:
                style = Style()
                prefix = "  "
            text = f"{prefix}{section}".ljust(width - 2)
            lines.append(Block.text(text, style))
        return join_vertical(*lines)

    def _render_selected_section(self, width: int) -> Block:
        """Render the currently selected section's content."""
        section = self.SECTIONS[self._list_state.selected]

        if section == "Usage":
            return Block.text(self._data.usage, Style(fg="green"), width=width)

        if section == "Options":
            lines: list[Block] = []
            for opt in self._data.options:
                flag_style = Style(bold=True, fg="yellow")
                flag = Block.text(opt.flags.ljust(18), flag_style)
                desc = opt.description
                if opt.default:
                    desc += f" [{opt.default}]"
                desc_block = Block.text(desc, Style())
                lines.append(join_horizontal(flag, desc_block))
            return join_vertical(*lines)

        if section == "Examples":
            if not self._data.examples:
                return Block.text("No examples available.", Style(dim=True))
            lines: list[Block] = []
            for ex in self._data.examples:
                cmd = Block.text(f"$ {ex.command}", Style(fg="green"))
                desc = Block.text(f"  {ex.description}", Style(dim=True))
                lines.append(cmd)
                lines.append(desc)
            return join_vertical(*lines)

        if section == "Notes":
            if not self._data.notes:
                return Block.text("No additional notes.", Style(dim=True))
            return Block.text(self._data.notes, Style(italic=True), width=width)

        return Block.empty(width, 1)

    def on_key(self, key: str) -> None:
        if key == "q":
            self.quit()
        elif key in ("j", "down"):
            self._list_state = self._list_state.move_down()
            self.mark_dirty()
        elif key in ("k", "up"):
            self._list_state = self._list_state.move_up()
            self.mark_dirty()


def run_interactive(data: HelpData) -> None:
    """Level 3: Launch the interactive help TUI."""
    surface = HelpSurface(data)
    asyncio.run(surface.run())


def main(args: list[str] | None = None) -> int:
    """Entry point for help demo."""
    if args is None:
        args = sys.argv[1:]

    fidelity = parse_fidelity(args)
    width = terminal_width()

    if fidelity == Fidelity.MINIMAL:
        block = render_minimal(SAMPLE_HELP, width)
        print_block(block)
    elif fidelity == Fidelity.STANDARD:
        block = render_standard(SAMPLE_HELP, width)
        print_block(block)
    elif fidelity == Fidelity.STYLED:
        block = render_styled(SAMPLE_HELP, width)
        print_block(block)
    else:  # INTERACTIVE
        if is_interactive():
            run_interactive(SAMPLE_HELP)
        else:
            # Fall back to styled if not a TTY
            block = render_styled(SAMPLE_HELP, width)
            print_block(block)

    return 0


if __name__ == "__main__":
    sys.exit(main())
