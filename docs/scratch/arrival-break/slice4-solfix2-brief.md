# Slice 4 — sol r2 remediation (one scanner blocking + one docstring)

## Working directory — verify FIRST
    /Users/kaygee/Code/loops-wt/s4-solfix2
Prefix EVERY command with `cd /Users/kaygee/Code/loops-wt/s4-solfix2 && `. First:
    cd /Users/kaygee/Code/loops-wt/s4-solfix2 && pwd && git branch --show-current && git log --oneline -1
Expected: branch slice4/sol-fix2 from main. Otherwise STOP. Env: basetemp
/private/tmp/s4solfix-tmp/pt2 (outside worktree); lang via --directory. FOREGROUND ONLY,
COMMIT EARLY.

## EXECUTE YOURSELF — DO NOT DELEGATE. One response.

## Scope fence
ONLY libs/lang/src/lang/loader.py (the _scan_kdl_node_end scanner), libs/lang/src/lang/ast.py
(the StoreClauseSpan docstring), libs/lang/tests/**. Nothing else. STOP on more.

## Fix 1 (finding s4-sol-r2-hash-raw-store-span, BLOCKING). _scan_kdl_node_end
(loader.py:~1011-1061) recognizes hash-raw strings (r#"..."#) only when one STARTS a
token; embedded in a property value (backend=r#"fi" fake"#) the inner quote is taken as
a closing quote and the scanner consumes into trailing comments — producing ACCEPTED
wrong spans (probed: old property bytes leaked into the edited line; a trailing comment
deleted). KDL admits any non-empty backend string, so the shape is VALID input. Fix: the
scanner lexes a hash-raw string token wherever a value may begin — `r` + N hashes + `"`
... `"` + N hashes, N >= 0, matching hash counts — and skips its contents atomically
(same treatment as its existing quoted-string handling; mirror how it already lexes
token-initial raw strings). Unterminated raw string → refuse-shaped return, file
untouched. Tests (lang): sol's two accepted-wrong cases as regression tests —
(a) `store "./legacy.jsonl" backend=r#"fi" fake"# // KEEP OPERATOR " tail` → span ends
at the closing `"#`, publish-style rewrite preserves ` // KEEP OPERATOR " tail`
byte-for-byte; (b) `backend=r#"fi"` variant → no old-property bytes leak into an edited
line; (c) nested-hash form r##"..."## with embedded "# ; (d) unterminated raw →
refuse-shaped. Mutation proof: revert to the token-initial-only recognition → tests (a)
and (b) red.

## Fix 2 (s4-sol-r2-storeclausespan-doc-stale). StoreClauseSpan's docstring
(ast.py:698-705) still describes the whole-line span and comment replacement — the
opposite of the landed sub-line behavior. Rewrite to the truth: sub-line clause span,
trailing bytes preserved.

## Acceptance
COMMIT FIRST, then the mutation proof (paste red → restore → green → empty production
diff). Final: `uv run --directory libs/lang pytest -q` green (683+new); `uv run pytest
libs/migrate tests/architecture -q` untouched-green; git status clean but .tmp/.

## Report (stdout, one shot): changes, proof evidence, honest gaps.
