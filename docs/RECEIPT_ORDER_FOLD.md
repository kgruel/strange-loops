# Fold replay order is receipt order

**Status:** ratified 2026-08-15. Supersedes `decision:design/replay-total-order`.
**Fact:** `decision:design/replay-receipt-order`.
**Anchor:** `docs/CONCEPTUAL_MODEL.md` — *"Event time never substitutes for
receipt order."* This change is that line finally holding everywhere.

## The decision

A vertex store replays its facts in **receipt order** — `facts.rowid`, the order
this store actually received them. That is the fold. The ULID `id` is stable
identity; `ts` is event-time metadata the emitter supplied. Neither orders the
fold.

`(ts, id)` survives as an explicit **read lens**: an event-time projection a
reader may ask for. It is a way of *looking at* the facts, never the order they
are folded in.

Receipt order is **store-local**. A rowid means something only relative to the
store that assigned it. Everything below follows from that one property.

### What it replaces

`decision:design/replay-total-order` made `(ts, id)` the fold order on the
grounds that it is a store-independent total order, so any two stores holding
the same facts fold to the same state. That was true and it was expensive: a
backdated arrival lands in the middle of the history, so every append could
re-order the whole fold, and the only sound way to answer a read was to re-fold
everything. Ingest was O(n²) in consequence.

It was also dishonest in a way the conceptual model already named. Event time is
a claim the emitter makes; receipt order is what this store witnessed. Folding on
the former let an emitter's clock rewrite what a reader had already been shown.

Under receipt order a fact folds where it arrived, an append is a suffix, and a
held fold can be advanced by folding just the new rows onto it. Determinism is
unchanged — it is now determinism *given a store*, which is the honest scope.

## Rulings

### R1 — merge inserts by `(ts, id)`; that IS the merge ceremony

`store.merge_store` inserts the source's rows into the target ordered by
`(ts, id)` (`libs/store/src/store/merge.py`). The SQL did not change and the
reason it did not is the ruling:

A merged store is a **new store**. The rowids the merge hands out *are* that
store's receipt order — the merge is the receipt event. So the insertion order
is not an incidental scan order to be documented away; it is the ceremony that
defines what the merged store folds. `(ts, id)` is chosen because it is
deterministic for given source content.

What survives of commutativity is **narrower than it was, and it must be stated
narrowly.** Under the old decision `merge(A,B)` and `merge(B,A)` re-folded
identically, because both fed the same store-independent sort into the fold.
That is **no longer true and must not be claimed**. A merge appends the source's
rows after the target's existing rowids, so the two directions produce different
receipt orders and therefore different fold sequences: merging B into A folds
A's rows then B's; merging A into B folds B's rows then A's.
`libs/store/tests/test_merge.py::test_merge_direction_sets_fold_order_by_receipt`
pins exactly this.

That is not a defect. It is receipt order being honest: the two merges *are*
different custody events, and a store folds what it received in the order it
received it.

What merge still guarantees, and what R1 is actually about:

- **Determinism per direction.** For given source content, `merge(A,B)` lays
  down one specific rowid sequence, every time — never a scan order. This is
  what the `(ts, id)` insertion convention buys, and it is why the convention is
  load-bearing rather than incidental.
- **Content equality across directions.** Both results hold the same fact set
  with the same ids (dedup is on the id primary key). They disagree on fold
  *sequence*, not on what was merged.

Fold-state equality across directions therefore holds only for order-insensitive
fold ops, and is not a merge guarantee. Code and prose must claim determinism
and content equality — never identical fold sequences.

### R2 — combined reads use the `(ts, id)` lens (named interim state)

A combine/discover vertex reads across several attached member stores. rowid is
per-store, so a `UNION ALL` over members has **no receipt axis at all** —
`ORDER BY rowid` across it would be meaningless, not merely different.

Combined reads therefore fall back to the explicit `(ts, id)` read lens
(`libs/engine/src/engine/vertex_reader.py`, `_combined_read` and
`facts_in_range`). A combined fold is a **lens projection, not a receipt
replay**, and it may disagree with a single-store fold over the same facts.

This is an **interim state, named rather than hidden**. What receipt order means
across members — a per-member cursor vector, a merge-into-one ceremony, or
accepting that aggregates fold on a lens — is an open design question. Until it
is ruled, no code should claim single-store and combined folds agree.

