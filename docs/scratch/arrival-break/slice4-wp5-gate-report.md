# Slice 4 WP5 — combined gate + adversarial report

**Range:** `main..7b7c9ff1` (4 commits) — `70f7cdd5` W1, `72c1136e` W2, `158b5668` W3, `7b7c9ff1` W4
**Gate worktree:** `/Users/kaygee/Code/loops-wt/s4-wp5-gate` @ `slice4/wp5-gate`
**Seat:** combined gate + adversarial (proportionality ruling; slice-wide sol integration review is the independent second seat)

## Verdict

**BLOCKING** — 6 blocking findings, 5 non-blocking. The mechanical spine of the WP is
sound: W1 is provably prose-only, W2's dissolution is real and behaviour-preserving at the
editor surface, W3's rule has genuine power on four independent probes. What fails is the
*claim discipline*: W2 left its predecessor's detection machinery in the tree welded inert,
W2 shipped a public return shape with two fields no consumer reads, W3's shrink-only
allowlist does not actually force a shrink, and W4's new prose asserts four things about
the code that the code does not do.

All four suites are green. Nothing here is a correctness defect in the migration path;
every finding is residue, overclaim, or a ratchet that will not ratchet.

---

## Suites (all re-run by the gate, not read from the worker report)

| Suite | Command | Result |
|---|---|---|
| engine @ base (`main`) | `uv run --directory libs/engine pytest -q` | 2306 passed, 1 skipped |
| engine @ `7b7c9ff1` | same | 2306 passed, 1 skipped |
| apps (workspace root) | `uv run pytest apps/loops -q` | 2539 passed, 1 xfailed |
| migrate + custody + architecture | `uv run pytest libs/migrate libs/custody tests/architecture -q` | 181 passed |
| lang | `uv run --directory libs/lang pytest -q` | 682 passed |
| store | `uv run --directory libs/store pytest -q` | 180 passed |

Engine base and head counts are **identical**, as W1 requires.

Two environment notes, neither a worker defect:

- `uv run pytest libs/lang` **from the workspace root fails collection** (7 errors,
  `ModuleNotFoundError: hypothesis`) — lang and engine declare `hypothesis` in their own dev
  groups, which the root env does not resolve. The brief's final-check command inherits this.
  Both must run with `--directory`.
- A first lang run under `TMPDIR=<worktree>/.tmp` produced 43 failures in
  `test_corpus_serializer_reparse_equivalence`. Cause was the gate's own pytest basetemp
  artifacts being globbed into lang's `.vertex` corpus. Re-run with basetemp outside the
  worktree: 682 passed, 0 failed. **Gate contamination, not a worker defect** — recorded
  because the brief's own test-env instruction (`TMPDIR=<worktree>/.tmp`) reproduces it.

## Scope

Exactly 4 commits; 12 files, all inside the fence:

```
docs/architecture/arrival/backend-contract.html   docs/architecture/arrival/protocol.html
libs/engine/src/engine/arrival.py                 libs/lang/src/lang/__init__.py
libs/lang/src/lang/ast.py                         libs/lang/src/lang/loader.py
libs/lang/tests/test_loader.py                    libs/migrate/CLAUDE.md
libs/migrate/src/migrate/sidecar.py               libs/migrate/tests/test_sidecar.py
libs/store/CLAUDE.md                              tests/architecture/test_rule_19_...py
```

All new files tracked (`git ls-files` confirms `libs/migrate/CLAUDE.md` and the Rule 19
file). `git status --short` clean. `.loops/` untouched; no `sl`/`loops` emit in the range.
Rule 19 confirmed the next free number (16, 17, 18 occupied).

---

## W1 — stale prose sweep: **PASS**

**Prose-only, proven mechanically.** For each of the 45 modules under
`libs/engine/src/engine/`, I parsed base and head with `ast`, normalised every string
`Constant` to a sentinel, and compared `ast.dump`. Every module identical, `arrival.py`
included. The comparator was self-tested against a deliberate one-token mutation
(`==` → `!=` on the `GENESIS_KIND` branch) and correctly reported `DIFFERENT`, so the
identity result is not a vacuous pass.

