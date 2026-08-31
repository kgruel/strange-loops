# Slice 4 WP5 — docs, residue, the lang store-clause dissolution, and the deps ratchet

## Working directory — verify FIRST

    /Users/kaygee/Code/loops-wt/s4-wp5

Prefix EVERY command with `cd /Users/kaygee/Code/loops-wt/s4-wp5 && `. First:

    cd /Users/kaygee/Code/loops-wt/s4-wp5 && pwd && git branch --show-current && git log --oneline -1

Expected: branch `slice4/wp5` cut from main after the WP4 merge (`loops store migrate`
must exist in apps and `arrival_signer_for` in custody — verify both; STOP if absent).
Test env: `TMPDIR=<worktree>/.tmp`, pytest `--basetemp=.../.tmp/pt`; ENGINE suite runs
use `TMPDIR=/private/tmp/s4wp5-tmp` (create it); the apps suite runs from the worktree
root as `uv run pytest apps/loops -q` — never `--directory`.
FOREGROUND ONLY — never background a command or end your turn waiting. COMMIT EARLY —
each coherent item its own commit.

## EXECUTE YOURSELF — DO NOT DELEGATE. One response.

## Context

Final build package of slice 4 (`design:arrival-break-slice4-migration-sidecar` +
amendments #1-#3 — read the design fact via `sl read project --kind design --plain |
grep -A5 slice4` read-only from /Users/kaygee/Code/loops, and the proposal
docs/scratch/arrival-break/slice4-design-proposal.md §0.5, §F, §L). Four ruled work
items; deviations reportable, never decidable.

## Scope fence

You MAY edit ONLY: `docs/architecture/arrival/protocol.html` + `backend-contract.html`
(prose catch-up), `libs/engine/src/engine/arrival.py` (PROSE ONLY — the two stale
docstring/message passages named in W1; zero behavior tokens), `libs/store/CLAUDE.md`,
`libs/migrate/CLAUDE.md` (new) + `libs/migrate/src/migrate/sidecar.py` (W2's ckdl
dissolution + W4's docstring line) + `libs/migrate/tests/**`, `libs/lang/src/lang/**` +
`libs/lang/tests/**` (W2's query only), `tests/architecture/` (W3's new rule test only),
and `tests/architecture/test_rule_04_lib_dependency_dag.py` ONLY if W2 changes migrate's
real imports. NOTHING else. Never touch `.loops/` or real stores; never run `sl`/`loops`
emit. STOP and report anything more.

## The work

**W1 — stale-prose sweep (proposal §L.2, ruled at ratification).** `arrival.py` carries
two passages contradicting the ratified design: the "a keyless genesis belongs to the
migration sidecar" refusal-message clause (:~565-571) and mint's docstring "containment
claims belong to the migration sidecar's genesis" (:~889-892). The ratified protocol.html
§09 says the OPPOSITE (ordinary signed genesis; claims live in the signed report +
bootstrap receipt). Rewrite BOTH passages to the ratified truth — prose only; run the
engine suite before and after and paste identical counts. Sweep for any sibling stale
phrases (`grep -n "migration sidecar" libs/engine/src/engine/*.py`) and fix or report
each hit.

**W2 — the lang store-clause query dissolution (closes
finding/s4wp3-migrate-undeclared-ckdl-bypasses-lang).** `sidecar.py` holds a direct
`ckdl.parse` call (one site, fenced by an INTERIM comment) to locate the effective store
clause line for the surgical edit. lang is the repo's KDL boundary and already parses
`.vertex` files. Add to lang a SMALL public query — e.g.
`effective_store_clause(text) -> StoreClauseSpan` (frozen dataclass: line number, the
clause's source span, count of store nodes found) — implemented on lang's existing parse
machinery, returning enough for the editor to (a) locate the ONE effective clause line
and (b) refuse on duplicates/ambiguity exactly as the CLI's F2 guard does today. Then
`sidecar.py`'s ckdl import + interim comment DISSOLVE — it calls the lang query; migrate
already depends on lang (Rule 4 row unchanged). Design the return shape from what the
TWO existing consumers (the editor's locate + the ambiguity refusal) actually need —
nothing speculative. lang tests: the query against a comment-shadowed clause, duplicate
clauses, unusual spacing, no store clause. Migrate's editor tests must pass unchanged
(behavior-preserving at the editor surface — that is the proof). Mutation: make the
query return the FIRST rather than the effective clause → the comment-shadow editor test
goes red.

**W3 — the imports⊆declared-deps ratchet (ruled; fourth instance of the defect class
this slice).** New `tests/architecture/test_rule_19_third_party_imports_declared.py`
(next free rule number — verify 19 is free; if not, take the next): for every lib under
libs/ AND apps/loops, parse src/ (and tests/ where the package declares a dev group)
with `ast`; every top-level imported module that is not stdlib, not a relative import,
and not another workspace member must appear in that package's declared dependencies
(pyproject `dependencies` for src/, dependencies+dev group for tests/). Enumerable,
shrink-only allowlist for any deliberate exception (expect NONE — start empty; if
reality forces an entry, report it rather than silently allowlisting). Style-match the
neighbouring rule files (docstring explains the why: Rule 4 sees only inter-lib imports;
this slice hit the gap four times — ckdl, migrate-in-apps, custody+sign in migrate
tests). Prove it catches: temporarily remove `sign` from migrate's dev group → red;
restore.

**W4 — small ruled residue.** (a) `_check_inventory_equality`'s docstring gains the line
that partial-batch drops are refused upstream by the transformer, so its dropped-units
accounting covers whole-unit drops only (gate note, WP3 r2). (b) `libs/migrate/CLAUDE.md`
(new, short): the sidecar's purpose, the quarantine rule (nothing imports migrate; the
frozen copies import no legacy modules — cite the in-package AST ratchet and its slice-5
dissolution), the injection rule (src never imports custody/sign — signers are injected;
test-only deps in the dev group), and the pipeline stages with the design-fact pointer.
(c) `libs/store/CLAUDE.md`: the Rebirth section gains one paragraph — rebirth is
sqlite→sqlite, superseded for migration by libs/migrate (the sidecar), slated for
slice-5 disposition; do not grow its use. (d) protocol.html §09 + backend-contract.html
§11: a short "as-built (slice 4)" note per section — lineage-named staging, the five
publish preconditions + already-migrated guard, the arrival custody domain
(loops-arrival-v1), outer-unsigned migrated records, report beside target. Match each
document's voice; surgical additions, not rewrites.

## Acceptance bar

COMMIT EARLY per item, THEN proofs (paste red → restore → green → empty production diff
each):

1. W2 mutation (first-vs-effective clause) → editor comment-shadow test red.
2. W3 (remove sign from migrate dev group) → the new rule red.

Final checks, paste output: engine suite identical counts before/after W1 (2306+1s);
`uv run pytest libs/migrate libs/custody libs/lang tests/architecture -q` green;
`uv run pytest apps/loops -q` (workspace-root) 2539+1x; `grep -rn "import ckdl"
libs/migrate/src/` EMPTY; `git status --short` clean but `.tmp/`.

## Report format (stdout, one shot)

Per-item changes; evidence per proof; the lang query's final shape and why; any
allowlist entry W3 forced (expect none); anything stopped on; found-but-left-alone;
honest unverified list.
