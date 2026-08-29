# Slice 2 / WP5 GATE report — independent verification

**Target:** `slice/arrival-backend-contract` @ `f9e1ea19` (6 commits over `e7513164`).
**Rulings executed:** `decision:design/arrival-slice2-contract-text` @ `01M17M3RJJGC79KXH776Z4DQBR`.
**Gate worktree:** `~/Code/loops-s2wp5-gate` on `slice2/wp5-gate`, created fresh from
`f9e1ea19`; `git rev-parse HEAD` = `f9e1ea19a5f1c113234c897adb856f59ce532ab1` verified
before any check ran. Fresh `uv sync --all-packages` (exit 0). Neither `~/Code/loops-s2wp5`
nor the main checkout was read or touched; all artifacts came from this worktree or
`git show f9e1ea19:...` bytes.

**VERDICT: GATE: PASS** — 7/7 oracle items PASS, one NON-BLOCKING finding raised.

---

## Item 1 — suites re-run from scratch, deltas reconciled — **PASS**

Run in this worktree, not trusted from the report:

| Suite | Result here | Claimed | Match |
|---|---|---|---|
| engine | **2063 passed, 1 skipped** | 2063 + 1s | ✓ |
| store | **180 passed** | 180 | ✓ |
| lang | **671 passed** | 671 | ✓ |
| architecture | **99 passed** | 99 | ✓ |
| apps | **2530 passed, 1 xfailed** | 2530 + 1xf | ✓ |

Reconciled at collection level, not by totals. `git diff e7513164 f9e1ea19 --
libs/engine/tests/` grepped for `^[-+]\s*def test_` yields **exactly one line**, an
addition: `+def test_both_deliberate_absences_refuse_under_the_contract_root`. Zero
removals, zero renames — so engine's +1 over the 2062 baseline is fully accounted by
that one test, which collects and passes individually. The apps zero-delta explanation
also holds: `grep -rn NotImplementedError apps/**/*.py` returns **0** pins, so the
refusal-type change cannot reach that suite.

`git ls-files --error-unmatch` on all **9** changed files: every one TRACKED. `git
status --porcelain` empty at report time; the 9 files match the impl report's table
exactly.

## Item 2 — ruling faithfulness — **PASS** (all five)

### Ruling 1 — the §06 F2 callout, word-for-word

Done as my **own** strip-tags comparison (`HTMLParser` extraction of the
`doc-callout is-security` whose label is "Verification never repairs" — note the file
carries **4** `is-security` callouts, so a naive first-match regex grabs the wrong one),
normalising typographic quotes/dashes/whitespace against the §E blockquote from
`git show f9e1ea19:docs/scratch/arrival-break/slice2-design-proposal.md`.