Because that normalisation also masks non-docstring string changes, I ran a second pass
extracting every string constant that is *not* a docstring and diffed the sets. Exactly one
non-docstring string changed — the `_placement_fault` refusal message — which is precisely
the intended W1 target. No dict key, kind name, or condition string moved.

**Ratified-truth check.** Both passages now match `protocol.html` §09's own words:

- `arrival.py:577` — "every genesis introduces the founding public key at ordinal 0; the
  core grammar admits no keyless genesis". §09 rules ordinary signed genesis; the old text
  ("a keyless genesis belongs to the migration sidecar") asserted the opposite.
- `arrival.py:895` — "source fingerprints and equivalence claims live in the signed
  migration report and bootstrap receipt, never in a containment-only genesis". §09 puts
  claims in the signed report + bootstrap receipt; the old text put them in the sidecar's
  genesis.

**Sibling sweep.** `grep -n "migration sidecar" libs/engine/src/engine/*.py` leaves 5 hits,
all accurate as written (they refer to the sidecar as a *reader* or as a *consumer of the
projection*, not as an owner of genesis semantics):
`arrival_body.py:35`, `arrival_contract.py:189`, `arrival_head_seam.py:21`,
`arrival_projection.py:262`, `jsonl_codec.py:35`.

---

## W2 — lang store-clause query: **PASS on mechanism, 2 BLOCKING on discipline**

The dissolution is real. `grep -rn "import ckdl" libs/migrate/src/` is **empty**;
`grep -rn "INTERIM" libs/migrate/src/` is **empty**; migrate's Rule 4 row is unchanged
(migrate already depended on lang). Migrate's editor tests pass unchanged.

**Mutation proof re-run by the gate (not read).** I patched `effective_store_clause` to
return the FIRST `^[ \t]*store\b.*$` line rather than the effective one, and ran the
editor's comment-shadow test:

```
FAILED libs/migrate/tests/test_sidecar.py::test_edit_vertex_store_clause_comment_shadowed_active_store
  PublishPreconditionRefused: expected store=PosixPath('data/target.arrival'),
  got PosixPath('data/active.jsonl')
```
Restored → `1 passed`. The proof holds.

**ckdl carries no position information** (`ckdl._ckdl.Node` exposes only
`args, children, name, properties, type_annotation`), so the hand-written quote/comment/
slashdash scanner is *forced*, not gratuitous — and it now lives in lang, the KDL boundary,
which is exactly the ruling. That part is right.

### Gate-built probes (17 inputs, none from the worker)

| Input | count | line | located slice |
|---|---|---|---|
| block-comment-shadowed | 1 | 5 | `store "./new.jsonl"` ✓ |
| `//`-shadowed | 1 | 3 | ✓ |
| slashdash `/-` shadowed | 1 | 3 | ✓ |
| nested block comment | 1 | 3 | ✓ |
| duplicate clauses | 2 | None | refuse-shaped ✓ |
| no clause / only-commented | 0 | None | refuse-shaped ✓ |
| unusual spacing / tabs | 1 | 2 | ✓ |
| `store` in a child block | 1 | 2 | outer clause ✓ |
| word "store" inside a string arg | 1 | 3 | ✓ |
| CRLF | 1 | 2 | ✓ |
| raw string containing a quote | 1 | 2 | ✓ |
| **same-line trailing comment** | 1 | 2 | `store "./a.jsonl" // was ./old.jsonl` ← whole line |
| **`name "a"; store "./a.jsonl"`** | 1 | 1 | `name "a"; store "./a.jsonl"` ← whole line |
| **`other store="x"` + real clause** | 1 | **None** | refuses despite an unambiguous node |
| **quoted node name `"store" "…"`** | 1 | **None** | refuses a legal KDL document |

Every deviation is refuse-shaped or caught downstream by verification-by-re-parse. I
confirmed the last point end-to-end: `name "a"; store "…"` refuses with
`condition='vertex_reparse'`; a `store` node with a children block refuses at pre-parse.
**No input produced a silently wrong edit** except the trailing-comment case (N2 below).

### B1 (BLOCKING) — the dissolved locator was neutered, not removed

`sidecar.py:249-274` still computes `block_comment_spans` and `regex_matches`, and still
carries both old guards — but each was welded inert by appending `and store_span.count == 0`:

