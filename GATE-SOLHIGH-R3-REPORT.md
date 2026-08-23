# GATE REPORT — sol-HIGH r3 remediation (finding 09, gatekeeper by construction)

Independent gate. Target `959bafe0` on `slice/D-solhigh-r3` (fix `bc5ee83b`),
merge-base `da1012c4`. Branch `slice/D-solhigh-r3-gate`.

## VERDICT: **PASS** — finding 09 closed, and the residual door is closed too.

No findings. The residual-door question gets an affirmative answer, not a
"nothing seen".

---

## 1. Scope and suites

In-fence: `sqlite_store.py`, `test_arrival_coordinate_d0.py`, report.

| Suite | Baseline (r2 final) | HEAD | Delta |
|---|---|---|---|
| **engine** | **1906 + 1 skip** | **1910 passed, 1 skipped** | **+4** |
| store | 176 | 176 | 0 |
| apps/loops | 2530 + 1 xfail | 2530 + 1 xfail | 0 |

`test_arrival_coordinate_d0.py` collects **44** (40 at r2) — +4, and it is the only
test file touched, so the delta is fully accounted for. The fix report's table
matches mine.

## 2. The r3 reproduction — refused, and nothing stamped

Marker flipped to `'mirrored'`, index rows deleted, arrival mark retained, reopened
through the public constructor:

```
marker -> ('mirrored',) | facts rows -> 0 | log holds 3
REFUSED: index content does not match arrival log coordinates
         (facts has 0 rows, log has 3) — run …rederive_projections
marker unchanged: ('mirrored',)
```

Refused with a counted location claim, **and the marker is left untouched** — a
refused path writes nothing, which is the property finding 09 was about.

## 3. THE RESIDUAL DOOR — closed, by enumeration and by two experiments

**Enumeration.** `grep -rn "validate=False"` across `libs`, `apps`, `spec` returns
exactly **one** production caller:

```
libs/engine/src/engine/arrival_projection.py:581:
    ensure_coordinate_schema(conn, mode="arrival", validate=False)
```

It sits at the end of `_ensure_index_schema`, immediately after that function's
column ALTERs — the ruled non-validating rederive route from G-1, and nothing
else. The entry point's default is `validate: bool = True`, so a new caller must
opt in explicitly.

**Experiment B — an explicit second caller.** I added `validate=False` to the
`SqliteStore` store-open call site (a plausible future "optimisation"):

```
6 failed, 1904 passed
  …TestSolHigh07EmptyIndexConsultsProvider::test_empty_index_with_populated_log_refuses_rederive
  …TestSolHigh09ArrivalStampGatekeeperByConstruction::test_sol_r3_reproduction_empty_index_with_flipped_marker_refuses
```

**Experiment A — silent default drift.** I flipped `ensure_coordinate_schema`'s
own default from `True` to `False`, the "a future branch silently defaults into
it" case:

```
12 failed, 1898 passed
  …test_sol_r3_reproduction_empty_index_with_flipped_marker_refuses
  …test_all_four_arrival_stamping_branches_refuse_on_provider_mismatch
  …test_empty_index_with_populated_log_refuses_rederive
```

Both doors are shut by **behavioural** gates, not by the text ratchet — explicit
misuse and silent default drift each fail loudly. **The 09 evasion is not
reborn.**

*Correction to my own work.* My first pass at Experiment A patched the first
`validate: bool = True,` in the file, which belongs to `_stamp_arrival_axis`, not
to `ensure_coordinate_schema`. All 1910 tests passed — because every one of the
four call sites passes `validate=validate` explicitly, so the gatekeeper's default
is dead code. I nearly reported "the door is unratcheted" off a no-op patch.
Re-targeted at the entry point, it fails 12 tests. Recording the misfire because
the false negative was mine, and because the dead default is worth knowing about
in its own right.

## 4. All four stamping branches route through the gatekeeper

Read at `sqlite_store.py:735-800`. Every arrival-stamping branch —
mismatch-correction, no-tables, `already_migrated`, and post-rebuild — has the
identical shape:

```python
if mode == "arrival":
    _stamp_arrival_axis(conn, coordinates, validate=validate)
else:
    _stamp_coordinate_axis(conn, mode)
```

`_stamp_coordinate_axis` now raises `ValueError` on `"arrival"`, so the mirrored
writer cannot be misused as the arrival one. `_rebuild_table` no longer stamps at
all (`is_final` removed), which is what makes "the gatekeeper is the sole writer" a
structural property rather than a convention.

**One site passes a variable rather than a literal** — `sqlite_store.py:1116`,
`_stamp_coordinate_axis(self._conn, self._coordinate_mode)` in `SqliteStore.__init__`.
It is safe: `_coordinate_mode` is literally assigned `"mirrored"` nine lines
above, and `ArrivalStore` sets `"arrival"` only after `super().__init__()` returns.
And if that ordering were ever disturbed, the `ValueError` guard fires — it fails
loudly rather than stamping wrongly. Not a finding; noted because it is the one
place the mode is not statically obvious.

## 5. The ratchet narrows its own claim

`test_structural_ratchet_single_arrival_stamp_in_store_meta` asserts exactly one
literal `'coordinate_axis', 'arrival'` write and that it lives inside
`_stamp_arrival_axis` — regex plus AST. Its docstring states:

> NOTE: This ratchet is a residue locator for the literal 'arrival' write into
> store_meta, not proof of provider-agreement correctness alone. The behavioral
> gates own the verdict.

That is the WP-3 `oid` lesson carried forward without being asked: the text scan
claims location, the behavioural gates carry the verdict. Experiments A and B
confirm the behavioural gates really do carry it — both were caught by
`TestSolHigh09…` and the 07 reproduction, not by the ratchet.

## 6. r2's fixtures still hold at r3

- **06** — a fresh `ArrivalStore` still stamps `('arrival',)`.
- **07** — an emptied, unmarked index over a populated log still refuses.

Both re-run against r3's code, not assumed from r2.

## Bottom line

Finding 09 is closed the way the ruling intended — by construction rather than by
vigilance. The stamp has one writer, `_rebuild_table` no longer stamps, the
mirrored writer refuses the arrival value, and all four branches funnel through the
gatekeeper.

The residual door I was asked to hunt is genuinely shut: one caller, the ruled
one, with a `True` default, and both an explicit second caller and a flipped
default fail loudly against behavioural gates. The one thing worth carrying
forward is my own near-miss — the gatekeeper's `validate` default is dead code,
and patching it looks exactly like patching the real door.

**PASS.** Ready to merge, and for sol-HIGH r4 to make the convergence call.
