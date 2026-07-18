# Session 3 design advice — TUI shell integration

*2026-07-17. Independent advisor: Codex. Grounded in the TUI corpus, the
Painted capability triage, session-1 cursor arbitration, session-2
`VertexHandle` contract, the current read/dispatch/lens code, and the current
`store_app` implementation.*

## Recommendation

Make the TUI an **interactive RUN tier over a resolved lens plan**, not a new
command-shaped reader and not a second family of renderers. The canonical
entry is:

```text
sl read [VERTEX] -i [--lens NAME]
sl [VERTEX] -i [--lens NAME]       # shorthand, after dispatch-default lands
```

The shell owns one `VertexHandle`, one selected cursor, and one mounted view.
The mounted view owns navigation state only. Acquisition and projection remain
the lens's existing fetch side; rendering remains its existing renderer. The
interactive host adds allocation, viewport, focus, keys, tabs, and chrome.
There must be no `tui_fetch`, no store-specific TUI reader, and no TUI-only
fold implementation.

Keep Painted's canonical renderer signature exactly:

```python
def lens(data: T, fidelity: Fidelity, width: int | None) -> Block: ...
```

Do not add height, cursor, `piped`, vertex identity, or a row-renderer callback
to that signature. Height belongs to the interactive host. `width is None`
already means the pipe register. Cursor identity and its honesty labels are
domain data returned by fetch. Standard rows go through a shared loops grammar
function imported by lenses, rather than through a callback smuggled into the
renderer contract.

The minimum honest 0.8.0 shell is the three corpus tabs (`read`, `stream`,
`ticks`), generic mounting of declared lens views, four fidelity levels,
keyboard navigation, a discrete receipt-position scrubber, HEAD-following from
one handle iterator, explicit cursor labels, and clean lifecycle/quit behavior.
Composer, toast, bespoke interactions for all eight studies, mouse-drag polish,
and a perfect 17-slot visual replica are not release criteria.

## 1. Lens mount mechanism

### Declaration

Replace convention-only lens wiring with a small `LensSpec`; retain the current
function names as a compatibility input while built-ins migrate. A lens module
may export one or more specs:

```python
@dataclass(frozen=True)
class LensSpec(Generic[T]):
    name: str
    route: Literal["read", "stream", "ticks"]
    project: Callable[[VertexSnapshot, ReadQuery], T]
    renderer: Renderer[T]  # (data, fidelity, width) -> Block
    tui: TUIViewSpec | None = None

@dataclass(frozen=True)
class TUIViewSpec:
    title: str
    controller: type[ViewController] = BlockViewController
    selectable: bool = True

class ViewController(Protocol[T]):
    def mount(self, host: MountHost, data: T) -> None: ...
    def refresh(self, data: T, change: ChangeBatch | None) -> None: ...
    def unmount(self) -> None: ...
```

`project` is the domain half of today's optional lens `fetch`. The one-shot
CLI fetch becomes: open/capture a snapshot, then call `project(snapshot,
query)`. The TUI calls that **same projector** on `handle.snapshot`. This is
one fetch definition with two acquisition lifetimes, not two read paths. A
lens must not declare an independent TUI fetch.

`ReadQuery` carries domain selectors (`--kind`, `--key`, `--at`, `--as-of`,
etc.); `Fidelity` carries disclosure. The split preserves the ratified
domain-query versus terminal-axis boundary.

For cursor-bearing reads, `T` includes a typed presentation envelope:

```python
@dataclass(frozen=True)
class CursorPresentation:
    position: WitnessPosition | AggregatePosition | None
    mode: Literal[
        "head", "witness", "tick-floor", "event-time-projection",
        "aggregate-head",
    ]
    label: str
    anchored: bool
    sealed: bool
    receipt_seq: int | None
    visible_count: int | None

@dataclass(frozen=True)
class FoldRead:
    fold: FoldState
    cursor: CursorPresentation
```