```python
if len(regex_matches) != 1 and store_span.count == 0:   # line 258
    ... condition="vertex_store_regex_match_count"
if regex_matches:
    for c_start, c_end in block_comment_spans:
        if c_start <= match_start < c_end and store_span.count == 0:   # line 269
            ... condition="vertex_store_in_comment"
```

When `count == 1` (the whole point of the change) both branches are dead and the two regex
computations are dead work. When `count == 0` all three surviving branches refuse — the
*only* difference between them is which of three `condition` labels gets attached to a
refusal that means one thing: "no effective store clause."

This is the residue the dissolution was supposed to sweep. Per the standing rule —
*dissolution isn't done until its residue is swept; removing X means clearing its trail
(dead code, vestigial detection) in the same change, not a follow-up* — the old locator has
to go, not get conjunction-guarded into silence. It is also exactly the shape the
scope-the-claim rule warns about: a detector kept alive past the point where it detects
anything.

**Prescription.** Delete `block_comment_spans` (`sidecar.py:249-253`), `regex_matches`
(`:255-257`), and both neutered guards (`:258-274`). Keep `count > 1 →
vertex_store_duplicate_nodes` and collapse the rest into the one surviving refusal at
`:276-281` (`count == 0 or span is None → vertex_store_ineffective`). `re` may then be
unused in the module — check. The only test that asserts the retiring labels already
asserts them as a set (`test_sidecar.py:859`,
`condition in {"vertex_store_in_comment", "vertex_store_ineffective"}`) and stays green;
the other two labels appear nowhere else in the repo except a prior gate report.

While there: `vertex_store_ineffective`'s message ("matched store line does not correspond
to an effective store node") is wrong for the `count == 1, span is None` case, where an
effective node exists and only the *locator* was ambiguous. One extra sentence, or a
distinct condition, would keep the refusal honest.

### B2 (BLOCKING) — `StoreClauseSpan` ships two fields nobody reads

The brief ruled: *"Design the return shape from what the TWO existing consumers actually
need — nothing speculative."* Grepping every consumer outside lang's own tests, the sidecar
reads `.count` (`:242, :245, :258, :269, :276`) and `.span` (`:276, :283`). **`.line` and
`.raw` have zero production consumers**, and both are derivable from `span` + the text.
This is a new public export on the repo's KDL boundary, so the surface is not free.

**Prescription.** Drop `line` and `raw` from `StoreClauseSpan` (`libs/lang/src/lang/ast.py:698-704`)
and from the three construction sites in `loader.py:1002, 1086, 1087`; adjust the lang tests
that assert them (they can assert `text[span[0]:span[1]]`, which several already do). If
`line` is wanted for a future refusal message, add it when that message exists.

---

## W3 — Rule 19: **PASS on power, 2 BLOCKING on the ratchet**

### The widening is correct and confirmed implementable

The worker widened the rule to cover workspace-member imports in `tests/`. That widening is
ratified and is honoured: `test_declared` is built with `include_dev=True` and workspace
members appear in it by name. I confirmed the division of labour the brief asked about —
Rule 19 checks *declaration*, Rule 4 checks *DAG shape*; they overlap on src/ workspace
imports by design, and they must, because slice-4 defect #2 (`migrate` imported in
apps/loops src, undeclared) is itself a src-level workspace import that Rule 4's DAG check
passes and Rule 19 catches.

### Power proofs — four, all run by the gate

| Probe | Result |
|---|---|
| P1 remove `"sign"` from migrate's dev group | **RED** — 4 violations named with file:line (worker's own proof, reproduced) |
| P2 stale allowlist entry (`strategies.py`, `numpy`) | **RED** — `'numpy' is no longer imported` |
| P4 `import numpy` at module level in `store/src/store/__init__.py` | **RED** |
| P5 `import numpy` **inside a function** in the same file | **RED** — the collector's `generic_visit` descends into function bodies, so lazy imports are in scope |

All restored; `git status --short` clean after each.

### Allowlist entries 1-2: the pattern claim is **verified legitimate**

