#!/usr/bin/env python3
"""Generate docs/CLI.md from the argparse definitions in cli.py.

Usage:
    uv run --package strange-loops python scripts/gen_cli_docs.py
"""

from __future__ import annotations

import argparse
from pathlib import Path

from strange_loops.cli import create_parser

DOCS_DIR = Path(__file__).resolve().parent.parent / "docs"


def _format_action(action: argparse.Action) -> str | None:
    """Format a single argparse action as a markdown table row."""
    if isinstance(action, argparse._SubParsersAction):
        return None
    if isinstance(action, argparse._HelpAction):
        return None

    flags = ", ".join(f"`{o}`" for o in action.option_strings) if action.option_strings else None
    name = flags or f"`{action.dest}`"

    help_text = action.help or ""
    default = action.default
    if default is not None and default != argparse.SUPPRESS and default != "":
        help_text += f" (default: `{default}`)"

    required = ""
    if not action.option_strings and action.nargs not in ("?", "*"):
        required = "required"
    elif getattr(action, "required", False):
        required = "required"

    return f"| {name} | {help_text} | {required} |"


def _format_parser(parser: argparse.ArgumentParser, heading_level: int = 2) -> list[str]:
    """Format a parser (and its subparsers) as markdown sections."""
    lines: list[str] = []

    # Collect positional and optional actions (skip subparsers and help)
    positionals = []
    optionals = []
    subparsers_action = None

    for action in parser._actions:
        if isinstance(action, argparse._SubParsersAction):
            subparsers_action = action
        elif isinstance(action, argparse._HelpAction):
            continue
        elif action.option_strings:
            optionals.append(action)
        else:
            positionals.append(action)

    # Arguments table
    all_actions = positionals + optionals
    if all_actions:
        lines.append("| Argument | Description | Required |")
        lines.append("|----------|-------------|----------|")
        for action in all_actions:
            row = _format_action(action)
            if row:
                lines.append(row)
        lines.append("")

    # Recurse into subcommands
    if subparsers_action:
        for name, subparser in sorted(subparsers_action.choices.items()):
            prefix = "#" * (heading_level + 1)
            help_text = ""
            # Find help text from the subparser's description or the action's help map
            for sub_action in subparsers_action._choices_actions:
                if sub_action.dest == name:
                    help_text = sub_action.help or ""
                    break

            lines.append(f"{prefix} `{name}`")
            lines.append("")
            if help_text:
                lines.append(help_text)
                lines.append("")
            lines.extend(_format_parser(subparser, heading_level + 1))

    return lines


def generate() -> str:
    """Generate the full CLI.md content."""
    parser = create_parser()
    lines = [
        "# CLI Reference",
        "",
        "Auto-generated from argparse definitions in `src/strange_loops/cli.py`.",
        "",
        "```",
        f"Usage: {parser.prog} <command> [options]",
        "```",
        "",
        parser.description or "",
        "",
    ]

    # Top-level commands overview
    for action in parser._actions:
        if isinstance(action, argparse._SubParsersAction):
            lines.append("## Commands")
            lines.append("")
            for name, subparser in sorted(action.choices.items()):
                # Find help text
                help_text = ""
                for sub_action in action._choices_actions:
                    if sub_action.dest == name:
                        help_text = sub_action.help or ""
                        break
                lines.append(f"- [`{name}`](#{name}) — {help_text}")
            lines.append("")
            lines.append("---")
            lines.append("")

            # Detailed sections
            for name, subparser in sorted(action.choices.items()):
                help_text = ""
                for sub_action in action._choices_actions:
                    if sub_action.dest == name:
                        help_text = sub_action.help or ""
                        break

                lines.append(f"## `{name}`")
                lines.append("")
                if help_text:
                    lines.append(help_text)
                    lines.append("")
                lines.extend(_format_parser(subparser, heading_level=2))

    return "\n".join(lines)


def main() -> None:
    content = generate()
    out_path = DOCS_DIR / "CLI.md"
    out_path.write_text(content)
    print(f"Generated {out_path}")


if __name__ == "__main__":
    main()
