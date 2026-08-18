# Cut B — PROJECTIONS: design proposal

Branch `feat/arrival-libs` @ `01ab4bb0`. Every citation below was read at that
commit. Scope: `libs/engine` + `libs/store` only; `apps/` diff-empty.

Reading order for a reviewer in a hurry: **Q1** (the verb) and **Q4** (merge)
carry the cut. **Q7** is gate item 1's answer. **Q3** is gate item 2. Q5, Q6,
Q8 are dissolutions — each removes something rather than adding it.

---

## Q1 — The re-derivation verb

### THE RULING

**Name and home.** A module function, not a store method:

```python
# libs/engine/src/engine/arrival_projection.py  (NEW)
@dataclass(frozen=True)
class Rederivation:
    lineage: str
    ordinal: int          # the last record consumed
    records: int
    facts: int
    ticks: int
    projections: tuple[str, ...]   # ("index",) or ("index", "derived-log")

def rederive_projections(
    canonical: Path, *, derived_log: bool = False
) -> Rederivation: ...

def rows_of_record(record: dict) -> list[tuple[str, tuple]]: ...
```

`rederive_projections` opens **its own sqlite connection** to
`index_path_for(canonical)` and its own `ArrivalLog`. It **never constructs an
`ArrivalStore`**, and `ArrivalStore` gains **no** `rederive` method.

**Why a module function and not a method (NON-NEGOTIABLE).** The states this
verb resolves are exactly the states `ArrivalStore.__init__` refuses
(`arrival_store.py:157` runs `catch_up()` inside the constructor, and
`catch_up` raises `ArrivalCanonicalUnsupported` at `:236-260`). A method on the
class would be unreachable on the very stores that need it — you cannot
construct the object. Making the constructor tolerate the refusal (a
`park`/`defer` flag) would mean a store that opens in a broken state, which is
precisely what the consume-or-refuse posture forbids. The precedent is
`canonical_audit`'s "pure reader, by contract" (`canonical_audit.py:13-20`):
the module that must not repair never constructs the store that does. Here it
is the inverse and the same rule — the module that repairs never constructs the
store that refuses.

Second consequence, and the reason it is worth the module: **no write path can
call re-derivation as a side effect.** It is not on the object the write path
holds.

**Which of the three catch-up refusals resolve into it.** None of them stop
being refusals. All three change from dead ends into refusals that **name the
verb**:

| `arrival_store.py` | State | After cut B |
|---|---|---|
| `:236-242` | index carries state, **no log** | **Stays a dead end.** No verb offered. Re-derivation cannot manufacture a log; offering it here would name an operation that destroys the only surviving artifact. |
| `:245-251` | rows present, **no mark** | Refuses, and names `rederive_projections`. |
| `:254-260` | mark the log rejects | Refuses, and names `rederive_projections`. |

Grounding for keeping them refusals: the ratified posture is "re-derivation is
an explicit verb, never an open-time side effect for a store that carries
state". The distinction that survives untouched is `arrival_store.py:47-49` —
**an absent projection builds automatically** (`ensure_arrival_index`,
`:497-521`, and the `mark is None and not _has_rows()` arm), because building
an absent projection destroys nothing. An *existing* projection with rows is
evidence, and discarding evidence is an operator's decision.

**What survives a re-derivation.**

- `facts`, `ticks`: cleared and rebuilt from the log, ordinal 0 forward.
- `facts_fts`, `fts_state`: **dropped**, exactly as `jsonl_store._rebuild`
  does and for the identical reason (`jsonl_store.py:945-953`: `DELETE FROM
  facts` resets the rowid counter, so a surviving FTS index resolves stale
  text to new facts). Search then reports `missing`, the honest "run reindex"
  state.
- `store_meta.own_lineage`: **restamped from the log** — see Q5.
- The resume mark (`arrival_lineage`/`arrival_offset`/`arrival_ordinal`):
  restamped to the last consumed record.
- Every other `store_meta` row: preserved. Same rule as
  `jsonl_store.py:942-944` — `store_meta` holds identity, not fact.

**Live write lock.** `rederive_projections` takes **the sqlite write lock only**
(`BEGIN IMMEDIATE` for the whole clear-and-replay), and **does not take the
arrival append lock**. Rationale, both halves:

- Taking sqlite's write lock serializes it against every `ArrivalStore._write`
  (`arrival_store.py:366` stages its INSERT under the same lock), so no
  appender can interleave an index write into a half-replayed index.