`atoms.testing.strategies` and `lang.testing.strategies` are genuinely shipped `src/`
modules (both exist, both packaged under `src/<pkg>`), and they are genuinely imported by
downstream test suites: `libs/atoms/tests/strategies.py`, `libs/engine/tests/strategies.py`,
`libs/store/tests/strategies.py`, `libs/sdk/tests/test_properties_sdk.py`,
`libs/lang/tests/strategies_kdl.py`. This is the `numpy.testing` pattern, and Rule 6 already
carries the identical exception for `atoms.testing`
(`test_rule_06_atoms_stdlib_only.py:27-31`). These two entries are legitimate and should
survive.

Note for the record: the allowlist is **10 entries in 4 documented groups**, not 4 entries —
group 3 is 1 entry (`apps/loops/tests/test_store_migrate.py`, `rfc8785`) and group 4 is 6
entries (`libs/store/tests/*`, `atoms` ×5 and `lang` ×1).

### B3 (BLOCKING) — the allowlist is not shrink-*forcing*

`test_rule_19_allowlist_is_minimal` asserts each entry's file exists and still imports the
module. It does **not** assert the entry is still an actual *violation*. So the moment an
entry's dependency gets properly declared, the entry becomes dead weight and nothing says so.

Proved directly (P3): I added `"rfc8785>=0.1.4"` to `apps/loops`'s dev group — which is
exactly the fix round the arbiter has planned for entry group 3 — and re-ran:

```
2 passed in 1.49s
```

Green. The allowlist entry is now unnecessary and the ratchet is silent about it. This is
the failure mode the ratchet test exists to prevent: *an invariant that lives only in review
vigilance drifts.* Without this fix, the B4 fix round below will declare the deps and the
stale entries will sit in the allowlist indefinitely, each one a standing false exemption.

**Prescription.** In `test_rule_19_allowlist_is_minimal`, replace the "still imported" check
with "still a violation": resolve the entry's owning package from `rel_path`, recompute
`_get_package_declared_modules(pkg, include_dev=<True if the path is under tests/>)`, and
assert `module not in declared` — failing with "entry no longer needed; remove it". Keep the
existing file-exists and still-imported checks as the other two staleness causes. After that
change, P3 must go red; that is the acceptance proof for this fix.

### B4 (BLOCKING) — entry groups 3 and 4 are real findings and must become declarations

Per the arbiter pre-ruling these are undeclared-dependency defects allowlisted rather than
fixed. Exact prescription:

**Group 3 —** `apps/loops/pyproject.toml`, line 9:
```toml
dev = ["pytest>=8.0", "pytest-cov>=6.0"]
→
dev = ["pytest>=8.0", "pytest-cov>=6.0", "rfc8785>=0.1.4"]
```
No `[tool.uv.sources]` change (rfc8785 is a PyPI dist, already pinned `>=0.1.4` in the root
and in engine).

**Group 4 —** `libs/store/pyproject.toml`. Add to `[tool.uv.sources]` (currently line 10-11,
holds only `engine`):
```toml
atoms = { workspace = true }
lang  = { workspace = true }
```
and to `[dependency-groups] dev` (lines 13-20), alphabetically before `hypothesis`:
```toml
"atoms",
"lang",
```
Test-only, so the dev group is the right home — `store`'s runtime `dependencies` stays
`["engine", "python-ulid>=3.0"]`, preserving the Rule 4 row. Add the same short rationale
comment migrate's dev group already uses for `sign`.

Then `_ALLOWLIST` shrinks from 10 entries to 2 (the two `hypothesis` strategy entries), and
with B3 applied the minimality test enforces that it stays there.

---

## W4 — docs: **BLOCKING (2)**

`libs/store/CLAUDE.md`'s rebirth paragraph is **accurate** — verified against
`libs/store/src/store/rebirth.py`: `rebirth_store` creates the target through
`engine.sqlite_store.ensure_coordinate_schema` and raises `ArrivalCanonicalUnsupported` for
arrival targets, so "sqlite→sqlite only … superseded for migration by `libs/migrate`" holds.

The other three documents do not.

### B5 (BLOCKING) — four factual claims the code does not support

Each was checked against source, not against the worker's report.

