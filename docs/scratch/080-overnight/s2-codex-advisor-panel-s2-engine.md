# Panel review — ENGINE-REALITY lens on s2-codex-advisor.md (VertexHandle)

*2026-07-17. Claude-family skeptic pass, engine-reality lens. Method: every
engine claim re-derived against code (file:line), empirical tests run where
they settle a claim (PRAGMA data_version behavior, benchmark re-run, live
store queries). Verdict: AMEND — the design survives every break attempt on
its core mechanism; three named amendments, none structural.*

## 1. Claims verified against code (each independently re-read, not deferred)

### 1.1 EventStore.version — quote CONFIRMED
`libs/engine/src/engine/store.py:123-126`:
```python
@property
def version(self) -> int:
    """Bumped on each append. Use to detect new events."""
    return self._version
```
Exact docstring match. It is a Python int on one in-process object
(`_version += 1` at store.py:138); the doc's "another process cannot mutate
it and it cannot wake anything" is correct. The doc's inline quote of
`EventStore.append` elides the JSONL file-write between the two lines
(store.py:134-138) — harmless elision, substance accurate.

### 1.2 Projection.advance — quote CONFIRMED, and the doc's caveat is right
`libs/engine/src/engine/projection.py:100-111`: `store.since(self.cursor)`,
per-event `apply` + `cursor += 1`, single identity-checked state swap. The
doc's deeper claim — that `advance` assumes cursor order is valid incremental
fold order, which is false for SQLite backdated arrivals — is correct and
sharper than it looks: `SqliteStore.since(cursor)` selects `WHERE rowid > ?`
but orders `ORDER BY ts, id` (sqlite_store.py:873), so a backdated arrival
(new rowid, old ts) would be applied *after* later-ts facts already folded,
violating the §6.2 `(ts,id)` replay contract. `advance` is only safe under a
proven event-tail condition, exactly as the doc restricts it. Additionally,
`Projection.advance` increments `cursor` by event *count* while
`SqliteStore.since` interprets it as *rowid* — coincidentally aligned only
while rowids are dense; the doc's "never synthesize a next cursor from count"
(S0) forecloses this correctly.

### 1.3 SqliteStore rowid reads and COUNT(*) — CONFIRMED
- `since()` sqlite_store.py:867-892, `since_raw()` :894-918,
  `replay_cursor()` :920-936 — all filter `WHERE rowid > ?` and **discard the
  rowid** from the returned rows. Doc claim exact.
- `total` is `SELECT COUNT(*)` (sqlite_store.py:967-971). Doc claim exact.
- So the proposed `fact_head/facts_after/tick_head/ticks_after` are genuinely
  new surface, not duplication. No conflicting existing methods found.

### 1.4 WAL config — CONFIRMED
`PRAGMA journal_mode=WAL` + `synchronous=NORMAL` set once on new DBs
(sqlite_store.py:440-441); existing DBs rely on WAL persistence (:446-449).
Live store check: `sqlite3 -readonly .loops/data/project.db "PRAGMA
journal_mode"` → `wal`. Also: 3,086 facts with `MAX(rowid) == COUNT(*)` —
rowids dense in the real corpus, as the append-only schema predicts (facts
has `id TEXT PRIMARY KEY`, an implicit-rowid table, sqlite_store.py:270-278).

### 1.5 PRAGMA data_version — EMPIRICALLY CONFIRMED, plus one caveat the doc omits
Ran a two-process WAL test (scratchpad `dv_test.py`, sqlite 3.53.1):

| Scenario | Result |
|---|---|
| Same-connection commit | data_version **unchanged** (2→2) |
| Cross-**process** commit (WAL, autocheckpoint off) | **changed** (2→3) |
| No-change probe | stable |
| Same-process other-connection commit | changed (3→4) |
| **Probe inside a held read transaction, external commit lands** | **unchanged (4→4); only visible after txn close (→5)** |

Rows 1-4 match the doc's claims exactly (including the self-dirty-bit
requirement for local writes — the doc has it). Row 5 is the omission: see
Amendment A. The doc's rejections of update/commit hooks (per-connection
only) and `-wal` file watching (checkpoint reset/truncate/delete) match
documented SQLite semantics; hint-only framing is correct.

### 1.6 Benchmark number — REPRODUCED
`libs/engine/benchmarks/benchmark_vertex_hotpath.py` replay scenario is
2,500×2 received facts + 500 external appends = **5,500 facts**, timing
`reader.replay()` + `reader.evaluate_boundaries()`. My run:
`replay_ms=64.435` vs the doc's "about 63.5 ms" — reproduced. The doc's
skepticism is *understated* if anything: naive linear extrapolation to 100k
is ~1.17 s, i.e. already **over** the 1 s hard target — the S5 optimization
ladder is load-bearing, not insurance. The tiered budget (probe <1ms /
tail <250ms / forced-full <1s) is the right shape.

