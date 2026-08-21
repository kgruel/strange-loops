# Slice D — Surfaces: design proposal

Status: **proposed, awaiting Kyle's ruling.** Five separately ratifiable
decisions (D0–D4) plus a gate plan and work packages. Written 2026-08-20
against `feat/arrival-libs` @ `eeb05de8`. No source file was modified.

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

## Four things that are already true, and make D smaller than it looks

Each was verified against source before anything below was designed. Each
removes work the plan's prose implies.

**1. The portable witness handle never carried a rowid.**
`durable_handle` (`witness.py:550-568`) emits `fact:<lineage>/<id>` and
refuses to serialize unadopted/genesis positions. The rowid lives only
inside the in-memory `WitnessPosition`. Nothing in the tree writes a
position to disk: `handle.py`'s `VertexHandle` checkpoint machinery holds
`FactHead`/`TickHead`/`CursoredFact` in memory on an open handle
(`handle.py:196-240`) and never serializes them — the only `open(`-class
call in that module is `sqlite3.connect` at `handle.py:291`. **There is
therefore no persisted-position migration story and no wire-format change
in D1.** The compat surface is one process's lifetime.

**2. Tick commitments never contained a rowid.**
`_tick_envelope` (`sqlite_store.py:158-166`) signs ten fields: id, name, ts,
since, origin, payload, prev_hash, window_start, fact_cursor, window_hash.
`window_start` and `fact_cursor` are **fact ids**. The rowid appears only in
`_cursor_rowid` (`:1531`) and `_window_hash`'s selection clause (`:1547`),
i.e. in how the window's row *set and order* are resolved — never in the
bytes. **D2 can therefore preserve signed bytes exactly and keep every
existing sealed chain verifiable**, provided the re-keyed selection
enumerates the same rows in the same order. It does (see D2).

**3. The set-membership jsonl comparison already exists.**
`arrival_projection.audit_derived_log` (`:343`) re-derives the log and diffs
digest **sets** (`_derived_digests`, `:313`). Slice D does not write it; D
*wires* it into the audit surface. The dissolution test kills a whole
proposed component here.

**4. `_suffix_unindexed` exists only because the byte offset was an
unverifiable self-report.** Its docstring says so: it turns "the suspect's
own marker says so" into a claim the log supports. Under arrival, the
consumed mark is structurally corroborated by the substrate —
`ArrivalLog.walk_from`/`walk_marked` re-verify the anchor record at the
mark's ordinal and reject a mark that does not match (`arrival.py:1165-1174`),
and the records past it are enumerable directly. The corroboration probe has
no job left. **`_suffix_unindexed` dissolves; it does not translate.**

---

## D0 — The projected arrival coordinate (prerequisite for D1–D3)

**Decision.** The derived index gains two columns on both `facts` and
`ticks`:

| column | meaning |
|---|---|
| `arrival_ordinal INTEGER` | the ordinal of the arrival record this row was derived from |
| `arrival_seq INTEGER` | this row's 0-based position within that record's `rows_of_record` expansion |

Spelled in full to match the vocabulary already in the tree —
`ARRIVAL_ORDINAL_KEY = "arrival_ordinal"` (`arrival_store.py:104`) and
`ResumeMark.arrival_ordinal` (`arrival.py:682`). An abbreviated sibling
(`arr_ord`) would be a second spelling of one coordinate. Flagged as
**open question D0-Q2** in case Kyle prefers the short form at the column
level; the rest of this document uses the long form.

`(arrival_ordinal, arrival_seq)` is the index's total order. It is written by the two —
and only two — sites that already expand a record into rows:
`arrival_store`'s catch-up indexer and `arrival_projection.rederive_projections`
(`:500-509`), both of which consume `rows_of_record` and already hold the
record's `ResumeMark`.

**Why this is not new state.** It is a projection column carrying a
coordinate arrival already mints and already verifies. It is derived,
rebuildable, and — unlike rowid — invariant under any re-derivation,
including a shuffled one. The dissolution test was run: the alternative is
resolving a coordinate by walking arrival on every witness resolve, every
seal window bound, and every audit check, which is O(log) per call on the
substrate's hot read path. `arrival_ordinal` is the memoization of that walk, and
all three of D1/D2/D3 dissolve into it.

