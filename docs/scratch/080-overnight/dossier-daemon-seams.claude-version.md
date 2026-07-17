# Dossier — daemon-shaped access: the missing primitive and its three consumers

Grounding chapter for 0.8.0 design session 2 (daemon-shaped engine access).
Empirical survey, 2026-07-17. Everything below is quoted from source or the
project store; corrections to the tasking prompt's assumptions are flagged
inline as **PROMPT CORRECTION**.

The one-line thesis, in the store's own words (session fact
`session/2026-07-16-070-cut-and-wave-renumber`):

> "Audit's structural finds banked: one-engine-seam-counted-three-times
> (ticked poll = Watch change-detection = TUI live-refresh)"

---

## 0. Where the artifacts actually live (prompt corrections)

**PROMPT CORRECTION 1 — ticked's location.** The prompt says to look for
ticked in `/Users/kaygee/Code/tasked`. That checkout contains only three
textual references to ticked, all lineage/lesson comments; it does not contain
the ticked daemon. The implementation named by the friction is in the sibling
`loops-tasks` checkout. Three distinct task orchestrators exist:

| Name | Location | Status |
|---|---|---|
| **ticked** (the quadratic-poll daemon named by the friction) | `/Users/kaygee/Code/loops-tasks/src/ticked/` — repo `loops-tasks`, package `ticked` | The friction's subject. `friction:no-daemon-shaped-store-access` opens "ticked (loops-tasks) runs a 2s-poll daemon over a vertex". |
| **tasked** (successor/sibling) | `/Users/kaygee/Code/tasked/src/tasked/` | Separate repo; its `substrate.py` and `walker.py` cite ticked as lineage ("the ticked reset=true trap", substrate.py:90; "ticked's field lesson", walker.py:124; "subtask/ticked lineage", adapters.py:4). It has its own 2s-poll daemon (the "walker"). |
| **strange_loops** (monorepo app) | `/Users/kaygee/Code/loops/apps/tasks/src/strange_loops/` | Older task app; also polls at 2s (`follow_task_log` in commands/task.py:604-646, `_POLL_INTERVAL = 2.0` in commands/dashboard.py:34). |

