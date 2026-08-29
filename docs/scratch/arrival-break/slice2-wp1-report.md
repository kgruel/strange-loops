# Slice 2 / WP1 report — contract surface + file adapter + F1 + GF-2 ratchet

Branch: `slice/arrival-backend-contract` (the slice-2 wave branch, created by this WP).
Base: `28654a96` (includes the design proposal at `8bfb5e6a`).
Contract: `docs/scratch/arrival-break/slice2-wp1-brief.md`; design
`docs/scratch/arrival-break/slice2-design-proposal.md` §A, §D.1, §F; ratified fact
`design:arrival-break-slice2-backend-contract` @ `01M177MHWHD5HM574VSTDE17X8`.

Baselines measured on the branch before any edit, with the per-package invocation the
repo actually uses (`uv run --package <pkg> pytest …` — a bare `uv run pytest` in a fresh
worktree cannot collect `hypothesis`-dependent modules):

| Suite | Baseline |
|---|---|
| engine | 1937 passed, 1 skipped |
| store | 177 passed |
| architecture | 98 passed |

These match the brief's stated baseline exactly.

---

## 1. Design points

### 1.1 `following` widens to `Head`, not to the head record dict

§D.1 offered either "a `Head`, or the head record". Chose `Head`.

The adapter has a `Head` in hand at `append(expected, drafts)` and cannot manufacture a
head *record* from it — a `Head` carries no body — so the record-dict spelling would have
forced the adapter to synthesise a partial record, which is a `Head` in disguise with the
type checking removed. Widening to `Head` also makes the pin self-describing at every
call site: `following=head` cannot be confused with an ordinal the way `following=7` and
`following=ordinal` could.

Consequence: `engine/arrival.py` imports `Head` from `engine/arrival_contract.py`. That
direction is the safe one — the contract module imports nothing from `engine.arrival` at
runtime, so there is no cycle, and it adds no import footprint (`arrival.py` already
imports `dataclasses` and `typing`), which Rule 16's empty `engine` allowlist requires.

### 1.2 The bare-int refusal raises `ArrivalError`, not a contract refusal

A caller passing an ordinal is a *caller bug*, not a head mismatch, so it must not be
catchable as one. `ArrivalError` is the family `ArrivalLog.read` already uses for a
malformed ordinal argument, and it is deliberately NOT `AppendRejected` — `store/merge.py`
retries on `AppendRejected`, and a type error that got retried in a loop would spin rather
than surface.

### 1.3 A CAS-specific `StaleHead(AppendRejected)`, so the adapter's translation is 1:1

`AppendRejected` is raised at five sites, only two of which are the CAS: the other three
are `_check_follows` placement faults (`arrival.py:1497-1513`). An adapter that mapped
every `AppendRejected` to the contract's `HeadMismatch` would make a verdict claim the
evidence does not support, and message-sniffing to tell them apart is worse. So the two
F1 sites raise `StaleHead`, a subclass, and `FileLedger` maps *that* 1:1.

Nothing downstream changes: `isinstance(exc, AppendRejected)` still holds, and the
existing `pytest.raises(AppendRejected, match="arrived since")` pins still pass, because
the refusal message keeps the phrase "arrived since".

### 1.4 `ProjectedThrough` is a `Watermark`, not a `Head` — the projection has no head hash

Contract §07 says the projection "stores a verified `projected_through` head". The arrival
file projection provably does not: the resume mark is three fields
(`arrival_lineage` / `arrival_offset` / `arrival_ordinal`) and the index's coordinate
columns are `(arrival_ordinal, arrival_seq)`. **No record hash is stored anywhere in the
projection.** `Head` therefore cannot be `projected_through`'s return type for this
backend, and `ResumeMark` cannot be it either — a byte offset is file-backend-specific
and has no meaning to a DuckDB or PostgreSQL projection.

So the contract gains `Watermark(lineage, ordinal)`: how much of the lineage a projection
accounts for. Resolving a watermark to a verified `Head` needs the record that sits at
that ordinal, which only the ledger can attest — `FileLedger.head_at(watermark)`, over
`ArrivalLog.anchor`. That split is not a workaround; it *is* the custody/reads separation
§A.2 pins, stated in the return types: the query half knows how far it has projected, and
only the custody half can say what is there.

