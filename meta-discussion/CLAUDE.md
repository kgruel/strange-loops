# Meta-Discussion

Cross-cutting design space — patterns, principles, and ways of working that
survive outside any specific project. Not loops-specific architecture (that
lives in project.vertex). Ideas emerge here from work across projects and
observers, then flow to implementation repos as ticks when ready.

## Session Bootstrap

Launch via the config script (resolves identity → `--system-prompt`):

```bash
~/.config/loops/bin/launch meta-claude ~/Code/loops/meta-discussion
```

Or manually (hooks still fire, but no `--system-prompt` identity):

```bash
cd ~/Code/loops/meta-discussion && LOOPS_OBSERVER=meta-claude claude
```

Hooks in `.claude/settings.json` (monorepo root) handle the rest:
- **SessionStart** — side effects (session marker, discord sync, check-in) + JSON `additionalContext` injection (project fold + identity + comms)
- **UserPromptSubmit** — comms delta (silent when empty)
- **SessionEnd** — mechanical delta log + session close marker

`LOOPS_OBSERVER` scopes all reads and tags all emits.

### Bootstrap self-check

On first response, verify three things loaded:

1. **Identity** — system prompt should contain "meta-claude. I hold the cross-cutting thread..." (via launch `--system-prompt` or hook `additionalContext`)
2. **Project fold** — decisions, threads, tasks, sessions visible in context (via hook `additionalContext`). Look for `## DECISION`, `## THREAD`, `## TASK` blocks.
3. **Comms** — discord status line if peers are online (via hook `additionalContext`)

If any are missing, run manually to diagnose:
```bash
uv run loops read project --lens prompt --plain   # project fold
uv run loops read identity --plain                 # identity
uv run loops read comms --observer all --lens comms --plain -q  # comms
```

## Store

Facts live in `meta.vertex` → `data/meta.db`.

### CLI syntax

```bash
uv run loops meta emit <kind> key=value "trailing message"
uv run loops meta read                    # current fold state
uv run loops meta read --facts --kind <kind>    # event history
uv run loops meta read --kind decision    # filter to one kind
```

`meta` resolves via combine at `~/.config/loops/meta/meta.vertex` → this
project's `meta.vertex`. Works from anywhere in the monorepo.

### Fact Kinds

| Kind | Fold | Purpose |
|------|------|---------|
| `decision` | by topic | Cross-cutting resolved positions |
| `thread` | by name | Open investigations |
| `dissolution` | by concept | Things that collapsed into existing primitives |
| `handoff` | collect 1 | Session continuity — the cold-start narrative |

### Topic Namespacing

Decisions use namespaced topics:

- `testing/*` — test philosophy (factories, tiers, gate ordering)
- `workflow/*` — dev harness, experiment lifecycle, session continuity
- `design/*` — dissolution, fidelity, attention, lenses as concepts

Loops-specific decisions (`architecture/*`, `identity/*`, `implementation/*`)
belong in project.vertex, not here.

## Peer Communication

**Native (agent-to-agent, same machine)** — primary channel for loops-claude ↔ meta-claude:
```bash
uv run loops emit comms/native message body="message text"
```

**Discord (alcove, external)** — alcove shares `#alcove-chat`, polls on ~60s interval:
```bash
uv run --with requests python3 ~/.config/loops/discord/discord-source send "message text"
uv run --with requests python3 ~/.config/loops/discord/discord-source poll
```

All messages (native and discord) are visible via `uv run loops read comms`.

## Source Projects

| Project | Path | Character |
|---------|------|-----------|
| loops | `~/Code/loops` | Language/runtime monorepo — 4 libs, 3 apps |
| siftd | `~/Code/siftd` | CLI tool — conversation indexing, adapter plugins |
| painted | `~/Code/painted` | TUI framework — frozen dataclasses, golden tests |
| gruel.network | `~/Code/gruel.network` | Infrastructure/homelab — shell dispatchers, CI/CD |
| strange-loops | `~/Code/strange-loops` | Task orchestration — loops-as-orchestration |