### 1.7 Replay guard — CONFIRMED
`vertex.py:741-766` `_replay_guard`: detaches every descendant's store
(`v._store = None`) and sets `_replaying = True` tree-wide, restored in
`finally`. Boundaries suppressed at :591-592 when `_replaying`. The doc's
"external facts are never re-appended and never fire boundaries in the
reader" is exactly what this mechanism provides.

### 1.8 Receipt / receive signatures — NO API CONFLICT
- `Receipt(fact_id, tick, stored)` at vertex.py:54-82; gate rejection returns
  `Receipt(fact_id=None, tick=None, stored=False)` (:508, :514) — matches the
  doc's `Receipt(stored=False)` claim.
- `VertexProgram.receive(fact, grant=None, *, id_override=None) -> Receipt`
  (program.py:81-109). The handle's
  `receive(fact, grant=None, *, expect=None, id_override=None) -> ReceiveResult`
  is a superset wrapping Receipt — no signature collision, and
  `open_vertex`/`VertexHandle` collide with nothing
  (`grep -rn "open_vertex\|VertexHandle" libs apps` → no hits).
- Sketch types resolve: `FoldState`/`FoldItem` exist in atoms
  (libs/atoms/tests/test_fold_state.py imports them from `atoms`); `Tick`,
  `Grant`, `Fact` exist. `WriteCredentials`/`FoldExpectation` are new,
  correctly marked as seams.
- The doc's aside that `Vertex.run()` is a **stale claim** is itself correct:
  `grep "def run\|def collect"` over program.py/vertex.py/loop.py/executor.py
  → no hits. (Engine CLAUDE.md Level 0 still advertises `.collect()`/`.run()`
  — stale doc, separate cleanup; the advisor was right not to lean on it.)

### 1.9 Constructor-injected signers + the tasked wedge — CONFIRMED
`SqliteStore.__init__(*, ..., tick_signer=None, fact_signer=None)`
(sqlite_store.py:400-426) — constructor injection, exactly as claimed. The
wedge is not hypothetical: `~/Code/tasked/src/tasked/substrate.py:103-108`
carries the field comment verbatim — "a handle-lifetime cache froze key
material at daemon startup (key minted/rotated after start → tick_signer
stays None → UnsignedTickInSignedEra on every boundary until restart;
confirmed empirically)". Operation-fresh `CredentialProvider` is grounded.
Note the ceremony paths (`absorb_genesis`/`absorb_edit`) already take
`fact_signer` per-call, so per-op signing has precedent inside the store.

### 1.10 ticked's current cost — CONFIRMED line by line
`~/Code/loops-tasks/src/ticked/runner.py`: `poll_s: float = 2.0` (:86),
`time.sleep(self.config.poll_s)` (:122), `cycle()` folds at :130 and again
at :135 after reconcile, `_still_running` re-derives per check (:220-225 via
`store.task_view`), `_closed_task_names` scans ticks from epoch zero —
`vertex_ticks(self.store.vertex_path, 0.0, ...)` (:229). Per-emit fresh
program: `~/Code/loops-tasks/src/ticked/vertex.py:114`
`load_vertex_program(...)` inside `emit()`. The §7 deletion list is real.

### 1.11 Ceremony atomicity and the fact/tick commit split — CONFIRMED
`absorb_genesis`/`absorb_edit` run under explicit `BEGIN IMMEDIATE`
(sqlite_store.py:615, :776) — one ceremony = one commit, so a read-txn head
capture cannot observe a partial ceremony; the doc's "SQLite reveals its rows
only after the ceremony transaction commits" holds. Separately,
`append` commits at :521 and `append_tick` commits at :1302 — **two
transactions per boundary-firing receive** — which confirms the crash window
the `ReceiveCommittedError` design exists for. Well-grounded.

## 2. Two-writer staleness walk (re-derived, not deferred)

Process A holds a handle (epoch E1, held connection, facts cursor N).
Process B commits an edit ceremony (k `_decl.*` rows, one txn).

1. **Pre-commit**: rows invisible to A (WAL snapshot isolation);
   `data_version` on A's connection unchanged. A serves the E1 snapshot
   labeled position N — position-honest under the A1 witness-cursor
   semantics. Not a lie, just latency.
2. **Post-commit**: A's next probe (≤50 ms) sees `data_version` bump
   (empirically verified cross-process). One short read txn captures
   `fact_head = N+k` and fetches `(N, N+k]` **in the same txn** — the
   ceremony's single commit means all-k-or-none, so mid-ceremony capture is
   impossible on this path. `_decl.*` kinds detected → conservative
   recompile → full reconstruct → atomic swap. Window closed at
   ≤ probe interval + rebuild time. The invalidation **does** close the
   staleness window for readers — I could not construct a scenario where a
   consumer is handed an E1-compiled interpretation of a post-ceremony
   position, given the all-or-nothing publish rule.