**Why `arrival_seq` and not `ORDER BY arrival_ordinal, rowid`.** A batch record expands
to N fact rows sharing one ordinal (`jsonl_codec.records_from_object:448-451`).
Ordering those by rowid would reintroduce exactly the axis D exists to
leave, under shuffle. `arrival_seq` is derived from the record's own row order,
so the total order is arrival-derived end to end.

**Legacy indexes (the NULL problem).** jsonl-canonical and sqlite-canonical
indexes have rows predating these columns, and a legacy store must keep
answering reads after upgrade without a forced rebuild. Three options:

- **(a) Populate at insert for every store class.** `SqliteStore.append`
  writes `arrival_ordinal = <next monotonic>`, `arrival_seq = 0`; `ArrivalStore` writes
  the real coordinate. `_ensure_index_schema`'s `ALTER TABLE` backfills
  existing rows with `arrival_ordinal = rowid, arrival_seq = 0` in the same idempotent
  migration that already adds `signature` and the chain columns
  (`arrival_projection.py:544-566`). One axis name, one query shape, no
  per-mode fork anywhere above the schema.
- (b) A per-mode axis switch at `canonical_mode`'s three arms — explicit,
  but forks every witness/seal/audit query three ways.
- (c) `COALESCE(arrival_ordinal, rowid)` at each query site — cheapest diff, but
  makes every query silently dual-axis and defeats the provenance check
  below.

**Recommended: (a).** It is the only one where the coordinate vocabulary
above the schema is single-valued, which is the point of the re-key. For a
store with no arrival log, `arrival_ordinal` *is* its arrival axis — the statement
is true, not a fudge.

**Scope-the-claim corollary.** `arrival_ordinal IS NULL` is evidence of an
out-of-band insert **only in an arrival-canonical index that has been
migrated**. Under (a) the backfill makes NULL impossible in legacy rows, so
the check is safe — but it must be spelled as "this arrival-canonical index
holds a row carrying no arrival coordinate", a location claim scoped to
arrival stores, never "this store is clean".

**Legacy rows are row-granular.** The backfill gives each legacy row a
distinct `arrival_ordinal = rowid` with `arrival_seq = 0`, so D1-Q1's
record-granularity semantics apply only to arrival-projected rows. True by
construction; worth stating so nobody looks for batch behavior in a
pre-arrival store.

---

## D1 — Witness re-key

**The new data model** (`witness.py:164-195`):

```python
@dataclass(frozen=True)
class WitnessPosition:
    fact_id: str            # unchanged — the durable handle
    arrival_lineage: str    # NEW — the log whose ordinal axis this indexes
    ordinal: int            # REPLACES rowid — the arrival record cutoff; -1 = empty prefix
    seq: int                # unchanged meaning — count of rows at-or-before
    lineage: str | None     # unchanged — the store's own_lineage (declaration lineage)
    unadopted: bool         # unchanged
    anchor: TickAnchor | None   # unchanged
    store: str              # unchanged
```

`lineage` and `arrival_lineage` are **different identities and both stay**:
`lineage` is the store's `own_lineage` declaration marker, which is what A10
qualifies a portable handle by; `arrival_lineage` names the coordinate axis
the `ordinal` indexes. Collapsing them would be the subtle error available
here.

**Empty-prefix sentinel.** Today `rowid = 0` is the empty prefix because
rowids start at 1. Arrival ordinals start at 0 (genesis), so the empty
prefix is `ordinal = -1`. Genesis is structural and projects no rows
(`arrival_projection._projects`), so `arrival_ordinal <= 0` and `arrival_ordinal <= -1` in
fact select the same empty set — but `-1` is the honest spelling and the one
that survives a future projecting-genesis grammar. `handle.py:852-855`'s
storeless bootstrap moves to `ordinal=-1, arrival_lineage=""`.

