# C6 independent design audit — September 6, 2026

Scope: source-only audit of D5/C6 continuity and compatibility. I inspected
Arrival capture/hydration/planning, declaration projection and diffing, source
template expansion, and the legacy replay/evaluation entrypoints. No
production or test files were changed, no live store was opened, and no Fable
review was run here. This note is a design gate for the requested bounded
implementation; it does not introduce a wire incarnation identifier.

## Contract and evidence boundary

The current Arrival writer captures the effective declaration from bounded
`_decl.*` documents, then builds a detached runtime from that AST and the same
snapshot's facts/ticks (`libs/engine/src/engine/runtime_write.py:715-790,
977-1042`). The local `.vertex` file supplies residence and ingress values;
`effective_declaration_from_documents` supplies the declaration semantics and
reattaches only those locator values (`libs/engine/src/engine/declaration.py:919-945,
973-1080`). This is the correct authority split for current Arrival planning.

The gap is that the final effective documents erase declaration history. The
resolver overlays definitions and removes tombstoned subjects into a final
mapping (`libs/engine/src/engine/declaration.py:258-276`), while
`documents_to_vertex` reconstructs only the final loop map
(`libs/lang/src/lang/document.py:940-1035`). `diff_documents` permits a loop
retirement followed by a later definition of the same `(kind, subject)`; only
vertex identity is refused as a routine rename (`libs/lang/src/lang/document.py:1100-1159`).
Thus a runtime candidate receives current loop semantics plus all historical
facts/ticks, without knowing whether a same-named loop is an uninterrupted
boundary or a removed-and-recreated one.

Two representation limits qualify that conclusion. `materialize_vertex` always
installs the implicit `cite` collect loop (`libs/engine/src/engine/compiler.py:1003-1023`),
so tombstoning an explicit `cite` definition does not retire that runtime
identity; it leaves the same implicit collect identity available. A history
classifier must distinguish that case from actual loop retirement. Also, one
declaration append may be an atomic batch of several semantic documents. It
must evaluate effective declaration sets at the batch's committed receipt
boundary, rather than mistake transient partial definitions inside a batch for
independently observable incarnations.

## Findings

### 1. High: same-name removal/recreation and boundary edits reuse old consumption

`hydrate_snapshot` accepts a tick when `tick.origin == self._name`, looks up
`self._loops[tick.name]`, and invokes that current loop's `replay_boundary`
(`libs/engine/src/engine/vertex.py:769-849`). `plan_pending_boundaries` uses the
same ownership predicate and keys the latest consumed edge by `tick.name`
(`vertex.py:1260-1355`). Neither receives the declaration version that created
the tick. A loop retired in one declaration and re-added under the same name
therefore inherits the old tick edge/reset/count state; a boundary-kind,
match, count, or mode edit also applies current semantics to old edges.

A disposable in-memory probe confirmed the current reset interpretation: a
same-named historical tick leaves a rebuilt loop at `[2]` with current
`reset=True`, but `[1, 2]` with current `reset=False`. This is a probe of the
engine behavior, not a filesystem reproduction. The current DSL maps all
boundary forms to `reset=True` (`libs/engine/src/engine/compiler.py:541-593`),
while direct `Loop` construction supports carry, so the distinction still
matters to engine callers and future declaration vocabulary.

The bounded policy fork should be explicit:

- A normal in-place change to a loop's trigger/count/match/mode may inherit the
  existing edge. Current semantics then govern facts after that edge; for
  example, a current `after` boundary seeing an earlier owned tick is
  exhausted, while a current `every` boundary may continue. This is a change
  to future interpretation, not an automatic reset. It needs a conformance
  table and tests for every→after, after→every, count changes, and trigger
  changes.
- A loop removed and later re-added under the same name with an owned
  historical tick must refuse runtime capture/planning and ordinary edit
  execution. There is no role/incarnation evidence that distinguishes
  continuation from a new boundary. If no owned tick exists, a normal add is
  safe and does not imply a restart or cutoff.
- Fold, presentation, parse, and source-command edits with an unchanged
  consumption profile may continue to reinterpret facts under the effective
  declaration. They must not silently claim that old tick payloads were
  hydrated; current code re-folds facts and uses ticks only for reset/count/
  period bookkeeping.

Disabling a boundary or removing an explicit vertex citation also does not by
itself prove runtime retirement: the vertex name persists, and `cite` is
materialized implicitly. Such edits should inherit the existing vertex/loop
edge under the chosen in-place policy; only a proven historical role or
membership discontinuity should trigger refusal.

The minimum implementation seam is a pure classifier over declaration events
through H, the proposed effective declaration, and bounded ticks. It must
retain retirement/redefinition events before final document folding, group
atomic declaration batches at their committed receipt coordinate, and model
the implicit `cite` identity separately from explicit declaration documents.
Refuse only an owned same-name reappearance (and any explicitly unsupported
reset / carry transition); do not add an incarnation field to existing ticks.

### 2. High: template and environment-generated identities lack historical proof

Absorbed template documents retain template/params paths, template bytes hash,
and params-file hash (`libs/lang/src/lang/document.py:603-634`). That can prove
literal template and params-file inputs were unchanged. It does not preserve
the resolved value of an environment-indirected parameter: `_resolve_param_indirection`
reads `$NAME` from today's process environment at compile time
(`libs/engine/src/engine/compiler.py:400-426`). `compile_sources` then uses that
value to instantiate the loop and, where configured, to derive its kind and
boundary kind (`compiler.py:429-477`). The Arrival capture path compiles this
current expansion after resolving historical documents
(`runtime_write.py:760-789`).

Consequently, an owned tick for a generated kind or boundary whose identity
comes from an unrecorded environment value cannot be associated safely with
its historical declaration just because today's source file and pin still
match. A future classifier must either find a recorded literal expansion for
that identity or refuse the affected runtime capture/plan. Re-reading today's
environment, template, or params file cannot establish past identity. This is
an evidence limitation, not a reason to alter the template wire format in C6.

The refusal cannot be limited to revisions that contain an owned tick. An
unresolved generated membership interval between two known revisions can hide
a retirement and re-add before a later owned tick, so a later current-name
match does not repair the continuity proof. The classifier should retain that
interval as unresolved and refuse the affected runtime whenever a local tick or
current boundary depends on it; evidence reads remain available.

The legacy `load_vertex_program(vars=...)` path is a separate bypass: it
substitutes current values in `program.py:224-267` after `load_declaration`,
and its reconstructed `VertexFile` omits fields including `boundary`,
`observers`, `lens`, and `strict`. C6 Arrival capture does not accept `vars`,
so this should be documented as legacy/out-of-scope or explicitly refused for
Arrival rather than treated as historical continuity evidence.

### 3. Medium: repaired C5 collisions can leave ambiguous historical ticks

A tick carries `name` and `origin`, but no boundary role or declaration
coordinate (`libs/engine/src/engine/arrival_contract.py:209-230`). A vertex
boundary tick uses the vertex name (`vertex.py:934-965`); a loop tick uses the
loop name (`vertex.py:917-932`). C5 now refuses a *current* loop/vertex name
collision, but a store may already contain a tick produced before that rule.
After a later collision-free declaration, `hydrate_snapshot` can still see a
local tick with `tick.name == self._name`; it has no persisted role evidence to
say whether it was a vertex-level close or an old loop collision.

The inverse case is also unsafe: an old local-looking tick whose name is no
longer declared, or whose historical declaration cannot be resolved at its
receipt coordinate, is an unknown role. The absence of a tombstone is not
evidence that it is safe to attach that tick to the current loop.

Do not refuse every vertex-named tick: legitimate vertex-level ticks are part
of the supported profile. The bounded classifier should reconstruct the
historical declaration at the tick's receipt coordinate from the complete
`_decl` event stream. If that version had a same-named loop, refuse runtime
execution/planning for the ambiguous history; preserve facts, ticks,
inspection, verification, and export. If the declaration history cannot be
reconstructed at the tick coordinate, refuse the affected runtime path rather
than guess. This leaves current C5's append-forward repair available where no
ambiguous tick exists.

The evidence read must cover the complete receipt range needed by this check.
`TickRequest` defaults `since=0.0` (`libs/engine/src/engine/arrival_contract.py:249-255`),
and the Arrival writer currently calls `TickRequest()` in
`runtime_write.py:789,868,1014`. If negative event-time ticks are legal, that
default silently omits historical evidence before the Unix epoch; continuity
code must request an explicit lower bound (or otherwise prove the legal time
domain) rather than use the convenience default. This is a bounded read
contract issue, not a reason to reinterpret foreign/originless ticks.

### 4. Medium: legacy replay/evaluation bypass Arrival origin ownership

Arrival hydration and pending planning correctly ignore foreign and originless
ticks via `_owns_tick` (`vertex.py:769-778, 805-820, 1288-1300`). The attached
legacy `replay` path instead sets a vertex period from
`store.last_tick_ts(self._name)` or the newest tick whose `name` matches,
without checking `origin` (`vertex.py:1135-1152`; `SqliteStore.last_tick_ts`
queries only `name`, `sqlite_store.py:1235-1246`). Legacy `evaluate_boundaries`
starts at the timestamp of the globally newest stored tick, regardless of
name or origin (`vertex.py:1176-1205`). A foreign/originless imported tick can
therefore advance the legacy cutoff or period context and suppress a local
boundary.

This is not a defect in the supported Arrival capture path, which uses
`hydrate_snapshot` and `plan_pending_boundaries`. It is a compatibility
boundary for any C6 claim covering every runtime entrypoint. Keep legacy
replay/evaluation unchanged in the bounded Arrival implementation unless the
product explicitly brings legacy semantics into scope; otherwise state that
origin ownership applies to Arrival hydration/planning only. Origin itself is
still a claim in the current tick profile: outer tick authorship is deferred,
so a foreign writer that can produce a valid tick with the local origin is not
cryptographically distinguishable by this field alone. C6 should not invent a
new wire role to solve that deferred profile decision.

## Compatibility matrix for the next bounded slice

| History and proposed declaration | Runtime capture/planning | Declaration edit | Evidence reads/export |
| --- | --- | --- | --- |
| Same loop identity; fold/presentation/source command changes; consumption profile unchanged and expansion historically provable | Inherit edge and re-fold facts under current effective AST | Allow with existing full-H CAS | Allow |
| Same loop identity; trigger/count/match/mode changes | Allow with explicit inherit-edge semantics; test one-shot/repeating transitions | Allow; report changed future interpretation | Allow |
| Loop retired, then same name re-added, with an owned tick | Refuse before signer/append | Refuse ordinary edit; require future explicit transition | Allow facts/ticks/inspection/export |
| Same-name historical loop/vertex collision, later current declaration collision-free | Refuse affected runtime path after historical coordinate classifier | Allow only a collision-free forward repair if no ambiguous write is attempted | Allow |
| Generated kind/boundary depends on unrecorded `$ENV` value and owned tick exists | Refuse affected generated runtime path unless literal expansion evidence exists | Refuse a transition that would guess old identity | Allow |
| Explicit `cite` definition is removed but the implicit materialized `cite` identity remains | Keep the implicit collect runtime; do not classify the tombstone as retirement of that identity | Allow only under the explicit `cite`/implicit compatibility rule | Allow |
| Owned tick's name is no longer declared or historical declaration at its receipt coordinate is unavailable | Refuse affected runtime path as unknown role | Refuse an edit that would attach the tick by current-name guess | Allow |
| Foreign/originless ticks | Ignore in Arrival hydration/planning; retain as evidence | No role assignment | Allow |
| No owned tick for a new name or repaired current C5 collision | Normal current declaration validation | Allow append-forward edit | Allow |

A pure classifier should consume the declaration event stream and tick
coordinates after the adapter's structural row and watermark/Head agreement
checks; a projection watermark by itself is bounded evidence, not a substitute
for adapter row validation. Preserve the existing two declaration-fold widths
and avoid a new `RecordIterator` protocol. Run it before source execution,
signer invocation, append, or maintenance. It must not alter read-only evidence
operations. Existing full-head CAS remains necessary for concurrent
declaration edits but cannot replace the historical compatibility classifier.

## Acceptance cases and review gate

The implementation should add focused real Arrival coverage for: retirement
then same-name re-add with and without an owned tick; every→after and
after→every edge inheritance; changed boundary trigger/count; vertex-level tick
versus historical loop/vertex collision; unknown-role local-looking ticks;
explicit-cite removal versus implicit cite materialization; a declaration batch
whose intermediate documents must not be treated as observable history; foreign
and originless ticks; and an environment-indirected template kind whose
environment changes after the historical tick. The last case should refuse
rather than use today's value. If negative event timestamps are accepted, add a
pre-epoch tick regression proving the continuity request does not use
`TickRequest`'s default lower bound.

The requested Fable HIGH review remains a pre-implementation gate. Root should
freeze this design with that review and adjudicate the two product choices:
edge inheritance for in-place trigger/count edits, and whether legacy replay/
evaluation is explicitly excluded from C6's supported Arrival contract.
