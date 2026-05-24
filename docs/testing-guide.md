# Testing Guide

How tests are organized and run across the strange-loops monorepo — a `uv`
workspace of five libs (`atoms`, `engine`, `lang`, `sign`, `store`) and three
apps (`loops`, `hlab`, `tasks`). Rendering lives in the external `painted`
package (PyPI), so there is no `libs/painted/` to test here.

Every command below is verified against the actual `pyproject.toml`,
`./dev` scripts, and `conftest.py` files in the repo.

---

## 1. How to run tests

### Install the workspace first

```bash
uv sync                                # install all workspace packages + dev deps
```

### Test one package

Pytest config is **per-package** (`testpaths = ["tests"]`). Run against a
package with `--package <name>` and point pytest at that package's `tests/`
directory:

```bash
# Libs
uv run --package atoms  pytest libs/atoms/tests
uv run --package engine pytest libs/engine/tests
uv run --package lang   pytest libs/lang/tests
uv run --package sign   pytest libs/sign/tests
uv run --package store  pytest libs/store/tests

# Apps  (note: the tasks package is named "strange-loops")
uv run --package loops          pytest apps/loops/tests
uv run --package strange-loops  pytest apps/tasks/tests
```

`apps/hlab` is an archived experiment and has no tests.

### Run a single file or the golden subset

```bash
uv run --package engine pytest libs/engine/tests/test_vertex.py
uv run --package loops  pytest apps/loops/tests/golden      # snapshot tests only
```

### Root architecture tests

The repo-root `tests/` directory holds cross-cutting boundary tests. It has no
pytest config of its own, so run it from the repo root with plain `uv run`:

```bash
uv run pytest tests/test_architecture.py -v
```

> **Known state:** two assertions in `test_architecture.py` currently fail
> because their stale-path exception lists still reference
> `libs/painted/src/painted/...`, which no longer exists (painted is now an
> external PyPI dependency). The test logic runs fine; 5 of 7 pass. Fix is to
> prune the `libs/painted/...` entries from the `EXCEPTIONS` sets in that file.

### The CI gate: `./dev check`

A `./dev` harness exists **only in `apps/tasks/`** (there is no root `./dev`
and no `apps/loops/dev`). It discovers subcommands from `apps/tasks/scripts/*.sh`:

```bash
cd apps/tasks
./dev check        # fmt + lint + test (the CI gate) — runs scripts/{fmt,lint,test}.sh
./dev test         # just the test step (forwards extra args to pytest)
./dev check -v     # verbose: stream each step's output
```

Under the hood `./dev test` runs `uv run --package strange-loops pytest`.
Where a package has no `./dev`, run its package-scoped `pytest` command
directly (above) before committing.

---

## 2. Test framework & configuration

The framework is **pytest** throughout. Configuration is declared per-package
in each `pyproject.toml` — there is no shared root pytest config.

| Setting | Where | Value |
|---------|-------|-------|
| `testpaths` | every package `[tool.pytest.ini_options]` | `["tests"]` |
| `asyncio_mode` | `atoms`, `engine` only | `"auto"` |
| `asyncio_default_fixture_loop_scope` | `engine` only | `"function"` |
| branch coverage | every **lib** + `apps/tasks` `[tool.coverage.run]` | `branch = true`, `source = ["src/<pkg>"]` |

`asyncio_mode = "auto"` (pytest-asyncio) means `async def` tests run without an
explicit `@pytest.mark.asyncio` marker — relevant to `atoms` (async `Source`
collection) and `engine` (async `Stream`/`Tailer`). Packages that have no async
tests (`lang`, `sign`, `store`, the apps) don't set it.

### Dev dependencies

Declared per-package under `[dependency-groups] dev`:

- **Libs** (`atoms`, `engine`, `lang`, `sign`, `store`) and **`apps/tasks`**:
  `pytest`, `pytest-cov`, `pytest-asyncio`, plus tooling (`ruff`, `ty`, `rich`).
- **`apps/loops`**: a lighter `pytest` + `pytest-cov` only.

### Coverage

