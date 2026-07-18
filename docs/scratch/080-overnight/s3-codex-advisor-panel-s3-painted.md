# PAINTED-REALITY lens review — s3-codex-advisor.md (0.8.0 TUI synthesis)

*2026-07-17. Claude-family skeptic pass. Everything below was verified against
the painted repo working tree (`/Users/kaygee/Code/painted`, now at
`v0.12.1-10-gf81b25a`), the installed pin
(`/Users/kaygee/Code/loops/.venv/.../painted-0.12.1`), and the loops source —
not against the dossier's claims. Verdict: **AMEND** — the architecture holds,
but §4's renderer-host commission is stale against painted main and two of its
contract statements now contradict what upstream ratified and shipped.*

---

## 0. The load-bearing discovery: the dossier's snapshot is stale by two slices

The dossier (§0) recorded painted main at **8 commits ahead of v0.12.1**
(S1 HeightRenderer + S2 evidence/frame-assembly, `git describe` →
`v0.12.1-8-g5f400de`). Painted main is now at **`v0.12.1-10-gf81b25a`** —
host-rung **S3 and S4 have landed** since the dossier was written:

```
f81b25a host-rung S4: interactive dispatch + input routing — HostSurface (tui),
        both arms mounted from run_cli INTERACTIVE ... universal -i ...
5a147f9 host-rung S3: viewport adapter — ViewportAdapter at painted.host
        (frozen state, pure transitions) ... ticket-based publish,
        Frame+FrameToken inseparable hit-testing ...
```

Concretely, on painted main today:

- `src/painted/host.py` — `ViewportAdapter` (host.py:328), a **frozen,
  delivery-agnostic value**: `plan(RenderKey)` (369), `publish(content, plan,
  frame_height)` (390), `resize` (468), `scroll/page_up/home/end/scroll_to/
  scroll_into_view` (506–535), `frame()` (548), `resolve(x, y, token)` (575).
  Its docstring pins the ownership rule: *"It never invokes a renderer (it
  \*receives\* Blocks), never consults TTY state, never writes to a terminal,
  and imports nothing from cli or tui"* (host.py:13–15), and *"this object is
  built so S4 can drive it without modification, exercised here entirely
  through constructed Blocks"* (host.py:17–19).
- `src/painted/tui/surface.py:494` — `class HostSurface(Surface)`: *"a
  semantic renderer's Block delivered interactively"*. Constructor
  (surface.py:540–552): `render: (width, height) -> Block` closure,
  `accepts_height`, `content_id`, `inputs`, `evidence_label`,
  **`quit_keys=("q", "escape")`**, `fps_cap`, `on_emit`, `no_color`. Two arms
  (omitted → host `ViewportAdapter`; offered → renderer returns exactly-H,
  `ContractError` otherwise, surface.py:637–648).
- None of this is installable: the workspace and tool venvs both carry
  `painted-0.12.1.dist-info`, the installed package has **no `host.py`** and
  no `HostSurface` in `tui/surface.py` (checked by listing/grep of
  `.venv/lib/python3.13/site-packages/painted/`), the pin is
  `painted>=0.12.1,<0.13` (`/Users/kaygee/Code/loops/pyproject.toml:17`), and
  the lock resolves the 0.12.1 PyPI artifacts (`uv.lock:598–606`).

This changes §4's "renderer-through-Surface host — upstream commission" from
"commission it" to "**it exists on main; reconcile with its shipped contract**"
— and the shipped contract contradicts two things the synthesis specifies
(§2 below).

---

## 1. Triaged-gap verdicts, item by item

### 1a. Scrubber — EXISTS/MISSING call CORRECT; commission does not contradict main

Re-verified independently: `grep -rniE "scrub|slider" src/painted --include="*.py"`
matches only C0/C1 control-character scrubbing (`core/cell.py:95–96`,
`cli/_prompt_line.py:97`). No scrubber/slider/timeline widget anywhere on main
(so also not in 0.12.1). The build-from primitives the synthesis relies on all
exist in the **installed** 0.12.1: `painted.cursor.Cursor`,
`painted.views.components.progress_bar`, mouse events, refs (verified by
import against the venv package).

The proposed `ScrubberState(count, selected, marks, live_edge)` +
`scrubber(state, width, *, focused=False) -> Block` + pure `scrub_key`/
`scrub_mouse` transitions matches painted's shipped interaction idiom exactly —
S3's `ViewportAdapter` is precisely "frozen dataclass + pure transitions +
Block-producing frame function". No contradiction; if anything the commission
now has a house style to copy. One convention note: painted main's newest
mouse discipline is token-anchored (`resolve` drops events against replaced
frames, host.py docstring "the exact *displayed mapping*"); a commissioned
`scrub_mouse(state, event, region)` should adopt the same
stale-event-drops-not-translates rule or reviewers upstream will bounce it.

