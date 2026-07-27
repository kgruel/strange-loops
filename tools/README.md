# tools/ — cross-implementation conformance generators

Scripts that produce the ground truth of the [loops-go](https://github.com/kaygee/loops-go)
conformance oracle: every vector and fixture under `loops-go/testdata/` is the
output of *this* repo's `atoms`/`engine`/`store` running for real.

| Generator | Writes into loops-go |
|---|---|
| `gen_vectors.py` | `testdata/vectors/{fold,parse}_vectors.json` |
| `gen_store_fixture.py` | `testdata/stores/proc.{db,expected.json}` (M1 store-read interop) |
| `gen_merge_fixture.py` | `testdata/stores/merge_{ab,ba}.db` + `merge.expected.json` (§6.2 commutativity) |
| `gen_tie_fixture.py` | `testdata/stores/tie.{db,expected.json}` (§4.6 same-`ts` id tie-break) |

```bash
uv run python tools/gen_vectors.py --loops-go ~/Code/loops-go
```

`$LOOPS_GO_REPO` works instead of `--loops-go`. The destination is never guessed:
a generator that silently writes into a default checkout is how the artifacts and
the implementation drift apart without anyone choosing it.

## Why here, and why not a lib

These are loops code — they import the reference implementation directly, and
what they emit is loops output. They previously lived in `loops-go/tools/` and
reached back with `sys.path.insert(0, Path.home() / "Code" / "loops" / ...)`,
bypassing the uv workspace, any released artifact, and any version pin. The drift
that invites was already visible: `gen_store_fixture.py`'s docstring described the
Go reader as `ORDER BY rowid` long after `loops-go/store/sqlite.go` moved to
`ORDER BY ts, id`.

They are **not a library**. `ARCHITECTURE.md`'s surfacing charter rules that
"app-side surfacing occupants (the TUI shell, cross-implementation protocol
artifacts) belong to the layer by role without being libs" — a `libs/protocol`
would contradict the charter it implements and trip
`test_every_lib_declares_a_layer`. This is a top-level script directory in the
same shape as `benchmarks/`: run under the workspace env, imported by nothing.
`_conformance.py` is shared plumbing for the four, resolved off the script
directory the way `benchmarks/_profile.py` is.

"Imported by nothing" is now a ratchet rather than a fact about today:
`test_production_does_not_import_a_non_production_root` (Rule 13,
`tests/test_architecture.py`) fails if anything under `libs/*/src` or
`apps/*/src` imports a non-production root. The roots are derived from the tree,
so a future script directory is covered without being remembered. It was added
because sol MEDIUM (2026-07-27) put `import tools._conformance` into
`libs/engine` and all 46 architecture tests stayed green — the containment claim
had no enforcement behind it.

The artifacts stay in loops-go, where the Go conformance suite reads them. What
loops-go owes the protocol is tracked in `docs/dev/loops-go-protocol-queue.md`.
