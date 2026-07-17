# Session 2 design advice — daemon-shaped engine access

*2026-07-17. Independent advisor: Codex. Grounded in
`dossier-daemon-seams.md`, then amended by the ratified-pending A1/A7 contract
in `s1-arbitration.md`.*

## Recommendation

Ship an **in-process, long-lived `VertexHandle` per consumer process**, not a
separate daemon. The handle is a lifecycle and consistency boundary around a
held declaration/compile plan, SQLite connection(s), current immutable
snapshot, facts-only witness cursor, tick-table cursor, and change iterator.
`ticked`, Watch, and the TUI should all consume this one contract.

SQLite supplies durable catch-up, not cross-process callbacks. Use
`PRAGMA data_version` on one held connection as a cheap invalidation hint, then
confirm and consume change with cursor-bearing `facts.rowid` and `ticks.rowid`
queries. A 50 ms version probe plus a 200 ms trailing-edge coalescer is the
honest 0.8.0 transport. It is polling at the lowest layer; the contract above it
is eventful because consumers wake only for committed change and derive from a
lossless WAL-backed cursor. Watching the `-wal` file is not a correctness
mechanism.

Most importantly, **WAL-incremental means incremental discovery, not blindly
incremental folding**. A1 makes the facts rowid/ordinal the Watch cursor; A7
keeps full reconstruction of each delivered coalesced group as the semantic
contract. Every refresh selects the newly witnessed prefix and reconstructs it
in `(ts, id)` order. Built-in folds may optimize that reconstruction with
insertion-aware checkpoints, but the result must equal a cold replay.

This adds no tables, columns, triggers, or broker. It consumes the session-1
cursor decision; it does not amend the storage protocol.

## Binding interpretation

The three orders/identities must remain separate:

1. `facts.rowid` is the private, per-store facts-only detection cursor and the
   source of Watch's displayed receipt sequence. It includes visible domain
   facts and `_decl.*` control receipts.
2. `(ts, id)` is the replay order for the selected fact set. It is never
   replaced by rowid order on a live handle.
3. `ticks.rowid` is a second private catch-up cursor. A tick can wake a consumer
   and render an anchor, but does not advance the facts witness position. There
   is no invented cross-table arrival order in 0.8.0.

The serializable/canonical position identity is the lineage-qualified
`fact_id`; `seq` is its per-store rowid-derived display ordinal and in-process
tail offset. It is not promised to survive rebuild/slice/merge. Code resolves
an id by primary-key lookup and never orders or parses mixed-era ids.

A declaration ceremony is one atomic receipt group because SQLite reveals its
rows only after the ceremony transaction commits. A delivery batch may coalesce
several committed groups. Its state diff is from the state before that batch to
the full reconstruction at its ending facts position; Watch still receives the
individual receipt/control records inside the batch.

## Proposed API

The public name should be `open_vertex`, leaving `load_vertex_program` as the
explicit one-shot primitive. The sketch is Python-shaped, but the types and
failure semantics are the contract rather than bikesheddable spelling.

