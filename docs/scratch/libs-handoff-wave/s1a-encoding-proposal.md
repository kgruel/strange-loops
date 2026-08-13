# S1a — Canonical-log encoding for declaration ceremonies (JSONL-canonical stores)

Status: PROPOSAL (design only, no implementation)
Scope: `JsonlStore.absorb_genesis`, `JsonlStore.absorb_edit`. `reanchor` stays refused — it is
history-mutating, not append-shaped, and belongs to the (undesigned) log-rewrite ceremony.
Contract source: `docs/scratch/libs-handoff-wave/LIBS_CHANGES.md` P0.1.

## Chosen shape — two parts, only one of them new grammar

The load-bearing observation: **declaration rows are ordinary 7-field fact rows** (kinds
`_decl.genesis`, `_decl.*-defined`, `_decl.*-retired`, minted by `SqliteStore.absorb_genesis`
/ `absorb_edit` via `FACT_INSERT_SQL`). The codec already carries them as `"t":"fact"` lines.
The only genuinely new problem is *multi-row atomicity*, and only `absorb_edit` has it.

1. **Genesis: no new grammar.** `_decl.genesis` is one fact row. The refusal exists solely
   because the sqlite ceremony's compare-and-swap (CAS) may roll back *after* the row is built,
   and flush-first durability would make a rolled-back genesis real in the log. That dissolves
   by reordering into the exact shape `JsonlStore._write` already has: run every CAS check in
   the staged (uncommitted) transaction *before* any byte reaches the log. No codec change,
   no new record type.

2. **Edit: one `"t":"batch"` line.** A multi-row edit ceremony serializes as a single JSONL
   line whose `rows` array holds the N ordinary fact record objects, in emission order. One
   line is the atomicity unit the log already has: a line is either complete-with-newline or
   torn, and a torn tail is truncated on the next open. So "recovery cannot expose a partial
   ceremony" is inherited from `_truncate_torn_line` for free — no framing records, no
   replay buffering, no pending state.

This is option (a) from the task (batch/envelope), with genesis carved out because it
dissolves into the existing grammar entirely — the envelope is minted only where multi-row
atomicity actually exists.

## Wire format

### Genesis (existing grammar, unchanged)

```json
{"t":"fact","id":"01JA…","kind":"_decl.genesis","ts":1765432100.123,"observer":"kyle","origin":"","payload":"{\"protocol\":1,\"documents\":[…],\"chain_head\":null,\"fact_cursor\":\"01J9…\"}","signature":"eyJ…"}
```

### Edit ceremony (new record type)

```json
{"t":"batch","rows":[
  {"t":"fact","id":"01JB1…","kind":"_decl.kind-defined","ts":1765432200.5,"observer":"kyle","origin":"","payload":"{\"lineage\":\"01JA…\",\"subject\":\"decision\",\"change\":\"modified\",\"payload\":{…}}","signature":"eyJ…"},
  {"t":"fact","id":"01JB2…","kind":"_decl.kind-retired","ts":1765432200.5,"observer":"kyle","origin":"","payload":"{\"lineage\":\"01JA…\",\"subject\":\"note\",\"change\":\"removed\"}","signature":"eyJ…"}
]}
```

(One line on the wire; wrapped here for readability.)

### Codec rules for `batch` (`jsonl_codec._SPEC` gains one entry)

Rules run in both directions (serialize validates like deserialize, same as today):

- `rows` is a JSON array of **≥ 2** record objects. A 1-row batch is a second spelling of a
  plain line — same one-canonical-form ethos as "signature must be absent, not null". A
  single-change edit ceremony emits a plain `"t":"fact"` line.
- Each element must validate as a **fact** record (full `_validate` against `_SPEC["fact"]`,
  including the verbatim-payload-as-TEXT-string rule — signatures and commitment hashes
  survive round-trip unchanged, per inner row). Tick records and nested batches are rejected.
  Ticks are minted one-at-a-time by `append_tick` and chain-linked; batching them has no
  consumer and would complicate `prev_hash` derivation — widen later if a consumer appears.
- No key other than `t` and `rows` on the envelope. Duplicate `id` **within** one batch is
  rejected at the codec gate (sibling of `_no_duplicate_keys`) — otherwise a dup only
  surfaces as tail-forward → PK collision → rebuild → `JsonlCanonicalUnsupported`, three
  layers away from the append site where it is attributable.
- The codec does **not** require rows to share one `ts`. Rationale below (Decision D1).

