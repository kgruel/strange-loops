# Scaffold Template

The goal state: when starting a new project or app, what should be in place
from day one? This document accumulates resolved patterns from other threads.

## Status: Draft

Collecting patterns. Not yet actionable as a generator.

## What a New App Should Have

Based on what we've built and what we wish we'd had from the start.

```
apps/<name>/
├── CLAUDE.md                    # app conventions, dev cycle, domain mapping
├── DESIGN.md                    # architecture, fact kinds, CLI shape (if non-trivial)
├── dev                          # convention-based command dispatcher
├── pyproject.toml               # deps, entry point, test config
├── scripts/
│   ├── lib/dev.sh              # shared helpers (ok, fail, step, run_uv)
│   ├── check.sh                # arch → lint → test
│   ├── lint.sh                 # ty + ruff
│   ├── test.sh                 # pytest passthrough
│   └── fmt.sh                  # ruff format
├── src/<package>/
│   ├── __init__.py
│   ├── cli.py                  # thin dispatcher
│   └── commands/               # subcommand implementations
└── tests/
    ├── __init__.py
    ├── conftest.py             # building-block fixtures (not god-fixtures)
    ├── architecture/           # or test_architecture.py
    │   └── test_invariants.py  # frozen dataclasses, layer boundaries, conventions
    └── test_smoke.py           # import + entry point verification
```

## What a New Lib Should Have

```
libs/<name>/
├── CLAUDE.md                    # one concern, key types, invariants
├── README.md                    # API overview for external consumers
├── pyproject.toml               # minimal deps, test config
├── src/<package>/
│   ├── __init__.py             # public API re-exports
│   └── ...
└── tests/
    ├── __init__.py
    ├── conftest.py             # building-block fixtures
    └── test_<module>.py        # behavior-grouped test classes
```

## Conventions Baked In

### Testing

- **Factories over mocks.** `conftest.py` provides factory fixtures that build
  real objects. No `Mock(spec=X)` for internal types.
- **Behavior-grouped test classes.** `TestConstruction`, `TestSerialization`,
  `TestBoundaryFiring` — not `TestMyClass`.
- **Building-block fixtures.** Atomic, composable. Tests compose them for intent.
  No pre-wired scenario fixtures.
- **Architecture tests from day one.** Even if it's just "frozen dataclasses
  are frozen" and "public API matches `__init__.py` exports." Start with the
  invariants you already know.
- **Smoke test on scaffold.** `test_smoke.py` verifies import and CLI entry
  point. Exists from minute zero.

### Dev Harness

- `./dev check` is the CI gate. Runs before every commit.
- Default ordering: `arch → lint → test`
- `./dev -h` is self-documenting via `# DESC:` comments.
- `-v` flag on all scripts for verbose debugging.

### Documentation

- **CLAUDE.md** at app/lib level. Answers "what do I need to know to work here?"
- **DESIGN.md** if the architecture is non-trivial.
- **No README.md in apps** (CLAUDE.md serves the purpose). README.md in libs
  (for API consumers who aren't reading CLAUDE.md).

### Architecture Enforcement

- **Tier 1:** Package boundaries via pyproject.toml (cross-lib). Exists by
  default in monorepo.
- **Tier 2:** tach for import boundaries (within-lib or cross-module). Configure
  when intra-package structure matters.
- **Tier 3:** `tests/architecture/` for domain invariants. Start with frozen
  dataclass enforcement and naming conventions.

### pyproject.toml

```toml
[project]
requires-python = ">=3.11"

[dependency-groups]
dev = ["pytest>=8.0", "pytest-cov>=6.0", "ruff>=0.8", "ty"]

[tool.pytest.ini_options]
testpaths = ["tests"]

[tool.ruff]
target-version = "py311"
line-length = 100
```

## What's NOT in the Scaffold

- No CI pipeline (project-specific)
- No Dockerfile (not every project needs one)
- No pre-commit hooks (use `./dev check` manually or integrate later)
- No logging setup (add when needed)
- No config system (add when needed)

Keep the scaffold minimal. Add complexity when the use case demands it.

## Open Questions

- Should the scaffold be a `./dev new <name>` command in the monorepo root?
- Should it be a cookiecutter/copier template for standalone projects?
- How does tach.toml fit — per-app, per-lib, or monorepo root?
- Should the scaffold include a session vertex for development tracking?
