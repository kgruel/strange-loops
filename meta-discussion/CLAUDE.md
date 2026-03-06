# Meta-Discussion

Cross-cutting design space — patterns, principles, and ways of working that
survive outside any specific project. Not loops-specific architecture (that
lives in project.vertex). Ideas emerge here from work across projects and
observers, then flow to implementation repos as ticks when ready.

## Session Bootstrap

Launch with observer identity set:

```bash
LOOPS_OBSERVER=meta-claude claude
```

Hooks in `.claude/settings.json` (monorepo root) handle everything:
- **SessionStart** — session marker + project fold + identity fold + comms
- **UserPromptSubmit** — comms delta (silent when empty)
- **SessionEnd** — session close marker

Identity, project state, and peer messages inject automatically via hooks.
`LOOPS_OBSERVER` scopes all reads and tags all emits.

## Store

Facts live in `meta.vertex` → `data/meta.db`.

### CLI syntax

```bash
uv run loops meta emit <kind> key=value "trailing message"
uv run loops meta fold                    # current fold state
uv run loops meta stream --kind <kind>    # event history
uv run loops meta fold --kind decision    # filter to one kind
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

Alcove shares `#alcove-chat` on Discord. The discord source at
`~/.config/loops/discord/` posts and polls. Messages are stored as facts
in `discord.db`. Use the source script directly:

```bash
uv run --with requests python3 ~/.config/loops/discord/discord-source poll
uv run --with requests python3 ~/.config/loops/discord/discord-source send "message"
```

## Source Projects

| Project | Path | Character |
|---------|------|-----------|
| loops | `~/Code/loops` | Language/runtime monorepo — 4 libs, 3 apps |
| siftd | `~/Code/siftd` | CLI tool — conversation indexing, adapter plugins |
| painted | `~/Code/painted` | TUI framework — frozen dataclasses, golden tests |
| gruel.network | `~/Code/gruel.network` | Infrastructure/homelab — shell dispatchers, CI/CD |
| strange-loops | `~/Code/strange-loops` | Task orchestration — loops-as-orchestration |
