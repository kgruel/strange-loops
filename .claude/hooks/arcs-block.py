#!/usr/bin/env python3
"""Render the ARCS-IN-FLIGHT context block for session_start.

Selects the top-N open/partial threads by recency and renders each as a
cumulative `sl trace --diff` — showing what changed across the thread's
lifecycle rather than re-rendering current state. This composes with
session_landing's TOUCHED block (which carries current state) by adding
the trajectory: where each arc has been, what transitioned at each
emit.

Env in:
- REPO_ROOT: monorepo root (where .loops/project.vertex lives)
- LOOPS_BIN: path to the `loops` binary

Writes a ready-to-inject markdown section to stdout. Silent on failure
— additionalContext is best-effort; never block session start.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

# Tunables — kept at the top so they're easy to tweak without re-reading
# the body. The two numbers describe orthogonal budgets: TOP_N caps how
# many arcs surface; MAX_LINES_PER_ARC caps each arc's render size.
TOP_N = 2
MAX_LINES_PER_ARC = 30


def main() -> int:
    repo_root = Path(os.environ.get("REPO_ROOT") or Path.cwd())
    project_vertex = repo_root / ".loops" / "project.vertex"
    if not project_vertex.exists():
        return 0

    # Defer the import — only paid if vertex resolved.
    # retain_facts=True so we can filter to threads with multi-fact lifecycles
    # — single-fact threads have nothing diff-worthy (everything is first-emit),
    # so prefer threads that have actually evolved across emits.
    from loops.commands.fetch import fetch_fold

    state = fetch_fold(project_vertex, kind="thread", retain_facts=True)
    threads: list[tuple[float, str, int]] = []
    for section in state.sections:
        kf = section.key_field
        if not kf:
            continue
        for item in section.items:
            status = item.payload.get("status", "")
            if status not in ("open", "partial"):
                continue
            name = item.payload.get(kf, "?")
            ts = item.ts or 0.0
            fact_count = len(state.source_facts.get(f"{section.kind}/{name}", []))
            threads.append((ts, name, fact_count))

    # Prefer multi-fact threads — they have actual lifecycle to render. Fall
    # back to all threads (sorted by recency) if none are multi-fact yet.
    multi_fact = [t for t in threads if t[2] >= 2]
    candidates = multi_fact if multi_fact else threads
    candidates.sort(key=lambda t: t[0], reverse=True)
    top = candidates[:TOP_N]
    if not top:
        return 0

    loops_bin = os.environ.get("LOOPS_BIN") or str(repo_root / ".venv" / "bin" / "loops")

    out_lines: list[str] = ["## ARCS", ""]
    for _, name, _ in top:
        result = subprocess.run(
            [loops_bin, "trace", "project", f"thread/{name}",
             "--diff", "--plain"],
            capture_output=True, text=True, timeout=10,
        )
        trace_out = result.stdout.strip()
        if not trace_out:
            continue
        lines = trace_out.splitlines()
        if len(lines) > MAX_LINES_PER_ARC:
            elided = len(lines) - MAX_LINES_PER_ARC
            lines = lines[:MAX_LINES_PER_ARC] + [
                f"  ... ({elided} more — sl trace project thread/{name} --diff)"
            ]
        out_lines.extend(lines)
        out_lines.append("")

    # If every trace came back empty, suppress the section entirely
    # (no header without body).
    if out_lines == ["## ARCS", ""]:
        return 0

    sys.stdout.write("\n".join(out_lines))
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        # Best-effort — never block session start on hook failures.
        sys.exit(0)