**D1 — same-ts is a ceremony rule, not a codec rule.** The contract's "every row shares one
effective timestamp" is a property of the *declaration edit ceremony*. Baking it into the
transport record would make `batch` unusable for the contemplated future batch-emit (facts
with distinct ts, ordered by emission sequence — `atoms/typed-edge-array-values` arc). So:
`absorb_edit` already stamps one `ts` across the ceremony (sqlite path, step 3) and keeps
doing so; `audit_deep` additionally asserts same-ts for any batch whose rows are all
`_decl.*` kinds. Codec stays structural; the ceremony invariant is enforced where the
ceremony lives and verified where verification lives.

## Write path — `JsonlStore` overrides

Both ceremonies share one preamble rule (the `_sync_derived_state` rule, generalized):
**reconcile before the CAS reads.** Genesis derives `chain_head`/`fact_cursor` from the
index; edit derives the declaration head. A durable-but-unindexed line must be consumed
before either derivation, or the mis-derivation lands in the canonical log where no rebuild
can repair it.

Sequence (both ops), mirroring `_write`'s five steps:

1. `self._reconcile()` — index consumes any durable unindexed line first.
2. `BEGIN IMMEDIATE` (explicit, autocommit mode as today) — takes sqlite's write lock, so
   the committed markers and lineage state read next cannot be raced by another handle.
3. **All CAS checks and refusals** inside the transaction, before any log byte:
   `GenesisExists` / `NoGenesis` / `AmbiguousGenesis` / `StaleDeclarationHead` /
   `ReservedKindViolation` / `UnsignableGenesis` / `UnsignableEdit`. Payload building and
   signing happen here — the signature covers the exact `payload_text` that rides verbatim
   into the line (contract: "signatures cover the final persisted payload").
4. **Stage** the INSERTs uncommitted: genesis stages one fact row + the
   `store_meta.own_lineage` upsert; edit stages N fact rows in ceremony order (insert order
   = `rows` array order = rowid order, so witness order and deep-verify order agree).
5. Serialize: genesis → `serialize_fact_row`; edit → `serialize_batch(rows)` (N == 1 → a
   plain fact line, per the ≥2 rule). Append the ONE line, flush + fsync.
6. Stamp offset + counts (facts += N), COMMIT. Any failure after step 5's fsync rolls back,
   leaving the line durable and unindexed — the standard recoverable state; the next
   open/reconcile tails it forward.

A refusal at step 3 or 4 rolls back with the log untouched — **stale `expected_head` leaves
the log byte-identical to its pre-call state**. One nuance for the acceptance test: the
step-1 reconcile may have lawfully caught the *index* up to lines that were already durable
before the call. That is convergence toward the log (the index becoming a more faithful
derivation), not a ceremony artifact; "byte/row equivalent" means log unchanged + index a
pure function of that unchanged log.

## Replay / open / verify / recovery interactions

**`_index_lines` / catch-up / rebuild:** on a `batch` line, expand and insert each inner row
in array order; `facts += N`; the offset stamps at the line's end as today. Atomicity at
replay is inherited: the line is indexed entirely or (torn) truncated entirely. The
`_RowAlreadyIndexed` / rebuilding-dup logic applies per inner row unchanged.

**Open-time detection stays two cheap checks, no content walk.** Count parity: unchanged
mechanism, the stamp already carries totals; a batch line just contributed N to the stamped
count when written. Last-line integrity (`_prefix_intact` and `canonical_audit._check_last_line`):
when the last consumed line is a batch, run `row_matches` for **each inner row**. Cost is
bounded by ceremony size (a handful of subjects), not log size — the "one line, not the
file" posture holds.

**`audit_deep`:** `_iter_lines` expansion — a batch line yields its inner rows in order,
compared field-for-field against the index exactly as plain lines are; plus the D1 same-ts
assertion for all-`_decl.*` batches. The tick-chain re-derivation is untouched: declaration
rows are facts, a later tick's `window_hash` commits their content like any fact's, so an
interior edit to a *sealed* ceremony row breaks `verify_chain` exactly as today. The
live-edge residue is also unchanged: an unsealed ceremony row's witnesses are its signature
and the next seal — same custody boundary the module already documents. Declaration rows
never appear *in* tick records, so window semantics need no change at all.

**Fold-replay order:** ceremony rows share one ts, so `(ts, id)` replay orders them by id —
ids are minted in emission sequence, and subject-granular diffs mean no two ceremony rows
touch the same subject, so intra-ceremony order cannot change declaration resolution.

**Recovery matrix:**

