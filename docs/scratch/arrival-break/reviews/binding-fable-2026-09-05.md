# Binding identity: Fable 5.1 adversarial review

Date: 2026-09-05
Scope: stage2C adapter-owned binding provider, registry/head-seam integration,
and focused tests.

## Invocation and evidence

The verified static invocation was:

```text
claude -p --safe-mode --model 'claude-fable-5-1[1m]' \
  --no-session-persistence --tools '' --output-format json \
  < /tmp/loops-arrival-review/binding-prompt-2026-09-05.md \
  > /tmp/loops-arrival-review/binding-result-2026-09-05.json \
  2> /tmp/loops-arrival-review/binding-stderr-2026-09-05.txt
```

The packet supplied the helper, registry/seam diffs, focused tests, contract
requirements, and prior validation. Returned metadata identifies
`claude-fable-5-1`; no tools or web searches were used in the substantive
review. Raw artifacts are retained under `/tmp/loops-arrival-review/`.

## Verdict

Initial verdict: **REVISE**. Fable identified one blocker-class test gap, one
real key-collision defect, and one real file-policy edge regression. All three
were addressed before this report was written. The remaining observations are
pre-existing scope or non-blocking suggestions.

## Findings and dispositions

1. **Blocker-class test gap — opaque write/reopen was untested. Fixed.** The
   first test opened an empty fake ledger and therefore never exercised
   `bootstrap(binding=...)`, the opaque key in `bindings.jsonl`, exact-key
   reopen, or replacement refusal. Added
   `test_opaque_binding_bootstrap_reopen_and_replacement_are_exact_keyed`.
   It asserts the journal key, reopens with seam filesystem helpers forbidden,
   then replaces the log and asserts `LineageReplaced`.

2. **Medium — delimiter collision. Fixed.**
   `backend:a:b:c` could represent either backend `a:b` plus locator `c`, or
   backend `a` plus locator `b:c`. `opaque_binding` now length-frames both
   fields while retaining the exact locator, and the test covers the
   adversarial pair.

3. **Low — missing file identity could skip historical binding validation.
   Fixed.** The seam previously returned immediately when an explicit file
   binding supplied `filesystem_identity=None`. `aliased_lineage` now reads
   and validates historical bindings before returning no alias for an absent
   file. Opaque bindings never call this function because the explicit
   `filesystem_aliases` policy gates it.

4. **Low — broad genesis precheck catch. Not changed.** The registry's
   existing backend-neutral `verify(Open())` precheck catches backend
   exceptions before the attested seam. Narrowing it would require inventing a
   neutral absence type or importing a backend exception; this is outside the
   binding slice and the seam still performs the mandatory refusal comparison.

5. **Low — `NotADirectoryError` wording. Scoped.** The file provider maps
   non-`FileNotFoundError` `OSError`s to `BindingProbeUnanswered`, matching the
   existing `_identity_of` refusal posture. No separate absent-path exception
   was introduced.

6. **Scope observation — undeclared suffix inference. Not changed.** The
   descriptor inference change is part of the concurrent descriptor stage, not
   this binding patch. This slice does not widen or restore that behavior.

7. **Suggestion — private test attributes. Partly addressed.** The opaque
   bootstrap test now asserts the persisted journal key and replacement
   behavior. The namespace test retains `_canonical` assertions as a compact
   check of the seam's adapter key; the public behavior is covered by the
   journal test.

8. **Scope observation — direct in-memory non-file descriptor `ValueError`.
   Not changed.** This is an existing descriptor contract decision and is
   outside the registry/head binding implementation.

## Root acceptance follow-up

The owner reproduced an additional contract gap after the Fable pass: a
custom `binding_provider` could return a `BindingIdentity` whose backend or
key belonged to another namespace, and the registry would open it. Fixed by
validating provider output before calling the opener: backend names must match,
file bindings must retain the file alias policy, and non-file bindings must use
the length-framed opaque namespace with no filesystem identity. Tests cover a
foreign backend key, a historical file-shaped key, and a valid adapter-owned
normalized key. Invalid providers call neither the opener nor the witness.

## Validation after triage

```text
uv run --package engine pytest \
  libs/engine/tests/test_arrival_registry.py \
  libs/engine/tests/test_arrival_head_seam.py \
  tests/architecture/test_rule_18_arrival_vocabulary_denylist.py -q
161 passed in 0.72s

uv run --package engine ty check \
  libs/engine/src/engine/arrival_binding.py \
  libs/engine/src/engine/arrival_registry.py \
  libs/engine/src/engine/arrival_head_seam.py
All checks passed!
```

No live stores, commits, or pushes were used.
