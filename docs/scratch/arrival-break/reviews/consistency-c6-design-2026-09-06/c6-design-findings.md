# c6-design — Fable review

Effort: high. Finished: 2026-09-06T20:33:26.980872+00:00.
Packet SHA-256: `628adc28379988d79bac226df15bf108a408b5246b7a079595cef553af068597`.

Static reviewer output; findings still require primary triage.

**REVISE.** The inherit-in-place policy is sound and implementable without a wire change. Four items need resolution before Sol/Terra/Luna start: one contract contradiction between the root and agent notes, one missing classification rule, one missing evidence type, and a set of unstated observable semantics that the acceptance tests would otherwise pin by accident.

## Blockers

**B1. High: root and agent notes disagree on ambiguous vertex-name ticks without a vertex-boundary consumer.**
Root matrix row 78 and SDK notes row 61 refuse runtime unconditionally once an ambiguous `origin == name == vertex` tick exists. Engine notes step 6 refuses only when the target has a vertex boundary, and engine notes lines 38-40 say removing the consumer takes the row "out of runtime state." Root acceptance test 6 says only that evidence reads stay usable, which does not settle it.
Counterexample: history has loop `v` colliding with vertex `v`, a tick `(name=v, origin=v)` at receipt R1, then a repair that retires loop `v` and declares no vertex boundary. Under root, all emission is refused forever. Under engine notes, it runs.
The consumer-scoped rule is correct on the shown code. In `hydrate_snapshot` the only effect of that tick on a collision-free candidate is `_vertex_period_start` at `vertex.py:815-819`, and the only supported reader of that field is gated by `_has_vertex_boundary` at `vertex.py:1320`. The loop-role reading is dead because C5 guarantees no current loop named `v`. Refusing without a consumer is an unnecessary restriction on interpretation.
Fix: root row 78 and SDK row 61 become "refuse when the target declares a vertex boundary; a proposal that adds one is refused." Keep the wording that the row is never relabeled. One caveat you should verify: `_evaluate_vertex_only_boundaries` at `vertex.py:1357` is not in the packet. If it reads `_vertex_period_start` on a supported path without the gate, the rule must cover it.

**B2. Medium: no rule for an owned tick sharing an `arrival_ordinal` with self-lineage declaration facts.**
Root step 2 groups declaration facts by ordinal into one revision. Engine notes step 2 justifies this by claiming a wire batch contains fact rows only and cites `arrival_body.py:179`, which is not in the packet. The packet's own batch planner appends pending tick drafts into the same `logical` list as facts at `runtime_write.py:1321-1330`, so ticks and facts do share records in the supported path. Whether declaration rows can also share one depends on code not shown, and the design already commits to rejecting unsafe history "imported or appended through other mechanisms."
Counterexample: an imported record at ordinal 40 contains `kind-retired x` at seq 0, `tick(name=x, origin=v)` at seq 1, and `kind-defined x` at seq 2. Grouping by ordinal makes `x` continuously present and attaches the tick. Seq-ordering makes the tick fall during absence. The design says both.
Fix: state the rule explicitly. Smallest safe rule: any owned tick whose ordinal also carries a same-lineage declaration row is unclassifiable and refuses, naming both coordinates. This is bounded because no supported writer produces that shape.

**B3. Medium: the runtime refusal has no evidence-carrying type.**
Engine notes say capture raises `RuntimeWriteRefused` from an issue. That base class at `runtime_write.py:90` carries no basis, captured head, or declaration. `OrdinaryWritePreparationRefused` requires a `fact`, which does not exist at capture time. The SDK notes require "existing normalized refusal family" and "plans report the reason." The declaration side has the same gap: `_preparation_refused` at `arrival_declarations.py:105` has effects and heads but no `cause` slot for the structured issue.
Fix: add one `BoundaryContinuityRefused(RuntimeWriteRefused)` with `basis`, `captured_head`, `effective_declaration`, and the issue DTO. Add `cause` to `_preparation_refused`. Both must be raised before signer, collector, or intent creation, which the design already requires.

