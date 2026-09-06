# C7 aggregate resolver continuation: validation

All commands used these process environment overrides, recorded in
`/tmp/loops-arrival-c7-followup-2026-09-06/validation/environment.txt`:

```text
XDG_STATE_HOME=/tmp/loops-arrival-c7-followup-2026-09-06/validation/state
XDG_CONFIG_HOME=/tmp/loops-arrival-c7-followup-2026-09-06/validation/config
LOOPS_HOME=/tmp/loops-arrival-c7-followup-2026-09-06/validation/loops
```

The requested focused follow-up set passed:

```text
uv run --package sdk pytest \
  libs/sdk/tests/test_arrival_aggregate_resolution.py \
  libs/sdk/tests/test_arrival_aggregate.py \
  libs/sdk/tests/test_arrival_registry_injection.py \
  libs/sdk/tests/test_arrival_read.py libs/sdk/tests/test_target.py -q
65 passed in 1.32s
```

The full SDK and architecture suites also passed:

```text
# cwd: libs/sdk
uv run pytest -q
562 passed in 20.30s

# cwd: worktree root
uv run pytest tests/architecture -q
101 passed in 6.02s
```

Scoped Ruff and `git diff --check` passed. The raw outputs and manifests are
under `/tmp/loops-arrival-c7-followup-2026-09-06/validation/`:

- `focused.txt`, `focused-after-fixture.txt`
- `sdk-full.txt`, `architecture.txt`
- `ruff.txt`, `ruff-after-fixture.txt`, `diff-check.txt`
- `hashes-before.txt`, `hashes-after.txt`

The final source/test hashes are:

```text
cf5d37367cd20b20560f051fd307ac521e3c3651c970b75069473096936b37de  libs/sdk/src/sdk/read.py
c501632a54563e3645b2bbd0861226bd7cb181433a5f26f7517f73dd1e01f8f0  libs/sdk/tests/test_arrival_aggregate_resolution.py
```

The full SDK run preceded the final one-line fixture correction that made the
replacement file syntactically a valid aggregate locator. The three focused
follow-up cases were rerun afterward and passed (`3 passed in 0.26s`); the
production source hash was unchanged. The correction improves the regression
because the old resolver now fails by opening the replacement residence, while
the new bridge retains the original parsed descriptor.

The independent baseline probe at
`/tmp/loops-arrival-c7-followup-2026-09-06/baseline-probe-valid-replacement.txt`
records all three pre-fix failures as `GenesisRefused` on the replacement
location; the current implementation passes all three. This is source/test
evidence only and uses disposable fixture stores.

No C7 follow-up blocker was found. The bridge remains limited to preserving
the root descriptor parse; aggregate member custody and recursive topology
validation remain outside this continuation.
