# Slice 3 / WP1 gate report — the head-attestation module

Target: `slice3/arrival-witness` @ `be8b6c5e` (8 commits over `main` @ `4c4bf148`).
Gate worktree `~/Code/loops-s3wp1-gate` (branch `slice3/wp1-gate`), fresh
`uv sync --all-packages`; baseline worktree `~/Code/loops-s3wp1-base` detached at
`4c4bf148` with its own sync. Python 3.13.11, pytest 9.1.1, ruff 0.16.5.
Contract: `slice3-wp1-brief.md`, design §B/§C, ratified fact
`01M17S26ZC1JFC51VEVSG4ZA67`, and the amended ruling
(`finding:s3wp1-mid-file-journal-damage-unstated` @ `01M17TWCK28T11QACVX53SY56H`).
The implementation report was read from git bytes (`git show be8b6c5e:…`) and treated
as the target of review, not as evidence.

## GATE: FAIL

Two BLOCKING findings, both in the **read classification** that feeds the amended
ruling's new type — not in the type itself. The `EstablishedHead`/`HeadLowerBound`
design survives the adversarial attempt intact (item 5's accessor-level checks all
pass). What fails is that two byte patterns reach a *confident* head without ever
producing the bound: one of them silently lowers *K* with `.skipped` empty, and one
of them collapses a remembered lineage to first contact with no attacker involved.
Everything else on the Oracle passes, most of it exactly as claimed.

## Oracle, item by item

| # | Item | Verdict |
|---|---|---|
| 1 | Suites, counts, `git ls-files`, ruff | **PASS** |
| 2 | Import closure | **PASS** |
| 3 | XDG isolation | **PASS** |
| 4 | All seven mutation demos | **PASS** |
| 5 | The amended ruling's shape (unignorable by construction) | **FAIL** |
| 6 | Design conformance | **PASS** |
| 7 | WP2/WP3 handoff claims | **PASS** |

### 1. Suites, counts, files, lint — PASS

Run separately, the CI way, in the gate worktree:

| Suite | Baseline (`4c4bf148`) | Gate tip (`be8b6c5e`) | Delta |
|---|---|---|---|
| engine | `2063 passed, 1 skipped` | `2150 passed, 1 skipped` | **+87** |
| architecture | `99 passed` | `99 passed` | **0** |

`pytest libs/engine/tests/test_arrival_head_attestation.py --collect-only` reports
**87 tests collected** — the entire engine delta is the new file, as claimed, with
nothing else moved.

**The pollution warning is true and I confirmed it on the base commit before
accepting it.** `uv run --package engine pytest libs/engine/tests tests/architecture`
in ONE process at clean `4c4bf148` yields `29 failed, 2133 passed, 1 skipped` — the
impl's stated number exactly, on a tree containing none of its work. Running the two
suites separately is therefore the correct measurement, not a convenience.

`git ls-files` shows all four changed files tracked; `git status --porcelain` in the
gate worktree is empty. The two new files are `libs/engine/src/engine/arrival_head_attestation.py`
(1025 lines) and `libs/engine/tests/test_arrival_head_attestation.py` (1035 lines).
`ruff check` on both: `All checks passed!`

Rule 18 enrollment is genuinely load-bearing, not decorative: deleting the single
`_SCAN_TARGETS` line and re-running architecture fails
`test_every_arrival_named_engine_module_is_scanned` (`1 failed, 98 passed`). The
"enrolls by birth" claim is real. Restored, tree clean.

### 2. Import closure — PASS (re-run independently, not inherited)

I wrote my own subprocess probe rather than trusting the impl's test passing:

```json
{"after_import": [], "after_read": [],
 "engine_modules": ["engine", "engine.arrival_contract", "engine.arrival_head_attestation"]}
```

Neither `sqlite3` nor `engine.arrival` is in `sys.modules` after importing the module,
nor after calling `parse_journal_lines`. The engine closure is exactly the module plus
the contract. The §B.1 stdlib-and-contract-only claim holds.

### 3. XDG isolation — PASS

