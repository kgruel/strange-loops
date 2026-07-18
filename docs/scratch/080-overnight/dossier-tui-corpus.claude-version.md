# TUI mock corpus: temporal cursors, shell, and lenses

This chapter reads the visible terminal copy in the supplied HTML studies. Citations are to source files and approximate source lines; for the interactive shell, visible strings are assembled by JavaScript, so citations point to the generating code.

## Rewind: a time-addressed reconstruction with a mixed boundary identity

The public address is time. The command is `$ loops read project --asof 'last friday'`, and the result locates the reconstruction as `project · asof Fri Jan 10 · 17:00   replayed 51 of 142 facts` ([Rewind View.dc.html, ~34–35](</Users/kaygee/Downloads/Terminal UI for loops/Rewind View.dc.html>)). The mock is explicit that the mark is positional rather than a range filter: `asof Fri Jan 10 · 17:00   ·   the mark is a cursor, not a cutoff   ·   rewound 4d 19h` (~41). At mechanism depth, that becomes `asof T    fold( facts where ts ≤ T )    51 facts  →  the rows above` (~88). Thus the user supplies a human timestamp expression, normalized conceptually to `T`; replay includes facts through that timestamp.

The selected temporal position nevertheless has a tick/sequence identity: `tick cursor at T   01JQ4C…  seq 116 · Jan 10 16:58   (last tick before the mark)` (~91). The mock does **not** say that `--asof` is addressed by tick or sequence. It says the time cursor is associated with the last tick before the mark. The shell's tick rows reinforce the pairing: each tick has a timestamp, linkage, signature, and a cursor such as `seq 142` or `seq 116` ([Loops TUI.dc.html, ~135–140, ~345–357](</Users/kaygee/Downloads/Terminal UI for loops/Loops TUI.dc.html>)). Empirically, `seq` is an append-log position/count boundary: Watch subscribes `from seq 142 onward`, while tick metadata advances through `seq 116`, `seq 122`, `seq 130`, and `seq 142`. The corpus never formally defines whether sequence numbers are per vertex or global, so any stronger claim would exceed the mock.

The scrubber scrubs reconstructed state, not merely event visibility: `drag the ruler and every other lens (fold, stream, graph) reframes to that instant; release on now and you're live again` ([Rewind View.dc.html, ~109](</Users/kaygee/Downloads/Terminal UI for loops/Rewind View.dc.html>)). A second mark turns position into comparison: `Drop a second mark and the gap between them is the diff.` The concrete form is `$ loops read project --asof 'last friday' --diff now`, followed by `Fri Jan 10 17:00 → now   ·  4d 19h  ·  +21 facts across 6 keys  ·  0 deleted` (~63–64). Position diffs are grouped into `new — didn't exist then` with `+` rows, and `revised — same key, folded further` with `~` rows; revisions show multiplicity and state transitions, e.g. `~ decision  design/sqlite-persistence   ×2 → ×4   proposed → accepted` (~66–76). The honesty statement is exact and structural: `the diff is a set difference of two reconstructions — nothing is ever deleted (append-only)` (~78), elaborated as `diff      rows(now) ⊖ rows(T)          a pure set difference` (~89).

There is no `-v` Rewind panel in the mock. The progression jumps from the two-cursor default example to `-vv ADDS — HOW, AND WHY ONLY HERE` (~84). Therefore the prompt's implication that both `-v` and `-vv` have Rewind semantics is partly false: only `-vv` is specified. It reveals HEAD folding, timestamp-bounded folding, row-set difference, the tick/seq cursor, and chain continuity: `chain to replay    01JQ8F… ← 01JQ7M… ← … ← 01JQ4C…   intact · no gaps` (~86–94). Its trust claim is append-only addressability: `a mutable log overwrites the past; here the past is all still there, addressable by T`. Provenance supplies the companion integrity language: `chain      01JQ8F… ← 01JQ4C… ← 01JPZ8… ← 01JPX2…   intact · no gaps` and `integrity  each ULID sorts by ts · monotonic · replay is deterministic` ([Provenance View.dc.html, ~69–77](</Users/kaygee/Downloads/Terminal UI for loops/Provenance View.dc.html>)).

## Watch: the same cursor pinned to the append edge

