# Slice 4 WP4 — the CLI surface: `loops store migrate` + verb dispositions staged

## Working directory — verify FIRST

    /Users/kaygee/Code/loops-wt/s4-wp4

Prefix EVERY command with `cd /Users/kaygee/Code/loops-wt/s4-wp4 && `. First:

    cd /Users/kaygee/Code/loops-wt/s4-wp4 && pwd && git branch --show-current && git log --oneline -1

Expected: branch `slice4/wp4` cut from main AFTER the WP3 merge — `libs/migrate` must
contain `sidecar.py` with `run_migration`; if absent, STOP and report (stale base). Test
env: `TMPDIR=/Users/kaygee/Code/loops-wt/s4-wp4/.tmp`, pytest `--basetemp=.../.tmp/pt`.

## EXECUTE YOURSELF — DO NOT DELEGATE. One response.

## Contract (ratified `design:arrival-break-slice4-migration-sidecar`, §F + §J.1 WP4)

WP4 adds the migration verb and STAGES the verb dispositions for slice 5 — it deletes
nothing. Read first: docs/scratch/arrival-break/slice4-design-proposal.md §F, §J.1 (WP4);
the sidecar surface `libs/migrate/src/migrate/sidecar.py` (`run_migration(source_path,
vertex_path, *, store_dir, signer, transform_rule, resume_target=None) ->
MigrationOutcome` — verify the exact signature in source, it is authoritative over this
prose) and `libs/migrate/src/migrate/refusals.py` (`MigrationRefused` family).

1. **`loops store migrate` verb** in `apps/loops/src/loops/commands/store.py`, mirroring
   the existing `rebirth` verb's shape (`:668-700`) for argument/flag idiom: positional
   source path, `--vertex` (default: resolve the store's `.vertex` the way neighbouring
   verbs do), `--rule {identity,ulid-migration}` (default ulid-migration, matching
   rebirth), `--resume TARGET` (maps to `resume_target=` — resuming is a deliberate act,
   never inferred), `--json` for the outcome. The custodian signer loads from the vertex's
   own key (`<vertex dir>/keys/ed25519.key`) — look at how `custody`/engine construct a
   Signer for the vertex self-observer and use the same path (engine's `Signer`; WP2's
   transform tests show the construction). NO new privileged paths: the verb is a thin
   wrapper over `run_migration`.
2. **Refusal rendering**: a `MigrationRefused` subclass surfacing at the CLI exits
   non-zero with the refusal's message on stderr — no traceback for typed refusals
   (match how neighbouring store verbs render refusals; find one precedent and mirror
   it). Untyped exceptions still traceback (they are bugs, not refusals).
3. **Verb dispositions STAGED, not executed** (§F): add a `# slice-5:` marker comment
   block at the TOP of `_run_absorb`'s genesis-mode helper and `_run_reanchor` quoting
   their ruled dispositions (absorb-genesis dissolves into the sidecar's mint; reanchor
   dies outright — no ceremony successor; ref the design fact). Do NOT change their
   behavior. `loops init`'s `_run_absorb([])` call site (`commands/init.py:472-480`) gets
   the same marker naming its mint-shaped successor. Three comments, zero behavior edits.
4. **Three-surface lockstep** (§F residue list): `STORE_SUBCOMMANDS` in
   `apps/loops/src/loops/cli/store_args.py:43` + the dispatcher in `commands/store.py` +
   the base-inspect `description=` prose (`commands/store.py:~1875-1885`) all gain
   `migrate` together — `tests/test_store_completion.py` is the parity net and must pass.
5. **Tests** (`apps/loops/tests/`): (a) end-to-end through the CLI: build a small
   synthetic legacy jsonl store + `.vertex` in tmp, run the verb via the app's test
   harness (find how neighbouring store-verb tests invoke commands and mirror it),
   assert exit 0, the target exists, and the descriptor updated; (b) refusal path: a
   source with a mixed-observer batch line → non-zero exit, refusal message on stderr,
   no traceback; (c) `--resume` requires its argument (deliberate act); (d) completion
   parity green. NOTE: apps tests must not touch the real state root — check whether
   apps/loops/tests already isolates XDG_STATE_HOME (conftest); if not, add the same
   autouse fixture libs/migrate/tests/conftest.py uses, scoped to your new test module.

## Scope fence

You MAY edit ONLY: `apps/loops/src/loops/commands/store.py`,
`apps/loops/src/loops/commands/init.py` (comment marker ONLY),
`apps/loops/src/loops/cli/store_args.py`, `apps/loops/tests/**` (new test module +
completion-parity expectations). NOTHING else — no libs/ edits of any kind, no other
apps files, no rule files (commands/store.py is already on Rule 15's exception list — a
migrate import grows no allowlist; verify, and STOP if that turns out false). Never touch
`.loops/`, never run `sl`/`loops` emit against real stores — CLI tests run against tmp
stores only. STOP and report anything needing more.

## Acceptance bar

COMMIT FIRST, then break/restore proofs (paste red → restore → green → empty production
diff each):

1. Remove `migrate` from STORE_SUBCOMMANDS only → the completion-parity test fails.
2. Make the CLI swallow the refusal and exit 0 → the refusal-path test fails.
3. Break the signer loading (wrong key path) → the end-to-end test fails with a signing
   error (paste it), proving the verb exercises real custody.

Final checks, paste output: `uv run pytest apps/loops -q` FROM THE WORKSPACE ROOT (never --directory for apps — friction:uv-directory-apps-resolves-stale-engine) green and RECONCILE the count
against a pre-change run on your base commit (apps suite is NOT in CI — the local run is
the gate; state both counts); `uv run pytest libs/migrate tests/architecture -q`
untouched-green; `git status --short` clean but `.tmp/`.

## Report (stdout, one shot)

Changes file by file; evidence per proof; both apps-suite counts; anything stopped on;
found-but-left-alone; honest unverified list.