Coverage is branch-mode (`branch = true`) and scoped to each package's `src/`.
`[tool.coverage.report]` excludes the usual non-executable lines
(`pragma: no cover`, `if TYPE_CHECKING:`, `@overload`, `...` protocol stubs).
Note `apps/loops/pyproject.toml` declares **no** `[tool.coverage]` block — run
coverage there by passing `--cov` flags explicitly if needed.

```bash
uv run --package engine pytest libs/engine/tests --cov --cov-report=term-missing
```

---

## 3. Test structure

Each package keeps a `tests/` directory that mirrors its `src/` layout, with
one test file per module (`test_<module>.py`). Fixtures live in a package-level
`conftest.py`; reusable test builders live alongside (e.g.
`libs/engine/tests/vertex_test_sdk.py`, `apps/loops/tests/builders.py`).

### Root `tests/test_architecture.py` — import-boundary enforcement

The most distinctive test in the repo. It is **AST-based**: it parses each
source file's import statements (no runtime imports), and is **TYPE_CHECKING
aware** — imports under `if TYPE_CHECKING:` are excluded from runtime rules.
The rules it enforces:

1. **Apps don't import `StoreReader`** — the vertex is the sole read interface
   (a small `EXCEPTIONS` set covers the store-inspector meta-tool).
2. **Apps don't import `sqlite3`** directly.
3. **Libs never import from apps** — dependency flows libs → apps only.
4. **Lib dependency DAG** — the only allowed cross-lib runtime imports are
   `engine → lang` and `engine → atoms` (and the latter is function-local /
   lazy); everything else is forbidden.
5. **Lib dataclasses are frozen** (`@dataclass(frozen=True)`), with a documented
   exceptions list for legitimate accumulators.
6. **`atoms` is stdlib-only** at runtime — zero external dependencies.
7. **`sqlite3` is confined to `engine` and `store`.**

This is how the "engine depends on atoms via `TYPE_CHECKING` only, no cycles"
invariant from `CLAUDE.md` is mechanically guarded.

---

## 4. Golden snapshot testing

Both `apps/loops` and `apps/tasks` use golden-file snapshot tests for rendered
output — they commit expected text and diff against it. There are **two
distinct invocation styles**; don't conflate them.

### Keying

A `Golden` dataclass writes/compares files at:

```
goldens/{test_module}/{test_name}/{name}.txt   # apps/loops/tests/golden/
snapshots/{test_module}/{test_name}/{name}.txt # apps/tasks/tests/
```

The key is **module + test name** (plus an artifact `name`, usually `"output"`).
Zoom level is *not* a separate key axis — it rides in `test_name` via
parametrization: `@pytest.mark.parametrize("zoom", list(Zoom))` produces test
names like `test_run_facts_demo[MINIMAL]`, `…[SUMMARY]`, `…[DETAILED]`,
`…[FULL]`, so each zoom gets its own golden directory.

### Style A — render a lens directly (`apps/loops/tests/golden/`)

These tests call the pure lens function and render the resulting `Block` to
text. They do **not** go through the CLI entry point:

```python
block = run_facts_view(SAMPLE_FACTS, zoom, width=80)
golden.assert_match(block_to_text(block), "output")
```

`block_to_text` (in `apps/loops/tests/golden/helpers.py`) renders a `Block`
via painted's `print_block` into a `StringIO` buffer.

### Style B — drive the CLI in-process (`apps/tasks/tests/test_snapshots.py`)

These exercise the whole command path by calling
`strange_loops.cli.main(argv)` directly (no subprocess), with fixed
timestamps for deterministic output, then snapshot what was rendered.

### In-process capture in `apps/loops` (Reporter injection)

`apps/loops` end-to-end CLI tests capture output by injecting a
`BufferReporter` (a `Reporter` Protocol implementation that buffers blocks/text
instead of painting to a terminal). The injection point is the **Operation IR
`dispatch`**, not `main`:

```python
reporter = BufferReporter()
rc = dispatch(op, reporter=reporter)        # test_cli_dispatch.py
```

> **Accuracy note:** `loops.cli.app.main` has the signature
> `main(argv: list[str] | None = None) -> int` — it does **not** accept a
> `reporter=` argument. Reporter injection happens one layer down at `dispatch`.