That is what makes honest headers unavoidable. A lens cannot receive a
rewound fold while accidentally retaining a HEAD label. Existing HEAD static
output may keep its current bytes; new cursor modes get new goldens.

### Discovery and mounting

Extend the existing resolver tiers, not the top-level CLI registry:

1. Resolve the three fixed tab routes through the same vertex-local → cwd →
   user → built-in lens order.
2. At runtime, enumerate `LensSpec`s whose `tui` is non-null and whose route
   matches the active tab. Import only the selected module. Completion keeps
   using AST inspection and must remain render-free.
3. `--lens graph` selects that read-tab mount at entry. Inside the shell, `l`
   opens a lens picker for the active route. It changes the mounted plan, not
   the handle or data source.
4. `read`, `stream`, and `ticks` are tabs, not eight permanent tabs. Graph,
   Confluence, Horizon, Dissolution, and other study views are alternate
   read-route mounts. Provenance is a row drill/layer. Strata is a ticks-route
   mount once its lineage substrate exists.

The generic `BlockViewController` is sufficient for a first version: call the
same renderer, mount its `Block` in a Painted viewport, scroll it, and use
semantic refs for selection. A bespoke controller may interpret keys or mouse
hits, but it may not query the store or render an alternate copy of the lens.

### Lifecycle and ownership

- **Mount:** resolve `LensSpec`; call `project(handle.snapshot, query)` once;
  create controller state; render the lens block at the current fidelity and
  width. The host owns height and viewport clipping.
- **Refresh from handle:** the single handle consumer receives a
  `ChangeBatch`, reads the new immutable `handle.snapshot`, reruns the same
  pure projector, and atomically replaces mounted data. Selection is restored
  by stable row address, never list index. `RowChange` may drive highlights or
  selection repair; it is not an authority for patching state.
- **Rewind:** continue warming the handle's HEAD snapshot while the displayed
  snapshot is frozen at the selected position. There is still one iterator.
  Returning to `now` swaps the mounted data to the latest HEAD atomically.
- **Unmount:** discard controller/focus/hit state and cancel lens-local UI
  tasks. It does not close the shared handle.
- **Vertex switch / shell exit:** unmount, close the one active iterator, then
  close the handle idempotently. Never mutate the store on detach.

This is `fetch -> lens -> RUN` in all tiers: static RUN prints the block; live
RUN hosts it ephemerally; interactive RUN mounts it in a viewport.

## 2. Entry, dispatch, and quit

### Entry

Use `-i` on `read`, because interactivity is a Surface/fidelity tier of the
same read. Do **not** mint `sl tui` as a new domain verb. The explicit,
always-unambiguous form is `sl read project -i`; the preferred shorthand is
`sl project -i`. `sl read project -i --lens graph` mounts Graph in the read
tab without a second fetch path.

The shell may show command-bar text such as `loops read project --facts -v`,
but it is a truthful projection of the current `ReadQuery` plus `Fidelity`, not
an eval string and not a second parser.

### Dispatch-default relation

The open store thread is correct: Painted's `run_app(default=...)` already
models “unmatched arg0 goes to a default handler with the full argv.” Land the
default `AppCommand` for vertex shorthand, delete the `known`-set/manual
fall-through in `cli/app.py`, and test `completion`, unknown commands,
path-like errors, predicates, and every vertex-first operation. Then
`sl project -i` reaches the same read operation as `sl read project -i`.

Do not add a TUI exception to the existing pre-router. If schedule forces the
dispatch dissolution later, 0.8.0 can still advertise the explicit
`sl read project -i`; the shorthand is not allowed to use new one-off routing.

### Quit collision

The corpus wins:

- `q` and `-`: zoom out one fidelity level.
- `v`, `+`, and `=`: zoom in one level.
- `Q` or `Ctrl-C`: quit the shell.
- `Escape`: cancel composer/modal, collapse a drill, or clear selection; it
  never quits from the root view.

At MINIMAL, `q` is a no-op with an inline status-bar message. It never changes
meaning based on zoom. This deletes `store_app`'s `q`/`Q`/Escape quit behavior
instead of perpetuating the collision.

