# Slice D — Surfaces: design proposal

Status: **r6 — revised against codex DP-r5 finding, awaiting Kyle's ruling.**
Five separately ratifiable decisions (D0–D4) plus a gate plan and work
packages. r1 written 2026-08-20 against `feat/arrival-libs` @ `eeb05de8`;
r2 revised it against the ten DP-r1 findings (7 MAJOR, 3 minor); the r2
re-verify (`codex-design-r2-stdout.log`) passed 8/10 dispositions, failed
DP-r1-03/-10, and raised DP-r2-01..04 — r3 answers those. All dispositions
are tabled at the end. No source file was modified.

## The contract

Ruled scope, `plan:arrival-libs-slice-D` @ `01M090RAN7Z9FMZX0S5KSEZ322`
(Kyle-ratified 2026-08-17), quoted:

> Wave-1 slice D — SURFACES. `canonical_audit.py`'s WHOLE offset/prefix
> custody model moves to arrival — including the default L1 gate
> (`_check_offset` :429-460, `_suffix_unindexed` :400-427, `_check_last_line`
> :495-540), not just `--deep`; jsonl comparison becomes set-membership;
> blast radius one call site. Seals re-base on `(arrival_lineage, ordinal)`,
> fixing the latent rowid chain-commitment defect (`jsonl_store.py:931-934`).
> DONE-CRITERIA: `preflight.py` UNTOUCHED; `WitnessAggregateUnsupported` +
> A10 VERBATIM; federated-read vs admission distinction protected in the new
> store API (admission signature verification is NEW CODE). GATE: audit
> vectors over a deliberately rebuilt/shuffled index — L1 answers from
> arrival, not byte offsets.

Driving conformance findings: CX-DC-01 (audit still byte-offset), CX-DC-02
(witness positions still projection rowids), CX-DC-03 (seals still rowid
commitments), plus the CX-BR-02 rider (admission signature verification,
deferred once already).

---

## Four things that are true, and what each licenses (r2-corrected)

Each was verified against source; two of r1's four survived review intact,
one was narrowed, one was overturned. What each now licenses is stated
exactly.

**1. The portable witness handle never carried a rowid, and nothing
persists a position.** `durable_handle` (`witness.py:550-568`) emits
`fact:<lineage>/<id>` and refuses to serialize unadopted/genesis positions;
`handle.py`'s checkpoint machinery holds heads in memory only. **Licenses:**
no persisted-position migration, no wire-format change in D1. **Does NOT
license** "all rowid consumers are in libs/engine": app code compares
in-memory `WitnessPosition.rowid` values to attribute a diff baseline
(`apps/loops/src/loops/cli/views/fold.py:1525-1536`) — see D1 and DP-r1-07.

**2. Tick commitments never contained a rowid.** `_tick_envelope`
(`sqlite_store.py:158-166`) signs ten fields; `window_start` and
`fact_cursor` are fact ids. The rowid appears only in how windows and edges
are *resolved*. **Licenses:** signed bytes are untouched in D2 and old seals
can stay verifiable — but only once every resolution site is re-keyed, on
the verification path as well as construction (the r1 "three functions"
blast radius was wrong; see D2), and only with a migration that assigns
correct coordinates (the r1 backfill did not; see D0).

**3. An order-insensitive derived-jsonl audit already exists — with set,
not multiset, semantics.** `arrival_projection.audit_derived_log` (`:343`)
diffs `set[bytes]` digests (`_derived_digests`, `:313`), so a *duplicated*
legitimate line is invisible as an extra line. D3 wires it in and upgrades
the comparison to digest **multisets** (a `Counter`), staying
order-insensitive while making multiplicity part of the claim (DP-r1-08).

