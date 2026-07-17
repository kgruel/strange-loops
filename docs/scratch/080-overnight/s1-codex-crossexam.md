# Session 1 cross-examination — break the temporal cursor

*2026-07-17. Adversarial pass against `s1-arbitration.md`. Evidence checked
against the incumbent code, the live/project stores, the archived pre-rebirth
project store, the S5 tests, and loops-go `SPEC.md`. The prior Codex advisor
was treated as an argument to attack, not an authority.*

## Bottom line

Do **not** ratify the synthesis as the 0.8.0 implementation contract. Its
selection/replay distinction is sound:

> select a received set in witness order; replay that selected set in
> `(ts, id)` order.

The proposed position space and product claims around it are not sound yet.
The actual schema has no store-wide witness position, no durable fact/tick
interleaving, and no receipt grouping for atomic multi-row declaration edits.
The wall-clock address fails over the real pre-chain/rebirth era, the primary
`project` UX is an aggregate with no scalar cursor, and the claimed §10
rebuild guarantee is wholly unimplemented. Those are not rendering details;
they invalidate the advertised common Rewind/Watch cursor.

## 1. There is no store-wide witness prefix in the incumbent

**Scenario.** A fact is appended, then a tick is sealed, then another fact is
appended. Watch wakes after both writes and must render the two receipts in
order. Rewind later needs to say whether the tick anchor existed before or
after the second fact.

The schema has independent `facts` and `ticks` tables, hence independent
SQLite rowid domains (`sqlite_store.py:269-296`). Fact selection can resolve
`fact id -> facts.rowid` and select `facts.rowid <= P`
(`sqlite_store.py:1176-1218`). Tick order is independently
`ticks.rowid` (`sqlite_store.py:1256-1258`, `1668-1674`). There is no durable
column or receipt log that interleaves a fact row with a tick row.

The arbitration tries to have it both ways: ticks are Watch events (“a tick
arrival renders an anchor”) but do not advance fold position. That is fine for
fold state, but it does not make “Watch tails receipts in witness order” true.
If a fact and tick arrive between refreshes, their cross-table receipt order is
not queryable. WAL frame order is an ephemeral SQLite implementation detail,
not exposed by these reads, not retained through checkpoint, and not §10
interchange data.

**Verdict: FATAL.** Amendment **GlobalReceiptPosition**: add one durable,
monotonic store-wide receipt ordinal (or an append log referenced by both
tables), define whether a tick occupies an ordinal, and make both Watch and
§10 consume it. A facts-only `WitnessPosition` may remain the fold boundary,
but it cannot be advertised as the common receipt cursor without a separate
store-wide event position.

## 2. Witness fact cursors split atomic declaration edits

**Scenario.** One `store absorb` edit renames kind A and changes kind B's fold
key. `absorb_edit` writes two `_decl.*` rows in one transaction. The user later
addresses the fact id of the first declaration row.

The incumbent explicitly identifies a half-applied ontology as a lie and
prevents it on the ts axis by stamping every row in one ceremony with one
effective timestamp (`sqlite_store.py:704-723,796-847`). Transaction atomicity
only prevents a live reader observing the middle of the commit. Once committed,
each row has its own fact id and rowid. The synthesis's inclusive
`rowid <= rowid(fact_id)` therefore makes the first row a durable address to a
half-applied ceremony—the exact state S5 was hardened to make unreachable.

`seq:N` makes the hole easier to hit, not harder. The synthesis cannot repair
this by replaying declarations in `(ts,id)` order: the second declaration row
is absent from the selected set.

**Verdict: FATAL.** Amendment **AtomicReceiptGroups**: cursor selection must
close over a transaction/ceremony receipt group. Store a group id/end ordinal,
canonicalize every member handle to the group end (or reject interior
positions), and vector a multi-subject edit. A shared timestamp is insufficient
as a durable group identifier because unrelated rows may share it and the
whole point of the new selector is not to select by timestamp.

## 3. Fact-id and `seq:N` resolution across id eras

**Scenario.** A store has uppercase ULIDs, lowercase ULIDs, and uuid4 ids. A
user resolves `fact:<uuid prefix>` and `seq:116`.

