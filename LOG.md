# LOG

Session history for fidelis.

---

## 2026-02-22 — Extraction and cleanup

Extracted `libs/cells/` from the loops monorepo into standalone fidelis repo.

**What happened:**
- Created `/Users/kaygee/Code/fidelis/` with `git init`
- Copied src, tests, demos, docs from `libs/cells/` and `demos/cells/`
- Renamed all `cells` → `fidelis` (package, imports, docs, demos)
- Set up pyproject.toml with full PyPI metadata (MIT, hatchling, py>=3.11)
- 349 tests passing on initial commit

**Monorepo side:**
- Removed `libs/cells/` and `demos/cells/` from loops
- Updated app pyproject.toml files to path dep `../../../fidelis`
- Fixed path resolution (uv resolves relative to member location, not workspace root)
- 732 monorepo tests passing (atoms 295 + engine 357 + loops 80)

**Post-extraction cleanup:**
- Renamed `bench.py` → `tour.py`
- Updated all stale `demos/cells/` and `demos/fidelis/` paths to `demos/`
- Fixed `slide_loader.py` broken import (`from demos.bench` → `from demos.tour`)
- Removed deprecated Fidelity API (Fidelity enum, HarnessContext, detect_fidelity,
  add_fidelity_args, run_with_fidelity, fidelity_to_zoom) — clean break at 0.1.0
- Updated DEMO_PATTERNS.md, README.md, FIDELITY.md for tour rename
- 347 tests passing after cleanup (4 deprecated tests removed)

**Pushed to:** `git@git.gruel.network:kaygee/fidelis.git` (8 commits on main)
