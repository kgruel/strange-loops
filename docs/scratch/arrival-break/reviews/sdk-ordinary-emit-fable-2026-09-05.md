# SDK ordinary emit — Fable 5.1 adversarial review

Date: 2026-09-05  
Final verdict: **APPROVE**

## Scope and artifacts

The static packets covered the SDK ordinary Arrival preview/emit source,
typed results and errors, root exports, the full new Arrival emit and error
tests, the stage report, and validation evidence. Batch, CLI, initialization,
and new protocol design were excluded.

Raw artifacts:

- `/tmp/loops-arrival-review/sdk-emit-prompt.txt`
- `/tmp/loops-arrival-review/sdk-emit-result.json`
- `/tmp/loops-arrival-review/sdk-emit-stderr.txt`
- `/tmp/loops-arrival-review/sdk-emit-supplement-prompt.txt`
- `/tmp/loops-arrival-review/sdk-emit-supplement-result.json`
- `/tmp/loops-arrival-review/sdk-emit-supplement-stderr.txt`

## Initial review

Verdict: `REQUEST_CHANGES` with six bounded findings.

1. Preview and dry-run dropped `id_override`. Fixed by carrying it into
   `prepare_ordinary_write`; equal-retry and divergent-content tests were
   added.
2. SDK errors could be wrapped as `EmissionFailed`. Fixed with explicit
   `except SdkError: raise` boundaries.
3. Default preview credential purity was unverified. Source inspection showed
   load-only key lookup; a real test now proves no key directory is created.
4. Boundary receipt fields were untested. A real boundary fixture now verifies
   tick identity and a two-record commit.
5. SDK CAS behavior was untested. A race regression verifies one execute,
   retained plan identity, and no append beyond the injected interloper.
6. Strict-kind diagnostics lost the established message. The SDK now derives
   that message from the same effective snapshot and tests it exactly.

Model metadata reported by the CLI:

- `claude-fable-5-1`: input `2`, cache read `3,305`, cache creation `35,598`,
  output `9,500`, thinking `7,025`, context `1,000,000`, cost `$1.18780625`.
- preprocessing `claude-haiku-4-5`: input `25,296`, output `14`, cost
  `$0.025366`.
- total cost `$1.21317225`; duration `125,929 ms`; one turn; `is_error=false`.

## Capped supplement

Verdict: `APPROVE`, with three low-severity observations.

1. A simultaneous unknown observer and undeclared kind could mask the actual
   observer refusal with the strict-kind compatibility text. Fixed by applying
   the text only to `UndeclaredKind`; a mixed-refusal regression was added.
2. The reviewer suggested guarding a null effective declaration on the typed
   preparation refusal. Declined: the engine constructor requires
   `effective_declaration: VertexFile`, and every raise site supplies the
   reconstructed declaration. The successful plan's optional provenance is a
   separate low-level shape.
3. The locator-policy test's loop rename pattern did not match the multiline
   fixture. Fixed to rename the actual node and retain the same-snapshot policy
   assertions.

Supplement model metadata reported by the CLI:

- `claude-fable-5-1`: input `2`, cache read `3,305`, cache creation `31,919`,
  output `3,800`, thinking `2,370`, context `1,000,000`, cost `$0.82922625`.
- preprocessing `claude-haiku-4-5`: input `22,969`, output `17`, cost
  `$0.023054`.
- total cost `$0.85228025`; duration `54,705 ms`; one turn; `is_error=false`.

Post-disposition focused validation: `39 passed`; Ruff and ty passed.