| Crash / failure point | State | Recovery |
|---|---|---|
| During step 3–4 (refusal, signer failure, stale head) | log untouched, txn rolled back | none needed; caller retries |
| Mid-append (torn line) | partial line, no newline | truncated on next open; ceremony never happened; retry |
| After fsync, before commit (edit) | batch line durable, unindexed | next open/reconcile tails it; all N rows index atomically |
| After fsync, before commit (genesis) | genesis line durable, unindexed, `own_lineage` never stamped | next open tails the row in; the **pre-marker adoption path** (single genesis row, no marker → adopt as self, backfill marker) self-heals identity. A caller retry then gets `GenesisExists` — the honest receipt for "your genesis is durable; you never saw the receipt" |
| After commit | done | n/a |

Note on genesis + rebuild: `store_meta` (incl. `own_lineage`) survives rebuilds by design;
a fresh clone (log tracked, no db) re-derives identity through the same adoption path.

## Rejected alternatives

- **(b) Prepare/commit framing records.** Two-plus lines reintroduce the torn window between
  them. A prepare whose commit never lands is a durable line that must never be indexed —
  either permanently-unindexed dead bytes (offset/count bookkeeping breaks; the index stops
  being a pure function of the log without carrying pending-state memory) or a compensating
  abort record (a third type). Replay must buffer across lines; Go must implement the same
  state machine. Strictly worse on every axis the task weighs.
- **Multi-line append with one fsync, no envelope.** POSIX does not make a multi-block write
  atomic; a crash can persist a complete prefix of the ceremony's lines, which truncation
  cannot detect (they are well-formed). Fails "recovery cannot expose a partial ceremony."
- **Collapse the whole edit into one fact whose payload holds all changes.** That is what
  genesis already is, but for edits it rewrites the S2 resolver contract (per-subject
  `_decl.*-defined`/`-retired` rows) and the Go mirror of it — a much larger protocol change
  than a transport envelope, for no gain.
- **Ceremony-id field + commit flag on the last row** (plain lines, logical grouping).
  Same buffering/dead-bytes problem as (b), plus it pollutes the fact schema with transport
  concerns.
- **Same-ts as a codec rule** — rejected per D1 (blocks future batch-emit reuse).
- **Batches of ticks / nested batches / 1-row batches** — rejected per codec rules above.

## Go conformance — how alignment stays checkable

Golden log fixtures, in-repo (e.g. `libs/engine/tests/fixtures/jsonl/`), as the
cross-language contract — the Go conformance oracle (thread:loops-go-conformance-oracle)
consumes the same files when it lands. Python tests pin them now:

- **Positive:** a log containing a genesis line, ordinary facts, a 2-row and a 3-row edit
  batch, and a sealing tick — fixture asserts the exact decoded row sequence, index row
  counts, and that `audit_deep` passes.
- **Negative (each must be refused, with the refusal class pinned):** empty `rows`; 1-row
  batch; nested batch; tick record inside a batch; duplicate id within a batch; unknown
  envelope key; torn batch line at EOF (truncation, not error); `_decl.*` batch with mixed
  ts (audit_deep divergence, not codec error — pins D1's boundary).

## Acceptance tests (implementation slice's gate)

1. Genesis succeeds against a new `.jsonl`-canonical store; receipt matches sqlite-canonical
   behavior; log carries one well-formed `_decl.genesis` fact line; `audit_deep` passes.
2. Second genesis refuses `GenesisExists`; log byte-identical before/after.
3. Kind add / modify / retire round-trip through declaration resolution on a JSONL-canonical
   store; multi-change ceremony lands as one batch line; all rows share one ts.
4. Single-change ceremony lands as a plain fact line (no 1-row batch ever written).
5. Stale `expected_head` refuses `StaleDeclarationHead`; log byte-identical; index a pure
   function of the unchanged log (allowing lawful pre-CAS catch-up, per the nuance above).
6. Fault injection: (a) before append — log untouched; (b) after append, before index
   commit — next open tails the full ceremony in, never a subset; (c) torn line — truncated,
   no ceremony; each followed by a passing `audit_deep`.
7. Rebuild from log (delete `.db`) reproduces identical facts/ticks including ceremony rows,
   in the same rowid order; `own_lineage` survives or re-derives via adoption.
8. `_prefix_intact` / `_check_last_line` on a store whose last line is a batch: detects an
   index-side edit to ANY row of that batch.
9. Golden fixtures (previous section) pass in Python; negative fixtures refuse with the
   pinned classes.
10. `reanchor` still refuses `JsonlCanonicalUnsupported` (scope pin).
