"""Guardrail: prevent regressions to len() for display width.

In display-critical modules, string display width must use wcwidth/wcswidth
semantics (see fidelis._text_width).
"""

from __future__ import annotations

import ast
import re
from pathlib import Path


TARGET_MODULES = [
    Path("src/fidelis/block.py"),
    Path("src/fidelis/compose.py"),
    Path("src/fidelis/_lens.py"),
    Path("src/fidelis/components/text_input.py"),
    Path("src/fidelis/components/data_explorer.py"),
]

# Heuristic: arguments containing these tokens are likely string/text.
_SUSPICIOUS_ARG_RE = re.compile(
    r"(\.text\b|\btext\b|\btitle\b|\bcontent\b|\bword\b|\bkeys\b|\bkey\b|\bprefix\b|\bplaceholder\b|\bsummary\b|\bleaf\b|\bch\b)"
)

# Allowlist of len() calls that are intentionally about indices or collection sizes.
# Keys are (path, lineno, source_snippet).
ALLOWLIST = {
    ("src/fidelis/components/text_input.py", 23, "len(ch)"),
    ("src/fidelis/components/text_input.py", 34, "len(self.text)"),
    ("src/fidelis/components/text_input.py", 47, "len(self.text)"),
    ("src/fidelis/components/text_input.py", 57, "len(self.text)"),
    ("src/fidelis/components/text_input.py", 61, "len(text)"),
    ("src/fidelis/components/text_input.py", 69, "len(text)"),
    ("src/fidelis/components/text_input.py", 70, "len(text)"),
    ("src/fidelis/components/text_input.py", 83, "len(text)"),
}


def test_no_new_len_on_text_variables_in_display_modules():
    violations: list[tuple[str, int, str]] = []

    for path in TARGET_MODULES:
        src = path.read_text(encoding="utf-8")
        tree = ast.parse(src, filename=str(path))

        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            if not isinstance(node.func, ast.Name) or node.func.id != "len":
                continue
            if len(node.args) != 1 or node.keywords:
                continue

            arg_src = ast.get_source_segment(src, node.args[0]) or ""
            if not _SUSPICIOUS_ARG_RE.search(arg_src):
                continue

            call_src = ast.get_source_segment(src, node) or "len(?)"
            key = (path.as_posix(), node.lineno, call_src)
            if key not in ALLOWLIST:
                violations.append((path.as_posix(), node.lineno, call_src))

    if violations:
        formatted = "\n".join(f"- {p}:{ln}: {src}" for p, ln, src in violations)
        allow = "\n".join(f"- {p}:{ln}: {src}" for p, ln, src in sorted(ALLOWLIST))
        raise AssertionError(
            "Unexpected len() on likely text variables in display-critical modules.\n\n"
            "Violations:\n"
            f"{formatted}\n\n"
            "If this len() is intentional (non-display), add it to ALLOWLIST.\n"
            "Current ALLOWLIST:\n"
            f"{allow}\n"
        )