**Selection.** Every `rowid <= ?` cutoff becomes `arrival_ordinal <= ?`. The sites
are enumerated in e2/e6 and are all inside libs/engine:
`store_reader.facts_between` (`:631`), `facts_by_kind` (`:677`),
`query_facts` pagination (`:809-816`, `<`/`>`), `declaration._decl_lineage_and_head_on_conn`
(`:654-656`), `witness._resolve_witness_position_on_conn`'s seq count (`:317`),
`witness.diff_interval_report` (`:624-641`), `witness._resolve_anchor`. The
`at_rowid: int | None` parameter name on `store_reader` moves to
`at_ordinal: int | None` in the same change — it is coordinate vocabulary,
and leaving it is exactly the residue the dissolution rule forbids.

**Non-arrival stores.** `resolve_witness_position` against a jsonl- or
sqlite-canonical store sets `arrival_lineage=""` — the same spelling as the
storeless bootstrap, meaning "this store's axis is its own". The new
same-path replacement guard below is therefore scoped to arrival-canonical
stores only: a legacy store has no log to compare a lineage against, and the
guard must not fire there.

**Serialization / compat.** `durable_handle` is **unchanged, verbatim**.
Nothing persists a position (finding 1 above). No migration.

**Same-lineage re-resolution** (`verify_position_for_store:466-516`) keeps
its exact structure and both refusals verbatim. Only the closing comment's
rationale improves: today it re-resolves because "append order is per-store,
so a merge that copied the fact reorders it"; under the re-key it
re-resolves because **the target store's arrival log is a different lineage,
so the source ordinal indexes an axis that does not exist here** — a
stronger statement of the same refusal. Add a cheap structural guard at the
top of the same-store arm: if `at.arrival_lineage` does not match the target
log's lineage, refuse even when the paths match (a store file replaced
in place under the same path). This *strengthens* A10 without altering its
message.

**Proof the verbatim criteria survive.** `WitnessAggregateUnsupported`
(`witness.py:98-106`) is raised at three sites (`vertex_reader.py:1216`,
`:1613`, `:1692`) on a purely structural condition — "the read is a
combine/discover aggregate" — which mentions no coordinate. Its raise
conditions and messages are untouched by D1. The A10 refusal
(`WitnessLineageMismatch`, `witness.py:109-119`) keys on `at.lineage` and
`at.store`, neither of which changes. Both are pinned by
`libs/engine/tests/test_witness_position.py` and
`libs/engine/tests/test_diff_interval_report.py`, which match on message
substrings (`"an UNADOPTED handle is session-local to its own store"`,
`"does not match this store's lineage"`) — those substrings must not move.

**Open question D1-Q1 — batch granularity.** An ordinal cutoff is
record-granular: a fact inside a batch resolves to its record's ordinal, so
the prefix includes its batch siblings. Today's rowid cutoff can stand
*inside* a batch. Recommended: **record granularity** — a ceremony is
admitted atomically, so no witness should stand inside one, and it keeps the
cutoff a single integer. Named consequence Kyle must accept: resolving
`seq:N` where N lands mid-batch returns a position whose `seq` is greater
than N, breaking `seq` round-trip for that case. The alternative is a
`(arrival_ordinal, arrival_seq)` composite cutoff, which restores intra-batch
addressing at the cost of a two-field comparison in every query. Kyle rules;
either way the gate carries the named round-trip test (G-D1-3).

---

## D2 — Seal re-base

**What changes.** Three functions in `sqlite_store.py`:

- `_cursor_rowid(fact_id) -> int | None` (`:1531-1545`) becomes
  `_cursor_ordinal(fact_id) -> int | None`, selecting `arrival_ordinal` instead of
  `rowid`, with `"" -> -1` as the start-of-store sentinel. Its
  unresolvable-cursor behavior (returns `None`, window hashes as empty) is
  preserved verbatim — it is a deliberate custody property.
- `_window_hash(start, end)` (`:1547-1574`) selects
  `WHERE arrival_ordinal > ? AND arrival_ordinal <= ? ORDER BY arrival_ordinal, arrival_seq`. Every
  other line — the era-aware column list, `_facts_have_signature_column`,
  `_fact_row_hash` — is unchanged.
- New-tick state (`:1632-1650`): the fact-cursor edge becomes
  `SELECT id FROM facts ORDER BY arrival_ordinal DESC, arrival_seq DESC LIMIT 1`, and
  the predecessor tick `SELECT ... FROM ticks ORDER BY arrival_ordinal DESC,
  arrival_seq DESC LIMIT 1`.