**(i) `<lineage>.staging.arrival` does not exist.** Asserted in `protocol.html`
("Writes to `<lineage>.staging.arrival` before atomic cutover"), in
`backend-contract.html` ("Targets are staged at `<lineage>.staging.arrival`"), and in
`libs/migrate/CLAUDE.md` Rule 1. The code writes `s_dir / f"{lineage}.arrival"`
(`sidecar.py:762`; resume path `:633`). `grep -rn "staging" libs/migrate/src` returns only
prose. The staging property is that the path is *lineage-named* — hence not yet referenced by
the `.vertex` — not that it carries a `.staging` suffix. CLAUDE.md contradicts *itself* here:
Rule 1 says `.staging.arrival`, Stage 2 correctly says `<store_dir>/<lineage>.arrival`.

**(ii) The report filename is wrong.** All three docs say
`<target>.migration-report.json`. Code: `target_path.parent / f"{lineage}.migration-report.json"`
(`sidecar.py:954`) — i.e. `<lineage>.migration-report.json`, *not*
`<lineage>.arrival.migration-report.json`. `sidecar.py`'s own module docstring already has
this right. The CLAUDE.md Level 0 example compounds it with a literal wrong path:
`Path("data/project.arrival.migration-report.json")`.

**(iii) The enumerated "5 publish preconditions" replaces two real gates with two
non-gates.** The code's canonical five (module docstring §H.2 at `sidecar.py:43-49`, and the
executing code at `:903-950`) are:

1. target verifies `Full` (`condition="target_verify_full"`)
2. equivalence re-run matches (`condition="equivalence_rerun"`)
3. journal's FIRST entry for the lineage is bootstrap/MINT (`condition="journal_first_entry_mint"`)
4. inventory equality (`condition="inventory_equality"`)
5. source content hash unchanged (`SourceChangedRefused`)

The new prose lists "source fingerprint unchanged, target openable through head, target head
matches scan head, inventory equality, valid signed report". It **drops** the equivalence
re-run and the journal-first-entry-MINT gate — two of the five — and substitutes "target head
matches scan head" (that is the resume-diff in Stage 4, not a publish precondition) and
"valid signed report".

**(iv) "valid signed report" / "report verified" overclaims.** `run_migration` never calls
`verify_migration_report`. It checks that the injected signer returned a non-`None` signature
(`sidecar.py:1004-1008`, `condition="report_signature"`). "Report is signed" and "report is
verified" are different claims, and the docs make the stronger one.

**(v) The already-migrated guard is attributed to the wrong layer.** It *does* exist — but in
`apps/loops/src/loops/commands/store.py:819-821`
(`if canonical_mode(pre_ast.store) == "arrival": return _refuse_store("already on an arrival
lineage …")`). There is no such guard anywhere in `libs/migrate` (no matching symbol, no
refusal class). `backend-contract.html`'s wording survives this; `protocol.html`'s bundling
of it with the library's publish preconditions is loose; **`libs/migrate/CLAUDE.md` Stage 9
is simply wrong** — it tells the next reader that `run_migration`'s stage 9 verifies "the 5
publish preconditions … + already-migrated guard", and F6 attributes the guard to a migrate
design fact.

To the brief's question — *five preconditions + already-migrated guard = six now?* — **no.**
It is five preconditions in `libs/migrate` plus one guard in `apps/loops`, at different
layers, and the docs should say so rather than summing them.

**Prescription.** In all three documents: `.staging.arrival` → `<lineage>.arrival`, naming
lineage-derivation (not a suffix) as what makes it staging; report path →
`<lineage>.migration-report.json`; replace the five-precondition list with the code's actual
five as enumerated above; change "valid signed report"/"report verified" to "custodian
signature obtained for the report"; and move the already-migrated guard out of the migrate
precondition list into a sentence naming `apps/loops store migrate` as its home. Fix the
CLAUDE.md Level 0 example path in the same pass.

### B6 (BLOCKING) — `libs/migrate/CLAUDE.md` omits two ruled contents

The brief ruled the new CLAUDE.md must carry the quarantine rule *including* "the frozen
copies import no legacy modules — cite the in-package AST ratchet and its slice-5
dissolution", and the injection rule *including* "src never imports custody/sign — signers
are injected; test-only deps in the dev group".

What landed: Rule 1 covers offline-ness and zero write paths but never mentions the frozen
legacy copies, never cites the ratchet, never mentions slice-5 dissolution. Rule 2 states the
signer callback but never states the import prohibition or the dev-group placement.

