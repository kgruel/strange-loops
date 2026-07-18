# Panel review — CONSTRAINT-COMPLIANCE lens on s3-codex-advisor.md

*2026-07-17. Claude-family skeptic pass, independent of the codex conclusions.
Every load-bearing claim below was re-derived against the checkout, the
installed painted 0.12.x wheel, and the live project store — not taken from
the document.*

Verdict: **AMEND**. The design honors four of the five ratified constraints
outright; the fifth ("one coordinated lens-signature migration") has a real
scope hole (apps/tasks), and two supporting claims need tightening (golden
coverage breadth, the piped= deletion). Nothing invalidates the approach.

---

## C1 — Surface = fidelity tier on ONE fetch; static Block byte-identical, golden-guarded

**Structurally compliant, verified.** All current `run_cli` fetch closures are
zero-arg and fidelity-independent (checked `commands/stream.py:40`,
`commands/store.py:101,1181,1295,1392` — none receive zoom/fidelity), so the
`LensSpec.project(snapshot, query)` / render-at-fidelity split matches how the
code already behaves: fidelity is a render tier, never a refetch. The host's
`set_fidelity` re-render keeps that in the shell.

**Amendment 1 — golden coverage is narrower than the S0 exit implies.** The
golden suite exists (`apps/loops/tests/golden/goldens/`, 12 fixture dirs, 4
zoom levels each: fold paths, fold surface paths, store, why, compile, log,
run, status, declarations, test, validate, grammar-parity). But **stream,
ticks, ls, sync, and population have no byte goldens** — they are guarded only
by register-parity tests (`test_parity_stream_ticks.py`, `test_parity.py`),
which assert cross-register content parity, not byte stability across a
refactor. The S0 exit criterion "all existing static goldens are
byte-identical" therefore passes **vacuously** for exactly the surfaces the
shared `render_row` consolidation touches hardest. Step 1's "freeze current
static golden output" must be made explicit: *add* byte goldens for every
run_cli surface lacking them **before** any lens body changes, so the gate is
load-bearing rather than trivially green.

**Amendment 2 — deleting `piped=` needs the ratchet, not just the deletion.**
The doc asserts "`width is None` already means the pipe register." That is the
ratified rule, and `cli/views/fold.py:612` does compute
`width = ... if ctx.isatty else None` so piped ⇔ width-is-None at that site.
But `lenses/stream.py:39-52` explicitly documents the opposite stance —
"``piped`` keys the presentation register on the channel (**not width**)" —
and honors `piped=True` independently of width. The project's own store
records why: a thread (post-codex-review, fix e8643a6) states *"The
piped=>width=None rule keeps shipping as caller discipline, not an invariant:
the codex review found store/stats callsites passing ctx.width with no
register split."* Deleting the explicit `piped=` kwarg removes the
belt-and-suspenders that has repeatedly caught this defect class. The
migration may collapse the axes **only if** it simultaneously lands the
enforced invariant the store thread asked for (a ratchet test that no caller
passes a non-None width on a non-TTY channel). Per the user's global ratchet
principle, an invariant that lives only in review vigilance drifts. The doc
should name this as part of S0, not leave it implied.

## C2 — store_app retires as redundant consumer

**Compliant, deletion inventory verified accurate.**

- `loops/tui/store_app.py` exists; quit collision is real:
  `store_app.py:131: if key in ("q", "Q", "escape"): self.quit()` — exactly
  the corpus conflict the doc resolves in favor of q-as-zoom-out.
- Independent fetch is real: `store_app.py:113-117` imports `make_fetcher` /
  `make_fidelity_fetcher` and fetches on its own.
- `make_fidelity_fetcher` (defined `commands/store.py:1448`) is consumed
  **only** by store_app and its tests (`test_store_command.py`,
  `test_tui.py:752`) — verified by grep; safe to delete with it.
