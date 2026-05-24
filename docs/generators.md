# Documentation Generators

Some docs *mirror* a machine-readable source of truth. Those rot silently — a command
gets retired, a flag renamed, a symbol added to `__all__` — and the hand-written mirror
keeps lying until someone runs the thing. This repo hit exactly that: `loops export`
documented as live after retirement, `--minimal` documented when the flag is `-q`,
`Grant(observer=...)` documented after the field was removed.

This page is the map of what we generate, what we *could*, and what we deliberately
don't.

## The rule (dissolution test, applied to docs)

> **Generate** a doc section iff it is a projection of a machine-readable source of
> truth — CLI argparse help, a package `__all__`, `pyproject` dependencies, git log.
>
> **Hand-write** a doc section that expresses *intent* — the conceptual deep-dives, the
> guide ladder, design rationale, curated practice tables. Generation would flatten the
> judgment that makes them worth reading.

A corollary: where curation *is* valuable but drift is still a risk (the API reference's
hand-written "Brief" columns), don't regenerate — **validate**. Catch the drift class
(symbol added/removed/renamed) without overwriting the prose.

## The tool

[`bin/gen-docs.py`](../bin/gen-docs.py) — one tool, a generator-function per region,
plus a `--check` mode for CI.

```bash
uv run --package loops python bin/gen-docs.py            # regenerate in place
uv run --package loops python bin/gen-docs.py --check    # verify; exit 1 if stale
```

It runs via `uv run` (from source, not the installed `sl`) on purpose: a doc check must
validate the code being committed, not whatever binary happens to be installed. This is
the inverse of the smoke-test caveat in the root `CLAUDE.md` — for *verifying the
installed binary* you use `sl`; for *documenting the source* you use `uv run`.

Determinism is load-bearing for `--check`: `COLUMNS` is pinned to 80 (argparse wraps to
terminal width otherwise), iteration follows stable dict / `__all__` order, and there
are no timestamps in output.

## Generated now

| Artifact | Source of truth | How |
|----------|-----------------|-----|
| [`cli-catalog.md`](cli-catalog.md) | `loops.cli.registry` + each command's argparse `--help` | Every verb/command, status badge, verbatim help. New/removed commands appear/vanish automatically; retired stubs (`export`) are flagged via a tiny curated `KNOWN_STATUS` overlay. |

## Validated now (not generated — curation worth keeping)

| Doc | Check | Catches |
|-----|-------|---------|
| [`api-reference.md`](api-reference.md) Part 2 | every workspace lib's `__all__` symbol must appear in the text | a symbol exported but undocumented, or documented after it stopped being exported |

## Candidates — one generator-function each away

These fit the rule and are cheap to add; they're left out for now to keep scope tight,
not because they don't belong.

| Candidate | Source of truth | Feasibility |
|-----------|-----------------|-------------|
| `changelog.md` | `git log --no-merges` with conventional-commit prefixes | High — parse `type(scope): subject`, group by type, append new entries since the last recorded hash. The learn workflow already does this by hand. |
| `codebase-summary.md` dependency tables | each package's `pyproject.toml` `[project.dependencies]` | High — pure projection; one table per workspace member. |
| atoms fold/parse op vocabulary | `atoms.__all__` categories + class docstrings | Medium — overlaps the API reference; only worth it if a standalone op cheat-sheet is wanted. |
| Internal dependency graph | AST import scan (the existing `tests/test_architecture.py` already parses this) | Medium — reuse the architecture test's import map to emit a Mermaid graph for `system-architecture.md`. |

To add one: write a `render_<region>()` returning markdown, write it to its target (or
splice between `<!-- GENERATED:<name> START/END -->` markers for an in-doc block), and
add it to the `--check` path.

## Not candidates (deliberately hand-written)

- **Conceptual deep-dives** — `VERTEX`, `TEMPORAL`, `PERSISTENCE`, `IDENTITY`,
  `SCOPE-LATTICE`, `CADENCE`, `LENSES`. These explain *why*, not *what*.
- **The guide ladder** (`guides/`) — pedagogy and sequencing; no machine source.
- **`project-overview-pdr.md`, design rationale** — human intent.
- **Curated practice tables** — the kind/fold-key table, topic-prefix discipline, and
  emit-timing guidance in the root `CLAUDE.md` are *decisions*, not projections of code.

## Enforcement

The check is wired into the repo-root gate:

```bash
./dev check        # runs bin/gen-docs.py --check
```

`./dev` is a script-discovering dispatcher (same pattern as `apps/*/dev`); `./dev check`
runs `scripts/check.sh`, which currently enforces documentation drift. Add further
repo-wide checks by dropping a `scripts/<name>.sh` with a `# DESC:` line. Per-package
gates still live in each lib/app's own `./dev`.

For tighter loops, the underlying command also runs standalone:

```bash
uv run --package loops python bin/gen-docs.py --check
```
