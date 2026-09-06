# Minimal CLI: Fable 5.1 adversarial review — 2026-09-05

## Invocation

The scoped static packet was reviewed with:

```text
claude -p --safe-mode --model 'claude-fable-5-1[1m]' \
  --no-session-persistence --tools '' --output-format json \
  < /tmp/loops-arrival-review/minimal-cli-prompt-2026-09-05.md \
  > /tmp/loops-arrival-review/minimal-cli-result-2026-09-05.json \
  2> /tmp/loops-arrival-review/minimal-cli-stderr-2026-09-05.txt
```

The raw JSON and prompt are retained under `/tmp/loops-arrival-review/`.
Metadata identifies `claude-fable-5-1` with 6,808 output tokens and 4,362
thinking tokens; no tools or web searches were available to the reviewer.
The review returned `approve-with-fixes` with five defects and three
non-blocking observations.

## Findings and dispositions

1. **Fixed — root parser errors bypassed JSON.** The first implementation
   used the custom parser only for subcommands. Missing or unknown commands
   therefore printed argparse text with empty stdout. The root parser now also
   uses `_ArgumentParser`; subprocess coverage checks unknown commands and
   malformed values, while help remains conventional.

2. **Fixed — the wheel boundary lacked an automated check.** The package now
   declares its local test tools and `test_built_wheel_contains_only_the_cli_boundary`
   builds the actual wheel, checks the package files, console entry point, and
   `Requires-Dist: sdk`. An independent clean-venv smoke also passed: local
   wheels for SDK and its dependencies plus the loops-min wheel were installed,
   and a temporary Arrival fixture returned a successful `summary` through the
   `loops-min` console script.

3. **Fixed — pretty output was lost on parse errors.** The error path now
   examines `sys.argv` when `main()` receives no explicit argument list. A
   subprocess test proves `--pretty` before the command produces indented JSON
   for a malformed invocation.

4. **Fixed — non-finite values could produce invalid JSON.** `_write` now
   constructs the complete document before writing and uses `allow_nan=False`.
   Serialization failures receive the safe internal-error envelope without a
   partially written stdout document.

5. **Fixed — read argument routing had insufficient coverage.** The real
   Arrival subprocess fixture now checks `target`, `sync`, facts with kind and
   observer filters, and ticks with a name filter. Search, timeline, and entity
   resolution each assert the intended Arrival `TargetUnsupported` result.
   `resolve` no longer invents a schema; it wraps the SDK scalar as `fact_id`
   until the SDK exposes a result model. After this review, `inspect` was moved
   to the explicit unavailable set because its SDK implementation still enters
   legacy declaration probing for descriptor targets.

6. **Addressed after review — target error category.** The CLI maps
   `TargetUnsupported` to exit 3 and other typed `TargetError` values, such as
   `TargetNotFound`, to refusal exit 4. Their JSON types retain the distinction.

7. **Verified by targeted runtime check — `sync` is Arrival-native.** The real
   fixture returns `read_path="arrival"` and a current sync result. The CLI
   delegates this SDK operation and does not inspect storage itself.

8. **Scoped hygiene suggestion — tighten the AST allowlist.** The allowlist
   includes `collections` for no current import. This is harmless and does not
   widen runtime dependencies; the source scan now uses `rglob` so future
   subpackages are covered.

## Recheck

```text
uv run --package loops-min pytest apps/loops-min/tests -q
5 passed in 1.72s

uv run --package loops-min ruff check apps/loops-min/src apps/loops-min/tests
All checks passed!

./dev check
101 passed in 4.41s

uv lock --check
Resolved 48 packages in 4ms
```

The CLI remains Stage4A: missing Arrival initialization, writing,
verification, declaration editing, export, replication, and admission calls
are explicit unavailable operations. No legacy writer or initializer is
reachable from those names, and continuation tokens remain process-local.

The owner audit additionally moved `inspect` into that unavailable set after
confirming that `sdk.inspect_declaration` still calls legacy `probe_target` and
`load_declaration_status`; this avoids presenting a legacy declaration probe as
an Arrival read. SDK `TargetNotFound`/other `TargetError` values now map to the
refusal category (4), while `TargetUnsupported` remains category 3.

**VERDICT:** approve-with-fixes; all Fable findings were addressed. A follow-up
supplement separately verifies the public `sdk.errors` normalization of raw
engine corruption, projection, attestation, admission, and committed-outcome
exceptions. The CLI imports that classifier rather than engine classes.

**LIMITS:** Fable reviewed a static packet. The independent wheel smoke and
the temporary-file subprocess fixture were run separately by the owner. The
review did not inspect SDK exception inheritance or implementation internals.
