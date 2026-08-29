# Slice 2 / WP1 gate report — contract surface + file adapter + F1 + GF-2 ratchet

**GATE: PASS** — with 4 non-blocking findings, 0 blocking.

Target: `slice/arrival-backend-contract` @ `70f7f7d3` (6 commits over `28654a96`).
Gate worktree: `~/Code/loops-s2wp1-gate` (branch `slice/arrival-backend-contract-wp1-gate`),
fresh `uv sync --all-packages`. Binaries verified before any green was trusted:

```
engine: /Users/kaygee/Code/loops-s2wp1-gate/libs/engine/src/engine/__init__.py
py:     /Users/kaygee/Code/loops-s2wp1-gate/.venv/bin/python3
```

Every claim below was re-derived in this worktree. The impl report was read from git
bytes (`git show 70f7f7d3:…/slice2-wp1-report.md`) and treated as the target, not the
authority. Every mutation demo was re-run here rather than accepted.

---

## 1. Brief oracle items 1–8

| # | Item | Verdict |
|---|---|---|
| 1 | 14 arrival test files green AND unmodified | **PASS** |
| 2 | CAS-race gate, full-head compare | **PASS** |
| 3 | Injected-failure-per-append-stage | **PASS** |
| 4 | Query-handle separation test | **PASS** |
| 5 | Rule 18 + ratchet, 4-step mutation demo | **PASS** |
| 6 | F1 mutation at each site independently | **PASS** |
| 7 | Suite counts reconciled | **PASS** |
| 8 | `git ls-files` shows all 5 new files | **PASS** |

### 1.1 — 14 arrival test files green and unmodified (PASS)

`git diff main...70f7f7d3 --name-only` touches exactly three test files: the two NEW ones
(`test_arrival_cas_full_head.py`, `test_arrival_contract.py`) and
`tests/architecture/test_rule_18_arrival_vocabulary_denylist.py`. **No pre-existing
arrival test file appears.** The 14 enumerated independently here: 13 engine
(`test_arrival_authority{,_gate}.py`, `_body`, `_cas_head`, `_coordinate_d0`,
`_derived_log`, `_gate`, `_grammar`, `_key_registry`, `_projection`,
`_rederivation_rowids`, `_store`, plus `test_probe_arrival_matrix.py`) + 1 store
(`test_arrival_merge.py`). Unmodified in *bytes*, which is stronger than the brief's
"unmodified in intent".

### 1.2 — CAS-race gate with full-head compare (PASS)

Two tests, and they are not the same test twice.
`test_two_writers_at_one_expected_head_and_exactly_one_wins` is deterministic;
`test_a_real_race_of_many_writers_admits_exactly_one` runs 8 threads on one
`threading.Barrier` at one captured head. Both assert exactly-one-wins **on the log**
(`landed = [r for r in log.walk() if r["ord"] > 0]; assert len(landed) == 1`) and tie the
survivor to the winner's identity — not on return values, which is the assertion that
could pass vacuously.

### 1.3 — Injected-failure-per-append-stage (PASS)

Five stages parametrized (`fence`, `assign`, `validate`, `encode`, `durability`), plus a
byte-wise crash test injecting at **every** byte position of the appended region, plus a
ceremony-atomicity test, plus an `os.fsync`-is-actually-called guard. The integrity
assertion is `walk()` completing over a dense `range(len(records))` prefix — `walk`
recomputes every `rh` and refuses a gap, repeat, or broken `prev`, so its completion IS
the no-partial-record claim.