The core fact-prefix mechanism survives mixed ids. Existing exact/prefix
lookup treats ids as opaque text, doing exact equality first and then a range
prefix lookup (`store_reader.py:369-411`). Window selection resolves exact id
to rowid (`sqlite_store.py:1176-1190`). A correctly implemented `seq:N` as
“Nth fact row ordered by rowid” is also independent of id shape. It must not be
implemented as `ORDER BY id`, `MAX(id)`, or raw `rowid == N`.

The live-store audit does not support using current stores as the only test.
The five members of the live `project` aggregate are now all canonical-ULID
stores. Likewise the five oldest current config stores audited were
post-rebirth canonical. The archived pre-rebirth project store proves the
compatibility obligation: 2,053 facts comprise 872 uuid4 ids and 1,181 ULIDs.
The current project was produced by the explicit `ulid-migration` rebirth, so
old uuid fact handles do **not** resolve in the current incarnation; rebirth is
not §10 rebuild.

Two traps remain:

- The proposed spelling `fact:01J…` reads like a ULID grammar. It must accept
  opaque legacy ids and prefixes, not validate only `is_ulid`.
- `seq:N` means the Nth selected fact receipt, not SQLite rowid value N. Rowid
  gaps and rebuild renumbering otherwise change it.

**Verdict: AMENDMENT-NEEDED.** Amendment **OpaqueFactIdAndOrdinalSeq**: specify
opaque id grammar, ordinal-by-witness-order resolution, ambiguity behavior,
and mixed uppercase/lowercase/uuid vectors. The selection algorithm itself
survives.

## 4. The rebuild durability claim is an aspiration presented as fact

**Scenario.** A user bookmarks `fact:F` and `seq:116`, dumps a mixed-era store,
rebuilds it, then reopens both handles.

SPEC §10.1 requires one JSONL stream carrying facts and ticks with witness
order explicit per line; §10.3 requires rebuild verification and byte-identical
redump (`SPEC.md:1191-1220`). It also labels the vectors “to build”
(`SPEC.md:1235-1240`). The incumbent implements none of this. There is no §10
dump/rebuild command or encoding.

Today's superficially adjacent paths are counterexamples, not substitutes:

- `slice` copies facts and ticks separately and strips tick-chain columns.
- `merge` appends source facts in `(ts,id)` order and then source ticks in a
  separate statement (`store/merge.py:73-111`), losing source witness order and
  all fact/tick interleaving.
- `rebirth` preserves source fact rowid order, then converts *all* ticks to
  facts after all facts, appends a new receipt, and mints a new tick
  (`store/rebirth.py:275-313,412-461`). Its ULID migration intentionally
  changes legacy ids.
- `store_meta.own_lineage` is store-local and its own docstring says S6 must
  carry it explicitly; there is no implementation yet.

Even the proposed format cannot be implemented from today's two rowid domains:
the original cross-table interleaving is unrecoverable.

**Verdict: FATAL.** Amendment **GateOnSection10**: downgrade “fact-id cursors
survive rebuild” to a design goal until a global receipt ordinal, total dump,
rebuild, metadata carriage, and §10.5 vectors ship. Cursor durability must be
an exit criterion for 0.8.0 if it remains a user-facing promise.

## 5. Concrete UX walk: `sl read project --at 2026-06-01`

**Scenario.** Run the proposed command against the real project history.

Current `.loops/data/project.db` contains 2,176 facts whose event timestamps
are at or before 2026-06-01. It has 58 chained ticks, but the first is the
rebirth tick at 2026-06-12 15:03:48. Therefore the greatest tick at or before
June 1 does not exist. The command returns “no witness-time anchor,” not a
folded answer.

The archived predecessor makes the failure more explicit. It has 216 ticks:
211 legacy rows with NULL `fact_cursor`/`window_hash`, followed by five chained
ticks beginning June 9. The last tick at or before June 1 is May 20, but it has
no usable cursor. There are 1,965 facts with `ts <= June 1`. Again the proposed
wall-clock form cannot answer. Skipping backward to a “usable” tick finds none;
using the legacy tick's timestamp as a ts cutoff silently changes semantics.

This meets the arbitration's own change-my-mind condition: tick-floor snapping
makes a natural wall-clock rewind useless across a large real era. It also
contradicts the Rewind mock, which promises that the past is “all still there,
addressable by T.” The past exists, but this address grammar cannot name it.

