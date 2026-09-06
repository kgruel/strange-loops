# C6 continuity validation — 2026-09-06

This validation covers the C6 boundary continuity classifier and its runtime/declaration call sites. The post-correction source and test hashes were identical before and after the final validation runs.

## Final validation

All commands used the shared worktree `/Users/kaygee/Code/loops-wt/arrival-finish`.

From `libs/engine`:

```text
uv run --package engine pytest -q
2597 passed, 1 skipped in 63.03s (0:01:03)
```

From `libs/sdk`:

```text
uv run --package sdk pytest -q
545 passed in 28.27s
```

From the worktree root:

```text
uv run pytest tests/architecture -q
101 passed in 5.58s
```

The focused continuity suite after the diagnostic correction was `22 passed in 0.70s` (the full engine count includes the same added regression). Its raw output is `continuity-focused.txt` in the post-correction directory. Scoped checks passed:

```text
uv run --package engine ruff check src/engine/arrival_boundary_continuity.py src/engine/arrival_declarations.py src/engine/runtime_write.py tests/test_arrival_boundary_continuity.py tests/test_arrival_declaration_custody.py tests/test_runtime_capture.py
All checks passed!

uv run --package sdk ruff check src/sdk/kind.py tests/test_arrival_boundary_continuity.py
All checks passed!

uv run ruff check tests/architecture/test_rule_18_arrival_vocabulary_denylist.py
All checks passed!
```

The requested broader engine Ruff command additionally included `src/engine/compiler.py` and reported 57 findings. Running the same check against `git show HEAD:libs/engine/src/engine/compiler.py` reported the identical 57 findings, including the pre-existing deferred-import `E402`/`F821` set. The C6-scoped files excluding this compiler baseline pass Ruff.

Pre-correction outputs remain under `/tmp/loops-arrival-c6-2026-09-06/final-validation/`. Final post-correction outputs and manifests are under `/tmp/loops-arrival-c6-2026-09-06/final-validation/post-correction/`: `engine-full.txt`, `sdk-full.txt`, `architecture-full.txt`, `ruff-engine-scoped.txt`, `ruff-sdk.txt`, `ruff-architecture.txt`, `ruff-compiler-baseline.txt`, and `hashes-before.txt`/`hashes-after.txt`. The post-correction manifests compare equal and include the new continuity module/test, changed engine compiler/declaration/runtime files and tests, SDK kind/test, and the Rule 18 target list.

The final post-correction hashes are:

```text
f40ec43cb43cc17b473bf47df72d8fc46ec2407f70a695576b889ee06c8d3cef  libs/engine/src/engine/arrival_boundary_continuity.py
ec142ac85023601964aabf3d031b557b5a4ecb72a731a5b77b384eaba4862ef1  libs/engine/src/engine/arrival_declarations.py
b282fdf164631fbbce16372e28c25e85f99b6121321fde3734af8893ff2bf43d  libs/engine/src/engine/compiler.py
8e95338b936b884112553f3f17603310444bedc540f5779cb8653a67df9437a3  libs/engine/src/engine/runtime_write.py
209d6f25def94265e486b9ae36a5aec5a19355477882fc3256f23d713d1240c4  libs/engine/tests/test_arrival_boundary_continuity.py
36214f2f2174065b7212a52cb6de3b229d603b5b37b4c95ac688849cfb2e0fc4  libs/engine/tests/test_arrival_declaration_custody.py
81e7c0dffc9c8e7e2a84b0b5a21e90d1dac23f6bca50b41fdd5cc7b4e0b81284  libs/engine/tests/test_runtime_capture.py
df66c2f6c5f986d72ece95d37d6b491f26f0b422ad09c32fa9177607397ea68d  libs/sdk/src/sdk/kind.py
e5fd3a1fc25f43392255c40a21ff764a3bf1e6633090701ccf7780839110da9c  libs/sdk/tests/test_arrival_boundary_continuity.py
35478ee2085e4b2cbbce6f430098744cc1c61e63dd3ea0910a07fc63e5889204  tests/architecture/test_rule_18_arrival_vocabulary_denylist.py
```

## Focused evidence

The continuity tests cover receipt-ordered, same-ordinal declaration grouping; own-lineage filtering; foreign and originless tick inertness; implicit `cite`; vertex-versus-loop role selection; malformed same-ordinal projection shape; pregenesis evidence; remove/recreate and vertex identity discontinuities; negative event time; generated names; literal-dollar escaping; dynamic unknown generators; pinned parameter-file parsing; and missing vertex identity refusal.

The generated-only interval case proves that a loop tick before an unknown generated revision refuses with `unproven-generated-incarnation`, while ticks after a later known restoration pass. Direct membership remains proven through an unrelated unknown generator. The foreign-source test confirms the historical parameter collector does not open a foreign lineage’s path.

The corrected `test_later_absence_with_mixed_subject_declarations_identifies_loop_fact` covers a loop retirement and observer definition sharing one Arrival ordinal while an owned loop tick was received earlier. The classifier returns `prior-incarnation` and now identifies the loop retirement fact; the full engine run and focused suite both pass.

Cross-file inspection confirms the intended integration: runtime candidate construction obtains all receipt-bounded ticks (`since=-inf`), collects only own-lineage pinned parameter evidence, and invokes the analyzer before materialization/hydration. Declaration preparation invokes it against proposed documents before signing. The collector hashes and parses one exact parameter-byte snapshot; the ordinary compiler delegates to the same byte parser. Rule 18 scans the new continuity module.

The continuity module assumes facts, ticks, and the declaration anchor came from the existing structurally verified snapshot/custody boundary; it does not independently verify signatures, Head membership, or adapter row agreement. A matching parameter hash proves only the recorded file bytes. Unpinned, missing, mismatched, or environment-indirected historical generators remain unknown and are refused when a consumed edge depends on them. No live store or external source was used.

No C6 acceptance blocker remains. The only non-green lint result is the pre-existing broad `compiler.py` Ruff debt, reproduced with the identical 57 findings at `HEAD`; all C6-scoped files pass Ruff. No live store or external source was used.

## Post-review inline-parameter coverage

Fable-low accepted the frozen production with no blockers and requested optional
real-store coverage of canonical inline template rows. Terra added that positive
SDK case after review; production remained unchanged. Focused C6 SDK: **6 passed**;
full SDK: **546 passed in 23.98s**; scoped Ruff and diff-check passed. The engine
and architecture results above still apply to their unchanged files.

See [post-review evidence](reviews/consistency-c6-implementation-2026-09-06/post-review-inline-evidence/validation.md)
and [primary triage](reviews/consistency-c6-implementation-2026-09-06/primary-triage.md).
The final SDK test hash is
`d7eca43eb2a52045e2684bb0d64a65d28335691fb3ff6088a48911ddf13eaee3`.
The original review packet and validation manifests remain frozen; final
comparison records the added test and completion-only documentation updates.