Note the test file's own scoping comment (`:336-345`): it proves *no partial RECORD* and
explicitly does **not** claim a multi-record `append_marked_many` is all-or-nothing on
disk. That is honest rather than evasive, and it still satisfies the oracle's "no partial
logical group": the group that must be atomic — a multi-row ceremony — becomes ONE `batch`
record, and `test_a_multi_row_ceremony_is_one_record_so_it_is_never_partial` walks every
byte cut asserting `len(ceremonies) in (0, 1)` and never a fragment carrying one of two
rows. For the group a partial write could actually corrupt, the record IS the group.
The `durability` stage correctly asserts `visible == 4` (bytes landed, fsync unconfirmed
= §05's "acknowledgment lost"), not a failure.

### 1.4 — Query-handle separation (PASS)

`test_no_ledger_mutating_op_is_reachable_from_a_query_handle` +
`test_a_query_cannot_be_constructed_from_a_ledger`. The op list is **derived from
`LEDGER_MUTATIONS`** in the contract module (`arrival_contract.py:325`), not hand-copied
into the test — so an op added to the Protocol later cannot silently escape the check.
That is the ratchet-test discipline applied correctly.

### 1.5 — Rule 18 + the 4-step ratchet, re-run here (PASS)

Both new modules are in `_SCAN_TARGETS`. The ratchet mutation demo re-run in this
worktree with a throwaway `libs/engine/src/engine/arrival_zzz.py`:

| Step | State | Result observed here |
|---|---|---|
| 1 | born, unregistered | **FAILS**: `Arrival-surface modules not held to the glossary: libs/engine/src/engine/arrival_zzz.py` |
| 2 | added to `_SCAN_TARGETS` | `1 passed` |
| 3 | moved to `_NOT_SCANNED` with a reason | `1 passed` |
| 4 | file deleted, excuse left behind | **FAILS**: `AssertionError: stale exception: libs/engine/src/engine/arrival_zzz.py` |

Step 4 is the one §F does not spell out, and it is the one that keeps a shrink-only list
shrinking. `git status --porcelain` empty after cleanup.

### 1.6 — F1 mutation at each site, independently (PASS)

Each site reverted to the ordinal-only compare, alone, using the report's own revert diff.

| Site | Mutation | Observed |
|---|---|---|
| A — `append_marked`/`build` | `_refuse_stale_head(headr, pin)` → ordinal compare | `2 failed, 20 passed` — `test_site_a_refuses_a_head_rewritten_to_the_same_ordinal`, `test_site_a_refuses_a_head_from_another_lineage` |
| B — `append_marked_many`/`_locked_head` | `_refuse_stale_head(head, pin)` → ordinal compare | `2 failed, 20 passed` — the two `test_site_b_…` equivalents |

**No cross-fire in either direction**: mutating A fired no B test and vice versa, which is
what makes these independently pinned rather than jointly pinned through a shared helper.
`git diff` clean after each restore. The discriminating case in both is a log rolled back
in the bytes and re-grown to the same ordinal with different content — provably invisible
to an ordinal compare.

### 1.7 — Suite counts reconciled (PASS, exact)

| Suite | Baseline (brief) | Measured here | Delta | Accounted |
|---|---|---|---|---|
| engine | 1937 p + 1 s | **1988 p + 1 s** | +51 | `test_arrival_cas_full_head.py` 22 + `test_arrival_contract.py` 29 = 51 |
| store | 177 | **177** | 0 | merge.py changed behaviour-preservingly |
| architecture | 98 | **99** | +1 | `test_every_arrival_named_engine_module_is_scanned` |

Every delta lands on a named new test; nothing is unaccounted. The claimed counts match
the measured counts exactly — no mismatch to resolve.

**The wider net ("others baseline"), reconciled rather than waved through.** The impl
report also claims root `tests/` 99, sdk 324, apps/loops 2530+1xfail, lang 655, atoms 517,
sign 37, custody 13, chaos 12. Resolved two ways.

*By argument, for the suites not re-run.* The only behavior change outside the two new
modules is F1's `following` widening. `grep -rn "following=" libs apps --include="*.py"`
outside `libs/engine/` and `libs/store/` returns **nothing** — no consumer in apps, sdk,
lang, atoms, sign, custody or chaos passes a CAS pin at all. The widened parameter is
therefore unreachable from those suites, and `arrival_file_backend` is imported by nothing
outside tests (§3). There is no mechanism by which they could move.

*By spot-run, to anchor that argument.* Root `tests/` → **111 passed**; sdk → **324
passed**, matching the sdk claim exactly.

One report-accuracy nit falls out, and it is bookkeeping rather than a miscount: root
`tests/` holds exactly two directories, `architecture` and `chaos`, so `pytest tests` is
99 + 12 = **111**, not the "99" the impl lists beside a separate "chaos 12". The impl's
"root tests/ 99" is the architecture count relabelled, and its "unchanged from baseline"
is what tipped it off — architecture demonstrably went 98 → 99. Nothing is missing or
double-failing: 111 reconciles to the component counts exactly, and 110 → 111 is the same
+1 ratchet test. Recorded for accuracy; no finding.

### 1.8 — All 5 new files committed (PASS)

`git ls-tree -r 70f7f7d3 --name-only`: `arrival_contract.py`, `arrival_file_backend.py`,
`test_arrival_cas_full_head.py`, `test_arrival_contract.py`, `slice2-wp1-report.md`.

---

## 2. The four deviations — verified, not accepted

### D1 — third F1 caller (`ArrivalStore._ceremony_persist`) — **CONFIRMED, partially pinned**

Confirmed at source: `_ceremony_persist` now passes `following=self._pinned_head(
self._reconciled_mark)` (`arrival_store.py:575`), and `_pinned_head` completes the pin via
`ArrivalLog.anchor` and **raises `ArrivalCanonicalUnsupported` rather than returning
`None`** when the log will not vouch for the mark. So the anchor-completion path does
refuse an unvouched mark rather than falling back unpinned, as claimed.

The lead pre-registered the right question — the impl listed mutation demos for sites A
and B but not for this caller. A literal revert would prove nothing (it would trip
`_checked_pin`'s type gate, re-demonstrating the type refusal rather than the behavior),
so I mutated the two *behavioral* properties instead:

| Mutation | Property under test | Result |
|---|---|---|
| `following=self._pinned_head(...)` → `following=None` | is the ceremony pinned at all? | **CAUGHT** — `test_a_ceremony_racing_an_interloper_refuses_before_any_byte` (`test_arrival_store.py:443`) fails `DID NOT RAISE AppendRejected`. `1 failed, 1987 passed`. |
| `_pinned_head`'s `anchor is None` branch → `return None` | does it refuse rather than fall back? | **SURVIVES** — `1988 passed, 1 skipped`. Nothing pins it. |

So D1's headline behavior *is* pinned — by a pre-existing test that survived the widening,
which is why the impl did not need to add one. **Finding G1** covers the untested refusal
branch. The same probe at the merge.py caller (`following=_pinned_head(log, consumed)` →
`None`) is also **CAUGHT**: `test_concurrent_merges_never_double_append`
(`test_arrival_merge.py:715`) fails, `1 failed, 176 passed` — which is why store legitimately
gained zero tests.

### D2 — projection stores no head hash — **CONFIRMED at source; Watermark is honest**

Verified independently of the report. `_read_mark` (`arrival_store.py:203-218`) reads
exactly `ARRIVAL_LINEAGE_KEY`, `ARRIVAL_OFFSET_KEY`, `ARRIVAL_ORDINAL_KEY`; the index's
coordinate columns are `(arrival_ordinal, arrival_seq)`. **No record hash is stored
anywhere in the projection.** §07's verified-head obligation genuinely cannot be met by the
current projection, and `Watermark(lineage, ordinal)` scopes its claim to exactly what the
projection knows — a location claim, not a verdict. It honestly does not pretend to be a
`Head`.

But the resolution is **not on the contract**: see **Finding G2**.

### D3 — extra types — **CONFIRMED, each consumed by real code**

| Type | Consumed by |
|---|---|
| `Watermark` | `FileQuery.projected_through` return, `FileLedger.head_at` param, 4 tests |
| `Profile`, `DurabilityProfile`, `VerificationLevel` | `Capabilities` fields + `_DURABILITY`; cross-checked by `test_capabilities_claims_nothing_the_adapter_does_not_have` |
| `ExportedPrefix` | only the `ArrivalLedger.export` signature — **but the brief itself required those ops be declared** ("your contract module DECLARES those ops"), so a return type was forced. Declaring `Iterator[bytes]` would have dropped §08's manifest from the contract WP2 builds against. |

No speculative grammar: the report's own counter-example holds — `mint(options: Mapping)`
and `verify(scope) -> Head` invented no type. Not a finding.

### D4 — refusal-set gaps — **CONFIRMED: they propagate, not swallowed or mistranslated**

Characterized, not ruled (arbiter/gate contract-text input). Absence (`GenesisRefused`),
corruption (`ArrivalCorrupt`) and double-mint all surface as the file backend's own
exceptions and are **not** caught anywhere in `arrival_file_backend.py`. The only
translation in the module is `except StaleHead → HeadMismatch` (`:206-211`), and it is
1:1 from the CAS subclass — never from the parent `AppendRejected`, which is also raised
for `_check_follows` placement faults. That restraint is correct: mapping a torn tail to
`NotAuthority` would be a verdict claim on evidence that does not support it. Nothing is
swallowed. **Finding G3** carries the adjacent observation about `NotImplementedError`.

---

## 3. Contract conformance from the diff — PASS on all seven

| Check | Verdict / evidence |
|---|---|
| `arrival_contract.py` stdlib+typing only | **PASS**. Imports: `collections.abc`, `dataclasses`, `enum`, `typing`. Empirically in a clean subprocess, after `import engine.arrival_contract`: `'sqlite3' in sys.modules` → **False**, `'engine.arrival' in sys.modules` → **False**. |
| Adapter never mutates `ArrivalStore` | **PASS**. `arrival_file_backend.py` does not import or touch `ArrivalStore` (it imports only the two meta-key constants). The single `arrival_store.py` edit is exactly D1's pin change: docstring, `following=` line, `_pinned_head` helper (46+/9−). |
| No registry module | **PASS**. `ls libs/engine/src/engine/arrival*.py` → `arrival{,_body,_contract,_file_backend,_projection,_store}.py`. No `arrival_registry.py`. |
| No consumer rewiring | **PASS**. Non-test importers of the new modules are only the three F1 callers pulling `Head` (`arrival.py:60`, `arrival_store.py:85`, `merge.py:343`). **Nothing outside tests imports `arrival_file_backend` at all** — the adapter is built and pinned but wired to no consumer, exactly as SD-7 requires. |
| `merge.py` change is only the F1 caller adaptation | **PASS**. Three edits, all pin-completion: `_target_state` returns a `ResumeMark` instead of a bare int (and reads all three mark keys to build it), the new `_pinned_head`, and the call site. No admission/dedup/retry logic touched. |
| `StaleHead` subclasses `AppendRejected`; `match="arrived since"` still passes | **PASS**. `class StaleHead(AppendRejected)` (`arrival.py:233`); the refusal message retains the phrase (`arrival.py:273`); the pre-existing `pytest.raises(AppendRejected, match="arrived since")` at `test_arrival_store.py:443` passes in the green run — and is the very test that catches D1's pin-drop. |
| Wire codec + commitment machinery untouched | **PASS**. The `arrival.py` diff contains **zero** added or removed lines matching `encode_record|content_commitment|_canonical_bytes|rfc8785|build_record|fact_commitment`. No new `_canonical_bytes` spelling. |

---

## 4. Static diagnostic at `arrival_file_backend.py:309` — NOT a real crash

Pyright flags `.ordinal` on a possibly-`None` `through`. **Unreachable by construction.**

```python
reached = through is None          # :289
...
    reached = True                 # :302, only on the ordinal match
if not reached:                    # :307
    raise HeadMismatch(f"... ordinal {through.ordinal} ...")   # :308-312
```

`reached` is initialized to `through is None`. If `through is None`, `reached` is `True`
and is never reassigned to anything falsy, so `if not reached` is `False` and the raise
cannot execute. The raise is reachable only when `through is not None`. Pyright cannot
track the correlation between a bool and the narrowing of a different name, so this is a
false positive. **No finding, no change requested** — narrowing it for the type checker
(e.g. `if through is not None and not reached`) would be a readability trade the gate does
not require. The empty/unminted-store query path does not reach it either: with
`through=None` the loop simply yields nothing and returns.

---

## 5. The impl's ruff claim — VERIFIED

Same binary (`~/Code/loops-s2wp1-gate/.venv/bin/ruff`), each tree's own config, A/B:

| Scope | Gate tree | Main | Verdict |
|---|---|---|---|
| CI's actual scope (`libs/custody libs/sign`, per `ci.yml:65`) | All checks passed | All checks passed | clean both sides |
| The five touched source files | **6 errors** | **6 errors** | **zero added** |

The 6 are all on pre-existing lines of pre-existing files — `arrival_store.py:73` (UP035),
`:92` (F401), `:469` (E501), `merge.py:211,217,218` (E501). **None is in
`arrival_contract.py` or `arrival_file_backend.py`, and none is on a line the diff adds.**
Claim confirmed. Worth noting for the arc: CI's ruff gate only covers `libs/custody` and
`libs/sign`, so these 6 were never CI-enforced either way.

---

## 6. Findings

All **NON-BLOCKING**. None blocks the WP1 landing; G1 and G2 are input WP5/the arbiter
should carry forward.

### G1 — `_pinned_head`'s refuse-don't-fall-back branch is untested (NON-BLOCKING)

`finding:s2wp1-gate-pinned-head-refusal-untested`

Mutating `arrival_store.py`'s `if anchor is None: raise ArrivalCanonicalUnsupported(...)`
to `return None` leaves the engine suite fully green (1988 p + 1 s). The impl report calls
this branch out twice as the property that keeps D1 from being a silent weakening — "a
mark the log will not vouch for REFUSES rather than falling back to `following=None`" —
and by the slice's own mutation-evidence norm, an argued safety property with no test is
an assertion rather than a guarantee. The identical branch in `merge.py:_pinned_head`
(raising `RuntimeError`) is equally unpinned.

Not blocking, for three reasons: the *headline* behavior (that the ceremony is pinned at
all) IS caught; the branch is defensive against a state `catch_up()` already refuses on
open, so it is near-unreachable in practice; and the branch **demonstrably works** — it is
untested, not dead. Probed at runtime here with a stub whose `anchor` returns `None`:

```
RAISED ArrivalCanonicalUnsupported:
  /tmp/idx.db reconciled against arrival ordinal 7 of lineage LIN123, but
  /tmp/fake.arrival does not vouch for a record there — the index's mark and the
  log disagree, and appending under an uncompletable pin would write onto that
  disagreement. Run engine.arrival_projection.rederive_projections(...)
```

It fires, names both coordinates, and points at the remedy. That same five-line stub, as a
test asserting the refusal, is all G1 needs to close.

### G2 — `head_at` is on `FileLedger`, not on the `ArrivalLedger` Protocol (NON-BLOCKING)

`finding:s2wp1-gate-head-at-not-on-the-contract`

The impl report (§1.4 and D2) says the contract "gains `Watermark`, and `head_at` on the
ledger". Only the first half is true of the contract module. `ArrivalLedger` declares
mint / head / append / replicate / read / scan / verify / export / capabilities and **no
`head_at`**; the method exists only on the concrete `FileLedger` (`:245`). So the
watermark → verified-head resolution that D2 offers as its answer to §07's gap is a
file-adapter convention, and a DuckDB or PostgreSQL backend inherits no obligation to
provide it.

This does not weaken D2's core claim — `Watermark` is the honest return type and the
projection genuinely stores no hash. It sharpens what the §07 gap actually is: not just
"the type is a watermark", but "the *resolution operation* is unrepresented in the
contract". That is contract-text input for WP5/the arbiter alongside D2 itself. Minor
sibling, same finding: the report says `head_at` works "over `ArrivalLog.anchor`"; the
code uses `self._log.read(watermark.ordinal)` (`:254`). `_pinned_head` is the one that uses
`anchor`.

### G3 — two adapter paths refuse with `NotImplementedError`, not a `ContractRefusal` (NON-BLOCKING)

`finding:s2wp1-gate-notimplementederror-outside-the-refusal-root`

`FileLedger.append` raises `NotImplementedError` for a pre-signed draft (`:183`) and
`verify` raises it for an `Incremental` scope (`:344`). Both are argued well in place, and
both are genuinely outside the ratified five — so this is D4's shape a third and fourth
time rather than a new problem. Recording it because a caller written against the
contract catches `ContractRefusal`, and these two escape that root while `capabilities()`
does correctly advertise only OPEN and FULL. Whether the refusal set should grow a member
for "the backend does not offer this" is the same contract decision D4 raises; this is
extra evidence for it, not a separate ask.

### G4 — merge's partial-mark path falls back to unpinned (NON-BLOCKING, characterization only)

`finding:s2wp1-gate-merge-partial-mark-unpinned`

`_target_state` now returns `None` (⇒ unpinned append) if **any** of the three mark keys is
absent, where the old code pinned on a present ordinal alone. In the same function whose
docstring forbids completing a pin by dropping it, that reads like the weakening D1 exists
to prevent.

I checked reachability before ruling and it is **fine**: `_stamp_mark`
(`arrival_store.py:220-224`) stages all three keys with the caller owning one commit; all
three key constants were born in the same commit (`f345fb7b`); and `_read_mark`
(`:203-218`) has *always* required all three ("All three fields or nothing: a partial mark
is not a position"). So merge.py's new all-or-nothing **matches the store's own
pre-existing semantics** — it is a consistency improvement, and a partial mark is reachable
only by manual `store_meta` surgery. Recorded so a future reader does not re-derive the
scare; no action.

---

## 7. Verdict

**GATE: PASS.**

Eight oracle items pass, all four deviations verified rather than accepted, seven contract
conformance checks pass, the Pyright diagnostic is a false positive, and the ruff claim
holds under an A/B with the same binary. Every mutation demo the impl claimed was re-run
here and reproduced exactly, including the no-cross-fire property that makes the two F1
sites independently pinned.

The impl report is accurate on every empirically checkable claim except one wording slip
(G2's `head_at`, plus `anchor`-vs-`read`). Where its tests found behavior different from
what the author assumed, it says so (§4.3) and the corrected assertions are the stronger
ones — the torn-tail `verify` refusal in particular.

Four non-blocking findings. G1 (untested refusal branch) is the one worth closing inside
this arc; G2 is contract-text input that belongs with D2 for the arbiter and WP5; G3 adds
evidence to D4's open question; G4 is a characterization that needs no action.

---

## 8. G1 re-check @ `0d38c969` — **G1 CLOSED**

Scope: G1 only, per the lead. Nothing else reopens; §§1-7 above stand as written against
`70f7f7d3`, and the delta below does not disturb any of them.

Gate worktree rebased onto the new tip (`git rebase 0d38c969`), so the two report commits
now sit on top of it. Tree clean before and after every experiment.

### 8.1 The delta is tests only (PASS)

`git diff 70f7f7d3..0d38c969 --stat` — three files, **no source file among them**:

```
docs/scratch/arrival-break/slice2-wp1-report.md | 67 ++++++++++++++++---
libs/engine/tests/test_arrival_cas_full_head.py | 51 ++++++++++++++
libs/store/tests/test_arrival_merge_pin.py      | 70 ++++++++++++++++++
```

That matters for the re-check's validity: the behavior G1 flagged as unpinned is byte-identical
to what I mutated the first time, so the mutations below are testing the *tests*, which is
exactly what closing G1 requires.

The 14 arrival test files remain **byte-unmodified**. `libs/store/tests/test_arrival_merge.py`
in particular is untouched — the new store tests went into a **separate file**
(`test_arrival_merge_pin.py`) whose docstring names that constraint as the reason. That is
the right call rather than a dodge: it closes the finding without spending the brief's
unmodified-14 guarantee.

### 8.2 Both mutation demos re-run here (PASS)

| Caller | Mutation | Observed here |
|---|---|---|
| `ArrivalStore._pinned_head` (`arrival_store.py`) | `raise ArrivalCanonicalUnsupported` → `return None` | **1 failed**, `test_the_ceremony_refuses_an_unanchorable_mark_rather_than_unpinning` — `1 failed, 1988 passed, 1 skipped` |
| `store.merge._pinned_head` (`merge.py`) | `raise RuntimeError` → `return None` | **1 failed**, `test_an_unanchorable_mark_refuses_rather_than_unpinning_the_append`, `Failed: DID NOT RAISE RuntimeError` — `1 failed, 179 passed` |

Each fails **exactly** the named test and nothing else; `git checkout` restored each and
`git status --porcelain` was empty after both. This is the same experiment that produced a
fully green suite at `70f7f7d3` — it now goes red at both callers, which is the whole of
what G1 asked for.

### 8.3 The tests exercise the branch they claim (PASS)

Checked rather than assumed, because a refusal test can pass for the wrong reason. Probed
`ArrivalLog.anchor` directly with the fixtures the tests use:

```
anchor(offset=3, mid-record) -> None
anchor(valid boundary)       -> ord 0 rh e2cdc5501d21
```

So the unanchorable mark genuinely drives `anchor` to `None` — the branch under test — rather
than tripping some earlier validation, and a well-formed mark still resolves. The choice of a
mid-record offset over a foreign lineage is the better one: it exercises `_anchor_for`'s
boundary check instead of its cheapest early return, and it is the shape a real index/log
disagreement takes.

Both sites also carry the **negative control** that stops the refusal over-firing —
`_pinned_head(None) is None` must stay legal (§1.9), asserted inline in the engine test and as
`test_no_mark_is_still_no_pin` in the store file — plus a positive completion case
(`test_a_vouched_mark_completes_into_the_full_head`) so neither refusal test can pass by
refusing unconditionally. That is the shape a ratchet needs; nothing here is a tautology.

### 8.4 Counts reconciled (PASS)

| Suite | @ `70f7f7d3` | @ `0d38c969` | Delta | Accounted |
|---|---|---|---|---|
| engine | 1988 p + 1 s | **1989 p + 1 s** | +1 | the ceremony refusal test |
| store | 177 | **180** | +3 | `test_arrival_merge_pin.py` (refusal + negative control + positive case) |
| architecture | 99 | **99** | 0 | no architecture file changed |

Every delta lands on a named new test. The impl's claimed counts (1989 / 180 / 99) match.

### 8.5 The impl report's §4.4 records what actually happens (PASS)

Compared line by line against my runs. Both failure lines are reproduced verbatim —
`DID NOT RAISE ArrivalCanonicalUnsupported` and `DID NOT RAISE RuntimeError` — and both test
names are correct. §4.4's per-file counts (`1 failed, 22 passed` and `1 failed, 2 passed`) are
file-scoped where mine were suite-scoped; they reconcile exactly (23-test file, 3-test file).
The section is also honest about *why* the gap mattered — "an unpinned append *succeeds*, so
nothing would ever have gone red" — which is the correct diagnosis of why a green suite was
not evidence.

One residual report-accuracy nit, carried not raised: §3's prose still says the diff shows
"no test file among the changes except **the two** new ones", but there are now **three**
(`test_arrival_merge_pin.py` joined). The underlying claim — the 14 held unmodified — remains
true and I verified it independently; only the count in the sentence is stale.

### 8.6 Verdict

**G1 CLOSED.** The refusal branch is pinned at both F1 callers, each mutation goes red at
exactly the named test, the tests provably exercise the anchor-is-None path, and the negative
and positive controls keep the claim scoped. The gate report's §6 G1 entry stands as the
historical record of the finding; its recommendation ("a five-line stub test does it") was
taken at both sites.

**G2, G3 and G4 are untouched by this commit and remain open as previously characterized** —
all still NON-BLOCKING. Overall verdict is unchanged: **GATE: PASS**, now with three
non-blocking findings outstanding instead of four.
