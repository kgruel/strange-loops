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
