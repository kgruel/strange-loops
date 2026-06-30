#!/usr/bin/env python3
"""Stop hook: the reroute-capture backstop (thread:reroute-capture-practice).

Fires when the agent finishes a turn. Asks once — did anything get routed
around that should hit the log? — then lets the continuation stop freely
(stop_hook_active guards the loop). The capture channel is the zero-ceremony
`log` kind; promotion to friction happens at sweep/reconcile, not here.

Skips trivial turns (nothing to capture after a one-tool answer) by only
firing when the transcript shows real work: a crude tool-call count over
the current turn keeps the nudge out of conversational back-and-forth.

No-ops outside a loops-dogfooding repo (the plugin installs at user scope, so
this Stop hook is live in every repo — only nudge where a project vertex exists).
"""

import glob
import json
import os
import sys

try:
    data = json.load(sys.stdin)
except Exception:
    sys.exit(0)  # empty/malformed stdin → never block (matches the file's posture)

# Continuation after our own block — let it stop.
if data.get("stop_hook_active"):
    sys.exit(0)

# Only operate in repos that dogfood loops — mirror the CLI's _find_local_vertex
# (.loops/.vertex, .loops/project.vertex, or any .loops/*.vertex).
proj = os.environ.get("CLAUDE_PROJECT_DIR", os.getcwd())
loops_dir = os.path.join(proj, ".loops")
if not (
    os.path.exists(os.path.join(loops_dir, ".vertex"))
    or os.path.exists(os.path.join(loops_dir, "project.vertex"))
    or glob.glob(os.path.join(loops_dir, "*.vertex"))
):
    sys.exit(0)

# Crude work-detection: count tool_use events in the last turn of the
# transcript. Conversational turns (< 3 tool calls) don't get nudged.
tool_calls = 0
try:
    transcript = data.get("transcript_path", "")
    with open(transcript) as f:
        lines = f.readlines()
    # Walk backwards to the last user (non-meta) message — that bounds the turn.
    for line in reversed(lines):
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            continue
        if entry.get("type") == "user" and not entry.get("isMeta"):
            break
        if entry.get("type") == "assistant":
            content = entry.get("message", {}).get("content", [])
            if isinstance(content, list):
                tool_calls += sum(1 for c in content if c.get("type") == "tool_use")
except Exception:
    sys.exit(0)  # unreadable transcript → never block

if tool_calls < 3:
    sys.exit(0)

print(json.dumps({
    "decision": "block",
    "reason": (
        "Turn-capture backstop (one line each or 'none', then stop): "
        "did this turn include (a) a reroute — anything you worked around "
        "instead of stopping for (tool fought you, verb missing, syntax "
        "retried, hand-edit where machinery exists); (b) an in-moment "
        "friction or surprise not yet emitted? "
        "Capture reroutes via: sl emit project log message=\"...\" "
        "(zero ceremony — promotion happens at sweep, not now)."
    ),
}))
