# c6-design-followup — Fable review

Effort: high. Finished: 2026-09-06T20:46:19.962222+00:00.
Packet SHA-256: `f03a1ca5123fc1b49282c29f8c11cc5e83171ec229954d2249a403a413c94269`.

Static reviewer output; findings still require primary triage.

**REVISE.** B1, B2, B3, B4 and all six algorithm items from the first review are resolved as specified. One item remains a must-fix: B5's positive proof rests on a premise the baseline contradicts. The fix is small and does not change the architecture.

## Resolved

- **B1.** Consumer-scoped rule is correct on the shown code. `_evaluate_vertex_only_boundaries` is reached only behind `_has_vertex_boundary` at `vertex.py:1204` and requires an attached store at `vertex.py:1171`. No unsupported reader of the period field remains.
- **B2.** Premise correction accepted. `_validate_batch` rejects tick-shaped rows, and `append_marked_many` assigns per-entry ordinals. The defensive contradictory-shape refusal is the right rule.
- **B3.** `BoundaryContinuityRefused` with `coordinator_phase`, `effects`, and scalar `tick_id`/`ordinal`/`fact_id`/`vertex` serializes through the existing C2 walker without new wire schema. Explicit `raise ... from` for preparation is sufficient given `_causal_exception`.
- **B4.** The count table matches `loop.py:111-115`, `loop.py:157-166` and `vertex.py:837-846` exactly, including K equal to M minus one firing on next ingress under both branches.
- **Algorithm items.** Documents as the common target, compiled-name cross-check, `$$` handling, two named tick selections, built-in `cite`, no-op analysis, and preview C5 over provable generated names are all specified.

## MUST-FIX: B5 proves declared expansion, not runtime expansion

The design says verified pin bytes establish "that revision's parameter rows" and reconstructs "effective runtime names" in force at each tick. Those are the same only if every supported tick producer refused to compile a params file whose bytes mismatched the recorded pin. The packet shows the opposite. `_template_source_from_payload` at `document.py:626` drops `content_sha256` and `params_sha256` as provenance, so the effective `VertexFile` carries no pin. `_build_effective_arrival_candidate` then calls `compile_sources` at `runtime_write.py:761`, which reads the file unverified at `compiler.py:458`. The comment at `document.py:590` confirms drift is surfaced only at absorb. Both supported tick producers, ingress count boundaries and source-mode pending planning, run on drifted bytes today. My first review missed this; the "pin commits to bytes" argument was true but insufficient.

**Counterexample.** Genesis declares a template source `from params.txt` pinned H1 with one row `kind=a` and loop `every 2`. Facts and a tick t1 for `a` are appended. The operator edits params.txt to `kind=b` on disk without absorbing. Several emissions run; every runtime in that interval materializes `b` and not `a`. The operator restores the H1 bytes. The collector verifies current bytes against H1, the classifier marks `a` continuously present from genesis, and t1 is accepted as `a`'s edge. In runtime effect `a` was retired and recreated with no declaration row, which is the exact case the design refuses when recorded through declarations. The accept-side error is the class C6 exists to prevent.

**Smallest fix.** Two sentences and one small gate.

1. State the reading explicitly: a declaration revision's generated names are its *declared* expansion, defined by the recorded document plus pin-verified rows. A runtime that compiled drifted bytes was out of contract.
2. Make that reading hold going forward: in `_build_effective_arrival_candidate`, before `compile_sources`, compare the current params file bytes against the current revision's recorded `params_sha256` from the resolved documents. A mismatch refuses with `RuntimeWriteRefused` before hydration, signing, or collection. A `None` pin stays unpinned and unknown, as now. Source-mode tier recapture inherits the gate through the same builder.
3. For ticks that predate the gate, name the residual as an explicit assumption in the design and the user-facing note: rows in force are presumed to be the pinned rows because drift-without-absorb was already outside the pin's guarantee. Root or the user picks between admitting the proof under that stated assumption or leaving file-derived membership unknown for this slice. I recommend admitting it; the refuse-side alternative blocks every ticked file-driven loop forever, and the gate closes the hole for all future ticks.