## 3. `store_app` retirement

Retire the redundant application, not a fictitious fidelity parser.

Delete:

- `loops.tui.store_app.StoreExplorerApp`;
- `StoreExplorerState` and the misleadingly named navigation-only
  `FidelityState`;
- its hand-built tick list/detail/fact-window renderer and keymap;
- `make_fidelity_fetcher`, which is used only by `store_app` and its tests;
- store-app-specific builders, tests, and the `loops.tui` export;
- the base `store -i` handler that instantiates it.

Keep:

- static `sl store`, `store stats`, `store ticks`, verify/rebirth/reanchor/
  absorb/adopt, `make_fetcher`, and their existing lenses/tests;
- Painted `DataExplorerState`/`ListState` where other consumers use them;
- the domain idea of a tick-window fact drill, expressed as the shell's
  `ticks` mount plus `stream` drill rather than as a store-only app;
- `AutoresearchApp` until its bespoke controller is deliberately mounted in
  the shell; it is not part of this retirement by implication.

Cut over atomically with the first shell that has `read`, `stream`, and `ticks`:
there should be no release with two interactive store browsers and no release
that silently loses the old entry. For one compatibility release,
`sl store VERTEX -i` may delegate to the **same** read-shell operation and
print a deprecation note. A bare `.db -i` must refuse with “interactive views
require a .vertex declaration; use static `sl store DB`,” because inventing a
declaration-free TUI would preserve the duplicate path. Remove the delegation
in the next major/minor cleanup.

## 4. Painted gap plan

### Scrubber — build the loops semantics now; commission reusable mechanics

0.8.0 needs a keyboard-operable discrete scrubber. Build the loops controller
from Painted `Cursor`, progress rendering, semantic refs, and mouse events.
Its domain is `0..fact_head_seq`, its values are exact receipt positions, and
tick marks are decorations. No date interpolation is permitted.

Commission a small upstream Painted `DiscreteScrubber`, because index-to-cell
layout, keyboard motion, click/drag hit-testing, focus styling, and headless
tests are generic interaction mechanics. Minimal contract:

```python
ScrubberState(count, selected, marks, live_edge)
scrubber(state, width, *, focused=False) -> Block  # refs each selectable cell
scrub_key(state, key) -> ScrubberState
scrub_mouse(state, event, region) -> ScrubberState
```

It must know nothing about timestamps, ticks, SQLite, or Watch. If the
commission misses the release window, ship keyboard movement and click-to-
ordinal using existing primitives; trim continuous drag polish rather than
copy a full widget downstream.

### Toast — trim from 0.8.0

Do not build or commission toast for this cut. Emit success, orphan warnings,
and dry-run status in a persistent status-bar `callout`; this is more honest
and testable than a disappearing message. Toast returns with the composer and
can later be a generic Painted timed `Layer`. No timer/overlay abstraction is
needed by the minimal shell.

### Theme roles — use Painted's extension mechanism downstream

Do not grow `Palette` into a loops-shaped 17-field type and do not create a
parallel loops theme dataclass. Use Painted's five semantic roles,
`text`/`surface`, and series ramp. Declare `refIn`, `refOut`, `stale`, plus the
seven chrome/selection names (`bright`, `body`, `win`, `bar`, `border`,
`selBg`, `selBar`) as namespaced app roles through `Vocabulary`/`Theme.roles`.
That is Painted's supported open-role mechanism, not a workaround. Only
commission core roles upstream if a second application proves the vocabulary
portable; chrome names from one mock do not justify freezing them into
Painted's core semantics.

The 0.8.0 exit criterion is semantic distinguishability and monochrome/no-
color correctness, not pixel-perfect reproduction of all 17 mock slots.

### Inbound host events — wait for 0.13; consume the handle in-loop now

