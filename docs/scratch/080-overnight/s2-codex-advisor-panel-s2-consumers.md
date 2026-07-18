# Panel review — CONSUMER-FIT lens on the VertexHandle design (s2-codex-advisor.md)

*2026-07-17. Claude-family skeptic pass. Everything below was re-derived
empirically on this checkout — commands run, code quoted, stores counted.
Nothing is deferred to the codex advisor's conclusions.*

Verdict: **AMEND** — the process model, transport, ordering discipline, and
performance budget all survived active attempts to break them, but the
contract as written leaves four ticked/Watch requirements unserved or
served only in prose, and one S7 exit criterion depends on work outside
the slice plan.

---

## 0. Empirical baseline (things I measured, not reasoned)

**Live store sizes** (sqlite3, `immutable=1` read-only):

| Store | facts | ticks |
|---|---|---|
| `loops/.loops/data/project.db` | 3,086 | 58 |
| `~/.config/loops/tasked/data/tasked.db` | 180 | 40 |
| `~/.config/loops/identity/data/identity.db` | 317 | 3 |
| `meta-discussion/data/meta.db` | 301 | 0 |
| `~/.config/loops/tasks/data/tasks.db` | 56 | 2 |

The 100k fixture is ~32× the largest live store. It is a headroom gate,
not a current-reality gate — appropriate, but see §4 for which rung of the
optimization ladder it makes load-bearing.

**Replay timings** (this machine, `uv run --package loops python`):

- `vertex_read` on the live 3,086-fact project vertex: **9.4–9.9 ms** warm.
- `load_vertex_program` on the same vertex: **185 ms** (KDL + pins +
  compile + open + full replay; dominated by declaration work, not facts).
- Synthetic 100k-fact store (3 kinds, upsert folds, built via
  `SqliteStore.append`, appended in 2.6 s): `vertex_read` **269–510 ms**;
  `load_vertex_program` **170 ms** (trivial declaration, so the replay
  component itself is cheap through the runtime fast path).

**`PRAGMA data_version`** (two connections on one WAL db): initial a=2,b=2;
after a's own commit a still sees 2 and b sees 3; after b's commit a sees 3.
Exactly the semantics the synthesis's transport depends on, including the
"same-connection local write must mark itself dirty" corollary.

**Engine code claims** (all quoted lines verified on this checkout):

- `since`/`since_raw`/`replay_cursor` filter `WHERE rowid > ?` but `ORDER BY
  ts, id` and never return the rowid
  (`libs/engine/src/engine/sqlite_store.py:867-936`); `total` is
  `SELECT COUNT(*)` (`sqlite_store.py:967-971`). S0's cursor-bearing methods
  are genuinely missing today.
- Signers are constructor-injected on `SqliteStore`
  (`sqlite_store.py:400-408`) — the operation-fresh `CredentialProvider`
  requirement is real, not hypothetical.
- The replay guard exists (`libs/engine/src/engine/vertex.py:197,741-766`,
  early-return at `:591`) — S2's "no external refresh appends a fact or
  fires a boundary" criterion has an implementable substrate.
- A1–A13 exist as stated in `s1-arbitration.md:153-220`; the synthesis's
  bindings (facts-only cursor, receipt groups, full-reconstruction contract,
  aggregate vectors, lineage-qualified handles) consume them consistently.

**One citation in the synthesis is unverifiable**: §6's "on this checkout's
existing engine benchmark, replay plus boundary reconciliation for 5,500
facts measured about 63.5 ms" — no such benchmark exists anywhere in
`libs/` or `apps/` (grep for the number and for benchmark files: zero
hits). The number is an ad-hoc advisor run, not a checked-in artifact. My
own measurements above *replace* that anchor and actually strengthen the
conclusion (see §4), but the synthesis should not cite a nonexistent
benchmark as "existing"; S5 checking in fixtures/benchmarks fixes this
going forward.

---

## 1. ticked — requirement-by-requirement fit

Requirements from the dossier §7(a), each mapped against the proposed
contract, verified against `loops-tasks/src/ticked/runner.py` and
`vertex.py` directly.