**B4. Medium: inherit semantics for count boundaries are stated incompletely, and tests will pin whatever falls out.**
Engine compat table says "every N to every M: new count starts at zero after last tick." True, but the observable behavior when facts since the edge already exceed M is not stated. `Loop.receive` at `loop.py:111-114` keeps incrementing during hydration and the return value is ignored, so after an edit from `every 10` to `every 5` with 7 facts since the last tick, the count hydrates to 7 and the boundary fires on the next ingress, not retroactively and not after 5 more.
The unticked recovery path at `vertex.py:837-846` uses `replayed % count` instead, so a fresh loop and a ticked loop recover differently from identical facts. Under inherit that is acceptable but must be written down, because it is the user-visible meaning of "no silent restart."
Related and unstated: the fresh-name route the design recommends instead of restart, at root row 76, hydrates an `after N` loop as already exhausted when at least N older facts route to it, per `vertex.py:840-842`. A user retiring `x` and adding `x2 { after 5 }` gets a boundary that never fires. That is the intended reinterpretation, but the SDK acceptance scenario "first capture states that older facts are being interpreted, not reset" should name this case.
Fix: add the three rows to the conformance table and to engine acceptance test 1.

**B5. Low: the params-file rationale is wrong and the negative acceptance text would enshrine an unnecessary refusal.**
Root line 154-156 says a `from` file's hash pin "establishes current drift checking, not historical row values." A matching SHA-256 is a commitment to the bytes. When the current file verifies against the pin recorded at revision R, its rows are the rows at R. Engine notes lines 274-276 already say this. Root acceptance text at lines 234-237 then requires refusal for "file-derived generated names ... even when source documents are unchanged," which would lock the over-restriction in.
Fix now: narrow the negative scenario to pins that do not verify against current bytes and to env-indirected `kind`. Keep the classifier pure by letting the caller pass `verified_params: Mapping[sha256, rows]` from the read it already performs for pin verification. Prepare and preview may pass an empty map and refuse more than runtime; that is safe. Note env indirection stays unprovable: the resolved value was deliberately not recorded.

## Missing algorithm detail before implementation

- **Unify the classifier's target input.** Engine notes pass compiled `effective_loop_names`; root passes documents. Use documents in all three call sites so prepare, preview, and capture cannot disagree. Runtime then cross-checks that every compiled current spec name is either provably present or coverable by an unknown generator at the target revision, and refuses otherwise.
- **`$$` escape.** The classifier must apply the same whole-value `$NAME` and `$$` rules as `compiler.py:400-426` when deciding whether a literal `kind` is provable.
- **Two named tick selections.** Capture, prepare, and preview call `TickRequest(since=float("-inf"))` for the classifier. Hydration and pending planning keep `TickRequest()` at `runtime_write.py:789,1014`. Name them separately in code so a negative-time tick that the classifier refuses is never silently un-replayed by a later widening.
- **Cite as built-in.** Membership for `cite` is present from genesis onward regardless of explicit definition or tombstone, per `compiler.py:1008`. A pre-genesis `cite` tick is unproven like any other.
- **Prepare no-op path.** Decide whether the noop plan at `arrival_declarations.py:960` runs the classifier on the current state. Recommend yes, so a preview never reports a safe plan that capture refuses one call later.
- **Preview C5 gap.** `_arrival_semantic_preview` at `kind.py:123` validates only `proposed_ast.loops`, not literal generated names. Since the C6 classifier computes those, run name reservation over the provable generated set in the same pass.

## Optional improvements, user decisions, and scoped limitations

**Optional.** Include the last relevant declaration and tick receipt coordinates in every diagnostic so a user can find the retirement without a history dump. Add a positive test that an explicit `cite { after 3 }` retired and re-added inherits the old cite tick as exhausted, since that is the least intuitive consequence of the built-in rule.

**Open user decision.** Inherit versus conservative refusal for in-place trigger/count edits. Recommend inherit. Refusal would block all emission on a store, not one loop, for the most routine edit a user makes, and the inherit semantics are deterministic once B4 is written down. If the user picks refusal, bound it to loops that both have an owned tick and change `boundary.type` or `count`, and leave fold, parse, route, condition, and `when` kind edits inherited.

**Already scoped, agreed.** Legacy `replay`, `evaluate_boundaries`, and `load_vertex_program(vars=...)` stay outside the contract. Origin is a claim, not authorship. Pre-genesis owned ticks for a currently interpreted name refuse with rename as the only forward path; state the blast radius in the user-facing note if such stores exist. Negative event-time hydration remains the existing policy. Credential D0/D2 and the explicit transition ceremony are deferred, and nothing here requires a wire reset or incarnation scheme.

**Not verified from the packet.** `arrival_body.py:179` batch composition, `_evaluate_vertex_only_boundaries`, backend handling of `since=-inf`, and whether `FactRequest(kind="_decl")` is a prefix match. Confirm each before Sol relies on it.