**Verdict: FATAL.** Amendment **LegacyTimeAddress**: choose and label one of:
(a) a protocol migration that backfills durable receipt anchors without
retro-claiming attestation; (b) an explicit `event-time:` approximation for
unanchored eras; or (c) removal of general wall-clock addresses, with the UI
honestly exposing only `seq`/fact positions. A bare ISO time must not simply
error across the principal historical corpus while remaining the showcased
Rewind syntax.

## 6. Concrete UX walk: 400 facts between ticks three weeks apart

**Scenario.** Tick K1 occurs, then 400 facts arrive over three weeks, then tick
K2 occurs. The user drags a ruler labelled in dates between K1 and K2.

The synthesis says Rewind scrubs all 400 fact positions. That is mechanically
useful, but those positions have no receipt timestamps. There is no honest way
to place them along a three-week wall-clock ruler. Uniform seq spacing invents
a temporal distribution; spacing by fact `ts` substitutes observation time and
can move backward under late arrivals; interpolating between K1 and K2 is
fabricated receipt time. A tick-only ruler has no selectable interior despite
the claimed fact-position scrubbing.

**Verdict: AMENDMENT-NEEDED.** Amendment **DiscreteScrubberContract**: make the
scrubber's primary scale receipt ordinal, label it as discrete sequence, render
ticks as the only dated markers, and never interpolate dates for facts. If the
product requires a continuous time ruler, add durable per-receipt time in a new
era instead.

## 7. Watch sequence, hidden declarations, and recomputation

**Scenario A.** Watch has printed 90 visible domain facts. Twenty-six hidden
`_decl.*` rows have also arrived, so the next domain row is `seq 117`. The user
sees “seq 117” after only 91 visible events.

This is not semantically wrong—declarations really are receipts and can change
the view—but it is confusing if the UI calls seq a fact count. A declaration
receipt that changes ontology must produce a visible control event such as
`seq 116 · ontology changed · 3 fold rows reinterpreted`; otherwise Watch
appears to skip numbers and state changes without an event.

**Scenario B.** Every newly received fact is backdated earlier than most of a
100k-fact store. The mock promises “on append apply → diff → emit.” Blind apply
at the tail violates `(ts,id)` replay. The safe generic implementation is a
full reconstruction after each receipt, yielding quadratic work. The current
incremental engine primitive itself selects `rowid > cursor` then returns those
new facts in `(ts,id)` order (`sqlite_store.py:894-934`); applying that batch to
the old head still cannot insert it before already-folded facts. Declaration
changes can reinterpret the entire store and have the same problem.

**Verdict: AMENDMENT-NEEDED.** Amendment **WatchControlEventsAndReplayBudget**:
render hidden cursor-advancing events, display both receipt seq and visible
domain count, coalesce by committed receipt group, and specify either full
reconstruction with an explicit performance budget/checkpoint strategy or an
insertion-aware replay index. Do not promise O(1) “apply” semantics for generic
folds.

## 8. S5 equal-cursor regression and tick interpretation

**Scenario.** A fact and declaration edit share timestamp T. Existing callers
run `--facts --as-of T`; a new fold caller runs `--at fact:F`, where F was
received before the edit.

The migration is implementable **only as two explicit selector APIs**. Keep
`load_declaration(as_of=float)` as the existing inclusive event-time
projection. Add a separate witness selector, e.g.
`load_declaration(at=WitnessPosition)`, mutually exclusive with `as_of`.
Then the shipped same-ts test at `test_ontology_as_of.py:162-175` and the
head/now equivalence at `:193-204` retain their meaning. The focused S5 suite
currently passes (9 tests).

If `as_of` is silently reinterpreted as rowid position, those tests and the
existing `--facts --as-of` CLI contract break. Under witness selection, F
correctly uses old ontology if the edit was not yet received. At a later cursor
the edit may reinterpret F under the new whole-document ontology; that is the
selected-snapshot model, not the old same-ts rule.

`vertex_tick_fold` is not a trivial migration. It accepts only a `Tick` and
loads ontology at `tick.ts` (`vertex_reader.py:1048-1077`); `fact_cursor` lives
in a separate envelope returned only by `vertex_ticks(with_envelope=True)`
(`store_reader.py:292-350`). The drill API must carry the stored envelope, and
legacy ticks need an explicit ts-mode fallback or “unanchored interpretation”
notice.