| # | Requirement | Contract answer | Fit |
|---|---|---|---|
| 1 | One compiled/materialized vertex across cycles | `open_vertex` + held compile plan | **Served** |
| 2 | Refresh from other processes' writes, store as sole coordination channel | `refresh()` / `changes()` over durable rowid cursors | **Served** |
| 3 | `receive()` on the current handle, existing `Receipt` intact | `receive()` → `ReceiveResult`; S3 exit preserves Receipt/boundary dispatch | **Served** |
| 4 | Catch-up must not re-append or re-fire boundaries | replay-guard semantics named in Refresh section | **Served** (substrate verified, vertex.py:741) |
| 5 | No signer freeze across handle life | `CredentialProvider.for_write()` per write | **Served** — directly answers tasked's substrate.py:103-108 lesson |
| 6 | Conditional emit / CAS | `expect=` seam named, semantics deferred | **Deferred honestly**, but see finding F4 |

Beyond the dossier's list, three concrete ticked call sites are **not**
covered by the API as written:

**F1 — the tick read surface is claimed in prose, absent in the API.**
Synthesis §7: "the handle's tick cache replaces `_closed_task_names()`
scanning ticks from epoch zero." But `VertexSnapshot` carries only
`tick_seq: int`, and `ChangeBatch.ticks` carries only ticks that arrived
*after* the handle's tick cursor — which is initialized at head on open
("cold-reconstructs once", no batch at open). `_closed_task_names`
(`runner.py:227-236`) needs *task name → latest close-tick boundary
payload* over **all history**, every reconcile pass. Under the proposed
API, ticked's only options are (a) keep calling
`vertex_ticks(path, 0.0, …)` — which the S7 exit criterion "no epoch
`vertex_ticks`" forbids — or (b) do one startup epoch scan and accumulate
`TickEvent`s in its own memory, which the synthesis never states and which
S7's criterion as worded would still fail on the startup scan. Either add
a bounded tick query to the handle (e.g. `handle.ticks(name=…)` served
from the held cache, hydrated at open) or restate §7 and the S7 exit
criterion to bless startup-scan-plus-accumulation. Right now the deletion
claim and the API do not meet.

**F2 — no idle/deadline wake on `changes()`.** The synthesis itself says
the 2 s poll "becomes `changes()` plus a timeout at the nearest deadline
derived from facts (claim grace, work timeout)" and correctly argues a
dead detached worker emits nothing (`CLAIM_GRACE_S` at `runner.py:52`,
pid liveness at `:70-82`). But the iterator contract has no timeout: sync
`changes()` blocks in `next()` until a committed change exists; nothing in
the signature (`poll_interval`, `coalesce`, `max_latency`, `max_receipts`,
`max_bytes` — all delivery policy *after* detection) lets a consumer say
"wake me by T even if nothing changed." The async variant could be wrapped
in `asyncio.timeout`, but cancelling a pending `__anext__` mid-probe and
then reusing the iterator is undefined in the contract. Ticked's reaper is
the one consumer that *must* wake on wall-clock deadlines with zero store
traffic. Amend: either an `idle_timeout=` that yields a sentinel/empty
wake, a separate `next_change(timeout=…) -> ChangeBatch | None`, or an
explicit guarantee that async-iterator cancellation is safe and resumable.

**F3 — per-emit declaration reparse survives the cutover.** Every ticked
emit calls `check_emit(vertex_path, observer, kind)`
(`vertex.py` emit body; implementation at
`apps/loops/src/loops/commands/identity.py:199-239`), which re-walks the
.vertex chain and combine sources (`_collect_all_observers`) — KDL parses
per emit. The handle holds exactly the compile plan that knows the
declared observers and grants, but exposes no surface for it
(`ontology_epoch` is a digest, not a query). S7's exit criterion ("no
per-emit `load_vertex_program`") passes on the letter while a per-emit
declaration walk survives in spirit. Small amendment: expose
observers/grants from the held plan (or fold the undeclared/forbidden
classification into `receive()`'s named errors) so the cutover actually
retires the reparse.

**F4 — S7's exit depends on work outside the slice plan.** "tasked's race
test passes under transactional expectation before its wrapper deletion"
requires the conditional-emit/CAS semantics that §Proposed API explicitly
assigns to "the sibling conditional-emit/CAS design" and S3 explicitly
lands only as a dead parameter. There is no conditional-emit slice in
S0–S7. As written, S7 cannot exit without an unplanned dependency, or it
exits by quietly dropping that criterion. Amend: either pull a minimal
conditional-emit slice into the plan, or split S7's exit into
"ticked cutover" (achievable now) and "tasked wrapper deletion" (gated on
the sibling design, tracked as its own entry).

**F5 (minor) — the foreign-vertex notify path.** `_notify` →
`notify_reply_vertex` (`vertex.py:332-357`) one-shot-loads a *different*
vertex per task close. Legitimate — the handle is per-vertex — but a
grep-shaped test of S7's "call graph contains no per-emit
`load_vertex_program`" will flag it. One sentence of carve-out ("per-close
cross-vertex notify may use a one-shot program or a second short-lived
handle") keeps the criterion honest and mechanical.

**Does the quadratic poll actually die?** Idle cycles: yes — the probe is
a `data_version` read (~µs, verified semantics above), zero replays, and
the runner's 4–8 full replays per cycle (verified at `runner.py:127-136`
fold + re-derive, `:220-225` `_still_running` fresh fold, `:227-236` tick
scan, `:124-125` drain check, plus per-emit program loads) all collapse
into snapshot reads. Change-bearing cycles: under A7 the contract is full
reconstruction per coalesced group — still O(total facts) per active
cycle. What kills the *quadratic* term (O(N) work per append over the
daemon's life) is specifically ladder rung 4, the previous-head-as-
checkpoint tail append. At today's sizes this is academic (9.6 ms at 3k
facts), but the synthesis should state that rung 4 is **required for the
cutover claim**, not an optional optimization — the S5→S7 ordering already
supports this; only the framing ("may optimize") undersells it. Ticked's
folds are built-in declarative upserts, so they sit inside the
capability-gated checkpoint eligibility. Fine.

