# Slice 4 WP4 gate report — `loops store migrate` verb

**Range**: `main..slice4/wp4` = 1 commit, `e1de3a4b` ("feat(cli): loops store migrate
verb + staged verb dispositions (slice4 WP4)").
**Gate worktree**: `/Users/kaygee/Code/loops-wt/s4-wp4-gate`, branch `slice4/wp4-gate`.
**Protocol**: `delegating-to-antigravity` §4, with the pipeline adaptations. Every
check below was re-run by the gate; nothing is quoted from the worker.

## VERDICT: **FIX ROUND** — 2 blocking, 3 non-blocking

The verb works. The oracle passes end to end through the *real installed CLI*, the
migration report verifies against the vertex's own declared key, the legacy source is
byte-identical, and the migrated store re-opens through three read verbs. The staged
dispositions are provably comment-only. Both blocking findings are in the CLI's own
guard/precedence layer, not in the sidecar, and both are small, contained fixes.

---

## Gate check 1 — suites and count reconciliation ✅

Workspace-root form throughout (never `--directory apps/loops`).

    uv run pytest apps/loops -q                        → 2533 passed, 1 xfailed
    uv run pytest apps/loops -q \
      --ignore=apps/loops/tests/test_store_migrate.py  → 2530 passed, 1 xfailed
    uv run pytest libs/migrate tests/architecture -q   → 159 passed

Delta is **exactly +3**, and all three are `test_store_migrate.py`. The claimed
base of 2530+1xfail is confirmed by construction rather than taken on trust (the
ignore-form reconciles against the same runner and the same venv, which a separate
base checkout would not). `libs/migrate` + `tests/architecture` untouched-green at
159. Re-run after a `uv sync --all-packages` (my `uv run --package loops` probe in
check 6 mutated the env): still 2533+1xfail / 159.

Rule 15's shrink-only allowlist already carries
`apps/loops/src/loops/commands/store.py`
(`tests/architecture/test_rule_15_apps_import_only_sdk_and_painted.py:43`), so the
`migrate` import grows no allowlist. The brief's precondition holds.

## Gate check 2 — the CLI oracle, independent and end-to-end ✅

I built my own synthetic legacy store (three jsonl fact rows, one carrying a fake
inner signature, uuid4-era ids) and a `.vertex` with a flat self-observer keypair,
then ran **the installed CLI binary** `.venv/bin/loops` — not the app's `main()`, not
the test harness. Both forms are reachable in this worktree; I exercised the
installed-CLI form for every oracle arm and `main()` only for the untyped-bug probe
in check 3 (which needs a monkeypatch).

    XDG_STATE_HOME=<tmp> .venv/bin/loops store migrate <src> --vertex <v> \
        --rule identity --json
    EXIT=0

| Claim | Verified how | Result |
|---|---|---|
| exit 0 | process exit status | ✅ 0 |
| `<lineage>.arrival` exists | `tp.name == lineage + ".arrival"` and `exists()` | ✅ |
| migration report verifies | re-canonicalised `{"body":…,"signer":…}` with `engine.arrival._canonical_bytes`, sha256, checked through `custody.fact_verifier_for(<v>)` | ✅ True |
| — negative control (bogus observer) | same sig attributed to `mallory` | ✅ False |
| — negative control (tampered digest) | same sig over `"0"*64` | ✅ False |
| `.vertex` store clause updated | re-read the file | ✅ `store "./01M1AR7RVKDTDBXDNAQNYFRTBN.arrival" backend="file"` |
| source byte-identical | sha256 before/after | ✅ unchanged |
| re-open through a read verb | `loops store stats` / `store verify` / `store ticks` against the migrated `.vertex` | ✅ all exit 0; stats reports `alice · 3 facts · 1 kinds · 0 ticks` |

`store verify` reports FACT SIGNATURES BROKEN on the migrated store — that is my
synthetic row's fake `"signature": "sig-a"` riding through verbatim, which is the
designed behaviour (migrated records are never re-signed), not a defect. It is
incidental confirmation that inner signatures ride verbatim.

Equivalence in the report: `matched: True, 3 → 3`. Custodian: `alice`.

I also ran the **default** rule (`ulid-migration`, no `--json`) on a second store:
exit 0, `transform_rule: ulid-migration`, equivalence 3 → 3, and the human render is
clean:

    ✓ legacy.jsonl → alice: migrated (rule=ulid-migration)
      lineage: 01M1ARJQ6R39ESWZ2J2Y3SG0M3 · head 3 25fa8dea4c9ee8ff…
      target: 01M1ARJQ6R39ESWZ2J2Y3SG0M3.arrival
      report: 01M1ARJQ6R39ESWZ2J2Y3SG0M3.migration-report.json

`--resume` is wired correctly, which nothing in the suite covers (the only test is
argparse arity). Re-running the completed oracle with
`--resume <lineage>.arrival` returns the *same* lineage and the *same* head at exit
0 — idempotent, and the `str`→`Path` coercion the sidecar signature allows works.

## Gate check 3 — refusal rendering and exit-code discipline ✅ (with N1)

My own mixed-observer source (one batch line spanning `alice` and `someone-else`),
run through the installed CLI:

    EXIT=2
    stdout: (empty)
    stderr: ✗ alice: Migration refused for source '…/legacy.jsonl' (legacy source
            defects found). The following source line(s) carry batch rows spanning
            more than one observer (GF-3 violation), … line 1: observers 'alice',
            'someone-else' Advisory: repair the source line(s) by hand …
    Traceback count in stderr: 0
    Artifacts left in the store dir: alice.vertex, keys, legacy.jsonl  (no .arrival,
      no report — the refusal fires in the inventory pass, before any target bytes)

**Exit code 2 matches the store-verb precedent.** `_refuse_store`
(`commands/store.py:37-49`) is the single shared renderer for every refusing path in
the module and returns 2 by construction; its docstring names that as the reason it
exists ("so the exit code cannot drift between subcommands"). The impl reused it
rather than inventing a code. Correct.

Untyped/error paths, all through the installed CLI:

| Input | Exit | stderr | Traceback |
|---|---|---|---|
| `--vertex <nonexistent>.vertex` | 1 | `…/nope.vertex does not exist` | no |
| `<nonexistent source>.jsonl` | 1 | `…/missing.jsonl does not exist` | no |
| `--vertex <x.db>` (not a `.vertex`) | 1 | `migrate requires a .vertex target — …` | no |
| vertex with **no** `keys/` dir | 2 | `✗ alice: no signing key for the vertex's self-observer …` | no |
| **simulated bug** (`run_migration` raises `RuntimeError`) | 1 | full stack to `boom()` | **yes** |

Note for the record: the brief anticipated the absent-vertex path tracebacking. It
does not — `FileNotFoundError`/`ValueError` are rendered cleanly at exit 1 by the
shared app boundary, which is the *right* answer and matches
`decision/design/store-verb-existence-exit-code-parity`. Genuine bugs still traceback
(row 5, verified by monkeypatching `migrate.sidecar.run_migration` and going through
`loops.main.main`). The contract holds; only its illustration in the brief was off.

## Gate check 4 — break/restore proofs, hand-verified ✅

Both re-run by me against the committed fix, with a restore and a re-green.

**(a) completion parity.** Removed `"migrate"` from `STORE_SUBCOMMANDS` only:

    test_store_completion.py::TestStoreSubcommandsParity::test_matches_run_store_dispatch_chain
    E  AssertionError: assert ('verify', 'r...) == ('verify', 'r...)
    E    At index 2 diff: 'migrate' != 'reanchor'
    1 failed, 8 passed
    → git restore; git diff --stat EMPTY; 9 passed

**(b) swallow the refusal.** Replaced the `except MigrationRefused` body with
`return 0`:

    test_store_migrate.py::TestMigrateEndToEnd::test_migrate_refuses_mixed_observer_batch_before_target_exists
    E  assert 0 != 0
    1 failed, 2 passed
    → git restore; git diff --stat EMPTY; 3 passed

Both proofs are real. The parity net in particular is a genuine three-surface
ratchet: it re-derives the dispatch chain from `store.py`'s source with a regex and
asserts tuple equality against `STORE_SUBCOMMANDS`, so order matters too.

## Gate check 5 — the comment-only claim ✅ (proved by AST, not by eye)

Reading a diff cannot prove "zero behaviour tokens changed", so I parsed both
revisions and compared ASTs (which carry no comments):

    functions ADDED:                 ['_run_migrate']
    functions REMOVED:               []
    functions whose AST CHANGED:     ['_dispatch_store']
      _run_reanchor:        AST identical base vs head -> True
      _absorb_genesis_mode: AST identical base vs head -> True
    init.py whole-module AST identical base vs head -> True

The only semantic changes in the range are the new `_run_migrate` and the two lines
`_dispatch_store` gained (the `migrate` route and the description prose). The three
staged markers are provably inert.

One thing worth confirming rather than assuming: the markers are placed *between*
the `def` line and the docstring. Comments are not statements, so the string literal
is still the first statement and still becomes `__doc__` — verified:

    _run_migrate:         docstring present -> True
    _run_reanchor:        docstring present -> True
    _absorb_genesis_mode: docstring present -> True

**Three-surface lockstep**, all naming `migrate`: `STORE_SUBCOMMANDS`
(`store_args.py:45`), the dispatcher (`store.py:1912`), the base-inspect description
prose (`store.py:2015`), plus the module header prose (`store_args.py:8`, "nine" →
"ten") and the parity test (`test_store_completion.py:46`). Green.

## Gate check 6 — the pyproject gap, sized ✅ (finding N2, smaller than feared)

Confirmed: `apps/loops/pyproject.toml` declares
`dependencies = ["lang","atoms","engine","custody","sign","store","painted"]` — no
`migrate`, and no `migrate = { workspace = true }` in `[tool.uv.sources]` — while
`commands/store.py` now imports `migrate.legacy_ids`, `migrate.refusals`,
`migrate.sidecar`.

**The shipped wheel is not affected.** I built it and looked inside:

    uv build --wheel  → strange_loops-0.11.0-py3-none-any.whl
    migrate/ modules in the wheel: 9 (sidecar.py, refusals.py, legacy_source.py, …)
    Requires-Dist: ckdl>=1.0, cryptography>=43, painted<0.14,>=0.12.1,
                   pyjwt[crypto]>=2.9, python-ulid>=3.0, rfc8785>=0.1.4,
                   typing-extensions>=4.0

WP1 already added `libs/migrate/src/migrate` to the root's `only-include` and wheel
`packages` (commit `6e39d84e`), and migrate's only third-party deps — `python-ulid`,
`ckdl` — are already in the root's hand-mirrored union. So `uv tool install .` and
the PyPI artifact both carry migrate and its deps. **The root flat-wheel registration
from WP1 is sufficient for the shipped wheel.** No ship-path break.

**Why the gap is invisible locally** — the exact mechanism, because "the workspace
venv works" is true for a reason worth naming. `uv run --package loops python -c
"import migrate"` *succeeds*, which looks like the gap is imaginary. It is not: uv
installs 7 packages for that env (migrate is not among them), but the root project's
editable install drops `_editable_impl_strange_loops.pth` into site-packages, and
that `.pth` appends **all nine** `libs/*/src` paths plus `apps/loops/src` to
`sys.path`. Every `--package loops` env in this repo therefore silently inherits
migrate from the root's editable install. The declaration gap cannot be detected by
any local run.

**Consequence, concretely.** It breaks exactly one path: a standalone
`pip install apps/loops` (or any consumer resolving the `loops` distribution's own
metadata), where `loops store migrate` would `ImportError` at
`from migrate.sidecar import run_migration`. That path is not shipped — `.github/
workflows/ci.yml:74` states apps/* is deliberately out of CI scope, and the release
ceremony publishes the root `strange-loops`. So this is **metadata honesty**, not a
live break: the workspace member's `pyproject.toml` no longer describes what its code
imports, and the next person who reads it will be misled.

**Prescription** (two lines, `apps/loops/pyproject.toml`):

    dependencies = ["lang", "atoms", "engine", "custody", "sign", "store",
                    "migrate", "painted"]
    ...
    [tool.uv.sources]
    migrate = { workspace = true }

## Gate check 7 — state-root hygiene ✅ (and the fixture is load-bearing)

Snapshot method: `ls ~/.local/state/loops/heads | sort | shasum`, before and after.

    BEFORE: count=267 sha=73284f6212b39afb139f23fa7c89a03698b3b98b
    (env -u XDG_STATE_HOME uv run pytest apps/loops/tests/test_store_migrate.py -q → 3 passed)
    AFTER:  count=267 sha=73284f6212b39afb139f23fa7c89a03698b3b98b
    → REAL STATE ROOT UNTOUCHED (listing byte-identical)

`state_root()` reads `XDG_STATE_HOME` at call time with no caching
(`arrival_head_attestation.py:598-613`), so the module's `monkeypatch.setenv` autouse
fixture is effective.

I also proved the fixture is doing work rather than being decorative, without
touching real state: disabled it and redirected `HOME` to a fake, so the
`~/.local/state` *fallback* branch resolved into tmp.

    fixture disabled  → 2 files under <fakehome>/.local/state/loops/heads:
                        01M1ARDGC2SV2Q9V5P9F84AE16.jsonl, bindings.jsonl
    fixture restored  → 0 new files
    git restore; git diff --stat EMPTY; 3 passed

Without the fixture, every run of this module would deposit a lineage journal **and**
a `bindings.jsonl` entry in the user's real state root.

## Gate check 8 — the signer path ✅

`custody.fact_signer_for(vertex_path)` resolves per observer:
`keys/<observer>/ed25519.key`, else the flat `keys/ed25519.key` **only** for the
self-observer (`signing.py:127, 141-142`). `run_migration`'s `custodian` defaults to
the vertex name, so `signer(custodian, digest)` resolves the vertex's own
self-observer key — the ratified custodian, not some other identity.

Probed rather than reasoned: I constructed the keys dir myself, migrated, and checked
the report signature through the vertex's declared-key registry.

    declared observer keys in .vertex: {'alice': 'SuCEUENJZNr8tuK8pXj3wLHxsaOT9MNWHOgjnkFnCNU='}
    report signer field: alice
    SIG VERIFIES against the .vertex's own declared key: True
    negative control (attribute sig to a bogus observer): False
    negative control (tampered digest):                   False

Signing domain is `FACT_DOMAIN` via `custody`'s signer closure; verification through
`fact_verifier_for` uses the same domain and the *declared* public key, so this is a
genuine round trip against the vertex's own registry, not a self-consistent loop
inside one helper.

---

# Findings

## BLOCKING

### B1 — `--vertex` is silently ignored under the vertex-first form, and the wrong vertex is migrated

`_run_migrate` resolves its target with
`_resolve_target(args.vertex, vertex_path)` (`store.py:786`). `_resolve_target`
returns `vertex_path` whenever it is non-`None` and **discards `file_arg` without a
word** (`store.py:276-277`). `vertex_path` is set by the vertex-first shorthand
`loops <vertex> store …` (`cli/app.py:461-463` → `_vertex_first` → `Invocation(
vertex_path=…)` → `views/store.py:38`).

So `loops aaa store migrate <src> --vertex bbb.vertex` migrates **aaa** and rewrites
**aaa**'s store clause, at exit 0, with no mention of `bbb`. Probed directly against
two throwaway vertices (I deliberately did **not** probe this through the real
CLI shorthand, because the only reachable vertex names are the user's registered
ones and the operation rewrites a real `.vertex`):

    _run_migrate([<a/legacy.jsonl>, "--vertex", <b/bbb.vertex>, "--rule", "identity",
                  "--json"], vertex_path=<a/aaa.vertex>)
    rc: 0
    aaa.vertex store clause: ['store "./01M1ARHZZ9WPC4ATGR5SQX32E1.arrival" backend="file"']
    bbb.vertex store clause: ['store "./legacy.jsonl"']          ← untouched

The precedence itself is the established store-verb pattern and is fine for
`verify`/`stats`/`ticks` — they are read-only and take a *positional* target, so
there is no second explicit naming to contradict. `migrate` is the first store verb
where this precedence redirects a **write**, and the first to name its target with an
explicit flag the user must type. Two targets are named and the one the user typed
loses, silently.

**Prescription** — refuse the conflict rather than picking a winner; that matches the
arc's refusal discipline and the "explicit over implicit" rule. In `_run_migrate`,
before `_resolve_target`:

```python
if vertex_path is not None and args.vertex is not None:
    return _refuse_store(
        f"two targets named: the vertex-first form says {vertex_path.name} "
        f"and --vertex says {args.vertex} — name one",
        label="store migrate",
    )
```

Cheaper alternative if the arbiter prefers: let `args.vertex` win when explicitly
given. I recommend refusal — a mis-targeted migration rewrites a descriptor, and
"which one did it pick" is not a question the operator should have to ask.

### B2 — the `signer is None` guard overclaims; a partially-provisioned `keys/` dir tracebacks at mint

`store.py:797-804` refuses when `fact_signer_for(vertex_target)` returns `None`,
with the message *"no signing key for the vertex's self-observer"*. But
`fact_signer_for` returns `None` only when the `keys/` **directory** is absent
(`signing.py:122-124`); it returns a working multi-observer signer whenever `keys/`
exists, even if that directory holds no key for the self-observer. The guard's
evidence is "no keys dir"; its claim is "no key for the custodian". That is exactly
the claim-scoping failure `decision:practice/scope-the-claim-over-widen-the-detection`
names.

Reachable and ordinary: a per-observer key layout where `keys/bob/ed25519.key` exists
but the vertex's own key does not (a partially provisioned vertex, or one whose
custodian key lives elsewhere). Probed through the installed CLI:

    EXIT=1
    Traceback (most recent call last):
      …
      File ".../commands/store.py", line 813, in _run_migrate
        outcome = run_migration(
      File ".../migrate/sidecar.py", line 784, in run_migration
        current_head = ledger.mint(mint_options)
      …
      File ".../engine/arrival.py", line 923, in mint
        raise GenesisRefused(
    engine.arrival.GenesisRefused: genesis for lineage 01M1ARFCPSP2TBZH090PDKP7YK is
    unsigned — genesis is the lineage's attestation root and observer 'alice'
    produced no signature

Mitigating, and I want it on the record because it bounds the severity: **nothing is
persisted.** No `.arrival`, no report, no head journal entry, and the `.vertex` store
clause is untouched — the genesis refusal fires before any bytes land. The operator
also does get an accurate sentence, at the bottom of a stack trace.

Strictly, the impl met the letter of the brief: `GenesisRefused` is an `engine`
refusal, not a `MigrationRefused` subclass, and untyped exceptions are meant to
traceback. But this is an operator condition, not a bug, and the guard that exists
specifically to catch it does not.

**Prescription** — check capability, not existence. The signer closure is pure and
side-effect-free, so probing it costs nothing:

```python
signer = fact_signer_for(vertex_target)
custodian = vertex_target.stem
if signer is None or signer(custodian, "0" * 64) is None:
    return _refuse_store(
        "no signing key for the vertex's self-observer — migration must sign "
        "the custodian genesis and key introductions "
        "(loops add <vertex> observer --keygen)",
        label=vertex_target.stem,
    )
```

That leaves the message exactly as written and makes it true. Wrapping
`GenesisRefused` into `MissingCustodianKeyRefused` inside the sidecar would also
work, but that is outside WP4's fence and the guard would still be overclaiming.

## NON-BLOCKING

### N1 — multi-line refusals are flattened to a single line

The sidecar's refusal prose is deliberately structured. `LegacySourceRefused.__str__`
returns four lines — what happened / which source lines / the advisory:

    "Migration refused for source '/x/legacy.jsonl' (legacy source defects found).\n
     The following source line(s) carry batch rows spanning more than one observer
     (GF-3 violation), which cannot map to a single Arrival record:\n
       line 1: observers 'alice', 'someone-else'\n
     Advisory: repair the source line(s) by hand or re-run migration after a ruled
     re-ceremony."

`_refuse_store` renders it as one `Block.text(head, Style())`, and the CLI emits a
single line (`wc -l` on captured stderr: **1**). All the information survives, as a
wall of text; per-line structure and the indented `line 1:` enumeration do not.

Every other store refusal is single-line, which is why this never showed before.
Migrate is the first verb whose refusals carry structure.

**Prescription** — `join_vertical` the split in `_refuse_store` (in-fence,
`commands/store.py`); single-line callers render identically, so no other verb
changes:

```python
lines = str(msg).splitlines() or [""]
head = f"✗ {label}: {lines[0]}" if label else f"✗ {lines[0]}"
paint(join_vertical(*(Block.text(ln, Style()) for ln in [head, *lines[1:]])),
      file=sys.stderr)
```

### N2 — `apps/loops/pyproject.toml` does not declare `migrate`

Full sizing in gate check 6. Shipped wheel unaffected; local runs masked by the
root's editable `.pth`; the real cost is that the workspace member's metadata no
longer describes its imports. Two-line fix given above.

### N3 — no impl report at the briefed path

`docs/scratch/arrival-break/s4-wp4-impl-report.md` does not exist on the branch (nor
in the worker's worktree). The commit message is unusually complete and carried
enough to gate against, and the worker's scope held exactly (`git status --short` in
`/Users/kaygee/Code/loops-wt/s4-wp4` is clean but `.tmp/`; only the five fenced files
in the diff), so nothing was lost — but the per-WP receipt is missing from the arc's
paper trail.

### N4 (note, not a finding) — `--resume` has arity coverage only

`test_resume_requires_its_argument` asserts argparse rejects a bare `--resume`;
nothing exercises the flag's actual wiring. I verified it by hand (idempotent re-run
against a completed target returns the same lineage and head at exit 0), so it works
today. A resume test needs an interrupted migration to be worth writing, which is
sidecar territory; flagging it so it is a deliberate omission rather than an
oversight.

---

## Scope, cruft, hygiene

- Worker's worktree touched read-only. `git status --short` there: `?? .tmp/` only.
- Diff touches exactly the five fenced files. No `libs/` edits, no rule files, no
  other apps files.
- No `.loops/` writes; every probe ran against tmp stores with `XDG_STATE_HOME`
  redirected. Real `~/.local/state/loops/heads` verified byte-identical
  (267 entries, same listing hash) after the gate.
- All break/restore arms ran against the **committed** fix; every restore left
  `git diff --stat` empty and the suite green.
- Gate worktree clean but `.tmp/` (not committed).

## What I could not verify

- The `pip install apps/loops` break in N2 is reasoned from the wheel metadata and
  the `.pth` mechanism, not executed — building and installing the apps wheel into a
  clean interpreter would settle it, and I judged the shipped-wheel evidence
  sufficient to size the finding.
- B1 was probed at the `_run_migrate` boundary, not through the real
  `loops <vertex> store migrate` shorthand, because that form can only name the
  user's registered vertices and the operation rewrites a live `.vertex`. The
  dispatch chain to `vertex_path` is read from source (`app.py:461-463`,
  `_vertex_first`, `views/store.py:38`) and is unambiguous.

---

# Round 2 — fix round 1 re-check

**Range**: `44a14cea` (custody: arrival signing domain + verifier) and `df17edd3`
(CLI F1–F8), merged into `slice4/wp4-gate` at `c4743d58`.

## VERDICT: **FIX ROUND** — all five open findings verifiably FIXED, one NEW blocking regression

Every one of the five open WP4 findings is fixed, and I verified each by re-running my
own round-1 probe rather than by reading the tests. The new blocking item is a defect
this round *introduced*, not a failure of any of the five: the F3 dissolution made
`libs/migrate`'s tests import `custody` without declaring it, so migrate's test suite
is no longer independently installable.

### N3 withdrawn

The impl report exists — committed on `main` at `a8d89d45`
(`docs/scratch/arrival-break/s4-wp4-impl-report.md`); the impl filed to the main
checkout, not the slice branch. I looked only on the branch and in the worker's
worktree. My round-1 N3 was wrong; the arc's paper trail is complete.

## Suites and reconciliation ✅

    uv run pytest apps/loops -q                                  → 2538 passed, 1 xfailed
    uv run pytest libs/custody libs/migrate tests/architecture -q → 178 passed

Base was 2533 + 1 xfailed; delta is **+5**, and the five are exactly the new cases in
`test_store_migrate.py` (positional/flag agreeing, positional/flag disagreeing, required
flag, keys/bob capability, already-migrated). That module now runs 8. Split of the 178:
libs/custody 19 (was 13, +6 arrival cases), libs/migrate 60, tests/architecture 99.

Rule checks the arbiter asked for, both confirmed:

- **No migrate-src → custody import.** `grep -rn custody libs/migrate/src/` returns one
  hit and it is prose in `transform.py:30`'s docstring, not an import. Rule 11 clean.
- **Rule 4's migrate row unchanged** — still `{engine, lang}`. Neither rule file was
  touched by either commit (`git diff --stat e1de3a4b..df17edd3 -- tests/` is empty).

Both rules scope to `root/src/` only (`_src_py_files`, `_helpers.py:152-157`), so the
worker's F3(3) arm — dissolving migrate's test-local `ARRIVAL_DOMAIN` against the
product constant — is legal under the rules as written. That reading is correct. What
it missed is the packaging consequence, below.

## Re-check 1 — my B1 probe ✅ FIXED

Same probe as round 1, two throwaway vertices:

    positional aaa + --vertex bbb  → rc 2
      ✗ store migrate: positional vertex target '…/a/aaa.vertex' conflicts with
        --vertex '…/b/bbb.vertex' — targets resolve to different vertices
        (aaa.vertex != bbb.vertex)
      aaa store clause: 'store "./legacy.jsonl"'   ← unchanged
      bbb store clause: 'store "./legacy.jsonl"'   ← unchanged
      *.arrival in a/: []   in b/: []

    positional aaa + --vertex aaa  → rc 0, aaa republished onto the minted lineage

The refusal names both spellings and the resolved basenames. Nothing migrated, nothing
created. Agreement proceeds. Exactly the ruled behaviour.

Minor ordering note (not a finding): when the `--vertex` target does not exist,
`_resolve_target` raises `FileNotFoundError` before the conflict check can run, so the
user sees "ghost.vertex does not exist" rather than the conflict message. That is the
right error and it renders cleanly at exit 1 through the app boundary.

## Re-check 2 — reviewer's B2, `--vertex` required ✅ FIXED

    loops store migrate <src>          (no flag)
    EXIT=2
    usage: loops store migrate [-h] --vertex VERTEX [--rule {identity,ulid-migration}]
                               [--resume TARGET] [--json] source
    loops store migrate: error: the following arguments are required: --vertex
    Traceback count: 0

`--vertex VERTEX` appears unbracketed in the usage line (required), and the misleading
"default: resolve like other store verbs" help string is gone from the source. Clean
exit 2, no traceback.

Scoping one thing so it is not mistaken for a regression: `loops store migrate -h`
prints the *store*-level help, not migrate's own parser help. That is painted's
intercepted `-h` walk and it behaves identically for `loops store rebirth -h` (verified
side by side) — pre-existing, documented in `store_args.py`'s module docstring, and not
introduced here. Migrate's real flag help is reachable through the usage line above.

## Re-check 3 — AMENDMENT #3, the heavy item ✅ FIXED (with a non-blocking structural note)

**The domain constant.** `ARRIVAL_DOMAIN = "loops-arrival-v1"` sits beside
`TICK_DOMAIN = "loops-tick-v1"` and `FACT_DOMAIN = "loops-fact-v1"`, matching the
established `loops-<layer>-v1` spelling exactly, and it lives in custody — which is
where the module header says domain constants belong ("the domain-separation constant
lives HERE, not in libs/sign … and not in engine"). Correct on both counts.

**Key resolution mirrors the fact pair exactly.** Reading two near-identical functions
side by side is not proof, so I parsed both and compared their ASTs with the domain
constant normalised to a placeholder and docstrings stripped:

    fact_signer_for   vs arrival_signer_for   : AST-identical modulo domain -> True
    fact_verifier_for vs arrival_verifier_for : AST-identical modulo domain -> True

So there is no divergent resolution path today: the per-observer layout, the
self-observer-only flat fallback, the empty-observer and `..` traversal guards, the
per-observer cache, and the malformed-declared-key skip are all bit-identical.

**Live probe, both directions.** I migrated a fresh store through the installed CLI and
checked every attestation the sidecar mints:

    ARRIVAL_DOMAIN = 'loops-arrival-v1' | FACT_DOMAIN = 'loops-fact-v1'

    -- MIGRATION REPORT --
      arrival_verifier_for -> True     fact_verifier_for -> False
    -- GENESIS RECORD (kind=genesis, observer=alice) --
      arrival_verifier_for -> True     fact_verifier_for -> False

This is the exact inversion of my round-1 oracle, which verified the report through
`fact_verifier_for` and got `True`. It now returns `False`, as required.

I also built a **two-observer** store (flat self-key for alice, `keys/bob/` for bob) so
a key-introduction record would actually be minted, since the report and genesis alone
would not have covered that class:

      @0 kind=genesis  observer=alice  arrival=True  fact=False
      @1 kind=key      observer=alice  arrival=True  fact=False

All three attestation classes — genesis, key-introduction, migration report — now carry
`loops-arrival-v1`.

**Custody's own mutual-refusal pin, break/restore verified** (re-check 3's second arm):

    baseline: libs/custody 19 passed
    BREAK: ARRIVAL_DOMAIN = "loops-arrival-v1" → "loops-fact-v1"
      FAILED test_signing.py::TestArrivalSigner::test_fact_and_arrival_mutually_refuse
      E  assert fact_verifier("x", arr_sig, digest) is False
      E  AssertionError: assert True is False
      1 failed, 18 passed
    RESTORE: git diff --stat EMPTY; 19 passed

The pin is real and it fires at the source, in both directions (the test asserts all
four cells of the two-by-two, not just one).

### NON-BLOCKING N5 — the arrival pair is a copy of the fact pair, not a composition

The AST-identity above is what the ruling asked for, and it is also the finding: the
two pairs are identical because one was **duplicated** from the other. Four functions
now exist where two parameterised ones would do, and "identical today" is precisely the
state that decays — the twin-resolvers hazard is not avoided by the copy, it is created
by it and merely not yet realised.

The evidence that erosion has already begun is in the copies themselves: `fact_signer_for`
carries the rationale for its guards —

    # An empty observer must never sign: ``keys_root / ""`` collapses
    # to the flat layout, which would mint the VERTEX key's authorship
    # claim for an anonymous writer. Same guard for path traversal —
    # an observer name is a key, not a path expression.

and `# exists → pure load` on the cache line. `arrival_signer_for` has the *code* for
both guards and **neither comment**. A future reader of the arrival copy sees a guard
with no reason attached, which is how the copy loses it.

This is the dissolution test: the arrival signer is the fact signer with a different
domain constant. Prescription — collapse to one private resolver each and keep the four
public names as thin wrappers, a pure refactor with the existing 19 custody tests plus
the new mutual-refusal pin as the net:

```python
def _observer_signer_for(vertex_path: Path, *, domain: str): ...   # today's body
def fact_signer_for(v):    return _observer_signer_for(v, domain=FACT_DOMAIN)
def arrival_signer_for(v): return _observer_signer_for(v, domain=ARRIVAL_DOMAIN)
```

If the duplication is deliberate, the ratchet alternative is to make the mirror
enumerable rather than hoped-for: a rule test asserting the `*_signer_for` /
`*_verifier_for` families are AST-identical modulo their domain constant — which is
the check I ran by hand above and would take about fifteen lines.

### NON-BLOCKING N6 — the new pair is not exported from the package

`fact_signer_for`, `fact_verifier_for`, `tick_signer_for` and `tick_verifier_for` are
all re-exported from `custody/__init__.py` and listed in `__all__`.
`arrival_signer_for` and `arrival_verifier_for` are not. The consequence is visible at
the call site: every other custody use in the app reads `from custody import ...`
(eleven of them across `emit.py`, `sync.py`, `seal.py`, `add.py`, `store.py`), while the
new one reads `from custody.signing import arrival_signer_for` (`store.py:829`) — the
only submodule-reaching custody import in the app. Residue from the new pair, one line
in `__init__.py` plus one in `__all__`.

## Re-check 4 — my B2 probe ✅ FIXED

Same construction as round 1: `keys/` exists holding only `keys/bob/ed25519.key`, no key
for the self-observer.

    EXIT=2
    ✗ alice: no signing key for the vertex's self-observer — migration must sign the
      custodian genesis and key introductions (loops add <vertex> observer --keygen)
    Traceback count: 0
    .arrival / .migration-report.json created: 0
    head journals written: 0
    store clause: 'store "./legacy.jsonl"'   ← untouched

The guard now probes capability (`signer(vertex_target.stem, "0"*64) is None`), so the
message is true of the evidence. The `GenesisRefused` traceback is gone.

## Re-check 5 — F5, F6, F7, F8

**F5 — multi-line refusal ✅.** Same mixed-observer source as round 1:

    stderr line count: 4   (round 1: 1)
    ✗ alice: Migration refused for source '…/legacy.jsonl' (legacy source defects found).
    The following source line(s) carry batch rows spanning more than one observer
    (GF-3 violation), which cannot map to a single Arrival record:
      line 1: observers 'alice', 'someone-else'
    Advisory: repair the source line(s) by hand or re-run migration after a ruled re-ceremony.

The structure survives, including the indented enumeration. `_refuse_store` still
returns 2 and single-line callers render unchanged.

**F6 — pyproject idiom ✅.** `"migrate"` added to `dependencies` and
`migrate = { workspace = true }` added under `[tool.uv.sources]`, both matching the
file's existing form exactly. Cosmetic nit only: `migrate` was appended *after*
`painted`, so the list now reads `…, "store", "painted", "migrate"` where every other
workspace dep precedes the one external dep. Ordering, nothing more.

**F7 — e2e strength ✅, verified by the mutation my round-1 report said the old
assertion would miss.** The test now pins `resolve_canonical_path(vpath) == target_path`
and opens the store through `main([str(vpath), "store", "stats", "--json"])`, asserting
the fact count.

    baseline: 8 passed
    BREAK: publish target_location="./WRONG-NOT-THE-TARGET.arrival" (backend still "file")
      FAILED test_migrate_through_cli_mints_lineage_and_updates_descriptor
      E  assert PosixPath('…/WRONG-NOT-THE-TARGET.arrival')
              == PosixPath('…/01M1AV7WG6N74HFMG75DD8V3G2.arrival')
      1 failed, 7 passed
    RESTORE: git diff --stat EMPTY; 8 passed

That mutation passed the old backend-name-only assertion. It does not pass now.

**F8 — already-migrated guard ✅.** Second migrate on the vertex republished in
re-check 1:

    EXIT=2
    ✗ aaa: already on an arrival lineage (01M1AV4QE15V17H33KN0Q1QAFX.arrival) —
      re-migration would orphan it; deliberate re-migration is a slice-6 ceremony
    Traceback count: 0
    .arrival files in the store dir: 1        store clause: unchanged

### NON-BLOCKING N7 — F8's guard has a bare `except` that fails open, and a dead disjunct

Two things in the seven lines of the F8 pre-flight.

*The bare except.* `parse_vertex_file` is wrapped in `except Exception: pre_ast = None`,
and `None` skips the guard entirely — a guard that fails open on any parse failure. This
is the anti-pattern the arc already ruled on and fixed in WP3
(`s4wp3-report-verifier-retypes-unopenable`: bare `except Exception` in a newly written
verifier), reappearing in a newly written guard one work package later.

I sized it rather than asserting it is harmless. A `.vertex` that fails to parse but
whose store clause says `./x.arrival` does bypass the guard — but it then fails again
inside the sidecar's own `parse_vertex_file` with `lang.errors.ParseError`, exit 1, and
nothing is persisted (0 artifacts, 0 journals). So the cost is a traceback three frames
deeper instead of a clean refusal, not a wrong migration. Prescription: drop the
try/except (a malformed descriptor is an error either way), or catch
`lang.errors.ParseError` explicitly and route it through `_refuse_store`.

*The dead disjunct.* The condition is

```python
if canonical_mode(pre_ast.store) == "arrival" or (
    pre_ast.store_backend is not None and pre_ast.store.suffix == ".arrival"
):
```

but `ARRIVAL_SUFFIX == ".arrival"` and `canonical_mode` returns `"arrival"` **exactly**
when the suffix is `ARRIVAL_SUFFIX` — so the second arm can never be reached when the
first is False. Verified:

    ARRIVAL_SUFFIX = '.arrival';  canonical_mode("x.arrival") = arrival
    second disjunct reachable? False

`canonical_mode`'s own docstring warns about this shape: "A family of per-mode booleans
is how a two-mode architecture creeps back in, so there isn't one." Drop the disjunct.

## Re-check 6 — break/restore, hand-verified ✅ (four, not two)

The arbiter asked for two. The amendment warranted more, so I ran four; all four went
red on my own break, restored to an empty production diff, and re-greened.

| # | What I broke | Test that went red |
|---|---|---|
| P1 | `ARRIVAL_DOMAIN` string → `"loops-fact-v1"` | `custody …::test_fact_and_arrival_mutually_refuse` |
| P2 | CLI back to `fact_signer_for` | `apps …::test_migrate_through_cli_mints_lineage_and_updates_descriptor` (arrival verify → False) |
| P3 | F1 silent precedence restored | `apps …::test_migrate_positional_and_flag_disagreeing_refuses` |
| P4 | publish to `./WRONG-NOT-THE-TARGET.arrival` | same e2e, on the F7 location pin |

P3 is worth one extra line: with the silent precedence restored, the failing test's
captured stdout shows `✓ legacy.jsonl → alice: migrated` — the round-1 bug reproducing
exactly as described, which is the cleanest confirmation that F1's test targets the real
defect and not a proxy for it.

## Re-check 7 — state-root hygiene ✅

    BEFORE count=268 sha=bf1ef11538c59f45f153b1af8dc3dfabc3f71981
    (env -u XDG_STATE_HOME; test_store_migrate.py + libs/custody → 27 passed)
    AFTER  count=268 sha=bf1ef11538c59f45f153b1af8dc3dfabc3f71981
    → REAL STATE ROOT UNTOUCHED

The five new apps cases and the six new custody cases all stay inside their tmp state
roots. (The 267→268 drift since round 1 happened outside my measurement window; both
of my before/after pairs are internally identical.)

## Re-check 8 — scope ✅

Exactly two commits. Files touched across both:

    apps/loops/pyproject.toml
    apps/loops/src/loops/commands/store.py
    apps/loops/tests/test_store_migrate.py
    libs/custody/src/custody/signing.py
    libs/custody/tests/test_signing.py
    libs/migrate/tests/test_sidecar.py
    libs/migrate/tests/test_transform.py

All inside the fix brief's fence. One note against the arbiter's phrasing: the custody
commit was expected to touch "only signing.py + custody tests", and it also touches the
two `libs/migrate/tests/` files. That is correct — it is F3(3)'s dissolution arm, which
the brief explicitly permitted under `libs/migrate/**` — but it is where the new
blocking finding lives. Gate worktree clean but `.tmp/`.

---

# Round 2 findings

## BLOCKING

### B3 — F3's dissolution made `libs/migrate`'s tests import `custody` without declaring it, and migrate's tests are no longer independently installable

`libs/migrate/tests/test_sidecar.py` and `test_transform.py` now do
`from custody.signing import ARRIVAL_DOMAIN` (commit `44a14cea`), but
`libs/migrate/pyproject.toml` declares neither `custody` in `dependencies` nor in
`[dependency-groups] dev`, and has no `custody = { workspace = true }` in
`[tool.uv.sources]`.

This is invisible in the workspace venv for exactly the reason I documented for N2 in
round 1 — `_editable_impl_strange_loops.pth` appends all nine `libs/*/src` paths to
`sys.path`, so any import of any lib succeeds here. **It is the same undeclared-import
defect F6 fixed for `apps/loops`, reintroduced in `libs/migrate`'s test tree by the same
fix round.**

Unlike N2, this one has a live consumer. CI's `test-packages` matrix job runs
per-package, in a fresh checkout with no root install:

    uv run --package ${{ matrix.package }} pytest "libs/${{ matrix.package }}/tests" -q
    — .github/workflows/ci.yml:105-111

Reproduced by pointing uv at a fresh environment
(`UV_PROJECT_ENVIRONMENT=.tmp/freshvenv`), which is what CI gets:

    libs/migrate/tests/test_transform.py:61: from custody.signing import ARRIVAL_DOMAIN
    E   ModuleNotFoundError: No module named 'custody'

**Scoping the claim, because it matters here.** This round does **not** newly break a
green job. I ran the identical fresh-env probe on the pre-fix base `e1de3a4b` and the
migrate job was *already* failing collection, for a different undeclared dependency:

    base e1de3a4b:  1 collection error
      libs/migrate/tests/test_sidecar.py:27: from sign import ed25519
      E   ModuleNotFoundError: No module named 'sign'

    after the fix round: 2 collection errors — that pre-existing `sign` one, plus the
      new `custody` one

So `sign` is pre-existing (an earlier WP's residue, outside WP4's fence) and `custody`
is this round's. I am calling it blocking anyway: the fix is two lines, it is in-fence,
it is caused by this round, and it violates the discipline the same round's F6
established one directory over. Letting it ride means slice 5 inherits a second
undeclared cross-lib dependency in a suite the arc's "CI 11/11 green" milestone depends
on.

**Prescription** — `libs/migrate/pyproject.toml`. Custody is a *test-only* dependency of
migrate (src must never import it, Rule 11), so it belongs in the dev group, not
`dependencies`:

```toml
[dependency-groups]
dev = [
    "custody",
    "sign",          # pre-existing gap — see below
    "hypothesis>=6.100",
    ...
]

[tool.uv.sources]
engine = { workspace = true }
store = { workspace = true }
lang = { workspace = true }
custody = { workspace = true }
sign = { workspace = true }
```

I recommend fixing `sign` in the same change even though it is outside WP4's fence:
it is one more line in the same list, and declaring only `custody` leaves the migrate
CI job red for the other reason — a half-fix that looks like a fix. Flagging rather
than assuming: if the arbiter would rather keep the fence clean, `sign` should become
its own item so it is not lost.

*Alternative, if declaring custody in migrate is unwanted:* take F3(3)'s other arm —
restore migrate's test-local constant and keep the cross-check only in apps tests, where
the import is already legal and already exists. That arm is already carrying the
domain-separation pin (verified in re-check 3), so nothing would be lost but the
single-sourcing of the string.

## NON-BLOCKING (round 2)

- **N5** — arrival pair duplicated rather than composed; guard rationale comments
  dropped in the copies. Prescription: one parameterised resolver each, or an
  AST-identity ratchet test.
- **N6** — `arrival_signer_for` / `arrival_verifier_for` missing from
  `custody/__init__.py` and `__all__`; the only submodule-reaching custody import in the
  app.
- **N7** — F8's bare `except Exception` fails the guard open (bounded: the sidecar's own
  parse still stops it, nothing persists); and its second disjunct is unreachable dead
  code.
- **F6 nit** — `"migrate"` appended after `"painted"`, breaking the
  workspace-deps-then-external ordering.

## Round-1 findings: disposition

| Finding | Status | Fixing commit | Verified by |
|---|---|---|---|
| `s4wp4-vertex-flag-silently-discarded` (= `-dropped`, same defect, both seats) | **fixed** | `df17edd3` | re-check 1 probe + P3 break/restore |
| `s4wp4-signer-guard-overclaims-keys-dir` | **fixed** | `df17edd3` | re-check 4 probe |
| `s4wp4-attestations-signed-fact-domain` | **fixed** | `44a14cea` + `df17edd3` | re-check 3 live probe (both directions, three attestation classes) + P1/P2 |
| `s4wp4-flagless-default-unreachable` | **fixed** | `df17edd3` | re-check 2 |
| N1 (multi-line refusal) / N2 (apps pyproject) | fixed | `df17edd3` | F5 / F6 above |
| N3 (missing impl report) | **withdrawn** | — | exists on main at `a8d89d45` |

## What I could not verify

- The `sign` gap in B3 is pre-existing and I did not trace which work package introduced
  it; I established only that it predates `e1de3a4b`.
- I did not run the real CI workflow, only reproduced its per-package install form
  locally via `UV_PROJECT_ENVIRONMENT`. The failure mode is a module-resolution one, so
  the local reproduction should be faithful, but a CI run is the only proof.

---

# Round 3 — fix round 2 re-check (closing)

**Range**: `e1edaa24` (migrate dev deps), `b226adce` (compose by domain), `042f9504`
(package-root exports), `080ff470` (guard honesty + dead disjunct + pyproject ordering),
merged into `slice4/wp4-gate` at `4835e459`.

## VERDICT: **PASS** — WP4's gate closes

All four items land, every round-2 finding is fixed, and no regression appeared in the
behaviour the earlier rounds established. Nothing new found.

## Re-check 1 — B3, with my own fresh-env method ✅ FIXED, and more completely than asked

`libs/migrate/pyproject.toml` gains `custody` and `sign` in the **dev** group (correct
placement — they are test-only; src must never import them under Rule 11) plus both in
`[tool.uv.sources]`, with a comment naming why they are there.

Re-running the exact probe that produced the finding — a fresh environment via
`UV_PROJECT_ENVIRONMENT`, which is what CI's per-package matrix gets:

    uv run --package migrate pytest libs/migrate/tests -q
    Creating virtual environment at: .tmp/freshvenv
    Installed 26 packages in 17ms
    60 passed in 1.49s

Both causes are gone: the `custody` one this arc introduced **and** the pre-existing
`sign` one that predated `e1de3a4b`. The migrate CI job goes from failing collection to
green, which is a better outcome than the finding strictly required — I had flagged
`sign` as out-of-fence and recommended taking it anyway; the worker took it.

Rule 11 still clean at the source:

    grep -rnE "^\s*(from|import)\s+(custody|sign)\b" libs/migrate/src/
    → NONE — src imports neither custody nor sign

## Re-check 2 — F2, behaviour-preserving composition ✅

**The shape.** `_scoped_signer_for(vertex_path, domain)` and
`_scoped_verifier_for(vertex_path, domain)` now hold the one copy of each resolution
path; `fact_signer_for`, `arrival_signer_for`, `fact_verifier_for` and
`arrival_verifier_for` are one-line wrappers that pass their domain constant. Four
public names, two implementations — the duplication N5 named is gone rather than
documented, and there is no longer a second resolver that *can* drift.

**The comments came with it.** This was the specific erosion I flagged, so I checked the
shared body rather than trusting the diff summary. `_scoped_signer_for` carries all
three rationale comments the arrival copy had dropped:

    # An empty observer must never sign: ``keys_root / ""`` collapses
    # to the flat layout, which would mint the VERTEX key's authorship
    # claim for an anonymous writer. Same guard for path traversal —
    # an observer name is a key, not a path expression.
    ...
                key_dir = keys_root  # flat delta-2 layout = self-observer
    ...
        cache[observer] = ed25519.load_or_generate(key_dir)  # exists → pure load

and `_scoped_verifier_for` keeps the malformed-declared-key note. The full per-observer
resolution contracts stay on the public wrappers, where a caller reads them.

**Behaviour unchanged at HEAD.** I re-ran the round-2 three-class live probe, rebuilding
the two-observer store (flat self-key alice, `keys/bob/`) so a key-introduction record
would actually be minted:

    package-root import of the arrival pair: OK | 'loops-arrival-v1' 'loops-fact-v1'

    -- LEDGER RECORDS --
      @0 kind=genesis    observer=alice  arrival=True   fact=False
      @1 kind=key        observer=alice  arrival=True   fact=False
    -- MIGRATION REPORT --
      arrival=True  fact=False

Identical to round 2 in every cell. Domain separation survived the refactor across all
three attestation classes, both directions.

## Re-check 3 — F4, guard honesty ✅ FIXED

The bare `except Exception: pre_ast = None` is replaced by `except ParseError` returning
a typed refusal, and the unreachable second disjunct is deleted — the condition is now
just `canonical_mode(pre_ast.store) == "arrival"`. (`ParseError` is a real `lang` export,
listed in its `__all__`, not an accidental re-export.)

Re-running my round-2 probe, which then produced a three-frame `lang.errors.ParseError`
traceback at exit 1:

    EXIT=2
    ✗ broken: the vertex file cannot be parsed: broken.vertex:1: Unexpected token, expected node
    Traceback count: 0
    artifacts: 0 | journals: 0

The guard no longer fails open — it refuses, at the CLI, in the module's own refusal
idiom, naming the parse error. Exit 2 rather than the previous exit 1, which is right:
this is a refusal, not a crash.

Regression sanity on the two behaviours the refactor touched around:

    keys/bob, no self-key → EXIT=2, clean refusal, 0 tracebacks
    second migrate        → EXIT=2, "already on an arrival lineage (…) — re-migration
                            would orphan it; deliberate re-migration is a slice-6 ceremony"

## Re-check 4 — break/restore, hand-verified ✅

The mutation that tests whether the composition actually preserved domain separation is
making the shared resolver ignore its `domain` argument:

    baseline: 28 passed
    BREAK: _scoped_signer_for → ed25519.sign(..., domain=FACT_DOMAIN)   [ignores `domain`]
      FAILED custody …::TestArrivalSigner::test_signs_under_arrival_domain_and_roundtrips
      FAILED custody …::TestArrivalSigner::test_fact_and_arrival_mutually_refuse
      FAILED apps …::test_migrate_through_cli_mints_lineage_and_updates_descriptor
      3 failed, 25 passed
    RESTORE: git diff --stat EMPTY; 28 passed

Three tests at two layers — the custody source pin and the apps e2e pin — so the
composition is covered from both ends, not just where it was written.

## Re-check 5 — suites and scope ✅

    uv run pytest apps/loops -q                                  → 2539 passed, 1 xfailed
    uv run pytest libs/custody libs/migrate tests/architecture -q → 178 passed

Apps goes 2538 → **2539**, delta +1, and the one is
`test_migrate_refuses_unparseable_vertex` (that module now runs 9). The 178 is unchanged
because F2 is a pure refactor and F3 adds exports without new cases — libs/custody 19,
libs/migrate 60, tests/architecture 99, same as round 2.

State root byte-identical across all three suites (268 entries, same listing hash),
measured per-suite. One measurement note: invoking apps and libs test dirs in a *single*
pytest run raises `ImportPathMismatchError` on the two `conftest.py` basenames — a
rootdir artifact of my combined command, not a defect; each suite is clean on its own,
which is how CI and the gate run them.

**Scope**: exactly four commits, six files, all inside the widened fence.

    libs/migrate/pyproject.toml              (e1edaa24)
    libs/custody/src/custody/signing.py      (b226adce)
    libs/custody/src/custody/__init__.py     (042f9504)
    apps/loops/src/loops/commands/store.py   (042f9504, 080ff470)
    apps/loops/tests/test_store_migrate.py   (042f9504, 080ff470)
    apps/loops/pyproject.toml                (080ff470)

Gate worktree clean but `.tmp/`.

## Round-2 findings: disposition

| Finding | Status | Fixing commit | Verified by |
|---|---|---|---|
| `s4wp4-migrate-tests-undeclared-custody` (B3) | **fixed** | `e1edaa24` | fresh-env `uv run --package migrate` → 60 passed; both causes gone |
| N5 (arrival pair duplicated) | fixed | `b226adce` | composition read; guard comments confirmed carried; domain-ignore break/restore |
| N6 (pair not exported) | fixed | `042f9504` | `from custody import arrival_verifier_for` exercised in my own probe |
| N7 (bare except fails open; dead disjunct) | fixed | `080ff470` | unparseable-vertex probe → typed refusal, exit 2, no traceback |
| F6 ordering nit | fixed | `080ff470` | `…, "store", "migrate", "painted"` |

All eleven WP4 findings across three rounds are now closed. Nothing is left open.