**Verdict: SURVIVES**, conditional on amendment **DualSelectorAPIAndTickEnvelope**.
The synthesis's stated intent—preserve ts cutoff as explicit projection—can
keep shipped behavior, but the tick migration is real implementation work and
must not be described as merely swapping one argument.

## 9. Aggregate reads have no scalar witness cursor

**Scenario.** The live `project` vertex—the normal entry point and TUI corpus
subject—is a storeless `combine` over five project stores. Run
`sl read project --at seq:116`.

There are five independent rowid/seq domains. `seq:116` names up to five
different facts. A `fact:F` from one member says nothing about the other four
members' positions. `tick:K` anchors only its source store. A wall-clock input
could in theory resolve to a five-element vector of per-store tick floors, but
members without anchors make it partial, and current combined ticks deliberately
return empty attestation envelopes (`vertex_reader.py:1258-1290`).

The current aggregate read simply unions every child fact and sorts globally by
`(ts,id)` (`vertex_reader.py:330-369`). Its membership comes from the current
aggregate file. `load_declaration_status` already labels historical aggregate
membership `aggregate-head` because its history is not built
(`declaration.py:354-386`). SPEC itself says aggregate constitution history
requires an internal table or the historical read is dishonest
(`SPEC.md:1184-1185`).

This is not a peripheral route: the provided `project` configuration combines
the loops, gruel.network, siftd, loops-tasks, and tasked stores, and the TUI mock
opens on `project`. Deferring aggregate cursors defers the primary Rewind UX.

**Verdict: FATAL.** Amendment **AggregateCursorVector**: define an immutable
cursor vector keyed by member lineage plus historized membership, canonical
serialization, partial/missing-anchor behavior, and per-member ontology
positions. Alternatively, explicitly refuse Rewind on aggregates and remove
aggregate-first TUI claims from 0.8.0; that is honest but a major scope cut.

## 10. Merge handles are claimed lineage-bound but encoded lineage-free

**Scenario.** In B, `fact:F` is at source seq 100. Merge B into A. The current
merge appends B facts to A in `(ts,id)` order, not B witness order
(`store/merge.py:73-102`). Resolve `fact:F` in the merged A.

The id exists, but its prefix now includes all prior A facts and a reordered
subset of B. The answer differs from B's handle. The synthesis says handles
bind to lineage, yet its public canonical spelling is only `fact:01J…`; no
lineage appears in the token and no mismatch rule is specified. Current merge
also does not append the SPEC's proposed `_decl.merged` receipt or carry source
`store_meta`, so there is no complete in-store translation record.

For A-native handles when A is the target, the old prefix happens to remain a
prefix because source rows append. That accidental asymmetric success does not
generalize to an empty merged target, reverse merge, B-native handle, rebuild,
or copied database under a new lineage.

**Verdict: AMENDMENT-NEEDED.** Amendment **LineageScopedHandle**: serialize
`lineage + fact id` (or an opaque signed equivalent), reject it in a different
lineage by default, and require an explicit translation operation using a
merge receipt. A bare fact id may be a local convenience only; it cannot be
called a durable lineage-bound handle.

## 11. Two flags by route is taxonomy leaking into UX

**Scenario.** A user learns `sl read project --at T`, then adds `--facts` to
inspect contributing events. The same temporal intent now errors because the
synthesis permits `--at` only on fold and expects `--as-of` on facts/ticks.
Conversely, the existing and mocked spelling `sl read project --asof 'last
friday'` errors on fold and tells the user to change vocabulary.

The strongest counter-position is not “one ambiguous flag.” It is one global
camera-position flag across read routes:

- `--at` (with `--as-of` retained as a compatibility alias during migration)
  sets the reading position for fold, stream, ticks, graph, and TUI.
- A separately named analytical predicate such as `--event-through T` means
  current retrospective knowledge filtered by `fact.ts <= T` on any route
  where it makes sense.

That division is semantic and consistent. The synthesis's division is
route-based: users must know which internal read path they are on before they
can name the same-looking time. The current router already demonstrates the
cost of route-sensitive semantics (`cli/views/read.py:27-87`).

If backward compatibility forbids renaming current `--as-of`, then expose both
semantics consistently: `--at` for witness position on every route and
`--as-of` for event-time projection on every route. Do not make the flag set
change merely because `--facts` was added.

