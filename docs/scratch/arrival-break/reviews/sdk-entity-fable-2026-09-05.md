# SDK entity-resolution Fable review — 2026-09-05

## Scope and review receipt

Reviewed the completed single-store Arrival `resolve_entity` change: the full
`EntityResolutionResult` DTO, `sdk.read.resolve_entity`, the real signed
Arrival fixture and entity cases (receipt order, exact key values, absent
projection, internal exclusion, and capture-then-append), plus minimalCLI's
resolve wire and regression. The static prompt and raw JSON result are saved
at `/tmp/loops-arrival-review/sdk-entity-fable-prompt.txt` and
`/tmp/loops-arrival-review/sdk-entity-fable-result.json`.

Command:

```sh
claude -p --safe-mode --model 'claude-fable-5-1[1m]' \
  --no-session-persistence --tools '' --output-format json \
  < /tmp/loops-arrival-review/sdk-entity-fable-prompt.txt \
  > /tmp/loops-arrival-review/sdk-entity-fable-result.json
```

The result's top-level `model` is null, but `modelUsage` verifies substantive
`claude-fable-5-1` use: canonical model `claude-fable-5-1`, 9,813 cache-create
and 3,305 cache-read input tokens, 3,363 output tokens (including 1,778
thinking tokens), first-party provider. It also records a 19-token Haiku
routing use. The requested response limited findings to five; the returned
visible review had five findings and an overall verdict.

Accepted behavior remains: custody captures H before `FileQuery.open_snapshot`;
a valid projection that advanced after H is clamped to H, and an independent
later lookup may capture and see the newer head. This is intentional, not a
strict-head rejection.

## Findings and dispositions

1. **Concurrent test could hide a leak behind event-time ordering — fixed.**
   The injected row now has later event time (`2.0`) as well as later receipt
   position, so a leaked projection cannot pass through an event-time ordering
   mistake. The resolver also requests the contractually receipt-descending
   `FactRequest(order="newest")` and selects the first exact match, removing
   an unnecessary in-memory re-sort.

2. **Duplicate test definitions — rejected.** The prompt builder accidentally
   included entity tests both as part of its fixture slice and as explicit test
   sections. Source inspection (`rg '^def test_arrival_resolve_'`) shows one
   definition of each test; no source defect or Ruff F811 exists.

3. **Unbounded scan — accepted only as the implementation simplification
   above.** Entity lookup presently needs the latest exact top-level match and
   the portable snapshot contract has no predicate/last-match operation. The
   full bounded kind scan remains intentional for this first backend-neutral
   SDK path; the direct newest ordering removes needless extra work.

4. **Legacy aggregate string coercion — rejected as out of scope.** The new
   exact missing/null/string/number/bool semantics are specified and tested
   for Arrival. Changing old aggregate matching would be a legacy behavior
   migration, not a safe consequence of this wrapper change.

5. **Wrapper evidence assertions — fixed.** Legacy resolution now asserts
   `read_path="legacy"`, `store is None`, `basis is None`, and the structured
   address. minimalCLI asserts Arrival `read_path`, file store descriptor, and
   address in the normal `result` envelope.

## Validation

- From `libs/sdk`: `uv run --package sdk pytest tests -q` — **384 passed in
  17.44s**.
- From `apps/loops-min`: `uv run --package loops-min pytest tests -q` — **6
  passed in 3.25s**.
- From `libs/sdk`: `uv run --package sdk pytest tests/test_arrival_emit.py -k
  'resolve_entity' -q` — **7 passed, 21 deselected in 1.01s** after the review
  fixes. `uv run ruff check src/sdk/read.py tests/test_arrival_emit.py
  tests/test_read.py` passed.
- From `apps/loops-min`: `uv run --package loops-min pytest tests/test_cli.py
  -q` — **6 passed in 2.61s**; `uv run ruff check tests/test_cli.py` passed.
- From repository root: `uv run pytest tests/architecture -q` — **99 passed,
  2 failed in 5.92s**. Both failures are outside this entity scope and in
  concurrently changed files: an unapproved `loops-fact-v1` literal in
  `libs/engine/src/engine/arrival_initialization.py`, and undeclared imports
  from `engine/tests/test_arrival_initialization.py` (`custody`) and
  `sdk/src/sdk/declare.py` (`ulid`). No entity file appears in either failure.
