# Slice 4 WP3 — fix round 2 (two small ruled items before merge)

## Working directory — verify FIRST
    /Users/kaygee/Code/loops-wt/s4-wp3
Prefix EVERY command with `cd /Users/kaygee/Code/loops-wt/s4-wp3 && `. First:
    cd /Users/kaygee/Code/loops-wt/s4-wp3 && pwd && git branch --show-current && git log --oneline -1
Expected: branch slice4/wp3, HEAD 70a6dbb2. Otherwise STOP and report.
Test env: TMPDIR=/Users/kaygee/Code/loops-wt/s4-wp3/.tmp, pytest --basetemp=.../.tmp/pt.

## EXECUTE YOURSELF — DO NOT DELEGATE. One response.

## Scope fence
ONLY libs/migrate/**. Nothing else. Never touch .loops/ or run sl/loops emit.

## Fix 1 (finding s4wp3-report-verifier-retypes-unopenable — the F4 anti-pattern
reintroduced in the new verifier). verify_migration_report wraps the target open in a bare
`except Exception` and raises ReportHeadMismatchRefused — asserting the head DIFFERS when
it could not be READ (cause chain seen live: ReportHeadMismatchRefused <- StoreLost <-
ArrivalTornTail). Fix: a fifth distinct verifier cause (target-unopenable, carrying the
cause) with a typed catch (StoreLost / ArrivalTornTail / ArrivalCorrupt / OSError — never
bare Exception re-typed narrower); ReportHeadMismatchRefused is raised ONLY after a
successful open and an actual comparison. Test: verifier against a torn-tail target →
the unopenable cause with the engine type in the chain, NOT head-mismatch; mutation:
restore the bare-except re-type → that test goes red.

## Fix 2 (finding s4wp3-migrate-undeclared-ckdl-bypasses-lang — interim form, ruled).
sidecar.py imports ckdl directly (undeclared; works via lang's transitive install) and
holds a second KDL parse path. INTERIM fix now: declare ckdl in libs/migrate/pyproject.toml
dependencies (same version spec lang uses — read libs/lang/pyproject.toml) and add a loud
comment at the import site: "INTERIM: direct ckdl parse pending the ruled dissolution —
lang exposing its effective-store-clause query (finding s4wp3-migrate-undeclared-ckdl-
bypasses-lang); do not add further ckdl call sites." Do NOT redesign the editor and do
NOT touch libs/lang.

## Acceptance
COMMIT FIRST, then the Fix-1 break/restore proof (paste red/green + empty production
diff). Final: uv run pytest libs/migrate tests/architecture -q all green;
git status --short clean but .tmp/.

## Report (stdout, one shot): changes, proof evidence, honest gaps.
