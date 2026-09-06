# C6 engine design notes: boundary continuity across declaration history

Status: design for cross-model review. No implementation is authorized by this
document. It assumes C3 custody completion and the accepted C5 current-name
reservation are already present.

## Decision to make

D5 says a declaration edit changes interpretation without rewriting facts, while
an unchanged boundary identity keeps its established consumption edge. Restart
and reincarnation must be explicit; a declaration hash is not a boundary ID
([identity decisions D5](identity-decisions-2026-09-06.md#d5--declaration-edits-preserve-history-reset-must-be-explicit)).
C6 exists because the current runtime cannot distinguish a continuously defined
loop from a retired and later recreated loop that happens to reuse its name
([consistency matrix C6](consistency-contract-matrix-2026-09-06.md#prioritized-worklist)).

The bounded policy proposed here is **inherit by runtime role and name while the
role remains continuously present**:

- A loop is `(vertex name, loop role, loop name)`. In-place edits retain that
  identity and its last recorded edge. This includes changing `when`/`after`/
  `every`, counts, matches, conditions, folds, parse, routes, run commands and
  read facets. Those changes can alter current and future conclusions; that is
  the append-forward reinterpretation D5 already permits.
- Retiring the whole loop ends its presence epoch. Recreating the same name may
  reuse an earlier epoch's local tick under the current implementation. Refuse
  the recreation when such a tick exists. A tick-free retirement/recreation is
  permitted: facts alone are interpretation input and make no persisted claim
  that a boundary was consumed.
- A vertex boundary is `(vertex name, vertex-boundary role)`. Its several trigger
  clauses all produce the same tick name and share one vertex-period edge.
  Editing the clause tuple, including empty then nonempty, retains the role; it
  is not treated as a new incarnation.
- A historical local tick whose role was ambiguous when received is not repaired
  by a later C5 configuration correction. In particular, if `origin == name ==
  vertex` and a same-named loop existed at that receipt coordinate, a current
  vertex boundary cannot safely consume it as a vertex-period edge. A repair
  with no such tick is valid. Removing the vertex-boundary consumer as well as
  the colliding loop leaves the ambiguous row available for inspection but out
  of runtime state.

This is intentionally narrower than semantic equivalence. It does not try to
prove that two folds or predicates compute the same result.

The vertex-role refusal is consumer-scoped. `hydrate_snapshot` assigns
`_vertex_period_start` for a local vertex-name tick, but supported detached
execution reads that value only while a current vertex boundary exists:
ordinary ingress gates its initialization on `_has_vertex_boundary`
([vertex.py:662](../../../libs/engine/src/engine/vertex.py#L662)), and pending
planning has the same gate ([vertex.py:1319](../../../libs/engine/src/engine/vertex.py#L1319)).
`_evaluate_vertex_only_boundaries` is reached only behind the current
`_has_vertex_boundary` check ([vertex.py:1204](../../../libs/engine/src/engine/vertex.py#L1204));
the surrounding legacy evaluator also requires an attached store, while the
Arrival candidate is storeless. C5 prevents a current same-named loop from
reading the row through the loop path. Therefore an ambiguous historical tick
does not block a target with neither consumer. A proposal that adds a vertex
boundary must re-run the check and refuse.

## What the engine actually does

### Recorded ticks are edges, not state checkpoints

`Vertex.hydrate_snapshot` merges facts and ticks by receipt coordinate. For an
owned tick (`tick.origin == vertex.name`), it looks up the **current** loop by
`tick.name`, calls `Loop.replay_boundary`, and independently treats
`tick.name == vertex.name` as a vertex-period edge
([vertex.py:769](../../../libs/engine/src/engine/vertex.py#L769),
[vertex.py:784](../../../libs/engine/src/engine/vertex.py#L784)). It never reads
the old tick payload, `since`, fact cursor, window hash or signature into fold
state.

`Loop.replay_boundary` applies the **current** loop's reset/count mode: reset
returns the current projection to its current initial value, `every` zeros the
count, and `after` marks it exhausted
([loop.py:157](../../../libs/engine/src/engine/loop.py#L157)). Therefore an old
edge under a current `after` definition means “already exhausted”; under a
current `every` definition it is the edge from which the new count resumes.
That result should be explicit in tests, rather than described as preservation
of the old trigger policy.

Facts are always routed, parsed and folded under the current candidate
([vertex.py:821](../../../libs/engine/src/engine/vertex.py#L821)). This is why a
fold-only edit is not an “incompatible tick payload” in today's engine: no tick
payload is deserialized. Historical tick payloads remain raw evidence. If a
future runtime hydrates from payload checkpoints, it will need a persisted
checkpoint schema/compatibility claim and is outside this slice.

### Pending boundaries use the same name edge on a different ordering axis

Source-mode pending evaluation builds the latest owned edge per tick name using
event time with receipt coordinate as its tie-break, then scans eligible facts
by event time and receipt coordinate
([vertex.py:1260](../../../libs/engine/src/engine/vertex.py#L1260)). This is
correctly distinct from the declaration-history question: which definition was
in force at a tick is determined by the tick's **receipt coordinate**, not its
event timestamp. The validator must not replace either ordering with the other.

Count boundaries are not invented by pending evaluation
([vertex.py:1275](../../../libs/engine/src/engine/vertex.py#L1275)); their restored
counter/exhaustion state comes from hydration
([vertex.py:835](../../../libs/engine/src/engine/vertex.py#L835)). A continuity
guard must therefore run before both ordinary planning and source pending
planning.

### The supported declaration surface currently has reset only

The generic engine permits `reset=False`, but historized `LoopDef` has no reset
field ([ast.py:518](../../../libs/lang/src/lang/ast.py#L518)). Every DSL boundary
maps to `reset=True`, and materialization copies that value into `Loop`
([compiler.py:541](../../../libs/engine/src/engine/compiler.py#L541),
[compiler.py:981](../../../libs/engine/src/engine/compiler.py#L981)). The
programmatic carry form is therefore not a supported Arrival declaration
transition today.

No reset/carry field should be invented in C6. If one is added later, changing
it in the presence of an earlier local tick must require the explicit transition
ceremony: otherwise `replay_boundary` retroactively applies the new choice to
every old edge. Low-level callers that construct a detached `Vertex` remain
caller-responsible; the supported Arrival authority path reconstructs from
historized documents.

### Final effective documents are insufficient

The snapshot declaration resolver seeds the genesis document set, applies own-
lineage definitions/tombstones in receipt order, and returns only the surviving
documents ([declaration.py:221](../../../libs/engine/src/engine/declaration.py#L221)).
That correctly answers “what is effective now,” but erases the retirement that
distinguishes continuous presence from reincarnation.

Runtime construction fetches all internal facts, resolves only the final set,
compiles/materializes a new candidate, then hydrates it with ticks
([runtime_write.py:715](../../../libs/engine/src/engine/runtime_write.py#L715)).
Declaration preparation currently requests declaration facts only, resolves the
final set, diffs the proposal and starts signing
([arrival_declarations.py:799](../../../libs/engine/src/engine/arrival_declarations.py#L799)).
Both call sites need the same historical analysis before hydration or signing.

## Proposed bounded implementation

### 1. Pure receipt-history analyzer

Add a small engine module, tentatively `arrival_boundary_continuity.py`, with no
store or registry access:

```python
@dataclass(frozen=True)
class BoundaryContinuityIssue:
    reason: Literal[
        "prior-incarnation",
        "ambiguous-tick-role",
        "unproven-generated-incarnation",
        "invalid-projection-shape",
    ]
    vertex_name: str
    loop_name: str | None
    tick_id: str
    tick_ordinal: int
    tick_seq: int
    declaration_fact_id: str | None
    epoch_started_at: tuple[int, int] | None
    retired_at: tuple[int, int] | None

def analyze_boundary_continuity(
    anchor: DeclarationAnchor,
    facts: Sequence[Fact],
    ticks: Sequence[Tick],
    *,
    target_documents: Sequence[Mapping[str, object]],
    verified_params: Mapping[str, tuple[Mapping[str, str], ...]] | None = None,
    compiled_loop_names: Collection[str] | None = None,
) -> BoundaryContinuityIssue | None: ...
```

The target is documents at every call site. Runtime may also supply the compiled
current name set as a two-way cross-check: every provable target name, including
implicit `cite`, must materialize, and every materialized name must be provable
or coverable by an unknown generator at the target revision. A mismatch refuses
rather than letting prepare, preview and capture silently use different
namespace algorithms. Checking both directions also detects a parameter file
swap between the verified-row read and compilation when that swap removes a
known name; the analyzer does not treat a one-way subset check as sufficient.

The exact DTO names are not protocol. The analyzer returns structured evidence
and does not choose an SDK error. Runtime capture needs one new
`BoundaryContinuityRefused(RuntimeWriteRefused)` carrying `basis`,
`captured_head`, `effective_declaration`, and the issue. It should expose the
issue's stable `tick_id`, `ordinal`, loop/vertex name, and declaration coordinate
as scalar diagnostic fields, plus `coordinator_phase="prepare"` and explicit
custody-not-entered effects. This is the planning attempt's mutation proof; an
earlier registry open may still have advanced witness evidence.

Declaration preparation keeps its existing `DeclarationPreparationRefused`.
It must catch the continuity conflict explicitly before the generic preparation
handler and raise a continuity-specific preparation message `from` that
exception, with captured H and its existing C2 prepare/custody-not-entered
fields. Otherwise the generic “cannot establish preparation basis” wrapper
would retain the cause but misstate the phase that failed. The SDK normalizer
already follows `__cause__`; there is no demonstrated need to add a general
`cause` parameter to `_preparation_refused`. Raw evidence readers, inspection,
verification and export do not call the analyzer.

The analyzer:

1. Validates/uses the already licensed declaration anchor. It seeds state from
   the own genesis `documents` and ignores foreign/absent-lineage declaration
   rows exactly as the resolver does.
2. Sorts declaration facts and ticks by `(arrival_ordinal, arrival_seq)`. It
   applies every declaration fact sharing one `arrival_ordinal` as one atomic
   revision before moving to the next record. A wire `batch` contains fact rows
   only, so there is no legitimate tick halfway through a declaration ceremony
   ([arrival_body.py:179](../../../libs/engine/src/engine/arrival_body.py#L179)).
   `FileLedger.append` may commit several drafts in one CAS, but
   `append_marked_many` assigns each draft its own next outer ordinal
   ([arrival_file_backend.py:321](../../../libs/engine/src/engine/arrival_file_backend.py#L321),
   [arrival.py:1517](../../../libs/engine/src/engine/arrival.py#L1517)). A query
   returning an owned tick at an ordinal that also contains an own-lineage
   declaration fact contradicts both legal wire expansions. Refuse it as
   `invalid-projection-shape`, naming the conflicting coordinates; do not invent
   a transient mid-record definition state. This is the narrow contradiction
   relevant to continuity and a defensive adapter validation, not a supported
   boundary event.
3. Tracks uninterrupted presence epochs for **all materialized loop names**, not
   merely loops that currently declare a boundary. Membership at each atomic
   revision is three-valued: present, absent, or unprovable from recorded
   template inputs. Hydration calls `replay_boundary` on a matching passive loop
   too.
4. Classifies only owned ticks. Foreign and originless ticks remain visible but
   establish no local edge, matching `_owns_tick`.
5. For every current loop name, requires every owned matching tick to have a
   continuously **present** membership from that tick's receipt through the
   target revision. A tick before genesis, during absence, or in an earlier
   retired epoch makes the current consumption unproven. So does an unresolved
   intermediate revision after an otherwise known tick: it may conceal an
   absence/recreation, and the later known definition cannot repair that gap. An
   unresolved revision entirely before all relevant ticks does not matter if
   membership is provably present from each tick forward. A current loop with no
   such tick is clean and is allowed, even if facts of that kind predate it.
6. If the current runtime has a vertex boundary, checks each owned tick named
   for the vertex against the definition state at that tick's receipt. A
   same-named loop in force there is an ambiguous role; pre-genesis role is
   likewise unproven. If there is no current vertex-boundary consumer, the row
   does not block runtime execution, but a proposal that adds one is checked and
   refused.
7. Applies the compiler's whole-value parameter rules when deriving literal
   generated names: `$NAME` is environment-indirected and unknown, `$$value`
   is the literal `$value`, and other values are literal
   ([compiler.py:400](../../../libs/engine/src/engine/compiler.py#L400)). It also
   runs the C5 name reservation over every provable generated name, so semantic
   preview and declaration preparation do not omit literal template collisions.

The query must request the full bounded tick prefix, not the convenience time
default. `TickRequest()` starts at `0.0`
([arrival_contract.py:248](../../../libs/engine/src/engine/arrival_contract.py#L248)),
while wire timestamps are finite but need not be nonnegative. Use
`TickRequest(since=float("-inf"))`, keep the snapshot's captured-head bound, and
sort by receipt coordinate inside the analyzer. This establishes continuity
from the whole receipt prefix. Existing hydration/pending timestamp selection
must not be widened as an incidental C6 change; if the runtime keeps its current
nonnegative convenience request, name the two tick selections separately and
test the negative-time history guard explicitly.

### 2. Runtime integration before materialization effects

In `_build_effective_arrival_candidate`:

1. Fetch facts and the complete continuity tick prefix from the same CURRENT
   snapshot. Keep any narrower runtime tick selection explicit rather than
   silently relying on `TickRequest()` in both roles.
2. Resolve and compile the current declaration, including final template specs.
3. Analyze continuity before `materialize_vertex` and before
   `hydrate_snapshot`.
4. Store the already checked facts/ticks in `RuntimeCapture`; ordinary and batch
   preparation already compose `capture_runtime`, and source preparation calls
   `capture_runtime(source_mode=True)` before collector construction
   ([arrival_sources.py:477](../../../libs/engine/src/engine/arrival_sources.py#L477)).

This single chokepoint covers supported ordinary, batch, pending-boundary and
source paths. `plan_batch_from_capture` needs no second historical scan because
the immutable capture was validated at its exact basis. Later source tiers
recapture and already refuse changed declaration documents before collection
([arrival_sources.py:959](../../../libs/engine/src/engine/arrival_sources.py#L959));
the new capture performs continuity validation as well.

The guard must run before fold initializers or external collectors. Template
compilation already performs pinned source reads in runtime construction, so
the bounded slice does not add a second live locator/declaration read.

### 3. Declaration proposal integration before signing

`prepare_declaration_edit` should fetch all declaration facts and the complete
tick prefix from its existing snapshot. After `diff_documents`, simulate the
proposal as one next atomic revision and analyze the resulting current runtime
roles before building `_declaration_row` or invoking any signer. This preserves
C5's append-forward correction rule:

- removing a currently invalid collision is permitted when no recorded tick
  makes the remaining vertex role ambiguous;
- a collision that did produce an ambiguous tick cannot be “proved repaired” by
  merely adding a unique loop;
- retirement is permitted; recreation is refused only when the new current loop
  would consume an owned tick outside its new epoch;
- a never-used name and a tick-free retired name are permitted.

The no-op path should analyze the current state too if it is returned as an
executable declaration basis; otherwise a no-op could report a safe plan that
runtime capture immediately refuses. The result remains a refusal before intent,
cache publication, signing or append. Initialization needs no C6 history check:
there is no earlier local tick; C5 proposed-name validation remains its guard.

### 4. Template-generated names

The runtime final map is direct specs updated by template specs
([runtime_write.py:760](../../../libs/engine/src/engine/runtime_write.py#L760)).
Template source documents retain their loop definition, inline parameter forms,
and hashes for template/parameter files, but not resolved environment values or
old file bytes
([document.py:603](../../../libs/lang/src/lang/document.py#L603)). Compilation
loads parameter files and resolves whole-value `$ENV` indirection at runtime
([compiler.py:429](../../../libs/engine/src/engine/compiler.py#L429)).

Runtime construction already calls
`effective_declaration_from_documents(documents, locator)` before
`compile_sources`; its default `verify_pins=True` calls
`verify_source_pins_from_documents`, including `from.params_sha256`
([runtime_write.py:742](../../../libs/engine/src/engine/runtime_write.py#L742),
[declaration.py:913](../../../libs/engine/src/engine/declaration.py#L913),
[declaration.py:944](../../../libs/engine/src/engine/declaration.py#L944)). Thus a
supported runtime does not compile a mismatched pinned parameter file. No new
pin gate is part of C6.

Consequently the analyzer must not claim it can reconstruct every historical
expanded name:

- Literal inline `with kind=...` rows are reconstructible from each recorded
  source-document revision. Treat their generated names like direct loops.
- An unchanged external parameter-file recipe can be reconstructed only while
  the current file verifies against the same recorded hash; an older replaced
  hash without retained bytes cannot be reconstructed.
- An environment-indirected kind is never historical identity evidence because
  its resolved value was deliberately not absorbed. Its generated membership is
  unprovable for the entire declaration revision, even if the current expansion
  happens to name a known loop.
- Source entries with no loop spec do not add loop names and are irrelevant to
  this check. Command/cadence-only edits do not create an incarnation.
- A direct or implicit loop that is provably present keeps membership present
  even while another template's generated-name set is unknown. A generated
  override can change the spec, but inherit-by-role/name treats that as an
  in-place interpretation edit; the unknown source cannot conceal absence of a
  name another recorded definition guarantees.

The bounded safe fallback is refusal only when the current runtime would consume
an owned tick whose continuous generated-loop epoch cannot be proven. An
unresolved revision at the tick or anywhere after it is such a gap, even if the
current revision is known again; otherwise remove/recreate could hide inside the
unknown interval. Do not refuse a dynamic template merely because it exists,
and do not use today's env or unpinned bytes as yesterday's proof. If compiler
work cannot retain enough per-spec provenance without widening the slice,
reject the unprovable tick case and leave richer template continuity for a
follow-up.

Keep the analyzer pure by passing already verified parameter rows keyed by their
recorded SHA-256. Runtime construction may populate that map from the pin-checked
read. A matching hash commits to the file bytes at that declaration revision, so
the classifier may use those rows; the pin is more than a generic “current
drift” flag. The parsed verified rows and compiled names are then compared in
both directions as described above. Declaration preparation and semantic preview
may pass no verified historical rows and conservatively leave those generated
memberships unknown. A missing/mismatched pin and an environment-indirected
`kind` remain unknown. Current external bytes are never used for an older
different hash.

The implicit `cite` loop is also materialized even when undeclared
([compiler.py:1003](../../../libs/engine/src/engine/compiler.py#L1003)). Treat it
as a continuously present built-in role for the supported runtime epoch; an
explicit `cite` definition changes its interpretation in place rather than
retiring its name. A local `cite` tick before the historized epoch remains
unproven.

## Compatibility table

| Transition with current consumer | Local tick evidence | Proposed result |
| --- | --- | --- |
| Fold/search/preview/edge/lifecycle/run edit | any tick in current presence epoch | allow; current interpretation, same edge |
| `when` trigger/match/condition edit | any tick in current presence epoch | allow; pending facts after the edge use new predicate |
| `every N` to `every M` | prior loop tick | allow; new count starts at zero after last tick |
| `every` to `after` | prior loop tick | allow; current `after` is already exhausted |
| `after` to `every` | prior loop tick | allow; current `every` resumes from last tick |
| Remove boundary but retain loop | prior loop tick | allow; historical reset edge still partitions current replay |
| Remove loop and leave it absent | prior loop tick | allow; no current loop consumes the row |
| Remove then recreate loop | no owned tick before new epoch | allow; facts are reinterpreted, no persisted edge is reused |
| Remove then recreate loop | owned tick before new epoch | refuse; incarnation is not recorded |
| Add never-declared loop | no prior owned same-name tick | allow |
| Add apparently new loop | prior/pre-genesis owned same-name tick | refuse; clean identity is unproven |
| Repair C5 loop/vertex collision | no ambiguous tick | allow |
| Repair collision but retain vertex boundary | ambiguous local vertex-name tick | refuse while vertex boundary would consume it |
| Same-name foreign/originless tick | any transition | ignore for continuity; it is not a local edge |
| Change reset/carry | earlier local tick | not expressible now; future explicit transition required |

The count rows above need these exact observable qualifications:

- With a prior loop tick, hydration resets current `every` bookkeeping at the
  tick and then increments for every later routed fact. It suppresses firing
  during hydration and does not reduce the accumulated count modulo the new
  threshold. If seven facts follow the edge under current `every=5`, the **next
  ingress fires** (count becomes eight); no retroactive tick is minted and it
  does not wait five more facts.
- With no prior loop tick, hydration uses `events_folded % count` for `every`.
  Seven folded facts under `every=5` leave two counted, so the next boundary is
  after three more routed ingresses. The ticked and unticked cases deliberately
  differ because a recorded tick is an exact reset edge.
- With a prior loop tick, current `after=N` is exhausted by `replay_boundary`
  regardless of facts later in the prefix. With no prior tick, `after=N` is
  marked exhausted when replayed facts are already at least `N`; below `N`, the
  next ingresses continue from the replayed count. Thus replacing retired `x`
  with clean `x2 { after=5 }` can immediately be exhausted by five older facts.
  That is current reinterpretation, not an implicit fresh-facts cutoff.

## Acceptance tests for an implementation slice

Use real signed declaration history and a real file projection for the public
preparation/capture tests; pure analyzer tests can use small DTO fixtures.

1. A continuously present `every=2` loop fires, is edited to `every=3`, and
   resumes counting from the recorded tick. Cover both fewer-than-threshold and
   at/above-threshold post-tick fact counts; at/above fires on the next ingress,
   never during hydration. Contrast the unticked modulo case. `every -> after`
   with a tick stays exhausted, `after -> every` resumes, and an unticked
   `after=N` is exhausted when replay already has at least N facts. Also prove a
   clean replacement name with `after=N` interprets older facts rather than
   receiving a fabricated fresh cutoff. These pin inherit-by-name rather than
   accidental old-policy replay.
2. Fold-only, condition, route, parse, presentation and run edits with a prior
   tick are accepted and deterministically use current interpretation.
3. A boundary is removed while its loop stays passive; hydration still applies
   the existing edge. Re-adding the boundary stays the same loop epoch.
4. Whole-loop remove/recreate with an earlier owned tick refuses declaration
   preparation before signing and append. The same history without a tick is
   accepted even with old facts. Removal without recreation remains executable.
5. An already-recorded/imported unsafe recreation refuses ordinary capture,
   batch and source preparation before signing, append, pending tick planning or
   collector construction. Handles close through existing capture cleanup.
6. A C5 collision followed by a local ambiguous tick and then a configuration
   repair still refuses a current vertex-boundary consumer. The tick-free repair
   succeeds. Removing the vertex-boundary consumer leaves evidence reads usable.
7. Passive current loops are included: an out-of-epoch tick refuses even though
   the loop declares no boundary. Foreign and originless same-name ticks do not.
8. Multiple declaration changes in one Arrival ordinal are one state transition;
   source replacement does not create a false intermediate incarnation. An
   injected query that places an owned tick beside an own-lineage declaration
   fact at the same ordinal refuses as invalid projection shape; supported
   FileLedger append proves its records have distinct ordinals.
9. A negative-event-time tick is detected through the full receipt-prefix
   request.
10. Static literal generated names get the same epoch behavior, including `$$`
    literal escaping and C5 vertex-name reservation. A params file whose current
    bytes verify the recorded revision hash is usable evidence. Env-indirected,
    missing-pin, mismatched-pin, or older replaced-hash generated membership is
    unknown and refuses only when a current consumer would reuse an owned tick;
    a source with no loop is unaffected. Runtime capture already refuses a
    mismatched current pin before compilation; the C6 regression additionally
    checks exact target-name equality in both directions across verified rows
    and compiled specs.
11. Raw read, inspection, verification and exact export still expose histories
    that runtime execution refuses.

## Explicit transition deferred

Refusal is not a restart mechanism. A later append-forward transition needs a
reviewed declaration event that says which `(vertex, role, name)` is being
continued or restarted and establishes the receipt cutoff for the new
incarnation. Hydration and pending evaluation would then select edges within
that declared incarnation. The event must also define reset/carry behavior and
how an operator adjudicates old C5 role ambiguity. It must not rewrite existing
facts/ticks or infer intent from a declaration hash.

That future ceremony may avoid changing the tick wire shape by making the
incarnation interval a declaration-history claim, but its vocabulary,
authorization, import behavior and recovery semantics require protocol review.
C6's first slice should only refuse cases that current evidence cannot classify.

## Limits to state plainly

- This is a role/name continuity check, not a full projection-vs-ledger audit or
  authorship verification pass.
- It does not prove semantic equivalence of folds, routes, parse steps or
  predicates. D5 permits those to reinterpret facts under the retained edge.
- Current declaration history cannot prove old environment values or replaced
  external parameter-file contents. The design refuses affected edge reuse
  rather than substituting current ingress.
- Facts without a tick do not prove a consumed boundary. Allowing their current
  reinterpretation may cause a newly declared pending boundary to fire; that is
  the requested current interpretation, not a recovered historical claim.
- Histories predating declaration genesis have no definition timeline. A current
  role must not consume a pre-genesis local tick unless a later explicit
  transition classifies it.
- Generic/legacy `Vertex` construction and evidence-only reads retain their
  current behavior. The guard belongs to supported Arrival authority planning
  and declaration preparation.