The cited artefact exists and is exactly what the brief meant —
`libs/migrate/tests/test_quarantine.py`, whose own docstring reads "This ratchet guards the
freeze window until slice 5 deletes those modules, at which point it dissolves (construction
supersedes detection) — slice 5's residue sweep removes it", with
`FORBIDDEN_MODULES = {engine.jsonl_codec, engine.jsonl_store, store.rebirth, store._conn}`.
A CLAUDE.md that omits it leaves the next reader without the one pointer that explains why
migrate's imports look the way they do and when the constraint lifts.

Both underlying invariants are **true** and worth stating: `grep` over
`libs/migrate/src/migrate/*.py` finds no `custody` or `sign` import (injection holds), and
migrate's dev group declares `sign` with a rationale comment.

One phrasing caveat for the fix: the brief's "nothing imports migrate" is stale post-WP4 —
`apps/loops/src/loops/commands/store.py:842` imports `migrate.refusals` (function-level),
and CLAUDE.md's own chain already says so. State the quarantine as *migrate imports no
legacy modules and has no write path into a live store*, not as *nothing imports migrate*.

---

## Non-blocking

**N1 — lint regression in `test_sidecar.py`.** The commit added a stray
`from lang import BackendDecl, parse_vertex` at line 30, duplicating line 26-27's
`from lang import BackendDecl, ObserverDecl, VertexFile, parse_vertex_file`, placed inside
the `migrate.*` import block. `ruff --select E501,F811,I` goes from **7 errors at base to 9
at head**: new `F811 Redefinition of unused BackendDecl from line 26` and new
`E501` at line 867. Fix: delete line 30 and add `parse_vertex` to the existing lang import;
wrap line 867.

**N2 — `span` is a *line* span, not a clause span, and the docstring says otherwise.**
`effective_store_clause`'s docstring promises "(start_char, end_char) slice in text" for "the
clause's source span"; it returns `l_start .. line-end`. Consequence, verified end-to-end:

```
input:  store "./a.jsonl" // KEEP THIS COMMENT
output: store "./target.arrival" backend="file"
```

The trailing comment is silently deleted, and verification-by-re-parse cannot catch it —
comments are not in the AST. This is **pre-existing** (the old `re.sub(r"^[ \t]*store\b.*$")`
did the same), so it is not a regression and not blocking. But the new docstring now
*promises* clause-granularity while delivering line-granularity, which will mislead the next
caller. Either narrow the docstring to say "the full source line containing the effective
clause" or tighten the scanner to end the span at the node's terminator. The docstring fix is
the cheap correct one.

**N3 — one refuse-shaped capability regression.** A document with a top-level `store=`
*property* on another node alongside a real store clause (`other store="x"` + `store "./a"`)
previously edited fine (the old regex matched only the line-initial `store`); the scanner now
matches both, returns `span=None`, and the editor refuses `vertex_store_ineffective`.
Same for a quoted node name (`"store" "./a.jsonl"`), which is legal KDL. Both are refusals,
never corruption, and both are contrived for a `.vertex`. Recorded, not blocking.

**N4 — Rule 19 does not cover the root `tests/` tree.** It iterates `apps/loops` + `LIBS`
only, so `tests/architecture` and `tests/chaos` are unchecked against the root's dev group.
Small gap; the root dev group is `pytest`/`pytest-cov`/`ruff` and those trees are largely
stdlib. Worth one line in the docstring or one more package in the loop.

**N5 — the brief's final-check command cannot run lang from the root** (see Suites). Not a
worker defect; the brief should carry `--directory` for lang and engine.

---

## Honest unverified

- I did not run mutmut or any mutation campaign beyond the two ruled proofs.
- I did not verify the HTML renders (no browser); claims were checked as text.
- Design-fact conformance was checked against `protocol.html` §09, `backend-contract.html`
  §11 and the code, not against the signed `design:` fact in the store (read-only `sl` from
  the primary worktree was out of this gate's fence).
- The 5-precondition enumeration was reconciled against `sidecar.py`'s module docstring and
  the executing code; I did not cross-check it against the proposal's §H.2 text.