```python
from collections.abc import AsyncIterator, Iterator, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Protocol

@dataclass(frozen=True)
class WitnessPosition:
    lineage: str | None       # store lineage when historized
    seq: int                  # inclusive facts.rowid-derived display ordinal
    fact_id: str | None       # canonical identity at seq; None at empty

@dataclass(frozen=True)
class AggregatePosition:
    members: Mapping[str, WitnessPosition]  # stable member id -> position

@dataclass(frozen=True)
class ReceiptEvent:
    seq: int
    fact_id: str
    kind: str
    ts: float
    observer: str
    origin: str
    payload: Mapping[str, object]
    control: bool             # True for _decl.*; never silently hidden

@dataclass(frozen=True)
class TickEvent:
    tick_seq: int             # ticks.rowid, explicitly not a fact seq
    tick_id: str
    name: str
    tick: Tick

@dataclass(frozen=True)
class FoldAddress:
    kind: str
    key: str | None           # None means a non-keyed/whole-section fold

@dataclass(frozen=True)
class RowChange:
    address: FoldAddress
    before: FoldItem | None
    after: FoldItem | None

@dataclass(frozen=True)
class VertexSnapshot:
    position: WitnessPosition | AggregatePosition
    fold: FoldState
    state_by_kind: Mapping[str, object]
    generation: int           # process-local successful-swap generation
    ontology_epoch: str       # resolved declaration-content digest
    tick_seq: int

@dataclass(frozen=True)
class ChangeBatch:
    before: WitnessPosition | AggregatePosition
    after: WitnessPosition | AggregatePosition
    receipt_ranges: tuple[tuple[str, int, int], ...]  # member, first, last
    receipts: tuple[ReceiptEvent, ...]
    ticks: tuple[TickEvent, ...]
    rows: tuple[RowChange, ...]
    ontology_changed: bool
    tick_arrived: bool
    visible_domain_count: int
    replay_mode: Literal["full", "checkpoint-suffix", "tick-only"]
    catching_up: bool
    oversized_group: bool

@dataclass(frozen=True)
class ReceiveResult:
    receipt: Receipt
    change: ChangeBatch | None  # None when ingress was rejected/not stored

class CredentialProvider(Protocol):
    def for_write(self, vertex: Path) -> WriteCredentials: ...

def open_vertex(
    vertex: Path,
    *,
    validate_ast: bool = True,
    credentials: CredentialProvider | None = None,
) -> VertexHandle: ...

class VertexHandle:
    @property
    def snapshot(self) -> VertexSnapshot: ...

    def refresh(self, *, force: bool = False) -> ChangeBatch | None: ...

    def receive(
        self,
        fact: Fact,
        grant: Grant | None = None,
        *,
        expect: FoldExpectation | None = None,
        id_override: str | None = None,
    ) -> ReceiveResult: ...

    def changes(
        self,
        *,
        poll_interval: float = 0.050,
        coalesce: float = 0.200,
        max_latency: float = 0.500,
        max_receipts: int = 1_000,
        max_bytes: int = 8 * 1024 * 1024,
    ) -> Iterator[ChangeBatch]: ...

    def changes_async(self, **policy) -> AsyncIterator[ChangeBatch]: ...
    def close(self) -> None: ...
    def __enter__(self) -> "VertexHandle": ...
    def __exit__(self, *exc: object) -> None: ...
```

`FoldExpectation` belongs to the sibling conditional-emit/CAS design. Naming
the seam here prevents the handle from foreclosing it; implementing a refresh,
compare, then append sequence would **not** be CAS and is forbidden.

### Core method semantics

**Open.** `open_vertex` parses, pin-verifies, compiles, opens the store, captures
its file identity and lineage, and cold-reconstructs once. It publishes no
snapshot until all of that succeeds. The snapshot is immutable/detached so a
TUI can paint it without holding a database transaction.

**Refresh.** `refresh()` is synchronous and non-waiting in the subscription
sense; it may perform reconstruction work. In one short SQLite read
transaction it captures the facts and ticks heads, fetches rows after the two
private cursors with their rowids, and closes the transaction. It then builds a
candidate snapshot off to the side. On success it atomically swaps runtime,
snapshot, and cursors, then returns the diff. On failure it advances neither.
External facts are replayed under the existing replay guard: they are never
re-appended and never fire boundaries in the reader.

If there are only new ticks, refresh updates `tick_seq`, returns a `tick-only`
batch, and does not refold. If any `_decl.*` receipt arrives, it is a visible
control event and invalidates the compiled epoch. The handle resolves the
declaration at the ending witness prefix, re-runs pin verification, recompiles,
discards old checkpoints, and reconstructs all selected domain facts before it
can publish. A no-op or foreign declaration still takes this conservative path;
the contract does not let an apparently inert control receipt bypass ontology
validation.

**Receive.** A write first catches the handle up, obtains signers from
`CredentialProvider.for_write()` at the moment of the write, and calls the live
receive path exactly once. The writer remains the only process that may fire
and persist a boundary. The handle then captures the fact/tick rowids and
reconstructs the canonical `(ts,id)` snapshot before returning
`ReceiveResult`. This includes external writes that raced between pre-refresh
and append, and prevents the local fact from being applied again on the next
refresh. A locally backdated fact therefore cannot leave the published handle
state in live-tail order.

A gate rejection returns the existing `Receipt(stored=False)` and
`change=None`. If the fact commit succeeds but boundary/tick persistence then
raises, the handle catches up in `finally` and raises a named
`ReceiveCommittedError(fact_id, change, cause)`. The caller must be told that
the fact landed even though the compound live operation failed; retrying it as
if nothing committed would duplicate data.

