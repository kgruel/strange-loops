#!/bin/bash
# Shared resolution for the loops plugin hooks. SOURCED by the hook scripts, not run.
#
# Resolves the three machine/repo-specific inputs in ONE place:
#   SL  — the loops CLI: PATH first, then the uv-tool install location. (The
#         pre-plugin hooks hardcoded an absolute path to dodge a thin hook PATH;
#         this keeps that robustness without bolting to one machine.)
#   V   — this repo's WRITABLE project vertex, resolved the way the CLI's own
#         _find_local_vertex does: .loops/.vertex, then .loops/project.vertex,
#         then the first .loops/*.vertex. CLAUDE_PROJECT_DIR is the hook contract
#         for "where the session opened"; fall back to PWD for hand-runs. (Emit
#         dispatch is cwd-aware, but a hook must not RELY on its cwd.)
#   OBS — the observer/agent identity. The launcher sets LOOPS_OBSERVER per agent;
#         the kyle/loops-claude default is intentional for PERSONAL use — export
#         LOOPS_OBSERVER to attribute sessions to a different identity.
SL="$(command -v sl 2>/dev/null || echo "${HOME}/.local/bin/sl")"
OBS="${LOOPS_OBSERVER:-kyle/loops-claude}"

_root="${CLAUDE_PROJECT_DIR:-$PWD}"
if [ -f "$_root/.loops/.vertex" ]; then
  V="$_root/.loops/.vertex"
elif [ -f "$_root/.loops/project.vertex" ]; then
  V="$_root/.loops/project.vertex"
else
  V="$(ls "$_root"/.loops/*.vertex 2>/dev/null | head -1)"
fi