### Regenerating goldens

Both packages register a `--update-goldens` pytest option (via `pytest_addoption`
in their `conftest.py`). On a first run with a missing golden the file is
bootstrapped and the test passes; thereafter mismatches fail with a unified
diff. To accept intended output changes:

```bash
uv run --package loops          pytest apps/loops/tests --update-goldens
uv run --package strange-loops  pytest apps/tasks/tests  --update-goldens
```

Review the regenerated `.txt` files in your diff before committing.

---

## 5. Notable fixtures

Fixture names verified against the actual `conftest.py` files.

### `apps/loops/tests/conftest.py`

| Fixture | Provides |
|---------|----------|
| `loops_home` | Isolated `LOOPS_HOME` tmp dir; sets the env var, clears `LOOPS_OBSERVER` |
| `loops_env` | `loops_home` + cwd chdir'd into it |
| `simple_vertex` | Minimal vertex: one `fold_count` loop + store |
| `project_vertex` | Project-style vertex: `thread`/`decision`/`task` loops folding by name/topic |
| `autoresearch_vertex` | Autoresearch vertex: `experiment`/`log`/`finding` (`fold_collect`) + `config` |
| `populated_store` | `project_vertex` pre-seeded with a few facts; returns `(vertex_path, db_path)` |
| `app_state`, `store_explorer_state`, `autoresearch_fold_state`, … | TUI / FoldState builders for lens tests |

### `apps/loops/tests/golden/conftest.py`

| Fixture | Provides |
|---------|----------|
| `golden` | A `Golden` keyed by `request.node.module` + `request.node.name`, honoring `--update-goldens` |

### `apps/tasks/tests/conftest.py`

| Fixture | Provides |
|---------|----------|
| `home` | Isolated `LOOPS_HOME` tmp dir |
| `workspace` | Tmp workspace with copied `tasks.vertex`/`project.vertex`; monkeypatches `lifecycle` so reads hit temp files |
| `git_repo` | Minimal git repo with `main` branch + initial commit (for worktree tests) |

### `libs/engine/tests/conftest.py`

| Fixture | Provides |
|---------|----------|
| `tmp_jsonl` | Tmp JSONL path (not yet created) |
| `stream` | Fresh `Stream[Event]` |
| `event_store` | In-memory `EventStore[Event]` |
| `sum_projection`, `count_projection` | Seeded `Sum`/`Count` projections (the projection building blocks) |
| `file_writer`, `tailer` | `FileWriter`/`Tailer` bound to `tmp_jsonl` |

Engine also ships **`vertex_test_sdk.py`** — a reusable `VertexTestBuilder`
(fluent `count_loop`/`sum_loop`/`latest_loop`/`routes`/`with_store` → `build()`)
plus a `fact(...)` helper and `reopen_store(...)`. Prefer composing these
building blocks over pre-wired scenarios.

---

## 6. Coverage expectations (historical context)

There is no enforced minimum coverage gate; coverage is instrumentation, not a
pass/fail threshold. Historically, **Campaign 001** (documented in
`docs/autoresearch/CAMPAIGN-001-COVERAGE.md`) drove `apps/loops` coverage from
~85% to **98.4% line coverage (0 missed lines)** over 218 autoresearch
experiments, while compressing test runtime. Two takeaways from that campaign
inform how to read coverage here:

- **Coverage instrumentation adds ~1.7× timing overhead** — measure test speed
  with coverage *off*.
- **High line coverage is not test quality.** The campaign's own review (#218)
  surfaced tautological assertions (`or True`) and weak `isinstance(rc, int)`
  checks. Aim for assertions that would actually fail on a regression.

Treat 98.4% as a historical high-water mark for `apps/loops`, not a standing
requirement.

---

## See also

- [`../CLAUDE.md`](../CLAUDE.md) — build/test quickstart and project conventions
- [`code-standards.md`](code-standards.md) — coding conventions (frozen dataclasses, pure functions, lib boundaries)
- [`system-architecture.md`](system-architecture.md) — the lib/app dependency graph the architecture tests enforce
