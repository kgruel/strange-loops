# Code Standards & Conventions

How code in this monorepo is structured, the invariants it holds to, and the
gates it must pass. This is the *engineering* companion to the architecture map
([`system-architecture.md`](system-architecture.md)). For project-specific
working practice (the loops dogfooding workflow, vertex/kind discipline) the
canonical source is [`../CLAUDE.md`](../CLAUDE.md) — this doc links to it rather
than restating it.

---

## Core values

The repo follows these in tension-breaking order:

1. **Correctness over convenience.**
2. **Doing it right over doing it now.**
3. **Maintainability over short-term productivity.**
4. **Robust design over quick fixes.**

Two design heuristics applied throughout:

- **Explicit over implicit / simple by default, complex when justified.**
- **Dissolution test** — before adding a construct, ask whether it can be expressed
  as a property or composition of what already exists. If yes, it dissolves.

## Immutability by default

- **Frozen dataclasses** for data carriers (`Fact`, `Tick`, `Peer`, `Grant`, `Lens`,
  `Cadence`, all `lang` AST nodes, all `store` result types).
- **Pure functions** for transformation — folds are `(state, payload) → new_state`;
  rendering is `(data, zoom, width) → Block`. No in-place mutation of shared state.
- **`MappingProxyType`** wraps dict payloads for effective immutability.
- State is **derived, not stored** — reconstructable by replaying facts.

Mutation, where it exists, is local and opt-in (`Spec.replay()` mutates for bulk
efficiency; `Spec.apply()` deep-copies to stay pure).

## Library boundaries (enforced)

```
atoms (0 internal deps)  →  engine (imports atoms TYPE_CHECKING only, + lang)  →  store
apps depend on atoms + engine + lang + painted ;  sign is independent
```

- `engine` imports `atoms` **only** under `if TYPE_CHECKING:` (or deferred into
  function bodies) — never at runtime module load.
- No cross-lib imports beyond the graph above; **no cycles**.
- These rules are checked by **`tests/test_architecture.py`** (AST-based). A
  violation fails CI, not just review.

→ The full graph and rationale: [`system-architecture.md` §5](system-architecture.md#5-dependency-rules), [`codebase-summary.md`](codebase-summary.md).

## Package layout

Every lib and app follows the same shape:

```
libs/<name>/  (or apps/<name>/)
  CLAUDE.md          progressive, level-based onboarding for that package
  pyproject.toml     package metadata + deps + tool config
  src/<pkg>/         source (note: src-layout)
    __init__.py      public surface via lazy __getattr__ / __all__
  tests/             pytest, mirrors src/
  dev                (some packages) ./dev check — the CI gate
```

- **Public API is the `__init__.py` surface.** Many packages export lazily via
  `__getattr__` to keep import time low (`atoms` ~13ms, deferring stdlib/3rd-party).
  Underscore-prefixed names have no stability contract.
- **Deprecated aliases** are retained for back-compat and marked as such (`Shape`
  for `Spec`, `Facet` for `Field`, `CommandSource` for `Source`).
- **Progressive CLAUDE.md** — start at the level matching your intent; see the
  routing table in [`../CLAUDE.md`](../CLAUDE.md) ("Where to start").

## Tooling & style

| Concern | Setting |
|---------|---------|
| Python | ≥3.11 (pyright targets 3.13) |
| Formatter / linter | `ruff` — line-length **100**, target-version `py311`, rules `[E, F, I, UP, B, SIM, PTH]` |
| Type checking | `ty` (per-package); `pyrightconfig.json` at root |
| Tests | `pytest`, `pytest-cov` branch coverage; `asyncio_mode = auto` in the async packages (`atoms`, `engine`) |
| Config locality | per-package `pyproject.toml`; no root `ruff.toml` |

## The CI gate — `./dev check`

Packages with a `./dev` script expose `./dev check` as the pre-commit gate
(typically: type check + format check → tests). **`./dev check` must pass before
commit.** → exact steps per package live in its `dev` script; see [`testing-guide.md`](testing-guide.md).

## Rendering discipline

- **No raw `print`.** All CLI output flows through a single boundary — the
  `Reporter` protocol (`PaintedReporter` in production, `BufferReporter` in tests).
- **Lenses are pure** `(data, zoom, width, **kwargs) → painted.Block`. Orchestration
  (vertex resolution, fetching) stays in the `_run_*` / command layer, never in a
  lens.
- **Fidelity levels** — MINIMAL (counts) / SUMMARY (orient) / DETAILED / FULL
  (progressive disclosure). The same data renders at all four. → [`LENSES.md`](LENSES.md).

## The CLI install discipline (load-bearing)

After changing CLI code, run **`uv tool install . -e`** and exercise via `sl …`
directly. The user-installed `sl` is the production path; the workspace-runner
form (`uv run --package loops sl …`) rebuilds from source each invocation and can
**mask staleness** of the installed binary. (This is anchored in [`../CLAUDE.md`](../CLAUDE.md)
by a real two-month divergence that in-session smoke tests hid.)

## Commit & changelog conventions

- Type-prefixed commit subjects: `feat/<slug>`, `fix/<slug>`, `refactor`,
  `docs:`, `changelog:`, plus area prefixes like `loops/<area>`.
- Dated `changelog:` commits carry human-readable notes inline. → [`changelog.md`](changelog.md).

## Project working practice

The deeper *practice* layer — how this repo dogfoods loops (vertex selection,
kind/topic-prefix discipline, emit timing, ref-graph fidelity, friction-in-moment)
— is documented in [`../CLAUDE.md`](../CLAUDE.md) and the deep dives. Not restated
here to avoid drift; treat `CLAUDE.md` as canonical for working conventions.

---

*See also: [../CLAUDE.md](../CLAUDE.md) · [system-architecture.md](system-architecture.md) · [codebase-summary.md](codebase-summary.md) · [testing-guide.md](testing-guide.md)*