### R3 — the CAS token rides the receipt axis

`SqliteStore.declaration_head` / `_declaration_head_in_txn` surface the token
`absorb_edit` compares `expected_head` against. It is `(rowid, id)` — receipt-
ordered, the same axis `declaration.py`'s resolver now folds on. The token and
the resolver must move together or optimistic concurrency compares two different
notions of "head".

The `at` (`rowid <=`) / `as_of` (`ts <=`) **selector duality** is untouched by
all of this. Both are selectors, and neither is a lens — see the ruling below.

### `as_of` is a selector, not a lens

`decision:design/as-of-is-a-selector-not-a-lens`.

`as_of` is an **event-time selector over the receipt-order fold**. It decides
WHICH facts fold — `ts <= T` — and never how they order. The rows it selects
fold in receipt order, exactly like every other fold; `at` differs from it only
in where the cutoff is drawn (`rowid <=` versus `ts <=`), not in what happens
after.

The code was already right: `StoreReader.facts_by_kind` applies `until_ts` as a
`WHERE` clause and orders by `rowid` regardless. It was this record that
overclaimed, by filing `as_of` under the read lens.

The distinction matters because it is the whole point of the change. A lens
re-**orders**; a selector re-**scopes**. Calling `as_of` a lens smuggles the
superseded model back in — it implies that asking an event-time question gets
you an event-time *ordering*, which is exactly what receipt order removed. A
backdated fact inside the cutoff folds at its receipt position, last, the same
as it would at head. Pinned by
`libs/engine/tests/test_fold_as_of.py::TestAsOfFoldsInReceiptOrder`.

Event-time **ordering** lives on the lens surface only — the `(ts, id)` read
lens, timelines, combined reads.

## What follows for prose

The load-bearing distinction, and the one the ratchet enforces:

- **Fold / replay order** — receipt order, `rowid`, store-local. Never `(ts, id)`.
- **Selector** — `at` (`rowid <=`) and `as_of` / `until_ts` (`ts <=`). These
  choose which facts fold. They do not order anything; what they select folds
  in receipt order. Never call a selector a lens.
- **Read lens** — `(ts, id)`, timelines, combined reads. This is the only place
  event-time ORDERING lives. Explicitly a projection. Must say so.

"Late arrival" is now a **lens-level observation**, not a fold warning. A fact
that arrives out of event-time order folds last, like any other arrival, and
perturbs nothing. What it tells a reader is that the `(ts, id)` lens over that
window will order those rows differently from the fold — so a lens-ordered view
of the window is not the fold's history.

`tests/architecture/test_rule_17_fold_order_prose_is_receipt_order.py` is the
ratchet: no shipped prose in `libs/`, `apps/`, `spec/`, or `docs/` may claim
`(ts, id)` is the fold order outside a shrink-only allowlist of genuinely
lens-labeled sites.

## Where it is implemented

| Concern | Site |
|---|---|
| Kind-filtered fold read | `libs/engine/src/engine/store_reader.py` — `facts_by_kind` |
| Raw / cursor reads | `libs/engine/src/engine/sqlite_store.py` — `since`, `since_raw`, `replay_cursor` |
| Single-store vertex fold | `libs/engine/src/engine/vertex_reader.py` — `_combined_read` (single-store branch) |
| Declaration resolution + head | `libs/engine/src/engine/declaration.py` |
| CAS token (R3) | `libs/engine/src/engine/sqlite_store.py` — `declaration_head` |
| Incremental fold | `libs/engine/src/engine/handle.py` — `replay_mode="checkpoint-suffix"` |
| Suffix fold primitive | `libs/atoms/src/atoms/spec.py` — `Spec.replay_from` |
| Merge ceremony (R1) | `libs/store/src/store/merge.py` |
| Combined-read lens (R2) | `libs/engine/src/engine/vertex_reader.py` |
| Normative spec | `spec/conformance/SCHEMA.md` §6 replay, §7 witness, §8 merge, §9 lens |
| Lens conformance vectors | `spec/conformance/vectors/lens/` |

## Open

- **R2's interim state.** Combined folds ride a lens. Needs a ruling.
- The merge vector still carries the name
  `merge-interleaved-timestamps-replay-total-order`, from the superseded
  decision. Renaming it regenerates a conformance vector, so it is deliberately
  left for a spec change rather than a prose sweep.
