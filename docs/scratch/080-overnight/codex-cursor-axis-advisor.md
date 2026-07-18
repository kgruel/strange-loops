## Recommendation

Gate 0.8.0 on a **witness-prefix cursor**:

> A cursor denotes the inclusive prefix of facts/declaration events that this store had received at a particular witness position. The selected prefix is then replayed in normative `(ts, id)` order.

That preserves the protocol’s essential distinction:

- **Selection:** witness order — which rows were present.
- **Replay:** `(ts, id)` event/observation order — how that selected set derives state.

SPEC §8.4 explicitly assigns those two jobs to different authorities and says neither substitutes for the other ([SPEC.md:843](/Users/kaygee/Code/loops-go/SPEC.md:843)). A historical UI cursor belongs to the first job; §6.2 remains authoritative for the second ([SPEC.md:566](/Users/kaygee/Code/loops-go/SPEC.md:566)).

Do not make `ts <= T` the common Rewind/Watch cursor. Keep that as an explicit analytical query meaning “what is currently known to have observation-time ≤ T.”

### Resolution and selection

Resolve every common cursor address to:

```text
WitnessPosition {
    store_lineage,
    end_fact_id,       # inclusive; empty sentinel allowed
    display_seq        # derived ordinal, not identity
}
```

In SQLite, `end_fact_id` resolves to its current rowid. Selection is:

```sql
WHERE rowid <= rowid(end_fact_id)
```

Then:

1. Select domain facts and self-lineage declaration rows in that prefix.
2. Resolve ontology from the selected declaration set, ordered by `(ts, id)`.
3. Replay the selected domain facts in `(ts, id)` order.
4. Exclude `_decl.*` from domain folding/display, but never from cursor advancement.

This makes §9.3’s equal-cursors rule concrete: the facts and ontology cursors default to the **same witness position P**. Both see exactly the rows available at P. Unequal positions remain the explicit reinterpretation escape hatch required by §9.3 ([SPEC.md:1110](/Users/kaygee/Code/loops-go/SPEC.md:1110)).

The current S5 resolver must therefore gain witness-position selection. Its current `ts` cutoff is an interim implementation, not a settled protocol authority: the module itself says witness-order as-of is deferred until a fact-cursor surface exists ([declaration.py:50](/Users/kaygee/Code/loops/libs/engine/src/engine/declaration.py:50)). Its SQL currently filters declarations only with `_ts > as_of` ([declaration.py:313](/Users/kaygee/Code/loops/libs/engine/src/engine/declaration.py:313)).

## Address forms

Use several user addresses, but resolve them all to the same internal witness position:

| Address | Resolution |
|---|---|
| `head` / `now` | Atomically capture the newest fact ID by witness order. Once returned, freeze it; do not persist a moving “head” token. |
| `seq:116` | The 116th fact-table receipt, including hidden declaration rows. Resolve immediately to its fact ID. |
| `fact:01J…` | Exact inclusive witness prefix ending at that fact. This is the durable canonical cursor. |
| `tick:01J…` | Resolve the tick, verify/report its chain status, then use its stored `fact_cursor`. |
| ISO timestamp | Resolve to the greatest eligible tick anchor at or before that timestamp, then use that tick’s `fact_cursor`. Report the snap explicitly. |

For the mock, render something like:

```text
seq 116 · fact 01JQ… · anchored by tick 01JR… at Jan 10 16:58
```

The mock’s `seq 116` should mean **fact witness ordinal**, not tick sequence. Neither the tick table schema nor the signed tick envelope currently contains a sequence field ([SPEC.md:157](/Users/kaygee/Code/loops-go/SPEC.md:157), [SPEC.md:806](/Users/kaygee/Code/loops-go/SPEC.md:806)).

A wall-clock address cannot produce an exact receipt-time snapshot because facts carry no receipt timestamp. It must therefore snap to a tick and say so. If there is no prior resolvable tick, return “no witness-time anchor,” not an approximation using fact `ts`. Tick timestamps are signed claims, not proof of an accurate physical clock.

Tick IDs are addresses/anchors, not a third ordering authority. A tick already maps to a witness prefix through `fact_cursor`; its window is defined in witness order ([SPEC.md:816](/Users/kaygee/Code/loops-go/SPEC.md:816)).

