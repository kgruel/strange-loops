# C6 SDK boundary continuity design notes

## Finding

The supported Arrival writer captures effective declaration documents, facts,
and ticks at one CURRENT basis, then hydrates a detached runtime
([runtime_write.py](../../../libs/engine/src/engine/runtime_write.py#L719-L850)).
Hydration treats every tick with `origin == effective vertex name` as local and
applies a matching tick name to the current loop, even when that loop is
passive ([vertex.py](../../../libs/engine/src/engine/vertex.py#L769-L819)). An
in-place declaration edit therefore reuses its old tick's reset/count/period
effect by policy. A vertex tick has the
same name as the vertex, so a historical C5 collision (`origin == name` and
`tick.name == name`) cannot be classified after a later declaration correction.
It matters to supported runtime continuity only when the corrected target has a
vertex-boundary consumer; without one, the row remains evidence but has no
current loop or vertex-boundary effect.

This is not a reason to restrict ordinary interpretation. Facts are deliberately
re-folded under the bounded effective declaration; hydration does not restore
old tick payloads as fold state. Existing `diff_documents` already rejects a
vertex rename as a normal declaration edit
([document.py](../../../libs/lang/src/lang/document.py#L1100-L1157)). C5
separately rejects a *current* loop/vertex name collision. C6 is about historical
tick consumption, not credentials, observer equivalence, key locations, or
lineage identity (D0/D2 remain separate).

## Proposed public policy

Use the effective declaration and complete bounded tick stream at the
declaration/runtime capture head. Only ticks owned by the effective vertex
(`origin` exactly equals its declared name) participate; foreign or originless
ticks remain evidence and never block a transition. Compare names exactly.

The supported identity is the exact `(vertex name, boundary role, boundary
name)` and its continuous membership interval, rather than a declaration or
boundary fingerprint. An in-place trigger/count, condition, fold, parse, route,
or dispatch edit inherits that identity's recorded edge. The current compiler
fixes `reset=True` for all DSL boundary forms
([compiler.py](../../../libs/engine/src/engine/compiler.py#L541-L593)); if reset
or carry becomes declarative later, changing it is an explicit-transition
question, not an inferred identity change. Source, search, presentation,
lifecycle, and observer edits remain ordinary interpretation changes.

Generated source loops need a stricter evidence rule. Only a template source
with a declared `loop` can generate additional runtime loop identities; bare
paths, inline collection commands, and templates without `loop` do not. Literal
inline parameter rows plus the absorbed loop document can establish generated
names. A `from` parameter file can establish historical rows **only** when the
currently read bytes verify against that revision's recorded SHA-256 pin. The
pin then commits to those bytes and its parsed rows. Environment-indirected
values remain unprovable because their resolved value was not recorded.

The classifier records membership as **present**, **absent**, or **unknown** at
each revision. Direct declaration loops and implicit `cite` are present despite
an unresolved generator; unknown generated membership never overrides that
proof. Verified file-pin rows establish the corresponding generated names in
their recorded order. Unknown means only that a dynamic generator could add or
override an otherwise unproven name; it is never treated as absent.

Use one shared evidence loader for runtime capture, declaration preparation,
and semantic preview. Build it on
`verify_source_pins_from_documents`/`effective_declaration_from_documents`
with its default `verify_pins=True`: the bounded declaration documents select
the expected hashes and the current source and parameter bytes are verified
before compilation. Given a historical revision's pin and source location, the
loader reads one byte snapshot, hashes before trusting it, and, only on a match,
parses that same snapshot with the compiler's actual parameter parser. Its
output is a pure `verified_params` mapping from recorded hash to ordered
parameter rows; it does not resolve environment values. Extract a text-to-rows
parser from the compiler if necessary rather than creating a second grammar. A
missing, unreadable, mismatched, or malformed file contributes no historical
rows. If an owned local tick occurs during such an unresolved generated
revision, continuity is **unprovable** for the affected runtime capture or plan
even when today's source document is unchanged. Do not load current
environment/files as history. A command-only source edit is ordinary when full
history proves its generated name literal and stable; it does not itself reset
a boundary.

| Proposed change at captured H | Historical owned tick for scope/name? | Result | User-visible route |
| --- | --- | --- | --- |
| Same continuously present loop or vertex boundary; fold, parse, route, trigger/count, condition, run, presentation, or boundary-enable/disable edit | either | **Inherit** existing tick edge/count/period. Facts may be reinterpreted under the new declaration; this is not a restart. | Existing `plan_kind_mutation`, `add_kind`, `edit_kind`, `edit_declaration`. |
| Add/change a boundary, or recreate a loop with a name that has no owned tick | no | **Inherit interpretation**, including re-folded older facts. This is not a fresh-facts cutoff. | Existing declaration edit APIs, after normal preview/CAS. |
| Remove a loop entirely | either | **Retire** it from future runtime; its facts/ticks remain queryable evidence. | Existing `remove_kind`; a later same-name add is subject to the reappearance rule below. |
| A runtime name with owned ticks disappears and later reappears | yes | **Refuse** ordinary plan/apply/runtime capture. Do not guess reset, carry, or tick role. | Choose a fresh name for a distinct future identity, or use a future explicit transition. |
| C5-collision configuration with no owned tick | no | **Repair forward** by a normal declaration edit that removes/renames the colliding loop. | Existing declaration edit; C5 already permits preparing a collision-free successor. |
| C5-collision history with an owned ambiguous tick | yes | **Refuse** if the corrected target declares a vertex boundary (including a re-added one). A corrected target without that consumer may run; the row remains evidence and is never relabeled. | A future explicit cutover is required to consume that row as a vertex-boundary edge. |
| Source/template-generated identity cannot be reconstructed from absorbed history and an owned tick exists | yes | **Refuse** the affected runtime capture or declaration plan, even if the current source declaration is textually unchanged. A matching recorded file pin supplies the needed ordered rows; environment indirection does not. | Preserve declaration/tick evidence; a future durable transition or historically recorded expansion is required. |

Disabling or removing a boundary while its loop remains is an in-place
interpretation edit: the loop and its prior edge remain the same identity.
Retiring an old loop and adding a fresh, unique loop name creates a distinct
future tick identity. It is **not** a restart: it neither cuts off old facts nor
promises that a new interpretation will not fold or fire on them. It does not
carry state or translate old facts/ticks. A current C5 collision with no tick
can use that configuration repair. A collision that already produced a tick
cannot be made executable with a current or re-added vertex boundary merely by
renaming a later loop, because that row is also shaped like a vertex period
tick. Without a vertex-boundary consumer, the corrected target may run and
retains the ambiguous row as evidence.

## Explicit transition, deferred implementation

The alternative is a new signed declaration-ceremony transition, for example
`plan_boundary_transition`/`apply_boundary_transition`, rather than an option
silently attached to `edit_kind`. It would atomically append the successor
declaration documents and a durable transition fact at one exact H. Its body
must name the scope (loop or vertex), old/new names, action (`restart` or
retire), predecessor evidence, and its effective receipt coordinate. Runtime
capture would reconstruct declaration transitions
from the bounded declaration stream and ignore pre-cutover tick consumption for
the transitioned scope. The result exposes captured H, transition fact ID,
Commit/outcome, and post-commit projection status just as declaration edits do.

That does not change the tick wire format, but it is new declaration vocabulary
and replay behavior. It needs a separate compatibility decision for historical
reads and for vertex-boundary restarts; it must never relabel old ticks. Until
then, do not expose a `reset`, `carry`, same-name recreation, or alias parameter
on the existing SDK edit APIs.

## Entry-point worklist

1. Extract a pure continuity classifier over `(full bounded declaration
   history through H, proposed-after, bounded owned ticks,
   verified_params)`. It must reconstruct exact role/name membership
   intervals across retired/recreated/imported history, not compare only
   effective-before/effective-after documents. Use it in
   `prepare_declaration_edit` and `_arrival_semantic_preview`; plans report the
   reason before draft/signature use. Run it for a no-op target as well: a
   no-op must not claim safe applicability when runtime capture would refuse.
   Initialization has no pre-genesis history, so C5's existing new-declaration
   validation is sufficient there.
2. Run the same classifier in `capture_runtime`, ordinary/batch preparation,
   and source invocation preparation. A local cache cannot bypass a historized
   unsafe transition. Its tick input must explicitly request
   `TickRequest(since=-inf, until=inf)`: the contract default is `since=0`,
   which is not a complete historical range. Preserve C5's current-name
   validator as a separate check.
3. Keep `preview_emission`, `emit_fact`, `emit_batch`, and `run_sources` on the
   existing normalized pre-append refusal path. Credential providers may load
   existing signer callables before capture, but those callbacks are not called;
   no signing,
   collector, append, or maintenance action begins after a continuity refusal.
4. Leave `read_facts`, summary, state, timeline, inspection, verify, and export
   usable for unsafe histories. They return their normal bounded basis/evidence;
   none claims runtime execution is safe.

`capture_runtime` already opens `ProjectionRequirement.CURRENT`; so do ordinary,
batch, preview, and source paths that delegate to it. SDK
`_arrival_semantic_preview` also uses `_open_arrival_read(... CURRENT)` and
must pass that snapshot's complete `_decl` facts plus full-range ticks to the
pure classifier. `prepare_declaration_edit` likewise has a CURRENT snapshot
and all declaration facts but must add the explicit full-range tick request.
Both it and semantic preview obtain `verified_params` from the common loader.
The classifier's provable target runtime-name set, including literal generated
names, must also feed C5's namespace validator; checking only
`proposed_ast.loops` leaves a generated-name collision preview gap. No C6
decision needs `ALLOW_BEHIND`, a legacy reader, or a second snapshot.

## Acceptance scenarios

- A loop with an owned tick accepts fold-only and count/when/match edits, then
  emit/preview resumes with the preserved boundary edge. It does not refire a
  previously consumed observation under the new rule.
- Removing a ticked loop succeeds; adding the same name later refuses. A
  fresh-name successor has a distinct future tick identity, without claiming a
  fact cutoff, reset, or state carry.
- A new boundary on a tick-free loop is accepted and its first capture states
  that older facts are being interpreted, not reset.
- A legacy C5 collision without ticks is corrected by an append-forward edit
  and can run. With an owned ambiguous tick, a target that declares a vertex
  boundary refuses; without that consumer, runtime/source/emit may run while
  fact/tick reads, inspection, verify, and export retain the row as evidence.
- Proposed and local declarations disagree: the effective captured documents
  and owned ticks decide the refusal; no cache edit or concurrent declaration
  advance can widen the plan. A full-head CAS still protects execution.
- A command-only source edit with a fixed literal kind keeps an owned boundary
  edge only when full declaration history proves the generated identity. A
  pinned parameter file with bytes matching its recorded hash supplies those
  historical rows; a mismatched/missing file and environment-indirected kind
  refuse with owned ticks even if source text is unchanged.

The unresolved product decision is whether the explicit transition ceremony is
worth supporting before a future tick boundary-ID wire revision. The conservative
matrix above is implementable without that decision and does not narrow the
user's ability to reinterpret facts or inspect historical evidence.
