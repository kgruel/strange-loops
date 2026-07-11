# loops — Claude Code plugin

Packages the **in-session** loops integration as a Claude Code plugin, portable
across **the author's own repos and machines** (personal scope — see *Identity*).

| Surface | What it does |
|---------|--------------|
| `SessionStart` hooks | Mark the session open in this repo's `project` vertex, then print the orient block (last seal, open threads/frictions, what moved, which lenses to run). |
| `SessionEnd` hook | Mark the session closed and `seal` (boundary → tick). |
| `Stop` hook | The reroute-capture backstop — nudges once per working turn to log reroutes/frictions before stopping. |
| Skill | The `loops` practice doc, auto-invoked when you mention loops, vertices, folds, observers, signing, reconcile, or the store. |
| Skill (`release`) | The strange-loops release ceremony — CHANGELOG sweep, version stamp, wheel pre-flight, tag, GitHub release → PyPI trusted publishing, deploy verification. Scoped to this monorepo; no-ops as a trigger elsewhere. |
| `/loops:sweep` | Session-wrap: triage this session's reroutes, promote frictions, update threads, emit the session-arc. |
| `/loops:reconcile` | The slower structural review: staleness lens, friction backlog, stale threads, hypothesis staleness. |

## Portability

The hooks resolve their three machine/repo-specific inputs in **`hooks/lib.sh`**:

- `SL` — the loops CLI (PATH first, then the uv-tool install location). If `sl`
  is found neither way, the hooks print one stderr line and no-op rather than
  silently dropping the session.
- `V` — the writable project vertex, resolved like the CLI's own
  `_find_local_vertex`: `.loops/.vertex` → `.loops/project.vertex` →
  first `.loops/*.vertex`, under `${CLAUDE_PROJECT_DIR}`.
- `OBS` — `${LOOPS_OBSERVER:-kyle/loops-claude}`.

Every hook entry point guards on the vertex existing, so the plugin **no-ops
cleanly** in repos that don't dogfood loops (it installs at user scope, i.e.
active everywhere).

### Identity (personal scope)

The default observer is `kyle/loops-claude` — **intentional for personal use**,
not a generic default. The launcher sets `LOOPS_OBSERVER` per agent; for any
non-author install, **export `LOOPS_OBSERVER`** to attribute sessions correctly.
Genericizing the observer (and a first-run key-mint) is deferred until there's a
real second installer.

**Out of scope** (deliberately): the session **lenses** (`session_start`,
`reconcile`, …) are loops' own runtime-resolved layer (`lens_resolver.py`,
already in `~/.config/loops/lenses/`), not bundled here — `/loops:reconcile`
degrades gracefully when the `reconcile` lens is absent. The **launcher**
(pre-session identity → `--system-prompt`) is pre-session and outside the plugin
model, which runs in-session.

## Install (local)

Requires the `loops`/`sl` CLI on PATH (`uv tool install . -e` from the repo root).

```bash
/plugin marketplace add /Users/kaygee/Code/loops/clients/claude-code
/plugin install loops@gruel
```

Or, for dev iteration without a marketplace:

```bash
claude --plugin-dir /Users/kaygee/Code/loops/clients/claude-code
```

> Distribution is **local-path only** for now. The catalog (`marketplace.json`)
> lives in this subdir, not the repo root, so the GitHub-shorthand
> `/plugin marketplace add owner/repo` form won't find it — that's a deferred
> public-distribution concern.

## Cutover (REQUIRED on first adoption)

Plugin hooks **merge with** your existing user hooks — they don't replace them.
The pre-plugin wiring in `~/Code/loops/.claude/settings.local.json` registers the
**same** `SessionStart` / `SessionEnd` / `Stop` events. If you enable the plugin
while that wiring is still live, every session **double-fires**: two
`session status=open` emits, the orient block printed twice, two `sl seal` per
close (the second seals a drained window → a degenerate tick), and a double
turn-capture nudge.

When you adopt the plugin, in the same change:

1. Delete the entire `"hooks"` block from `~/Code/loops/.claude/settings.local.json`
   (keep `permissions`).
2. Sweep the now-vestigial helpers it pointed at:
   `~/Code/loops/.claude/hooks/session-orient.sh` and `turn-capture.py`
   (confirm `arcs-block.py` isn't wired elsewhere first — it's dormant).
3. Retire the old skill home (the plugin is now canonical): remove the global
   symlink `~/.config/claude/skills/loops` and the gitignored source
   `~/Code/loops/.claude/skills/loops/`.

This is the dissolution sweep: the plugin *is* the new home for this wiring;
leaving the old wiring in place is un-swept residue.