**PROMPT CORRECTION 2 — Watch's design location.** The prompt says Watch's
change-detection design is in `docs/dev/interactive-read-path-design.md`.
It is not: that file contains **zero** occurrences of "watch" (verified by
grep). Watch's design lives in the 0.6.0-ratified TUI corpus at
`~/Downloads/Terminal UI for loops/Watch View.dc.html` (corpus location
pinned by `decision:design/roadmap-060-static-honest-wave`: "Corpus:
~/Downloads/'Terminal UI for loops' (9 lens studies + shell + Static TTY +
7 palettes, all at 4 fidelity levels)"). What
`interactive-read-path-design.md` *does* contribute to this chapter is the
held-open-handle fetch-layer design (§3 below).

**PROMPT CORRECTION 3 — the self-deleting docstring.** The prompt attributes
the "predicts its own deletion" docstring to tasked's `substrate.py`. That is
correct — quoted in §1.4 — but note ticked's own `vertex.py` (loops-tasks)
carries the same posture one generation earlier.

---

## 1. Consumer 1 — ticked's quadratic poll

### 1.1 The poll loop

`/Users/kaygee/Code/loops-tasks/src/ticked/runner.py:84-122`:

```python
@dataclass
class RunnerConfig:
    poll_s: float = 2.0
    max_workers: int = 2
    work_timeout_s: float = 3600.0
...
    # -- loop ---------------------------------------------------------------

    def run(self, *, once: bool = False) -> None:
        while True:
            actions = self.cycle()
            for a in actions:
                print(a, flush=True)
            if once and not actions and not self._works_in_flight():
                # Drain mode exits when a pass changed nothing and no worker
                # is running: everything left (if anything) waits on a human
                # (escalations) or on new requests.
                return
            if not actions:
                time.sleep(self.config.poll_s)
```

The runner's module docstring states the design constraint that makes
consumer-side caching wrong (runner.py:1-9):

> "Every decision derives from the fold (never from memory between cycles),
> so a restart is a replay: the store is the only coordination channel."

### 1.2 Where the full replays land, per cycle

Each of these is a full-history fold or scan (see §4 for why):

1. **Cycle fold** — runner.py:127-136:
   ```python
   def cycle(self) -> list[str]:
       """One pass: reconcile, then at most one transition per open task."""
       actions: list[str] = []
       fold = self.store.fold()
       views = self.store.views(fold)
       actions += self._reconcile(views)
       if actions:
           # Reconciliation changed state; re-derive before stepping.
           fold = self.store.fold()
           views = self.store.views(fold)
   ```
   `TasksStore.fold()` is `vertex_read(self.vertex_path)` (vertex.py:232-233)
   — a full parse+compile+replay per call.

2. **Post-reconcile re-derive** — the second `self.store.fold()` above
   (runner.py:135-136), another full replay whenever reconciliation acted.

3. **Per-running-work fresh fold** — `_still_running`, runner.py:220-225:
   ```python
   def _still_running(self, task_name: str, run: str) -> bool:
       view = self.store.task_view(task_name)
   ```
   `task_view(name, fold=None)` defaults to `self.fold()` (vertex.py:245-247)
   — one more full replay *per dead-pid candidate per cycle*, deliberately
   (runner.py:169-172):
   ```python
   # Re-read this run fresh before overwriting: the worker may
   # have finished between our fold read and now. (A true CAS
   # needs engine support — friction filed; this shrinks the
   # window to the emit itself.)
   ```

4. **All-ticks scan** — `_closed_task_names`, runner.py:227-236:
   ```python
   def _closed_task_names(self) -> dict[str, dict]:
       """Task name → its latest close-tick boundary payload."""
       ticks = vertex_ticks(self.store.vertex_path, 0.0, time.time() + 60, "task.close")
   ```
   Full tick-table scan from epoch 0, every cycle, inside `_reconcile`.

5. **Emits** — every write is a fresh program load (§1.3).

6. **Drain-mode check** — `_works_in_flight` (runner.py:124-125) calls
   `self.store.views()` with no fold argument: yet another full replay
   (only on `once=True` passes).

### 1.3 The write path: fresh program per emit

`/Users/kaygee/Code/loops-tasks/src/ticked/vertex.py:79-123` — the class
docstring states the posture and its reason:

```python
class TasksStore:
    """Handle on the tasks vertex. Cheap to construct; every write opens a
    fresh program (replay + receive + close), matching the CLI's semantics
    so concurrent writers (runner, workers, CLI, other sessions) compose
    through the WAL store alone."""
```

and the emit body:

```python
        fact = Fact(kind=kind, ts=time.time(), payload=clean, observer=observer, origin="")
        fact_id = gen_id()
        program = load_vertex_program(
            self.vertex_path, validate_ast=False, **_signers(self.vertex_path)
        )
        try:
            tick = program.receive(fact, id_override=fact_id)
        finally:
            store = getattr(program.vertex, "_store", None)
            if store is not None:
                store.close()
        return EmitReceipt(fact_id=fact_id, kind=kind, tick=tick, warning=warning)
```

(Two archaeology notes: ticked pre-mints `fact_id` and reaches into
`program.vertex._store` — both already dissolved upstream by the 0.7.0
engine `Receipt` work; tasked's successor code uses `with
load_vertex_program(...) as program: return program.receive(fact)` cleanly,
tasked/substrate.py:109-112.)

Cross-process close serialization is an advisory `fcntl` lock because the
engine offers nothing better (vertex.py:205-216):

```python
        """The punctuation: mints the per-task tick via the loop-scoped boundary.

        Serialized across processes with an advisory lock: the engine appends
        the close fact and its tick in separate transactions, so concurrent
        closes (runner vs. `ticked cancel`) could otherwise fork the tick
        chain. One writer at a time keeps the chain linear.
        """
        import fcntl

        lock_path = self.vertex_path.parent / ".close.lock"
```

### 1.4 The friction fact (the canonical statement)

`sl read project --facts --kind friction --key no-daemon`:

> **no-daemon-shaped-store-access** (mid, open, 2026-07-16) — "ticked
> (loops-tasks) runs a 2s-poll daemon over a vertex, but every engine
> touchpoint is CLI-shaped: load_vertex_program does KDL parse + pin-verify
> + compile + FULL-history replay per emit, and vertex_read replays per
> read. One runner cycle = ~4-8 full replays (fold, post-reconcile
> re-derive, per-running-work fresh fold in _still_running, all-ticks scan
> in _closed_task_names, plus emits). Cost per cycle is O(total facts ever)
> -> quadratic over the daemon's life. Consumer-side caching is the wrong
> fix (restart-safety design correctly treats the WAL store as the only
> coordination channel). Fix-shape: daemon-shaped access in engine --
> long-lived VertexProgram handle with WAL-incremental refresh (replay
> facts since last seen rowid) and receive() without reload. Third
> consumer-forced engine need from ticked after no-conditional-emit and
> no-cli-verb-flat-tick-key."

Related engine need from the same consumer
(`friction:no-conditional-emit`, mid, open, 2026-07-14):

> "Entity-upsert consumers need a conditional emit (CAS): ticked's runner
> reaps dead workers by upserting work status=finished outcome=error, but
> between its fold read and the emit the worker may emit finished/replied —
> the later error upsert wins unconditionally. ... a real fix is
> engine-level: receive(fact, expect={field: value}) that refuses when the
> current folded value diverges (same shape as SqliteStore.absorb_edit's
> expected_head CAS)."

### 1.5 tasked's substrate.py — the docstring that predicts its own deletion

`/Users/kaygee/Code/tasked/src/tasked/substrate.py:1-23` (full module
docstring):

```python
"""Substrate embedding — every read and write of the tasked vertex.

This module is deliberately the ONLY file that embeds the store write/read
path (load_vertex_program/vertex_read/Fact): it is the client API the
substrate should eventually export (see loops-store
friction:no-daemon-shaped-store-access). When that API lands upstream,
this file deletes and callers don't move. Other files are free to import
engine utilities directly (e.g. walker.py uses engine.gen_id) — the
constraint is on owning the store path, not on engine imports generally.

Custody (signing) composes through libs/custody — promoted out of the
loops CLI app when this repo became the second consumer (loops-store
design:architecture/custody-lib-extraction). The upstream ratchet
string-pins the domain constants to that lib, so composing through it
IS the at-rest-format agreement; nothing to keep in sync by hand.
The one remaining CLI-app import is loops_home from
loops.commands.resolve (one resolution rule, XDG included) — client
knowledge that lands in the eventual client lib, quarantined here and
pinned by tests/test_boundaries.py (shrink-only, ratchets to empty).

Grants: M1 posture is declared-observers-only (kyle, walker, walker/*);
enforcement arrives with the substrate's grant API, not re-implemented.
"""
```

Its `Store` class restates the fresh-program posture and names it honestly
(substrate.py:70-74):

```python
class Store:
    """Handle on the tasked vertex. Every write opens a fresh program
    (replay + receive + close) so concurrent writers (walker, workers,
    CLI) compose through the WAL store alone — the known-inefficient but
    correct posture until the engine grows daemon-shaped access."""
```

And it carries a **design constraint any long-lived handle must honor** —
signers are functions of disk state, not of the path
(substrate.py:103-108):

```python
        # Signers rebuild PER WRITE, matching the fresh-program posture:
        # they are functions of path AND disk state at call time, not pure
        # functions of the path — a handle-lifetime cache froze key material
        # at daemon startup (key minted/rotated after start → tick_signer
        # stays None → UnsignedTickInSignedEra on every boundary until
        # restart; confirmed empirically in the loops-side review).
```

tasked's walker daemon is the same poll shape
(`/Users/kaygee/Code/tasked/src/tasked/walker.py:155-181`:
`poll_s: float = 2.0`, `while True: ... time.sleep(self.config.poll_s)`;
`cycle()` at walker.py:183-188 opens with `fold = self.store.fold()`).

### 1.6 ticked's own TUI already pays the same cost

`/Users/kaygee/Code/loops-tasks/src/ticked/tui/dashboard.py:38,99-122`:

```python
POLL_INTERVAL_S = 2.0
...
class Dashboard(Surface):
    """Read-only status board over a `TasksStore`. Polls on a timer inside
    `update()` — never in `render()`, which only paints `self._state`."""
...
    def update(self) -> None:
        now = time.monotonic()
        if not self._loaded or now - self._state.last_refresh >= POLL_INTERVAL_S:
            self._refresh(now)

    def _refresh(self, now: float) -> None:
        views = self._store.views()  # IO — fetched here, never in render()
```

`views()` → `fold()` → `vertex_read` → full replay, every 2 seconds, for a
pure viewer. The monorepo's `strange_loops` app repeats the pattern twice
more (apps/tasks/src/strange_loops/commands/task.py:604-646 `while True:
... time.sleep(2)` polling `vertex_facts`/`vertex_ticks` from `last_ts`;
commands/dashboard.py:284-293 `_fetch_stream` re-fetching every
`_POLL_INTERVAL = 2.0` seconds).

---

## 2. Consumer 2 — Watch's change-detection design

Source: `~/Downloads/Terminal UI for loops/Watch View.dc.html` ("Design
study — turn 9 · watch · the leading edge"). Roadmap anchor
(`decision:design/roadmap-060-static-honest-wave`, ratified by Kyle
2026-07-01): "0.7.0 [renumbered 0.8.0] = everything needing
design+discussion: TUI shell + shared temporal cursor (**Rewind/Watch as
ONE abstraction**)".

The framing:

> "Every lens so far is a snapshot — it reads the store once and renders.
> Watch is a subscription. It pins the cursor to HEAD and stays open,
> printing facts as they're appended and refolding live."

> "It's the exact mirror of Rewind. Rewind drags the cursor back through
> the timeline; Watch pins it to now and follows it forward. Same immutable
> log, same fold — one dragged into the past, one riding the leading edge.
> And because state is fold( facts ), watching isn't tailing a log of
> events — it's watching derived rows move in place as each append is
> applied."

`-v` fidelity level — fold-on-write:

> "each fact, and the derived row it moves ... you watch state move, not
> just events — the fold runs on every append"

`-vv` fidelity level — **the change-detection mechanism, verbatim** (this
is the closest thing to a spec for the primitive):

```
watch = fold that never terminates · cursor pinned to HEAD

subscribe     tail the append log   from seq 142 onward
on append     apply → diff → emit   changed rows only, not the whole fold
coalesce      bursts < 200ms        fold together before printing
backpressure  slow consumer         batches · never drops a fact
exit          ^C detaches           the store is unaffected

the mirror of Rewind: the same cursor, pinned forward instead of dragged back
```

Note what this asks of the engine, line by line: (a) a sequence-cursor
subscription over the append log ("from seq 142 onward" — rowid-shaped);
(b) incremental fold application with **row-level diff output** ("changed
rows only, not the whole fold"); (c) burst coalescing; (d) lossless
backpressure; (e) detach without store side-effects.

Rewind View (same corpus) confirms the shared-cursor contract from the
other direction: "Two cursors on the same timeline give --diff for free"
and "drag the ruler and every other lens (fold, stream, graph) reframes to
that instant; release on now and you're live again."

---

## 3. Consumer 3 — TUI live-refresh

### 3.1 The TUI corpus's own statement

Watch View, closing paragraph:

> "In the TUI, watch is the default when a loop is active — the view
> breathes, rows lighting as facts land and the fold recomputing under
> you. Scope it with --kind, --observer, or --key to a single lane. And
> it's Rewind's twin on one control: drag the scrubber back to review,
> release on now and you're watching again. The loop, live."

(The shell mock `Loops TUI.dc.html` is a React artifact rendering static
sample data — it contains no additional change-detection text; the Watch
study is the live-refresh design authority in that corpus.)

### 3.2 The store's convergence observation

`sl read project --kind observation --key architecture/ --facts` —
`observation:architecture/daemon-access-serves-tui` (2026-07-17, verbatim):

> "Convergence: ticked's 2s-poll daemon
> (friction:no-daemon-shaped-store-access) and the 0.7.0 TUI are the SAME
> consumer shape — a long-lived process needing incremental reads (replay
> facts since last rowid, not full history) and receive() without reload.
> The daemon-shaped engine access ticked forces is the TUI's substrate too;
> designing it once serves both, and the temporal-cursor work inherits the
> same long-lived-handle contract. Sequencing implication: the engine
> design session for daemon access should sit BEFORE TUI work on the 0.7.0
> track, not parallel to it."

(The "0.7.0 TUI" references predate the renumber; that wave is 0.8.0 —
`decision:design/roadmap-070-substrate-cut`.)

### 3.3 The interactive read-path design's fetch-layer asks

`docs/dev/interactive-read-path-design.md` (2026-06-27) — no Watch content,
but its "Fetch-layer changes" section is the read-side half of the same
primitive (lines under "## Fetch-layer changes"):

> "commands/fetch.py must grow a lazy, held-open substrate so the Surface
> does not re-materialize the whole vertex per frame ... Adds, in priority
> order:
> 1. A held-open StoreReader + memoized specs cache — every fetch_*
> re-parses the .vertex, recompiles specs, reopens the store; lazy
> expansion needs one persistent handle so an expand isn't a full
> re-bootstrap, and the eager fold is paid once."

and its risk register repeats the O-cost discipline:

> "any facet that RE-FOLDS would be O(2547) and laggy — the
> facet-as-re-projection discipline (in-memory sort/since/reconcile) MUST
> hold, and only diff/facts/refs/ticks may touch the store lazily."

---

## 4. What exists in libs/engine today

### 4.1 VertexProgram lifecycle — is there a long-lived handle?

**Yes, a handle can be held open; no, it cannot stay current.** Two
separate facts, both load-bearing:

**(a) The lifecycle verb exists and is daemon-aware.**
`libs/engine/src/engine/program.py:111-130`:

```python
    def close(self) -> None:
        """Release the program's store resources (idempotent).

        The lifecycle verb for the load → receive/sync → close arc.
        Embedded clients (daemons, tests, second apps) MUST close —
        a loaded program holds an open store handle (sqlite connection
        or file). One-shot CLI processes get away without it via process
        exit; long-lived processes leak handles per load without it.
        Prefer the context-manager form::

            with load_vertex_program(path) as program:
                receipt = program.receive(fact)
        """
        self.vertex.close()
```

**(b) `receive()` does NOT require a reload** — within one handle. A
received fact is appended to the store and folded into the in-memory
projections in the same call (`vertex.py:529-539` append, `:565-575` fold
via `loop.receive`), then live boundaries fire
(`vertex.py:594-597`). So "receive() without reload" is already true *for
the handle's own writes*. What forces the reload-per-write posture in
every real consumer is **other writers**: a held handle never sees facts
appended by another process. There is no refresh/reload/resync method on
`VertexProgram` or `Vertex` (grep for "refresh" in program.py/vertex.py:
zero hits), and the only replay entry point the load path uses is
full-history:

`program.py:276-285` (load pipeline tail):

```python
    # Replay stored facts to rebuild fold state — makes one-shot CLI
    # invocations indistinguishable from a persistent runtime. A raising
    # replay (corrupt row, raising fold) must not leak the store handle
    # materialize_vertex just opened — no vertex reference escapes this
    # function on raise, so close here.
    try:
        vertex.replay()
    except BaseException:
        vertex.close()
        raise
```

`load_vertex_program` does the full CLI-shaped pipeline every call
(program.py:241-297): `load_declaration` (KDL parse) →
`verify_source_pins` (pin-verify, "No-auto-enact gate", :242-246) →
optional `lang.validate` → `compile_vertex_recursive` →
`collect_all_sources` + dependency-DAG validation → `materialize_vertex`
→ `vertex.replay()`. This matches the friction fact's characterization
exactly.

**`Vertex.replay()` hardcodes cursor 0.** `vertex.py:768-841` — every
branch replays from the beginning: `store.replay_cursor(0)` (:812),
`store.since_raw(0)` (:821), `store.since(0)` (:839). Boundaries are
suppressed during replay via `_replay_guard` (detaches every descendant's
store and sets `_replaying=True`, vertex.py:740-766); `receive()` returns
early before boundary evaluation when `_replaying` (vertex.py:590-592).

**An incremental-replay helper exists but is orphaned.**
`libs/engine/src/engine/replay.py:17-33`:

```python
def replay(vertex: Vertex, store: "Store[Fact]", *, from_cursor: int = 0) -> int:
    """Replay stored facts into vertex, return cursor position after replay.
    ...
        from_cursor: Start from this position (for incremental replay)

    Returns:
        Cursor position after replay (store.total)
    """
    for fact in store.since(from_cursor):
        vertex.receive(fact, grant=None)
    return store.total
```

It is exported (`engine/__init__.py:38,111`) but has **zero production
callers** in libs/ or apps/ (grep: the only "replay" import hit is
`loops.provenance.replay_attribution`, an unrelated function). Note also
its semantics differ from `Vertex.replay()`: it routes through
`vertex.receive()`, which — outside `_replay_guard` — would RE-APPEND every
fact to an attached store and fire boundaries. As written it is only safe
on storeless vertices. It is a signature sketch, not a working incremental
refresh.

### 4.2 SqliteStore — WAL, cursors, ordering

WAL is on and persistent (`sqlite_store.py:438-449`):

```python
        if is_new:
            # New DB — set WAL (persistent) and synchronous, create schema
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.execute("PRAGMA synchronous=NORMAL")
            for stmt in _SCHEMA_STMTS:
                self._conn.execute(stmt)
            self._sync_set = True
        else:
            # Existing DB: skip schema + pragmas — WAL is persistent,
            # schema already exists, first real query triggers schema load.
```

Module docstring (:7): "Uses WAL mode for concurrent reads during folds."
Each `append` commits immediately (`sqlite_store.py:516-522`:
`INSERT INTO facts ... ; self._conn.commit()`). Read side: `StoreReader`
opens its own connection with `PRAGMA query_only=ON` and a 5s busy
timeout (store_reader.py:21-31) — so multi-process writer+readers already
compose at the SQLite layer; the waste is all above it.

**Rowid-cursor primitives already exist** on the store:

- `since(cursor)` — "Return events with rowid > cursor" (:867-875)
- `since_raw(cursor)` — payload-only variant (:894-918)
- `replay_cursor(cursor)` — streaming generator (:920-936)
- `total` — `SELECT COUNT(*) FROM facts` (:967-971); the `Store` protocol's
  cursor position (`replay()` in replay.py returns `store.total`)

The WAL-incremental fix-shape ("replay facts since last seen rowid") is
therefore one missing *composition*, not missing store machinery.

**Ordering caveat the design session must resolve** — the cursor is rowid
but the fold order is not. `since_raw` docstring
(sqlite_store.py:902-906):

```
FOLD REPLAY ORDER is (ts, id) — event order, deterministic across
custody contexts, so merge(A,B) and merge(B,A) re-fold to the same
state. Witness order (rowid) remains the chain/window authority;
the two orders answer different questions (see ORDERING AUTHORITY
on append_tick).
```

All three cursor reads SELECT `WHERE rowid > ?` but `ORDER BY ts, id`
(:873, :909, :931). An incremental refresh that applies "facts since last
rowid" on top of an existing fold assumes new arrivals sort *after*
everything already folded — false for a late-arriving fact carrying an old
event `ts` (the exact case the ORDERING AUTHORITY comment block documents
for tick windows, sqlite_store.py:61-77: "late arrival — a
backfilled/synced fact honestly carrying an old event timestamp"). Upsert
folds are last-write-wins by replay position, so an out-of-order arrival
folded incrementally can produce a different state than a cold full
replay. This tension between the friction's fix-shape and the engine's
declared fold-order authority is unresolved anywhere in the sources
surveyed; it directly couples this design session to the 0.8.0 session-1
cursor-axis question (ts vs witness-order vs tick-anchor).

### 4.3 Change-feed / notification primitive — none

Grep across `libs/` for `update_hook`, `data_version`, `inotify`,
`watchdog`, `kqueue`, `fsevents`: zero hits. There is no
subscription, wake, or change-notification primitive anywhere in the
engine. The only incremental-tail primitive is for JSONL files, not
SQLite — `libs/engine/src/engine/tailer.py:1-12`:

```python
"""Tailer: reads JSONL files, tracks position, returns new events on poll.

The inverse of FileWriter. FileWriter appends events to a JSONL file.
Tailer reads events from a JSONL file.

Tracks byte offset so it can:
  - Replay from beginning (or any offset) to catch up
  - Poll for new lines efficiently (seek to last position, read what's new)
  - Resume after restart (persist offset externally if needed)

Composable: poll() returns events, caller decides where they go.
"""
```

Its `poll()` (tailer.py:46-85) is non-blocking, offset-tracked, and leaves
incomplete trailing lines for the next poll — the byte-offset analogue of
the rowid cursor Watch's "subscribe: tail the append log from seq 142
onward" asks for.

### 4.4 How a fold refresh happens today — full replay, per call

The sole read interface is `vertex_reader.py` ("The sole read interface
for store data", :3). Every call re-does everything. `vertex_read`
(vertex_reader.py:686-774), simple-store branch:

```python
    ast = load_declaration(vertex_path)
    specs = compile_vertex(ast)
    ...
    with StoreReader(store_path) as reader:
        result = {}
        for kind, spec in specs.items():
            facts = reader.facts_by_kind(kind)
            ...
            result[kind] = spec.replay(payloads)
        return result
```

`facts_by_kind` is an all-rows-of-kind query (store_reader.py:459-468:
`SELECT ... FROM facts WHERE kind = ? ORDER BY ts, id`), and
`spec.replay(payloads)` re-folds from the initial state. `vertex_fold`
(the typed variant the CLI uses, vertex_reader.py:892-1043) has the same
shape. The CLI's `fetch_fold` (apps/loops/src/loops/commands/fetch.py:100-142)
is a thin wrapper over `vertex_fold` — one full parse+compile+open+replay
per invocation, which is exactly what the interactive-read-path doc's
"every fetch_* re-parses the .vertex, recompiles specs, reopens the store"
describes. There is no cached FoldState, no partial re-fold, no
fold-since-cursor anywhere.

### 4.5 Doc drift found while verifying (flagged, not editorial)

- `libs/engine/CLAUDE.md` Level 0 documents `program.collect(rounds=1)`
  and `async for tick in program.run()`. Neither method exists:
  `VertexProgram` has only `receive`, `close`, `sync`/`sync_async`
  (program.py:32-158), and no `def collect`/`def run` exists anywhere in
  `libs/engine/src/engine/` (grep verified).
- `decision:design/daemon-as-vertex-lifecycle` (2026-03-10) asserts "The
  vertex runtime (Vertex.run) already has a persistent loop — CLI runs it
  one-shot." No `Vertex.run` exists today. The decision's *principle*
  ("Daemon is a vertex property, not app infrastructure ... same engine,
  different lifecycle") may still be live; its mechanism claim is stale.

---

## 5. The store's design record (for citation in session 2)

- `friction:no-daemon-shaped-store-access` (open, 2026-07-16) — the
  canonical statement + fix-shape; quoted in full at §1.4.
- `observation:architecture/daemon-access-serves-tui` (2026-07-17) —
  the three-consumers convergence + sequencing implication; §3.2.
- `friction:no-conditional-emit` (open, 2026-07-14) — CAS
  `receive(fact, expect=...)`; a sibling need any long-lived-handle API
  should at least not foreclose; §1.4.
- `decision:design/roadmap-060-static-honest-wave` — "TUI shell + shared
  temporal cursor (Rewind/Watch as ONE abstraction)"; the corpus pointer.
- `thread:080-design-wave` (open) — session order: "grounding dossier ->
  design sessions 1-4 in forced order (cursor axis w/ Go-vector oracle
  check inside; **daemon-shaped access**; TUI integration; Digest)".
- `thread:daemon-as-new-lib` (parked 2026-04-28) — the maximal daemon
  vision (UDS transport, thin-client CLI, driver host, subscribe
  protocol, vertex registry; naming candidates hearth/keep). Explicitly
  parked; the current friction's fix-shape is the narrow subset
  (long-lived handle + WAL-incremental refresh + receive-without-reload).
  Its dissolution list is still the best inventory of what a daemon would
  absorb: "uv-install-on-every-emit ... vertex program cache (load once,
  fold in memory, replay never re-runs per emit; per-fact cost ms not
  seconds); notify/wake substrate ... cross-process boundary
  deduplication ... streaming subscription model becomes natural."
- `decision:design/daemon-as-vertex-lifecycle` (2026-03-10) — daemon as
  lifecycle property, not infrastructure (mechanism claim stale, §4.5).
- `paradigm/boundary-as-watcher-triple` (2026-04-28) — boundary = (watched
  state, driver, fire-condition); notes "dispatch is per-program ...
  only 'run cadenced sources' remains — and that itself is the cadence
  driver firing, which dissolves further if a daemon hosts drivers
  continuously."

## 6. Summary table — what each consumer needs vs. what exists

| Need | ticked (§1) | Watch (§2) | TUI (§3) | Exists today |
|---|---|---|---|---|
| Long-lived handle | forced to fresh-load per write | implied by "stays open" | held-open StoreReader ask | `VertexProgram` holdable; every consumer opens fresh |
| Incremental read ("since last rowid") | fix-shape in friction | "subscribe: tail the append log from seq 142 onward" | "eager fold paid once" + lazy per-entity | `since/since_raw/replay_cursor(cursor)` on SqliteStore; `Vertex.replay()` hardcodes 0; orphaned `engine.replay(from_cursor=)` helper |
| receive() without reload | fix-shape in friction | n/a (read-only) | n/a (read-only) | true within one handle; defeated by multi-writer staleness (no refresh) |
| Change notification / wake | 2s sleep-poll | "on append: apply → diff → emit" | "rows lighting as facts land" | none (no update_hook/data_version/fs-watch); JSONL `Tailer.poll()` only |
| Changed-rows diff out of the fold | n/a | "changed rows only, not the whole fold" | Rewind two-cursor `--diff` | none at fold layer |
| Coalescing / backpressure | n/a | "<200ms coalesce; batches, never drops a fact" | frame-rate concern | none |
| Multi-writer safety on refresh | WAL + advisory `.close.lock` + CAS friction | n/a | n/a | WAL yes; CAS no; tick-chain fork guarded only by consumer lock |
| Signer freshness across handle life | per-write signer rebuild (tasked lesson) | n/a | n/a | signers injected at load; no rotation path on a held handle |

## 7. Requirements, shared primitive, and open questions

### (a) Exact requirements imposed by each consumer

**ticked / tasked daemon poll**

1. Keep one compiled/materialized vertex open across cycles instead of paying
   declaration parse, pin verification, compilation, store open, and
   full-history replay for every read and emit. This is the direct remedy for
   the measured 4–8 full replays per ticked cycle
   (`store-dumps/frictions.txt:91`; ticked runner call sites in §1.2).
2. Refresh the in-memory fold from writes made by *other* processes, from a
   durable cursor, without treating process memory as the coordination
   authority. The store remains the only coordination channel
   (`/Users/kaygee/Code/loops-tasks/src/ticked/runner.py:1-9`).
3. Let the same current handle receive and fold its own writes, returning the
   existing `Receipt`, without reopening. This already works for local writes
   (`libs/engine/src/engine/program.py:81-109`); the missing half is refreshing
   before decisions in a multi-writer store.
4. Preserve correct boundary/tick behavior while applying external facts:
   catch-up must not re-append historical facts or duplicate live boundary
   fires (`libs/engine/src/engine/vertex.py:740-766,768-890`).
5. Do not freeze signer/key state for the handle lifetime. tasked records the
   observed failure explicitly: a cached signer missed post-start key creation
   or rotation (`/Users/kaygee/Code/tasked/src/tasked/substrate.py:99-108`).
6. Separately, task reaping needs conditional emit/CAS. This is related but is
   **not supplied merely by incremental refresh**: the race remains between a
   refresh/read and the append (`store-dumps/frictions.txt:213`).

**Watch change detection**

1. Start at a durable append-sequence cursor and continue from it: “tail the
   append log … from seq 142 onward”
   (`~/Downloads/Terminal UI for loops/Watch View.dc.html:66-68`).
2. On every append, incrementally apply the fold and report the affected
   derived rows, not the whole fold: “apply → diff → emit … changed rows only”
   (`Watch View.dc.html:69`).
3. Coalesce bursts shorter than 200 ms before delivery
   (`Watch View.dc.html:70`).
4. Provide lossless backpressure: batch a slow consumer and never drop a fact
   (`Watch View.dc.html:71`).
5. Detach cleanly without mutating the store (`Watch View.dc.html:72`).
6. Share the temporal cursor model with Rewind; Watch is HEAD-following, not a
   separate ordering axis (`Watch View.dc.html:23-26,74`).

**TUI live-refresh**

1. Feed external changes into the painted event loop so the active view marks
   itself dirty and redraws when facts land. The design-wave record names this
   seam explicitly as “external-change feed into Surface”
   (`store-dumps/facts-60d.txt:21`).
2. Pay the eager fold once, then keep a held-open reader/spec cache; do not
   re-materialize the vertex per frame
   (`docs/dev/interactive-read-path-design.md:144-150,176-182`).
3. Re-project sort/since/reconcile/kind facets in memory, with no store access
   or re-fold on keystrokes; only lazy entity details may query the store
   (`interactive-read-path-design.md:50-52,178-186,226-229`).
4. When pinned to HEAD, apply arriving facts and redraw changed state; when the
   temporal scrubber moves backward, stop following HEAD; when it returns to
   now, resume without rebuilding a second watch mechanism
   (`Watch View.dc.html:89`; `store-dumps/facts-60d.txt:10`).
5. Support scoped lanes (`kind`, `observer`, `key`) without losing the shared
   underlying cursor/feed (`Watch View.dc.html:89`).

### (b) What one shared primitive must provide

A single engine-level primitive must be a **long-lived, closeable vertex
session** over the WAL store, not merely a cached `FoldState` and not a new app
daemon. Its minimum contract is:

1. Load/verify/compile/materialize once; own explicit context-manager cleanup.
2. Expose the current typed fold plus a durable, monotonic store cursor.
3. Refresh atomically from that cursor, applying each newly witnessed fact
   exactly once to in-memory projections, including external writers, without
   re-appending it or replaying boundaries as if it were a new local ingress.
4. Accept local `receive()` on the same handle and advance the same cursor, so
   local and external writes cannot be double-applied on the next refresh.
5. Return a lossless change batch containing at least the consumed fact range
   and affected fold addresses/before-after rows. ticked may ignore the diff;
   Watch and the TUI require it.
6. Offer a non-blocking poll/refresh core plus an async/event-loop adapter that
   wakes on change, coalesces bursts, bounds delivery batches, and applies
   backpressure without losing cursor continuity.
7. Recover after disconnect/restart from the durable cursor, and detect cursor
   invalidation rather than silently skipping or duplicating facts.
8. Define signer/key refresh for a held writer and preserve WAL multi-process
   concurrency. CAS can compose beside this API but must be transactional at
   append time, not simulated by refresh.

The existing pieces are close but uncomposed: `VertexProgram` supplies
lifecycle and local receive (`program.py:32-130`); `SqliteStore` supplies WAL
and rowid-filtered reads (`sqlite_store.py:435-449,867-936`); `Tailer` supplies
the shape of offset-tracked non-blocking polling for JSONL
(`tailer.py:23-89`). None supplies the cross-process live session or its change
batch.

### (c) Open questions

1. **Ordering authority:** can a rowid tail be incrementally folded while cold
   replay remains ordered by `(ts, id)`? A late-arriving old-timestamp fact can
   make incremental and cold folds diverge (`sqlite_store.py:894-936`). Must
   0.8.0 choose witness order for live folds, buffer/replay an affected suffix,
   or define another cursor/order relation?
2. **Cursor identity:** is the public cursor a rowid, fact id resolved to rowid,
   `(ts,id)`, or tick anchor? This is the unresolved session-1 axis explicitly
   upstream of “Watch's seq-N tail” (`store-dumps/facts-60d.txt:10`).
3. **Change granularity:** should refresh return facts, changed loop names,
   changed fold keys, typed before/after `FoldItem`s, or a general patch? Watch
   requires changed rows; ticked needs only current state.
4. **Notification transport:** SQLite has WAL but no cross-process callback in
   this engine. Is the first contract timed `poll()` over rowid/data-version,
   filesystem/WAL watching, an IPC broker, or pluggable wake strategies? The
   correctness contract must not depend on notifications: wake may coalesce,
   cursor catch-up must remain lossless.
5. **Transaction boundary:** how are a fact append and any boundary tick exposed
   as one observed change when the engine currently commits them separately?
   The consumer-side `.close.lock` proves the race is real
   (`/Users/kaygee/Code/loops-tasks/src/ticked/vertex.py:205-228`).
6. **Boundary catch-up:** should external facts ever fire a boundary in the
   refreshing process, or is the writer solely responsible? How is crash
   recovery handled without duplicate ticks?
7. **Signer rotation:** should a session reload signers per write, receive a
   signer provider, or expose explicit credential refresh?
8. **Declaration drift:** if the `.vertex` file or absorbed declaration state
   changes while a session is open, can specs be hot-swapped safely, or must the
   session report “reload required” and establish a new cursor/fold epoch?
9. **Multi-store vertices:** what does one cursor mean across `combine` or
   `discover` stores, and how are independent WAL feeds merged without losing
   each store's witness order?
10. **Backpressure bounds:** Watch says “batches · never drops a fact,” but no
    maximum latency, memory bound, or slow-consumer policy is specified
    (`Watch View.dc.html:71`). Which resource is bounded, and what signal tells
    the consumer it must catch up from the cursor?