Do not invent `post_event`, a cross-thread queue, or a loops copy of the
ratified 0.13 seam. In 0.8.0, `Surface.on_start` spawns one task that iterates
`handle.changes_async()`. That iterator is poll-backed at 50 ms, coalesced at
200 ms, updates immutable shell state on the Surface event loop, and calls
`mark_dirty()`. Cancellation closes the iterator and handle. This follows
Painted's shipped `StreamSurface` pattern without importing its private class.

Yes, this can ship honestly without the inbound seam. Product language must
say “live, poll-backed from the durable receipt cursor” rather than imply
native SQLite push. Correctness comes from `facts.rowid`/`ticks.rowid` catch-up;
polling affects latency only. When Painted 0.13 exposes the supported inward
seam, replace only the wake adapter, not the handle or shell state machine.

### Renderer-through-Surface host — upstream commission

This is distinct from inbound events and is the Painted gap most likely to
create real duplication. Commission the remaining 0.13 host rung: a public
adapter that mounts an existing `(data, fidelity, width) -> Block` renderer in
a `Region`, owns viewport/scroll/hit refs, and accepts atomic `set_data` /
`set_fidelity` updates. Height is offered to the host/viewport, never added to
the static lens signature. It needs no loops domain types and no event-source
API.

Consume it only after a Painted release and explicit root pin/lock bump; the
current `>=0.12.1,<0.13` pin excludes it. Do not code against the sibling
Painted checkout. If upstream timing misses, the only acceptable downstream
residue is a shell-specific `Block.paint(region)` mount, not a reusable shadow
host framework.

## 5. The one lens-signature migration

### Target

Every lens and every command-level renderer ends at Painted's existing
contract:

```python
def view(data: T, fidelity: Fidelity, width: int | None) -> Block:
    depth = fidelity.depth
    piped = width is None
```

The migration deletes `zoom_from_fidelity`, `_zoom_of`, signature inspection
in `call_lens`, `visible/chars/lines` teardown kwargs, and explicit `piped=`
threading. Lenses read `fidelity.visible`, `.chars`, and `.lines` directly.
Vertex identity and `CursorPresentation` travel in typed fetched data or a
read-specific result envelope. Height remains absent.

Introduce one shared, byte-preserving grammar function for standard entity/
event rows:

```python
def render_row(row: Row, fidelity: Fidelity, width: int | None,
               *, selected: bool = False,
               decorations: RowDecorations = RowDecorations()) -> Block: ...
```

It owns the rail, address, body, metadata, refs, and semantic ref attachment.
Fold/declarations/vertices/store/stream use it where they render the same row
concept; genuinely view-specific summary and diagram rows stay local.
Provenance/selection overlays enter as typed `RowDecorations`, not per-lens
hooks. Attaching refs/styles must not alter existing visible bytes.

Cursor threading is therefore **not a fourth renderer argument**. The fetch
resolves `--at`/`--as-of` and produces `CursorPresentation` alongside the
reconstruction. The lens prints that label; the TUI uses the same position for
the scrubber and command bar. This makes the cursor a semantic property of the
answer rather than terminal context.

### Migration order

Treat this as one coordinated branch and one golden gate:

1. Freeze current static golden output and add parity assertions around the
   shared row candidates. Add `CursorPresentation`, `RowDecorations`, and the
   shared renderer without switching output.
2. Make lens bodies accept `Fidelity` directly, starting with leaf lenses
   (`compile`, `validate`, `test`, `run`, `sync`, `population`), then
   stream/ticks/store/ls, then fold and composition lenses. A temporary
   internal adapter may keep the branch green, but it is deleted before the
   slice lands.
3. Convert command callers in low-to-high fanout order: devtools; sync and
   population; stream and ticks; the three store surfaces; the two ls
   surfaces; `cli.dispatch` last. Pass lens functions directly wherever no
   domain binding remains.
4. Move vertex/cursor identity into fetched results, switch the standard row
   sites together, delete all teardown adapters and old `Zoom` lens imports,
   then run the complete golden/parity/TTY/pipe suite once.