**4. `_suffix_unindexed`'s mechanism dissolves; its capability does not.**
(r1 overclaimed here — DP-r1-01.) The check does two jobs
(`canonical_audit.py:383-427`): (a) corroborate that the first line past the
stamped mark is genuinely unindexed — the byte-marker self-report problem,
which arrival's verified anchor genuinely retires; and (b) detect a
**rewound marker** — a mark sitting *below* rows the index already consumed
("the marker was rewound below rows the index consumed, which no writer
produces", `:400-402`). Job (b) is a real detection that must survive.
Arrival-native replacement: the index holds a row with
`arrival_ordinal > consumed_ordinal` — a structural query, stronger than the
one-line probe it replaces. It survives as the named check `rewound` in D3.
Note also that `walk_marked`'s anchor check is *self-consistency only* —
"checked for self-consistency, never for chaining back to genesis"
(`arrival.py:1149`) — so no L1 claim may lean on anchor validation implying
chain integrity; chain-to-genesis remains `--deep`'s scope.

---

## D0 — The projected arrival coordinate (prerequisite for D1–D3)

**Decision.** The derived index gains two columns on both `facts` and
`ticks`:

| column | meaning |
|---|---|
| `arrival_ordinal INTEGER` | the ordinal of the arrival record this row was derived from |
| `arrival_seq INTEGER` | this row's 0-based position within that record's `rows_of_record` expansion |

Spelled in full to match `ARRIVAL_ORDINAL_KEY = "arrival_ordinal"`
(`arrival_store.py:104`) and `ResumeMark.arrival_ordinal` (`arrival.py:682`).
(Open question D0-Q2 keeps the short-form alternative in front of Kyle.)

`(arrival_ordinal, arrival_seq)` is the index's total order, per table.
The two coordinate spaces are **per-table** in legacy stores (facts and
ticks have independent rowid sequences today and no query compares a fact
coordinate to a tick coordinate — windows select facts only, edges select
newest-per-table) and **shared** in arrival-projected stores (the log's
ordinal is one axis for all record types; density per table is not assumed
anywhere).

**Write sites.** Arrival-projected rows get the real coordinate at the two
— and only two — sites that expand a record into rows: `arrival_store`'s
catch-up indexer (`_index_record`, `:342-360`) and
`arrival_projection.rederive_projections` (`:500-509`), both of which hold
the record's `ResumeMark`. Legacy stores get a mirrored coordinate at
append time (below). **Every other insert path is enumerated and closed**
in WP-1: `SqliteStore.append`/`append_tick` (`sqlite_store.py:746`), the
slice/rebirth writers in `libs/store`, and the re-sign/re-anchor UPDATE
paths (`sqlite_store.py:1710-1756` — updates only, no inserts, unaffected).
The shared `FACT_INSERT_SQL`/`TICK_INSERT_SQL` grow the two columns, so an
insert that fails to supply them fails loudly at the statement, not
silently as NULL (DP-r1-03).

**Schema invariants** (DP-r1-03/DP-r2-01 — real database constraints, not
statement discipline):

- **New databases**: `_SCHEMA_STMTS` declares the columns with
  `arrival_ordinal INTEGER NOT NULL`, `arrival_seq INTEGER NOT NULL`, and a
  table-level `UNIQUE (arrival_ordinal, arrival_seq)` per table. The
  invariant lives in the table, so it binds every writer including foreign
  SQL, and NOT NULL moots SQLite's NULLs-pass-unique-indexes hole.
- **Existing databases — table rebuild, the honest SQLite mechanism**:
  retro-added columns cannot be ALTERed to NOT NULL, so the migration is
  the standard rebuild, per table, in ONE transaction:
  `CREATE TABLE facts_new (...full schema incl. NOT NULL + UNIQUE...)`;
  `INSERT INTO facts_new (rowid, ...) SELECT rowid, ..., <coordinate>,
  <seq> FROM facts` (coordinate per mode: `rowid, 0` mirrored, or a join
  against a temp id→(ord, seq) mapping staged from the coordinate provider
  for arrival-canonical); `DROP TABLE facts; ALTER TABLE facts_new RENAME
  TO facts`; same for `ticks`; recreate dependent schema; write the
  `coordinate_axis` marker; commit. No foreign keys exist on these tables,
  so the rebuild needs no FK dance. **Cost, stated:** one O(store) rewrite
  at first post-upgrade writable open — the same order as the coordinate
  walk it absorbs, once per database.
- **The rebuild preserves supported schema artifacts** (DP-r3-02):
  - **Rowids are preserved explicitly** — the copy names `rowid` in both
    column lists. This is not optional politeness: `facts_fts.fact_rowid`
    and the `fts_state.last_rowid` watermark key on exactly these rowids
    (`jsonl_store.py:944-954` documents the poisoning that renumbering
    causes; `vertex_reader.py:2187`), and WP-1 lands while witness/seal
    rowid consumers are still live — a renumbering rebuild would break the
    suites WP-1 is required to keep green. The FTS projection therefore
    survives the migration valid, and the rederivation precedent of
    dropping `facts_fts`/`fts_state` (`arrival_projection.py:492-495`) is
    correctly NOT followed here: rederivation renumbers (DELETE resets the
    rowid counter), the migration copy does not, and each treatment is the
    honest one for its mechanism.
  - **Triggers, indexes, AND dependent views are inventoried and
    recreated** (DP-r4-02): before the DROP, read every `sqlite_schema`
    row with `tbl_name` = the table and `type IN ('trigger','index')`
    (skipping auto-indexes) — and, separately, every `type = 'view'` row
    whose stored `sql` references the table, because a view's `tbl_name`
    is its own name and the table-keyed query structurally cannot find it.
    The view inventory is **dependency-closed, not direct-only**
    (DP-r5-01): view discovery iterates to a fixed point — after finding
    views whose `sql` references the table, re-scan for views whose `sql`
    references any already-collected view's name, until no new view is
    found — because a view over a dropped view is left invalid and can
    itself fail the RENAME's whole-schema reparse. The trigger inventory
    likewise extends over the closure: triggers attached to a collected
    view (INSTEAD OF triggers included) carry `sqlite_schema.tbl_name` =
    the VIEW's name, so the table-keyed query misses them and the view
    drop would silently delete them — they are inventoried by
    `tbl_name IN (<collected view names>)` and replayed with their views.
    The whole closure is DROPped before the rebuild and replayed verbatim
    after the RENAME **in dependency order** (views before the views that
    reference them, triggers after their views), in the same transaction,
    per SQLite's documented generalized rebuild procedure
    (lang_altertable.html#otheralter, steps 3/8/9) — necessary not only
    for preservation but for correctness: a surviving stale view can fail
    the RENAME's schema reparse outright.
    Triggers are supported behavior, not debris — the store deliberately
    reads back committed rows "after any AFTER triggers fired"
    (`sqlite_store.py:702-712`, `:746`).
- The audit's NULL check (D3) remains a backstop for databases that predate
  the migration or were written by a foreign schema copy — a location
  claim, exactly as before.
- **Legacy allocator:** for a store with no arrival log, append assigns
  `arrival_ordinal = COALESCE((SELECT MAX(arrival_ordinal) FROM <table>), 0) + 1`,
  `arrival_seq = 0`, inside the same transaction as the insert — one
  allocator, per table, serialized by the store's existing write
  transaction. For such a store the mirrored coordinate *is* its arrival
  axis: dense, append-ordered, rebuild-invariant is vacuous (nothing
  rebuilds it from a log), and identical to rowid order by construction.

**Migration — mode-aware, not uniform** (DP-r1-02 replaced r1's option (a)):

- **Legacy index (jsonl-/sqlite-canonical, no arrival log):** backfill
  `arrival_ordinal = rowid, arrival_seq = 0`. Correct by construction —
  rowid is that store's append order, and no batch record exists to share
  an ordinal (legacy rows are row-granular).
- **Arrival-canonical index:** rowid backfill is WRONG — a batch expands to
  N rows sharing one ordinal (`arrival_store.py:342`), so `ordinal = rowid`
  mints coordinates the log never issued and collides with the next
  catch-up (the DP-r1-02 counterexample). The migration instead re-derives
  coordinates **from the log**: walk `rows_of_record` over the records up
  to the stamped consumed mark, matching row ids in index order and
  stamping `(ord, seq)`; any mismatch between walk and index refuses into
  the existing escape hatch — `rederive_projections`, which rebuilds the
  index with coordinates written natively. The walk is O(store), once.
- **Migration dispatch — a common upgrader on every writable open**
  (DP-r2-02: `_ensure_index_schema` sits on the projection-rederive path
  only, `arrival_projection.py:479/:544`, while the shared
  `FACT_INSERT_SQL`/`TICK_INSERT_SQL` change hits ordinary `SqliteStore`
  and `JsonlStore` writers immediately, `sqlite_store.py:131`,
  `jsonl_store.py:668`). One module-level function beside the schema
  statements it extends, in `sqlite_store.py` — signature redesigned in r4
  (DP-r3-01: a bare `(conn, mode)` cannot perform the log-derived join —
  neither a connection nor a mode string reaches the arrival log):

  ```python
  ensure_coordinate_schema(
      conn, *,
      mode: Literal["mirrored", "arrival"],
      coordinates: Callable[[], Iterator[tuple[str, str, int, int]]] | None = None,
      # provider of (table, row_id, arrival_ordinal, arrival_seq), where
      # table is "facts" | "ticks"; REQUIRED for mode="arrival", forbidden
      # for mode="mirrored". A provider, not a materialized mapping: the
      # walk runs only if a rebuild is needed. The table namespace is part
      # of the key (DP-r4-01): facts.id and ticks.id are independent
      # primary keys (sqlite_store.py:308), so the same id string may
      # legally name a fact AND a tick from different arrival records —
      # the staging temp table and the rebuild's join both key on the
      # composite (table, row_id). rows_of_record already yields the row
      # type alongside the row, so the closure has the namespace for free.
  )
  ```

  Invoked before any insert SQL runs, by every writer of these tables,
  following the store's existing lazy-migration idiom
  (`_ensure_chain_columns`/`_ensure_fact_signature_column`,
  `sqlite_store.py:1495-1520`). How each route supplies its inputs:
  1. `SqliteStore` — pre-write hooks beside the two existing `_ensure_*`
     migrations; `mode="mirrored"`, no provider. The base class holds
     `self._coordinate_mode = "mirrored"` / `self._coordinate_provider =
     None` and the shared hook reads them, so subclasses override data,
     not the hook.
  2. `JsonlStore` — same inherited hook on its index connection, mirrored
     (its index rows are row-granular append-order).
  3. `ArrivalStore` — **constructor-ordering note, stated honestly**: its
     `ArrivalLog` is constructed only after `super().__init__` opens the
     connection (`arrival_store.py:133-139`), so the upgrader cannot run
     inside the base constructor for this class. It doesn't need to: no
     insert SQL runs during construction. Immediately after `self._log`
     is assigned — before the existing `_ensure_*` calls in its own
     `__init__` tail (`:144-145`) — ArrivalStore sets
     `self._coordinate_mode = "arrival"` and `self._coordinate_provider`
     to a closure walking `self._log` via `rows_of_record` (yielding each
     row's id with its record ordinal and expansion seq), then invokes
     the upgrader once. The pre-write hook remains as the backstop.
  4. `arrival_projection.rederive_projections` — holds `canonical` AND
     `log` before opening the index (`arrival_projection.py:470`);
     `_ensure_index_schema` delegates with `mode="arrival"` and the same
     log-walking provider. (Its own rebuild path deletes and re-derives
     rows with native coordinates, so the provider is only consulted if
     the index predates the columns and is not being rederived.)
  **Mis-mode guard**: a `mode="mirrored"` call against an index whose
  `store_meta` carries `ARRIVAL_LINEAGE_KEY` refuses (the
  `ArrivalCanonicalUnsupported` posture) instead of mis-stamping — a
  plain `SqliteStore` opened on an arrival index file must not mint
  mirror coordinates over a log-owned axis. The marker is authority;
  file suffix is never consulted.
- **Interrupted migration:** the rebuild is one transaction per table and
  the `store_meta` marker (`coordinate_axis = mirrored | arrival`) commits
  inside the second table's transaction. Marker present ⇒ migrated, the
  upgrader no-ops; absent ⇒ the rebuild runs (idempotently — a re-run of a
  completed first table is a no-op rebuild). A crash between the two table
  transactions leaves no half state a reader can observe: the marker is
  absent, so the next writable open re-runs the whole upgrader. There is
  no observable half-migrated state.

**Scope-the-claim corollary.** `arrival_ordinal IS NULL` in a migrated
index is evidence of an out-of-band insert. The check is spelled "this
index holds a row carrying no arrival coordinate" — a location claim,
never "this store is clean" — and after DP-r1-03's statement-level closure
it should never fire except on genuinely foreign writes, which is what an
audit backstop is for.

---

## D1 — Witness re-key

**The new data model** (`witness.py:164-195`):

```python
@dataclass(frozen=True)
class WitnessPosition:
    fact_id: str              # unchanged — the durable handle
    arrival_lineage: str | None  # NEW — the log whose ordinal axis this indexes;
                              # None = no arrival axis (legacy store / storeless bootstrap)
    ordinal: int              # REPLACES rowid — the arrival record cutoff; -1 = empty prefix
    seq: int                  # unchanged meaning — count of rows at-or-before
    lineage: str | None       # unchanged — the store's own_lineage (declaration lineage)
    unadopted: bool           # unchanged
    anchor: TickAnchor | None # unchanged
    store: str                # unchanged
```

`lineage` and `arrival_lineage` are **different identities and both stay**:
`lineage` is what A10 qualifies a portable handle by; `arrival_lineage`
names the coordinate axis. r2 change (DP-r1-09): the no-axis state is
`None`, not `""` — r1's empty-string spelling conflated "legacy store-local
axis" with "storeless bootstrap", and `None` makes axis-absence explicit
and unequal to every real lineage. The same-path replacement guard (below)
fires only when **both** sides carry a real axis.

**Empty-prefix sentinel.** Today `rowid = 0`; arrival ordinals start at 0
(genesis), so the empty prefix is `ordinal = -1`. Genesis projects no rows,
so the selected set is unchanged; `-1` is the honest spelling.
`handle.py:852-855`'s storeless bootstrap moves to
`ordinal=-1, arrival_lineage=None`.

**Selection.** Every `rowid <= ?` cutoff becomes `arrival_ordinal <= ?`
(record-granular arm; see D1-Q1 for the composite alternative). Enumerated
sites, all libs/engine: `store_reader.facts_between` (`:631`),
`facts_by_kind` (`:677`), `query_facts` pagination (`:809-816`),
`declaration._decl_lineage_and_head_on_conn` (`:654-656`),
`witness._resolve_witness_position_on_conn` seq count (`:317`),
`witness.diff_interval_report` (`:624-641`), `witness._resolve_anchor`.
The fold-replay and event-cursor prefix queries
(`sqlite_store.py:1203-1292`, `:1359`, `:1402`, `:2018-2069` — "FOLD REPLAY
ORDER is receipt order (rowid)") re-key to
`ORDER BY arrival_ordinal, arrival_seq` in the same package: they are the
ordering-authority read path the coordinate exists for. `at_rowid` →
`at_ordinal` rides along; leaving it is forbidden residue.

**The app-side rowid consumer** (DP-r1-07 — r1's "all sites inside
libs/engine" was false). `fold.py:1525-1536` picks the diff baseline by
comparing `pos1.rowid`/`pos2.rowid`. Two designs, Kyle rules (merged into
open question D-Q2 with the audit dispatch, since both are apps/ touches):

- **(i) Engine primitive (recommended).** `diff_interval_report` already
  computes the baseline; it gains a `baseline` field naming which input
  position is the lower endpoint. The app reads the field instead of
  comparing coordinates — the knowledge moves to the layer that owns it
  (the comment at `fold.py:1529-1536` documents that only attribution, not
  computation, belongs to the app). App diff: a few lines in one function.
- (ii) A public ordering predicate (`WitnessPosition.precedes(other)`, same
  refusals as `diff_interval_report`) — keeps the comparison app-side but
  re-keyed. Still touches apps/.

**Serialization / compat.** `durable_handle` unchanged, verbatim. No
migration.

**Same-lineage re-resolution** (`verify_position_for_store:466-516`) keeps
its exact structure and both refusal branches **byte-identical, messages
included** (DP-r1-09 tightened this): the new same-path guard — target is
arrival-canonical, position carries a real `arrival_lineage`, and it does
not match the target log's lineage (a store file replaced in place under
the same path) — raises a **separately-typed refusal**
(`WitnessAxisMismatch`, name final at implementation) rather than reusing
the A10 message for a failure A10's prose does not describe. A10's
branches, conditions, and messages do not change.

**Proof the verbatim criteria survive.** `WitnessAggregateUnsupported`
(`witness.py:98-106`) is raised at three sites (`vertex_reader.py:1216`,
`:1613`, `:1692`) on a structural condition mentioning no coordinate; raise
conditions and messages untouched. The A10 refusal (`WitnessLineageMismatch`,
`witness.py:109-119`) keys on `at.lineage`/`at.store`, neither changes.
One nuance is escalated rather than fudged: the class docstring of
`WitnessAggregateUnsupported` says positions "resolve against one store's
rowid axis" — open question D-Q6 rules whether correcting that one stale
word inside the docstring violates "VERBATIM" (raise sites and message
strings stay byte-identical either way).

**Open question D1-Q1 — batch granularity** (unchanged from r1). Record-
granular ordinal cutoff (recommended; a ceremony is atomic; costs `seq:N`
round-trip mid-batch — G-D1-3 pins the ruled answer) vs
`(arrival_ordinal, arrival_seq)` composite cutoff (restores intra-batch
addressing; two-field comparison everywhere).

---

## D2 — Seal re-base

**Blast radius, enumerated honestly** (DP-r1-04 — r1 named three functions;
the truth is every coordinate-resolution site on BOTH paths):

*Construction:*
- `_cursor_rowid(fact_id)` (`:1531-1545`) → `_cursor_ordinal`, selecting
  `(arrival_ordinal, arrival_seq)`; `"" → (-1, 0)` start-of-store sentinel;
  unresolvable cursor still returns `None` (deliberate custody property,
  preserved).
- `_window_hash` (`:1547-1574`) → `WHERE (arrival_ordinal, arrival_seq) > (?, ?)
  AND (arrival_ordinal, arrival_seq) <= (?, ?) ORDER BY arrival_ordinal,
  arrival_seq` (row-value comparison; the era-aware column list and
  `_fact_row_hash` unchanged).
- New-tick state (`:1622-1650`): newest-fact and predecessor-tick edges →
  `ORDER BY arrival_ordinal DESC, arrival_seq DESC LIMIT 1`.
- Latest sealed head / newest fact lookups (`:786`, `:808`) — same re-key.

*Verification (missed in r1):*
- `verify_chain`'s per-tick window count (`:1902-1908`):
  `_cursor_rowid` + `COUNT(*) WHERE rowid > ? AND rowid <= ?` → ordinal
  form.
- The covered-total count (`:1929-1935`): same re-key.
- The tick-scan ordering (`:1856`, `:1735`, and the re-anchor scan `:1710`)
  → `ORDER BY arrival_ordinal, arrival_seq` (scan order is presentation
  order for verification; re-anchor's UPDATE-by-rowid plumbing may keep
  rowid as a row *address*, which is the one allowlisted use — addressing a
  row, never ordering or windowing rows).

WP-3's fence closes with a ratchet grep: no `rowid` in any ORDER BY, range
WHERE, or COUNT window inside `sqlite_store.py` outside the allowlisted
row-address sites.

**What does not change: the signed bytes.** `_tick_envelope` untouched;
`window_start`/`fact_cursor` remain fact ids.

**Backward verifiability — an empirical claim with a precondition.** After
D0's *mode-aware* migration, `(arrival_ordinal, arrival_seq)` order equals
rowid order for every correctly-derived existing index: legacy rows mirror
rowid by construction, and arrival-projected rows were inserted in record
order, `rows_of_record` order within a record — the same traversal that
assigned their rowids. r1's version of this claim was falsified by its own
uniform backfill (DP-r1-02); it holds now *because* the migration
re-derives coordinates from the log for arrival stores. It remains an
empirical claim: G-D2-1 byte-compares window hashes on a pre-D sealed
fixture, and G-D2-2 does it across a batch-bearing store specifically.

**The latent defect this fixes** (`jsonl_store.py:920-940`, CX-DC-03):
window membership currently rests on rowid, an axis a rebuild regenerates;
the property survives rebuilds only because `rederive_projections` replays
from zero in order — an accident of replay strategy, not a commitment.
After D2 the window is defined on the arrival coordinate. Sweep item: that
docstring's rowid-reproduction rationale is superseded and is rewritten in
the same change.

---

## D3 — Audit re-base

### Per-check disposition

| legacy check | disposition | arrival replacement |
|---|---|---|
| `index` (`:340-353`) | TRANSLATE unchanged | index exists and is readable |
| `_check_offset` (`:430-461`) | **DISSOLVE → re-found** | `consumed`: the index's stamped `ResumeMark` vs the log's head ordinal. Claim: "index is behind arrival by N record(s), consumed through ordinal X." |
| `_suffix_unindexed` (`:383-427`) | **mechanism dissolves, capability survives** (DP-r1-01) | Job (a), unindexed-suffix corroboration: retired — the mark's anchor is verified structurally by the substrate. Job (b), rewound-marker detection: survives as `rewound` — any index row with `arrival_ordinal > consumed_ordinal` means the mark sits below consumed rows, which no writer produces. `beyond_offset` on `Check` is replaced by coordinates (below). |
| `_check_counts` (`:464-492`) | TRANSLATE + strengthen | stamped counters vs `COUNT(*)`; plus NULL-coordinate backstop (migrated indexes). |
| `_check_last_line` (`:495-542`) | TRANSLATE | `consumed_edge`: read the record at the consumed ordinal via the verified anchor (mechanism below), expand with `rows_of_record`, `row_matches` every row. `_last_line`'s backward byte-scan (`:290-310`) dissolves. |
| jsonl comparison (`--deep`, `_deep_checks:605-704`) | **wire + strengthen** | `audit_derived_log`, upgraded to digest **multisets** (order-insensitive, multiplicity-preserving — DP-r1-08). |

### The L1 mechanism, stated honestly (DP-r1-05 rewrote this)

r1 claimed L1 "never reads a byte offset" and could get the consumed record
"through the anchor" from `walk_marked`. Both were wrong: `walk_marked`
yields records *after* the anchor (`arrival.py:1206-1230`), and anchor
validation itself opens the file and seeks to `mark.arrival_offset`
(`_record_ending_at`, `arrival.py:1173-1180`).

The honest design: a small substrate API, `ArrivalLog.anchor(mark) ->
dict | None` — the already-existing `_anchor_for` validation
(`arrival.py:1149-1174`) surfaced as a public verb returning the **validated
anchor record itself** (None on rejection, same semantics the walk uses).
One new public method exposing existing machinery; no new validation logic.

The claim is then **scoped correctly**: the byte offset is an internal,
*verified seek hint* — trusted only after the record found there passes the
anchor checks (shape, lineage, ordinal, authority) — and L1 makes **no
byte-offset custody claim**: no `Check` cites an offset, and no audit
verdict depends on unverified byte positions. L1 does open the log file;
what it never does is unbounded work or offset-trusting reads. The
substrate note stays: anchor validation is self-consistency, not
chain-to-genesis (`arrival.py:1149`) — chain integrity is `--deep`'s claim.

Cost model: `consumed_edge` = one verified anchor read (O(1 record));
`consumed` = suffix count via `walk_marked` (O(records behind), zero on a
healthy store); `rewound` = one indexed query. **L1 must not call
`ArrivalLog.read` or `ArrivalLog.walk`** (both walk from zero by design,
`arrival.py:1040-1053`); G-D3-2 asserts bounded work behaviorally.

### The L1 / `--deep` split

- **L1 (`audit_agreement`)**: `index` · `consumed` · `rewound` · `counts` ·
  `consumed_edge`. Bounded: one verified record + suffix count + O(1)
  queries.
- **`--deep` (`audit_deep`)**: L1, then full `ArrivalLog.walk()` (density,
  hashes, ordinals, chain linkage), row-by-row index comparison over
  `rows_of_record`, multiset `audit_derived_log` for the derived `.jsonl`,
  tick chain re-derived from log content. `verify_authorship` stays a
  separate verb (authorship claim, not agreement claim).

### Scope-the-claim discipline

Every `Check` emits a location claim. `beyond_offset: bool` is replaced by
`behind_by: int` and `at_ordinal: int`; `rewound` reports the offending
coordinate. No check may assert intact/clean/safe; the strongest positive
form stays "N fact(s), M tick(s) accounted for".

### Blast radius — the one call site

`apps/loops/src/loops/commands/store.py:141-163` returns `None` for a
non-jsonl-canonical store, so arrival stores are unaudited through the CLI
today. Growing that dispatch an arrival arm **is** the plan's "blast radius
one call site" — and an apps/ touch under the arc's diff-empty scope law.
Open question D-Q2 (now jointly with the fold.py baseline touch from D1).
Recommendation unchanged: library-side complete, plus the dispatch arm as a
ruled, receipted exception — an audit surface nothing can reach is not a
surface.

---

## D4 — Admission signature verification (CX-BR-02 rider)

**The situation.** `merge_store` admits foreign records with no signature
verification (`merge.py:526-532`, `arrival.py:694-699` both say so). The
rider has rolled once. r1's arm 1 was **UNSOUND as designed** (DP-r1-06):
`verify_authorship(source_log, verify)` checks arrival-record *envelope*
signatures over the whole source log — but merge admits *rows*, carries the
**fact-row signature** ("a per-observer authorship claim over content only,
carried verbatim and never re-signed", `merge.py:512-515`), dedups before
appending (`_entries_for`, `:463-499`), and can split batches. So r1's arm
verified the wrong commitment over the wrong set: a forged carried
signature could enter unseen, and a bad envelope on a *non-admitted* record
could refuse a valid admission.

**Arm 1, redesigned — verify the exact post-dedup admission rows:**

1. Build the source's key registry with a **selective** walk — a new engine
   function `key_registry(log, verify)`, specified exactly (DP-r2-03: a
   straight refactor of `verify_authorship`'s loop would verify every
   signed envelope, `arrival.py:1597/:1627`, and a deduplicated record with
   a bad envelope would then refuse an admission it isn't part of —
   violating G-D4-2 — while skipping all envelope verification would admit
   forged key introductions):
   - walk the whole log **structurally** (`ArrivalLog.walk` — density,
     hashes, chain linkage come free; this much covers every record);
   - **verify envelope signatures ONLY for registry-forming records**:
     the genesis (self-certifying against its own `body["key"]`,
     `arrival.py:1604-1616`) and every `KEY_INTRODUCTION_KIND` record —
     including the authorization rule that the introduction's own
     signature must verify under a key already valid for the introducing
     record's observer before the named key joins the registry
     (`arrival.py:1627-1648`). A registry-forming record that fails
     verification refuses the merge: the key history itself is not
     trustworthy;
   - **do NOT verify any other record's envelope** — ordinary records'
     envelope signatures are no part of the admission claim (G-D4-2);
   - record each key's **introduction ordinal**; the registry's validity
     rule is the ruled slice-A clause verbatim: a key is valid at position
     N iff introduced at a position < N, or N is genesis and the record is
     self-certifying.
   `verify_authorship` becomes a consumer of the same registry machinery
   plus its existing verify-every-envelope loop, so the two verbs share
   one placement-rule implementation.
2. For each **admitted** (post-dedup) fact row carrying a non-NULL
   signature: verify it against `fact_commitment_hash` — the same
   content-only commitment the live emit path signs
   (`sqlite_store.py:254-278`) — under a key valid for the row's observer
   at the row's source position. Refusal class on failure; nothing is
   appended.
3. **Unsigned admitted rows**: admitted, era-aware, making no claim — the
   same NULL-era posture merge already documents.
4. **Split batches**: verification is per-row, so batch regrouping is
   irrelevant to it — the dedup/regroup question dissolves.
5. **Deduplicated (non-admitted) rows**: never verified — a bad signature
   on a record the merge does not admit cannot refuse the merge.

**Honest scope note:** this is bigger than r1's arm 1 — one new engine
function (registry extraction), one merge parameter, one refusal class, and
a per-row verification loop keyed by observer+position. It is still
libs-only, still callable-injected (`Verify`, `arrival.py:137` — the
no-`libs/sign`-dependency claim survives review, DP-r1-06 confirmed it),
and still the half of admission verification that is implementable now.
**Arm 2** (target-side trust: verifying against the *target's* key chain)
remains blocked on key-introduction transport — merge carries none
(no `KEY_INTRODUCTION_KIND` in `merge.py`) — wave-2 territory. **Arm 3**
remains full carve with a fresh receipt.

**Recommendation: redesigned arm 1, opt-in.** With the corrected claim
stated exactly: it verifies that every admitted signed row's authorship
claim verifies under the source's own key history — source
self-consistency, not target-operator trust. The refusal message and
docstring carry that scope. D4-Q1 (legacy source with no arrival log:
explicit no-claim, recommended, vs refusal) stands.

---

## Gate plan

Independent gate agent; re-derives the oracle from scratch; pointer branch
`slice/D-gate`. (r2: gates for every DP-r1 gap; the impossible and
non-discriminating r1 gates replaced — DP-r1-10.)

**G-D0-1 — the shuffled index (the ruled gate item).** A natural rebuild
cannot produce one (`rederive_projections` replays in order), so the gate
builds a **deliberate permuted-insert harness** — index rows inserted in
permuted record order so rowid order and arrival order disagree.
Assertions: L1 passes; every witness position, seal window, audit check,
and `verify_chain` answer identical to the unshuffled store. Written first;
used by every later package.
**G-D0-2** — deliberately rebuilt index: outstanding positions and seals
valid.
**G-D0-3** — migration of an existing **batch-bearing arrival-canonical**
index: coordinates equal the log's (the DP-r1-02 counterexample as a test);
subsequent catch-up appends collide with nothing.
**G-D0-4** — interrupted migration: kill between schema-add and stamp;
reopen; the store answers correctly and the marker semantics hold (no
observable half-state).
**G-D0-5** — invariant enforcement **by the table**: on a migrated (rebuilt)
and on a freshly-created database, a raw `conn.execute` INSERT with a
duplicate `(arrival_ordinal, arrival_seq)` raises `IntegrityError`
(UNIQUE), and one with NULL in either coordinate raises `IntegrityError`
(NOT NULL) — foreign SQL included, no store-layer code in the loop; legacy
allocator monotonic under interleaved fact/tick appends in one transaction.
**G-D0-6** — ordinary legacy opens migrate (the DP-r1-10 re-fail gap):
existing sqlite-canonical and jsonl-canonical fixture databases opened
through their normal public constructors and appended to via the public
API — the upgrader ran before the first insert, coordinates are correct
and constrained, prior rows carry the mirror backfill, and a read-only
open of an unmigrated database still answers reads.
**G-D0-7** — arrival dispatch route 3 (DP-r3-03): an existing UNMIGRATED
batch-bearing arrival-canonical index opened through `ArrivalStore`'s
public constructor — coordinates equal the log's, constraints present,
appends land correctly after.
**G-D0-8** — arrival dispatch route 4 (DP-r3-03): the same unmigrated
fixture through the rederivation entry point — migrated/rederived
coordinates identical to G-D0-7's, proving the two routes with different
log access agree.
**G-D0-9** — trigger survival (DP-r3-02): a fixture with an AFTER INSERT
trigger on `facts` (the read-back contract `sqlite_store.py:702-712`
supports) migrates; the trigger still exists in `sqlite_schema` and still
fires on the next public-API append.
**G-D0-10** — FTS/rowid survival (DP-r3-02): a fixture with populated
`facts_fts` + `fts_state` migrates; every `fact_rowid` still resolves to
the same fact (rowids preserved byte-for-byte), search answers
identically, and incremental indexing resumes from the watermark without
skipping or double-indexing.
**G-D0-11** — mis-mode refusal: a plain `SqliteStore` opened on an
arrival-marked index refuses to mirror-stamp it.
**G-D0-12** — cross-table id collision (DP-r4-01): an arrival fixture
containing a fact and a tick sharing the same id string, from different
records; migration assigns each its own distinct correct coordinate
(composite `(table, row_id)` staging proven discriminating).
**G-D0-13** — dependent-view survival, closure-deep (DP-r4-02 +
DP-r5-01): fixture carries `v1` over `facts`, `v2` over `v1`, and an
INSTEAD OF trigger on `v1`; post-migration all three remain present in
`sqlite_schema`, `v1` and `v2` answer identically, the INSTEAD OF
trigger still fires with identical behavior, and the RENAME completes.

**G-D1-2** — `WitnessAggregateUnsupported` at all three sites,
messages unchanged; A10 refusal messages byte-identical. Pinning tests
(`test_witness_position.py`, `test_diff_interval_report.py`,
`test_query_facts.py`, `test_fold_at.py`) pass untouched.
**G-D1-3** — `seq:N` round-trip across a batch boundary, pinning the ruled
D1-Q1 arm.
**G-D1-4** — same-path store-replacement: new typed refusal fires;
A10 and the unadopted refusal unchanged (their tests prove it).
**G-D1-5** — position equivalence (replaces r1's non-discriminating
G-D1-1): for a corpus store, every fact's resolved position selects the
same prefix row-set before and after the re-key; `durable_handle` output
unchanged as a corollary.
**G-D1-6** — fold diff baseline: reversed `--diff B..A` attributes the
baseline identically pre/post re-key (whichever D-Q2 design is ruled).

**G-D2-1** — pre-D sealed fixture: `verify_chain` green AND each window
hash byte-equal to the legacy computation.
**G-D2-2** — a seal spanning a batch record on a batch-bearing store:
window membership and hash identical before/after migration.
**G-D2-3** — unresolvable cursor still hashes as empty.
**G-D2-4** — verification under permutation: `verify_chain`'s window
counts and verdicts identical on the shuffled index (the DP-r1-04
verification-side residue, gated).
**G-D2-5** — rowid ratchet: no ORDER BY / range / COUNT on rowid in
`sqlite_store.py` outside allowlisted row-address sites (shrink-only
allowlist).

**G-D3-1** — L1 detects: index behind arrival; out-of-band insert; edit to
the last consumed row; **rewound marker** (mark ordinal < max indexed
ordinal) — each with the expected coordinate in the message.
**G-D3-2** — bounded work, deterministically instrumented (DP-r2-04: no
timing oracle): the harness counts record verifications (a test-scoped
counter on the substrate's record-verification seam) and asserts exact
bounds — on a healthy N-record store, L1 verifies exactly the anchor
record (plus zero suffix records); on a store K records behind, exactly
1 + K; `--deep` verifies N. L1 calls neither `ArrivalLog.read` nor
`ArrivalLog.walk` (asserted by the same instrumentation).
**G-D3-3** — torn arrival tail: L1 reports "behind", never "tampered".
**G-D3-4** — derived `.jsonl` reordered: multiset audit agrees; a
**duplicated line** is detected (the DP-r1-08 case); a removed line is
detected.

**G-D4-1** — forged carried signature on an admitted row: merge refuses.
**G-D4-2** — bad envelope/signature on a row the dedup drops: merge
succeeds (verification covers exactly the admission set).
**G-D4-3** — split batch: surviving rows verified, admission succeeds;
legacy source: admits with explicit no-claim (per D4-Q1 ruling).
**G-D4-4** — forged key introduction (DP-r2-03): a source log whose
key-introduction record carries a signature no previously-valid key
verifies refuses the merge — even when every admitted row is ordinary;
paired with G-D4-2 this pins the selective boundary exactly
(registry-forming envelopes verified, ordinary envelopes not).

**Fence check, every package:** `git ls-files` diff confined to
`libs/engine/`, `libs/store/` — plus exactly the ruled D-Q2 apps/ touches
if granted.

---

## Work packages

Sequenced by dependency; each is a fence for one implementer.

**WP-1 · the coordinate (D0).** `sqlite_store.py`: the
`ensure_coordinate_schema(conn, mode)` upgrader (table rebuild + marker),
new-DB schema constraints, `FACT_INSERT_SQL`/`TICK_INSERT_SQL`, legacy
allocator in `append`/`append_tick`, pre-write hook wiring beside the two
existing `_ensure_*` migrations. `jsonl_store.py`: the same hook on its
index connection. `arrival_store.py`: upgrader at open + catch-up indexer
coordinates. `arrival_projection.py`: `_ensure_index_schema` delegation +
`rederive_projections` native coordinates. Closure sweep of every other
insert path (libs/store slice/rebirth writers). Plus the permuted-insert
harness (G-D0-1), the batch-bearing migration fixture (G-D0-3), and the
normal-open fixtures (G-D0-6), both arrival dispatch routes (G-D0-7/8),
and the trigger/FTS survival fixtures (G-D0-9/10). Suites green on this
package alone — which the rowid-preserving copy is load-bearing for:
witness/seal rowid consumers are still live until WP-2/3.

**WP-2 · witness + read path (D1).** `witness.py`, `store_reader.py`
(`at_rowid` → `at_ordinal`, three query methods), `declaration.py:654-656`,
`handle.py:852-855`, `vertex_reader.py` `at=` selectors, and the
fold-replay/event-cursor ORDER BY sites in `sqlite_store.py`
(`:1203-1292`, `:1359`, `:1402`, `:2018-2069`). The new typed same-path
refusal. If D-Q2 rules design (i): the `baseline` field on
`diff_interval_report` + the one `fold.py` consumer change.
Residue sweep: coordinate vocabulary in docstrings.

**WP-3 · seals (D2).** `sqlite_store.py` seal construction AND verification
(`:786`, `:808`, `:1531-1650`, `:1710`, `:1735`, `:1856`, `:1902-1935`),
the rowid ratchet (G-D2-5), and the superseded `rederive_projections`
docstring rationale.

**WP-4 · audit (D3).** `canonical_audit.py` (L1 rewrite: `consumed`,
`rewound`, `counts`, `consumed_edge`; `Check.beyond_offset` →
coordinates), the `ArrivalLog.anchor(mark)` substrate verb, multiset
upgrade + wiring of `audit_derived_log` into `--deep`, and — if D-Q2 rules
it in — the dispatch arm in `apps/loops/commands/store.py`.

**WP-5 · admission (D4, if arm 1 is ruled in).** `key_registry` in
`arrival.py` — the SELECTIVE walk specified in D4 (registry-forming
envelopes verified, ordinary envelopes not; shared placement-rule
implementation with `verify_authorship`) —
`libs/store/src/store/merge.py` per-row verification + refusal class.
Independent of WP-2/3; parallel-safe.

**Ordering:** WP-1 → {WP-2, WP-3, WP-5} → WP-4. WP-4 last because it
audits what the others establish.

**Vocabulary ratchet — candidate additions:** `rowid` as a public
coordinate name (allowlist: `sqlite_store` row-address plumbing only),
`at_rowid`, `beyond_offset`, `consumed-offset`, `receipt order` as an
ordering-authority phrase.

---

## Open questions for Kyle

1. **D1-Q1 — batch granularity.** Record-granular ordinal cutoff
   (recommended) or `(arrival_ordinal, arrival_seq)` composite cutoff?
2. **D-Q2 — the apps/ scope law, now TWO touches** (r2 widened: DP-r1-07).
   (a) the audit dispatch arm (`commands/store.py:141-163`) and (b) the
   fold diff-baseline consumer (`cli/views/fold.py:1525-1536`, required by
   the removal of `WitnessPosition.rowid`). Recommended: both as ruled,
   receipted exceptions, with design (i) (engine `baseline` field)
   minimizing (b) to reading a field. Alternative: library-only, leaving a
   broken or shimmed app path — not actually available for (b), which makes
   this a forced ruling: (b) happens; the ruling is whether it is receipted
   as an exception or D is blocked on the scope law.
3. **D4 arm.** Redesigned arm 1 (post-dedup row verification, recommended;
   honestly bigger than r1's version), arm 2 (blocked, wave 2), or arm 3
   (carve with fresh receipt)?
4. **D4-Q1** (if arm 1) — legacy source with no arrival log: explicit
   no-claim (recommended) or refusal?
5. **Verbatim-vs-staleness A — `preflight.py` UNTOUCHED.** One-sentence
   docstring truth-up (`preflight.py:381-393`, "agreement audit is a later
   cut") as a ratified exception with byte-identical behavior, or leave
   stale for wave 2?
6. **Verbatim-vs-staleness B — `WitnessAggregateUnsupported` docstring**
   says "rowid axis". Correct the one stale word (raise sites + message
   strings byte-identical), or byte-verbatim including the stale word?
7. **D0-Q2 — column naming.** `arrival_ordinal`/`arrival_seq` in full
   (recommended) or short forms?
8. **D0 migration cost** (r3 restated — the cost grew): the migration is
   now a one-transaction **table rebuild** per table (the only SQLite
   mechanism that yields real NOT NULL + UNIQUE constraints on existing
   tables), absorbing the coordinate walk in the same pass — an O(store)
   rewrite at first post-upgrade *writable* open, once per database;
   read-only opens of unmigrated databases still answer. Accept
   (recommended), or gate the rebuild behind an explicit ceremony?

(r1's Q8 — the uniform-backfill option menu — is withdrawn: option (a) was
falsified by DP-r1-02; the mode-aware migration in D0 replaces it. r1's Q3
premise is corrected per DP-r1-06.)

---

## DP-r1 disposition table

| finding | severity | disposition in r2 |
|---|---|---|
| DP-r1-01 | MAJOR | **Redesigned.** `_suffix_unindexed` split into two jobs; rewound-marker capability survives as the arrival-native `rewound` check (D3); anchor self-consistency limits stated ("Four things" §4). |
| DP-r1-02 | MAJOR | **Redesigned.** Uniform backfill withdrawn; mode-aware migration — rowid mirror for genuinely-legacy indexes, log-derived coordinates (with rederive escape hatch) for arrival-canonical (D0). Counterexample gated as G-D0-3. |
| DP-r1-03 | MAJOR | **Redesigned in r2; FAILED re-verify; closed in r3** via DP-r2-01/02 below — table-level constraints and a universal writable-open upgrader replace the r2 statement-level story (D0). |
| DP-r1-04 | MAJOR | **Redesigned.** Full construction+verification enumeration incl. `verify_chain` :1902/:1929, scans :1710/:1735/:1856, heads :786/:808; rowid ratchet G-D2-5; verification-under-permutation gate G-D2-4 (D2, WP-3). |
| DP-r1-05 | MAJOR | **Redesigned.** `ArrivalLog.anchor(mark)` public verb; offset re-described as verified internal seek hint; claim scoped to "no byte-offset custody claim"; G-D3-2 rewritten as bounded-work assertion (D3). |
| DP-r1-06 | MAJOR | **Redesigned.** Arm 1 now verifies post-dedup admission rows' carried fact signatures (`fact_commitment_hash`) under source key registry (`key_registry` extraction); unsigned/split/dedup cases defined; scope growth stated honestly; arm choice re-presented to Kyle (D4, Q3). |
| DP-r1-07 | MAJOR | **Redesigned + escalated.** `fold.py:1525-1536` named; engine `baseline` field recommended; folded into D-Q2 as a forced scope ruling; G-D1-6 gates behavior (D1). |
| DP-r1-08 | minor | **Redesigned.** `audit_derived_log` comparison upgraded to digest multisets; duplicate-line detection gated in G-D3-4 (D3, "Four things" §3). |
| DP-r1-09 | minor | **Redesigned.** Separately-typed `WitnessAxisMismatch` refusal; A10 branches/messages byte-identical; `arrival_lineage: str | None` replaces the `""` conflation (D1). |
| DP-r1-10 | minor | **Redesigned in r2; FAILED re-verify; closed in r3** — G-D0-5 now asserts table-enforced refusals (raw-SQL IntegrityError), G-D0-6 covers ordinary legacy public-API opens, G-D4-4 covers forged key introductions, G-D3-2's timing proxy removed. |

r2 re-verify (`codex-design-r2-stdout.log`): DP-r1-01/02/04/05/06/07/08/09
PASS; the two FAILs above closed by r3. New findings:

| finding | severity | disposition in r3 |
|---|---|---|
| DP-r2-01 | MAJOR | **Redesigned.** NULL/uniqueness enforcement moved into the table itself: native NOT NULL + UNIQUE for new DBs; one-transaction table rebuild for existing DBs (the only SQLite mechanism yielding retro constraints), absorbing the coordinate backfill in the same pass; cost stated and routed to Kyle as restated Q8 (D0). |
| DP-r2-02 | MAJOR | **Redesigned.** `ensure_coordinate_schema(conn, mode)` in `sqlite_store.py`, invoked by every writable constructor/pre-write hook (SqliteStore, JsonlStore index, ArrivalStore, `_ensure_index_schema` delegating) following the existing `_ensure_*` lazy-migration idiom; mode explicit or derived from the store's own `ARRIVAL_LINEAGE_KEY` marker; G-D0-6 gates normal public-API legacy opens (D0, WP-1). |
| DP-r2-03 | MAJOR | **Redesigned.** `key_registry` specified as a selective walk: structural over everything; envelope verification ONLY for genesis + key-introduction records including the previously-valid-key authorization chain (`arrival.py:1627-1648`); ordinary envelopes never verified; introduction ordinals recorded, slice-A validity clause verbatim; G-D4-4 (forged introduction) added beside G-D4-2 (D4, WP-5). |
| DP-r2-04 | minor | **Redesigned.** G-D3-2's timing proxy deleted; mandatory record-verification call-count instrumentation with exact bounds (anchor-only healthy, 1+K behind, N for `--deep`). |

r3 re-verify (`codex-design-r3-stdout.log`): DP-r2-01/03/04 + DP-r1-03/10
PASS; DP-r2-02 FAIL, closed by DP-r3-01 below. D3 and D4 ruled SOUND;
D0 remained UNSOUND on migration mechanics. r4 answers:

| finding | severity | disposition in r4 |
|---|---|---|
| DP-r3-01 | MAJOR | **Redesigned.** Upgrader signature gains an explicit coordinate provider (`coordinates: Callable[[], Iterator[(row_id, ord, seq)]]`, required for arrival mode, forbidden for mirrored); per-route supply specified, including ArrivalStore's constructor-ordering reality (log constructed after the base connection opens; upgrader runs post-log-assignment, before the existing `_ensure_*` tail, with the pre-write hook as backstop) and rederivation's direct provider; mis-mode guard refuses mirror-stamping an arrival-marked index (G-D0-11). |
| DP-r3-02 | MAJOR | **Redesigned.** Rebuild copies `rowid` explicitly in both column lists — chosen over the rederivation FTS-drop precedent because the copy (unlike rederivation's DELETE) can preserve rowids, FTS stays valid, and live rowid consumers keep WP-1's suites green; triggers and indexes inventoried from `sqlite_schema` and replayed verbatim post-RENAME in the same transaction; gated by G-D0-9 (trigger fires after migration) and G-D0-10 (FTS resolves and resumes correctly). |
| DP-r3-03 | minor | **Redesigned.** G-D0-7 (ArrivalStore public constructor on an unmigrated batch-bearing index) and G-D0-8 (rederivation entry point on the same fixture, results identical) cover the two arrival dispatch routes independently. |

r4 re-verify (`codex-design-r4-stdout.log`): DP-r3-02/03 PASS (rowid
preservation, trigger/index replay, route gates all confirmed against
SQLite's documented rebuild procedure); DP-r3-01 FAIL solely on the
provider key shape, closed by DP-r4-01 below. D3 and D4 remain SOUND.
r5 answers:

| finding | severity | disposition in r5 |
|---|---|---|
| DP-r4-01 | MAJOR | **Redesigned.** Provider yields `(table, row_id, arrival_ordinal, arrival_seq)`; staging temp table and rebuild join key on composite `(table, row_id)` — facts.id and ticks.id are independent primary keys, so the bare-id mapping was ambiguous; `rows_of_record` already yields the row type, so the closure has the namespace for free. Gated by G-D0-12 (fact and tick sharing one id string, distinct coordinates). |
| DP-r4-02 | MAJOR | **Redesigned.** Rebuild inventory extended to dependent views, discovered via `sqlite_schema.sql` content (a view's `tbl_name` is its own name — the table-keyed query structurally misses them), dropped before and replayed verbatim after the rebuild per SQLite's generalized procedure (steps 3/8/9); stale-view RENAME-reparse failure mode noted. Gated by G-D0-13 (pre-existing view over facts queryable post-migration). |

r5 re-verify (`codex-design-r5-stdout.log`): DP-r4-01/02 both PASS; one
new finding. r6 answers:

| finding | severity | disposition in r6 |
|---|---|---|
| DP-r5-01 | MAJOR | **Redesigned.** View inventory made dependency-CLOSED: fixed-point iteration over view-name references in `sqlite_schema.sql` (views-on-views collected transitively); trigger inventory extended to triggers whose `tbl_name` names any collected view (INSTEAD OF included — the view drop would otherwise silently delete them); the whole closure dropped and replayed in dependency order within the one transaction. G-D0-13 extended: v2-over-v1-over-facts plus an INSTEAD OF trigger on v1, all surviving with identical behavior. |