**What does not change: the signed bytes.** `_tick_envelope` is untouched
(finding 2). `window_start` and `fact_cursor` remain fact ids.

**Backward verifiability — a hard requirement, and it holds.** For any
existing store, the row set selected by `arrival_ordinal > lo AND arrival_ordinal <= hi` is
identical to the set selected by `rowid > lo' AND rowid <= hi'` for the
corresponding cursors, and `(arrival_ordinal, arrival_seq)` order equals rowid order,
because both the arrival catch-up indexer and `rederive_projections` insert
rows in record order and, within a record, in `rows_of_record` order — the
same traversal that assigns rowids. Under D0 option (a) the legacy backfill
sets `arrival_ordinal = rowid`, making the identity exact by construction for
pre-arrival stores. So `_window_hash` returns byte-identical digests before
and after, and previously sealed chains verify unchanged. **This is an
empirical claim, not a rhetorical one — G-D2-1 tests it against a fixture
store sealed by the pre-D code.**

**The latent defect this fixes** (`jsonl_store.py:920-940`, CX-DC-03): today
a chain commitment's window membership rests on rowid, an axis a rebuild
regenerates. The rebuild happens to reproduce it — `rederive_projections`
replays from ordinal 0 precisely to preserve that (`:460-463`) — but the
property is an accident of the replay strategy rather than a commitment to
anything in the log. After D2 the window is defined on the arrival
coordinate, so a *shuffled* or partially rebuilt index no longer silently
produces a different window. Sweep item: that docstring's rationale
("the rowids handed out by a replay from empty reproduce the original
assignment exactly, which is what keeps outstanding witness positions and
seals valid across a re-derivation") is superseded and must be rewritten in
the same change.

**Ordering-authority note.** `_window_hash`'s comment block ("Id order is not
append order in mixed-id-era stores") stays true and stays; only the word
naming the axis changes from receipt/rowid order to arrival order.

---

## D3 — Audit re-base

### Per-check disposition

| legacy check | disposition | arrival replacement |
|---|---|---|
| `index` (`:340-353`) | TRANSLATE unchanged | index exists and is readable |
| `_check_offset` (`:430-461`) | **DISSOLVE → re-found** | `_check_consumed`: the index's stamped `ResumeMark` (`arrival_lineage`, `arrival_ordinal`) vs the log's head ordinal. Claim: "index is behind arrival by N record(s), consumed through ordinal X." |
| `_suffix_unindexed` (`:383-427`) | **DISSOLVE, no replacement** | Its job was corroborating an unverifiable byte marker (finding 4). The mark's ordinal is structurally verified by `walk_from`'s anchor check. `beyond_offset` on `Check` dies with it. |
| `_check_counts` (`:464-492`) | TRANSLATE + strengthen | Stamped counters vs `COUNT(*)` as today, plus: no row may carry `arrival_ordinal >` the consumed ordinal, and (arrival-canonical only) no row may carry a NULL `arrival_ordinal`. Both are out-of-band-insert location claims. |
| `_check_last_line` (`:495-542`) | TRANSLATE | `_check_consumed_edge`: read the record at the consumed ordinal via the log, expand it with `rows_of_record`, and `row_matches` every row against the index. Same detection (an out-of-band edit to the last consumed row), no byte seek. `_last_line`'s backward-scan helper (`:290-310`) dissolves with it. |
| jsonl comparison (`--deep`, `_deep_checks:605-704`) | **wire, do not write** | `arrival_projection.audit_derived_log` — set membership over digests, already built. |

**Byte offsets do not survive as custody claims anywhere.** `arrival_offset`
remains inside the `ResumeMark` because arrival's own verified walk uses it
as a seek hint, checked against the anchor record before it is trusted. That
is a substrate internal, not an audit claim, and no `Check` may cite it.

### Required mechanism — how L1 stays cheap (fence for the implementer)

`ArrivalLog.read(ordinal)` is a **full verified walk from zero** by design
(`arrival.py:1040-1053`: "the walk is the only way in on purpose"). An
implementer who reaches for `read(consumed_ordinal)` turns the default gate
into an O(n) per-record-hash verification of the whole log and silently
destroys the cheapness this section claims. The cheap path is
`walk_marked(stamped_mark)`: the mark's byte offset seeks directly to its
anchor record, whose ordinal and chain linkage are verified there
(`arrival.py:1165-1174`), and the iterator then yields only the suffix.
`_check_consumed_edge` reads the consumed record through that anchor;
`_check_consumed` counts the suffix, so it costs O(records behind), which is
zero on a healthy store. **L1 must not call `ArrivalLog.read` or
`ArrivalLog.walk`.** G-D3-2 asserts this.

### The L1 / `--deep` split under the new model

- **L1 (`audit_agreement`)** — O(1) plus the size of one record:
  `index` · `consumed` · `counts` · `consumed-edge`. It answers from the
  arrival log's head and the index's stamped mark. It never reads a byte
  offset and never streams the log.
- **`--deep` (`audit_deep`)** — L1, then a full `ArrivalLog.walk()` (which
  verifies density, record hashes, ordinals and chain linkage as a free
  consequence of walking), row-by-row index comparison over
  `rows_of_record`, `audit_derived_log` for the derived `.jsonl`, and the
  tick chain re-derived from log content as today. `verify_authorship` is
  available at this tier but is a separate verb, not folded in — it makes an
  authorship claim, not an agreement claim.

### Scope-the-claim discipline

Every `Check` emits a **location claim**. Concretely: `beyond_offset: bool`
(a flag one step from innocence) is replaced by `behind_by: int` and
`at_ordinal: int` — coordinates, not verdicts. No check may return a message
asserting a store is intact, clean, or safe; the strongest positive form
stays the existing one, "N fact(s), M tick(s) accounted for". The L1 pass
returning all-true means *these four questions found nothing here*, and the
report's own prose must not let a renderer say more.

### Blast radius — the one call site

`apps/loops/src/loops/commands/store.py:141-163` gates on
`is_jsonl_canonical(canonical)` and returns `None` for an arrival store, so
today arrival stores are simply unaudited. That gate growing an arrival arm
**is** the "blast radius one call site" the plan names. Note for the fence:
this is `apps/`, and the arc's scope law says apps/ is diff-empty across
every slice. Flagged as **open question D3-Q1** — either D touches this one
dispatch as a ruled exception, or the audit lands library-side and the CLI
arm waits for the tail's CLI rebuild, leaving arrival stores unaudited
through the CLI in the interim. Recommended: **library-side complete, plus
the one dispatch arm as a ruled, receipted exception** — an audit surface
nothing can reach is not a surface.

---

## D4 — Admission signature verification (CX-BR-02 rider)

**The situation, stated honestly.** `merge_store` admits foreign records
with no signature verification; `merge.py:526-532` and `arrival.py:694-699`
both say so explicitly and say an admission attestation is "a later cut".
This rider has rolled once. Three arms:

**Arm 1 — source-side verification at admission (in-slice, feasible).**
Merge holds the *source* arrival log open, and
`verify_authorship(log, verify)` (`arrival.py:1558`) resolves keys **from
that log alone**. So merge can verify the source's records against the
source's own key chain before admitting them, and refuse on a bad signature.
Dependency direction permits it: `Verify` is a bare
`Callable[[str, str, str], bool]` alias (`arrival.py:137`), so `libs/store`
takes one as a caller-supplied parameter — no `libs/sign` dependency is
added (`libs/store/pyproject.toml` depends on `engine` only, and `engine`
imports `sign` nowhere). Cost: one new parameter, one refusal class, and a
ruling on the legacy-source case (a jsonl/sqlite source has no arrival log,
so it must make an explicit no-claim or be refused — see D4-Q1).

**Arm 2 — target-side verification (blocked, wave 2).** Verifying admitted
records against the *target's* key chain is not implementable in D:
`merge.py` transports no key-introduction records (grep for
`KEY_INTRODUCTION_KIND` in `libs/store/src/store/merge.py` returns nothing),
so the target cannot resolve a foreign observer's key at all. This needs
key-introduction transport, which is a grammar-adjacent design exceeding
slice D.

**Arm 3 — full carve.** Ship D without it, with a fresh receipt naming arm 1
as available and arm 2 as blocked.

**Recommendation: Arm 1, in slice D, opt-in.** It discharges the rider with
existing machinery, it is the half that is actually implementable, and it
gives the federated-read-vs-admission distinction something to *be* — the
admission verb verifies, the federated read does not. Carving would be the
third deferral of a rider whose blocking rationale only ever applied to
arm 2. But the tradeoff is real and stated: arm 1 verifies the source's
self-consistency, **not** that the target's operator trusts the source's
keys. It is a weaker claim than "admission verified authorship", and the
refusal message and docstring must say exactly which claim it makes.

**Open question D4-Q1.** Legacy source (jsonl/sqlite, no arrival log) under
arm 1: explicit no-claim (admit, record that nothing was verified) or
refuse? Recommended no-claim — refusing would break every pre-migration
merge, and the hazard clock is already accepted.

---

## Gate plan

Independent gate agent; re-derives the oracle from scratch; pointer branch
`slice/D-gate`.

**G-D0-1 — the shuffled index (the ruled gate item).** A natural rebuild
*cannot* produce a shuffled index: `rederive_projections` replays in order,
so it reproduces the original rowid assignment by construction. The gate
therefore needs a **deliberate permuted-insert harness** — build an index by
inserting `rows_of_record` output in a permuted record order, so rowid order
and arrival order disagree. Assertions: L1 passes; every witness position,
seal window, and audit check answers identically to the unshuffled store.
Any answer that changes under permutation is a rowid dependency that
survived the re-key. This harness is the slice's central artifact and should
be written first.

**G-D0-2** — deliberately rebuilt index (`rederive_projections`): outstanding
positions and seals still valid.

**G-D1-1** — `durable_handle` output byte-identical before/after the re-key.
**G-D1-2** — `WitnessAggregateUnsupported` raised at all three sites with
unchanged messages; A10 refusal messages unchanged. Pinning tests:
`libs/engine/tests/test_witness_position.py`,
`libs/engine/tests/test_diff_interval_report.py`,
`libs/engine/tests/test_query_facts.py`, `libs/engine/tests/test_fold_at.py`
— they match on message substrings and must pass untouched.
**G-D1-3** — `seq:N` round-trip across a batch boundary, pinning whichever
D1-Q1 answer Kyle rules.
**G-D1-4** — same-path store-replacement refusal (the new `arrival_lineage`
guard).

**G-D2-1 — backward verifiability, empirically.** A fixture store sealed by
the pre-D code: after the re-key, `verify_chain` is green **and** each
window hash is byte-equal to the legacy computation. Not an argument, a
byte comparison.
**G-D2-2** — a seal spanning a batch record: window membership and hash
identical before/after.
**G-D2-3** — unresolvable cursor still hashes as empty.

**G-D3-1** — L1 detects: index behind arrival; out-of-band sqlite insert;
edit to the last consumed row. Each with the expected coordinate in the
message.
**G-D3-2** — L1 makes no byte-offset custody read and stays cheap: no
`open(canonical, "rb")` remains on the L1 path, and L1 calls neither
`ArrivalLog.read` nor `ArrivalLog.walk` (assert by construction or by
counting records verified on a large healthy store).
**G-D3-3** — torn arrival tail: L1 reports "behind", never "tampered" — the
false-accusation property `_check_last_line`'s docstring protects.
**G-D3-4** — derived `.jsonl` reordered line-for-line: set-membership audit
still agrees (the whole point of set membership).

**G-D4-1** (if arm 1 lands) — merge from a source with a forged record
refuses; merge from a legacy source admits with an explicit no-claim.

**Fence check, every package:** `git ls-files` diff confined to
`libs/engine/`, `libs/store/` — plus, if D3-Q1 is ruled in, exactly the one
dispatch in `apps/loops/src/loops/commands/store.py`.

---

## Work packages

Sequenced by dependency; each is a fence for one implementer.

**WP-1 · the coordinate (D0).** `arrival_projection.py` (`_ensure_index_schema`
migration + backfill, `rederive_projections` insert), `arrival_store.py`
(catch-up indexer), `sqlite_store.py` (`FACT_INSERT_SQL`/`TICK_INSERT_SQL`,
`append`/`append_tick` monotonic assignment). Plus the permuted-insert
harness (G-D0-1) — written here, used by every later package. Nothing above
the schema changes yet; the suites must stay green on this package alone.

**WP-2 · witness (D1).** `witness.py`, `store_reader.py` (`at_rowid` →
`at_ordinal`, three query methods), `declaration.py:654-656`,
`handle.py:852-855` bootstrap, `vertex_reader.py` at the `at=` selectors.
Residue: coordinate vocabulary in docstrings across all of these.

**WP-3 · seals (D2).** `sqlite_store.py:1531-1650` only. Sweep the superseded
`rederive_projections` docstring rationale in the same change.

**WP-4 · audit (D3).** `canonical_audit.py` (the L1 rewrite, the two
dissolutions, `Check.beyond_offset` removal), wiring `audit_derived_log`
into `--deep`, and — if D3-Q1 is ruled in — the one dispatch arm in
`apps/loops/src/loops/commands/store.py`.

**WP-5 · admission (D4, if arm 1 is ruled in).** `libs/store/src/store/merge.py`
plus its refusal class. Independent of WP-2/3/4; can run in parallel with
WP-3.

**Ordering:** WP-1 → {WP-2, WP-3, WP-5} → WP-4. WP-4 last because it audits
what the others establish.

**Vocabulary ratchet — candidate additions from this slice:** `rowid` as a
public coordinate name (allowlisted only inside `sqlite_store`'s row
plumbing), `at_rowid`, `beyond_offset`, `consumed-offset`, `receipt order`
as an ordering-authority phrase.

---

## Open questions for Kyle

1. **D1-Q1 — batch granularity.** Record-granular ordinal cutoff
   (recommended; batch is atomic; costs `seq:N` round-trip mid-batch) or
   `(arrival_ordinal, arrival_seq)` composite cutoff (restores intra-batch addressing;
   two-field comparison everywhere)?
2. **D3-Q1 — the one call site vs the apps/ diff-empty scope law.** Growing
   `apps/loops/.../store.py:141-163` an arrival arm is the plan's own
   "blast radius one call site", but the arc's scope law says apps/ is
   diff-empty every slice. Ruled exception, or library-only with arrival
   stores unauditable through the CLI until the tail's CLI rebuild?
3. **D4 arm.** Arm 1 (source-side, in-slice, recommended), arm 2 (blocked on
   key transport, wave 2), or arm 3 (full carve with a fresh receipt)?
4. **D4-Q1** (if arm 1) — legacy source with no arrival log: explicit
   no-claim (recommended) or refusal?
5. **Verbatim-vs-staleness conflict A — `preflight.py` UNTOUCHED.**
   `_arrival_preflight`'s docstring (`preflight.py:381-393`) says "the
   arrival agreement audit is a later cut; this gate makes no agreement
   claim". That sentence becomes false the moment D lands. Its *behavior*
   (`agreed` stays `None`, no innocence claim) should stay verbatim —
   preflight legitimately still makes no agreement claim, it just is no
   longer true that none exists. Proposed: a one-sentence docstring truth-up
   as a Kyle-ratified exception to "UNTOUCHED", with behavior byte-identical.
   Alternative: leave it stale and sweep in wave 2.
6. **Verbatim-vs-staleness conflict B — `WitnessAggregateUnsupported`.** Its
   docstring says positions "resolve against one store's rowid axis"
   (`witness.py:98-106`). Keeping it byte-verbatim preserves a coordinate
   word the slice exists to retire. Proposed: raise conditions, exception
   identity, and the raised *message strings* at all three sites stay
   verbatim (that is what the tests and the criteria actually protect); the
   class docstring's one stale word is corrected. Kyle rules whether that
   counts as verbatim.
7. **D0-Q2 — column naming.** `arrival_ordinal`/`arrival_seq` in full
   (recommended, matches `ARRIVAL_ORDINAL_KEY` and `ResumeMark`) or the
   short `arr_ord`/`arr_seq` at the column level?
8. **D0 legacy-index option.** (a) backfill `arrival_ordinal = rowid` for every
   store class (recommended), (b) per-mode axis switch, or
   (c) `COALESCE(arrival_ordinal, rowid)`?
