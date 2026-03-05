# Dev Harness Pattern

The `./dev` dispatcher and its scripts — a convention-based development CLI
that's replicated across siftd, painted, and strange-loops.

## The Pattern

A single executable `./dev` at the project root that discovers commands from
`scripts/*.sh`. No Makefile, no task runner, no config file. Convention *is*
the config.

```
project/
├── dev                    # ~33 line bash dispatcher
├── scripts/
│   ├── lib/dev.sh        # shared helpers
│   ├── check.sh          # CI gate (the important one)
│   ├── lint.sh           # ty + ruff
│   ├── test.sh           # pytest passthrough
│   └── fmt.sh            # ruff format
```

### The Dispatcher (`dev`)

```bash
#!/usr/bin/env bash
# Usage: ./dev <command> [options]
# Commands are discovered from scripts/*.sh
```

- Scans `scripts/*.sh` for files
- Extracts `# DESC:` comment from each for help text
- Routes `./dev <name> [args]` to `bash scripts/<name>.sh [args]`
- `./dev` or `./dev -h` prints discovered commands with descriptions

### Shared Helpers (`scripts/lib/dev.sh`)

```bash
DEV_ROOT          # auto-computed from script location
SRC_DIR           # derived
TESTS_DIR         # derived

ok()              # colored [OK]
fail()            # colored [FAIL] to stderr
step()            # colored [...] (in progress)
warn()            # colored [WARN] to stderr

run_uv()          # uv run --package <pkg> $@
require_command()  # fail if cmd not found
```

Color output auto-disables when not a TTY.

### The CI Gate (`check.sh`)

This is the one that matters. It's the fast-fail gate that runs before commits.
The *ordering* encodes what matters most:

| Project | check.sh order |
|---------|---------------|
| **painted** | arch → lint → unit → golden |
| **siftd** | lint → arch → unit |
| **strange-loops** | lint → test |

All support `-v` for verbose output. All exit on first failure. The sequencing
is a design decision — painted puts architecture first because structural
violations make everything else noise.

**Converging toward:** `arch → lint → test` as the default order for new projects.

## Where It Exists

| Project | Has `./dev` | Has `check.sh` | Has `lib/dev.sh` | Notes |
|---------|-------------|-----------------|-------------------|-------|
| siftd | Yes | Yes | Yes | Also has `agent.sh`, `agent-close.sh`, `docs.sh`, `setup.sh` |
| painted | Yes | Yes | Yes | Also has `cov.sh` |
| strange-loops | Yes | Yes | Yes | Minimal — just lint + test so far |
| loops (root) | No | No | No | Uses `uv run --package X pytest` directly |
| gruel.network | No | `hlab` dispatcher | `scripts/lib/common.sh` | Different shape — operational, not dev |

## What's Missing from the Pattern

**No monorepo variant.** The `./dev` pattern assumes one package per project.
The loops monorepo has 4 libs and 4 apps — `./dev test` would need to know
which package. Options:

1. Root `./dev test` runs all packages (slow but complete)
2. Root `./dev test atoms` targets one package
3. Each app gets its own `./dev` (strange-loops already has this)
4. Root `./dev` delegates to per-app `./dev` scripts

Option 2 or 3 seems right. Strange-loops already does 3. The root could do 2
for cross-cutting operations (full test suite, full lint).

**No `./dev new` or scaffold command.** When starting a new app in the monorepo,
you manually copy the `dev` + `scripts/` structure. Could be automated —
`./dev new <name>` creates the app skeleton with harness, CLAUDE.md, conftest,
smoke test, pyproject.toml.

## Why Not Make/Just/Task/etc?

- **Make**: implicit, requires knowing Makefile syntax, targets aren't discoverable
- **Just**: better than Make, but another dependency and config format
- **Task (go-task)**: YAML config, another binary
- **`./dev`**: bash (universal), self-documenting (DESC comments), zero deps,
  discoverable (`./dev` prints help), convention-based (add a script, it appears)

The pattern trades power for simplicity. No dependency graph between tasks, no
parallel execution, no caching. It's a dispatcher, not a build system. That's
the point.

## Graduation Criteria

When a `./dev` script becomes complex enough to need argument parsing, subcommands,
or state, it should graduate to a Python CLI (like `loops` or `hlab` did). The
`./dev` harness is for the dev cycle, not the product.