- Not taking the append lock means an appender may land record N+1 mid-walk.
  That is harmless: the walk stops at the last complete record
  (`arrival.py:_verify_from` returns on an unterminated line, and a newly
  fsync'd complete record simply is or is not seen), and the stamped mark
  names what was actually consumed. The result is the ordinary "index behind
  the log" state, which the next `_reconcile` (`arrival_store.py:307-324`)
  tails forward. Holding the append lock for an O(n) replay would block every
  writer in the system for the duration, to buy a property the mark already
  provides.

### REJECTED

- **`ArrivalStore.rederive()` as a method.** Unreachable on the refusing
  stores, as above.
- **Automatic re-derivation on open**, matching `JsonlStore`'s
  `offset is None → _rebuild` (`jsonl_store.py:693-695`). Rejected by ratified
  constraint; also it is the behaviour that makes an out-of-band row
  silently disappear, which `_refuse_out_of_band` (`jsonl_store.py:733-755`)
  exists to prevent.
- **A separate `ProjectionRefused` exception family.** `ArrivalCanonicalUnsupported`
  already means "an operation an arrival-canonical store refuses rather than
  fudges" (`arrival_store.py:119-127`); a second family is two names for one
  verdict.
- **Naming it `rebuild`.** `_rebuild` is the legacy spelling and carries the
  legacy semantics (rebuild-as-open-time-repair). The glossary word is
  *projection*; the verb is *re-derive*.

---

## Q2 — The derived `.jsonl` projection

### THE RULING

**Path — no new suffix.** For an arrival log at `<name>.arrival` the derived
log is `<name>.jsonl`, i.e. `canonical_for(index_path_for(log), "jsonl")`
(`residence.py:146-162`). This shape is **already ratified and already
classified**: `probe._probe_log` (`probe.py:320-341`) returns
`target_type="derived_log"`, `canonical_mode="arrival"` for a `.jsonl` sitting
beside an `.arrival`, with the note "custody is the arrival log's, so this file
is a projection, not a store". Cut A named the half-migrated shape; cut B is
what makes it *deliberate* rather than transitional. Nothing in `residence` or
`probe` changes.

**Line format — row-class records only.** The derived log projects the records
whose `k` is a **row class** (`fact` / `tick` / `batch`); each emits one line,
the `jsonl_codec` canonical encoding of that record's `body` and of nothing
else. Because the body IS the codec's object for the committed row
(`arrival_store.py:372`: `body = json.loads(serialize_row(committed_row))`),
re-encoding it is an identity round trip and the payload keeps riding as
verbatim stored TEXT. A `batch` record's body emits as one `batch` line,
unchanged.

**Structural records are skipped, exactly as the index skips them.** Every
arrival log's record at ordinal 0 is a genesis whose body is
`{protocol, lineage, key}` (cut A), and key introductions are the same shape —
neither is a codec object, so `serialize_object` would refuse them on unknown
fields. `_index_record` already walks past `_STRUCTURAL_KINDS`
(`arrival_store.py:113-114`, `:282-283`); the derived-log writer takes the
identical arm, from the same `rows_of_record` definition. **NON-NEGOTIABLE:
structural records (genesis, key introduction) have no derived-log line.**
Their content is not lost — it lives in the arrival log, which is the store.
**NON-NEGOTIABLE: the derived log is a function of the arrival log alone —
never of the index.** Deriving it from sqlite would make it a projection of a
projection, and a poisoned index would launder itself into a second artifact.

**Ordering on disk — byte-lexicographic sort of the encoded lines.**

This is the whole "re-keyed to SET MEMBERSHIP" ruling made concrete. Byte sort
is the only order that is a pure function of the *set*: it needs no field
semantics, is reproducible by `sort(1)` in any language, and is what makes the
merge driver (Q3) able to produce the same bytes a fresh derivation produces
without knowing any ordinal. **NON-NEGOTIABLE: line order in the derived log
carries no meaning, and no reader may attribute one to it.**

Two consequences, stated here rather than left for a reviewer to find:

1. **The derived log is not a chain-verification surface.** Tick chain order is
   not file order. `canonical_audit._ChainWalk` (`canonical_audit.py:739-836`)
   re-derives the chain from log order; run against a byte-sorted projection it
   would report breaks on a healthy store. Chain verification reads the
   **arrival** log. (Re-basing the audit is cut D's — `plan:arrival-libs-slice-D`.)
2. **A last-0.x reader rebuilding from this file folds in byte order, not
   receipt order.** That is a real interim hazard for the wave-2 sidecar and it
   is named here for that design. It is inside the hazard Kyle already accepted
   explicitly (`plan:arrival-arc-sequence`: "the interim fold-order hazard is
   ACCEPTED, not managed around"). The sidecar's own answer will be to consume
   the `.arrival`, which carries the ordinal.

**Derivation trigger — on demand only. NON-NEGOTIABLE: never on the append
path.** Appending to a byte-sorted file is not an append; regenerating it per
emit is O(n) per write, which is the O(n²) ingest shape this arc already paid
for once (see the CI/characterization finding: receive re-folds all history).
The derived log is materialized by `rederive_projections(..., derived_log=True)`
and by merge/receive (Q4). It is expected to lag, and a lagging derived log is
**not an error**: nothing in `libs/` reads it (reads execute through the index —
arrival law 1, `residence.py:42-46`).

**Staleness custody — none. There is no marker.** The offset/count triple does
not get a third sibling. The derived log's currency is a *set* question, and
the honest answer to a set question is a set comparison, not a stamp:

```python
@dataclass(frozen=True)
class DerivedLogAgreement:
    ok: bool
    missing: int    # records the arrival log carries, the file does not
    extra: int      # lines the arrival log never carried
    detail: str

def audit_derived_log(canonical: Path) -> DerivedLogAgreement: ...
```

Contract note, following the line-format ruling: `missing` counts **row-class**
records the file lacks. Structural records are outside the projection, so a
healthy store must never be reported as missing its genesis.

Implementation: hash each side's lines to 32 bytes and take two set
differences. Memory is bounded by record count, never payload size — the same
posture `_ChainWalk` documents (`canonical_audit.py:739-745`). This is the
repo's established contract for derived artifacts: `verify_rebirth` is
"re-run the transform, diff. An operation, not a promise" (`libs/store/CLAUDE.md`
Level 1.5).

**Home: `arrival_projection.py`, not `canonical_audit.py`.** Cut D moves
canonical_audit's whole custody model (`plan:arrival-libs-slice-D`); B must not
touch its defaults. The derived log is `arrival_projection`'s subject.

### REJECTED

- **`(ts, id)` sort.** Available from line content, but it *names an ordering
  claim* — event-time ordering in a file whose whole point is that order means
  nothing, and adjacent to "id is NEVER semantic time". A declared projection
  order is cut C's subject (`plan:arrival-libs-slice-C`); B must not grow a
  second design for it.
- **Ordinal order.** Not derivable from a codec line (fact/tick lines carry no
  ordinal), so the merge driver could not reproduce it.
- **A `<name>.derived.jsonl` suffix.** Would strand the shape `probe` already
  classifies, and break every last-0.x reader the projection exists for.
- **A `jsonl_projection_ordinal` marker in `store_meta`.** Reintroduces offset
  custody under a new spelling, inside the mutable artifact being judged.
- **Deriving on write, appending single lines.** Incompatible with byte sort,
  and O(n) rewrite per emit otherwise.

---

## Q3 — The git merge driver

### THE RULING

**Home: `libs/store/src/store/derived_log_merge.py`**, with a `python -m`
entry point:

```python
def merge_derived_log(base: Path, ours: Path, theirs: Path, out: Path) -> DerivedLogMergeResult
# CLI: python -m store.derived_log_merge %O %A %B   (writes %A in place, git's contract)
```

libs/store is the maintenance-operations lib by charter (`libs/store/CLAUDE.md`);
a git driver is tooling over store artifacts, not a runtime write path. The
**sort rule and the line grammar live once in engine** — the driver imports
`jsonl_codec.deserialize_records` and `arrival_projection`'s canonical-bytes
helper, so driver output and fresh derivation cannot drift. **NON-NEGOTIABLE:
the driver never opens a store and never touches an arrival log.**

**Union key: `(t, id)`; identity: the whole canonical line.** Per key:

| Case | Ruling |
|---|---|
| Key on one side only | include |
| Key on both sides, byte-identical lines | include once |
| Key on both sides, **different bytes** | **REFUSE** (rc 1, name the id) |
| Key in `base`, absent from a side | **REFUSE** (rc 1, name the id) |

Grounding for the two refusals:

- *Same id, different bytes* is a custody contradiction: at most one of them is
  what an arrival log says. `jsonl_store._index_lines` already refuses a log
  carrying an id twice (`jsonl_store.py:897-901`), and today's
  `INSERT OR IGNORE` (`merge.py:111-115`) resolves the same collision *silently
  in the target's favour* — the behaviour this cut is removing. A driver that
  picked a side would re-mint it.
- *Loss against base* cannot happen to a projection of an append-only log. If
  one branch's file lost a line the other kept, that branch's log was rewritten.
  Refusing is the only non-destructive answer, and it is the property that makes
  this a **semantic** driver rather than `merge=union`.

**Output: byte-sorted, byte-identical to a fresh derivation of the merged set.**

**Proof shape (gate item 2 — an actual `git merge`).**
`libs/store/tests/test_derived_log_merge.py`:

1. `git init` in `tmp_path`; `git config user.name/email`.
2. Build an arrival store, emit facts + a tick, derive the projection, commit
   on `main`.
3. `git checkout -b left`: emit divergent facts into a copy of the store,
   re-derive, commit. Same on `right` from `main`.
4. In the fixture repo only: write `.gitattributes` (`*.jsonl merge=loops-derived-log`)
   and `git config merge.loops-derived-log.driver "<sys.executable> -m store.derived_log_merge %O %A %B"`
   with `PYTHONPATH` pointing at the workspace.
5. `subprocess.run(["git", "merge", "right"])` on `left` — assert `returncode == 0`.
6. Assert the merged file's line **set** equals the union of both sides, and
   its **bytes** equal a fresh canonical derivation of that set.
7. Second test: both branches carry the same fact id with different payload
   bytes → assert `git merge` exits non-zero and the driver's stderr names the
   id.
8. Third test: a line present in `base` deleted on one branch → non-zero.

**Registration rides wave 2. NON-NEGOTIABLE: cut B adds no repo-root
`.gitattributes` and changes no `.gitignore` line** (today `*.jsonl` is ignored
at `.gitignore:9`; un-ignoring it is `plan:arrival-wave-2-and-tail`'s).

**Stated, designed, registered later: there is no merge driver for `.arrival`.**
Two arrival logs cannot be merged textually — every record after the divergence
point carries a `prev` chained to a different predecessor (`arrival.py:_check_follows`),
so a textual union produces a file that refuses to walk. Combining two arrival
lineages is a custody ceremony, and its name is `merge_store` (Q4). Wave 2
registers `*.arrival merge=binary` (or an explicitly refusing driver); B states
the rule so nobody defaults it.

### REJECTED

- **`merge=union`** (git's built-in). Produces duplicate and interleaved lines
  in arbitrary order, cannot detect same-id divergence, and cannot detect loss.
- **Union by record hash `rh`.** The projection line is a codec line and carries
  no `rh` — only the arrival record has one.
- **Union by whole line with no `(t, id)` grouping.** Same-id-different-bytes
  would silently produce a file with two rows for one id, which no index can
  consume (`jsonl_store.py:897-901`).
- **Driver in `libs/engine`.** engine owns the codec and the write path; it does
  not own tooling, and a driver there would invite calling it from a store.
- **Resolving same-id conflicts by preferring the newer `ts`.** Event time
  deciding custody — the retired model exactly.

---

## Q4 — `merge_store` / `receive_store` rewrite

### THE RULING

**Signature unchanged.** `merge_store(target, source, *, dry_run=False) -> MergeResult`
and `receive_store(target, source) -> ReceiveResult` keep their shapes and
result dataclasses: `apps/` is diff-empty, `_transport_local.py:34` and
`transport.py:136,139` call them, and `spec/conformance/generate_merge.py:535`
generates vectors through them.

**Dispatch on the target's custody, resolved through `probe`.** `merge_store`
receives a `.db` path, and under three modes a `.db` cannot answer its own mode
from the path (`residence.py:146-155`). `engine.probe.probe_target` is the
ratified home for existence-based disambiguation (cut A ruling) and already
returns `canonical_mode` + `canonical_path` for a bare `.db`
(`probe.py:364-410`). Three arms:

| Target custody | Path |
|---|---|
| `sqlite` | **Unchanged, byte-identical.** ATTACH + `INSERT OR IGNORE`. Cut A seam rule S3: every change is conditional on the declared locator. |
| `arrival` | New path: append-into-arrival, then re-derive both projections. |
| `jsonl` | **REFUSE** (`JsonlCanonicalUnsupported`), naming the export-and-reopen recovery. |

The `jsonl` arm is the one behaviour change to a legacy mode, and it is the same
verdict delivered earlier: a merge into a `.jsonl`-canonical store today
succeeds and then bricks the store at its *next open*
(`jsonl_store._refuse_out_of_band`, `:733-755`). Refusing at the site is
consume-or-refuse, attributable, and destroys nothing.

**The arrival arm, in order.**

1. **Bring the index current first.** Open the target through
   `open_canonical_store` (`jsonl_store.py:250-271`) so `catch_up` runs. If
   catch-up refuses, merge refuses — merging into an index that does not
   account for its log would dedup against a lie.
2. **Choose the source order.**
   - Source is **arrival-canonical** → walk its arrival log from ordinal 0
     (`ArrivalLog.walk()`) and replay in **ordinal order**.
     **NON-NEGOTIABLE.** Merging is replaying the source's arrival into the
     target's arrival; it consumes no event-time input at all.
   - Source is **sqlite/jsonl** (the transport case — `slice_store` emits a
     `.db`) → facts in `rowid` order, then ticks in `rowid` order, two passes.
     Deterministic, and it deliberately does **not** call
     `store.jsonl._receipt_order` (`jsonl.py:104-126`), which cut C dissolves
     (`plan:arrival-libs-slice-C`) — B must not grow it a second caller.
     Folds are unaffected: ticks never feed fold state (`witness.py:26-29`).
3. **Dedup before appending.** A row whose id the target index already holds
   appends nothing. **NON-NEGOTIABLE: the arrival log must never carry one row
   id twice** — both the index PK and `jsonl_store.py:897-901` refuse such a
   log, and no verb in this design can consume it.
4. **Append under ONE lock acquisition** — see the concurrency ruling below.
5. **Re-derive both projections**: the index by **consume-forward catch-up**
   (cheap — the records just appended are a suffix, so this appends rows and
   never clears), the derived log by **regeneration** (inherently O(n), it is
   sorted). *The plan's "re-derive both projections" must not be read as an
   O(n) index rebuild per merge.*

**Concurrency — `ArrivalLog.append_marked_many`. NON-NEGOTIABLE.**
`append_marked` takes the flock per call (`arrival.py:1330-1356` opens the lock
file fresh each time). Two processes merging the same source into one target
would both pass dedup against the pre-merge snapshot and both append fact X →
the log carries one id twice → permanently unconsumable by every verb in this
design. That is the worst artifact this cut could mint, so the append phase
holds the lock across all records. An outer lock + per-record `append_marked`
**deadlocks** (each `_append_under_lock` opens a second fd on the same lock
file, and `flock` is per open-file-description, so it blocks within one
process). Hence a new log-level primitive:

```python
def append_marked_many(self, entries: Sequence[Entry], *, following: int | None = None
) -> tuple[list[dict], ResumeMark]:
    """One lock acquisition, records chained sequentially, ONE fsync at the end."""
```

Single trailing fsync is sound: a crash loses only an un-fsynced suffix, or
leaves one torn tail line that the existing truncate-under-lock rule removes
(`arrival.py:1387-1408`). Recovery is "re-run the merge" — dedup makes it
idempotent, which is the whole story to tell an operator about an interrupted
merge.

**Record shape for a merged-in row.** Asymmetric between facts and ticks, and
the asymmetry is inherited, not invented:

- **`k`** = the row class (`fact` / `tick`), never the fact's kind
  (`arrival_store.py:18-24`).
- **`observer` / `origin` / `at`** mirror the row's own columns, exactly as the
  live path does (`arrival_store.py:374-378`). A merged fact's record claims
  its **original** observer — the record describes the authored row, not the
  operator who admitted it.
- **Fact body: verbatim, including the row's own `signature`.**
  `merge.py:93-97` already rules this: the fact signature is a per-observer
  authorship claim over content only, carried verbatim, never re-signed;
  era-aware NULL for a pre-signature source. **NON-NEGOTIABLE.**
- **Tick body: chain columns and tick signature are NULL/absent.**
  `prev_hash`, `window_start`, `fact_cursor`, `window_hash`, `signature` are
  **store-local receipt custody** — today's merge strips exactly these
  (`merge.py:119-123` selects only `id, name, ts, since, origin, payload`;
  `merge.py:93-96` states why). Carrying them verbatim would put ticks in the
  target whose `prev_hash`/`window_hash` reference the *source's* chain, so the
  target's `verify_chain` would break on every merged tick. And keeping the
  tick signature while nulling the chain would be a verification lie: the tick
  signature covers the chain fields (`sqlite_store.py:100-110`). The codec
  already accepts all five as nullable (`jsonl_codec.py:88-93`) — this is the
  pre-chain era shape, honestly claimed. **NON-NEGOTIABLE.**
- **Record-level `sig`: structurally absent.** `merge_store` takes no signer
  parameter and never will, so there is no key to sign with; and the target's
  operator holds no key for a foreign observer anyway. The grammar makes record
  signatures optional above ordinal 0 (only genesis must be signed —
  `arrival.py:183-196`). The authorship claim that survives is the fact row's
  own signature, riding in the body. **NON-NEGOTIABLE: merge never signs a
  record for an observer whose key it does not hold, and never re-signs a row.**
  An *admission* attestation — the target custodian's own claim that it admitted
  this record — is explicitly a later cut's: `plan:arrival-libs-slice-D` names
  "admission signature verification is NEW CODE".

**The ordering claim of a merged store, after R1-as-doctrine is discarded.**
The merged store's ordering claim is **the target's arrival ordinal — the order
records arrived at the target — and nothing else.** No claim is made about
`(ts, id)`, about rowids as a primitive, or about the relationship between
`merge(A,B)` and `merge(B,A)`. The two merges are different custody events and
the ordinal says so; what survives is determinism per direction and equality of
content.

**`dry_run`.** Appends nothing (the log never rewrites, so a SAVEPOINT rollback
is not available and not needed): it runs the same dedup pass and reports the
counts. Cleaner than today's `SAVEPOINT`/`ROLLBACK TO` (`merge.py:76,126-128`).

**`receive_store`.** Two changes only:

- Its merge arm delegates to the new `merge_store` (already does —
  `receive.py:57`), so it inherits the dispatch for free.
- Its create arm (`receive.py:63-77`, `shutil.copy2`) **refuses when the
  target's `.arrival` sibling exists**. Copying a `.db` over a live arrival
  log's index would mint a second custody holder beside it — the one hazard cut
  A named in the half-migrated shape. **NON-NEGOTIABLE.** Everything else about
  receive (sqlite magic-byte validation at `receive.py:80-85`, `ReceiveResult`)
  is unchanged: transport slices produce plain `.db` files, and receiving one
  into a non-existent target still creates a plain sqlite store.

**What replaces the discarded test.** `test_merge_direction_sets_fold_order_by_receipt`
(`test_merge.py:457`) is deleted, and its **doctrine residue swept in the same
change** (dissolution-residue rule):

- `merge.py:14-16` and `:79-92` — the R1 comment block and the
  `docs/RECEIPT_ORDER_FOLD.md` pointer.
- `docs/RECEIPT_ORDER_FOLD.md` — the **R1 section only** (`:43-83`) plus its
  "Merge ceremony (R1)" row in the implementation table. **R2 and R3 stay** —
  they are cut C's (`plan:arrival-libs-slice-C`: rewrite the CAS token
  coordinate and the combined-read fold fork).

New tests:

- `test_merge_appends_into_arrival_in_source_ordinal_order` — an arrival source
  replays into an arrival target in ordinal order, and the target's log carries
  the appended records.
- `test_merge_ordering_claim_is_the_target_ordinal` — replaces the discarded
  direction test: `merge(A,B)` and `merge(B,A)` each fold in **their own**
  arrival-ordinal order; content is equal, sequences are not, and the assertion
  is against the ordinal, never against rowid-as-doctrine.
- `test_merge_never_writes_the_index_directly` — the arrival target's index row
  count equals the record count the log accounts for, after merge.
- `test_merged_tick_carries_no_foreign_chain` — merged ticks land with NULL
  chain columns and NULL signature, and the target's `verify_chain` passes.
- `test_concurrent_merges_never_double_append` — two processes, same source,
  one target; the log carries each id exactly once.
- `test_merge_into_jsonl_canonical_refuses`.
- `test_merge_direction_is_deterministic` (`test_merge.py:481`) — **KEPT**,
  unchanged for sqlite targets, with an arrival-target twin.

**Conformance vectors are unaffected**: `generate_merge.py:529-537` builds
`target.db`/`source.db` as plain `SqliteStore`s (`:514`), which take the
unchanged sqlite arm. The implementer must confirm this by regenerating the
vectors and asserting an empty diff, not by assertion.

### REJECTED

- **`ORDER BY ts, id` for the arrival append order.** Event time as an ordering
  input, in the cut that removes exactly that.
- **Re-signing merged rows with the target's key.** Fabricates authorship.
- **Carrying the source's tick chain columns verbatim.** Breaks the target's
  `verify_chain` on every merged tick (above).
- **Letting a merge into a jsonl-canonical store proceed and be caught at next
  open.** Same verdict, worse attribution.
- **Adding a `mode=` parameter to `merge_store`.** The mode is the artifact's,
  not the caller's; a parameter is a second place for it to disagree
  (`residence.py:18-21`).
- **Per-record `append_marked` under an outer lock.** Deadlocks (above).

---

## Q5 — The restamp verb

### THE RULING

**There is no restamp verb. It dissolves.**

The crash window, traced: `_ceremony_persist` (`arrival_store.py:404-435`)
appends the genesis record and stages the mark; the caller COMMITs at
`sqlite_store.py:975`. A crash between the log's fsync and that COMMIT rolls
back the `_decl.genesis` INSERT, the `own_lineage` stamp
(`sqlite_store.py:970-974`) and the mark together. The next open's `catch_up`
**tails the record forward and re-inserts the `_decl.genesis` row** — so the row
recovers itself. The single residue is `store_meta.own_lineage`, which is not in
the log's rows and so is not restored, leaving `_own_lineage_in_txn` to find a
genesis row with no marker → `AmbiguousGenesis` (`sqlite_store.py:1341-1366`).

So the whole "restamp" requirement is one projection row, and cut A already
ruled its nature: *"own_lineage becomes a PROJECTION of the arrival genesis —
written from `ArrivalLog.lineage()`, read from sqlite, rebuildable by cut B"*
(`decision:design/arrival-sliceA-authority`). Cut B makes it rebuildable in the
two places projections are built:

1. **`catch_up` stamps it when it is ABSENT**, restoring what the ceremony
   would have stamped.
2. **`rederive_projections` stamps it unconditionally**, because it is
   re-deriving every projection row.

**Which genesis licenses the stamp — NON-NEGOTIABLE.** The stamp is licensed by
consuming a **`_decl.genesis` fact row** out of the log (movement 2, the
declaration absorb — the thing that stamps the marker today at
`sqlite_store.py:970-974`), **not** by the mere existence of the arrival genesis
at ordinal 0 (movement 1). Stamping on movement 1 would flip a minted-but-never-
absorbed store to "adopted", and `witness.durable_handle` (`witness.py:550-565`)
would start emitting portable `fact:<lineage>/<id>` handles for stores that
never opened a declaration lineage — a witness-semantics widening that belongs
to D/SDK, not here. Restricted to a consumed `_decl.genesis`, the stamp is a
pure projection restore with zero semantic change.

**What it may stamp:** `own_lineage` and the resume mark. **Never a fact or tick
row** — rows come from the log and only from the log.

**Refusal case, NON-NEGOTIABLE:** a marker that is PRESENT and disagrees with
`ArrivalLog.lineage()` **refuses**. Absent→present destroys nothing; overwriting
a present, disagreeing marker means this index is some other log's projection,
and silently repointing it would be the strongest lie available in this design.

**Reachability.** The catch-up arm is automatic — which is legal precisely
because it is non-destructive, the same reasoning that lets an absent projection
build automatically (`arrival_store.py:47-49`). The destructive form is the
explicit verb.

**`adopt_lineage` stays refused** (`arrival_store.py:470-485`). Identity is
structural at ordinal 0; there is still nothing to choose between. Only its
message changes: "restoring it from the log is projection repair, a later cut"
becomes a pointer to catch-up and `rederive_projections`.

**`absorb_edit`'s crash window needs nothing.** Its batch record tails forward
whole (`arrival.py` batch atomicity; `jsonl_codec` `_validate_batch`), and
`own_lineage` is already present by then. Self-heals completely.

### REJECTED

- **A new `restamp()` verb.** Fails the dissolution test: it is a property of
  catch-up (absent-marker arm) composed with re-derivation. A third verb whose
  only job is one `store_meta` row is a maintenance surface with no subject.
- **Stamping on the arrival genesis (movement 1).** Widens witness semantics
  (above).
- **Making catch-up overwrite a disagreeing marker.** Repair that destroys
  evidence.
- **Leaving `AmbiguousGenesis` parking in place and documenting it.** The
  ratified word is consume-or-refuse; a store parked forever on a recoverable
  state is neither.

---

## Q6 — Offset/count triple custody

### THE RULING

**Per key, the honest finding is that the move already happened at cut A** —
what remains at B is one import direction and one reader, and the reader is D's.

| Key (`canonical_audit.py:72-74`) | Arrival-canonical store | Cut B |
|---|---|---|
| `jsonl_offset` | Never stamped. `ArrivalStore` stamps `arrival_offset` (`arrival_store.py:104-106`, `_stamp_mark` `:204-208`). | Nothing to move. |
| `jsonl_fact_count` | Never stamped — **dissolved** by the dense ordinal (`arrival_store.py:100-103`, `ResumeMark` docstring `arrival.py:661-683`). | Nothing to move. |
| `jsonl_tick_count` | Same. | Nothing to move. |

`JsonlStore._stamp` (`jsonl_store.py:509-516`) writes all three and continues to
do so **for `.jsonl`-canonical stores only**. Cut B removes nothing from them.

**What B actually does.** One residue: `arrival_store.py:83` imports `_as_int`
and `_stamped_offset_current` **from the legacy module** — the arrival surface
reaching into `jsonl_store` for its currency rule. B breaks that dependency; see
Q8 for the home.

**The B/D seam, explicitly.**

- **B owns:** the arrival store's own currency (the three-field mark), the
  derived log's set-membership agreement (`audit_derived_log`, in
  `arrival_projection.py`), and the import direction.
- **D owns:** `canonical_audit`'s whole offset/prefix custody model, *including
  the default L1 gate* — `_check_offset` (`:430-461`), `_suffix_unindexed`
  (`:383-427`), `_check_last_line` (`:495-542`) — re-based on
  `(arrival_lineage, ordinal)`, with jsonl comparison becoming set-membership
  (`plan:arrival-libs-slice-D`).
- **What canonical_audit reads meanwhile:** unchanged. Run against an
  arrival-canonical store today it reports `offset: no consumed-offset marker`
  and `counts: no row-count markers` — i.e. it answers *"I cannot account for
  this store"*, which is true and is a location claim, not a false verdict of
  corruption. **NON-NEGOTIABLE: cut B changes no default and no threshold in
  `canonical_audit.py`, so D's premise (one call site, whole model moves at
  once) survives intact.** B must not "helpfully" teach L1 about arrival keys —
  that is exactly the half-move that would leave D with two models to
  reconcile.

### REJECTED

- **Teaching `audit_agreement` the arrival mark at B.** Pre-empts D and splits
  one custody model across two cuts.
- **Renaming the three keys to `arrival_*` for jsonl stores.** They are the
  legacy mode's honest keys; renaming would carry the row counts along, which is
  precisely what the arrival axis showed to be dissolvable.
- **Adding an `arrival_derived_log_offset` key.** See Q2 — a set has no offset.

---

## Q7 — Witness-position invalidation (gate item 1)

### THE RULING

**Re-derivation does NOT invalidate outstanding witness positions, and cut B is
what makes that true.**

**Rowids are re-assigned, and the re-assignment is identical.** `facts` has no
`AUTOINCREMENT`, so `DELETE FROM facts` resets sqlite's rowid counter
(`jsonl_store.py:945-948`) and a replay from empty hands out `1, 2, 3, …` in
insert order. That reproduces the original assignment exactly, given four
premises:

1. **Re-derivation always replays from ordinal 0** — never a partial rebuild.
   **NON-NEGOTIABLE.**
2. **The arrival ordinal is dense and gapless**, verified at every walk
   (`arrival.py:_verify_from`, ordinal-succession check).
3. **The index carries rows from no other source.** Before cut B this was
   *false*: `merge_store`/`receive_store` INSERTed straight into `facts`
   (`merge.py:111-123`), so a re-derived index would have renumbered every row
   after the first merged one. **Cut B's merge rewrite (Q4) is what establishes
   this premise** — that is gate item 1's real answer.
4. **Rows are never deleted and rowids are dense by construction** (append-only
   store; no `UPDATE`, no `DELETE` outside re-derivation). So even
   `compact_store`'s `VACUUM` cannot renumber them.

**And the durable contract never depended on rowids anyway.**
`witness.durable_handle` returns `fact:<lineage>/<id>` and explicitly "never
reuses a rowid" (`witness.py:550-565`); resolution is a primary-key lookup on
`facts.id` (`witness.py:20-26`, A3). `WitnessPosition.rowid` is derived at
resolve time; `seq` is `COUNT(*) WHERE rowid <= ?` (`witness.py:330-333`), which
is preserved by order alone. So the guarantee is doubled: order-preservation
would be sufficient, and identity of rowids is what we actually get.

**Receipt groups survive.** A ceremony's rows ride as one `batch` record and
expand in array order (`jsonl_codec.deserialize_records`), inserted in that
order by `_index_record` (`arrival_store.py:294-305`), so
`receipt_group_span`'s contiguity heuristic (`witness.py:203-244`) sees the same
runs.

**Seals survive.** `window_hash` membership is a rowid range, but its *inputs*
are fact row hashes over content (`sqlite_store._window_hash` at `:1547`;
`canonical_audit._ChainWalk._window_hash` at `:813-821`). Identical rowids means
identical membership means identical hash; the chain columns themselves ride
verbatim in record bodies and are re-inserted untouched. **B leaves seals on
their current basis.** Re-basing them on `(arrival_lineage, ordinal)` — and the
latent rowid chain-commitment defect that motivates it — is cut D's
(`plan:arrival-libs-slice-D`). B's contribution is proving that re-derivation
does not disturb them in the meantime.

**Ratchet it, do not assert it. NON-NEGOTIABLE.** The property is a consequence
of four premises, not an accident, so it gets a test:
`test_rederivation_reproduces_every_rowid` — build a store **through the arrival
write path**, with facts, ticks and a declaration ceremony; snapshot
`(rowid, id)` for both tables and every resolved `WitnessPosition`;
`rederive_projections`; assert every pair is identical and every position
re-resolves to the same rowid and `seq`. The **merged**-store case is added at
seam B6, not here: until the merge rewrite lands, a merge into an arrival target
still INSERTs directly, so premise 3 does not yet hold and the test would have
to exercise the very path this cut outlaws. That sequencing is the point — the
diff at B6 is where the premise becomes established. Plus
`test_rederivation_preserves_receipt_group_contiguity` and
`test_verify_chain_passes_after_rederivation`.

**The one case that breaks it, named:** a truncated or rewritten arrival log.
That is forbidden by the grammar (torn tail only, only at the tail, only under
the lock — `arrival.py:1387-1408`) and it is why `reanchor` is now a permanent
refusal (Q-plan item: `jsonl_store.py:971-982`, `arrival_store.py:487-494`).

**Positions are NOT declared ephemeral.**

### REJECTED

- **Declaring positions ephemeral and invalidating them on re-derivation.**
  Would be honest only if the premises above failed; they do not, and it would
  discard a genuine property to avoid proving it.
- **Preserving rowids by writing them explicitly (`INSERT INTO facts (rowid, …)`).**
  Would require the log to carry the rowid — a projection artifact inside a
  signed immutable record, which is arrival law 1's first prohibition (cut A
  ruled exactly this for `chain_head`).
- **Adding `AUTOINCREMENT` so rowids are never reused.** Would *break* the
  property: a re-derived index would start above the old high-water mark.

---

## Q8 — Codec decoded-dict entry, and the duplicated helpers

### THE RULING — codec (cross-lib API growth)

`jsonl_codec` grows exactly two entry points, both defined as the existing
line functions minus the `json.loads`/`json.dumps` step:

```python
def records_from_object(obj: dict) -> list[tuple[str, tuple]]:
    """deserialize_records' validation and expansion, on an ALREADY-DECODED
    object. `deserialize_records(line)` is defined as `records_from_object(_load(line))`."""

def serialize_object(obj: dict) -> str:
    """Validate an object through records_from_object, then canonical-dump it.
    Byte-identical to the serialize_* function that produced it."""
```

Contract, both directions: **the same validator runs**, so an object handed in
is held to exactly the domain a line is held to (`jsonl_codec.py:29-33` states
this posture already). No new rules, no relaxed rules. `deserialize_records`
keeps its signature and becomes a one-line composition — so decoding still has
exactly one dispatch (`jsonl_codec.py:364-383`).

Callers, both of which are the deferral being paid off (`arrival_store.py:290-293`):

- `arrival_store._index_record` → `records_from_object(record["body"])`, killing
  the `json.dumps` → `deserialize_records` round trip.
- `arrival_projection`'s derived-log writer → `serialize_object(record["body"])`.

### THE RULING — `_log_size` / `_has_rows` / `_as_int` / `_stamped_offset_current`

Four helpers, four different answers — the duplication is not one thing:

- **`ArrivalStore._log_size` (`:210-214`) is DELETED.** It re-implements
  `ArrivalLog._size` (`arrival.py:834-838`) on an object the store already
  holds. Promote `_size` to a public `ArrivalLog.size()` and call it. This is a
  dissolution, not a relocation — the better outcome than any shared home.
  `JsonlStore._log_size` (`:523-527`) stays: it has no log object.
- **`_has_rows`** (`arrival_store.py:216-222` / `jsonl_store.py:757-761`):
  becomes one module-level function taking a connection. Home:
  `arrival_projection.has_rows(conn)`, since the re-derivation verb is its
  principal caller; `JsonlStore` imports it. (Alternative home
  `engine/sql_util.py` rejected — that module's charter is *SQL predicate
  builders*, `sql_util.py:1-4`, and a table-existence probe is not a predicate.)
- **`_as_int`**: stays in `jsonl_store` as today. It is six lines, has no denied
  token, and moving it buys nothing.
- **`_stamped_offset_current`**: **stays in `jsonl_store` as the shared currency
  rule**, imported by `arrival_store.py:83` and `probe.py:445` as today. It is
  already mode-parameterized on `offset_key` (`jsonl_store.py:274-314`) — one
  spelling for both log-canonical modes is the property worth keeping, and the
  import carries no denied vocabulary. **Named rejected alternative:** move it to
  `probe.py` (the ratified home for existence checks). Viable, and it would cost
  two lazy imports to dodge the `jsonl_store` → `probe` cycle. Not worth a cycle
  workaround for a function that already reads correctly where it is; revisit
  when `JsonlStore` retires at the sidecar tail.

### REJECTED

- **A `_LogBacked` mixin for the two stores.** They share four small helpers and
  disagree about everything structural (offset triple vs three-field mark,
  rebuild-on-open vs refuse). A mixin would be a shared home for coincidence.
- **Growing the codec a `body=` keyword on the existing functions.** Two
  meanings for one parameter position; a separate name is explicit.
- **Having `arrival_projection` re-implement the body→rows decode.** Two
  definitions of "what a record indexes to" is how the writer and the re-deriver
  end up disagreeing — hence `rows_of_record` in `arrival_projection` and
  `ArrivalStore._index_record` delegating to it.

---

## Q9 — Rule 18 growth and vocabulary

### THE RULING

**Joins `_SCAN_TARGETS` at cut B** (`test_rule_18_arrival_vocabulary_denylist.py:39-45`):

- `libs/engine/src/engine/arrival_projection.py` — **new, born on the arrival
  surface**, so it joins at birth, exactly as `arrival_store.py` did at cut A.
- `libs/store/src/store/derived_log_merge.py` — same reason.
- `libs/store/src/store/merge.py` and `libs/store/src/store/receive.py` —
  **custody moves INTO them at B** (they stop being direct index writers and
  become arrival appenders), which is precisely the rule's own trigger: *"when a
  later slice moves custody into a module, that module joins in the same
  change"* (`:28-29`).

Note a real interaction the implementer will hit: `merge.py:16` names
`docs/RECEIPT_ORDER_FOLD.md` in its docstring, and the detector's PROSE mode
joins underscores, so `RECEIPT_ORDER_FOLD` tokenizes to `receipt`+`order`+`fold`
and the `receipt_order` window **matches** (`:117-124`, `_MAX_TOKENS = 4`). The
scan-target growth therefore *forces* the R1 residue sweep Q4 already requires.
That is the ratchet doing its job; do not allowlist it.

**Does NOT join: `libs/engine/src/engine/jsonl_store.py`. FLAGGED FOR KYLE.**
`plan:arrival-vocabulary-ratchet` says "jsonl_store until cut B", and this design
concludes otherwise: **custody has not left `jsonl_store`.** It remains the write
path for `.jsonl`-canonical stores, which survive until the sidecar/CLI-rebuild
tail (`plan:arrival-wave-2-and-tail`), and its `jsonl_offset`/`jsonl_fact_count`/
`jsonl_tick_count` names are that mode's *honest* keys (Q6). Adding it to
`_SCAN_TARGETS` at B would produce a standing failure resolvable only by a large
allowlist — the exact outcome the rule's scope note warns against (`:24-31`).
**Proposed ruling: jsonl_store's cut is the one that retires `JsonlStore`, not
this one.** Precedent for correcting a brief's premise in a design fact: cut A's
agent corrected the Rule 18 shrink premise (`_ALLOWED` was claimed empty) and the
correction was kept in the ratified record.

**Allowlist shrink at cut B: ZERO. Named, not manufactured.** Both entries
(`:147-160`) survive for reasons outside B's reach:

- `("…/residence.py", "def is_jsonl_canonical")` — gated on the apps caller
  (`apps/loops/.../store.py:142`), and `apps/` is diff-empty for the whole wave.
- `("…/arrival_store.py", "def reanchor")` — the refusing override **must**
  carry the legacy method name or it overrides nothing. Cut B makes that refusal
  **permanent** (retiring the queued log-rewrite ceremony framing in
  `jsonl_store.py:971-982` and `arrival_store.py:487-494`: the messages stop
  saying "until the log-rewrite ceremony is designed" / "a later slice" and say
  that rewriting a log is not an operation in this model). The entry falls away
  only when the base method retires.

Every cut's done-criteria nominally includes an allowlist shrink; B's is zero,
and manufacturing one would violate the shrink-only rule's own purpose.

**Candidate denylist addition surfaced by this design: `fold_order`** (one term).
This cut retires the R1 doctrine, whose vocabulary is "the merged store's fold
order". After B the ordering claim is the arrival ordinal, so `fold_order` as an
identifier on the arrival surface is the retired model coming back. It is
unambiguous, single-concept, and mechanizable exactly like `receipt_order`
already is.

**Not proposed, deliberately:** `rebuild` (a naming-consistency preference, not a
retired model — mechanizing it would be a verdict claim), `out_of_band` (the
arrival-side agreement audit is a later cut's, so the concept still exists), and
the three sense-qualified bans `event` / `merge` / `receipt`, which stay
unmechanized and stay named in `_NOT_MECHANIZED` (`:71`,
`test_the_unmechanized_bans_are_named_rather_than_silently_dropped`).

---

# Draft design-fact body

> Lines marked **[NN]** are NON-NEGOTIABLE — a review brief may quote them
> verbatim as the contract.

**CUT B — PROJECTIONS.** An arrival-canonical store has exactly two projections:
the sqlite index and the derived `.jsonl` log. Both are functions of the arrival
log, both are rebuildable at will, and neither is ever written by anything that
is not deriving it.

1. **[NN]** Re-derivation is a module function, `arrival_projection.rederive_projections(canonical, *, derived_log=False)`.
   It never constructs an `ArrivalStore`; `ArrivalStore` has no re-derivation
   method. It replays the arrival log from **ordinal 0** — never partially.
2. **[NN]** Building an ABSENT projection stays automatic. Re-deriving an
   EXISTING projection is an explicit operator verb. An index that carries state
   with no log stays a dead end: re-derivation cannot manufacture a log.
3. **[NN]** Re-derivation takes the sqlite write lock only, never the arrival
   append lock.
4. **[NN]** The derived log is `<name>.jsonl` beside the `.arrival` — the shape
   `probe` already classifies `derived_log`. It projects **row-class records
   only** (fact/tick/batch); structural records (genesis, key introduction) have
   no line, exactly as the index skips them. Its lines are the `jsonl_codec`
   encoding of those record bodies and **nothing else**; it is derived from the
   arrival log, never from the index.
5. **[NN]** Derived-log line order is a **byte-lexicographic sort**. Line order
   carries no meaning and no reader may attribute one to it. The derived log is
   not a chain-verification surface.
6. **[NN]** The derived log is materialized **on demand only**, never on the
   append path. A stale derived log is not an error. It carries no staleness
   marker; its agreement audit is a re-derive-and-diff set comparison
   (`audit_derived_log`).
7. **[NN]** The git merge driver unions by `(t, id)` over whole canonical lines,
   emits byte-sorted output identical to a fresh derivation, and **REFUSES** two
   cases: same id with different bytes, and a line present in `base` but absent
   from a side. It never opens a store. Registration rides wave 2; there is no
   textual merge driver for `.arrival` — combining lineages is `merge_store`.
8. **[NN]** `merge_store`/`receive_store` keep their signatures and dispatch on
   the target's custody via `probe`. sqlite targets are byte-identical to today;
   jsonl targets REFUSE; arrival targets **append into the arrival log and
   re-derive both projections, never INSERT into the index**.
9. **[NN]** An arrival source replays in **ordinal order**. No event-time field
   is an ordering input anywhere in the merge path.
10. **[NN]** A row id already in the target appends nothing. The arrival log must
    never carry one row id twice.
11. **[NN]** The whole append phase of a merge runs under ONE lock acquisition
    (`ArrivalLog.append_marked_many`, one trailing fsync). An interrupted merge
    is re-run; dedup makes it idempotent.
12. **[NN]** Merged **fact** bodies ride verbatim, fact signature included, never
    re-signed. Merged **tick** bodies carry chain columns and tick signature as
    NULL/absent — chain state is store-local receipt custody and the tick
    signature covers it.
13. **[NN]** A merged record carries no record-level signature: `merge_store` has
    no signer, and no store signs for an observer whose key it does not hold.
    Admission attestation is a later cut's.
14. **[NN]** The merged store's ordering claim is the **target's arrival
    ordinal**, and nothing else. R1-as-doctrine is discarded; determinism per
    direction and content equality survive.
15. **[NN]** `receive_store` refuses to create a store by copy when the target's
    `.arrival` sibling exists.
16. **[NN]** There is no restamp verb. `own_lineage` is restored by catch-up when
    ABSENT and by re-derivation unconditionally — licensed by a consumed
    `_decl.genesis` row, never by the arrival genesis alone. A PRESENT marker
    disagreeing with the log's lineage REFUSES.
17. **[NN]** `reanchor` is a PERMANENT refusal in both log-canonical modes.
    Rewriting a log is not an operation in this model; the queued log-rewrite
    ceremony is retired, not deferred.
18. **[NN]** Re-derivation reproduces every rowid exactly, so outstanding witness
    positions and seals survive it. This holds because the index carries rows
    from no source but the log — the premise this cut's merge rewrite
    establishes — and it is pinned by test, not by assertion.
19. **[NN]** Cut B changes no default, threshold or key in `canonical_audit.py`.
    The offset/prefix custody model moves whole, at cut D.
20. **[NN]** `apps/` is diff-empty. No `.gitattributes` and no `.gitignore`
    change. `preflight.py` untouched.
21. Rule 18 `_SCAN_TARGETS` gains `arrival_projection.py`, `derived_log_merge.py`,
    `store/merge.py`, `store/receive.py`. `jsonl_store.py` does NOT join — its cut
    is the one that retires `JsonlStore` (**flagged: departs from
    plan:arrival-vocabulary-ratchet's "jsonl_store until cut B"**). Allowlist
    shrink is zero, for stated reasons. One denylist candidate: `fold_order`.
22. The R1 residue is swept in the same change: `merge.py`'s doctrine block and
    the **R1 section only** of `docs/RECEIPT_ORDER_FOLD.md`. R2 and R3 stay for
    cut C.

---

# Commit-seam plan

Seven seams, each independently green (`uv run --package engine pytest libs/engine/tests`,
`uv run --package store pytest libs/store/tests`, `pytest tests/architecture`), and
each with `git diff --stat apps/` empty.

**B1 — codec decoded-dict entry + helper dissolutions.**
`jsonl_codec.records_from_object` / `serialize_object`; `deserialize_records`
redefined as their composition. `ArrivalLog.size()` public;
`ArrivalStore._log_size` deleted. `_has_rows` to one home.
`arrival_store._index_record` stops round-tripping through `json.dumps`.
*Green criterion:* no behaviour change; existing suites pass untouched.

**B2 — `arrival_projection.py`: `rows_of_record` + `rederive_projections`
(index only) + own_lineage restore.**
Catch-up's three refusals reworded to name the verb; the absent-`own_lineage`
arm added; `adopt_lineage`'s message repointed. Q5 and Q1's index half.
*Green criterion:* new suite covering all three refusal states, the crash-window
recovery, and the disagreeing-marker refusal.

**B3 — gate item 1: the rowid/witness ratchet.**
`test_rederivation_reproduces_every_rowid`, receipt-group contiguity, and
`verify_chain` after re-derivation — all over stores built **through the arrival
write path plus a declaration ceremony**, with no merge involved. Lands *before*
the merge rewrite so the premise's establishment is visible as a diff in B6.
*Green criterion:* the tests pass on arrival-written stores.

**B4 — the derived log: writer + `audit_derived_log`.**
Byte-sorted canonical bytes helper, `rederive_projections(derived_log=True)`,
set-difference audit.
*Green criterion:* round trip — derive, audit clean; delete a line, audit reports
`missing`; add a line, `extra`.

**B5 — gate item 2: `store/derived_log_merge.py` + the fixture-repo proof.**
Driver, `python -m` entry, and the three `git merge` subprocess tests (clean
union, same-id-different-bytes refusal, loss-against-base refusal). No repo
`.gitattributes`.
*Green criterion:* `git merge` returns 0 on the clean case and non-zero on both
refusals, asserted on the real subprocess.

**B6 — `merge_store`/`receive_store` rewrite + `ArrivalLog.append_marked_many`.**
probe dispatch, the three arms, dedup, one-lock append phase, tick chain strip,
consume-forward re-derivation, `dry_run` without SAVEPOINT. Delete
`test_merge_direction_sets_fold_order_by_receipt`; add the replacements; keep
`test_merge_direction_is_deterministic`. Regenerate conformance merge vectors and
assert an empty diff.
*Green criterion:* the concurrent-merge test (two real processes) shows each id
appended exactly once, **and B3's rowid ratchet is extended to cover a merged
store** — the premise established by this seam, asserted by this seam.

**B7 — residue sweep + Rule 18 growth + permanent reanchor refusal.**
`merge.py`'s R1 block and docstring; `docs/RECEIPT_ORDER_FOLD.md` R1 section and
its table row (R2/R3 untouched); reanchor messages in both stores made permanent;
`_SCAN_TARGETS` grows the four modules; `fold_order` proposed to `_DENIED` (or
carried as a review item if Kyle prefers).
*Green criterion:* `tests/architecture` green with **no allowlist entry added**,
and Rule 17's prose ratchet still green after the doc edit.