## `read --diff`

For cursors `P1` and `P2`:

```text
S1 = fold(prefix(P1), ontology(prefix(P1)))
S2 = fold(prefix(P2), ontology(prefix(P2)))
diff = structural_semantic_diff(S1, S2)
```

Compute both snapshots independently. Do **not** apply only facts in witness interval `(P1, P2]` to `S1`: a newly received backdated fact may insert near the beginning of `(ts, id)` replay and alter all order-sensitive downstream results.

The output should include:

- state changes;
- resolved fact IDs/sequences and tick anchors;
- ontology head at each endpoint;
- whether the interval contains declaration changes or late arrivals.

With equal cursors, a diff legitimately combines data arrival and ontology change. A fixed-ontology diff should require an explicit unequal-ontology option.

## Rewind and Watch

They should use the same witness-prefix axis.

- **Rewind:** scrub discrete fact receipt positions. Tick markers decorate positions; they do not define the only reachable positions. Multiple ticks may anchor the same fact position.
- **Watch:** tail new receipts in witness order and report `seq N`. Hidden `_decl.*` rows still advance the cursor and can trigger a state/ontology update.
- **Fold state in Watch:** after a late arrival, recompute the prefix under `(ts, id)`, or use an insertion-aware equivalent. Blindly applying the new fact after the old head would violate §6.2.
- **Tick arrival without new facts:** render a new anchor at the current sequence; it does not advance fold-state position.

A tick payload may be used as a cache only if its semantic provenance is trusted. The chain attests bytes, linkage, and receipt windows; it does not by itself prove that the embedded fold snapshot was computed correctly.

## Merge behavior

The correct split is:

- **Must be merge-stable:** head fold state for the same fact set and ontology; explicit `ts <= T` analytical projections; any replay of the same selected set. This is why replay remains `(ts, id)`, which SPEC §6.2 and the Go merge differential enforce ([SPEC.md:574](/Users/kaygee/Code/loops-go/SPEC.md:574), [merge_test.go:10](/Users/kaygee/Code/loops-go/internal/conform/merge_test.go:10)).
- **Legitimately per-store:** Rewind trajectory, Watch sequence, tick windows, witness-position diffs, and attestation. SPEC explicitly says set-determinacy does not apply to attestation because it is a function of receipt order ([SPEC.md:76](/Users/kaygee/Code/loops-go/SPEC.md:76)).

Thus `merge(A,B)` and `merge(B,A)` may have different historical cursor trajectories but must converge at head when they contain the same fact set and interpret it under the same ontology.

Bind serialized witness cursors to store lineage. Finding the same fact ID in a different merged store does not mean the preceding prefix is the same.

## Rebuild stability

A raw SQLite rowid cursor does **not** survive rebuild. A fact-ID witness cursor does.

SPEC §10.1 normatively says the dump carries rows in witness order so rebuild reproduces it ([SPEC.md:1191](/Users/kaygee/Code/loops-go/SPEC.md:1191)); §10.3 requires byte-identical round trip and equivalent verification ([SPEC.md:1209](/Users/kaygee/Code/loops-go/SPEC.md:1209)). Therefore:

- Fact IDs remain the cursor identity.
- Rebuild may assign different rowid numbers, but each fact ID resolves to the equivalent prefix.
- Derived `seq:N` survives only because relative fact line order is preserved.

There is an underspecification: facts and ticks currently occupy separate tables with separate rowid domains, yet §10 promises one globally witness-ordered stream. The existing schema cannot always recover a total facts↔ticks interleaving, especially for pre-chain ticks. Before implementing §10, add an explicit dump-level/global receipt ordinal or narrow the promise to the partial ordering recoverable from fact order, tick-chain order, and `fact_cursor`.

## Late-arrival answer

Suppose:

1. At receipt sequence 100, the store receives `A`, `ts=10:00`, amount `+10`.
2. At 10:01 it emits tick `K`, whose `fact_cursor=A`.
3. At receipt sequence 101, at 11:00, an import delivers `L`, carrying `ts=09:30`, amount `+5`.

At cursor `tick:K` / `seq:100`:

- **Witness selection:** `{A}` → state `10`. This is what the store’s reader could have seen when K was made.
- **`ts <= 10:01` evaluated after 11:00:** `{L,A}`, replayed `L` then `A` → state `15`. This is current retrospective knowledge about observation-time through 10:01.