Raised as a finding (§4.2) — closing the §07 gap is a doc/design decision for the gate and
WP5, not WP1's to invent.

### 1.5 `FileLedger` is deliberately Protocol-incomplete until WP2

`replicate` and `export` are declared on `ArrivalLedger` (the brief requires the
declaration) and are **not** implemented on `FileLedger` — not even as
`NotImplementedError` stubs, which would be residue WP2 has to sweep. `capabilities()`
matches: `export_codecs=()` and no replicate claim. A capability report that advertised an
op the adapter does not have would be exactly the false claim §12's conformance gate
exists to catch.

### 1.6 `FileLedger.append` refuses a pre-signed draft

Contract §03's `RecordDraft` carries an optional `signature`, and
`content_commitment(k, at, observer, origin, body)` covers exactly a draft's fields with
no coordinate — so a pre-signed draft is meaningful in the abstract. But the wrap target,
`ArrivalLog.append_marked_many`, builds every record with `sig=None`, and `Entry` has no
signature field (deliberately — see its docstring). Honouring a draft signature would mean
changing `append_marked_many`, and F1's CAS widening is WP1's only permitted arrival.py
behaviour change.

So `append` refuses a draft carrying a signature and names why, rather than silently
dropping it. Location claim, not verdict: the refusal says this adapter's batch append
builds unsigned records, not that pre-signed drafts are wrong.

### 1.7 `AtomicLimitExceeded` is exercised, not decorative