Watch starts as `$ loops watch project` and reports `project · watch   ● live · following HEAD · 3 observers active`; timestamped facts append above `● waiting for facts …` ([Watch View.dc.html, ~34–43](</Users/kaygee/Downloads/Terminal UI for loops/Watch View.dc.html>)). `-v` adds derived change detection: `each fact, and the derived row it moves`, with lines such as `task     budget-fields      → in-progress (was todo) ×3`; the invariant is `you watch state move, not just events — the fold runs on every append` (~48–57). `-vv` defines the refresh model: `watch = fold that never terminates · cursor pinned to HEAD`, `subscribe     tail the append log   from seq 142 onward`, `on append     apply → diff → emit   changed rows only, not the whole fold`, `coalesce      bursts < 200ms        fold together before printing`, and `backpressure  slow consumer         batches · never drops a fact` (~63–71). `^C` only detaches; it does not alter the store (~72). In the TUI, Watch is the active-loop default and rows light as facts land; `--kind`, `--observer`, and `--key` scope lanes. Dragging away from `now` reviews history; releasing on `now` resumes Watch (~89). This is event-driven append subscription with sub-200ms burst coalescing, not periodic polling.

## Loops TUI shell

The mounted shell is a terminal window with titlebar, a 34-character vertex sidebar, and a main column containing command bar, tabs, scrollable view, optional composer, and status bar ([Loops TUI.dc.html, ~513–566, ~569–604](</Users/kaygee/Downloads/Terminal UI for loops/Loops TUI.dc.html>)). The title is `loops — kyle/loops-claude — ~/src/strange-loops`; the sidebar lists `VERTICES`, six numbered vertices, activity/freshness, `+ config (12)`, and the legends `×n revisions`, `←n inbound refs`, `→n outbound refs`, `⊘ stale · open >7d`. The tabs are `read`, `stream`, and `ticks` (~548–553). They mount three renderers over the selected vertex: folded state, ordered facts, and resolved ticks (~187–201, ~576–578). The generated command bar mirrors that mount: `$ loops read <vertex>`, `$ loops read <vertex> --facts`, or `$ loops store ticks <vertex>`, plus `-q`, `-v`, or `-vv` at the selected fidelity (~537–545). This is the mock's entry point; no separate executable-launch text appears beyond those commands.

Bindings are `↑`/`↓` or `j`/`k` to move, `Tab`/`]` forward and `[` backward through views, `1–6` to select a vertex, `Enter` to expand refs, `e` to emit, and `Escape` to collapse/cancel ([Loops TUI.dc.html, ~376–400](</Users/kaygee/Downloads/Terminal UI for loops/Loops TUI.dc.html>)). Crucially, `q` does **not** quit: `q` and `-` zoom out one fidelity level; `v`, `+`, and `=` zoom in (~383–384). Fidelity is clamped across `MINIMAL`, `SUMMARY`, `DETAILED`, `FULL`, corresponding to `-q`, default, `-v`, `-vv` (~556–565).

The composer mounts below the view after `e` as `◆ emit  →  <vertex> as <observer>`, offers kind chips, and constructs `loops emit <vertex> <kind> <keyfield>=… "…"` ([Loops TUI.dc.html, ~451–510](</Users/kaygee/Downloads/Terminal UI for loops/Loops TUI.dc.html>)). Its preview shows `Fact`, kind, observer, timestamp, payload, fold destination, and detected refs. Missing a required fold key warns `stored but orphaned, will not fold`; Enter stores, Tab moves fields, `dry-run` validates without storage, and Escape cancels. Successful submission appends a stream fact and patches its fold row, briefly marking it `✦ new` (~421–449).

## Digest: close is an additive emitted fact

The command surface is `$ loops digest project --since 'last tick'`; the input header reports `142 facts · window Jan 3–15 (12d) · 5 observers` ([Digest View.dc.html, ~34–35](</Users/kaygee/Downloads/Terminal UI for loops/Digest View.dc.html>)). Output divides the window into `resolved this window`, `carried forward — rolls into the next tick`, and `→ synthesized · one fact, emitted upward`, whose destination is `◆ close  loops/roadmap` with an editable-looking quoted synthesis (~37–52). `-v` ranks inputs by salience around a `digest cutline — top-k by salience`, while promising that below-cutline material remains and re-competes next window (~57–68). `-vv` states `digest = summarize( fold( facts in window ) )`; the result is `kind=close · refs the window it summarizes`, `flows to  loops/roadmap          appended as 01JQ9K… · seq +1`, is folded by its parent, and leaves all 142 input facts intact (~74–84). In the TUI, resolving a tick emits the synthesis for editing before it flows upward; expansion descends into its compressed window and `why` exposes inputs (~99). The synthesized output lands as a new close fact in `loops/roadmap`, not as replacement text in the source vertex.