The ratified history calls this “19 `run_cli` sites.” On this checkout,
`rg '\brun_cli\s*\('` finds **17 executable calls**: devtools 5, store 3,
ls 2, ticks 2, sync 2, population 1, stream 1, and live dispatch 1. The other
matches are prose. Reconcile that inventory at implementation time; the real
exit gate is zero command render closures that convert Fidelity to Zoom and
zero lens entrypoints with the old signature, not an assumed count.

Existing static invocations must remain byte-identical. Update test calls from
`Zoom` to `Fidelity`; do not regolden changed visible output. Only new cursor
headers/modes receive new fixtures. This is one seam migration, not separate
zoom, cursor, and row-renderer waves.

## 6. 0.8.0 scope and shippable slices

### Dependency gates (not loops feature slices)

- Session-1 fold addressing must supply A1–A13 resolution and labeled cursor
  results.
- Session-2 handle S0–S4 must supply single-store immutable snapshots and the
  async change iterator. Aggregate interactive behavior depends on its vector
  handle; until then aggregates are explicitly head-only.
- Painted should release the renderer host and, preferably, the discrete
  scrubber; loops then bumps the `<0.13` pin deliberately. The inbound seam is
  not a gate.

### S0 — one renderer/lens contract

Perform the migration in section 5, including shared semantic refs/row
rendering, with no visible static drift.

**Exit:** all existing static goldens are byte-identical; TTY/pipe parity
passes; no lens takes `Zoom`; no renderer adapter calls `zoom_from_fidelity`;
completion remains render-free; all executable `run_cli` sites are accounted
for.

### S1 — reusable lens plans and dispatch default

Introduce `LensSpec`, split existing lens fetches into snapshot acquisition +
pure projection, and build read operations through one factory used by CLI and
future shell. Move vertex shorthand to Painted `run_app(default=...)`.

**Exit:** static `sl read V` and `sl V` are byte-identical; custom lens
precedence and loud failure are unchanged; completion still routes correctly;
an in-memory snapshot projected through a spec equals its one-shot fetch;
unknown/path-like dispatch tests and binary smokes pass.

### S2 — shell spine and atomic `store_app` cutover

Land `sl read V -i`, one selected vertex, the read tab, generic Block mount,
viewport, fidelity keys, `Q`/Ctrl-C quit, and deterministic `TestSurface`
coverage. Add stream/ticks mounts sufficient to replace the old explorer;
delegate `store V -i` to this shell and delete `store_app` in the same slice.

**Exit:** static reads remain unchanged; one initial fetch/project occurs;
resize/scroll/zoom/quit work; `q` never quits; `.db -i` refuses honestly;
there is one interactive store/read implementation in the repository.

### S3 — shell corpus skeleton

Add vertex sidebar, fixed read/stream/ticks tabs, command-bar projection,
status bar, lens discovery/picker, stable-address selection, and
mount/refresh/unmount tests. Mount alternative lenses through the generic
controller; do not promise their bespoke mock interactions.

**Exit:** switching tabs/lenses never opens a second watcher; selected lens
uses the same projector and renderer as static; vertex switch closes the old
handle; missing/broken mounts fail visibly; terminal widths/heights down to a
documented minimum render without crash or hidden quit controls.

### S4 — cursor and poll-backed live HEAD

Wire the one handle iterator, A5-labeled cursor headers, A6 discrete scrubber,
tick decorations, HEAD-following, unsealed-tail/control-event disclosure, and
head-versus-view snapshot separation. Keyboard operation is required; mouse
drag is conditional on the Painted commission.

**Exit:** external facts, backdates, `_decl` groups, and tick-only batches
wake the shell without loss; rendered state equals cold reconstruction;
`seq` and visible counts are distinct; a historical view stays frozen while
HEAD warms; returning to now catches up atomically; close/cancel mutates no
store; latency is documented as poll-backed.

### S5 — aggregate honesty and release gate

If the aggregate handle is ready, render member cursor vectors and per-member
anchor/fallback labels. Otherwise refuse aggregate scrubbing/live mode and
show the existing `aggregate-head` marker; static aggregate reads survive.
Run no-color, narrow-terminal, keyboard-only, multiprocess, golden, and fresh-
wheel tests.