**Result: MATCH.** All five body sentences PRESENT verbatim, including the carve-out
("Materializing a projection that does not yet exist is not repair: it destroys no
prior state and can hide no divergence") and the closing "This generalizes §07's
rule… neither direction of repair may travel under a verification verb". The only
residual diff was a whitespace artifact of my own ref-stripping (`verb .` vs `verb.`).
The one addition to the ruled language is the trailing
`(decision:design/arrival-slice2-contract-text, ruling 1)` — required by the brief and
in the house style, so expected, not a deviation.

**Placement verified independently:** the callout sits in `id="reads"` (§06 — sections
run purpose/descriptor/interfaces/append/durability/**reads**/projections/transfer/…),
immediately after the verification-levels discussion closes ("Open-level checks are
operational fast paths… A backend MUST describe exactly which level each API invokes"),
which is precisely where §E specified. Class is `is-security` as drafted.

### Ruling 2 — refusal root + typed `NotSupported` at both sites

§04 (`id="append"`) gained an `<h3>Typed refusals</h3>`. Checked against the ruling's
language: **all five named conditions present** — head mismatch, same-height fork,
unknown backend, atomic limit, not-authority — plus "typed `NotSupported` under that
same root", "Every other failure is backend-specific BY DESIGN", and the scope-the-claim
reason ("covers exactly what the contract text asserts and no more").

The five conditions are not just prose: `arrival_contract.py` declares
`ContractRefusal` (448) with `HeadMismatch` (456), `SameHeightFork` (466),
`NotAuthority` (476), `UnknownBackend` (485), `AtomicLimitExceeded` (493), and the new
`NotSupported` (502) — all six real subclasses of the root.

Both former `NotImplementedError` sites re-raise it: `arrival_file_backend.py:295`
(pre-signed draft) and `:699` (`Incremental` verify scope), messages unchanged.

### Ruling 3 — `head_at` on the Protocol, tenth row, §07 sentence, classification

Cross-checked **three independent sources** rather than trusting any one:

- §03 table op rows parsed from the HTML: 10 — `mint, head, head_at, append, replicate,
  read, scan, verify, export, capabilities`
- `RATIFIED_LEDGER_OPS` literal in `test_arrival_contract.py`: the same 10
- `ArrivalLedger` Protocol methods parsed from source: the same 10

**All three sets equal**, symmetric difference empty in both directions.

`LEDGER_MUTATIONS` = `{mint, append, replicate, import_prefix}` — **`head_at` absent**,
confirming the impl's classification (a ledger READ, not a mutation). The classification
is pinned as a genuine **assertion pair**, both directions, not prose:

```
assert "head_at" in _declared_surface(ArrivalLedger)
assert "head_at" not in LEDGER_MUTATIONS
```

§07 (`id="projections"`) gained the sentence tying the verified `projected_through`
obligation to `head_at(watermark)`, refs ruling 3. §03's tenth row reads
`head_at(watermark)` / `Authority / Replica` / "Resolve a projection watermark into the
verified head it names, or refuse."

### Ruling 4 — no import op-row, §08 prose tightened to agree with the code

**No `import` row exists** in the §03 table (the 10 rows above; `import_prefix` is
absent). `arrival_contract.py:327-333` justifies keeping `import_prefix` off the
Protocol by citing "§08 describes portable import in prose and the ratified op table
gives it no row". §08's landed prose now states exactly that property: "Import is a
procedure over the operations §03 names, not an operation of its own: the table gives
it no row, and one backend's import stays a convention until a second backend shows
which of it is shared." **The code's cited doc property and the doc now agree** — which
is the gap the tightening existed to close (the code cited a property the doc had not
stated).

### Ruling 5 — §08 resumable-import debt marker, leading sentence verbatim

The `doc-callout is-open` "Contract debt — resumable import" body **starts with**
"Resumable import is required for conforming limited backends; the reference file
backend does not yet implement it." — verbatim against the brief's executable form of
the ruling (the ruling fact's own phrasing is telegraphic: "required for conforming
limited backends, reference file backend does not yet implement it"; same content, both
clauses). Programmatic `startswith` check: True.

Its supporting claims were spot-checked and **hold**: §04 really says "A backend whose
safe limit is one remains conforming and imports by verified single-record steps", and
§12 really says "Exercise configured record, batch, nesting, import, and decompression
limits."

## Item 3 — mutation demos re-run by me — **PASS** (all three, plus the footnote)

Run in this worktree after the suites finished; each restored via `git checkout` with
`git status --porcelain` confirmed empty before the next.

| # | Mutation | Result here |
|---|---|---|
| a | drop `head_at` from the `ArrivalLedger` Protocol | `AssertionError` on `_declared_surface(ArrivalLedger) == RATIFIED_LEDGER_OPS` — **"Extra items in the right set: 'head_at'"**. 1 failed, 29 passed. **Right-side**, as ruled. |
| b | add `import_prefix` (an op the adapter DOES offer) as an 11th Protocol op | same assertion — **"Extra items in the left set: 'import_prefix'"**. 1 failed, 29 passed. **Left-side**, as ruled. |
| c | revert the `Incremental` site to `NotImplementedError` | **exactly 2 failures**, both named: `test_incremental_verification_is_absent_rather_than_faked` (type pin) and `test_both_deliberate_absences_refuse_under_the_contract_root` (root catchability). 2 failed, 28 passed. No collateral. |

**The impl's footnote independently confirmed.** I ran the rejected variant myself:
adding `compact` (an op the adapter LACKS) fails one line earlier at
`assert isinstance(ledger, ArrivalLedger)` → `assert False`, never reaching the
equality. The footnote is correct and load-bearing: `compact` would have proved the
`runtime_checkable` half, not the left side of the ten-row equality. Using
`import_prefix` is the right instrument for the ruled demo.

## Item 4 — the impl's beyond-ruled items — **PASS** (with finding F1 attached)

**The three F2-question-is-open docstrings — all updated, none missed.** A sweep for
`F2 addendum|Kyle rules|rules on at the slice-2` across `libs/` and `docs/architecture/`
returns **one** hit, and it is the legitimate ruling *reference* in the new ten-op
comment, not stale "still open" prose. Likewise zero residual `nine-op|nine op|nine rows`
in engine src, engine tests, or `docs/architecture/`.

1. `ArrivalLedger.verify` — now states the MUST and the carve-out, refs ruling 1. ✓
2. `FileLedger.verify` — "Whether that is a contract MUST is the F2 addendum Kyle rules
   on" → "§06 states that as a contract MUST as of … ruling 1; this adapter held it
   before the ruling". ✓
3. **The registry absent-projection test docstring — the scoping trap, checked
   deliberately and it is FAITHFUL.** Ruling 1 is about verification, not opening, and
   the landed text does not overclaim: it says the boundary "this sits beside" is ruled,
   then states outright "**Permitted is not required, and the ruling is about
   VERIFICATION rather than opening** — so this refusal stays conforming, and the test
   still records observed behavior rather than a policy anyone chose", routing the open
   question to slice 5. It attributes no open-path ruling to ruling 1. ✓

**WP4-F1 `descriptor_for` clause — landed.** The module docstring drops the flat word
"Pure" and scopes the claim: no-adapter-import is an IMPORT-TIME property (naming the
pinning test), with the call-time path named outright — calling it reaches
`engine.residence`, which imports `engine.arrival` at module level, pre-existing and
slice-5's.

**CLAUDE.md — every structural claim verified against source, one false clause found.**
Verified true: `arrival_contract.py` imports are stdlib/typing only (`collections.abc`,
`dataclasses`, `enum`, `typing` — no `sqlite3`, no `engine.arrival`); `admission.py`
holds `admit_records` (588) and `fact_commitment_hash` (194); `merge.py` really
delegates (`from engine.admission import admit_records`, called at :298); the three-arm
dispatch via `engine.probe.probe_target` (probe.py:194) is real, with the jsonl arm
genuinely refusing (`raise jsonl_store.JsonlCanonicalUnsupported`, merge.py:161); the
engine store table's five rows including the `ArrivalStore` row are still accurate; and
the impl's own claim that `engine/__init__.py` carries no `arrival_contract` entry in
`_LAZY_IMPORTS` holds (zero hits). **One clause does not hold — finding F1 below.**

**HTML balance — all five files PASS.** Stack-based `HTMLParser` check with void-element
handling: `ok backend-contract / index / protocol / wire-format / witness-protocol`,
0 failures, no unclosed tags, no mismatched closers.

## Item 5 — the WP4-F1 re-emit — **PASS**

Both facts are in the ledger. The original
`finding:s2wp4-gate-f1-descriptor-for-calltime-import` (`01M17F4027E8VHJCH2FM2V5F5W`,
agent `s2wp4-gate`) carries **status `deferred`** with the disposition: *"deferred to
WP5's doc pass — docstring clause scoping the claim to import time."* The re-emit
(`01M17NBSHB5KVFC6NZT3AQ8CSZ`, agent `s2wp5-impl`, **status `resolved`**, same fold
name) cites commit `e4848572`.

**Explicitly, as the oracle asks: the doc-pass closure satisfies that finding's
disposition.** The disposition asked for exactly one thing — a docstring clause scoping
the claim to import time — and that is what landed, plus more than was required: the
call-time path is named outright rather than merely excluded. The finding was
doc-precision only (`residence.py` is diff-empty in both WP4 and WP5), so a docstring
narrowing is a complete closure, not a partial one. The arbiter confirms the ledger
side; the code side is satisfied.

## Item 6 — `capabilities-carries-no-wire-version`, raised not fixed — **PASS**

**The claim is TRUE at source.** §12's Capability report sentence reads: "`capabilities()`
returns machine-readable **protocol and wire versions**, supported profiles, maximum
atomic append size, …". The `Capabilities` dataclass carries a single
`protocol_version: int` (`arrival_contract.py:228`) and nothing else version-shaped;
`arrival_file_backend.py:750` fills it `protocol_version=GRAMMAR_VERSION`. `grep -rn
wire_version libs/engine/src/` returns **zero hits**. So the typed surface conflates
grammar/protocol/wire into one integer and cannot report a wire version at all.

**Not fixing it was correct scope discipline.** Ruling 3 admitted exactly one surface
addition (`head_at`); adding a `wire_version` field to `Capabilities` is a second
contract-surface change, and the contract text is the authority. Taking it would have
been executing a ruling WP5 was not given — the same overreach the scope-the-claim
practice names. The impl's judgment stands.

**Characterization for the DuckDB-arc package.** This is a *contract-text* defect, not
an adapter bug: the doc promises two versions and the typed surface offers one, so
either §12 narrows to one version or `Capabilities` grows a wire field. It bites in two
places — deployment tooling that refuses an Authority assignment on version grounds
cannot distinguish grammar from wire, and a second backend cannot report a wire version
it genuinely differs on. It is already entangled with pinned state: wire v1 is pinned
separately (`decision:design/arrival-wire-v1-seam-triage`) and §08's export already
selects a codec **by name**, which is the shape a wire version would have to agree
with. Correct home is the DuckDB-arc contract-text package, beside the ruling-4 deferred
§08 import op-row — both are "one backend cannot settle this; the second backend is
where it earns its keep", and they should be ruled together.

## Item 7 — cross-doc contradiction sweep spot-check — **PASS** (3/3)

1. **Op-count claims outside `backend-contract.html`** — grepped `index.html`,
   `protocol.html`, `witness-protocol.html`, `wire-format.html` for `nine|ten op|ten-op`:
   **zero hits**. No sibling doc enumerates the op surface, so the tenth row could not
   have contradicted one — the claim never existed rather than being swept.
2. **`protocol.html`'s "No silent repair"** — reads "A complete interior record that
   fails grammar, density, lineage, or hash checks is corruption. A conforming
   implementation MUST refuse it; it MUST NOT skip, rewrite, or truncate history in the
   name of repair." **Points the same way as F2**; no contradiction. F2 generalizes it
   to the verification verb rather than opposing it.
3. **`witness-protocol.html`'s incremental verification** — its "Incremental
   verification: Verify every record after the last fully checked checkpoint, advance
   counts, and issue the next attestation" is the **witness's** operational cadence,
   sitting beside "Fast open checks" and "Periodic full audit". It is not a requirement
   that every adapter offer `VerificationLevel.INCREMENTAL`, so the file adapter
   declining that level does not contradict it. §06's levels table plus "A backend MUST
   describe exactly which level each API invokes" and §12's capability report (which
   lists `verification_levels` as a reported field, and `arrival_file_backend.py:753`
   fills it) is the reconciliation. **Correctly characterized by the impl.**

---

## Findings

### F1 — `libs/engine/CLAUDE.md` says `ArrivalStore` is untouched; slice 2 modified it — **NON-BLOCKING**

`s2wp5-gate-f1-claudemd-arrivalstore-untouched`

`libs/engine/CLAUDE.md:196` states: "`engine/arrival_file_backend.py` is the first
adapter (`FileLedger` / `FileQuery` wrapping `ArrivalLog` plus the projection;
**`ArrivalStore` itself is untouched**)". The clause is carried forward from the slice
contract's parenthetical (`01M177MHWHD5HM574VSTDE17X8`: "FileLedger/FileQuery wrapping
ArrivalLog+projection; ArrivalStore NOT modified; ResumeMark IS projected_through"),
where it scoped **what the adapter wraps**. As a present-tense claim in the package's
living guide it is false:

- Commit `d4c18fc3` ("fix(engine): close F1 — the append CAS compares the full head at
  both sites") is **in-slice** — `git merge-base --is-ancestor d4c18fc3 e7513164`
  succeeds, so it landed before WP5 began.
- It modified `ArrivalStore` directly: added `def _pinned_head(self, consumed:
  ResumeMark | None) -> Head | None`, and changed the ceremony append's pin from a bare
  `following=consumed.arrival_ordinal` to the full `Head`.
- It added `from .arrival_contract import Head` at `arrival_store.py:85` — a **reverse
  edge** from the legacy store path into the new contract module.

Scoped precisely, because the neighbouring claim survives: "**nothing routes through it
yet**" in the same paragraph remains TRUE — production still resolves through suffix
dispatch and no Protocol is used at runtime. The `Head` import is *type reuse*, not
routing. So the defect is one clause, not the paragraph.

Impact is doc-precision only; no code, test, or contract-text consequence, and the
engine store table's `ArrivalStore` row is independently accurate, so the impl's
*conclusion* (no row change needed) is right even though the stated reason is partly
wrong. Fix is a one-clause scoping edit — e.g. "the adapter does not wrap `ArrivalStore`"
— which is the same species of narrowing WP5 itself applied to close WP4-F1. The impl
report echoes the same claim ("`ArrivalStore` is unchanged by design"); that file is a
historical receipt and needs no edit.

Not emitted to loops: the gate's emission mandate is BLOCKING findings only. Routed to
the arbiter through this report.

### Carried, not re-raised

- `finding:s2wp5-capabilities-carries-no-wire-version` (`01M17N5N77G3Q4ZARA0WR9RJTS`) —
  verified true at source (item 6), correctly left unfixed, characterized above for the
  DuckDB-arc package.
- `finding:s2wp5-worktree-branch-already-checked-out` (`01M17N5CGDY49RDJCM4QJRC0B7`) —
  mechanical, and **now moot**: my opening `git worktree list` shows no `~/Code/loops-s2int`
  entry, corroborating that the stale second checkout was removed before this gate ran.
  The general form the finding draws (a brief handing over a wave branch should say
  which worktree holds it, because `add` is not idempotent) is worth keeping.

---

## GATE: PASS

Every ruled text is faithful to `01M17M3RJJGC79KXH776Z4DQBR`, verified by my own
comparison rather than the impl's; all three mutation demos reproduce with the exact
discriminators the oracle names; five suites are green in a fresh worktree with the
single test delta reconciled at collection level; the beyond-ruled work is real and
correctly scoped, including the two places (registry test docstring, unfixed wire-version
finding) where overclaiming was the available mistake and was not made. One non-blocking
doc-precision finding (F1) is attached for the arbiter.
