# C7 independent validation

Validation was run in `/Users/kaygee/Code/loops-wt/arrival-finish` after the
inspection source and tests were frozen. Engine production is unchanged by
C7.

## Results

From `libs/sdk`:

```text
uv run pytest -q
559 passed in 19.32s

uv run ruff check src/sdk/declare.py src/sdk/target.py src/sdk/types.py \
  tests/test_arrival_inspect.py tests/test_target.py tests/test_types.py \
  tests/test_arrival_inspect_contract.py
All checks passed!
```

The independent contract file also passes in isolation:

```text
uv run pytest -q tests/test_arrival_inspect_contract.py
5 passed in 0.19s
```

From the worktree root, architecture validation passed:

```text
uv run pytest tests/architecture -q
101 passed in 5.48s
```

The architecture run occurred before the final test-only sentinel edit; no
production or architecture-sensitive import changed afterward. The raw logs
are retained under `/tmp/loops-arrival-c7-2026-09-06/validation/`:

- `sdk-full-final.txt`
- `architecture-full.txt`
- `ruff-sdk-final.txt`
- `hashes-before-final.txt`
- `hashes-after-final.txt`

The final source/test hashes in `hashes-after-final.txt` are unchanged from
`hashes-before-final.txt`, because the final validation rerun followed the
last test edit. The independent test file was edited once after its first
focused run to add the required `XDG_STATE_HOME` isolation fixture and once
to add a `Path.glob` sentinel; the first unisolated run is disclosed below.

## Acceptance evidence

`test_arrival_inspect_contract.py` covers both local/effective aggregate
directions through one opaque registered root. The opener records one exact
root locator, rejects any member locator, and the test patches `Path.glob` so
discover expansion fails immediately. Query and ledger closure are observed
on success and when effective declaration resolution refuses; snapshot closure
is additionally verified by source inspection of `OpenedRead.close`, which
closes snapshot, query, and ledger idempotently.

Role and unknown-backend cases patch the legacy probe to fail if reached.
Storeless discover inspection patches both `probe_target` and
`load_declaration_status` to fail, proving the frozen local branch does not
consult legacy storage. Results retain `store=None`/`basis=None` for that
branch and serialize under `allow_nan=False`; literal null topology fields
remain distinct from ordered combine evidence.

The owner tests cover effective/local topology drift, aliases, changing-file
detachment, current projection refusals and byte preservation. The shared
`_arrival_definition` parser (`sdk/target.py:62-110`) retains one parsed AST,
including valid storeless roots, so inspection does not reparse before its
frozen branch or probe a replacement residence.

## Unisolated test disclosure

Before the test isolation fixture was added, early focused runs created four
temporary test lineage journals in the user's default attestation state and
four corresponding entries in its shared bindings journal:

```text
/Users/kaygee/.local/state/loops/heads/01M1WCGR8JG2900Y6AVXQ8W4K6.jsonl
/Users/kaygee/.local/state/loops/heads/01M1WCH8971C4KKD31WFRHMX09.jsonl
/Users/kaygee/.local/state/loops/heads/01M1WCH89P6JJSMAKWVCFCJAH1.jsonl
/Users/kaygee/.local/state/loops/heads/01M1WCH89ZZFCW359GAHFXQWJN.jsonl
/Users/kaygee/.local/state/loops/heads/bindings.jsonl
```

Root independently verified all four binding rows: one uses the initial
`opaque://tenant//root?projection=contract` locator, and three use the
`opaque://tenant//root-test_inspection_*?projection=contract` locators.
Each listed head file contains a header and one test bootstrap observation.
These test artifacts and the shared bindings journal were left intact; no
existing journal was deleted or rewritten. All subsequent focused and full
runs used pytest-scoped `XDG_STATE_HOME` directories. The new test module now
has an autouse isolation fixture. This disclosure concerns synthetic test
witnesses; no Arrival operation was directed at a real project store.

No C7 blocker was found. The scope remains bounded root inspection: aggregate
member custody, aggregate entity/fact semantics, topology validity and
legacy retirement are outside this result.

## Post-review assertion refinement

After Fable-low acceptance, root added two assertions to the existing opaque
root test: topology-only drift must report `local_status="drifted"` and
unequal semantic fingerprints. Both parametrized directions pass within the
5 focused tests (`0.21s`), and scoped Ruff passes. Production is unchanged;
the full 559/101 results above precede those assertion-only edits. See
[post-review evidence](reviews/consistency-c7-implementation-2026-09-06/post-review-validation.md).
