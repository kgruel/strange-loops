# CLI v2 parity ledger

Status: investigation result, 2026-08-13 (three-sweep survey: CLI surface,
in-repo consumers, external consumers)
Governs: successor-condition 3 (`design:architecture/cli-v2-successor-conditions`)
— "entire monorepo under the CLI" measured here, cutover per-row, old CLI
dies at ledger completion.

## How to read this

Rows are **workflows, not flags**. A row is done when the workflow runs on
v2 — which may mean v2 grew the capability, or the consumer was rewritten
against v2's JSON envelopes, or the workflow was retired. Preserving old
syntax is never the goal; preserving the workflow is.

Each row carries a **risk class** describing what the consumer actually
depends on:

| Class | Depends on | Cutover shape |
|---|---|---|
| RT | rendered text (grep'd layout, sentinel strings) | consumer MUST move to JSON envelope — never re-promise text shape |
| RJ | current `--json` shape | envelope covers it or consumer migrates to v1 envelope |
| RX | exit codes / error surface | v2 exit contract (thread:cli-error-surface-unification) supersedes |
| RS | invocation syntax (verbs, flags, k=v, env) | consumer edits at cutover; scriptable |
| RR | remote/provisioned (systemd, SSH, uv tool install) | needs deploy step, not just an edit |
| RL | library API, not CLI | not a v2 row — affected by libs-handoff instead |
| RD | prose/docs teaching syntax | rewritten at cutover; goes stale silently, so LAST and audited |

## The denominator: current surface (frozen at ratchet)

17 top-level names. Verbs (observer-peel): `read emit close sync cite seal
store`. Commands: `test compile validate orient init whoami ls add rm
export` + painted-injected `completion`. Plus tier-3 vertex-shorthand
dispatch (`sl <vertex> …` → implicit read / verb rewrite / population ops).
`store` carries nine subcommands (`verify rebirth reanchor export absorb
adopt ticks stats reindex`). 17 lenses + user-global lens resolution.
Registry note: only read-fold and emit use the Operation IR; close/sync and
most commands are legacy views — the strata Kyle named, confirmed.

Known-vestigial at freeze (do NOT port): `main.py` shim, add/rm bare-
positional row form, `ls <v> kind` positional form, fetch embedded
`kind/key` split, export argv param, tier-3 pre-router (dissolution already
threaded: `thread:dispatch-default-subsumes-vertex-pre-router`).

## Section 1 — in-session practice (the plugin: fires every session, any cwd)

| # | Workflow | Consumer | Syntax relied on | Risk | Cutover note |
|---|---|---|---|---|---|
| 1.1 | session open emit | `clients/claude-code/hooks/session-open.sh` | `sl emit <path> session name= status= --observer -q` (vertex as PATH) | RS | k=v → `--data`; path-target must stay legal |
| 1.2 | session close emit + seal | `session-close.sh` | emit + `sl seal <path> -m --observer -q` | RS | v2 needs a seal verb or hook calls libs |
| 1.3 | session orientation | `session-orient.sh` | `sl orient`; fallback greps `--plain` fold text: `': open ·'`, `HH:MM [kind]` lines, 180-char cuts; `--help` exit as feature probe | **RT (worst row)** | rewrite hook against JSON envelope; the middot-grep contract must die, not be honored |
| 1.4 | turn capture (reroute log) | `turn-capture.py` → instructs model | `sl emit project log message="…"` (vertex as NAME) | RS | name-target must stay legal alongside path-target |
| 1.5 | sweep ceremony | `/loops:sweep` | read `--facts --kind log --since 1d --plain`; emit friction/thread/observation; seal | RS | |
| 1.6 | reconcile ceremony | `/loops:reconcile` | `--lens reconcile` (user-global lens), `--kind X --plain`, `--facts` | RS+RT | lens is rendering-phase; interim = JSON + hook-side render or stay on frozen CLI |
| 1.7 | syntax teaching | `skills/loops/SKILL.md` (~28 forms) + STALE duplicate at `.claude/skills/loops/` | full emit/read/cite/seal/init/add-observer grammar | RD | rewrite at cutover; delete the stale duplicate NOW (pre-existing bug) |
| 1.8 | release ceremony smoke | `skills/release/SKILL.md` | `--version`, `read -q`, `ls <unknown>` exit/error assertions, PyPI-installed smoke | RX | re-point at v2 exit contract |
| 1.9 | arcs context block | `.claude/hooks/arcs-block.py` (orphaned, unwired) | library `fetch_fold` + `read <v> thread/<name> --diff --plain` | RL+RT | decide: rewire against envelope or retire |

## Section 2 — automation (scheduled/scripted, breaks silently)

| # | Workflow | Consumer | Contract | Risk | Cutover note |
|---|---|---|---|---|---|
| 2.1 | projects scan (1h loop) | `~/.config/loops/projects/bin/scan.py` | `sl read project --json` per repo; **parses `{"rows":[{kind,ts,key,payload:{status,name}}]}`**; exit-1-on-zero-projects channel | RJ+RX | first consumer to migrate to the v1 envelope — it's the envelope's design client |
| 2.2 | homelab monitor (10m systemd, remote) | `loops-monitor.service` on 192.168.1.30 + ansible provisioning | `loops sync <abs path>`, `LOOPS_OBSERVER`, `loops add … observer --keygen` at provision, uv-tool-install from git | RR | needs ansible change + redeploy; ALSO the monitor smoke-tests `loops --version` (row 2.5) |
| 2.3 | gruel session hook | `gruel.network/.claude/hooks/session-start.sh` | reads 3 vertices `--plain --kind --limit`; sentinel `"No data yet."` string-compare; non-zero-exit → warning; SSH read of monitor vertex | RT+RX+RR | prior breakage history (0.5.0); rewrite against envelope |
| 2.4 | agent launcher | `~/.config/loops/bin/launch` | `read identity --observer X --plain` → verbatim system prompt; `emit session …` | RT | output IS the deliverable — needs a plain-text-render guarantee or hook-side render |
| 2.5 | tool-health self-test | monitor `tool-registry.tsv` | `loops --version` exit 0 = healthy | RX | a rebuild flipping this fires a real alert — feature, not bug; time the cutover |
| 2.6 | task orchestration absorb | `~/Code/loops-tasks/src/ticked/init.py` | `loops store absorb tasks`, returncode + text-as-message | RS+RX | |
| 2.7 | homelab audit publish | `gruel.network/.loops/audit/publish_homelab_audit.py` | `store verify` returncode = verdict; stdout embedded in HTML | RX | |

## Section 3 — manual store driving (the long tail)

~20 external stores found (gruel.network×7, siftd×2 **JSONL-canonical**,
painted, tasked×2, loops-tasks×2, agent-attestation, backtesting×2, meta×2,
config-level roster incl. identity/comms/session/projects) plus loops-docs'
untracked `.loops/`. No scripts — but every one implies interactive CLI use
in that repo's sessions, in current syntax, by an agent whose CLAUDE.md/
MEMORY teach current idioms.

Risk: RS+RD diffuse. Cutover: these follow wherever the plugin + docs go;
the siftd JSONL stores are the natural early v2 dogfood targets (v2's JSONL
handling is the part the old CLI is weakest at).

Library-API consumers, explicitly NOT rows here (libs-handoff concerns):
`apps/tasks`, `apps/hlab`, `backtesting/src/ledger.py` (imports engine,
re-implements boundary dispatch), `generate-changelog.py` + `mentions-block`
(raw sqlite), `publish_homelab_audit.py`'s sqlite half.

## Section 4 — rendering-bound (deferred by design, listed so they're not forgotten)

| # | Workflow | Consumer | Note |
|---|---|---|---|
| 4.1 | user-global lenses | `~/.config/loops/lenses/` ×7 (reconcile, session_landing, …) + agent-auth/backtesting/loops-docs lens dirs | bound to `(data, zoom, width) → Block` — rendering-phase contract |
| 4.2 | store TUI | `store <file> -i` | rendering phase |
| 4.3 | zoom ladder | `-q/-v/-vv` everywhere | rendering phase; v2 interim = envelope only |
| 4.4 | painted's own tests | `test_completion_shell.py` asserts on literal `sl read --kind` strings | the inversion: the rendering lib pins the CLI's syntax — update with cutover |

## Section 5 — docs/prose (last, then audited)

`docs/CLI-CHEATSHEET.md` (90 forms — the terminus), `UPGRADING.md` (71),
root CLAUDE.md (27), `apps/loops/CLAUDE.md` (21), lib CLAUDE.mds (~20),
`~/.config/loops/CLAUDE.md`, MEMORY.md + 8 topic files, impl-pipeline
skill, meta-discussion docs, and **rendered next-step strings inside
lenses** (session_landing, comms `ack` hint, backtest library output) —
prose that TEACHES commands to future sessions. These rewrite at each
row's cutover and get a final grep-audit sweep (`sl |loops `) at ledger
completion.

## Pre-existing breakage found by the survey (fix independent of v2)

- `~/.config/loops/comms/discord/discord.loop` sources a **nonexistent**
  `discord-source` path — dead source.
- `~/.config/loops/CLAUDE.md` documents a `pickup.zsh` that doesn't exist.
- `.claude/skills/loops/SKILL.md` is a stale divergent duplicate of the
  plugin skill.
- `arcs-block.py` unwired in settings.
- `store_args.py` declares only subcommand names → store subcommand flags
  invisible to `-h`/completion (known, test-pinned).

## Cutover sequencing (follows from the rows)

1. **Envelope first** (condition 4): design the v1 result envelope against
   rows 2.1 (JSON parser), 1.3 (worst text parser), 2.4 (verbatim-output
   consumer) — the three hardest consumer shapes. If the envelope serves
   those three, it serves the rest.
2. **Automation rows before practice rows**: scheduled consumers break
   silently; session hooks break loudly with a human watching.
3. **Remote row (2.2) last of the automation set** — needs ansible +
   redeploy + the 2.5 health-check timing.
4. **Docs sweep at the end**, then the completion audit: repo-wide +
   config-wide grep for old-syntax invocations, zero hits outside
   CHANGELOG/UPGRADING history.
5. `apps/loops` deletion = ledger complete.