The fallback ("keyboard movement and click-to-ordinal using existing
primitives; trim continuous drag") is honest — everything it needs is in the
installed pin.

### 1b. Toast trim — CORRECT and consistent

Toast/notification confirmed absent from painted (same greps). The trim
decision (persistent status-bar `callout` instead) consumes a component that
exists in the installed 0.12.1
(`site-packages/painted/views/components/_callout.py:64 def callout`). This
is the right prefer-grow-painted posture: defer rather than build a downstream
timed-overlay that painted would later duplicate as a generic timed `Layer`.
No contradiction.

### 1c. Theme roles — downstream call CORRECT; two mechanical errors in the spelling

Verified: `Palette` carries 5 semantic roles + `text`/`surface` substrate +
`series` (unchanged since v0.12.1 — `git diff v0.12.1..HEAD -- src/painted/palette.py
src/painted/vocabulary.py src/painted/theme.py` is **empty**, so the dossier's
palette analysis holds for pin and main alike). The open-role mechanism is
real: `Role` declared inline by a `Vocabulary`, overridable by name via
`Theme(roles={...})` (vocabulary.py:63–76, theme.py:48–78). Refusing to grow
`Palette` into 17 loops-shaped fields and refusing a parallel loops theme
dataclass is the right downstream/upstream split.

But the synthesis's concrete instruction breaks on two validated constraints:

1. **Role names are validated lowercase kebab-case** —
   `_NAME_RE = ^[a-z][a-z0-9]*(-[a-z0-9]+)*$` (vocabulary.py:59), enforced in
   `Role.__post_init__` (vocabulary.py:80–85) with `DeclarationError`. The
   synthesis's literal names `refIn`, `refOut`, `selBg`, `selBar` are
   **invalid Role names** — they must be `ref-in`, `ref-out`, `sel-bg`,
   `sel-bar`. "Namespaced" can only mean hyphen-prefixing
   (`loops-sel-bg`); there is no dot/colon namespace. Also `Role` may not
   reuse a core name (`CORE_ROLE_NAMES` includes `text`, vocabulary.py:86–91),
   which is fine here but worth stating.
2. **There is no bare resolve-role-by-name public API.** The single public
   resolution point is `mark_style(vocab_name, value)` (vocabulary.py:471–481);
   `_role_style` is private. So the seven chrome names must be reached through
   a declared vocabulary (e.g. `Vocabulary("loops-chrome", values=("win",
   "bar", ...))` with inline `Role`s), not as free-floating roles. That works
   and stays theme-overridable, but it is chrome-through-the-*meaning*-channel
   — painted's own framing is "Roles are *meaning*; text/surface are the
   *substrate*" (palette.py docstring). For `ref-in`/`ref-out`/`stale` the
   mechanism is squarely on-label (the vocabulary docstring's own examples are
   "edge direction, freshness" — vocabulary.py:5–6). For `win/bar/sel-bg`
   chrome it is supported-but-off-label; "not a workaround" overstates it
   slightly. The decision survives; the certainty shouldn't.

The exit criterion (semantic distinguishability + monochrome/no-color
correctness, not 17-slot replication) is consistent with `MONO_PALETTE`'s
existence and the Style-not-Color role design.

### 1d. Inbound host events — poll interim is HONEST; the 0.13 replacement promise is softer than stated

The poll design is real and non-degenerate on the installed pin:

- `on_start` async lifecycle hook exists and runs inside the loop
  (surface.py constructor; dossier §1 verified, unchanged since 0.12.1 —
  `git diff v0.12.1..HEAD -- src/painted/tui/keyboard.py` and the surface
  changes are additive `HostSurface` only).
- The one-task-iterating-an-async-iterator + `mark_dirty()` shape is exactly
  the shipped `StreamSurface` pattern, and `StreamSurface` is indeed
  *"Private to the cli package"* with hardcoded `q`/ctrl-c quit (verified in
  the **installed** `cli/stream_surface.py:46–48`) — so "follow the pattern
  without importing the private class" is the only correct consumption.
- No busy-loop: the handle iterator awaits between polls (loops-side design),
  and the Surface loop itself sleeps the remainder of the frame period when
  idle (surface.py adaptive sleep). No pretend-push: "live, poll-backed from
  the durable receipt cursor" is accurate product language, and correctness
  genuinely rides on rowid catch-up, not poll timing.
- ContextVar ambient state "does not cross threads" (vocabulary.py:38–39) —
  the synthesis correctly keeps state updates on the Surface event loop.

One honesty nick: *"When Painted 0.13 exposes the supported inward seam,
replace only the wake adapter."* HOST_RUNG_DESIGN §7 ("The inward host-event
seam — designed here, deliberately last") pins the seam's constraints around
**host viewing-state reaching the application** (viewport-generation-identified
events; "viewport reached end performs no fetching itself") and leaves the
concrete event type "intentionally open until the adapter's input routing
exposes the real inventory". S4 shipped with the seam still refused
(surface.py:580: "the inward event seam stays refused, §7; this is outward").
A change-feed-shaped wake API is plausible (§7 names `strange-loops follow`
and `ticked runner` as the forcing consumers) but is not a shipped or even
concretely-shaped contract. The poll design should be stated as the plan of
record; the 0.13 swap is a hope, not a dependency. (The synthesis already
says "The inbound seam is not a gate" — good — but the "replace only the wake
adapter" sentence reads as a commitment upstream hasn't made.)

### 1e. Renderer-through-Surface host — the one real contradiction

The synthesis (§4) commissions: *"a public adapter that mounts an existing
`(data, fidelity, width) -> Block` renderer in a `Region`, owns
viewport/scroll/hit refs, and accepts atomic `set_data` / `set_fidelity`
updates. Height is offered to the host/viewport, never added to the static
lens signature."*

Painted main has already built this rung, with a **different ratified shape**:

1. **The adapter never invokes a renderer.** `ViewportAdapter` *receives*
   Blocks; data/fidelity changes are the **caller's** re-render, entering via
   `plan(RenderKey(content_id, inputs, width))` → `RenderAction.RE_RENDER` →
   `publish(new_block, plan, frame_height)` with ticket discipline
   (host.py:328–466). An adapter with `set_data`/`set_fidelity` methods that
   re-renders internally contradicts this ratified ownership split — a
   commission written to the synthesis's spec would be rejected upstream or,
   worse, accepted as a rival abstraction.
2. **The mount is not Region-shaped at the shipped surface.** `HostSurface`
   is a whole `Surface` (terminal-owning, single view, `render=(width,
   height) -> Block` closure) mounted from `run_cli` INTERACTIVE ("universal
   -i", commit f81b25a). The multi-region loops shell (tabs + sidebar +
   status bar + mounted view) cannot *be* a `HostSurface`; the reusable piece
   for it is `ViewportAdapter` driven per mounted view, painting the
   assembled `frame().block` into a `Region` via
   `Block.paint(buffer | BufferView, x, y)` (verified present in installed
   0.12.1, core/block.py:313). That is exactly what S4 does internally and
   what host.py's docstring says the adapter was built for.
3. **"Height ... never added to the static lens signature" is wrong as an
   upstream requirement.** HOST_RUNG_DESIGN §4 explicitly *rejects* confining
   height to a Surface-only adapter: "Height must reach the **semantic
   renderer**, not stop at a Surface-only adapter (round-0 P1). Confining it
   to the adapter would fork the contract." The ratified design is dual-arm:
   the 3-arg contract unchanged (omitted arm, host viewport) **plus** an
   opt-in `HeightRenderer(data, fidelity, width, *, height)` binding
   (offered arm). The synthesis's rule is correct **as a loops-lens
   decision** — loops lenses stay 3-arg and ride the omitted arm, which is
   the default and needs no declaration — but stated as the commission's
   contract it contradicts what upstream ratified on 2026-07-15 and has
   already shipped (S1, commit 7a3907b).

Also note the shipped default the synthesis's quit discipline must override:
`HostSurface(quit_keys=("q", "escape"))` (surface.py:548) and StreamSurface's
hardcoded `q`-quit both embody the exact `q`-quits convention the corpus
ruling deletes. `quit_keys` is a constructor parameter, so this is one line —
but S2's "`q` never quits" exit gate should name it, or a future
HostSurface-consuming mount silently reintroduces the collision via defaults.

The version-skew guidance itself ("consume only after a Painted release and
explicit pin/lock bump; do not code against the sibling checkout") is correct
and verified: pin `>=0.12.1,<0.13` excludes any 0.13 release automatically;
both venvs carry 0.12.1; the host rung is absent from the installed package.

---

## 2. Other synthesis claims verified (no findings)

- **`run_app(default=...)` exists in the installed 0.12.1** — not just main:
  `site-packages/painted/cli/app_runner.py:361–393`, *"default: Command for an
  unmatched non-flag argv[0] (the primary-noun shorthand). Its handler
  receives the \*full\* argv."* The S1 dispatch-default slice is buildable on
  the current pin today.
- **Fidelity fields** — installed `core/fidelity.py:31–44` carries
  `depth`/`visible`/`chars`/`lines` exactly as the migration assumes.
- **`width is None` = pipe register** — installed `cli/runner.py:474`: "the
  pipe case arrives as `width=None`, not a fabricated" [width]. The
  `piped=`-kwarg deletion is safe conflation, painted-canonical.
- **17 executable `run_cli` sites** — re-derived with
  `rg '\brun_cli\s*\(' apps/loops/src`: 21 raw matches − 2 devtools comments
  (devtools.py:123, 286) − 2 dispatch prose (dispatch.py:19, 358) = 17
  executable: devtools 5 (90, 143, 196, 259, 349), store 3, ls 2, ticks 2,
  sync 2, population 1, stream 1, dispatch 1 (409). The synthesis's
  correction of the ratified "19" is right, and its "reconcile at
  implementation time, gate on zero-not-count" hedge is the correct posture.
- **`store_app` retirement facts** — `q`/`Q`/`escape` quit at
  store_app.py:130–132; `make_fidelity_fetcher` defined at
  commands/store.py:1448 and consumed only by store_app.py:113,117 and its
  tests (test_store_command.py, test_tui.py) — the deletion list is accurate.
  `store -i` instantiates `StoreExplorerApp` at commands/store.py:1420–1423.
  `AutoresearchApp` exists as the second hand-rolled Surface app; keeping it
  out of the retirement is correctly scoped.
- **Interactive-without-handler errors** — cli/dispatch.py:235–241 confirms
  the cross-check in §7 of the synthesis.
- **Zoom bridge inventory** — `zoom_from_fidelity` call sites at
  store.py:1248/1326/1405, population.py:82, lens_resolver.py:480, plus
  `_zoom_of` at dispatch.py:205/341, and `call_lens`'s
  `inspect.signature`-sniffing (lens_resolver.py:461–490) — the S0 deletion
  targets are all real.

---

## 3. Amendments (named)

1. **host-commission-reconcile** — Rewrite §4 "Renderer-through-Surface host"
   from *commission* to *consume-and-verify*: painted main shipped S3
   `ViewportAdapter` (5a147f9) and S4 `HostSurface` (f81b25a) after the
   dossier snapshot. Drop the `set_data`/`set_fidelity` adapter contract — it
   contradicts the ratified "adapter receives Blocks, never invokes a
   renderer" split (host.py:13–19); the loops shell's data/fidelity updates
   are caller-side re-render + `plan`/`publish`. The shell's per-view mount
   drives `ViewportAdapter` directly (frame → `Block.paint` into a Region);
   `HostSurface` is the single-view `run_cli -i` shape, not the shell.
2. **height-claim-scope** — Rescope "Height is offered to the host/viewport,
   never added to the static lens signature" to loops lenses only (they ride
   the omitted arm, no declaration needed). As an upstream statement it
   contradicts HOST_RUNG_DESIGN §4's ratified rejection of adapter-confined
   height and the shipped `HeightRenderer` binding.
3. **theme-role-spelling** — Role names must be lowercase kebab-case and not
   collide with core names (vocabulary.py:59, 80–91): `ref-in`, `ref-out`,
   `sel-bg`, `sel-bar`, hyphen-namespaced (`loops-...`) if namespaced at all.
   Chrome slots resolve only through a declared vocabulary
   (`mark_style(vocab, value)` — no bare role-by-name public API); state the
   chrome-as-roles choice as supported-but-off-label rather than "not a
   workaround."
4. **quit-default-override** — Add to S2's exit gate: any consumption of
   `HostSurface` (post-0.13 bump) must pass explicit `quit_keys` — the
   shipped default `("q", "escape")` (surface.py:548) embodies exactly the
   `q`-quits collision the corpus ruling deletes.
5. **inbound-seam-promise-soften** — Replace "When Painted 0.13 exposes the
   supported inward seam, replace only the wake adapter" with a
   plan-of-record framing: HOST_RUNG §7 designs the seam "deliberately last,"
   pins only viewing-state constraints, leaves the event type open, and S4
   shipped with it still refused. The poll-backed iterator is the design, not
   a stopgap awaiting a promised API.

## 4. Verdict

**AMEND.** The architectural spine — one handle, one projector, canonical
3-arg renderer, host-owned height, poll-backed liveness, `store_app` deletion,
`run_app(default=...)` dispatch — survived every empirical check I threw at
it, on both the installed pin and painted main. The five amendments are all
§4-adjacent contract wording; none invalidates the approach, but #1/#2 must
land before implementation or the first upstream conversation starts from a
spec painted's own ratified design already contradicts.
