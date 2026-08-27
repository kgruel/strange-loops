# Cut B — PROJECTIONS: design brief

You are the design agent for wave-1 slice B of the arrival substrate arc in the
loops monorepo (`/Users/kaygee/Code/loops`, branch `feat/arrival-libs` @ 01ab4bb0).
Your deliverable is a DESIGN PROPOSAL the arbiter will spot-check and Kyle will
ratify as a design fact. You design; you do not implement. Ground every claim in
source you actually read — cite file:line.

## The ruled plan (plan:arrival-libs-slice-B, Kyle 2026-08-17 — verbatim contract)

> Wave-1 slice B — PROJECTIONS. catch_up/_rebuild re-point to arrival as source;
> .jsonl becomes a SECOND derived output re-keyed to SET MEMBERSHIP; offset/count
> triple moves to arrival; merge_store/receive_store rewritten as
> append-into-arrival + re-derive both projections (never direct index INSERTs);
> reanchor (jsonl_store.py:152-156) becomes a PERMANENT REFUSAL, retiring the
> queued log-rewrite ceremony item. PR#8 dispositions: DISCARD R1-as-doctrine
> (merge.py:83, test_merge_direction_sets_fold_order_by_receipt), KEEP
> test_merge_direction_is_deterministic. GATE: (1) trace whether index rebuild
> invalidates outstanding witness positions; (2) semantic git merge driver for
> the derived JSONL projection proven by ACTUALLY PERFORMING a git merge of a
> JSONL projection.

Scope law for the whole arc: libs/engine + libs/store ONLY; apps/ is diff-empty
(mechanical per-slice gate). The sidecar (frozen last-0.x reader) is wave-2 tail;
the merge driver is BUILT AND TESTED in slice B, but `.gitattributes`
registration rides wave 2 (plan:arrival-wave-2-and-tail). Do not design apps/
changes or driver registration.

## Inherited from Cut A (task:arrival-slice-A close, all named for cut B)

1. **Restamp verb**: a crash between the ceremony's log fsync and the sqlite
   COMMIT parks the store on AmbiguousGenesis until a restamp verb exists.
   Ceremony path: `_ceremony_persist` (arrival_store.py:404-435) appends+stamps
   inside the ceremony transaction; caller COMMITs at sqlite_store.py:975-976
   (genesis) and :1181-1182 (edit).
2. **Codec decoded-dict entry point**: arrival_store.py:290-293 defers a
   decoded-dict entry to "the cut where rebuild is the subject" — that is this
   cut. jsonl_codec's only entry is a line string; rebuild triple-round-trips
   JSON (dumps → deserialize).
3. **_log_size/_has_rows mixin call**: arrival_store.py:210-222 duplicates
   jsonl_store's shape; decide the shared home.

## Current state (verified locations)

- ArrivalStore catch-up refuses re-derivation at arrival_store.py:236-260 —
  three ArrivalCanonicalUnsupported arms, each saying "projection
  re-derivation, a later cut". This cut is that cut: those refusals resolve
  into the re-derivation verb.
- JsonlStore.catch_up (jsonl_store.py:674-731) reads the .jsonl log;
  `_rebuild` (:939-967) clears facts/ticks, preserves store_meta
  (`own_lineage` is identity, not fact). Rowid collision → rebuild at :920-932.
- Offset/count triple: OFFSET_KEY/FACT_COUNT_KEY/TICK_COUNT_KEY
  (canonical_audit.py:72-74), stamped by JsonlStore._stamp
  (jsonl_store.py:509-516); arrival mark keys arrival_store.py:104-106
  (lineage/offset/ordinal — counts deliberately dissolved).
- merge_store (libs/store/src/store/merge.py:37-141): ATTACH + INSERT OR
  IGNORE ordered by (ts, id); the R1-as-doctrine comment block is :79-92.
  receive_store (receive.py:29-77): copy2 or merge. Both are direct sqlite
  writes with no log awareness — for an arrival-canonical target these are
  exactly the out-of-band INSERTs the arrival model forbids.
- PR#8 disposition targets: libs/store/tests/test_merge.py:457
  (test_merge_direction_sets_fold_order_by_receipt — DISCARD as doctrine),
  :481 (test_merge_direction_is_deterministic — KEEP).
- reanchor: SqliteStore.reanchor (sqlite_store.py:1675), JsonlStore refusal
  (jsonl_store.py:971-978, "until the log-rewrite ceremony is designed"),
  ArrivalStore refusal (arrival_store.py:487-494). Plan: PERMANENT refusal;
  retire the queued log-rewrite ceremony framing.
- Witness positions: witness.py:276-330 resolves WitnessPosition from address
  + rowid; tick chain commits fact_cursor/window_hash
  (sqlite_store.py:1633-1651); verify_chain :1774-1900. Gate item 1 needs the
  design to STATE whether projection re-derivation invalidates outstanding
  witness positions (rowids are cleared and re-assigned on rebuild — trace
  what that means for previously-resolved positions and for seals).
