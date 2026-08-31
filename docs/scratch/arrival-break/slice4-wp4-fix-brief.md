# Slice 4 WP4 — fix round 1 (both seats + arbiter rulings incl. amendment #3)

## Working directory — verify FIRST

    /Users/kaygee/Code/loops-wt/s4-wp4

Prefix EVERY command with `cd /Users/kaygee/Code/loops-wt/s4-wp4 && `. First:

    cd /Users/kaygee/Code/loops-wt/s4-wp4 && pwd && git branch --show-current && git log --oneline -1

Expected: branch `slice4/wp4`, HEAD e1de3a4b. Otherwise STOP and report. Targeted-test env:
`TMPDIR=/Users/kaygee/Code/loops-wt/s4-wp4/.tmp`, pytest `--basetemp=.../.tmp/pt`. The FULL
apps suite runs from the worktree root as `uv run pytest apps/loops -q` — NEVER
`--directory apps/loops` (resolves a stale engine).

## EXECUTE YOURSELF — DO NOT DELEGATE. One response, foreground commands only — never
background a command and end your turn waiting; print mode is one-shot.

## Scope fence

You MAY edit ONLY: `apps/loops/src/loops/commands/store.py`,
`apps/loops/tests/test_store_migrate.py`, `apps/loops/pyproject.toml` (F6's two lines
only), `libs/custody/src/custody/signing.py` + `libs/custody/tests/**` (F3 only),
`libs/migrate/**` (F3's domain dissolution only). NOTHING else. Never touch `.loops/`,
`~/.local/state`, `~/.config/loops`; never run `sl`/`loops` emit against real stores.
STOP and report anything needing more.

## The fixes (all RULED; if a prescription conflicts with the code, STOP on that item)

**F1 — refuse positional-vs-flag disagreement (finding s4wp4-vertex-flag-silently-dropped
/ -discarded, both seats).** `_resolve_target(args.vertex, vertex_path)` returns the
positional vertex and silently drops `--vertex`. In `_run_migrate` ONLY (do not change
`_resolve_target` — read-only verbs legitimately use its precedence): when BOTH a
positional vertex target and `--vertex` are present and they resolve to different
vertices, REFUSE (exit 2, honor-or-refuse per `cli/refusals.py:3-5`, message naming both
spellings); when they agree, proceed. Test passing both (agreeing and disagreeing).

**F2 — `--vertex` becomes REQUIRED (finding s4wp4-flagless-default-unreachable, ruled).**
The flagless default resolves `<LOOPS_HOME>/.vertex`, whose dotfile suffix trips the .db
guard — the advertised default can never succeed, and only that accident stops an ambient
default from repointing the user's ROOT vertex from any cwd. Migration is a deliberate
ceremony: make `--vertex` required (argparse `required=True` or explicit refusal when
absent — match the file's idiom), delete the flagless fallback arm and fix the help text.
The vertex-shorthand positional still works WITH the flag under F1's agreement rule.

**F3 — arrival custody domain (finding s4wp4-attestations-signed-fact-domain; design
AMENDMENT #3, ruled).** Arrival attestation signatures currently mint under
`loops-fact-v1` because the CLI wires `custody.fact_signer_for`. Fix per custody's own
documented TICK/FACT domain discipline (read `libs/custody/src/custody/signing.py`'s
header first):
1. `custody/signing.py`: an arrival domain constant (spell it in the file's existing
   domain-string style, e.g. `loops-arrival-v1` — match the established format exactly)
   plus `arrival_signer_for` / `arrival_verifier_for` mirroring the fact pair's
   construction and key resolution precisely.
2. `_run_migrate` uses `arrival_signer_for`. The sidecar keeps taking an INJECTED signer
   (no migrate→custody import in src — Rule 11: migrate is record-layer, custody is
   surfacing; verify no such import exists after your change).
3. `libs/migrate`'s test-local `ARRIVAL_DOMAIN` constant + test verifier: dissolve
   against the product constant IF migrate tests may import custody under Rule 11's
   actual scope (read the rule test — does it cover tests/ or only src/?). If tests are
   covered by the rule, leave migrate's test-local constant but add the cross-check in
   APPS tests instead (apps may import custody): an e2e assertion that the migration
   report/genesis verify under `arrival_verifier_for` and are REFUSED by
   `fact_verifier_for` (the domain-separation pin, living where imports are legal).
   Report which arm you took and why.
4. custody tests: the new pair round-trips; fact and arrival domains mutually refuse
   (sign under one, verify under the other → False) — the separation pin at the source.

**F4 — signer guard probes capability, not existence (finding
s4wp4-signer-guard-overclaims-keys-dir, gate).** `fact_signer_for` (now
`arrival_signer_for`) returns non-None when the keys/ DIR exists even if the custodian's
own key is absent — the guard's message claims "no key for the custodian" on evidence
"keys dir exists". Gate's prescription, ruled: probe capability —
`if signer is None or signer(vertex_target.stem, "0"*64) is None: <refuse>` — making the
message true. Test: keys/bob/ present, no self-key → clean refusal, no traceback, nothing
persisted.

**F5 — multi-line refusal rendering (gate N1).** `_refuse_store` flattens
LegacySourceRefused's four structured lines into one. Gate's prescription:
`join_vertical` over `splitlines()` in `_refuse_store` (every other store refusal is
single-line, so nothing else changes). Test: the mixed-observer refusal renders its line
count on stderr.

**F6 — pyproject metadata honesty (gate N2, sized: no ship-path break — the root flat
wheel already carries migrate).** Two lines in `apps/loops/pyproject.toml`: `migrate` in
dependencies + `migrate = { workspace = true }` under `[tool.uv.sources]` — mirror how
the file declares its other workspace deps exactly.

**F7 — e2e test strength (reviewer N1).** The e2e asserts backend name only — a publish
to the WRONG location passes. Add: the post-migration `.vertex` parse's resolved store
location equals the minted target path; and open the migrated store through a real CLI
read path (`store stats` via main()) asserting the fact count.

**F8 — already-migrated guard (reviewer N2, ruled).** A second `migrate` run on a vertex
whose store clause already resolves to an arrival backend silently repoints it and
orphans the previous lineage. CLI pre-flight in `_run_migrate`: refuse (exit 2) when the
pre-edit `.vertex` store clause already names an arrival backend — message: already on an
arrival lineage; advisory prose: re-migration would orphan it; deliberate re-migration is
a slice-6 ceremony. Test.

## Acceptance bar

COMMIT FIRST (group sensibly; F3's custody change in its OWN commit), THEN break/restore
proofs (paste red → restore → green → empty production diff each):

1. F1: restore the silent precedence → the disagreement test fails.
2. F3: point the CLI back at fact_signer_for → the domain-separation pin fails.
3. F4: revert to the existence-only guard → the keys/bob test fails.
4. F8: drop the pre-flight → the already-migrated test fails.

Final checks, paste output: `uv run pytest apps/loops -q` (workspace-root form) — state
base and final counts (base 2533+1x); `uv run pytest libs/migrate libs/custody
tests/architecture -q` all green; `git status --short` clean but `.tmp/`; grep proof of
no migrate-src→custody import.

## Report format (stdout, one shot)

Per-item changes; evidence per proof; which F3(3) arm you took and why; both apps
counts; anything stopped on; found-but-left-alone; honest unverified list.