**Exit:** no aggregate ever displays a scalar `seq`/`fact` cursor; partial
anchors are disclosed per member; the wheel uses released Painted APIs only;
all 0.8.0 claims match the shipped capability.

### Deferred beyond 0.8.0

- composer/emit flow, toast, dry-run and orphan overlay;
- bespoke Graph panning, Dissolution threshold dragging, Provenance click-to-
  historical-winner, Confluence relay animation, and Horizon live controls;
- Strata until attested parent/child tick lineage exists, and Digest until
  session 4's authorization/routing design lands;
- generalized cross-thread Painted inbound events (consume 0.13 when shipped);
- per-fact receipt timestamps, continuous wall-clock interpolation, and global
  fact+tick receipt order;
- perfect 17-slot mock styling and continuous mouse drag if the upstream
  scrubber is not released;
- deleting `AutoresearchApp` before its controller has feature parity.

## 7. Cross-checks and conflicts

### Cursor design

- **A5:** a timestamp is not enough for a header. `CursorPresentation` must
  say tick-floor versus labeled event-time projection. This conflicts with
  the corpus's shorthand `asof T = facts where ts <= T`; session-1 arbitration
  supersedes that mock mechanism where a witness anchor exists.
- **A6:** the mock's visually continuous time ruler conflicts with the
  ratified discrete receipt scale. The ruler maps cells to receipt ordinals;
  ticks are dated marks. It never interpolates a fact position from a date.
- **A9:** one global shell scrubber conflicts with aggregate cursor vectors.
  Aggregate mounts need a per-member vector/marker presentation, or 0.8.0
  must make them head-only. `seq:` and `fact:` remain refused at aggregate
  scope.
- **A1/A7:** tick arrival cannot advance the facts scrubber, and `_decl`
  receipts cannot be hidden. Stream shows control events and both receipt seq
  and visible-domain count. No UI copy may promise O(1) incremental folding.
- **A2/A10/A12/A13:** the controller cannot land mid-ceremony; serialized
  positions remain lineage-qualified; unsealed tails and pre-genesis ontology
  floors retain their honesty labels.

### `VertexHandle`

- The handle publishes HEAD. Rewind therefore needs a separate immutable
  displayed reconstruction, not mutation of `handle.snapshot` and not a
  second handle/watcher.
- `ChangeBatch.rows` is a navigation/highlight aid. Applying it as the source
  of truth would conflict with the handle's cold-replay-equivalent snapshot
  contract, especially for backdates and ontology changes.
- Facts and ticks have independent cursors. Sorting their arrivals into one
  shell timeline would invent the global receipt order explicitly deferred by
  sessions 1 and 2.
- One active change iterator and idempotent close align with one shell task.
  A controller that subscribes independently would violate the contract.
- Aggregate projection must fold the union under `(ts, id)` from a member
  vector; combining mounted member fold states would be incorrect.

### Existing code and Painted

- Current read interactive mode without a handler errors. The shell must bind
  the read operation's interactive RUN handler; it must not bypass
  `Operation`/dispatch.
- Current `store_app` quits on `q`, fetches independently, and renders a
  store-specific view. All three conflict with the recommended shell and are
  deletion targets.
- Painted 0.12.1 can run the poll-driven shell, but its missing public renderer
  host makes generic Block mounting the main upstream commission. Its missing
  inbound seam is not a correctness or 0.8.0 release blocker.

## Bottom line

The smallest coherent shell is not a miniature clone of every mock. It is one
long-lived vertex session, one cursor axis, one resolved lens plan, and one
interactive Painted host. The important ratchets are architectural: cursor
truth travels with fetched data; static lenses keep the canonical renderer
contract and byte output; the TUI owns height and navigation; the handle owns
change discovery; and `store_app` disappears at cutover. Everything else can
grow as mounted controllers without reopening the data path.