3. **File-side declaration change** (no SQLite write at all): `data_version`
   never fires. The doc covers this with the declaration-dependency stamp in
   the cheap probe (§2, "a stamp change forces content hashing and a
   recompile attempt even if SQLite did not change"). Verified the resolver
   surface exists to recompile from (`load_declaration`, declaration.py:212,
   consumed by program.py/vertex_reader.py).
4. **Residual hole (real, doc partially names it)**: in `receive()`, B's
   ceremony can commit between A's catch-up and A's append. A's gate
   decisions — grant potential (vertex.py:507), observer-ownership (:511),
   reserved-namespace guard (:516), routes, boundary match — were all
   evaluated under E1. Post-write reconstruction repairs the *published
   state* (the head capture includes B's rows, recompile triggers) but does
   not and cannot re-adjudicate the *admission* of the already-committed
   fact. The doc names boundary evaluation as non-serializable and defers to
   the CAS/fact-plus-tick sibling — correct — but only boundaries.
   See Amendment B.

## 3. Break attempts that failed

- **Mixed-group head capture**: a domain fact committing between B's ceremony
  and A's capture — both fetched in one read txn, groups derived from
  contiguity + shared effective ts; the "extend through the committed
  ceremony" rule is reachable only across coalesced multi-group batches and
  is specified for exactly that. No tear found.
- **Local-write blindness**: same-connection commits don't bump
  `data_version` (verified) — doc explicitly requires the self-dirty bit. Covered.
- **Rowid durability**: cursor is process-private, never serialized as a
  handle (A3/A10 keep public handles id-based); `StoreReplaced`/lineage +
  `(device,inode)` covers file swap. VACUUM renumbering is the only in-place
  hazard and is an identity map on a dense append-only table (density
  verified on the live store). No hole.
- **Aggregate fold validity**: combining folded member states is indeed
  invalid in general; `_combined_read` exists (vertex_reader.py:330, used at
  :721, :933-939) and the doc keeps it as the 0.8.0 aggregate refold. Honest.
- **Iterator-vs-callback**: WAL-as-queue with a dirty-bit adapter is
  consistent with the verified cursor reads; `max_receipts` split at group
  boundaries composes with the atomicity argument above.

## 4. Amendments (named fixes — none structural)

**A. Probe-transaction discipline is a correctness invariant, not a style
note.** Empirical row 5 (§1.5): `data_version` is pinned inside an open read
transaction — an external commit is invisible until the txn closes. The
failure table's "missed notification at worst adds poll_interval latency" is
FALSE for this mode: a probe connection idling inside an open transaction
(one un-committed implicit DML txn on a shared connection is enough, under
python sqlite3's implicit-transaction behavior) converts the design's bounded
latency into **unbounded silent staleness** — the exact failure class the
handle exists to eliminate. Fix: state in the contract that the probe runs on
a connection that is transaction-free between probes (or probe = head query,
which the short-read-txn refresh already is); add an S0/S4 exit test: hold a
transaction open on the probe connection, commit externally, assert the
implementation still detects (or refuses/asserts) rather than serving stale
forever.

**B. Name the full admission window in receive(), not just boundaries.**
§ "Receive" and the race row in the failure table scope the
non-serializability to "boundary evaluation." Grant gating,
observer-ownership, reserved-namespace, and route/ontology admission are
evaluated in the same pre-refresh→append window against the stale compile
(vertex.py:507-528). S3's exit criteria should say the post-write
reconstruction canonicalizes *state*, not *admission*, and that admission
serializability is likewise deferred to the transactional-receive sibling —
otherwise an implementer may believe the post-write rebuild retroactively
re-validates the fact.

**C. "Existing serialization remains" (tick-chain fork row) overstates what
exists.** `append_tick` reads the prev tick row and the fact edge outside any
explicit transaction, then inserts and commits (sqlite_store.py:1256-1302) —
unlike the ceremonies, it is **not** `BEGIN IMMEDIATE`-wrapped, so nothing
mechanical serializes two cross-process boundary writers today; the guard is
the single-writer *convention* (one ticked daemon). The doc correctly
declines to solve this, but should say "existing single-writer convention
remains," so the fork row isn't read as citing a mechanism.

## 5. Verdict

**AMEND.** Every load-bearing engine claim checked out — several
(data_version semantics, the benchmark figure, the tasked signer wedge, the
rowid-discarding reads) verified empirically rather than by reading the doc's
own citations. The core mechanism (held connection + data_version hint +
rowid cursors + full-reconstruction contract + atomic snapshot swap) survives
the two-writer walk. The three amendments are contract-wording and
exit-criteria fixes; A is the only one with a real failure mode behind it,
and it is closable with one sentence and one test.
