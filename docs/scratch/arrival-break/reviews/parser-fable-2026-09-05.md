# Parser correction: Fable 5.1 adversarial review

Scope: the completed WP4-F3 backend-name type guard and regression tests only.
Requested model: `claude-fable-5-1[1m]`. Result metadata confirms
`claude-fable-5-1` (the CLI also reports auxiliary Haiku usage).
Invocation: noninteractive `claude -p`, safe mode, no tools, no session
persistence, supplied diff and requirement. Review was static; test counts
were supplied evidence, not independently executed by the reviewer.

## Reviewer response

**Verdict: accept.** The patch is minimal, correct for the stated requirement, and the tests pin both the rejection and the "open registry" behavior.

**Findings**

- **None blocking.** The `isinstance(backend_value, str)` guard is the right check: `bool` is not a `str` subclass, `None` and numerics fail it, and the empty/whitespace check still runs after it, so ordering of the two errors is sensible. The six parametrized rejection cases match the six regressions reported as failing before the fix, so the tests demonstrably exercise the changed line (`loader.py:819`).

- **Low / unverifiable: type-annotated strings.** If ckdl returns a wrapper object rather than a plain `str` for annotated values such as `backend=(kind)"file"`, this patch now rejects them with "must be a string". That is not a regression in any meaningful sense, since the old code would have stringified the wrapper into garbage, but the behavior is untested and depends on ckdl's value representation, which the diff does not show. Worth one test if annotated properties are ever expected here.

**Optional suggestions**

- Include the offending value's type in the error text so a user who wrote `backend=null` sees why. Purely ergonomic.
- The same `str(node.properties[...])` pattern likely exists for other properties in this loader. The fix is scoped correctly, but a grep for `str(node.properties` would tell you whether the same bug class remains elsewhere. Out of scope for this review.
- A whitespace-only case such as `backend="  "` presumably exists in the pre-existing `TestStoreBackend` tests; if not, add one, since the strip-then-empty path is the other branch of this block.

**Limitations**

I reviewed only the diff text. I could not inspect ckdl's Python type mapping, the rest of `test_loader.py`, or the reported test runs, so the pass/fail counts are taken as given.

## Acceptance judgment

Accepted for the scoped parser correction. No blocking findings. The existing
tests already cover empty and whitespace-only names. Annotated KDL values
were raised as an unverified edge case, not a demonstrated defect; the
independent validation pass will check the actual parser representation.
Error-message enrichment and other property coercions are not added to this
patch merely on suggestion. Descriptor implementation receives its own review.