Pre-refresh does not make the live boundary decision serializable: another
writer can commit between catch-up and this append. The post-write snapshot is
canonical, but a boundary may already have evaluated against the earlier
state. Closing that window requires the sibling transactional receive/CAS and
fact-plus-tick work; this handle must not claim to have done so. Ticked's close
lock remains until then.

Credential lookup per write is mandatory: tasked has already demonstrated that
caching signer callables for the handle lifetime wedges a process after key
creation or rotation. The current `SqliteStore` constructor-injected signers
must become operation-fresh providers or explicit per-write overrides.

**Changes, not callbacks.** Prefer pull iterators to `subscribe(callback)`.
They give natural backpressure, propagate consumer exceptions normally, and do
not execute foreign code while the handle lock is held. A slow consumer does
not require an unbounded in-memory event queue: the WAL is the queue. The
adapter retains at most a dirty bit/head watermark, and the next iteration
catches up from the durable cursor. `max_receipts` splits a backlog at receipt-
group boundaries; each yielded chunk is independently reconstructed and no
receipt is dropped. `max_bytes` is also a delivery bound, but one indivisible
ceremony may exceed it; that batch sets `oversized_group=True` rather than
splitting or dropping the ceremony.

The coalescer starts on the first detected commit, waits for 200 ms of quiet,
and has a 500 ms cap so a continuous writer cannot starve display. These are
delivery defaults, not cursor semantics. `close()` is idempotent, terminates
iterators, and a later method call raises `HandleClosed`.

The handle serializes `refresh()` and `receive()` and permits one active change
iterator. Snapshot values are immutable and may be handed to the painter.
Multiple independent subscriptions use independent handles/cursors rather than
callbacks racing over one mutable runtime.

## Answers to the design questions

### 1. Process model

Use one in-process handle in each process. `ticked` is already a service and
needs no second service merely to read its database. The TUI is a foreground
process that needs immutable snapshots in its own paint loop. Watch is either a
CLI mode or a TUI view and benefits from direct typed changes, not serialization
through IPC.

A separate daemon would add service discovery, startup ordering, authentication,
protocol versioning, snapshot serialization, signer custody across a process
boundary, and another failure domain. It would still need to detect SQLite
changes made by non-daemon writers. Nothing among the three consumers requires
remote access, a shared driver host, or cross-machine fan-out. Those would be
valid future reasons to revive the parked UDS daemon, but are not reasons to
make the 0.8.0 handle remote. This validates both “orchestration dissolves
daemon” and the older “daemon as vertex lifecycle” principle without relying
on the stale claim that `Vertex.run()` exists.

### 2. Cross-process SQLite change detection

The existing pieces have narrower meanings than their names may suggest:

- `EventStore.version` is documented as “Bumped on each append. Use to detect
  new events.” It is a Python integer on one `EventStore`; another process
  cannot mutate it and it cannot wake anything.
- `Projection.advance(store)` executes `store.since(self.cursor)`, applies each
  event, increments `cursor`, and swaps state once. It is O(new events), but it
  assumes the store's cursor order is valid incremental fold order. That is
  true for its in-memory stream model and false for a SQLite backdated arrival
  under this engine's `(ts,id)` replay contract. It can be used inside a proven
  append-at-event-tail optimization, never as generic handle semantics.
