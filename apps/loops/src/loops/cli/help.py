"""Top-level help rendering for the loops CLI."""
from __future__ import annotations

import sys


def _render_main_help(argv: list[str]) -> int:
    """Render two-group help: vertex operations + root commands."""
    import shutil
    from painted.cli import (
        Format,
        HelpData,
        HelpFlag,
        HelpGroup,
        Zoom,
        render_help,
        scan_help_args,
    )
    from painted.core.writer import print_block

    zoom, fmt = scan_help_args(argv)

    verbs_group = HelpGroup(
        name="Verbs",
        hint="loops <verb> [vertex] [args]",
        detail="Implicit read: loops project = loops read project",
        flags=(
            HelpFlag(None, "read", "Read vertex state", detail="[vertex] [kind/key] [--diff] [--refs [N]] [--facts] [--ticks] [--kind K] [--key PREFIX]"),
            HelpFlag(None, "emit", "Inject a fact", detail="[vertex] <kind> [KEY=VALUE ...] [--dry-run]"),
            HelpFlag(None, "sync", "Run sources (cadence-gated)", detail="[vertex] [--force] [--var KEY=VALUE]"),
            HelpFlag(None, "close", "Resolve and capture artifacts", detail="[vertex] <kind> <name> [message] [--dry-run]"),
            HelpFlag(None, "cite", "Attention signal — inform current work with prior refs", detail="[vertex] <ref1> <ref2> ... [--context NAME] [-m MSG]"),
        ),
    )

    commands_group = HelpGroup(
        name="Commands",
        flags=(
            HelpFlag(None, "test", "Test a .loop file", detail="<file> [--input FILE] [--limit N]"),
            HelpFlag(None, "compile", "Show compiled structure", detail="<file>"),
            HelpFlag(None, "validate", "Validate syntax and flow", detail="[files...]"),
            HelpFlag(None, "store", "Inspect store contents", detail="[file]"),
            HelpFlag(None, "init", "Initialize vertex", detail="[name] [--template NAME]"),
            HelpFlag(None, "ls", "List vertices"),
            HelpFlag(None, "whoami", "Show resolved observer identity"),
        ),
    )

    zoom_group = HelpGroup(
        name="Zoom",
        hint="(what to show)",
        detail="Controls how much detail is rendered.",
        flags=(
            HelpFlag("-q", "--quiet", "Minimal output"),
            HelpFlag("-v", "--verbose", "Detailed (-v) or full (-vv)"),
        ),
        min_zoom=Zoom.SUMMARY,
    )

    format_group = HelpGroup(
        name="Format",
        hint="(serialization)",
        flags=(
            HelpFlag(None, "--json", "JSON output"),
            HelpFlag(None, "--plain", "Plain text, no ANSI codes"),
        ),
        min_zoom=Zoom.SUMMARY,
    )

    help_group = HelpGroup(
        name="Help",
        flags=(HelpFlag("-h", "--help", "Show this help", detail="Add -v for more detail."),),
        min_zoom=Zoom.SUMMARY,
    )

    help_data = HelpData(
        prog="loops",
        description="Runtime for .loop and .vertex files",
        groups=(verbs_group, commands_group, zoom_group, format_group, help_group),
    )

    if fmt == Format.JSON:
        import json
        from dataclasses import asdict
        print(json.dumps(asdict(help_data), default=str))
        return 0

    use_ansi = fmt != Format.PLAIN
    if fmt == Format.AUTO:
        use_ansi = hasattr(sys.stdout, "isatty") and sys.stdout.isatty()

    width = shutil.get_terminal_size().columns
    block = render_help(help_data, zoom, width, use_ansi)
    print_block(block, use_ansi=use_ansi)
    return 0