- Rule 18 vocabulary ratchet (tests/architecture/test_rule_18_arrival_vocabulary_denylist.py):
  _SCAN_TARGETS grow "when a later slice moves custody into a module, that
  module joins in the same change". Decide which modules join at B and which
  allowlist entries shrink (decision:practice cites "jsonl_store until cut B").
- Arrival substrate surface: arrival.py __all__ (:60-88), append_marked
  (:1256-1307, following= CAS), fsync under lock (:1352-1356).
  ArrivalStore._write interleave handling (arrival_store.py:338-396).

## Questions the proposal MUST settle (each with rationale + rejected alternatives)

Q1. **The re-derivation verb.** Name, signature, custody: which of the three
    catch-up refusals resolve into it, which remain refusals, and what survives
    a re-derivation (store_meta identity rows, mark). Is it a method on
    ArrivalStore, a module function, or both? How does it interact with the
    live write lock?
Q2. **The derived .jsonl projection.** For an arrival-canonical store, what
    exactly is the second derived output: line format (codec lines verbatim
    from record bodies?), ordering on disk, derivation trigger (on write?
    on demand? on merge only?), staleness custody (re-keyed to SET MEMBERSHIP
    per the plan — spell out what the custody check becomes when line order
    stops carrying meaning), and its agreement audit. Name its path/suffix
    relationship to the store.
Q3. **The git merge driver.** Semantic merge of two versions of the derived
    JSONL projection: set-union by what key (record hash? fact id? whole
    line?), output ordering (deterministic — what order), conflict cases
    (same id, different bytes — refuse or resolve?), and the proof shape
    (an actual `git merge` in a fixture repo — design the fixture). Driver
    lives in libs/store or libs/engine? (Registration is wave-2; design the
    executable + tests only.)
Q4. **merge_store/receive_store rewrite.** New write path: append-into-arrival
    + re-derive both projections. What is the arrival record shape for a
    merged-in foreign fact (observer? signer? the source store's signatures
    ride in body verbatim?). Direction semantics after R1-as-doctrine is
    discarded: what IS the ordering claim of a merged store now (ordinal =
    arrival order at the target). What happens when the target is
    jsonl-canonical or plain-sqlite (legacy modes keep the old path?
    dispatch on canonical_mode?). What replaces the discarded test.
Q5. **Restamp verb.** Name, what it may restamp (the mark only — never rows?),
    preconditions (log readable, records verifiably consumed?), refusal cases,
    and how it resolves the fsync/COMMIT crash window (AmbiguousGenesis
    parking). Is it reachable from catch-up automatically or operator-invoked?
Q6. **Offset/count triple custody.** What "moves to arrival" means precisely
    for each key: which stamps disappear for arrival-canonical stores, what
    canonical_audit reads meanwhile (its FULL custody move is cut D — draw
    the B/D seam explicitly so B neither does D's work nor breaks D's plan
    premise).
Q7. **Witness-position invalidation** (gate item 1, answered at design level):
    does re-derivation preserve rowids? If not, state the invalidation story
    for outstanding WitnessPositions and seals — including whether cut B must
    preserve rowid assignment order (dense ordinal consumption implies
    deterministic rowids?) or must declare positions ephemeral.
Q8. **Codec decoded-dict entry + _log_size/_has_rows home.** Concrete API for
    the codec growth (cross-lib change — name the entry point and its
    contract); the mixin/base home for the duplicated helpers.
Q9. **Rule 18 growth + vocabulary.** Which modules join _SCAN_TARGETS at B;
    which allowlist entries shrink; candidate denylist additions surfaced by
    this design (e.g. merge-touches-custody senses now mechanizable?).

## Constraints (non-negotiable, from ratified rulings)

- Arrival law 1: reads execute through the index; the log is the sole
  authority. A projection is a function of the log, rebuildable at will.
- Record bodies are byte-verbatim codec objects; every existing signature and
  commitment survives round trips. No second encoding.
- id is NEVER semantic time. Ordering claims come from the arrival ordinal.
- Consume-or-refuse posture: no silent drops, no repair that destroys
  evidence. Re-derivation is an explicit verb, never an open-time side effect
  for a store that carries state.
- apps/ diff-empty; preflight.py untouched (that is cut D's protected zone —
  don't touch canonical_audit defaults either, D moves them).
- Vocabulary: the ratified glossary (arrival log, record, lineage, ordinal,
  coordinate, genesis, head, append, resume mark, torn tail, projection,
  body). No denied terms in new identifiers (Rule 18).

## Deliverable format

Write your proposal to
`/Users/kaygee/Code/loops/docs/scratch/arrival-sliceB/design-proposal.md`:
one section per question Q1-Q9, each with THE RULING (what you propose),
grounding (file:line evidence), and rejected alternatives with why. Close with
a draft design-fact body (the invariant list a review brief can quote
verbatim, NON-NEGOTIABLE lines marked) and a slice/commit plan (suggested
commit seams for the implementer). File-then-return: write the file, then
also send the full proposal text as your final report.