`append_marked_many` has no record limit today, so the honest `max_atomic_records` for the
file adapter is "none configured". Rather than invent a fake limit or ship an unraisable
refusal, `FileLedger` takes an optional `max_atomic_records`; unset it is unbounded and
`capabilities()` says so, set it refuses before any mutation (§04's "refuse before mutation
when the request exceeds the backend's limit") and §12's configured-limits gate has
something real to exercise.

### 1.8 No opener, no registry, no consumer rewiring

WP1 ships constructors only — `FileLedger(log)` and `FileQuery(reader)`. There is no
`open_file_backend()` helper: opening is `BackendRegistry`'s (WP4, per §A.1's "adapters
imported lazily inside their opener"), and adding a second resolution path here would be
the consumer rewiring SD-7 rules out of slice 2.

### 1.9 `following=None` stays legal

F1 refuses a *weaker* pin, not the absence of one. An append with no expected head is
still an append with no expected head; nothing in the brief or the ratified fact asks for
that to change, and making it illegal would break the unpinned callers for reasons F1 has
no evidence for.

### 1.10 `StoreDescriptor.location` is `str`, not `Path`

§02: location "is interpreted only by that adapter and may be a path, DSN reference, or
service URL". A `Path` would decide, in the neutral module, that every backend's location
is a filesystem path.

---

### 1.11 Two Rule 18 joins, not three

The brief says two (`arrival_registry.py` is WP4's — "do not create it"); §D.1 says
three, counting the registry. The brief is the operative instruction and the §F glob only
sees modules that exist, so the two are consistent rather than in conflict. `arrival_registry`
joins when WP4 gives birth to it, and the ratchet is now what makes that mechanical.

---

## 2. Deviations

Both are reported as `finding` facts as well as here. Neither was optional; each is
recorded so the gate can rule on it rather than discover it.

### D1 — F1 has THREE callers, not the two the brief's blast radius names

`finding:slice2-wp1-f1-third-caller` @ `01M1794DEPS5J49VCKNPBKZMBM`.

The brief says "Known blast: `store/merge.py:307` + tests". `ArrivalStore._ceremony_persist`
(`arrival_store.py:574`) was also passing an ordinal-only pin —
`following=None if consumed is None else consumed.arrival_ordinal`. Leaving it would have
kept the weaker compare-and-swap alive at exactly the kind of site SD-2 exists to close,
one method call from the site that was closed, so the ratified fact's "bare int REFUSED …
so no caller can pass a weaker pin" decides it.

**`ArrivalStore` is therefore modified** — one call site plus a `_pinned_head` helper. This
is compatible with the brief's "ArrivalStore NOT modified", which §A.2 states about the
*adapter* work ("`ArrivalStore` is not modified by the adapter work"); the adapter still
does not touch it. Reported anyway, because the brief's flat phrasing is what a gate would
check against.

Both F1 callers complete the pin through `ArrivalLog.anchor` — a validated seek to the
mark's own byte offset, not a walk, so the full-head pin costs one read rather than a pass
over the log. **A mark the log will not vouch for refuses** rather than falling back to
`following=None`: completing a pin by dropping it is the silent weakening F1 exists to
prevent.

### D2 — the projection stores no head hash, so `projected_through` cannot return a `Head`

`finding:slice2-wp1-projection-has-no-head-hash` @ `01M1794Q19F61TSV4PPDAXCH6V`.
Argued in §1.4. Consequences for the contract module: one type beyond the brief's
enumerated list (`Watermark`), and `head_at` on the ledger.

### D3 — types added beyond the brief's enumerated list

`finding:slice2-wp1-types-beyond-enumerated-list` @ `01M179XT4AWQ7BKNBTDAQQNGCK`.

The brief enumerates `Head`, `RecordDraft`, `Commit`, `DurabilityReceipt`, `Capabilities`,
`VerifyScope`, `StoreDescriptor`. Three additions, each because a declared signature would
otherwise have had to lie:

| Added | Why it could not be avoided |
|---|---|
| `Watermark` | D2 — `projected_through` has no honest return type without it |
| `ExportedPrefix` | §08 export produces records **and a manifest**; declaring `Iterator[bytes]` would drop the manifest from the contract WP2 builds against |
| `Profile`, `DurabilityProfile`, `VerificationLevel` | the §03/§05/§06 tables, typed. `Capabilities` fields would otherwise be stringly-typed, and the enums are what let `capabilities()` be cross-checked against the adapter in a test |

Avoided by contrast: `mint(options: Mapping[str, Any])` and `verify(scope) -> Head` need no
new type, so none was invented for them.

### D4 — the ratified refusal set does not cover absence, corruption, or double-mint

`finding:slice2-wp1-refusal-set-gaps` @ `01M179Y4PCEFY4V7CPJB7G3BEG`.

The five typed refusals (`HeadMismatch`, `SameHeightFork`, `NotAuthority`,
`UnknownBackend`, `AtomicLimitExceeded`) are the ratified set, so `head()` on an unminted
log, a corrupt record, and a second `mint` all surface as the file backend's own
`GenesisRefused` / `ArrivalCorrupt` rather than being translated. Translating them would
mean choosing a member of the five and claiming something the evidence does not support —
`NotAuthority` for a torn tail is a verdict, not a location. Named here rather than
silently absorbed; growing the refusal set is a contract decision, not WP1's.

---

## 3. Test-count table

| Suite | Baseline | Now | Delta | Accounted by |
|---|---|---|---|---|
| engine | 1937 passed, 1 skipped | 1988 passed, 1 skipped | **+51** | `test_arrival_cas_full_head.py` (+22), `test_arrival_contract.py` (+29) |
| store | 177 | 177 | **0** | `merge.py` changed behaviour-preservingly; no store test added |
| architecture | 98 | 99 | **+1** | `test_every_arrival_named_engine_module_is_scanned` (§F ratchet) |

The 14 arrival test files are green and **unmodified** — `git diff --stat` shows no test
file among the changes except the two new ones.

New-test breakdown, so the +51 is legible rather than a number:

| File | Count | Covers |
|---|---|---|
| `test_arrival_cas_full_head.py` | 22 | F1 per-site (site A ×4, site B ×4), bare-ordinal refusal ×2, unpinned-still-legal ×2, §12 race gate ×2, §12 injected-failure gate ×5 stages + byte-wise write crash + ceremony atomicity + an fsync guard |
| `test_arrival_contract.py` | 29 | contract module properties (stdlib-only, static + subprocess), refusal rooting, `Head`/`StoreDescriptor` shape, **query-handle separation ×2**, adapter append/scan/verify/capabilities/limits, projection watermark ×4 |

Wider net, all green and unchanged from baseline: root `tests/` 99, sdk 324, apps/loops
2530+1xfail, lang 655, atoms 517, sign 37, custody 13, chaos 12.

---

## 4. Mutation evidence

### 4.1 F1 — each site independently

The two sites share `_refuse_stale_head` but keep **separate calls** to it, so the call
site is the mutable unit and each can be reverted alone. Both reverts below replace the
call with the ordinal-only compare F1 removed.

**Site A — `append_marked` (`arrival.py`, inside `build`)**

```python
# revert:
-            _refuse_stale_head(headr, pin)
+            if pin is not None and headr["ord"] != pin.ordinal:
+                raise StaleHead("records arrived since the caller reconciled")
```

```
FAILED test_arrival_cas_full_head.py::test_site_a_refuses_a_head_rewritten_to_the_same_ordinal
FAILED test_arrival_cas_full_head.py::test_site_a_refuses_a_head_from_another_lineage
2 failed, 20 passed
```

Exactly the two site-A tests, and **no site-B test fired** — the sites are independently
pinned.

**Site B — `append_marked_many` (`arrival.py`, inside `_locked_head`)**

```python
# revert:
-            _refuse_stale_head(head, pin)
+            if pin is not None and head["ord"] != pin.ordinal:
+                raise StaleHead("records arrived since the caller reconciled")
```

```
FAILED test_arrival_cas_full_head.py::test_site_b_refuses_a_head_rewritten_to_the_same_ordinal
FAILED test_arrival_cas_full_head.py::test_site_b_refuses_a_head_from_another_lineage
2 failed, 20 passed
```

Restored after each; `git diff` clean, 22 passed.

The discriminating case in both is the one an ordinal-only compare provably cannot see: a
log rolled back in the bytes and re-grown to the **same ordinal with different content**
(`_rewritten_to_the_same_height`, which asserts the heights agree and the hashes differ
before the append is attempted, so the test cannot pass for the wrong reason).

### 4.2 GF-2 ratchet — four steps

An unregistered `libs/engine/src/engine/arrival_zzz.py`, then each escape in turn.

| Step | State | Result |
|---|---|---|
| 1 | born, unregistered | **FAILS**, naming the file: `Arrival-surface modules not held to the glossary: libs/engine/src/engine/arrival_zzz.py` |
| 2 | added to `_SCAN_TARGETS` | passes |
| 3 | added to `_NOT_SCANNED` with a reason | passes — the shrink-only escape works |
| 4 | file deleted, `_NOT_SCANNED` entry left | **FAILS**: `stale exception: libs/engine/src/engine/arrival_zzz.py` |

Step 4 is the one §F does not spell out and is worth having: an escape hatch that outlives
its subject is how a shrink-only list stops shrinking. `arrival_zzz.py` removed, Rule 18
restored, architecture 99 green.

### 4.3 Where the tests found real behaviour, not the behaviour I assumed

Two assertions failed on first run and were corrected toward what the code actually does —
recorded because the corrected versions are stronger claims:

- **`verify(Open())` on a torn tail refuses** rather than returning a head:
  `_tail_record` will not name a tip it would have to truncate to reach. That is better F2
  evidence than the "returns a head, bytes unchanged" I first wrote, so the test now asserts
  the refusal *and* the untouched bytes, plus that `Full` reads the clean prefix past it.
- **Opening an `ArrivalStore` over a freshly minted log consumes the genesis**, so the
  watermark is ordinal 0, not absent. The None branch is now tested where it genuinely
  occurs — a store with no arrival mark at all.

---

## 5. What WP2/WP3/WP4 inherit

- `FileLedger` gains `replicate` and `export`; **`capabilities()` must change in the same
  commit** (`Profile.REPLICA`, `export_codecs`) — `test_capabilities_claims_nothing_the_adapter_does_not_have`
  cross-checks the report against the object and will fail otherwise. That is deliberate.
- `ExportedPrefix` is WP2's to refine if the manifest shape needs it.
- `arrival_registry.py` joins `_SCAN_TARGETS` at birth; the §F ratchet now fails if WP4
  forgets.
- Open for the gate: D2's §07 gap, D4's refusal-set gap, and the absent `Incremental`
  verification level (§1.5/§1.9 of the adapter docstring) — all three are contract-text
  decisions, not implementation gaps.
