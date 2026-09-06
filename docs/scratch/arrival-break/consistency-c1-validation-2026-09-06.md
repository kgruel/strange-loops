# C1 registry injection validation — 2026-09-06

This independent check validates registry threading for `resolve_entity`,
`read_timeline`, and `inspect_declaration`. No production or test files were
changed by this validation, and no live stores or keys were used outside the
tests' isolated temporary fixtures.

## Source assessment

All three public APIs now accept a keyword-only `registry` and pass it into the
descriptor-first opener. `resolve_entity` uses the supplied registry for a
single descriptor (`sdk/read.py:1393-1408`); its legacy aggregate/member branch
continues to refuse descriptor-backed members, consistent with the existing
unsupported member-basis contract. `read_timeline` forwards the registry to
both aggregate capture and the single/root opener (`sdk/read.py:1503-1525`).
`inspect_declaration` forwards it to the descriptor opener (`sdk/declare.py:664-694`).

The aggregate helper already forwards the registry for every supported member
capture. Effective aggregate timeline capture reuses its already-opened root,
so it does not open the root through a default registry a second time. Unknown
backend errors remain typed `UnknownBackend`; descriptor paths are parsed before
legacy probing. Opaque locator strings are passed to the registered adapter
without filesystem fallback.

The README's API paragraph accurately states the keyword-only registry contract,
unknown-backend refusal, opaque locator handling, aggregate timeline member
support, and the continuing aggregate restrictions for entity resolution and
inspection.

## Validation

- From `/Users/kaygee/Code/loops-wt/arrival-finish/libs/sdk`,
  `uv run pytest tests/test_arrival_registry_injection.py tests/test_arrival_read.py tests/test_arrival_inspect.py tests/test_arrival_aggregate.py -q` — **40 passed**.
- From `/Users/kaygee/Code/loops-wt/arrival-finish/libs/sdk`, `uv run pytest tests -q` — **504 passed in 41.44s**. Exact stdout is retained at `/tmp/loops-arrival-c1-2026-09-06/sdk-final.txt`.
- The C1-specific file contains **7** tests: registered opaque single-target
  entity/timeline/inspection, unknown-backend no-fallback for all three,
  storeless aggregate member forwarding, effective aggregate root reuse, and
  storeless unknown-member no-default-registry behavior.
- From the SDK package, `uv run ruff check src/sdk/read.py src/sdk/declare.py tests/test_arrival_registry_injection.py` — **All checks passed**.
- From the repository root, `uv run pytest tests/architecture -q` — **101 passed**.

No actionable C1 defect remains. The unimplemented aggregate entity/inspection
member-basis behavior is explicitly preserved and documented; expanding it
would be a separate scope decision rather than a registry-threading fix.

## Post-review supplement (root / Terra)

Fable-low accepted. Terra added three `backend="file"` cases alongside the
opaque unknown-backend cases. Final focused file: **10 passed in 0.25s**; scoped
Ruff passed. Production code is unchanged. The full SDK **504 passed** result
above is the pre-supplement suite run; no combined 507-test rerun is claimed.
Root confirmed repeated `OpenedRead.close()` closes each underlying handle
once and clarified the README's legacy scope. See the
[primary triage](reviews/consistency-c1-2026-09-06/primary-triage.md).