At `seq:101`, witness selection becomes `{A,L}`, but replay is `(L,A)`, so state is `15`. The diff from 100 to 101 is the structural difference between those full replays.

The first answer is §9.3 receipt-honest. The second is valid and merge-stable, but it must be labeled “event-time/retrospective,” not “what a reader at 10:01 saw.” SPEC §8.4 says exactly why a late arrival must not retroactively enter an already sealed witness window ([SPEC.md:859](/Users/kaygee/Code/loops-go/SPEC.md:859)).

## Strongest failure of each pure choice

- **Pure `ts`:** historical answers are mutable. A late import changes yesterday’s state and can expose declarations that the store had not received then. It cannot drive a receipt tail or align exactly with tick coverage.
- **Pure witness/rowid:** raw rowids are storage-local and rebuild-unstable; wall-clock resolution is impossible without anchors; trajectories are deliberately non-merge-stable. Fact-ID handles solve the first defect, while ticks solve only the coarse time-address problem.
- **Pure tick-anchor:** positions are sparse. It cannot represent unsealed facts, pre-chain history, or every Watch update. Ticks are excellent verified names for witness positions, but inadequate as the position space itself.

## Equal-cursor coherence and S5

Equal cursors must share the same **selection axis**. They need not use receipt order for folding.

The coherent default is:

```text
facts selected at witness P
ontology selected at witness P
both selected sets reduced in (ts,id) order
```

The current S5 tests establish only float-cutoff behavior, including the inclusive same-`ts` rule ([test_ontology_as_of.py:162](/Users/kaygee/Code/loops/libs/engine/tests/test_ontology_as_of.py:162)). Their head-equals-now case contains no late arrival and explicitly constructs only ordinary increasing timestamps ([test_ontology_as_of.py:192](/Users/kaygee/Code/loops/libs/engine/tests/test_ontology_as_of.py:192)). It therefore does not prove §9.3’s “what the reader saw” claim under import/backfill.

Under the recommended design, a same-`ts` declaration edit affects a cursor only after that declaration has entered the selected witness prefix. That is the honest resolution of the current “edit wins regardless of append order” behavior.

## Go conformance impact

Existing Go vectors assume no as-of selection axis:

- Fold vectors contain only folds, an already ordered payload list, and expected state ([vectors_test.go:26](/Users/kaygee/Code/loops-go/internal/conform/vectors_test.go:26)).
- The vector runner applies those payloads directly; there is no cursor or cutoff ([vectors_test.go:62](/Users/kaygee/Code/loops-go/internal/conform/vectors_test.go:62)).
- The store reader reads the entire store in `(ts,id)` order ([sqlite.go:23](/Users/kaygee/Code/loops-go/store/sqlite.go:23)).
- The merge fixture tests full-store convergence, not historical selection ([merge_test.go:31](/Users/kaygee/Code/loops-go/internal/conform/merge_test.go:31)).

Therefore a ts-based fold-as-of would break **no existing Go vector**. Neither would witness-prefix selection at head. Current green conformance provides no evidence for either decision.

The decisive late-arrival/two-authorities vector is explicitly still “owed” by SPEC §8.7 ([SPEC.md:912](/Users/kaygee/Code/loops-go/SPEC.md:912)), as are dump/rebuild witness-order vectors in §10.5 ([SPEC.md:1235](/Users/kaygee/Code/loops-go/SPEC.md:1235)). Add cursor-selection vectors before calling 0.8 conformant.

## Framing corrections

- There are not three competing orders. Tick anchor is an address into witness order; `(ts,id)` is replay order; witness prefix is selection order.
- SPEC calls `ts` observation time, not receipt time, and not necessarily source-domain event time.
- §9.3 does not currently specify the cursor axis. This is a real spec gap, not a clear conflict with a normative ts cursor.
- §9–§10 are explicitly provisional pending implementation and vectors ([SPEC.md:927](/Users/kaygee/Code/loops-go/SPEC.md:927)).
- “Honest snapshot at wall-clock T” is currently unimplementable between ticks because per-fact witness time is not stored. Rewrite §9.3’s default claim as “what a reader at witness position P could have seen,” with wall-clock inputs documented as tick-floor resolution.