This is a behavior change for stores currently running on drifted params files. It must be listed as such. Gating the template file's own `content_sha256` is the same hazard but does not affect names, so it is a separate integrity decision and not required for C6.

## Unresolved contract rules where root must override the notes

Root design governs, but Sol and Terra read the notes. Each of these should be corrected in the note or explicitly marked superseded.

- **Every tick versus latest tick.** Root step 4 and line 224 require continuous membership from every relevant tick. Engine notes step 5 say an unresolved revision before the latest tick does not matter. With `reset=True` fixed, a later same-name tick observably supersedes an earlier one, so root's rule is stricter than hydration requires. That is a deliberate conservative choice and acceptable, but the engine note contradicts it and Sol will implement whichever they read first.
- **SDK table row 80.** "A loop is disabled while the same runtime name remains" is listed as refuse. Root lines 100-101 and the engine table say removing a boundary while keeping the loop is allowed and inherits the edge. The SDK row is wrong.
- **B2 breadth.** Root refuses an owned tick sharing an ordinal with a self-lineage declaration fact. Engine notes refuse a tick sharing an ordinal with any fact rows. Root's narrower rule is sufficient for continuity. Pick one wording.
- **Preparation wrapping.** The generic handler at `arrival_declarations.py:949` wraps any non-preparation exception as "cannot establish declaration preparation basis" with `from exc`. If the continuity exception is raised inside that block, the chain works but the top-level message is misleading. Specify an explicit `raise _preparation_refused(<continuity message>, captured_head=...) from issue_exc` outside or ahead of the generic handler.
- **Root matrix lacks a pre-genesis row.** Engine notes step 5 and the SDK notes refuse a pre-genesis owned tick for a currently interpreted name. Root covers it only implicitly through "no provable historical loop membership." Add the row.

## Consciously deferred compatibility

These are stated or implied limits, not defects. They belong in the user-facing note so blast radius is visible.

- **Pre-genesis ticks.** Any store that emitted ticks before adopting declaration genesis and still uses those names refuses all emission until rename or a future transition.
- **Env-indirected templates plus vertex boundaries.** An unknown generator can emit the vertex name, so any store with an env-indirected template loop and any historical vertex tick refuses while a vertex boundary is declared. The runtime C5 check at `runtime_write.py:766` would have refused such an expansion, but that cannot be assumed for historical runs for the same reason as B5.
- **Retired ticked names alongside unknown generators.** Target membership for a retired name is unknown when any unresolved generator exists, so the retired stream refuses rather than being ignored.
- **Recovery-appended history.** Declaration recovery replays a frozen plan. If ticks arrived between prepare and recovery under a pinned CAS failure and retry, a recreation could commit that runtime capture then refuses. The design already says runtime rejects such history independently; that is the right boundary for this slice.
- **Negative-time ticks.** The validator sees them; hydration and pending planning keep `TickRequest()` with `since=0`. A prior-incarnation negative-time tick refuses even though hydration would not replay it. Conservative, as intended.
- **Legacy attached paths** and the params-file parser's decode rule. `_load_params_file` uses `read_text()` with the locale default. The extracted parser must decode the hashed bytes with the same rule, or both should move to an explicit encoding together.

## Optional tests

Not required to start implementation.

- Drift scenario: after the gate, a params file edited on disk without absorb refuses ordinary, batch, and source capture before hydration. This becomes the load-bearing test for B5's assumption.
- Explicit `cite { after 3 }` retired and re-added inherits the old cite tick as exhausted.
- Two owned ticks for one loop with an unknown revision between them refuses under root's every-tick rule, and the same history with the unknown revision before both ticks runs.
- A file swapped between the collector's hash and parse cannot substitute rows; the design specifies single-read parsing, so this is a regression guard.
- Preparation refusal chain: the normalized SDK error carries the continuity issue's `tick_id` and `ordinal` in the cause node, not only in the top-level message.
