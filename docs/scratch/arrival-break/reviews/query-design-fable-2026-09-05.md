# Query proposal: Fable 5.1 adversarial review

Scope: Terra proposal v1, plus arrival_contract.py, arrival_file_backend.py and
arrival_head_seam.py source packet. Static design review, no execution.
Requested model: `claude-fable-5-1[1m]`; returned metadata confirms
`claude-fable-5-1` with auxiliary CLI Haiku usage.

## Reviewer response

**Verdict: REVISE.** The basis model and open ordering are right. Four defects block acceptance; two are correctness under ordinary concurrency, one violates the read-only rule outright.

## Blocking

**1. Stage 2 hands the read caller an append surface.** The consumer opener "returns `(attested_ledger, query_snapshot, open_report)`". `AttestedLedger` exposes `mint`, `append`, and `replicate` (arrival_head_seam.py, custody section). A read opened through the new SDK path can therefore append with no further check, which contradicts the Decision section's "read-only handle with no append surface" and the standing rule that read-only opens never grant append authority. Fix: return only the snapshot and the report. The coordinator already resolves `head_at` itself in step 4, so no ledger needs to leave the seam. If a read view is needed later, expose `head_at`/`read`/`scan`/`verify` behind a separate narrow object, not the attested ledger.

**2. Step 4 refuses every read that races an ordinary append.** The snapshot "rejects a foreign or ahead watermark", and acceptance test 3 pins "P > H raises the existing projection-ahead refusal". But H is captured at step 3 and the snapshot transaction opens later. Reproduce: capture H=10, a concurrent writer appends 11 and its catch-up moves the watermark to 11, the snapshot reads watermark 11 > H. The design classifies that as tail-truncation evidence. It is not. The same sequence breaks every continuation page: page 1 at H=10, any append plus catch-up, page 2 refuses. This is the seam's own distinction inverted: `_projection` calls `head_at` on the ahead branch and treats the refusal as the answer. Reuse that. Inside the basis step, if watermark.ordinal > H.ordinal then call `attested.head_at(watermark)`. If it answers, the projection is ahead of the capture, not the ledger: bound rows through H and set `projected_through = H`. If it refuses, raise `ProjectionAheadOfLedger`. Rewrite test 3 to name both outcomes.

**3. Step 3 captures H from a second, different observation.** `attested.head()` delegates to `FileLedger.head`, which is a full walk, while the seam's comparison used `verify(Open())`. Every SDK read pays FULL under an OPEN label, and H can differ from the head the projection report was compared against. Fix: take H from `open_report.comparison.presented`. `PreGenesis` has no head and must refuse the read.

**4. Aggregate basis map cannot represent shared lineages.** Stage 5 and the table return `dict[lineage, ReadBasis]`. Two members of one lineage at different prefixes, authority plus replica being the plain case, collide on the key and one basis is silently lost. Fix: key by member identity with lineage as a field on `ReadBasis` as it already is. Duplicate facts across such members is an explicit decision; recommend refuse duplicate lineages in the first cut rather than dedupe.

## Should fix before build

- **`projected_through: Head` cannot be built where the design puts it.** `QuerySnapshot.basis` carries a full head, but the query half holds only a `Watermark` and only custody completes it (arrival_contract.py `Watermark` docstring). The prose says the coordinator resolves it, the types say the snapshot owns it. Smallest fix: the snapshot exposes `represented: Watermark | None`, and the coordinator builds `ReadBasis`. No callback into the query object is then needed.
- **Continuation appears in two places.** `open_snapshot(..., continuation=)` in the Protocol and `facts(..., continuation=)` in the needs table. Pick one. The token constrains the basis, so `open_snapshot` is the right home, with the fact request checked against the token's filter and order hash.
- **Resume needs two checks, spelled out.** "Refuses if either prefix is unavailable" must mean: `head_at(P.ordinal)` returns P's hash, and the new watermark ordinal is at least P. A new watermark below P after a rederive must refuse under `ALLOW_BEHIND` too, since delivered pages already claimed P. Note the represented-prefix hash is the ledger's hash at P, not a projection content hash, so a projection rebuilt from a forked log at the same coordinate is not caught. Known debt, state it in the token docs.
- **Search continuation is not keyset-resumable.** Ranked results have no stable `(arrival_ordinal, arrival_seq, id)` order. Either search pages use receipt order or `SearchPage` offers no continuation in the first cut.
- **The read-only instance role cannot be declared with the file backend.** `Profile` has no read member. `ARCHIVE` is the sealed read-only profile and the file adapter does not advertise it, so a descriptor declaring it fails the capability check. Make READ purely an operation on an `AUTHORITY` or `REPLICA` descriptor and drop the "declared read-only instance role" wording until a backend offers `ARCHIVE`.
- **Opt-in missing-only materialization on the read path races other materializers.** Legacy `ArrivalStore.__init__` still runs `catch_up` on every open. Two projection writers on one SQLite index is undefined in this packet. Keep refuse-by-default, move the opt-in entirely under the maintenance protocol, and require that protocol to state its projection write lock.

## Interface scope

Not yet minimal. Drop `fact(id)`, it is `facts(FactRequest)` with one filter. Drop `resolve_entity`, entity resolution is domain logic unless a projection table backs it, and nothing in the packet says one does. `summary` is defensible only as a performance shortcut; say so. Remaining: `facts`, `ticks`, `summary`, `search` behind capability, `close`. `open_snapshot` on the existing `ArrivalQuery` Protocol is fine.

## Decisions the owner must make

1. Return no ledger from the consumer opener (blocking 1).
2. Advanced-since-capture clamps to H; ahead means `head_at` refuses (blocking 2).
3. H comes from the open report's presented head (blocking 3).
4. Aggregate keyed by member; duplicate lineage refuses (blocking 4).
5. `ReadBasis` built by the coordinator from a `Watermark`.
6. Continuation lives on `open_snapshot` only.
7. Search has no continuation until ordered by receipt.
8. READ is an operation, not a profile.
9. Materialization only via the maintenance protocol, never from a read.

One note, not a defect: a read open still writes the head journal on first contact or advance through `AttestedLedger.__init__`. That is by design and should be stated in the SDK read docs so "read-only" is understood as store-only.

## Primary judgment

Revise before implementation. Accept the read-surface, concurrent projection,
member identity, basis-construction and interface-scope corrections. Reuse the
attested open report as the captured head. READ is an operation, not a new
profile. Keep projection maintenance explicit and serialized.

Do not adopt the suggested blanket refusal of duplicate lineages: multiple
vertices interpreting shared evidence are central to the user’s model. Keep
member identity and basis separate; any deduplication requires aggregate-level
semantics, never a silent map overwrite. Aggregate implementation follows the
single-store acceptance path.

Cursor validity must also account for the query/declaration/projection generation;
ledger membership alone does not prove that derived views are unchanged. Refuse
resumption across incompatible generations in the initial implementation.

Terra is revising the proposal against these judgments and the actual code.