## Remaining views and Static TTY

**Confluence.** `$ loops read project --lens confluence` pivots 47 facts by four observers and kind, with density as share and block height as volume; `-v` reconstructs a feedback relay from observer, timestamp, and entity refs, and `-vv` adds per-observer horizon/potential plus convergence points ([Confluence View.dc.html, ~37–90](</Users/kaygee/Downloads/Terminal UI for loops/Confluence View.dc.html>)). Its honesty boundary is explicit: `the chain is reconstructed from observer + ts + entity refs — no new data` (~63).

**Dissolution.** `$ loops read project --lens dissolution` separates 51 surfacing facts from 91 below the fold and renders salience decay, digest absorption, orphans, and held open work ([Dissolution View.dc.html, ~34–46](</Users/kaygee/Downloads/Terminal UI for loops/Dissolution View.dc.html>)). `-v` explains safety per fact; `-vv` defines `salience = f( recency, inbound-refs, digest-coverage )`, a roughly six-tick half-life, and a 0.10 default-lens threshold. Nothing is deleted, and `--asof`/`why` remain addresses (~53–78). In the TUI the fold threshold is draggable and rewinding makes previously dissolved rows bright again (~93).

**Graph.** Graph offers a `--core` reference diagram and a scalable whole-vertex hub/chain/orphan listing; arrows follow entity refs and hubs have at least two inbound references ([Graph View.dc.html, ~34–74](</Users/kaygee/Downloads/Terminal UI for loops/Graph View.dc.html>)). The mock explicitly limits static fidelity to `hubs, chains, orphans, no lane-routing guesswork`; interactive `-i` supplies a pannable constellation and `--refs N` traversal (~81).

**Horizon.** `$ loops read infra --lens horizon` sorts loops by pressure toward a Spec boundary, including threshold, cadence, phased, and boundary-less folds ([Horizon View.dc.html, ~36–45](</Users/kaygee/Downloads/Terminal UI for loops/Horizon View.dc.html>)). `-v` exposes accumulated evidence; `-vv` shows the boundary and fold window plus the last tick. It claims no new data and names itself the natural `--live`/agent-poll surface (~49–79).

**Provenance.** `loops why` expands a folded row into its oldest-first apply trace, then `-v` shows per-field last writer and superseded value; shadowed facts remain addressable through Rewind ([Provenance View.dc.html, ~34–61](</Users/kaygee/Downloads/Terminal UI for loops/Provenance View.dc.html>)). `-vv` gives the reduction equation, chain continuity, ULID/timestamp monotonicity, and deterministic replay (~67–77). It is a drill in any lens, not its own screen; selecting a shadowed write moves the global cursor to when it was winning (~92).

**Strata.** `$ loops store ticks release/2025.1 --lens strata` renders nested resolved periods as an icicle/flamegraph where widths are contributed fact counts and `⊕` means the node is itself a tick ([Strata View.dc.html, ~33–68](</Users/kaygee/Downloads/Terminal UI for loops/Strata View.dc.html>)). `strata <node>` descends into another period; the TUI version arrows into branches and reframes from larger to smaller timescales (~75).

**Static TTY.** The static study declares `vertex ⊃ kind ⊃ key ⊃ fact`, distinguishes `read` as folded present from `stream` as ordered past, and makes `-q / default / -v / -vv` a universal fidelity contract ([Static TTY.dc.html, ~29–32](</Users/kaygee/Downloads/Terminal UI for loops/Static TTY.dc.html>)). Its three render directions—aligned columns, Painted-native cards, and a salience/recency rail—apply the same grammar to read, stream, ticks, and vertex listings (~47–203). The tick examples show wall time, fact delta/density, and ULID together, but do not print sequence cursors.