The fixture is genuinely autouse, not opt-in:
`@pytest.fixture(autouse=True) def _isolated_state_root(tmp_path, monkeypatch)` at
module scope (`test_arrival_head_attestation.py:62-71`), setting `XDG_STATE_HOME` to
`tmp_path/state`. `state_root()` resolves the env var at call time, so the redirect
binds every call in every test.

`XDG_STATE_HOME` **is** set in my shell (`/Users/kaygee/.local/state`). I snapshotted
`~/.local/state` (282 entries) *before* the first pytest run and re-took it after the
full 2150-test suite plus all seven mutation runs: `diff` is empty, and
`~/.local/state/loops` does not exist before or after. No stray `heads/` directory
anywhere under `$HOME`. The one test that unsets the variable
(`test_the_state_root_falls_back_to_local_state`) also monkeypatches `Path.home` to
`/home/tester` and only asserts on the computed path — it writes nothing.

### 4. All seven mutation demos — PASS (each re-run by me, each restored clean)

Applied to the module in my own worktree, the new test file run, the module restored
byte-for-byte (asserted equal to the original), and `git diff --stat` verified empty
before the next one.

| # | Mutation | My result | Named tests failed |
|---|---|---|---|
| (a) | rollback arm returns `UNCHANGED` | 3 failed, 84 passed | `test_lower_ordinal_is_rollback`, `test_out_of_order_journal_writes_still_catch_a_restore` ✓ |
| (b) | epoch filter dropped from `_epoch_of` | 6 failed, 81 passed | all six, incl. `test_after_a_trust_reset_the_restored_store_opens_unchanged` (the deadlock) ✓ |
| (c) | `_known_of` returns `epoch[-1]` | 4 failed, 83 passed | `test_the_known_head_is_the_maximum_ordinal_not_the_last_line`, `test_out_of_order_journal_writes_still_catch_a_restore` ✓ |
| (d) | `O_APPEND` dropped from the exclusive create | 1 failed, 86 passed | `test_a_create_race_does_not_overwrite_the_other_writers_entry` ✓ |
| (e) | torn-tail guard always returns `""` | 1 failed, 86 passed | `test_a_torn_tail_does_not_glue_itself_to_the_next_entry` ✓ |
| (i) | refusal on unreadable lines restored | 9 failed, 78 passed | `test_damage_anywhere_is_tolerated_and_reported` leads ✓ |
| (ii) | `HeadLowerBound` collapsed into `EstablishedHead` | 8 failed, 79 passed | `test_an_incomplete_read_cannot_classify_a_restore_as_unchanged` ✓ |

**Every named test failed in every demo**, which is the requirement. Three counts came
out above the report's, and the causes are accounted for rather than waved at:

- **(a) 3 vs 2 and (c) 4 vs 2 — suite growth.** The report measured these against the
  77-test file, before the seven amended-ruling tests existed. Every extra failure is
  a post-amendment test exercising the same arm (`test_a_bound_still_answers_rollback_soundly`
  for (a); `test_an_incomplete_read_cannot_classify_a_restore_as_unchanged` and
  `test_a_create_race_…` for (c)). Higher is stronger, not divergent.
- **(i) 9 vs 7 — my mutation's shape.** I restored the refusal *globally* (raise on any
  skipped line); the pre-amendment code refused positionally and kept torn-tail
  tolerance, so mine over-approximates and takes two torn-tail tests with it.

(b), (d), (e), (ii) match the reported counts exactly. All seven restores clean.

### 5. The amended ruling's shape — **FAIL**

**What passes, and it is the substantive half.** The type design is sound and the
adversarial cheap-caller attempt fails at the accessor level exactly as required:

| Expression | `EstablishedHead` | `HeadLowerBound` |
|---|---|---|
| `.entry` | `HeadAttestation` | `AttributeError` |
| `.at_least` | `AttributeError` | `HeadAttestation` |
| `.head` | `AttributeError` | `AttributeError` |
| `established_head()` | returns | **raises `IndeterminateComparison`** |

