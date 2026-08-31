# Slice 4 WP5 — fix round 1 (six blockings, gate-prescribed, arbiter-ruled; do IN ORDER)

## Working directory — verify FIRST
    /Users/kaygee/Code/loops-wt/s4-wp5
Prefix EVERY command with `cd /Users/kaygee/Code/loops-wt/s4-wp5 && `. First:
    cd /Users/kaygee/Code/loops-wt/s4-wp5 && pwd && git branch --show-current && git log --oneline -1
Expected: branch slice4/wp5, HEAD 7b7c9ff1. Otherwise STOP and report.
Env: pytest --basetemp=/private/tmp/s4wp5-tmp/pt (OUTSIDE the worktree — basetemp inside
poisons lang's corpus); lang and engine suites need `uv run --directory libs/<name>
pytest -q` with TMPDIR=/private/tmp/s4wp5-tmp; apps suite from worktree root, never
--directory. FOREGROUND ONLY; COMMIT EARLY, one commit per F-item.

## EXECUTE YOURSELF — DO NOT DELEGATE. One response.

## Scope fence
ONLY: tests/architecture/test_rule_19_third_party_imports_declared.py,
apps/loops/pyproject.toml, libs/store/pyproject.toml, libs/migrate/src/migrate/sidecar.py,
libs/lang/src/lang/** (the query module only) + libs/lang/tests/** (its tests),
libs/migrate/CLAUDE.md, docs/architecture/arrival/protocol.html + backend-contract.html,
libs/migrate/tests/test_sidecar.py (the one stray import). Nothing else. STOP on more.

## Fixes IN THIS ORDER (B3 first so the ratchet witnesses B4)

F1 (gate B3) — make the allowlist SHRINK-FORCING: test_rule_19_allowlist_is_minimal must
assert each entry IS STILL A VIOLATION (`module not in declared` for that entry's
package); a declared-but-still-allowlisted entry fails the test. Proof: after F2 lands,
the un-shrunk allowlist must go red (run it mid-sequence and paste).

F2 (gate B4) — declarations, exactly: apps/loops/pyproject.toml dev group gains
"rfc8785>=0.1.4" (no uv.sources change); libs/store/pyproject.toml gains atoms+lang in
[tool.uv.sources] (workspace) and "atoms","lang" in the dev group (runtime deps
UNCHANGED — Rule 4 row must not move). Then SHRINK the Rule-19 allowlist 10 → 2 (only
the two shipped testing/strategies entries survive). F1's test green again.

F3 (gate B1+B2) — sweep W2's residue in sidecar.py:249-274: the old regex/comment-span
locator is welded inert (`and store_span.count == 0` deadens both branches; dead regex
work every call). Delete the vestigial detection; the surviving refusal branches collapse
to the lang-query-driven guard (the existing labels-as-set test stays green — that is
the proof). AND in lang: StoreClauseSpan drops .line and .raw (zero consumers, derivable,
speculative on a new public export); its docstring stops promising a "source span" — it
is a LINE span; say so plainly (the same-line-comment deletion behavior is pre-existing
and documented honestly, not fixed here). Update lang tests accordingly.

F4 (gate B5+B6, one docs pass) — make every claim match the code:
(a) there is NO `.staging.arrival` suffix anywhere — staging IS the lineage-naming at
<store_dir>/<lineage>.arrival; fix CLAUDE.md (both places, it self-contradicts) and any
HTML echo. (b) report path is <lineage>.migration-report.json — fix the Level 0 example.
(c) the publish preconditions are exactly the code's five: target_verify_full,
equivalence_rerun, journal_first_entry_mint, inventory_equality, source-unchanged
(SourceChangedRefused); the already-migrated guard is an APPS-LAYER pre-flight
(commands/store.py:819-821), not a migrate precondition — state the layering honestly,
never attribute it to libs/migrate. (d) "report verified" → what the code does: the
signer returned a signature; run_migration never calls verify_migration_report (that
function exists for auditors). (e) CLAUDE.md quarantine section: the frozen legacy
copies, the AST ratchet (cite libs/migrate/tests/test_quarantine.py) and its ruled
slice-5 dissolution; injection section: src never imports custody/sign (dev-group-only),
signers injected. (f) replace the stale "nothing imports migrate" phrasing with
"migrate imports no legacy modules and has no write path into a live store" (apps
imports migrate.refusals since WP4 — the doc must not deny it).

F5 — delete the duplicate `from lang import BackendDecl, parse_vertex` at
libs/migrate/tests/test_sidecar.py:30 (F811/E501 regression; ruff back to base 7).

## Acceptance
COMMIT EARLY per item, proofs: (1) F1's mid-sequence red + post-shrink green, pasted;
(2) F3: re-add a vestigial `store_span.count == 0` branch → no test SHOULD care — so
instead prove by grep: no regex locator, no dead disjunct, and paste the labels-set test
green; (3) fresh-env migrate + store + apps collections still green after F2 (gate's
UV_PROJECT_ENVIRONMENT method, paste). Final: all suites green with the env forms above
(apps 2539+1x, migrate+custody+arch 181, lang 682 via --directory, store 180, engine
2306+1s via --directory); git status clean but .tmp/.

## Report (stdout, one shot): per-fix changes; proof evidence; honest gaps.