---

## 2. Watch — corpus contract line-by-line

From the ratified corpus block quoted in the dossier (§2, `-vv` verbatim):

| Corpus line | Contract answer | Fit |
|---|---|---|
| "subscribe: tail the append log from seq 142 onward" | `WitnessPosition.seq`, `receipt_ranges` | **Served at head; see F6 for resume** |
| "on append: apply → diff → emit, changed rows only" | `ChangeBatch.rows` typed before/after | **Served** |
| "coalesce bursts < 200ms" | 200 ms trailing-edge, 500 ms cap | **Served** |
| "backpressure: batches, never drops a fact" | WAL-as-queue, group-boundary splits, `catching_up`, `oversized_group` | **Served** — the strongest part of the design |
| "exit: ^C detaches, store unaffected" | idempotent `close()`, detach-only | **Served** |
| "the fold runs on every append" (-v) | receipts always delivered, even fold-no-op | **Served** |
| seq N vs visible N | `control` flag + `visible_domain_count` | **Served**, with F7 caveat |

**F6 — resume-from-position is implied but absent.** The dossier's minimum
contract item 7 requires "recover after disconnect/restart from the
durable cursor," and the synthesis's own failure table has a row for a
persisted cursor that "no longer resolves" (`CursorInvalidated`). But no
API accepts a starting position: `open_vertex` opens at head,
`changes()` takes only delivery policy. Either (a) add
`changes(since=WitnessPosition)` / `open_vertex(resume_from=…)` with the
already-specified invalidation behavior, or (b) explicitly scope 0.8.0 to
head-start-only and delete the dangling failure-table row and dossier
requirement from the served set. I lean (b) for scope — no 0.8.0 consumer
strictly needs backlog resume (ticked's state is the fold; a fresh Watch
starts at now; the TUI re-renders from head) — but the document must pick
one; right now it gestures at both.

**F7 (minor) — the initial header has no visible count.**
`visible_domain_count` lives on `ChangeBatch` (cumulative), but
`VertexSnapshot` doesn't carry it. Watch/TUI must render "seq N ·
visible M" at mount, before any batch has arrived. Add the cumulative
visible-domain count to `VertexSnapshot`.

---

## 3. TUI — s3's asks against this contract