**Loops Palettes.** The palette study offers SIGNAL (focused attention), TEMPORAL (time as depth), and STRANGE (collaboration/engraving), each explicitly mapping `painted's five semantic roles plus a categorical observer ramp` ([Loops Palettes.dc.html, ~23–29](</Users/kaygee/Downloads/Terminal UI for loops/Loops Palettes.dc.html>)). Each displays five named semantic swatches, a six-color ramp, and two substrate endpoints (~42–56, ~69–83, ~96–110). The imported TUI theme object, however, defines exactly **17 slots** per theme: `bg`, `win`, `bar`, `border`, `text`, `bright`, `body`, `muted`, `accent`, `success`, `warning`, `error`, `refIn`, `refOut`, `stale`, `selBg`, and `selBar` ([Loops TUI.dc.html, ~30–38](</Users/kaygee/Downloads/Terminal UI for loops/Loops TUI.dc.html>)). Therefore the proposed “~17 vs Painted's 5” is directionally right but imprecise: it is exactly 17 TUI implementation slots versus five claimed Painted semantic roles; the palette page itself also paints a ramp and substrate colors beyond its five labeled roles.

## Temporal-cursor-axis quotes

> `$ loops read project --asof 'last friday'`  
> `project · asof Fri Jan 10 · 17:00   replayed 51 of 142 facts`

> `asof Fri Jan 10 · 17:00   ·   the mark is a cursor, not a cutoff   ·   rewound 4d 19h`

> `sqlite-persistence reads ×2 · proposed — its then-state, not today's. a filter couldn't show that`

> `$ loops read project --asof 'last friday' --diff now`  
> `Fri Jan 10 17:00 → now   ·  4d 19h  ·  +21 facts across 6 keys  ·  0 deleted`

> `the diff is a set difference of two reconstructions — nothing is ever deleted (append-only)`

> `HEAD      fold( facts )                142 facts  →  today's rows`  
> `asof T    fold( facts where ts ≤ T )    51 facts  →  the rows above`  
> `diff      rows(now) ⊖ rows(T)          a pure set difference`

> `tick cursor at T   01JQ4C…  seq 116 · Jan 10 16:58   (last tick before the mark)`

> `chain to replay    01JQ8F… ← 01JQ7M… ← … ← 01JQ4C…   intact · no gaps`

> `a mutable log overwrites the past; here the past is all still there, addressable by T`

> `project @ Fri Jan 10 17:00 · 51/142 facts · since: +3 new · 4 revised · 0 deleted`

> `In the TUI this is the one view that literally wants a scrubber — drag the ruler and every other lens (fold, stream, graph) reframes to that instant; release on now and you're live again. Drop a second mark and the gap between them is the diff. Time stops being a --since filter and becomes the camera position.`

> `Watch`  
> `the cursor pinned to now`

> `project · watch   ● live · following HEAD · 3 observers active`

> `watch = fold that never terminates · cursor pinned to HEAD`

> `subscribe     tail the append log   from seq 142 onward`

> `the mirror of Rewind: the same cursor, pinned forward instead of dragged back`

> `In the TUI, watch is the default when a loop is active — the view breathes, rows lighting as facts land and the fold recomputing under you. Scope it with --kind, --observer, or --key to a single lane. And it's Rewind's twin on one control: drag the scrubber back to review, release on now and you're watching again. The loop, live.`

> `$ loops digest project --since 'last tick'`

> `flows to  loops/roadmap          appended as 01JQ9K… · seq +1`

> `last   tick auth/lockout · Jan 12 · 01JQ4L… · locked 8m`

> `still there addressable        by --asof (Rewind) and why (Provenance)`

> `rewind to Jan 11 and it's back on top → see the Rewind lens`

> `integrity  each ULID sorts by ts · monotonic · replay is deterministic`

> `Paired with Rewind's scrubber it becomes navigable — click a shadowed write and the cursor jumps to the instant it was still winning, then every lens reframes to that moment.`

> `cursor     seq 142`

> `cursor     seq 130`

> `cursor     seq 122`

> `cursor     seq 116`

> `Two axes of the same store`  
> `read is the folded present (state); stream is the ordered past (events). The grammar should make which axis you're on obvious.`

> `Time is fundamental, so hue encodes it. A luminous cyan present fades through indigo into a violet past — recency and staleness become the same axis. Ticks (resolved periods) carry the deeper end of the spectrum.`
