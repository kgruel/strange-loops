# Fidelis Extraction Design

Extract `libs/cells/` from the loops monorepo into a standalone project
at `/Users/kaygee/Code/fidelis/`, renamed from `cells` to `fidelis`.

## Decisions

- **PyPI name:** `fidelis` (available)
- **Import name:** `fidelis` (full rename, no split personality)
- **License:** MIT
- **Repo location:** `/Users/kaygee/Code/fidelis/`
- **Approach:** Fresh repo, clean initial commit (no extracted git history)
- **Monorepo migration:** Remove `libs/cells/`, path dep to `../fidelis`
- **Scope:** Extract + rename only. No new features, no CI, no PyPI publish.

## New Repo Structure

```
fidelis/
├── pyproject.toml
├── LICENSE
├── README.md
├── src/fidelis/          # renamed from src/cells/
│   ├── __init__.py
│   ├── cell.py, span.py, block.py, compose.py, ...
│   ├── tui/
│   ├── lens/
│   ├── widgets/
│   ├── mouse/
│   ├── effects/
│   └── components/
├── tests/
├── demos/                # from demos/cells/
└── docs/                 # from libs/cells/docs/
```

## PyPI Metadata

```toml
[project]
name = "fidelis"
version = "0.1.0"
description = "An opinionated cell-buffer terminal UI framework"
license = "MIT"
authors = [{ name = "Kyle Gruel", email = "kylegruel@gmail.com" }]
requires-python = ">=3.11"
dependencies = ["wcwidth>=0.2"]
classifiers = [
    "Development Status :: 3 - Alpha",
    "Environment :: Console",
    "Intended Audience :: Developers",
    "License :: OSI Approved :: MIT License",
    "Programming Language :: Python :: 3.11",
    "Programming Language :: Python :: 3.12",
    "Programming Language :: Python :: 3.13",
    "Topic :: Terminals",
    "Typing :: Typed",
]

[project.urls]
Homepage = "https://github.com/kgruel/fidelis"
Repository = "https://github.com/kgruel/fidelis"
```

## Monorepo Changes

1. Remove `libs/cells/` from workspace members and delete directory
2. Replace `cells` workspace dep with `fidelis` path dep (`../fidelis`)
3. Rename all `from cells` → `from fidelis` in apps/experiments/demos
4. Move `demos/cells/` to fidelis repo, remove from monorepo
5. Update CLAUDE.md references

## Rename Scope

Every `cells` Python package reference → `fidelis`:
- Package directory, all imports, tests, demos, docs, pyproject.toml
- The Cell *primitive* name stays — `fidelis.Cell` is a cell

## Implementation Plan

Structured for maximum parallelism.

### Phase 1: Scaffold (sequential — must complete first)

1. Create `/Users/kaygee/Code/fidelis/` with `git init`
2. Write `pyproject.toml` with full metadata
3. Write `LICENSE` (MIT, 2026, Kyle Gruel)
4. Copy `libs/cells/src/cells/` → `src/fidelis/`
5. Copy `libs/cells/tests/` → `tests/`
6. Copy `libs/cells/docs/` → `docs/`
7. Copy `demos/cells/` → `demos/`

### Phase 2: Rename in fidelis repo (parallelizable)

These are independent find-and-replace tasks across different file sets:

- **2a:** Rename imports in `src/fidelis/` (all .py files)
- **2b:** Rename imports in `tests/` (all .py files)
- **2c:** Rename imports in `demos/` (all .py files)
- **2d:** Update `docs/` references (all .md files)
- **2e:** Update CLAUDE.md for the new repo
- **2f:** Adapt README.md for public-facing fidelis identity

### Phase 3: Verify fidelis (sequential)

1. `uv sync` in fidelis repo
2. Run all 349 tests — must pass
3. Spot-check a demo runs

### Phase 4: Monorepo migration (parallelizable after Phase 3)

- **4a:** Update root `pyproject.toml` — remove `libs/cells` from workspace
- **4b:** Update `apps/loops/pyproject.toml` — cells → fidelis path dep
- **4c:** Update `apps/hlab/pyproject.toml` — cells → fidelis path dep
- **4d:** Rename `from cells` → `from fidelis` in `apps/loops/`
- **4e:** Rename `from cells` → `from fidelis` in `apps/hlab/`
- **4f:** Rename `from cells` → `from fidelis` in `experiments/`
- **4g:** Remove `demos/cells/` from monorepo
- **4h:** Remove `libs/cells/` from monorepo
- **4i:** Update monorepo CLAUDE.md and HANDOFF.md references

### Phase 5: Verify monorepo (sequential)

1. `uv sync` in loops monorepo
2. Run app tests that depend on fidelis
3. Initial commit in fidelis repo

### Parallelism Map

```
Phase 1 (sequential)
    │
    ▼
Phase 2: [2a, 2b, 2c, 2d, 2e, 2f] ← all parallel
    │
    ▼
Phase 3 (sequential)
    │
    ▼
Phase 4: [4a+4b+4c, 4d+4e+4f, 4g+4h, 4i] ← parallel groups
    │
    ▼
Phase 5 (sequential)
```