s3-codex-advisor.md consumes the handle correctly and its dependency gate
("handle S0–S4 must supply single-store immutable snapshots and the async
change iterator") matches this plan's ordering. Line-by-line:

- **Immutable snapshot paintable without a transaction** — served
  (`open_vertex` publishes detached snapshot; s3 §Lifecycle relies on it).
- **One iterator, one watcher** — served ("permits one active change
  iterator"); s3's rewind design ("keep a separate head snapshot warm...
  must not invent a second watcher") is compatible because rewind's
  historical reconstruction comes from the one-shot read path
  (`--at`/A8/A11), not the handle. Consistent, and worth one explicit
  sentence in the synthesis: *the handle serves HEAD; historical positions
  are the one-shot selector's job* — s3 says it, s2 only implies it.
- **`changes_async` consumed in `Surface.on_start`, 50/200 ms** — served;
  s3's honesty framing ("live, poll-backed from the durable receipt
  cursor") matches the transport exactly.
- **Scoped lanes (`--kind`/`--observer`/`--key`) on a shared feed** —
  served: `ReceiptEvent` carries kind/observer/payload; `RowChange`
  carries `FoldAddress` for key-scoped filtering. Consumer-side filtering,
  no contract change needed.
- **`RowChange` as highlight aid, not authority** — s3 states this and it
  matches A7's snapshot-is-canonical contract. Consistent.
- **Aggregate honesty** — s3's S5 (head-only fallback if the vector handle
  slips) composes with s2's S6; A9 refusal of `seq:`/`fact:` on
  aggregates appears in both. Consistent.

One cross-doc nit: s3's `ViewController.refresh(data, change:
ChangeBatch | None)` and `CursorPresentation.receipt_seq/visible_count`
consume F7's missing snapshot field — the same amendment serves both docs.

---

## 4. The performance gate, grounded

The S5 gates against my measurements:

- **p95 no-change probe < 1 ms**: a `data_version` read is microseconds —
  trivially achievable, and the gate is honest (it is the *steady-state*
  ticked/TUI cost).
- **100k forced-full hard target < 1 s**: measured 269–510 ms
  (`vertex_read`) and 170 ms (runtime replay) on a synthetic 100k store on
  this machine. The synthesis's fear that "naïve linear extrapolation does
  not establish a sub-second result" is *over*-cautious — the gate is
  comfortably real for built-in folds, and its presence in S5 as a
  measured, checked-in benchmark is the right fix for the currently
  nonexistent "existing engine benchmark" citation (§0).
- **p95 1–100 event-tail facts < 250 ms**: at 100k this is NOT met by
  forced-full (269–510 ms) — it is met only via ladder rung 4
  (head-as-checkpoint tail append). So within S5's own gates, rung 4 is
  mandatory, not "may optimize." The slice already implies this; the
  ladder's framing should say it.
- Fixture note: my synthetic store used 3 upsert/collect kinds and uniform
  payloads. S5's "representative built-in-fold fixtures" should include a
  collect-heavy kind and a wide-payload kind — collect folds grow state
  linearly and are the plausible worst case the 64 MiB checkpoint bound
  exists for.

Exit-criteria testability across S0–S7: **S0–S6 are testable as written**
(S0's rowid-gap test can synthesize gaps via direct SQL in a fixture;
S2/S3's cross-process and forced-failure cases are standard
subprocess/monkeypatch work; S4's timing tests want an injectable clock —
implementation detail, not a contract change; S5 is environment-pinned and
says so). **S7 is the only slice whose exit cannot currently be evaluated
mechanically**, for the reasons in F1 (tick scan), F4 (conditional-emit
dependency), and F5 (notify carve-out).

## 5. Overserving check

Nothing materially overserved. `AggregatePosition`/S6 is justified by the
config-level project aggregation the TUI will open;
`oversized_group`/`max_bytes` answer the dossier's open question 10;
`replay_mode`/`catching_up` are cheap honesty diagnostics. Mild
redundancy: `tick_arrived` duplicates `len(ticks) > 0` and
`ontology_changed` is derivable from control receipts — harmless
convenience, not scope creep. `refresh(force=True)` is the one parameter
with no defined semantics anywhere in the document; define it (presumably
"skip the data_version short-circuit and re-verify heads + declaration
stamp") or drop it.

## 6. Verdict

**AMEND.** The architecture survived the attacks I could mount: the
transport's SQLite claims reproduce empirically, the ordering discipline
(rowid detection / `(ts,id)` reconstruction, A1/A7) resolves the dossier's
hardest open question correctly, the backpressure story is genuinely
lossless, and the performance budget is not just plausible but measured.
The amendments are all contract-surface or slice-wording fixes, none
structural:

1. **A-tick-surface**: add a handle tick query (or restate §7 + S7 exit for
   startup-scan-plus-accumulation) — F1.
2. **A-idle-wake**: add a deadline/timeout wake to `changes()` or define
   async cancellation safety — F2.
3. **A-resume-scope**: either add resume-from-position or explicitly scope
   it out and reconcile the failure table/dossier item 7 — F6.
4. **A-s7-split**: split S7's exit into ticked-cutover vs tasked-deletion
   (conditional-emit-gated), add the notify carve-out, and expose
   observers/grants from the held plan (or accept the reparse and say so)
   — F3/F4/F5.
5. **A-snapshot-visible-count**: add cumulative visible-domain count to
   `VertexSnapshot` — F7 (also serves s3's `CursorPresentation`).
6. **A-benchmark-citation**: replace the nonexistent "existing engine
   benchmark" citation with S5's checked-in fixture numbers; promote
   ladder rung 4 from optional to required-for-cutover.