There is no uniform expression over the `known` field that yields a comparable head
without naming which case it is in. The refusal message names both the bound and the
damage: *"…its head is only known to be at or above ordinal 4… Unreadable: line 3:
does not parse (…)"*. A bound still answers ROLLBACK soundly
(`compare(bound.at_least, head(5), None) is Outcome.ROLLBACK`, verified). And the
`[90, 92, 91]` test states the whole refutation, both halves: it asserts
`established_head().head.ordinal == 92` **before** the damage and
`pytest.raises(IndeterminateComparison)` after, so the pre-damage truth *K*=92 is
pinned rather than assumed.

**Why the item still fails.** The ruling's requirement is not only that the type be
unignorable, but that the state be *produced* whenever a line is lost — its words are
"every unreadable line is skipped and surfaced on `JournalRead.skipped` wherever it
sits, never silently." Two byte patterns defeat that before the type is ever reached.
Both are BLOCKING and both are written up below.

**One sub-claim verified weaker than reported.** The Oracle asks whether ADVANCED is
also unobtainable against a bound. It is not — it is unobtainable *without naming the
case*:

```
compare(bound.at_least, presented=95, at_known=bound.at_least.head)  ->  advanced
```

That meets the construction standard (writing `.at_least` names the weaker claim), so
it is not itself a finding. But the report says both self-corrections are "now in the
type's docstring", and only one is: `HeadLowerBound.__doc__` names the *unchanged*
trap and the evidence-gathering correction, and never mentions `advanced`. A WP3
author reading that docstring would see the bound described as unsound for one
comparison when it is unsound for two. **WP3 handoff: treat `.at_least` as
rollback-only.**

**Residual, noted not chased.** `JournalRead.epoch` and `.entries` are public tuples,
so a caller can re-derive *K* uniformly across both cases —
`max(read.epoch, key=lambda e: e.head.ordinal)` returns 91 on the damaged
`[90, 92, 91]` journal and `compare` then says `unchanged`. This is NON-BLOCKING:
those fields are required by §C.4 (`unaccounted_heads` consumes `epoch`), and a caller
who reimplements `_known_of` is not the "forgot to look" caller the ruling targeted.
Worth one line in the WP3 gate: the guarantee is scoped to the
`known`/`established_head()` pair, not to the whole dataclass.

### 6. Design conformance — PASS

Mechanically asserted, all green:

- **`AttestationRefusal` roots outside `ContractRefusal`.** MRO is
  `['AttestationRefusal', 'Exception', 'BaseException', 'object']`; non-subclass in
  **both** directions; all nine refusals root in `AttestationRefusal` and none in
  `ContractRefusal`. Arbiter ruling 1 honored.
- **`HeadFork` vs `arrival_contract.SameHeightFork`** — distinct classes, unrelated by
  inheritance either way, while the outcome string stays `same-height-fork`.
- **The seven outcome strings** — exactly seven rows, values `first-contact`,
  `unchanged`, `advanced`, `rollback`, `same-height-fork`, `rewrite`,
  `lineage-replaced`.
- **Trust-epoch reset-INCLUSIVE**, and the code does what
  `finding:s3wp1-epoch-scope-is-reset-inclusive` says WP2 must encode: on a journal
  whose *last* entry is the reset, `epoch` is that single entry, *K* is the reset head
  90, and a restored store presenting 90 classifies **`unchanged`** — not
  `first-contact`. The pre-reset entry is retained in `.entries` as evidence.
- **`bindings.jsonl`** — `DELETE IN SLICE 5` appears 4×, "residue sweep" present,
  file sits beside the journals.
- **`bindings` reserved** — `bindings`, `BINDINGS` and `Bindings` all raise
  `UnsafeLineageName` (case-folded).
- **Journal home** — `XDG_STATE_HOME` honored (`/tmp/xdgprobe/loops`), `~/.local/state`
  fallback when unset, and `LOOPS_HOME` **ignored** both alone and alongside
  `XDG_STATE_HOME`. Choice 15's threat-model argument is implemented, not just stated.
- **headerless-entries-refuse** (`JournalUnreadable`, "no header"),
  **empty-file-is-not-headerless** (`parse_journal_lines([])` returns cleanly), and
  **crashed-creator-cannot-strand** — verified functionally on a real filesystem: an
  empty pre-created file followed by `append_entry` yields a journal whose first line
  is the header and whose read gives *K*=4.