- SQLite's `PRAGMA data_version` changes between two reads on the **same held
  connection** when another connection, including one in another process,
  commits. It does not change for commits made on that same connection, and
  values from different connections are not comparable. SQLite documents
  exactly those limits in [PRAGMA data_version](https://sqlite.org/pragma.html#pragma_data_version).
  It is therefore an invalidation hint, not a durable position.
- SQLite update/commit hooks are registered on one connection and do not turn
  commits from arbitrary other processes into callbacks on this connection.
- Watching `db-wal` is unsafe for correctness. SQLite may checkpoint, reset,
  overwrite, truncate, create, or delete that file; the main database also
  changes at checkpoint. The [WAL documentation](https://sqlite.org/wal.html)
  explicitly describes reset/reuse and last-connection deletion. Filesystem
  notifications may be an optional latency hint, but a missed notification
  must change nothing except latency.

The relevant current code is narrow and explicit:

```python
# EventStore.append
self._events.append(event)
self._version += 1

# Projection.advance
new_events = store.since(self.cursor)
for event in new_events:
    current = self.apply(current, event)
    self.cursor += 1
```

That is local append counting plus cursor-tail folding; neither part observes
or correctly reconstructs an arbitrary cross-process backdate by itself.

So 0.8.0 should poll `data_version` cheaply on a held connection, and on a
change query explicit heads plus `rowid > cursor`. The same-connection local
write path marks itself dirty because `data_version` deliberately will not.
The cheap probe also compares a cached declaration-dependency stamp
(vertex file plus pinned sources); a stamp change forces content hashing and a
recompile attempt even if SQLite did not change. Filesystem notification may
reduce that latency but remains hint-only.
This is honestly “cheap polling for a committed-change event,” not native
SQLite pub/sub. It satisfies the paradigm at the architectural boundary:
consumers respond to derived changes rather than scheduling full reloads.

### 3. Refresh and ontology semantics

`SqliteStore` needs cursor-bearing methods; the current `since*()` methods
filter by rowid but discard it, while `total` is `COUNT(*)`. Add internal
methods shaped like:

```python
def fact_head(self) -> FactHead: ...       # MAX(rowid), id, count
def facts_after(self, rowid: int, *, through: int) -> list[StoredFact]: ...
def tick_head(self) -> TickHead: ...       # MAX(rowid), count
def ticks_after(self, rowid: int, *, through: int) -> list[StoredTick]: ...
```

Never synthesize a next cursor from count. The returned `StoredFact` includes
both rowid and full fact metadata. Selection is rowid; reconstruction queries
the whole selected prefix in `(ts,id)` order or restores a valid prefix
checkpoint and replays an insertion-aware suffix.

Receipt-group labels are derived without schema: an ordinary append is its own
group; contiguous `_decl.*` rows sharing the ceremony's effective timestamp are
one group under A2. Head/`facts_after` capture must not split that span. If the
ending row lies inside one, extend through the committed ceremony before
publishing; user addresses inside it remain errors per session 1.

The published snapshot is all-or-nothing. `_decl` arrival or a changed vertex/
pinned-source fingerprint forces recompile. `SourceDrift`, an unsupported
declaration protocol, a half-resolvable aggregate, or a raising fold leaves the
handle in `INVALIDATED` with its last-good snapshot retained only for diagnostics;
normal `snapshot`, `receive`, and change delivery fail closed until a successful
refresh/reopen. Silently serving the old ontology is not allowed.

### 4. Change payload and coalescing

The minimum useful event is the proposed `ChangeBatch`, not a boolean dirty
flag. It carries:

- inclusive receipt range(s) and every receipt, including visible `_decl`
  controls;
- before/after witness positions and the cumulative visible-domain count, so
  Watch can render both `seq N` and “visible N” without pretending they match;
- structural changed rows as typed before/after values;
- an ontology-change flag and an explicit tick list/flag;
- replay mode and catch-up status for performance/honesty diagnostics.

An ordinary fact that leaves the fold unchanged still produces a receipt
event. An ontology receipt that changes no rows still produces a control event.
A tick-only commit still wakes Watch/TUI but does not move the facts position.
Because facts and ticks have separate rowid domains, their relative order inside
one refresh is disclosed as unknown; the batch must not sort them into a fake
global sequence.

The 200 ms rule is a delivery debounce. A batch's row diff is the structural
difference between two complete reconstructions, not a promise that each fact
was O(1)-applied. Receipt ceremonies are never split. A large catch-up may be
split only between groups and advertises `catching_up=True`.

### 5. Aggregate vertices

The contract composes, but not as five independently folded `VertexProgram`s.
An aggregate fold is over the union of member facts sorted globally by
`(ts,id)`; combining already-folded member states is generally invalid.

`open_vertex(combine_vertex)` should therefore return the same public handle
shape backed by:

1. one light tail/signal connection per current member store;
2. an `AggregatePosition` vector of member witness positions and tick cursors;
3. one cached aggregate declaration/spec plan; and
4. one combining projector that reconstructs the union and computes one row
   diff when any member advances.

In 0.8.0, be honest: member **detection** is WAL-incremental, but aggregate
state may continue to use a full `_combined_read`-shaped refetch/refold once per
coalesced batch. Five stores make that bounded and it preserves correctness.
It still removes declaration reparse/recompile per frame and eliminates idle
full reloads. Aggregate checkpointing can follow measurements.

Aggregate positions are vectors per A9. `seq:` and `fact:` addressing on the
aggregate are refused; a change names the member that advanced. Membership is
current-file `aggregate-head`, not historical. A membership edit rebuilds the
vector and full aggregate state and emits an ontology/membership control. A
storeless aggregate's `receive()` raises `ReadOnlyAggregate`; write-target
resolution remains a separate app/Digest concern.

### 6. Backdated arrivals and the 100k budget

The safe first implementation is a staged full refold. It is necessary but not
sufficient as the permanent hot path. On this checkout's existing engine
benchmark, replay plus boundary reconciliation for 5,500 facts measured about
63.5 ms on the advisor run; naïve linear extrapolation does not establish a
sub-second 100k result and certainly does not establish “much less than one
second” at five deliveries per second.

Use this optimization ladder, with cold replay equivalence tests at every rung:

1. Cache KDL parse/pin verification/compiled specs for the ontology epoch.
2. Keep fact metadata in an in-memory `(ts,id)` search index. For a new batch,
   find its earliest insertion key.
3. Keep a byte-bounded, small set of replay-prefix checkpoints only at receipt-
   group boundaries, keyed by ontology epoch and event-order key. Restore the
   newest checkpoint strictly before the earliest insertion, invalidate all
   later checkpoints, and replay the suffix including the new rows.
4. Treat the previous head as a checkpoint for the common event-tail append;
   this reduces an ordinary refresh to new facts without claiming that all
   arrivals are tail appends.
5. Discard every checkpoint on ontology change. Use in-memory checkpoints only
   in 0.8.0; persistent cache format/versioning is unjustified scope.

This is feasible for built-in declarative folds because their states are
deterministic plain data, but it is not universally free. Custom fold overrides,
routes/children, parse pipelines, and very large growing fold states need a
capability-tested `snapshot/restore`; otherwise the handle falls back to full
reconstruction. Bound checkpoints by bytes (for example 64 MiB) and count (for
example eight, selected geometrically/LRU), not “one full state every 4k facts,”
which can become quadratic memory.

No generic checkpoint can make an adversarial insertion before the first
checkpoint sublinear. The acceptance budget should distinguish ordinary and
exceptional paths on a checked-in 100k fixture: p95 no-change probe under 1 ms;
p95 1–100 event-tail facts under 250 ms; hard target under 1 s for a genesis-
backdate or ontology full rebuild. If the last target misses, optimize the full
replay fast path before calling the slice done; do not weaken A7.

### 7. What ticked deletes, and what remains

Today one idle cycle performs a full `fold`, possibly another after reconcile,
one fresh fold per `_still_running`, a full epoch tick scan, fresh
load/compile/replay per emit, and another fold in drain mode. With the handle:

- `Runner` owns one context-managed handle for its lifetime.
- `cycle()` receives one immutable snapshot. `views`, drain checks, and
  `_still_running` read it; the latter ultimately becomes transactional
  `receive(..., expect=...)`, not a fresh read that only narrows the race.
- `ReceiveResult` returns only after `handle.snapshot` is the post-write
  canonical snapshot, so reconcile does not reload.
- the handle's tick cache replaces `_closed_task_names()` scanning ticks from
  epoch zero;
- all emits use the held compile/runtime and operation-fresh signers;
- the fixed 2 s **store replay poll** becomes `changes()` plus a timeout at the
  nearest deadline derived from facts (claim grace, work timeout).

The last timeout matters. A detached worker can die without emitting a terminal
fact, so a store-only subscription cannot wake the reaper. Ticked may retain a
derived liveness deadline or add SIGCHLD/process supervision; retaining a cheap
PID check is honest, retaining full store replay on that timer is not.

What remains is ticked's domain work: policy/routing, state-machine decisions,
worker spawn/supervision, reconciliation, human escalation, and output. The
engine handle is not an orchestrator daemon.

For tasked, the store-path `Store` wrapper can delete after both this handle and
transactional conditional emit land. Its domain helpers (`split_refs`, observer
naming, bool/string validation) either remain in ordinary tasked modules or
move; they are not reasons to preserve a substrate wrapper. The handle alone
does not close the dead-worker lost-update race.

### 8. Protocol/oracle and downstream coordination

This work does **not** change schema. Facts/ticks rowids already exist; new
queries expose them inside the engine. `data_version`, declaration fingerprints,
in-memory checkpoints, and change batches are runtime concerns. No trigger,
global sequence table, receipt timestamp, or tick column is smuggled in.

Session 1 still owns witness-position selection, lineage-qualified public
handles, receipt-group resolution, and its Go vectors. The future
`GlobalReceiptPosition` covering facts plus ticks remains a protocol/oracle
amendment and is explicitly not required here. The handle must consume A1–A13,
especially A1, A2, A7, A9, and A10, but adds no new conformance format.

Session 3 is constrained to paint immutable snapshots and apply `RowChange`s
outside `render()`. HEAD-following uses this iterator. Rewind may pause delivery
and later catch up, or keep a separate head snapshot warm; it must not invent a
second watcher. Aggregate TUI state carries member vectors and the
`aggregate-head` honesty marker.

Session 4 may use a writable target handle for the final Digest append and a
read handle for its source window, but this design does not create a distributed
transaction between vertices, choose Digest's target, or settle authorization.
Fresh credential lookup and `ReceiveResult` help; cross-vertex routing,
Peer/Grant convergence, tick lineage, and Digest CAS/idempotency remain session-4
questions. A Digest append is simply another receipt observed by Watch.

## Failure modes and required behavior

| Failure | Required behavior |
|---|---|
| `SQLITE_BUSY`/locked during head capture or replay | Retry with bounded backoff in `changes()`; direct `refresh()` raises `StoreBusy`; never advance either cursor. |
| Store file replaced, lineage changed, head rowid regressed, or cursor id no longer resolves | Raise `CursorInvalidated`/`StoreReplaced`; close and explicit reopen/full bootstrap. Never silently reinterpret the old cursor. Capture `(device,inode)` as well as lineage where available. |
| Filesystem/WAL notification lost | At worst adds `poll_interval` latency; the next `data_version`/head probe catches up from rowid. Correctness is unchanged. |
| `data_version` changes but facts/ticks do not | Treat as a hint-only false positive (schema/meta/FTS may have changed); inspect declaration fingerprint/schema epoch, otherwise return no semantic batch. |
| `_decl` or source-file change cannot compile/verify | Mark invalidated, retain last-good state only for diagnostics, fail normal reads/writes closed, retry on later refresh or reopen. |
| Fold/replay/diff raises | Candidate is discarded; published snapshot and cursors remain paired at the last good generation for diagnostics, and the handle is invalidated until a successful retry/reopen. |
| Writer key rotates or appears | Next `receive` asks the provider again. A signing-floor refusal returns the existing named error and does not publish a fictitious change. |
| Fact commits but boundary tick fails/crashes | Catch the fact up, raise `ReceiveCommittedError` with its id/change, and later deliver any tick separately. Refresh never synthesizes or re-fires the missing tick; existing reconciliation owns the crash window. |
| External commit races between pre-refresh and local append | The final snapshot includes both writes, but current boundary evaluation is not serializable. Preserve existing writer serialization and surface this as the conditional-receive/fact-plus-tick transaction gap. |
| Two writers fork a tick chain | Not solved by read refresh. Existing serialization remains until the write transaction/boundary design fixes it. |
| Consumer is slow | Keep only wake/head state in memory; facts remain in SQLite. Resume from cursor, split only between receipt groups, set `catching_up`; never drop a receipt. One group over the byte cap is delivered whole and flagged. |
| Continuous writer prevents 200 ms quiet | Deliver at `max_latency`, then start a new batch. |
| Aggregate member disappears or membership changes | Emit member/membership control, refuse a silently partial “same aggregate”; rebuild under current membership or surface degraded state explicitly. |
| Checkpoint restore fails or parity assertion differs | Discard checkpoints and full-reconstruct. Checkpoints are disposable optimizations, never authorities. |
| Handle/iterator closes | Detach only; no store mutation. Use-after-close raises `HandleClosed`. |

The runtime assumes the engine's append-only API. Arbitrary out-of-band SQL
updates that preserve row count/head cannot be perfectly detected by a cursor
feed; chain verification remains the tamper/corruption tool.

## Implementation slices and exit criteria

### S0 — cursor-bearing SQLite reads

Add `fact_head/facts_after` and `tick_head/ticks_after`, returning rowids and
bounded through-head snapshots; stop using `COUNT(*)` as a rowid cursor. Add
same-connection `data_version` access and store/file identity capture.

**Exit:** tests prove rowid gaps do not misadvance the cursor; a second process
commit changes `data_version` on the held reader; a same-connection commit is
handled explicitly; facts and ticks remain separate axes; no schema diff.

### S1 — single-store cold handle and atomic snapshot

Introduce `open_vertex`, immutable `VertexSnapshot`, context management, cached
compile plan, staged reconstruction, and full-replay equality with
`vertex_read/vertex_fold`.

**Exit:** for simple, routed, parsed, child, boundary, and backdated fixtures,
the opening snapshot is structurally equal to a cold read; a raising replay
leaks no connection and publishes no partial snapshot; close is idempotent.

### S2 — refresh, declaration epochs, and typed diffs

Consume cursor-bearing groups; add candidate rebuild/swap, `_decl` visible
controls, recompile-on-declaration/source change, tick-only batches, and
row-address diffs. External replay must suppress stores and boundaries.

**Exit:** cross-process domain, backdated, `_decl` ceremony, no-op `_decl`, and
tick-only cases all produce the specified batch; every successful snapshot
equals a fresh cold reconstruction; no external refresh appends a fact or tick.

### S3 — write-through handle and CAS-ready seam

Make credentials operation-fresh, add `ReceiveResult`, catch up before write,
resolve the stored rowid after write, and rebuild before return. Add the
`expect` parameter but land its transaction semantics in the conditional-emit
slice, never as compare-then-append.

**Exit:** local/external racing writes appear exactly once; a backdated local
fact matches cold replay on return; key creation/rotation during one handle
lifetime works; gate rejection has no batch; a forced post-fact tick failure
returns a named committed-fact error and leaves the handle current; existing
`Receipt` fields and boundary dispatch remain intact.

### S4 — change iterators, coalescing, and backpressure

Build sync/async adapters over `data_version` probes, with 50 ms detection,
200 ms quiet coalescing, 500 ms cap, receipt-group-aware chunking, and bounded
wake state.

**Exit:** multiprocess burst tests coalesce without loss; a deliberately slow
consumer catches every seq in order with bounded adapter memory; continuous
writes deliver by the cap; cancellation/`^C` closes cleanly without store
mutation; no-change probes do no refold.

### S5 — replay budget and safe checkpoints

Check in 100k representative built-in-fold fixtures and benchmarks. Add the
event-order insertion index and byte/count-bounded prefix checkpoints behind a
capability gate; invalidate suffixes on backdate and all checkpoints on
ontology change. Keep the full path as fallback.

**Exit:** checkpoint and forced-full results are byte/structurally identical
across randomized backdates and declaration changes; p95 no-change is <1 ms,
ordinary 1–100-tail-fact refresh is <250 ms, and the 100k forced-full hard
target is <1 s on the recorded reference environment. Report, do not hide,
which mode answered.

### S6 — aggregate vector handle

Compose member tail connections plus one aggregate projector; retain current
full union refold per coalesced batch; add membership invalidation and vector
positions. Refuse aggregate scalar addresses and storeless writes.

**Exit:** a five-member fixture wakes for every member, reconstructs exactly as
current `_combined_read`, reports the advancing member/range, never invents
cross-member or fact/tick order, and labels current membership
`aggregate-head`. Idle frames perform no union read.

### S7 — consumer cutover and deletion ratchets

Move ticked's runner/dashboard to one handle, snapshot-driven views, cached
ticks, and change/deadline wake. Then expose the same client seam to tasked;
complete conditional emit before deleting its substrate store wrapper. Session
3 consumes the handle for Watch/TUI rather than building another watcher.

**Exit:** ticked's steady-state call graph contains no cycle-time
`vertex_read`, epoch `vertex_ticks`, or per-emit `load_vertex_program`; an idle
runner performs cheap probes but zero replays; one external task fact wakes and
advances the runner; worker-death reconciliation still occurs at its derived
deadline; tasked's race test passes under transactional expectation before its
wrapper deletion; TUI has one external-change feed seam.

## Bottom line

The missing primitive is not a background process. It is a held, closeable,
recompilable vertex session whose durable source of truth remains SQLite. Its
cursor makes change discovery incremental; A7 makes reconstruction honest;
iterators make delivery eventful; and bounded checkpointing makes the common
case fast without changing the answer. That is one contract for ticked, Watch,
and the TUI, with aggregate and Digest boundaries stated rather than hidden.
