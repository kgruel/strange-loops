# S3 impl report — admission policy at the engine boundary

Branch: `slice/s3-admission-policy` (reset onto wave head `9cb77675` per step 0)
Worktree: `/Users/kaygee/Code/loops/.claude/worktrees/agent-a44e80294771901a1`

## Commits

1. `9a78e2d6` feat(engine): grant_for_observer + receive_as (observer-grant resolution, LIBS_CHANGES P1)
2. `ac54ff94` feat(engine): strict enforcement at engine receive — typed UndeclaredKind before storage
3. `e3ede343` test(engine): admission contract tests (`libs/engine/tests/test_admission.py`, 21 tests)
4. `c4e42854` docs: this report; `96630217` test: aggregate case bypass-side assertion (raw receive on an aggregate program never consults admission)

Note: `VertexHandle._recompile` reassigns `self._ast`, so `receive_as` grant resolution stays fresh across ontology epochs (verified).

## A — observer-grant resolution

New `libs/engine/src/engine/admission.py`:

- `grant_for_observer(ast, observer) -> Grant | None` — public, exported from `engine`.
- Typed hierarchy: `AdmissionError` base; `UnknownObserver`, `UndeclaredKind`, `AggregateAdmissionUnsupported` (all exported).

Five contract cases (each pinned in tests, both enforced and bypassed):

| Case | Behavior |
|---|---|
| no observers block | `None` — no declared policy, unrestricted |
| unknown observer (block exists) | raises `UnknownObserver` |
| declared observer, no grant | `None` — declared, unconstrained |
| declared observer with potential | `Grant(potential=frozenset(...))` — out-of-potential kind rejects as `Receipt(stored=False)` |
| aggregate (combine/discover) | raises `AggregateAdmissionUnsupported` — members own admission |

Entry points: `VertexProgram.receive_as(fact)` and `VertexHandle.receive_as(fact)` resolve and apply the declared grant automatically (`VertexProgram` now carries a `declaration` slot, filled by `load_vertex_program`; the handle uses its `_ast`). The **explicit bypass** is the raw `receive` entry point (caller-supplied grant), now documented as such on both program and handle — bypass by named entry point, not omission.

## B — strict enforcement

Plumbing: `VertexFile.strict` → `CompiledVertex.strict` (new slot, default False) → `Vertex(strict=)`. Enforcement in `Vertex.receive_receipt`, after the grant/observer-state gates and **before the store append**: strict + `not self.accepts(kind)` → raise `UndeclaredKind`. Bypass is the explicit `admit_undeclared=True` kwarg, threaded through `Vertex.receive`/`receive_receipt`, `VertexProgram.receive`/`receive_as`, `VertexHandle.receive`/`receive_as`.

Decisions inside the ruling's envelope:

- "Declared" = `accepts()` (loop kinds, boundary kinds, routes, kinds a child accepts, plus the implicitly-injected `cite`).
- Child-tick re-entry (`_from_child`) is exempt — engine-internal, not client ingress.
- Observer-state kinds (`focus.*`/`scroll.*`/`selection.*`) get **no** exemption: undeclared is undeclared (pinned by test).
- Replay bypasses receive, so a strict store containing historical undeclared rows (written via bypass) still loads (pinned).
- Non-strict behavior preserved verbatim: undeclared fact stored, raw-readable, folds once the kind is later declared (pinned by `test_non_strict_preservation_verbatim`).
- `lang/ast.py` strict comment updated to the enforced semantics.

## Seam issues found

1. **Executor lifecycle facts (fixed in-slice, engine-side only).** `Executor` emits its own `_sync` / `_sync.{kind}` facts through `vertex.receive` unconditionally — on a strict vertex these undeclared internal kinds would have raised and broken every `sync()`. Fixed at the two engine-internal call sites with explicit `admit_undeclared=True` + comments; source-*produced* facts do NOT bypass (a strict raise during ingest is caught by the existing source-error capture and lands in `SyncResult.errors`). Pinned by `test_sync_lifecycle_facts_bypass_strict`.
2. **CLI composes cleanly — verified empirically** (script driving `cmd_emit`): strict vertex + undeclared kind → CLI pre-validation refuses first (rc=2, vertex-strict hint), engine never raises — no double rejection; `--strict` flag on a non-strict vertex → CLI-only refusal still works (precedence intact); non-strict undeclared → WARN + stored (preservation intact). The CLI's declared-set is narrower-or-equal to the engine's `accepts()`, so `UndeclaredKind` is unreachable from `cmd_emit`; `_resolve_strict` untouched.
3. **Latent, reported not fixed:** `loops` top-level `main()` has no engine-exception → exit-code mapper, so if a future CLI path reaches engine strict/admission errors directly (e.g. migrating emit to `receive_as`), they'd surface as tracebacks. Related follow-up: CLI emit (emit.py:890) still uses raw `program.receive` — migrating it to `receive_as` would start rejecting undeclared observers on observers-block vertices, a behavior change deliberately left out of this slice.

## Oracle results

- `libs/engine/tests/test_admission.py`: 21 passed (five grant cases both ways; strict reject/pass/bypass; preservation; replay; handle paths).
- Full engine suite: **1359 passed** (the 4 `test_topology.py` cache failures seen mid-run also failed on the clean wave head via `git stash`, and passed on re-run — flaky/env, not this slice).
- `apps/loops/tests`: **2521 passed, 1 xfailed** (CLI emit path, cascade/close path, hooks-adjacent flows regression-clean).
- `libs/lang/tests`: 557 passed, 3 skipped. Root `tests/` (architecture DAG): 59 passed.

## Deviations

- None from the contract. The executor `_sync` bypass is an addition forced by the strict floor (documented above, explicit per the bypass bar).