### 7. WP2/WP3 handoff claims — PASS

- **`compare`'s signature untouched** — `arrival_contract.py` is **absent from the diff
  entirely** (`git diff --stat main..HEAD -- …/arrival_contract.py` is empty; the
  branch touches exactly four files). Signature is the ratified
  `(known, presented, at_known) -> Outcome`. No WP2 vector shape changes.
- **`parse_journal_lines` pure** — no `open(`, `read_text`, `Path(` or `os.` in its
  source; takes an iterable of raw lines.
- **No clock** — no `time`/`datetime` import or use anywhere in the module;
  `observed_at` is caller-supplied throughout.
- **`append_entry` raises `OSError` outward** — `_write_all` raises on a short write,
  and `append_entry` contains no `except OSError`, so write failure surfaces per §D.4.

## Findings

### BLOCKING-1 — a kindless JSON object is absorbed as a header, silently lowering *K*

`parse_journal_lines` classifies **any** dict without a `"kind"` key as a header
(`arrival_head_attestation.py:768-773`): it sets `header_seen`, records **no** entry
and **no** skip, and moves on. So a line that is valid JSON but not an entry
disappears without a trace.

Reproduced in the round's own refutation scenario — one epoch, file order
`[90 trust-reset, 92, 91]`, true *K* = 92:

| The ordinal-92 line becomes | `known` | `.skipped` | `compare(K, presented=91)` |
|---|---|---|---|
| `{torn` (unparseable) | `HeadLowerBound(91)` | 1 line | `established_head()` **raises** ✓ |
| `{}` (parseable, kindless) | **`EstablishedHead(91)`** | **empty** | **`unchanged`** ✗ |

The truth is ROLLBACK from 92. This is precisely the silent re-acceptance the
maximum-ordinal rule exists to close and the amended ruling was written to close for
damaged lines, reopened through a different byte pattern — and it is *worse* than the
tolerated case, because the bound at least refuses.

