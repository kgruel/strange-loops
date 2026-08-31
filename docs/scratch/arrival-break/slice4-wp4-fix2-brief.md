# Slice 4 WP4 — fix round 2 (dep declarations + custody composition + guard honesty)

## Working directory — verify FIRST
    /Users/kaygee/Code/loops-wt/s4-wp4
Prefix EVERY command with `cd /Users/kaygee/Code/loops-wt/s4-wp4 && `. First:
    cd /Users/kaygee/Code/loops-wt/s4-wp4 && pwd && git branch --show-current && git log --oneline -1
Expected: branch slice4/wp4, HEAD df17edd3. Otherwise STOP and report.
Test env: TMPDIR=<worktree>/.tmp, pytest --basetemp=<worktree>/.tmp/pt; apps suite from
worktree root as `uv run pytest apps/loops -q` (never --directory).
FOREGROUND ONLY — never background a command; commit each fix as soon as coherent.

## EXECUTE YOURSELF — DO NOT DELEGATE. One response.

## Scope fence
ONLY: libs/migrate/pyproject.toml, libs/custody/src/custody/** + libs/custody/tests/**,
apps/loops/src/loops/commands/store.py, apps/loops/pyproject.toml (F4's one-line move).
Nothing else; never touch .loops/ or real stores. STOP and report anything more.

## Fixes (all RULED)

F1 (finding s4wp4-migrate-tests-undeclared-custody, gate B3 + the pre-existing sibling,
fence WIDENED BY RULING to cover both): libs/migrate/pyproject.toml declares BOTH
test-only deps in the dev group — `custody` AND `sign` (test_sidecar.py imports sign;
pre-existing, but declaring only custody leaves migrate's per-package CI job red for the
other cause — a half-fix that looks like a fix). Both with workspace uv.sources. src must
NEVER import either (grep-prove). Verify with the gate's method: a fresh
UV_PROJECT_ENVIRONMENT venv collects and runs libs/migrate green.

F2 (gate N5, ruled: compose, don't duplicate): custody's arrival pair was copy-pasted
from the fact pair (AST-identical today — which is the hazard, not the fix; comments
already eroded). Refactor: ONE private resolver per direction taking a domain argument;
fact_*/arrival_* become thin public wrappers. All existing custody tests + the mutual-
refusal pins stay green unchanged (behavior-preserving — that's the proof).

F3 (gate N6): export arrival_signer_for/arrival_verifier_for from custody/__init__
(__all__ included); store.py's import joins the `from custody import ...` idiom of its
eleven neighbors.

F4 (gate N7 + F6 nit): in _run_migrate's F8 guard — (a) replace the bare
`except Exception` fail-open with catching the loader's actual parse error type and
REFUSING cleanly (exit 2, "the vertex file cannot be parsed", advisory prose only in the
message) — never fail-open, never bare except; (b) delete the provably-unreachable second
disjunct (ARRIVAL_SUFFIX check — canonical_mode already answers it); (c) move "migrate"
into the workspace-deps ordering position in apps/loops/pyproject.toml.

## Acceptance
COMMIT FIRST, then proofs (paste red → restore → green → empty production diff):
1. F2: change the private resolver's domain handling to ignore the domain argument → the
   mutual-refusal custody test fails.
2. F4a: restore the bare-except fail-open → the unparseable-vertex test (add it) fails.
Final: `uv run pytest apps/loops -q` (state counts vs 2538+1x base); `uv run pytest
libs/migrate libs/custody tests/architecture -q` green; fresh-env migrate collection
green (paste); git status clean but .tmp/.

## Report (stdout, one shot): per-fix changes, proof evidence, honest gaps.