- The `-i` entry is `commands/store.py:1420-1423` (instantiates
  `StoreExplorerApp`).
- The `AutoresearchApp` carve-out is explicit and does not violate the
  constraint — the ratified retirement targets store_app specifically, and the
  doc correctly refuses to delete AutoresearchApp "by implication."
- The one-release `store V -i` delegation + honest `.db -i` refusal keeps
  "no release with two interactive store browsers" true.

## C3 — prefer/grow painted over workaround

**Compliant; the doc does NOT invent painted APIs.**

- `run_app(default=)` is real and has exactly the claimed semantics. Installed
  wheel, `painted/cli/app_runner.py:130-131`: *"``default`` lifts the
  'primary-noun shorthand' into the framework: when argv[0] matches no command
  and is not a flag, it routes to the default"*; `:243-244` dispatches
  `self.default.handler(argv)` with the name kept. Signature confirmed:
  `run_app(argv, commands, *, prog=None, description=None, default=None,
  aliases=())`. The `known`-set fall-through in loops `cli/app.py:440-443`
  and its stale comment at `:250` ("run_app … does not model 'unknown arg0 ⇒
  default'") predate this painted feature — the doc's instruction to delete it
  is a correct dissolution, and completion is covered upstream
  (`painted/cli/complete.py:226,239-240` threads `default`).
- `Theme.roles` + `Vocabulary` verified present (`Theme` dataclass fields:
  `palette, icons, borders, roles`; `painted.vocabulary` exports `Vocabulary`,
  `CORE_ROLE_NAMES`, `Role`, `Token`) — the app-role route for the 10 loops
  chrome names is a supported mechanism, not a workaround.
- The renderer-host gap is real: `painted.tui` exports Surface/TestSurface/
  Region/Layer (+ `painted.viewport.Viewport`) but **no** adapter that mounts
  a `(data, fidelity, width) -> Block` renderer with `set_data`/`set_fidelity`.
  Commissioning it upstream (with the shell-specific `Block.paint(region)`
  mount as the only acceptable fallback residue) is the constraint-honoring
  shape.
- Pin verified: root `pyproject.toml:17` = `painted>=0.12.1,<0.13`; the doc
  correctly gates consumption on a released bump, not the sibling checkout.

## C4 — height stays Surface-tier

**Compliant.** The renderer contract stays `(data, fidelity, width)`
(`Fidelity` fields verified: `depth, visible, chars, lines` — so
`fidelity.visible/.chars/.lines` reads are real attributes, not invented).
Height appears only in the host/viewport and the commissioned renderer-host
contract. `CliContext` carries `height` but the design never threads it to a
lens. No violation found; I tried.

## C5 — ONE coordinated lens-signature migration

**The 17-count is verified correct — for apps/loops only.** Grep of executable
`run_cli(` sites in `apps/loops/src`: dispatch 1 (`cli/dispatch.py:409`),
sync 2, ticks 2, store 3, population 1, stream 1, ls 2, devtools 5 = **17**;
`dispatch.py:19` and `:358` are docstring prose, as the doc says. The
"historical 19" traced to commit `6dd3f31` (2026-07-13, "render= gone from
all 19 run_cli sites"), which touched **only apps/loops** — the count shrank
to 17 since (S7 ticks/stream consolidation). The doc's
"reconcile-at-implementation-time, gate on zero-old-signature not on a count"
posture is sound.

**Amendment 3 (the real finding) — apps/tasks is silently out of scope.**
`apps/tasks/src/strange_loops/` has **7 more executable run_cli sites**
(`cli.py:127,161,187,241,263,298`, `commands/dashboard.py:933`) that the doc's
inventory and prose never mention. They are on the **deprecated pre-0.11
contract**: `render=(ctx, data)` closures reading `ctx.zoom`
(`cli.py:124-130` verified), backed by painted's compat `CliContext.zoom`
property (verified: a property, not a field — fields are
`fidelity, mode, use_ansi, is_tty, width, height, args, ...`), and
Zoom-signature lenses (`lenses/project.py:13`, `task.py:12`, `session.py:12`).
Consequences either way the scope falls:

- If the exit gate "zero command render closures that convert Fidelity to
  Zoom and zero lens entrypoints with the old signature" is **repo-wide**, it
  fails on day one — 7 sites and 6 lens entrypoints in tasks.
- If it is **loops-scoped**, then painted must keep `Zoom`, `render=`, and
  `CliContext.zoom` compat alive indefinitely for one in-repo consumer, and a
  second signature migration is latent — precisely the "separate waves"
  outcome the ratified constraint forbids.

The doc must say which. Given tasks is ~7 sites of the same mechanical shape
(and 6dd3f31 shows a delegated worker did 19 sites cleanly), folding tasks
into the same coordinated branch is the cheap, constraint-honoring answer;
an explicit deferral with the painted-compat consequence named is the
acceptable minimum. Silence is not.

**Correction (minor, honesty-class) — "Current read interactive mode without
a handler errors" is false.** `cli/views/fold.py:259-263`: `-i` returns mode
`"interactive"` **only when** `lens == "autoresearch"`; every other lens
**silently downgrades to static**. The error path
(`cli/dispatch.py:236-240`) is unreachable from `read -i` today. The design
consequence (bind an interactive RUN handler) is unchanged, but the doc should
state the current behavior accurately — a silent `-i` no-op is exactly the
honesty defect class this wave is supposed to retire, and S2 should claim
"replaces a silent downgrade," not "replaces an error."

## Confirmed empirically (how)

1. 17 executable run_cli sites in apps/loops — grep, per-file count matches
   the doc's inventory exactly; the 2 prose matches are dispatch.py docstrings.
2. Historical 19 = commit 6dd3f31's loops-only render=→renderer migration
   (git show; commit message says "all 19 run_cli sites").
3. `run_app(default=)` semantics — read installed
   `painted/cli/app_runner.py:130-141,243-244`; signature via inspect.
4. `Fidelity` fields `depth/visible/chars/lines` — dataclass fields probed at
   runtime; `Fidelity().visible` returns a frozenset.
5. Goldens: 12 fixture dirs × 4 zoom levels under
   `apps/loops/tests/golden/goldens/`; stream/ticks/ls/sync/population absent.
6. store_app quit keys (`store_app.py:131`), independent fetch (`:113-117`),
   `make_fidelity_fetcher` sole consumer — grep.
7. `Theme.roles`/`Vocabulary` and the absence of a painted renderer-host
   adapter — runtime dir() of installed wheel.
8. Fetch closures are zero-arg (fidelity-independent) — grep of `def fetch`
   sites in stream.py/store.py.
9. piped-vs-width: `stream.py:39-52` channel-keyed register;
   `fold.py:612-613` width-from-isatty; store thread on "caller discipline,
   not an invariant" — sqlite3 query against `.loops/data/project.db`.
10. `read -i` silent static downgrade — `fold.py:259-263` +
    `dispatch.py:235-241`.

## Amendments required

1. **tasks-app migration scope** (C5): name apps/tasks' 7 run_cli sites and 6
   Zoom lenses — in the coordinated branch, or explicitly deferred with the
   painted-compat (Zoom/render=/ctx.zoom must survive) consequence stated.
2. **Golden coverage before migration** (C1): S0 step 1 must add byte goldens
   for stream/ticks/ls/sync/population; "all existing goldens byte-identical"
   is vacuous for surfaces with none.
3. **piped⇒width=None as enforced ratchet** (C1): pair the `piped=` kwarg
   deletion with an enumerable invariant test (non-TTY channel ⇒ width None at
   every render callsite); the store's own history shows caller discipline
   alone regresses.
4. **Correct the `read -i` claim** (accuracy): silent downgrade to static, not
   an error; S2 language should reflect it.