**Why BLOCKING rather than a note.** It violates the ruling's own sentence, not an
inference from it: "every unreadable line is skipped and surfaced on
`JournalRead.skipped` wherever it sits, never silently." A `{}` line is unreadable as
an entry and is surfaced nowhere. It also breaks the module's own docstring invariant
(`parse_journal_lines`: "Every unreadable line is skipped and reported, wherever it
sits").

The deletion-equivalence defence in `JournalUnreadable.__doc__` — "anyone able to
corrupt a line in the journal can delete the journal instead and be met with
trust-on-first-use" — does not cover this case. Deletion leaves a journal whose
bootstrap is permanently labelled `first-contact`, which is exactly what slice 6
checks. This leaves a `mint`-rooted journal that looks completely healthy while
answering `unchanged` to a rollback.

*Sketch, not a prescription (remediation design is the impl's):* recognise a header by
its **shape** — the `type`/`protocol`/`wire` keys it is written with — and route other
kindless dicts through the ordinary skip-and-report path. That keeps
`test_a_second_header_from_a_create_race_is_not_damage` green, since real headers
carry `type`.

### BLOCKING-2 — when no entry survives, the incomplete read degrades to silent first contact

If every entry line is unreadable, `_known_of` gets an empty epoch, `known` stays
`None`, and the `HeadLowerBound` branch is never taken. `established_head()` then
returns `None` **without raising**, and `compare` answers `FIRST_CONTACT` — trust on
first use — while `.skipped` quietly holds the losses.

Verified on a journal written entirely by a later build (v2 header + v2 entries), which
needs no attacker at all, only version skew:

```
entries: 0   skipped: 3   known: None   bootstrap: None   established_head(): None
a FRESH GENESIS (ordinal 0) against a journal remembering 4217 -> first-contact
```

That is the design's own §D.4 case — *"a fresh genesis at a location whose journal
remembers ordinal 4217 is a replacement wearing the old name"*, the case `StoreLost`
exists to refuse — reached silently through the forward-compatibility path. With an
attacker it is a downgrade attack: force the older binary and be met with TOFU.

**Why BLOCKING.** This is the exact shape the ruling forbade — "not a boolean beside a
plain *K* a caller can skip". The tolerate-and-report half is satisfied; the
unignorable half is not. `known=None` with a non-empty `.skipped` is indistinguishable
at the accessor from a genuinely fresh journal, which is the one claim a damaged
journal must not be able to make. The ruling did not enumerate the zero-surviving-entry
corner, so this is a gap in its coverage rather than defiance of it — but the property
it required is absent there.

**Report-accuracy consequences of the same mechanism**, folded in here rather than
raised separately. Design §B.3 promises "a journal written by a later build must not
make an older build refuse to compare". Post-amendment the code is wrong in *both*
directions against that promise, and the artifacts still describe the old behaviour:

- **Mixed skew** (some v1 entries survive): `known` is a `HeadLowerBound`, so
  `established_head()` **raises** — the older build *does* refuse to compare.
- **Pure skew** (no v1 entries): silent first contact, as above.

Choice 10 in the report still reads "skipped and reported, **never refused**", and the
pinning test is named `test_an_entry_from_a_later_build_is_skipped_and_reported_not_refused`
with the docstring "A later build's journal must not make this one refuse to compare"
— while its own assertion is `isinstance(result.known, HeadLowerBound)`, the state whose
`established_head()` raises. The behaviour is pinned honestly; the name, the docstring
and choice 10 describe something the code no longer does. Worth an arbiter call on
whether §B.3's forward-compat promise survives the amendment, since the conservative
behaviour (a v2 entry could hold a higher ordinal, so *K* really is only a bound) looks
correct and it is the *promise* that should bend.

### NON-BLOCKING-3 — the "unobtainable" guarantee is scoped to the accessor, and one docstring is short

Three small residuals, none of them defeating the ruling's standard, all detailed under
item 5 above: (a) `.epoch`/`.entries` permit uniform re-derivation of *K* by a caller
who reimplements `_known_of`; (b) ADVANCED against a bound is obtainable via
`.at_least` — sound as construction, since naming the field names the case; (c)
`HeadLowerBound.__doc__` names only the unchanged trap, though the report claims both
self-corrections landed there. WP3 should treat `.at_least` as rollback-only and the
gate for WP3 should say so.

## What the gate does not doubt

The module is careful work and most of the round's hard thinking survived scrutiny. The
epoch scoping is right and reset-inclusive for the reason the finding gives; the
write-path fixes (`O_APPEND` on the exclusive create, the newline guard, the checked
`os.write`) are real hazards closed and each is pinned by a mutation that fails exactly
one test; the refusal family is rooted where the arbiter ruled; the import closure is
genuinely stdlib-plus-contract; the isolation fixture is autouse and the developer's
real state root was untouched across every run; and the `EstablishedHead`/
`HeadLowerBound` split does what the amended ruling asked of it at the accessor. The
two BLOCKING findings are both upstream of that split — in deciding *whether* a line
was lost, not in what the type does once it knows.

## Reproduction

```bash
git -C ~/Code/loops worktree add ~/Code/loops-s3wp1-gate -b slice3/wp1-gate be8b6c5e
cd ~/Code/loops-s3wp1-gate && uv sync --all-packages
uv run --package engine pytest libs/engine/tests -q        # 2150 passed, 1 skipped
uv run --package engine pytest tests/architecture -q       # 99 passed
uv run ruff check libs/engine/src/engine/arrival_head_attestation.py \
                  libs/engine/tests/test_arrival_head_attestation.py
```

BLOCKING-1 and BLOCKING-2 reproduce from `parse_journal_lines` alone, with no
filesystem: substitute `{}` for an entry line in a `[90 trust-reset, 92, 91]` journal,
and read a journal whose header and entries are all `"v": 2`.

---

# Re-check — round 1, at `fbdc5770`

Target advanced to `slice3/arrival-witness` @ `fbdc5770` (two commits over `be8b6c5e`:
`1df5c8f4` the fixes, `fbdc5770` the report). Gate worktree rebased onto it
(`git rebase --onto fbdc5770 be8b6c5e slice3/wp1-gate`), so this report sits directly on
the tip it judges. **Scope: only the two failed items and the docstring rider. Nothing
else was reopened**, and nothing else needed to be — the diff touches exactly three
files, `arrival_head_attestation.py`, its test file, and the impl report. No test,
fixture, contract or architecture file outside that set moved, so items 1-4, 6 and 7
stand on the round-0 evidence.

## RE-CHECK VERDICT: both BLOCKING findings CLOSED. **GATE: PASS** for WP1.

### BLOCKING-1 — kindless dict absorbed as a header — **CLOSED**

The fix replaces the positional-ish `"kind" not in decoded` test with `_is_header`,
which keys on the **type string**: a header is a kindless dict whose `type` is
`arrival-head-observation`. Everything else falls through to the ordinary
skip-and-report path.

My original demonstration, re-run on the same `[90 trust-reset, 92, 91]` journal
(true *K* = 92), now inverts:

| The ordinal-92 line becomes | round 0 | round 1 (`fbdc5770`) |
|---|---|---|
| `{}` | `EstablishedHead(91)`, `.skipped` **empty**, `compare` → `unchanged` | **`HeadLowerBound(91)`**, 1 line recorded, `established_head()` **raises** |

The recorded skip reads `line 3: not readable by this build`, the bound is 91, and the
bound still refuses below itself (`compare(at_least, head(5), None) is ROLLBACK`). The
refusal message was also widened to name **both** unobtainable answers — "cannot be
called unchanged **or advanced** against a bound".

Generalised beyond the one byte pattern I reported. Every non-header shape is now
skipped and recorded, none absorbed:

| line | result |
|---|---|
| `{}` | `HeadLowerBound`, skipped=1 |
| `{"v":1,"protocol":1}` (kindless, no `type`) | `HeadLowerBound`, skipped=1 |
| `{"v":1,"type":"something-else"}` (**different** type) | `HeadLowerBound`, skipped=1 |
| `null` | `HeadLowerBound`, skipped=1 |
| `[1,2]` | `HeadLowerBound`, skipped=1 |

And the tolerance it had to preserve is intact: two real headers in one file still read
clean (`EstablishedHead`, skipped=0), so the create-race case survives. The deliberate
choice to key on `type` alone rather than on `protocol`/`wire` too is verified to do
what it claims — a header with `"v":2`, `protocol` 9, `wire` 9 and an extra field is
still recognised, so a later build adding header fields does not brick this reader.

Pinned by `test_a_kindless_dict_is_not_absorbed_as_a_header` and
`test_a_header_naming_another_type_is_not_this_journals_header`.

### BLOCKING-2 — zero readable entries degraded to silent first contact — **CLOSED**

A third `known` state, `HeadUnreadable`, now covers the corner the ruling did not
enumerate: content was claimed and none of it could be read. It is **not** the absence
of a state, and it is not `None`.

My pure-skew demonstration (v2 header, v2 entries, no attacker — version skew alone):

| | round 0 | round 1 |
|---|---|---|
| `known` | `None` | **`HeadUnreadable`** |
| `established_head()` | returns `None` **silently** | **raises `IndeterminateComparison`** |
| fresh genesis vs. a journal remembering **4217** | `first-contact` | **declined — no comparison obtainable** |

`dataclasses.fields(HeadUnreadable)` is exactly `['skipped']` — **no ordinal, by
construction**, so unlike `HeadLowerBound` it cannot even answer rollback, which is
correct: there is no bound to be below. It has no `.entry`, no `.at_least`, no `.head`,
no `.ordinal`. All three losses are recorded, and the refusal message states the point
in words rather than leaving it to be inferred: *"…none of it is readable by this
build, so nothing is known about the head it accepted — not even a lower bound. **This
is NOT first contact: heads were accepted here.** Unreadable: line 2…"*

First contact remains reachable exactly where it is honest: an empty journal and a
**header-only** journal both give `known=None`, no skips, and classify `FIRST_CONTACT`
(`test_a_header_only_journal_is_still_first_contact`).

The re-scoped §B.3 promise landed in all three places claimed, and honestly. Report
choice 10 now reads "never refused **on its own account** … what the promise never
licensed is the stronger reading"; the `_parse_entry` docstring carries the same
re-scoping plus the version-skew consequence stated rather than hidden ("an older build
reading a purely newer journal declines its comparisons. Resolution is operator work");
and the misleadingly-named test is **gone** — zero occurrences of
`test_an_entry_from_a_later_build_is_skipped_and_reported_not_refused`, replaced by
`test_a_later_build_entry_is_never_refused_on_its_own_account`, which is what the code
actually does.

### The adversarial shortcut, re-run against **three** states — still unobtainable

No attribute reaches a comparable head across all three; each is reachable in exactly
one state, and `established_head()` is the only uniform accessor:

| expression | `EstablishedHead` | `HeadLowerBound` | `HeadUnreadable` |
|---|---|---|---|
| `.entry` | hit | — | — |
| `.at_least` | — | hit | — |
| `.head` / `.ordinal` / `.value` | — | — | — |
| `established_head()` | returns | **raises** | **raises** |

### Rider — `HeadLowerBound.__doc__` — **CLOSED**

The docstring now carries the ADVANCED half explicitly: *"A presented head `*above*` the
bound is not an advance either. Nothing bounds the accepted head from above, so a head
at ordinal 95 may still sit below a lost entry at 200 … Both proceed answers are
unobtainable; only the refusal below the bound survives."* That is the claim the report
made in round 0 and the docstring did not support. (My automated check reported a miss
on this line; that was my own substring assertion tripping over the `*above*` emphasis
markers, not a gap — the text is present and I read it directly.)

### Counts, lint, isolation

| Suite | round 0 tip | `fbdc5770` | Delta |
|---|---|---|---|
| engine | 2150 passed, 1 skipped | **2154 passed, 1 skipped** | +4 |
| architecture | 99 passed | **99 passed** | 0 |

Matches the claim. The new test file collects **91** (was 87), so all four new tests are
the four new cases and nothing else moved. `ruff check` clean on both files. The real
`~/.local/state/loops` still does not exist and my `~/.local/state` snapshot is
byte-identical to the pre-image taken before the first run of round 0, across every
suite and mutation run in both rounds.

### Both new mutation demos, re-run by me and restored clean

| # | Mutation | My result | Named |
|---|---|---|---|
| (1) | `_is_header` reverted to "any kindless dict" | 2 failed, 89 passed | `test_a_kindless_dict_is_not_absorbed_as_a_header`, `test_a_header_naming_another_type_is_not_this_journals_header` ✓ |
| (2) | `HeadUnreadable` arm removed (skipped-only → `None`) | 3 failed, 88 passed | led by `test_a_journal_of_nothing_but_later_build_entries_declines` ✓ |

Both counts match the claim exactly. Module restored byte-for-byte after each,
`git diff` empty.

## One residual, an observation and NOT a finding

Substituting a **well-formed header line** (`{"type":"arrival-head-observation"}`) for
the ordinal-92 entry is still absorbed silently: `EstablishedHead`, skipped=0, *K*=91.
This is **not a reopening of BLOCKING-1**, and it should not be treated as one. Deleting
the line outright produces the identical result — `EstablishedHead`, skipped=0, *K*=91 —
so header-substitution buys an attacker exactly nothing over line deletion, and line
deletion is undetectable in an append-only journal with no integrity protection. That is
the slice's *declared* posture: WP1 ships nothing signed (no `sig`, `issuer`, `key_id` or
`previous`), and §B.2 states the absence is the point rather than an omission. Closing
this class needs the deferred signed grammar, not a reader change.

What made BLOCKING-1 blocking was never tamper-resistance — it was that an *arbitrary*
non-entry dict vanished without being reported, breaking the amended ruling's own
sentence and the module's own docstring invariant. That is fixed. The residual is worth
one line wherever the signed-grammar work is scoped; it is not WP1's to close.

## Standing assessment

Both findings were closed at the level they were raised — BLOCKING-1 in the read
classification rather than by widening a detector, and BLOCKING-2 in the result type
rather than by a caller-vigilance rule, which is the same discipline the amended ruling
itself applied. The fixes generalise past the two byte patterns I demonstrated, they
carry their own mutation tests, the promise they re-scoped was corrected in the prose
and the test names instead of being quietly left behind, and the create-race and
header-only tolerances they had to preserve both survive. **GATE: PASS.**

---

# Re-check — round 2 (scoped), at `8ce304c6`

Line classification changed under sol-LOW r1, so this re-runs **only my own two
demonstrations** plus a re-assertion of the three-state shortcut attempt. Gate worktree
rebased onto `8ce304c6`. Not a re-derivation of anything else.

## Both demonstrations: verdicts UNCHANGED. **GATE stance holds: PASS.**

**Demo 1 — the `{}` substitution on `[90 trust-reset, 92, 91]`.** Still
`HeadLowerBound(91)`, still one recorded skip (`line 3: not readable by this build`),
`established_head()` still raises, bound still refuses below itself. The whole
generalisation set still holds: kindless-without-`type`, a different `type` string,
`null` and a list are each skipped and recorded, none absorbed. Create-race tolerance
and later-build-header recognition both survive. Under the new rule `{}` reaches the
skip by a different route — `_classify` returns `entry-shaped` because it carries no
type marker, and `_parse_entry` then declines it — but the observable outcome is
identical, which is what the finding was about.

**Demo 2 — the pure-skew journal.** Still `HeadUnreadable`, all three losses recorded,
still no ordinal (`fields == ['skipped']`), `established_head()` still raises naming the
lines and saying "This is NOT first contact", and the fresh-genesis-against-4217 case is
still **declined**. Empty and header-only journals still classify `FIRST_CONTACT`
honestly.

**Three-state shortcut — re-asserted, unchanged.** The state types were not touched:
`.entry` reaches only `EstablishedHead`, `.at_least` only `HeadLowerBound`,
`.head`/`.ordinal`/`.value` none of the three, and `established_head()` raises on both
weakened states.

## Spot-check of the new rule, where it touches my finding's mechanism

The three-way rule is a strict improvement on the two-way one I signed off, and it
closes a hole the type-string fix opened in the other direction. Confirmed:

- **The sol-LOW case.** A future header carrying its own `kind` no longer kills the
  file: the journal survives as `HeadLowerBound` with K bounded at 5, and the ambiguity
  is *named* — `line 3: carries both the journal type marker and an entry kind, so this
  build cannot say which it is`. That is a location claim, not a verdict, which is the
  right shape.
- **`JournalUnreadable` narrowed to nothing-to-parse.** A directory where the journal
  should be now raises `JournalUnreadable`, and it **is** an `AttestationRefusal` — so a
  caller catching the family root holds it. Previously a raw `OSError`/`UnicodeDecodeError`
  escaped past that root, which was a real leak in the refusal family I did not catch in
  round 0.
- An entry that acquires a type marker degrades to a *recorded* skip and therefore a
  bound, never a silent loss — so the new ambiguous arm cannot become a third absorption
  route.

## One note, non-blocking, for the record

**A round-0 Oracle line is now superseded by ruling.** Oracle item 6 named
`headerless-entries-refuse` and I verified it PASS at `be8b6c5e`. At `8ce304c6` a
headerless journal *with readable entries* no longer refuses — it yields
`HeadLowerBound` with the absence reported as `header: absent, so the protocol and wire
versions these record hashes derive under are unknown`, and still declines a full
comparison. That is deliberate and consistent with the reasoning `HeadUnreadable` was
built on (a weakened claim beats a verdict where a bound will do), and it is safe: the
read still cannot answer unchanged. Flagging it only so the item-6 wording is known to
be stale — **WP2's vectors must encode the bound, not a refusal**, if the family covers
headerless reads.

Counts at `8ce304c6`: engine **2157 passed, 1 skipped** (+3), new test file **94** (+3,
so the three new tests are the three new cases), architecture **99**, ruff clean.
