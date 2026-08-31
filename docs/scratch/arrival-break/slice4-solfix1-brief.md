# Slice 4 — sol integration r1 remediation (5 blockings + 2 ride-alongs, arbiter-ruled)

## Working directory — verify FIRST
    /Users/kaygee/Code/loops-wt/s4-solfix1
Prefix EVERY command with `cd /Users/kaygee/Code/loops-wt/s4-solfix1 && `. First:
    cd /Users/kaygee/Code/loops-wt/s4-solfix1 && pwd && git branch --show-current && git log --oneline -1
Expected: branch slice4/sol-fix1 cut from main (libs/migrate present). Otherwise STOP.
Env: pytest --basetemp=/private/tmp/s4solfix-tmp/pt (OUTSIDE the worktree; mkdir it);
lang/engine suites via `uv run --directory libs/<name> pytest -q` with
TMPDIR=/private/tmp/s4solfix-tmp; apps from worktree root, never --directory.
FOREGROUND ONLY; COMMIT EARLY, one commit per F-item.

## EXECUTE YOURSELF — DO NOT DELEGATE. One response.

## Scope fence
ONLY: libs/migrate/src/** + libs/migrate/tests/**, libs/lang/src/lang/** (the
effective_store_clause module) + libs/lang/tests/**, apps/loops/src/loops/commands/store.py
(custodian derivation only) + apps/loops/tests/test_store_migrate.py, libs/migrate/CLAUDE.md.
Nothing else. Never touch .loops/ or real stores; never run sl/loops emit. STOP on more.

## Fixes (all RULED; cross-family findings from a codex/sol review — treat prescriptions
as binding, STOP if one conflicts with code)

F1 (s4-sol-r1-gf3-spelling-census-loss) — the report-once-under-mixed shape is RULED and
stays; what fixes: the mixed-class entry for a both-aspect batch line carries a
spelling-distinct absent-aspect census (how many rows MISSING the field vs how many
observer=""), and the refusal message states the true spelling (an ''-row is never called
"missing"). The locking test at libs/migrate/tests/test_inventory.py:201
(len(absent_observer_lines)==0 for that case is CORRECT and stays — the class placement
is ruled) updates only to pin the new spelling census inside the mixed entry. Probe shape
to satisfy: a batch of alice+bob+'' → mixed entry names ('alice','bob'), absent-aspect
census {empty: 1, missing: 0}, message says observer is the empty string.

F2 (s4-sol-r1-resume-incomplete-draft-diff) — the resume prefix diff at sidecar.py
:841-873 gains authored_at and signature (every RecordDraft identity field). Tests: a
resume target whose record differs ONLY in signature (outer-signed vs expected-unsigned)
refuses; same for authored_at. Mutation proof: drop signature from the diff → red.

F3 (s4-sol-r1-resume-breaks-lineage-naming) — resume refuses when the target filename is
not <genesis-lineage>.arrival (M-2 at the resume door): typed refusal naming both the
filename and the lineage. Test + the friendly-name probe case.

F4 (s4-sol-r1-custodian-authority-source, both arms) — ONE authority source:
(a) the custodian identity derives from the custody self-observer definition (the vertex
file STEM, as custody/signing.py defines it), everywhere — transform.py stops defaulting
to VertexFile.name; the CLI passes nothing it didn't derive the same way. A vertex whose
declared name differs from its filename migrates fine (test: display-name vertex with a
keyed stem observer). (b) REMOVE the public custodian/custodian_key parameters from
run_migration and transform — the custodian is derived, never caller-supplied; internal
tests that exercised overrides construct real vertices instead. Grep-prove no
caller-supplied custodian path remains.

F5 (s4-sol-r1-surgical-publish-deletes-comments) — lang's effective_store_clause learns
the SUB-LINE span of the clause itself (node name through end of its arguments), so the
editor replaces only the clause and preserves every trailing byte on the line (same-line
comments survive — test with `store "./a.jsonl" // KEEP` asserting KEEP survives the
publish byte-for-byte). Refuse-shaped returns unchanged. Docstrings updated to the
now-true claim (span = the clause's source span, for real this time). Mutation proof:
revert to whole-line span → the KEEP test red. Migrate editor tests re-green.

F6 (s4-sol-r1-doc-truth-drift ride-along) — (a) CLAUDE.md Stage 2: the lineage is
MINTED (random ULID), not "deterministic" — determinism belongs to the transform, say it
correctly; Stage 7: the writer checks the signature is non-None (not "valid"). (b)
sidecar.py's signing docstring states the ACTUAL signed envelope ({"body":..., "signer":...})
— match implementation exactly.

F7 (s4-sol-r1-migrate-lint ride-along) — bring libs/migrate to ruff-clean: run
`uv run ruff check --fix libs/migrate` for the mechanical classes (F401/I001), then a
manual E501/SIM/PTH pass. Zero errors at the end (paste `ruff check libs/migrate`
output). No behavior changes — suites prove it.

## Acceptance
COMMIT EARLY per item, then proofs (paste red → restore → green → empty production diff):
1. F2 mutation (drop signature from the diff) → red.
2. F4: re-add a custodian= parameter path → the derivation test red (or grep-prove the
   parameter cannot be reintroduced without failing a test — pin it).
3. F5 mutation (whole-line span) → KEEP-comment test red.
Final: apps 2539+1x+new (workspace root), libs/migrate+custody+arch green, lang
--directory green, engine --directory 2306+1s, ruff check libs/migrate → 0 errors,
git status clean but .tmp/.

## Report (stdout, one shot): per-fix changes; proof evidence; honest gaps.