**Verdict: AMENDMENT-NEEDED.** Amendment **SemanticFlagsNotRouteFlags**.

## 12. Unsealed tail and `now`

**Scenario.** The last tick is three weeks old and 400 facts have arrived since.
The user enters an ISO timestamp one minute ago. Tick-floor snapping returns
the three-week-old state, while `head` returns all 400 additional facts.

The result is formally consistent but product-hostile unless the omitted tail
is impossible to miss. `now` is especially dangerous: the address table lists
`head` and wall-clock forms, while users reasonably treat `--at now` as a
wall-clock expression. If `now` snaps to the last tick rather than atomically
capturing head, two apparent synonyms diverge.

**Verdict: AMENDMENT-NEEDED.** Amendment **UnsealedTailDisclosure**: reserve
`head`/`now` as the atomic fact edge; for any snapped time print anchor time,
anchor fact seq, and “N later receipts omitted / live edge unsealed.” Require
confirmation or an explicit mode before silently returning a very stale snap
for a near-present time.

## 13. Pre-genesis witness positions contradict “ontology from the same prefix”

**Scenario.** Address a domain fact received before `_decl.genesis`.

The selected witness prefix contains no declaration rows. The synthesis says
ontology resolves from `_decl` rows in that same prefix, which yields no store
ontology and falls toward the current file—precisely the retro-claim S5 fixed.
The incumbent instead looks beyond the requested time to the later genesis and
returns its document set as an explicitly `Unhistorized` earliest-known floor
(`declaration.py:209-350`).

That behavior is honest but violates the literal “same prefix only” slogan.
The design must admit a metadata/look-ahead exception or reject folding the
pre-genesis era. It must also say whether the genesis fact id names the state
before or after genesis; inclusive prefix implies after.

**Verdict: AMENDMENT-NEEDED.** Amendment **UnhistorizedFloorException**:
preserve the genesis-floor look-ahead with an unavoidable status, and specify
empty/pre-genesis/genesis boundary behavior in cursor vectors.

## 14. Same-ts boundaries outside declaration batches

**Scenario.** A domain fact F and declaration edit D share `ts=T`, but F is
received first. Cursor F excludes D; cursor D includes it. Replay at both
positions remains `(ts,id)` within the selected set.

This is well-defined and more receipt-honest than S5's old rule for witness
reads. The event-time projection still includes D at T and therefore retains
the shipped “edit wins its own instant” rule. The only semantic footgun is
language: `(ts,id)` orders replay, but it must never be used to expand
membership past the witness boundary.

**Verdict: SURVIVES.** Add the F-before-D and D-before-F cases to the owed
two-authorities vectors. This survival does not rescue multi-row declaration
batches, which fail for absence/grouping rather than replay order.

## 15. “No receipt timestamp” is substantially correct

**Scenario.** Try to recover per-fact receipt wall time from existing data.

`facts.ts` is observation/event time and travels across import; it is not
receipt time. A tick's `ts` is a signed boundary-time claim and can date its
`fact_cursor`, but cannot date each fact inside the window. SQLite WAL ordering
has no durable timestamp and is checkpointable. Database/WAL file mtimes are
store-level filesystem metadata, mutable on copy, and not per row. Rowid gives
order only. None survives §10 as a protocol receipt time unless explicitly
encoded.

**Verdict: SURVIVES.** Tighten the wording to “no durable, protocol-carried
per-receipt timestamp.” Tick timestamps remain coarse claimed anchors, not
proof of clock accuracy.

## Required ratification changes

The minimal honest ratification is narrower than the current synthesis:

1. Ratify only the selection/replay split and fact-prefix semantics for a
   **single store**, subject to atomic receipt grouping.
2. Make §10 implementation and vectors a gate before claiming durable handles.
3. Either implement aggregate cursor vectors or explicitly cut aggregate
   Rewind/Watch from 0.8.0.
4. Withdraw general wall-clock addressing until the legacy/unanchored era has
   a labeled answer.
5. Add global receipt ordering if Watch includes ticks as events.
6. Keep S5's ts selector as a separate explicit analytical API and add a new
   witness selector rather than mutating `as_of`.

Without those changes, the design is internally elegant but describes a store
the incumbent does not actually have.
