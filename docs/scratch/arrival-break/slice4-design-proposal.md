# Slice 4 design proposal — migration sidecar

Arc: `design:arrival-break-implementation`. Slice: 4. Status: **proposed, awaiting arbiter
spot-check and Kyle's ratification** (the GF-3 head design point in §A is the ratify-gate).

Design of record: `docs/architecture/arrival/protocol.html` §09 *The migration sidecar boundary*
(offsets 21663–25249) and `docs/architecture/arrival/backend-contract.html` §11 *The backend as a
migration target* + *Publication contract* (offsets 30024–31711). Ratified scope:
`design:arrival-break-implementation` slice 4 ("rebirth.py is the skeleton; LegacySource
quarantines jsonl/sqlite readers + body.t + ulid_migration; absorb/reanchor demote to ceremonies;
genesis+key records minted from .vertex observers"). Plan of record: `plan.md:57-65` (slice 4),
`plan.md:111-113` (spine constraints 5–7), `plan.md:99` (verification), `plan.md:133,138-139`
(appendix rows for `rebirth.py` / absorb+reanchor / adopt).

Inherited inputs: `finding:slice1-gate-gf3-mixed-batch-remint` (deferred to this slice head),
`decision:design/arrival-wire-v1-pin`, `decision:design/arrival-slice2-contract-text` (five
rulings), `design:arrival-break-slice3-witness-minimum` (the seam this slice is the first
production consumer of).

Every load-bearing claim carries a `file:line` cite, gathered in the spot-check table at the end.
**Five findings that change what the impl agent builds are stated up front in §0.** **Plan-anchor
drift and two contract contradictions are reported separately in §L** — those are arbiter inputs,
deliberately not resolved here. **Open questions for Kyle are enumerated in §M**, each with a
recommended answer.

---

## The slice contract, quoted

From `plan.md:57-65`, binding:

> Frozen `LegacySource` → `Transformer` → `ArrivalSink` (protocol.html §migration;
> backend-contract.html §sidecar pseudocode). The new runtime keeps **no** compat mode —
> legacy-format knowledge quarantines here.
>
> - **Not greenfield — `store/rebirth.py` (668 ln) is the existing skeleton** (seam finding):
>   replay-through-deterministic-transform → new store → receipt → genesis seal maps onto mint →
>   append(groups) → verify(Full) → export. Keep its verification-by-re-run as the *sidecar's*
>   verification (stronger than the ledger's `verify(scope)`).
> - `LegacySource`: the jsonl-canonical and sqlite-canonical readers move here, frozen (this is
>   where the legacy codec's `body.t` knowledge survives). `ulid_migration()` (`rebirth.py:128–150`,
>   uuid4-era + lowercase-ulid-era knowledge) quarantines here too.
> - **`absorb` and `reanchor` demote from store verbs to sidecar ceremonies** (`store.py:948–1380`,
>   `:770–849`): absorb's job is signing genesis over pre-genesis legacy rows — the new runtime has
>   no genesisless stores; reanchor rewrites chain rows in place — impossible on an append-only
>   hash-chained ledger. Semantic demotion, not a port.
> - Transformer obligations: map every in-scope row exactly once in ruled source order; preserve
>   authored inner signatures byte-for-byte; **mint genesis + key records from the `.vertex`
>   observers block** (keys move in-log under arrival); respect batch grammar.
> - Sink: ordinary contract `append` (no privileged path); restartable only from a verified target
>   head; inventory + equivalence evidence; **atomic descriptor publish** (the `.vertex` store
>   clause update is the cutover) + bootstrap receipt emission; no dual authority — legacy store
>   stays read-only evidence after cutover.

And the design-of-record's own obligation list, `protocol.html` §09 *Sidecar obligations*:

> - Read a stable source snapshot without mutating it.
> - Declare the source format and migration tool version.
> - Map every in-scope canonical row exactly once and in the ruled source order.
> - Preserve authored signatures and content where the old format carried them.
> - Produce source inventory, target head, exceptions, and deterministic equivalence evidence.
> - Be restartable: an interrupted stage is discarded or resumed only from a verified target head.
> - Publish the new store descriptor atomically after verification and witnessing.

---

## 0. Five findings the plan could not have known

Each changes the build. None reinterprets ratified scope.

### 0.1 The contract text already decides GF-3's split arm — against it

`backend-contract.html` §04 *Atomic groups versus batch records* (offset 13208):

> A **batch record** is different: it expresses one application ceremony whose multiple fact rows
> share one ordinal. **Backend batching must not rewrite one semantic batch into several fact
> records or vice versa.**

The gate deferred GF-3 as an open two-way choice ("split mixed groups into per-observer records, or
refuse with a migration-specific message"). The contract text was not consulted when that finding
was written. It names the split arm's exact operation — rewriting one semantic batch into several
records — and forbids it. The clause sits in the append-transaction section and is addressed to
*backend batching*, so it is not word-for-word about the transformer; but the sidecar's whole
posture is that it is an ordinary caller with no privileged path (§C), and a rule that binds every
backend binds the one caller whose entire job is producing records for backends. §A argues this at
length; it is stated here because it inverts the finding's apparent symmetry before any other
analysis runs.

### 0.2 Migrated fact and batch records must be **outer-unsigned**, and that reshapes GF-3

The sidecar holds exactly one private key — the vertex's own, at `<vertex dir>/keys/`
(`init.py:201-202`, `add.py:306`). The `.vertex` observers block carries only **public** keys
(`lang/ast.py:670`). Under the wire-v1 pin an ordinary fact record's envelope `observer` is the
**author echo** (`decision:design/arrival-wire-v1-pin`), and `verify_authorship` tries a record's
signature only against keys valid *for that record's own observer* (`arrival.py:1971-1978`). So the
sidecar cannot sign a migrated fact record's envelope without either forging an authorship claim or
lying about the envelope observer.

It does not have to. An unsigned ordinary record is legal and is skipped by the authority walk —
`if _SIG in record and (verify_ordinary or forming)` (`arrival.py:2044-2045`); only genesis and key
introductions are structurally required to carry a signature (`arrival.py:551-596`). And the pin
already states the intended shape: *"outer signature = per-lineage arrival-content signature, the
inner fact-domain signature is what travels."*

**So: migrated fact/batch records carry envelope `observer` = the author echo and no envelope
signature; the authored inner signature rides in the body verbatim.** The custody claim is made
once, by the signed genesis under the migration custodian, plus the bootstrap receipt.

The consequence for GF-3 is precise and it cuts *toward* refusal, not away from it. The refusal's
own stated rationale is *"the record's envelope names row 0's and its signature covers them all"*
(`arrival_body.py:250-254`) — and for a migrated record there is no envelope signature to cover
anything. What survives is the first half: the envelope `observer` field would name row 0's
observer while the record carries another observer's rows. The dishonesty is a **labeling** one
rather than a signature-forgery one. That is a weaker objection than the grammar's own message
implies, and §A does not pretend otherwise — the decisive argument is §0.1's contract clause plus
the zero-instance census, not the signature story.

### 0.3 A restarted or abandoned migration collides with the slice-3 seam in two ways, one of them fatal

Verified against `arrival_head_seam.py` at main:

1. **Restart against a partially-built target is fine and the fence does not fire.** The fence's
   first gate returns immediately when the journal holds no abandoned epoch, and abandoned entries
   exist only behind a `trust-reset` (`arrival_head_seam.py:1319-1327`). A migration that never runs
   a trust reset never reaches the fence body. The restart classifies `UNCHANGED` when the last
   commit was journaled and `ADVANCED` when it was not — and `ADVANCED` costs `verify(Full)`, a
   whole-log walk (`_descent`, `arrival_head_seam.py:1377-1401`).
2. **Re-running a migration into a previously-attempted target *path* is refused with `StoreLost`,
   and there is no in-band recovery — not even `trust_reset`.** Once an attempt has minted, the
   location→lineage binding exists and the lineage's journal holds a head. Deleting the target file
   and re-minting hits `_absent` → `compare_absent_store` → `STORE_LOST`
   (`arrival_head_seam.py:1164-1197`), which fires *before* the ledger is handed back, so `mint` is
   unreachable. Pinned by `test_a_re_mint_under_a_remembered_location_refuses_too`. A trust reset
   does not clear it, because the reset entry itself keeps `known` non-`None`.
3. **A torn tail on the target converts a resumable restart into `StoreLost`.** `verify(Open())`
   refuses a log ending mid-record (`arrival.py:1254`), `_present` returns `None`, and the absent
   branch then refuses. The repair, `ArrivalLog.truncate_torn_tail()` (`arrival.py:1837`), is
   deliberately **not reachable through the wrapper** — delegation is explicit method-by-method
   (`arrival_head_seam.py:915-923`).

(2) is the one that reshapes the design. It is answered in §D by making the staging path
**lineage-named**, so a fresh attempt is a fresh lineage at a fresh path and the collision cannot
arise. That answer is chosen specifically because the alternative — an "abandon this attempt"
ceremony that clears the binding and journal — is the vocabulary
`design:arrival-reset-descendant-acceptance` will rule on at Kyle's slice-6 gate, and building it
now would pre-empt him.

### 0.4 `absorb` is bimodal and its **edit** mode must survive; only its genesis mode dissolves

The plan (and the arc's design fact) describe absorb as "signing genesis over pre-genesis legacy
rows." That was true at the time the seam analysis was written. It is no longer the whole function.
`_run_absorb` (`apps/loops/src/loops/commands/store.py:948-1060`) now branches three ways on
`_read_absorption_state`: genesisless → `_absorb_genesis_mode` (`:1063-1190`); genesis **plus** an
`own_lineage` marker → `_absorb_edit` (`:1202-1379`), a live declaration-protocol feature with 30+
tests (`apps/loops/tests/test_store_absorb.py`); genesis without a marker → a refusal pointing at
`adopt` (`:1040-1051`).

`_absorb_edit` has nothing to do with migration. Demoting it to a sidecar ceremony would delete a
shipped feature. **Only the genesis half dissolves** — and it dissolves into the sidecar's `mint`
rather than becoming a ceremony. §F states the corrected disposition.

Second-order: `loops init` calls `_run_absorb([])` best-effort to open a fresh store's lineage
(`init.py:472-480`). Under arrival a fresh store is *minted*, not absorbed, so that call site needs a
successor. It is slice-5 CLI work, but it is a slice-4-visible consequence and is named here so it
is not discovered during the deletion wave.

### 0.5 `rebirth.py` is a structural skeleton, not reusable code — and its receipt moves out of the ledger

`rebirth.py` is sqlite→sqlite. It reads with raw `sqlite3` through `_conn._open`
(`rebirth.py:385`), writes with raw `INSERT` statements (`rebirth.py:432-446`), and never touches
`Head`, `ArrivalLedger`, `BackendRegistry`, or the head journal. The plan's mapping
("replay-through-deterministic-transform → new store → receipt → genesis seal maps onto mint →
append(groups) → verify(Full) → export") is a mapping of *shapes*, and the shape that actually
carries over is the one the plan names as the thing to keep: **verification-by-re-run**, whose
mechanism is the shared spine at `rebirth.py:281-320` — `_expected_rows` is called by both
`rebirth_store` and `verify_rebirth`, "same function, write then check."

One placement does **not** carry over. Rebirth lands its receipt *inside* the target as a fact of
kind `rebirth` (`rebirth.py:439-446`). `protocol.html` §09 forbids that under arrival:

> The sidecar mints an ordinary signed target genesis under the migration custodian. It does not
> introduce a second keyless or containment-only genesis into the core protocol. Source
> fingerprints, counts, exceptions, and equivalence claims live in the **signed migration report and
> bootstrap witness receipt**; a future in-ledger provenance record, if wanted, uses a namespaced
> extension kind.

So the receipt splits: the head claim becomes the bootstrap journal entry (§E), and the
fingerprints/counts/exceptions/equivalence become a sidecar-side signed migration report (§I). §L
reports the contradicting stale prose inside `arrival.py` that says the opposite.

---

## A. GF-3 — the mixed-observer batch re-mint (the ratify-gate)

### A.1 The deferred finding, verbatim

`finding:slice1-gate-gf3-mixed-batch-remint`:

> GF-3 (scope-of-claim, non-blocking, slice-4 input): the impl rationale 'keeping the same-observer
> rule off the line codec avoids turning migration into a refusal' claims more than it buys. Gate
> demonstrated the boundary: legacy codec reads/writes a mixed-observer batch line fine, but
> re-minting those rows through `body_of_batch` is REFUSED — and slice 4's sidecar re-mints through
> `body_of_batch`. The refusal moved from codec to body grammar; migration is read PLUS re-mint.
> Right call for slice 1 (no live mixed-observer batches exist, verified), but slice 4 must design
> for it deliberately: split mixed groups into per-observer records, or refuse with a
> migration-specific message. DISPOSITION: deferred as a named slice-4 design point; the rationale
> must not be carried forward as a guarantee it does not make.

### A.2 The refusal, exactly

`arrival_body.py:241-266`:

```python
def _refuse_mixed_observers(rows: list[dict]) -> None:
    observers = {row["observer"] for row in rows}
    if len(observers) > 1:
        _bad(
            f"batch rows span {len(observers)} observers "
            f"({', '.join(sorted(repr(o) for o in observers))}) — every row "
            "in a batch record shares one observer, because the record's "
            "envelope names row 0's and its signature covers them all. A "
            "multi-observer ceremony is not one record."
        )
```

Type: `ArrivalBodyError(ValueError)` (`arrival_body.py:81-89`), raised through `_bad`
(`:117-118`). "Mixed" is decided strictly on the `observer` field of each *fact row body* — never
the envelope observer, which `_validate` checks only for non-empty-string-ness
(`arrival.py:436-499`). Enforced in **both** directions, encode (`body_of_batch`, `:179-191`) and
decode (`rows_of_body` → `_validate_batch`, `:282-285`), so a hand-assembled body cannot route
around it.

Two production callers, both of which the sidecar's path reaches: `arrival_store.py:565`
(`_ceremony_persist`) and `admission.py:486` (`_draft_for`). **Nothing in `libs/` or `apps/`
catches `ArrivalBodyError`** — a sidecar hitting it today crashes with a write-path message aimed
at the wrong audience.

### A.3 The four empirical questions, answered

**(a) Exactly-once in ruled source order.** A per-observer split preserves both. Each source row
still appears exactly once, and stable-partitioning a group by observer while keeping intra-group
row order, then emitting the partitions in first-appearance order, is order-preserving. *The split
does not violate this obligation.* This is the one obligation people assume decides GF-3, and it
does not.

**(b) Byte-for-byte inner signature preservation.** A split costs nothing here, and neither would
anything else. The inner commitment is `(kind, ts, observer, origin, payload_text)` and nothing else
(`admission.py:194-217` — note this moved out of `sqlite_store.py` in slice 2; §L). Record framing,
batch membership, ordinal, and seq are all outside it; `arrival_body.py:48-53` states this as the
module's non-negotiable and `test_arrival_body.py:225-232` pins it. Payload rides as verbatim stored
TEXT, never re-serialized.

There is also **no legacy outer signature to lose**: a legacy batch envelope admits exactly `t` and
`rows` (`jsonl_codec.py:142` `_BATCH_KEYS = frozenset(("t", _ROWS))`) — no signature key, no
digest, no envelope observer. And nothing anywhere verifies a legacy outer signature, before or
after migration. **The "preserve authored inner signatures byte-for-byte" obligation is entirely
orthogonal to GF-3.** Stating that plainly matters, because it is the constraint the finding's
phrasing invites a reader to reach for first.

**(c) Receipt-position / ordinal semantics.** This is where a real cost sits, and it is not the one
the finding anticipated.

| Mode | Allocator | An N-row ceremony occupies |
|---|---|---|
| plain sqlite | `sqlite_store.py:1436-1442` | **N ordinals**, seq 0 |
| legacy jsonl | *inherits the sqlite allocator* | **N ordinals**, seq 0 — but **one** batch log line |
| arrival | `arrival_store.py:530-535` (override) | **one** ordinal, seq 0..N-1 |

So "one legacy line = one ordinal" is **false today**. Migration does not preserve that
relationship; it *creates* one. A split into k records would make the ceremony occupy k ordinals
instead of 1.

What actually depends on the shared ordinal:

- **`StoreReader.query_facts` page extension** (`store_reader.py:864-892`) extends a page with the
  remaining rows of the last record via `arrival_ordinal = ? AND arrival_seq > ?`, promising
  (`:797-800`) that *"no record is ever split across pages."* A split ceremony can be cut across a
  page boundary. **This is the one concrete behavioral loss a split incurs.**
- `witness.receipt_group_span` (`witness.py:231-274`) already tolerates both layouts — it continues
  a run on `ord_val in (prev_ord, prev_ord + 1)` with equal `ts` and `lineage` — so a *contiguous*
  split keeps the declaration-ceremony guard intact.
- `WitnessPosition`'s durable identity is a fact id resolved by primary key, never an ordinal
  (`witness.py:19-24`), so no durable cursor breaks.
- `GlobalReceiptPosition` explicitly does not exist (`witness.py:26-30`).

**(d) Equivalence evidence.** A split makes the target's record count differ from the source's line
count while the row count matches. That is representable — the migration report can carry both
figures — so it is a reporting complication, not a blocker. But it means the *simplest* honest
equivalence statement ("every source line became one target record") stops being true, and the
report has to explain a per-source-line exception. Under scope-the-claim that is a claim getting
weaker to accommodate one shape that has never occurred.

### A.4 The census: the refusal arm is free today, and structurally so

Empirically scanned across every `.jsonl` reachable on this machine — the git-tracked repo store,
seven non-store logs, nine engine test fixtures, and 70 `~/.config/loops/tasked` transcripts:
**44,481 lines, 9 batch lines (all negative test fixtures), 0 mixed-observer batches.** No
`.arrival` log exists anywhere yet.

Better than the census: **no writer in this codebase has ever been able to produce one.** The only
production caller of `serialize_batch` is `jsonl_store.py:679` inside `_ceremony_persist`, reached
only from `SqliteStore.absorb_edit` (`sqlite_store.py:1803`), whose signature takes **one**
`observer` parameter for the whole ceremony (`sqlite_store.py:1612-1619`) and assembles every row
against that single variable (`:1756-1774`). `absorb_genesis` always writes a single row.

The file *format* admits mixed-observer batches; the *writer* cannot emit one. So a mixed batch can
only arrive from outside this codebase — a hand-written line, a foreign implementation, or a future
batch-emit primitive. That is exactly the class of artifact whose provenance the sidecar cannot
honestly re-attest.

### A.5 Recommendation: **refuse**, in the inventory pass, before the target exists

Refuse the migration when the source holds a mixed-observer batch line. Concretely:

1. **The refusal fires in `LegacySource`'s inventory pass, not at re-mint time.** The obligations
   already require the sidecar to "produce source inventory" before it does anything else. Detecting
   mixed batches there costs one field-set comparison per batch line on a pass that already reads
   every line. The alternative — discovering it when `body_of_batch` raises at source row 3,000,000
   with three million target records already written — is the failure mode worth designing out.
   **Assert in the gate that the target path does not exist after a refused migration.**
2. **The refusal enumerates every offending source line, not the first.** One run gives the operator
   the complete list; a first-failure refusal makes diagnosis O(number of bad lines) migration runs.
3. **A new typed refusal in the sidecar's own family**, not `ArrivalBodyError` and not
   `ContractRefusal`. Following slice 2's narrow-form ruling (*"the root covers what the contract
   asserts, no more"* — `decision:design/arrival-slice2-contract-text` ruling 2) and slice 3's
   precedent of rooting the witness layer's refusals outside `ContractRefusal`: this condition is
   named by neither the backend contract nor the witness protocol. It is the sidecar's.
4. **The type asserts what the read lacks; the remedy is advisory prose.** Per the content-vs-storage
   contract (`arrival_head_attestation.py:228-263`): *"the remedy is advisory prose in the message,
   chosen per cause, and the type asserts only what the read lacks."* So the type says *this source
   line carries rows from more than one observer, which this transformer cannot map to one record* —
   a location claim about the source. It does **not** say "split it", "the store is corrupt", or
   "retry". The message may carry advisory prose naming the choices; the type carries none of it.
5. **No flag turns it off.** A configuration switch for a safety property is the shape Rule 18's
   denylist already rejects (*"there is no mode — custody is structural, not configured"*,
   `test_rule_18_arrival_vocabulary_denylist.py:94-111`), and slice 3 held the same line for
   compare-on-open.

**Why refuse rather than split**, in the order the arguments actually carry weight:

- **The contract text forbids the split's exact operation** (§0.1): *"Backend batching must not
  rewrite one semantic batch into several fact records or vice versa."* Choosing the split means
  either reading that clause as not binding the transformer — a reading the arbiter would have to
  ratify — or amending `backend-contract.html`. Neither is a design agent's call.
- **The refusal costs nothing today and is not speculative.** It is not "we might refuse someday": it
  is what the code already does (`body_of_batch` raises), made deliberate, moved earlier, and given
  an honest type and audience. The work is catching, re-typing, and relocating a refusal that
  already exists.
- **Splitting decides, permanently and in the dark, what an artifact meant.** A mixed-observer batch
  line asserts "these rows are one ceremony." The arrival grammar asserts "a multi-observer ceremony
  is not one record." Those claims are incompatible; something has to give, and splitting picks the
  answer silently, at migration time, for an artifact whose author is unknown. Refusing surfaces the
  incompatibility to the one party who can actually adjudicate it.
- **Construction-over-detection, correctly applied.** The tempting reading is that refusal is the
  "detection" arm and splitting the "construction" arm. It is the reverse. Splitting *constructs a
  claim* the sidecar cannot support; refusing declines to construct one. The construction available
  here is the pre-mint inventory pass that makes the bad state unreachable rather than recoverable.
- **Deferring is cheap and gets strictly better evidence.** If a mixed batch ever appears, the
  decision (per-observer split, re-ceremony under a declared custodian, or hand repair before
  migration) gets made with a real instance in hand — its provenance, its author, and what the rows
  meant. Today that decision would be made against zero instances. "Later, if patterns emerge" is a
  valid disposition; this is one.

**What refusing gives up, stated plainly:** if a mixed-observer batch ever *does* appear in a live
store, that store cannot migrate until a human intervenes, and the arc's exit criterion is "all live
stores migrated" (`plan.md:84`). The exposure is bounded by the census — zero instances, and no
writer in this codebase can create one between now and slice 6.

### A.6 Alternatives considered

| Alternative | Why not |
|---|---|
| **Split into per-observer batch records** | Forbidden by `backend-contract.html` §04's batch-integrity clause (§0.1); breaks `query_facts`'s no-record-split-across-pages promise (§A.2c); decides silently what an unknown author meant. Signature-safe (§A.2b) — but nothing turned on that. |
| **Split into N single-fact records** | Strictly worse than per-observer: same contract violation, and it discards the ceremony grouping entirely rather than partially. |
| **Split, and record the regrouping in the migration report** | The report makes the *rewrite* auditable but does not make it permitted, and it still needs the ratified reading of §04 that the split arm needs. If the arbiter ratifies splitting, this is the shape it should take. |
| **Refuse per-row, skip the batch, continue** | Violates "map every in-scope canonical row exactly once." The obligations list does mention "exceptions", so a skip is *representable* — but skipping a ceremony whose rows are perfectly valid data, to avoid a framing decision, silently drops user content. Refusing the migration is the honest fail-closed posture. |
| **Refuse, with an operator flag to opt into splitting** | A configuration switch for a safety property — the shape Rule 18's denylist rejects and slice 3 held the line on. If splitting is ever right it is right unconditionally. |
| **Emit as a `fact` record whose body holds all rows** | Invents a fourth record shape outside the pinned wire-v1 grammar. Out of scope; wire v1 is pinned. |

---

## B. Sidecar placement and the quarantine boundary

### B.1 Recommendation: a new workspace package, `libs/migrate`

The quarantine has two directions and they need different strengths:

- **Inward:** the sidecar may import legacy-format knowledge, the contract, and the registry.
- **Outward:** *nothing* may import the sidecar. This is the direction that decays under review
  vigilance, and it is the one slice 5 depends on — the deletion wave is safe only if the runtime
  has no path back into legacy knowledge.

Rule 4's dependency DAG already expresses exactly this, as an enumerated allowlist keyed by lib name
(`test_rule_04_lib_dependency_dag.py:16-40`), and `LIBS` is **derived by globbing `libs/`**
(`_helpers.py:30`, `LIBS = _lib_names()`), not hand-listed. Consequences, both free:

- A new `libs/migrate` auto-enrolls in Rule 4 **by birth**, exactly the way slice 3's
  `arrival_head_attestation.py` auto-enrolled in Rule 18 by name.
- Since no existing lib's allowlist names `migrate`, **the outward quarantine is enforced with zero
  rule edits** — any lib that imports the sidecar fails Rule 4 immediately.
- The inward direction costs exactly one new row: `"migrate": {"engine", "store", "lang"}`.

This is the ratchet test applied before building: the invariant "nothing imports the sidecar" becomes
an enumerable-property test with a shrink-only allowlist, rather than a rule that lives in review
memory.

Rule 7 (`sqlite3` confined to engine + store) needs `migrate` added to `_SQLITE_ALLOWED_LIBS`
(`test_rule_07_...py:13`), since the frozen sqlite-canonical reader reads sqlite. One-line edit,
and it makes the third allowed lib visible rather than implicit.

### B.2 What "frozen" means concretely: copy, do not import

The legacy readers must be **moved** into the sidecar, not imported from the modules slice 5
deletes. `jsonl_codec.py`'s `body.t` knowledge, the sqlite-canonical reader, and `ulid_migration`
(`rebirth.py:128-154`) become sidecar-owned code with no import edge back to `engine.jsonl_codec`
or `engine.jsonl_store`. Otherwise slice 5's deletion wave either breaks the sidecar or is blocked
by it — and the whole point of the quarantine is that slice 5 can proceed without consulting it.

"Frozen" also means: no feature work, no refactors, no de-duplication against the arrival codec.
The sidecar's copy of the legacy grammar is a historical artifact and should read as one.

### B.3 Alternatives considered

- **`libs/store/src/store/sidecar/`** — natural on the "rebirth.py is the skeleton" reading and needs
  no new package. Rejected because `libs/store` is precisely the package slice 5 guts (merge arms,
  `receive.py`, `transport.py`, `_conn._SCHEMA` all die), so the frozen legacy knowledge would sit
  inside the churn, and the outward quarantine would need a hand-written intra-package rule instead
  of Rule 4's existing free one.
- **`libs/engine`** — rejected outright. The whole design is that the new runtime holds no legacy
  knowledge; putting the sidecar in the runtime's own package inverts it.
- **A `tools/` script** — rejected: it needs to be tested, versioned, and shipped, and it is the only
  path a user's data takes into 1.0.

---

## C. The sidecar writes via **admission**, never `replicate` — confirmed, not murky

The boundary is stated directly in the design of record, `protocol.html` §09 *Legacy conversion
versus backend movement*:

> The sidecar conversion above is only for a **pre-Arrival source**. Moving an existing Arrival
> lineage from the file backend to DuckDB or PostgreSQL is **exact replication** followed by the
> re-custody procedure: it preserves genesis, ordinals, signatures, record hashes, and the witnessed
> head rather than admitting the content into a new lineage.

And restated from the other side in `backend-contract.html` §08 *Portable import*:

> "Merge" that **re-coordinates content is an admission operation into another lineage, not
> replication.**

A legacy store has no lineage, no ordinals, and no record hashes. There is nothing for `replicate` to
preserve, and `replicate` validates supplied coordinates rather than assigning them
(`decision:design/arrival-slice2-contract-text` SD-3: replicate is composition over
`append_record`, *"validates-never-assigns, checks supplied rh"*). The sidecar assigns fresh
coordinates for content that has never had any. That is admission by definition.

**The boundary is crisp; I found nothing murky.** One correctness note that follows from it: because
the sidecar admits rather than replicates, the target is a **new lineage**, and every claim the
sidecar makes about descent from the legacy store is evidence in the migration report, never a
coordinate relationship in the ledger.

The append path is the ordinary contract `append`, taken through the registry-opened
`AttestedLedger`. There is no privileged path and none is needed — the seam's own module docstring
says so (`arrival_head_seam.py:19-23`): *"Slice 4's migration sidecar needs no exemption either —
minting through the wrapper IS how its bootstrap receipt gets written, and there is no privileged
path."*

---

## D. Restart from a verified target head

### D.1 The resume point is derived, never stored

The obligation is *"an interrupted stage is discarded or resumed only from a verified target head."*
A sidecar-side cursor file would be a second authority that can disagree with the target — the exact
shape slice 3 rejected for the head cache, and the shape the CLI's twin resolvers warn about
(*"two resolvers that can disagree is how a writer and a reader end up on different files"*,
`store.py:65-68`).

**Recommendation: derive the resume point from the target head by re-running the deterministic
transform.** The transform is deterministic by construction (`rebirth.py:96-99`: *"re-running the
transform over the same source must reproduce the target byte for byte — that re-run IS the receipt
verification"*), so on restart the sidecar:

1. Opens the target through `BackendRegistry.open` and takes the head the seam vouched for.
2. Re-runs `LegacySource` + `Transformer` from the beginning, producing the expected record
   sequence.
3. Diffs the expected prefix against the target's `scan` through the head. Any mismatch is a
   refusal, not a repair (F2).
4. Resumes appending at the first expected record beyond the head.

This is `rebirth.py`'s verification-by-re-run used as the *resume mechanism*, which is why the plan
is right that the skeleton's verification is the piece worth keeping. It needs no new state, cannot
drift from the target, and the restart gate is the same code path as the final equivalence gate.

Cost: a restart re-reads the source from the beginning. On a 4,366-line store that is free; the
design should not optimize it before a store makes it hurt.

### D.2 The staging location is **lineage-named**, which dissolves the `StoreLost` retry trap

Per §0.3(2), re-minting at a path whose binding and journal remember a prior attempt is refused with
no in-band recovery. So the design must never need to re-mint at a used path.

**Recommendation: the staging target is `<store-dir>/<lineage>.arrival`, where `<lineage>` is the
freshly minted lineage id.** A fresh attempt mints a fresh lineage (a ULID,
`arrival.py:360-361`), so it lands at a fresh path with no binding and no journal — `_absent`
classifies `PRE_GENESIS` and the mint proceeds (`arrival_head_attestation.py:466`, the comment
literally reads `# proceed — this is the sidecar about to mint`). An abandoned attempt leaves a dead
`<L1>.arrival` plus its journal as read-only evidence, which is exactly the posture the arc wants.

Three properties fall out:

- **No rename at cutover.** The descriptor publish names the staging path directly, so the file the
  migration built is the file the descriptor points at. A rename would leave a stale binding at the
  old spelling and manufacture a second location for one lineage.
- **Staging is enforced by non-addressability, not by directory.** `protocol.html` §11 requires
  *"the target is created at a staging location or namespace"* and *"ordinary application writers
  cannot address it during migration."* Until the `.vertex` store clause names it, **no ordinary
  writer can address the target at all** — after slice 2, backend resolution is explicit declaration,
  and after slice 5, suffix inference is gone. The descriptor *is* the addressing mechanism, and it
  is also the cutover, so the two requirements are one mechanism.
- **It removes the need for an "abandon this attempt" ceremony**, which is what keeps this design
  inside the interim law. Stated explicitly: **`design:arrival-reset-descendant-acceptance` is open
  at Kyle's slice-6 gate; the interim law on main is refuse-and-re-decree, and this design does not
  touch it.** The sidecar never runs a trust reset, never clears a binding, and never asks the seam
  to accept a descendant of an abandoned epoch. The fence is therefore inert for every migration
  path in this slice (§0.3(1)) — verified, not assumed: the fence's first gate returns when no
  `trust-reset` entry exists (`arrival_head_seam.py:1319-1327`).

Cost of the recommendation, and it is a visible one: a store file is named by its lineage rather
than by the vertex. A human reading `ls .loops/data/` sees a ULID, not `project.arrival`. Mitigation
is that after slice 5 the `.vertex` descriptor is the only resolver, so filename legibility stops
being load-bearing in exactly this arc. **Flagged as open question M-2** — it is an ergonomic change
Kyle should rule on, and the alternative (`<name>.arrival` plus an abandon ceremony) is coherent but
pre-empts his slice-6 fact.

### D.3 The two failure modes that survive, and what the design does about them

**`NotWitnessed` at mint is unrecoverable.** The genesis commits before the journal write
(`arrival_head_seam.py:1642-1669`); if the journal write fails, the store exists, `NotWitnessed`
fires, and the store's next open is labeled `first-contact` **permanently** — which is precisely the
label slice 6's exit criterion rejects. The ordering cannot be reversed (a journal cannot record a
head that does not exist yet).

Recommendation: **pre-flight the journal write before minting** — resolve the state root, create
`heads/`, write and remove a probe entry — so the common causes (missing directory, unwritable
state root, bad `XDG_STATE_HOME`) are eliminated while the failure is still free. This is a
probability reduction, not a fix, and should be named as such in the report. Residual: a disk that
fills between the probe and the genesis. Named, accepted, not detected.

**A torn tail on the target blocks restart** (§0.3(3)) and the repair is unreachable through the
wrapper. Recommendation: **do not build an in-sidecar repair.** F2 forbids verification from
repairing, and reaching around `AttestedLedger` to call `truncate_torn_tail()` would be the sidecar
granting itself the privileged path the whole design says it does not have. The honest posture is a
typed refusal naming the target, the condition, and — as advisory prose, per the content-vs-storage
contract — that the recovery is an out-of-band truncation followed by a re-open. If that recovery
deserves a verb, it is a CLI verb in slice 5, not a sidecar capability.

**One accepted cost:** a restart after an unwitnessed commit takes the `ADVANCED` branch and pays a
whole-log `verify(Full)`. Since the sidecar's own final gate is a full re-run anyway, one extra walk
on the restart path is amortized against work the migration already owes. Named, not optimized.

---

## E. The bootstrap receipt

**Recommendation: through `AttestedLedger.mint()`, obtained from `BackendRegistry.open(staging
descriptor)`, as the sidecar's first touch of the lineage. Confirmed to fit; two gaps flagged.**

The seam's producer fits the cutover moment exactly. `mint` writes `bootstrap`/`Level.MINT`
(`arrival_head_seam.py:1642-1669`), and `bootstrap()`'s own docstring names this slice as the
consumer (`:586-587`): *"Slice 4's sidecar must produce the former for every migrated store by
minting through `AttestedLedger`, and slice 6 checks it."* The registry wraps unconditionally with
no way to ask for an unwrapped ledger (`arrival_registry.py:202-216`), so the receipt is not
something the sidecar can forget to do — it is a consequence of minting at all.

Slice 3 also already delivered the prerequisite its own §0.4 flagged: `FileQuery` builds its reader
lazily (`arrival_file_backend.py:817-850`), whose docstring names *"the path slice 4's sidecar
takes to get its bootstrap receipt."* Mint-through-registry on an unmaterialized target works. That
gap is closed; I re-verified it rather than trusting the slice-3 report.

**Gap 1 — the mint must be the lineage's first journal entry, and `bootstrap()` is not idempotent.**
It appends with no dedup and no already-bootstrapped check (`arrival_head_seam.py:599-617`), and
`JournalRead.bootstrap` is defined as the journal's **first** entry
(`arrival_head_attestation.py:889-893`). A sidecar that opened the target before minting, or that
called `bootstrap()` directly, would land a late bootstrap that slice 6's check does not see.
Design obligation: **the sidecar's first contact with the target lineage is `mint()` through the
wrapper — never open-then-mint, never a direct `bootstrap()` call.** Worth a gate assertion:
`read_journal(lineage).bootstrap.level is Level.MINT` and it is entry #1.

**Gap 2 — the journal is per-user, per-machine state.** `$XDG_STATE_HOME/loops/heads/`
(`arrival_head_attestation.py:598-637`) is not git-tracked and does not travel. For slice 6's
single-operator migrations that is correct and intended. For the git-tracked project store, whether
a second copy of the journal is committed was deliberately deferred by slice 3 §A.5 to slice 6,
together with tracked-vs-gitignored. **Not re-opened here**; named so the arbiter sees it was
considered.

---

## F. `absorb`, `reanchor`, `adopt` — corrected dispositions

The plan's appendix says: *"CLI `_run_reanchor` / `_run_absorb` → demote to sidecar ceremonies"* and
*"CLI `_run_adopt` → genesis-claiming half dies; survives as descriptor lineage/role designation"*
(`plan.md:138-139`). All three need correction against the landed surface.

| Verb | Plan's disposition | Recommended disposition |
|---|---|---|
| `absorb` — genesis mode (`store.py:1063-1190`) | demote to sidecar ceremony | **Dissolves into the sidecar's `mint`.** It is not a ceremony the sidecar offers; it is a thing the sidecar's genesis makes unnecessary. Under arrival there are no genesisless stores, so nothing calls it. |
| `absorb` — edit mode (`store.py:1202-1379`) | *not in the plan* | **SURVIVES.** A live declaration-protocol feature with 30+ tests, unrelated to migration. Re-expresses onto the contract in slice 5. Demoting it would delete shipped behavior (§0.4). |
| `reanchor` (`store.py:770-849`) | demote to sidecar ceremony | **Dies outright in slice 5; slice 4 owes it nothing.** It rewrites chain rows in place — verified, `UPDATE facts SET signature = ? WHERE rowid = ?` at `sqlite_store.py:2415` — which an append-only hash-chained ledger cannot do. Its *purpose* (re-derive the attestation layer after a key change) already has an arrival successor in the grammar: a key introduction record. Migration does not need it either, because inner signatures ride verbatim and are never re-signed. There is no ceremony left to demote it to. |
| `adopt` (`store.py:1382-1437`) | genesis-claiming half dies, descriptor half survives | **The genesis-claiming half dies; the "descriptor half" does not exist yet and is slice 5's to build.** `_run_adopt` is 56 lines of pure genesis-claim; `StoreDescriptor`/`descriptor_for` have **zero** CLI reach today (§L). Slice 4 does not build the designation surface. It does, however, become the first real consumer of `StoreDescriptor.lineage` by writing it at publish (§H) — one slice earlier than slice 3 predicted. |

The unifying correction: **absorb-genesis and reanchor do not "demote to ceremonies" — they
dissolve.** The dissolution test applies cleanly: each is expressible as a property of what the
arrival design already has (a signed genesis at ordinal 0; a key introduction record). Naming them
"sidecar ceremonies" would carry two dead verbs into the one package the arc most wants to keep
small.

**Residue to sweep in the same change** (dissolution practice): `loops init`'s best-effort
`_run_absorb([])` call (`init.py:472-480`) needs a mint-shaped successor; `store_args.py:43-46`'s
`STORE_SUBCOMMANDS` tuple and `add_store_args`'s help string (`:49-62`) are a second surface held
against the dispatcher by a parity test (`test_store_completion.py:32,41`); and the base-inspect
`description=` prose at `store.py:1875-1885` is a third. Any verb change touches all three.

---

## G. Genesis and key records from the `.vertex` observers block

### G.1 Source of authority

`VertexFile.observers: tuple[ObserverDecl, ...]` (`lang/ast.py:743`), each entry
`ObserverDecl(name, identity, grant, key)` where `key` is the *public* Ed25519 key, raw-32-byte
base64 (`lang/ast.py:664-672`). Private keys live at `<vertex dir>/keys/` — the vertex's own
self-observer keeps the flat `keys/ed25519.key` layout with observer = vertex stem
(`add.py:306`, `init.py:201-202`).

**The migration custodian is the vertex's self-observer** — the only identity whose private key the
sidecar holds, and therefore the only one it can sign as. This is not a choice so much as the only
available answer, and it should be stated in the migration report rather than left implicit.

### G.2 Ordering, and why it is forced

```
ordinal 0     genesis          k="genesis"  observer = custodian
                               body = {protocol, lineage, key: <custodian public key>}
                               signed by the custodian, self-certifying
ordinal 1..k  key introduction k="key"      body = {observer: <name>, key: <public key>}
                               one per declared observer that carries a key,
                               each signed by the custodian
ordinal k+1.. migrated records k="fact"|"batch"|"tick", outer-UNSIGNED (§0.2)
```

The ordering is forced by the ruled authority clause, implemented verbatim at
`arrival.py:1962-1970`: *"a key is valid at position N iff it was introduced at a position < N, or
N is the genesis position and the record is self-certifying"*, and a key introduction is *"signed by
a key already valid for the INTRODUCING record's observer."* Only the custodian's key is valid at
ordinal 1, so the custodian introduces everyone.

**An honest statement the design must make:** because migrated records are outer-unsigned, **no
migrated record actually resolves against this registry.** The key introductions establish the
registry for *future live writes* to the migrated store; they are not what validates the migrated
content. The migrated content's authorship travels as inner fact-domain signatures, verified by the
existing fact verifier, unchanged. Writing that down matters — a reader who assumes the key
introductions are validating migrated rows has the security model backwards.

### G.3 Two edges, each owing a record

Both fall under *every-early-exit-owes-a-skip-record*, whose structural form in slice 3 is that every
line-dropping branch calls `skips.missed(...)` or `skips.re_asserted(...)`
(`arrival_head_attestation.py:1189-1259`), and whose scar tissue is a silently absorbed line that
lost the epoch maximum (`finding:s3wp1-gate-kindless-dict-absorbed-as-header`).

1. **A declared observer with `key = None`.** Cannot be introduced. Skip, with a named exception in
   the migration report. Not a refusal — the observer may simply never sign.
2. **An observer that appears in migrated rows but is absent from the observers block** — the real
   case, since foreign observers' facts arrive through merge. No public key is declared, so no
   introduction is possible. The rows are still admitted: their inner signatures ride verbatim, and
   *admit does not mean believe* (`decision:design/arrival-substrate-laws`, the admission
   boundary). Record as a named exception, do not refuse.

Neither exception is a verdict about the store. Both are location claims about what the `.vertex`
declaration does and does not cover — which is the scope-the-claim shape.

---

## H. Atomic descriptor publish

### H.1 The mechanism

The `.vertex` store clause update **is** the cutover. Mechanics:

1. Read the current `.vertex` text and parse it (the pre-edit parse is the baseline).
2. **Surgically edit the store clause line** — positional location plus the `backend=` property slice
   2 added — leaving every other byte untouched.
3. Re-parse the edited text and assert: the file parses, the store clause names the new location and
   backend, `StoreDescriptor.lineage` names the minted lineage, and **every other parsed field is
   equal to the pre-edit parse**. This is verification-by-re-parse, the same posture as
   verification-by-re-run.
4. Write to a temp file in the same directory, `fsync`, then `os.replace` onto the `.vertex` path.
   `os.replace` is atomic within a filesystem on POSIX.

**Why surgical rather than parse-and-re-emit:** there is no KDL writer in `libs/lang` — I checked;
`.vertex` files are only ever produced as raw text (`init.py:181`, `init.py:267`). A re-emit would
have to be written from scratch and would destroy hand-written comments and formatting in a
git-tracked file a human maintains. The existing precedent is text editing; the existing **gap** is
atomicity — `init.py:267` is a plain `write_text` with no temp-and-replace.

### H.2 Crash windows and the refusal posture

| Crash point | State | Recovery |
|---|---|---|
| During staging (before publish) | Legacy store authoritative; target is an unaddressed staged file | Restart from verified target head (§D.1), or abandon the lineage and start a fresh one (§D.2) |
| Between temp write and `os.replace` | Legacy store authoritative; a stray temp file | Delete the temp file; retry the publish |
| After `os.replace` | New store authoritative | None needed — this is success |

There is no partial-publish state, because the rename is the only mutation and it is atomic. That is
the whole reason for the temp-and-replace shape.

**The publish is refused unless all of these hold**, checked before the rename:

1. `verify(Full(through=head))` passes on the target.
2. The equivalence re-run (§I) matches, row for row.
3. The journal's **first** entry for the lineage is `bootstrap`/`Level.MINT` (§E gap 1).
4. The inventory equality holds (§I).
5. The legacy store is quiesced — the operator's obligation from `plan.md:81`, asserted rather than
   assumed: the sidecar records the legacy store's content hash at snapshot time and re-checks it
   immediately before publish. A changed source means an ordinary writer touched it during staging,
   which is *"two histories, not a migration"* (`protocol.html` §09 *No dual authority*).

(5) is the one check that is not obvious from the obligations list, and it is cheap: the content
hash is already being computed for the equivalence evidence.

**After cutover the legacy store becomes read-only archival evidence and never resumes writes**
(`backend-contract.html` §11). The sidecar should not delete it; that is an operator decision in
slice 6.

---

## I. Inventory, equivalence evidence, restartability evidence

### I.1 The migration report

A sidecar-side artifact, signed by the custodian, living beside the target and referenced by nothing
in the ledger — **evidence, not authority** (§0.5: an in-ledger provenance record is explicitly
deferred to a future namespaced extension kind).

Contents, mapped to the obligations:

| Obligation | Field |
|---|---|
| Declare the source format and tool version | `source_format` (`jsonl-canonical` \| `sqlite-canonical`), `tool_version` |
| Read a stable source snapshot without mutating it | `source_content_sha256` (witness-order row hash — the *verifiable* claim), `source_file_sha256` (forensic), both from `rebirth.py:193-219`'s existing distinction, re-checked at publish (§H.2(5)) |
| Source inventory | per-kind row counts, tick count, batch-line count, total lines, observer census |
| Target head | `lineage`, `ordinal`, `record_hash` |
| Exceptions | keyless declared observers (§G.3(1)), undeclared observers appearing in rows (§G.3(2)), any dropped or out-of-scope row, each with its source coordinate |
| Deterministic equivalence evidence | the transform rule name, and the re-run diff result |

`rebirth.py`'s two-hash distinction is worth carrying over verbatim, including its reason
(`rebirth.py:196-199`): the file hash is *not* the verifiable identity because WAL checkpoints,
VACUUM, and page layout change bytes without changing content.

### I.2 Equivalence = re-run and diff, not a count check

Keep `rebirth.py`'s verification-by-re-run (`rebirth.py:616-641` is the existing diff loop), for the
reason the plan gives: it is stronger than the ledger's `verify(scope)`. `verify(Full)` establishes
that the target is internally consistent — density, record hashes, chain linkage, signatures. It
says nothing about whether the target holds *what the source held*. The re-run does, because it
re-derives what should be there from the unmodified source and compares row by row.

Both run. They answer different questions and the report names both answers.

The diff is over the **logical rows**, not the records: for each source row in ruled order, the
target must hold a row with identical `(kind, ts, observer, origin, payload_text, signature)` and a
possibly-migrated id per the transform. Framing (which record a row landed in, at which
ordinal/seq) is target-side and is not part of the equivalence claim — which is consistent with
§A.2(b): the inner commitment excludes framing.

### I.3 Inventory equality, precisely

The plan's gate is "inventory equality" (`plan.md:99`). Made precise: **per-kind row counts, tick
count, and observer census are equal between the source inventory and the target's projection**,
after accounting for the enumerated exceptions. Record counts are deliberately *not* compared —
under arrival an N-row ceremony is one record (`arrival_store.py:530-535`) while the legacy jsonl
store spent N ordinals on it (§A.2c), so a record-count equality would be false by construction.

### I.4 Restartability evidence

The gate asserts the property, not the mechanism: kill the migration mid-append, restart, and the
final target must be **byte-identical** to the target an uninterrupted run produces from the same
source. That works only because the transform is deterministic, which is the property the whole
design leans on.

---

## J. Work packages and the test strategy

### J.1 Five work packages

Sized against slice 2's five and slice 3's three. The seam between WP1 and WP2 is deliberate: GF-3's
refusal belongs to the inventory pass (WP1), the batch grammar to the transformer (WP2), and keeping
them in one package would let the refusal drift to re-mint time — the failure mode §A.5(1) exists
to prevent.

**WP1 — `libs/migrate` and the frozen `LegacySource`.** New workspace package; Rule 4 row; Rule 7
`_SQLITE_ALLOWED_LIBS` entry; frozen jsonl-canonical and sqlite-canonical readers (moved, not
imported — §B.2); `ulid_migration` quarantined; the inventory pass; **the GF-3 refusal, typed, in
the sidecar's own family, enumerating every offending source line.**
*Exit:* Rule 4 green with the outward quarantine proven by a deliberate violation test; the mixed-
observer fixture refuses in the inventory pass **and the target path does not exist afterwards**;
inventory counts match a hand-computed fixture; no import edge from `libs/migrate` to
`engine.jsonl_store`.

**WP2 — the `Transformer`.** Row → `RecordDraft`; group grammar (single-observer batch → one batch
record, single row → one fact record); inner signatures byte-for-byte; the outer-unsigned decision
(§0.2) with its rationale in the module docstring; genesis + key-record minting from the `.vertex`
observers block (§G) including both exception edges.
*Exit:* signature byte-comparison over a fixture carrying signed and unsigned rows; key-introduction
ordering asserted against `verify_authorship`; both §G.3 exceptions land in the report; determinism
proven by re-running the transform and comparing.

**WP3 — the `ArrivalSink`, restart, and verification.** Registry open; mint-through-wrapper with the
journal pre-flight (§D.3); the append loop; `verify(Full)`; the equivalence re-run; the resume
derivation (§D.1); the lineage-named staging path (§D.2).
*Exit — against real stores, not mocks:* (1) full round-trip on a synthetic legacy store — inventory
equality, signature preservation, target verifies Full; (2) kill mid-append, restart, final target
byte-identical to an uninterrupted run; (3) the journal's first entry is `bootstrap`/`mint`;
(4) torn-tail target refuses with the typed refusal and **does not repair** — assert the target bytes
are unchanged afterwards (the F2 gate, in slice 3's WP3 shape); (5) a second migration attempt after
an abandoned one succeeds at a fresh lineage-named path with no `StoreLost`.

**WP4 — the CLI surface and the verb dispositions.** In parallel with WP3 once WP2's exit fixes the
sidecar API (disjoint files). The migrate verb; absorb-genesis and reanchor dispositions (§F) staged
for slice 5 rather than executed here; `loops init`'s successor named; `store_args.py` +
dispatcher + base-inspect prose kept in lockstep (`test_store_completion.py:32,41` is the parity
net).
*Exit:* dispatcher/completion parity green; `loops init` still opens a lineage on a fresh store.

**WP5 — docs and residue, last.** `protocol.html` / `backend-contract.html` catch-up; the stale
`arrival.py` keyless-genesis prose (§L-2); `libs/store/CLAUDE.md`'s Level 1.5 Rebirth section;
`libs/migrate/CLAUDE.md`; Rule 17/18 sweeps.

### J.2 The synthetic legacy store

One fixture builder, parameterized over both source formats, producing:

- facts across all three id eras — uuid4, lowercase ULID, canonical ULID — so `ulid_migration` is
  exercised on the same shapes the live stores actually carried (`rebirth.py:128-154` documents all
  three);
- signed and unsigned facts, so signature pass-through and honest-NULL both run;
- ticks, which re-enter as facts (`rebirth.py:251-278`) — note this is the one transform behavior
  that needs re-deciding under arrival, since arrival has a native `tick` record kind and the
  legacy tick-re-entry-as-fact shape may no longer be right. **Flagged as open question M-4.**
- **single-observer** batch lines, the legal ceremony shape;
- a **mixed-observer batch** fixture, constructed rather than found. It is constructible today:
  `object_of_batch([fact_row("01A", observer="kyle"), fact_row("01B", observer="someone-else")])`,
  the exact construction already used by
  `test_arrival_body.py:157-167` (`test_the_line_codec_does_NOT_carry_the_same_observer_rule`). This
  fixture is GF-3's gate and must assert the refusal fires **before** the target exists;
- a `.vertex` with multiple declared observers, one keyless, plus rows from an undeclared observer —
  §G.3's two edges;
- an empty store and a genesis-only store, the degenerate cases.

---

## K. Non-goals

- **No compat mode in the new runtime.** The point of the quarantine.
- **No `replicate` path.** Legacy sources have nothing to replicate (§C).
- **No in-ledger provenance record.** Deferred to a future namespaced extension kind
  (`protocol.html` §09).
- **No mixed-observer batch handling beyond the refusal** (§A.5). If one ever appears, that is when
  the design gets made, with the instance in hand.
- **No trust-reset, no binding clearing, no fence interaction.** `design:arrival-reset-descendant-
  acceptance` is open at Kyle's slice-6 gate; the interim law is refuse-and-re-decree and this design
  stays inside it (§D.2).
- **No torn-tail repair in the sidecar** (§D.3).
- **No `absorb`-edit changes, no `reanchor` port, no descriptor-designation CLI** — slice 5's (§F).
- **No consumer rewiring.** The ~30 `open_canonical_store` importers, the SDK's `canonical_mode`
  surface, and the CLI resolvers stay on today's path (`plan.md:69`, spine constraint 7).
- **No live-store migration.** Slice 6 is the operational arc; slice 4 builds the tool and proves it
  on synthetic stores.
- **No DuckDB sink.** The sidecar sees a generic staged target by design, but the second backend is
  the next arc's.

---

## L. Arbiter inputs — plan-anchor drift and contract contradictions

Reported, deliberately not resolved here.

### L.1 Drifted plan anchors

| Plan claim | Actual at 8a3ed22d |
|---|---|
| `apps loops store.py` | **`apps/loops/src/loops/commands/store.py`** (1903 ln). `apps/loops/src/loops/cli/views/store.py` is a 41-line shim; anchor nothing there. |
| `_run_absorb` at `:948–1380` | `_run_absorb` is **`:948-1060`**. The plan's range spans four functions: `_run_absorb`, `_absorb_genesis_mode` (`:1063-1190`), `_decl_short` (`:1193-1199`), `_absorb_edit` (`:1202-1379`). |
| absorb "signs genesis over pre-genesis legacy rows" (i.e. requires a genesisless store) | **Bimodal.** Genesisless → genesis mode; genesis + `own_lineage` marker → **edit mode**, a live shipped feature; genesis without marker → refusal pointing at `adopt`. §0.4. |
| `_run_adopt`: "genesis-claiming half dies; survives as descriptor lineage/role designation" | **There is no descriptor half.** `_run_adopt` is `:1382-1437`, 56 lines of pure genesis-claim. `StoreDescriptor` / `descriptor_for` (`arrival_contract.py:292`, `arrival_registry.py:68`) have **zero** CLI reach. That half is build, not port. |
| `_run_reanchor` at `:770–849` | **Exact, no drift.** |
| rebirth coupling at `store.py:672` | **Exact line**, but it is the `from store import identity, rebirth_store, ulid_migration, verify_rebirth` import; the calls are `:687` and `:694`, wrapped by `loops store rebirth`. |
| "the CLI's twin resolvers already encode the canonical-vs-index split — rename into the contract" (`plan.md:42`), implying slice 2 did it | **Slice 2 did not.** `resolve_store_path` (`:52-72`) and `resolve_canonical_path` (`:75-100`) are unchanged and unrenamed. Consistent with SD-7 (slice 2 is build-and-prove, no consumer rewiring) — the plan prose reads as if it had happened. |
| `fact_commitment_hash` at `sqlite_store.py:271–299` | **Moved to `admission.py:194-217`** in slice 2; `sqlite_store.py:39-41` re-exports. Those lines are now the `facts` table DDL. |
| `_stage_arrival_coordinates` / `_stamp_arrival_axis` | **Do not exist under those names.** The live machinery is `_allocate_ceremony_coordinates` — `sqlite_store.py:1436-1442` (base) and the arrival override `arrival_store.py:530-535`. Consistent with arbiter ruling SD-1 (they were §07 projection, not §04 mint) but the plan's names are gone. |
| `arrival_head_seam.py:576` (bootstrap), `:976` (second-path comment), `:1643` (mint-through-wrapper) | `bootstrap` at **`:576-617`** ✓; the second-path comment at **`:971-979`** (not 976); mint at **`:1642-1669`** ✓. |
| `arrival_file_backend.py:822` "names the sidecar's bootstrap path" | ✓ — inside `FileQuery`'s docstring, `:817-831`. |
| `rebirth.py` `ulid_migration :128–150`, `rebirth_store :342`, `verify_rebirth :525` | ✓ all three (`ulid_migration` runs `:128-154`). |

### L.2 Contract contradiction — keyless / containment genesis

**`arrival.py`'s prose says the sidecar mints a keyless, containment-carrying genesis. The ratified
`protocol.html` says it does not.**

`arrival.py:565-571`:

> `f"genesis carries no well-formed founding key ({key_fault}) — a live-store genesis introduces the
> founding public key at ordinal 0; a keyless genesis belongs to the migration sidecar, not to this
> grammar"`

`arrival.py:889-892` (in `mint`'s docstring):

> "era pins dissolve under the dense ordinal; **containment claims belong to the migration sidecar's
> genesis**, never to a live store's."

`protocol.html` §09, *One genesis grammar*:

> The sidecar mints an **ordinary signed target genesis** under the migration custodian. It **does
> not introduce a second keyless or containment-only genesis** into the core protocol. Source
> fingerprints, counts, exceptions, and equivalence claims live in the signed migration report and
> bootstrap witness receipt.

The code prose predates the suite's ratification (it reads as slice-A-era). Under the ratified
design there is no keyless sidecar genesis and no containment claim in the ledger — this proposal is
written to the ratified text (§G mints an ordinary signed genesis under the custodian; §I puts the
containment claims in the report). **The stale prose is residue that slice 4 should sweep in the
same change** (dissolution practice), but the arbiter should confirm the reading rather than have a
design agent silently overwrite a grammar docstring.

### L.3 Contract tension — the batch-integrity clause's scope

`backend-contract.html` §04's *"Backend batching must not rewrite one semantic batch into several
fact records or vice versa"* sits in the append-transaction section and is addressed to backends.
§A treats it as binding the transformer, on the ground that the sidecar is an ordinary caller with
no privileged path and a rule constraining every backend constrains the caller whose job is
producing records for them. **That reading is load-bearing for the GF-3 recommendation and the
arbiter should confirm it.** If the clause is ruled backend-scoped only, the split arm returns to the
table and §A.6's "split, and record the regrouping in the migration report" row is the shape it
should take.

### L.4 A stale in-repo claim (not plan drift, but it bites WP4)

`_absorb_genesis_mode`'s docstring (`store.py:1076`) claims its output is *"golden-locked, so the
rendering is preserved verbatim."* No golden under `apps/loops/tests/golden/` covers absorb, genesis,
adopt, or reanchor output. There is no golden net for these renderings; do not rely on one.

---

## M. Open questions for Kyle

Each with a recommended answer. **M-1 is the ratify-gate.**

**M-1. GF-3: refuse or split?**
*Recommendation: **refuse**, in the inventory pass, before any target bytes exist, with a typed
sidecar refusal that enumerates every offending source line and names no remedy in the type (§A.5).*
The decisive arguments are that `backend-contract.html` §04 forbids the split's exact operation
(§0.1, subject to L.3's scope confirmation); that the refusal is free today and structurally so — no
writer in this codebase can produce a mixed batch (§A.4); and that splitting decides silently what an
unknown author meant, whereas refusing surfaces it to the one party who can adjudicate. The
signature-preservation obligation everyone reaches for first turns out to be entirely orthogonal
(§A.2b). If a mixed batch ever appears, the design gets made then, with the instance in hand.

**M-2. Is the staging target lineage-named?**
*Recommendation: **yes** — `<store-dir>/<lineage>.arrival` (§D.2).* It dissolves the `StoreLost`
retry trap, which has no in-band recovery, without building the abandon ceremony that would pre-empt
`design:arrival-reset-descendant-acceptance` at your slice-6 gate. The cost is ergonomic: store files
are named by ULID rather than by vertex. After slice 5 the `.vertex` descriptor is the only resolver,
so filename legibility stops being load-bearing — but it is a visible change and it is yours to rule
on. The alternative is `<name>.arrival` plus an explicit abandon ceremony that clears the binding and
journal; coherent, but it builds slice-6 vocabulary a slice early.

**M-3. Does the migration report live beside the target as a signed file, or somewhere else?**
*Recommendation: **beside the target**, `<lineage>.migration-report.json`, signed by the custodian,
referenced by nothing in the ledger (§I.1).* `protocol.html` §09 requires the claims to live in "the
signed migration report and bootstrap witness receipt" and forbids an in-ledger provenance record, so
the only real question is where the file goes. Beside the target keeps evidence and subject together
and travels with a copy of the store.

**M-4. Do legacy ticks still re-enter as facts?**
*Recommendation: **no** — migrate them as arrival `tick` records.* `rebirth.py:251-278` converts each
source tick into a fact of kind `tick.<name>` with the chain envelope in the payload, because
sqlite→sqlite rebirth had no other home for them. Arrival has a native `tick` record kind, so the
re-entry shape is a workaround for a constraint that no longer exists — the dissolution test applies.
This changes the fixture expectations and the equivalence diff, so it needs deciding before WP2, not
during. Flagged because it is the one place where "rebirth.py is the skeleton" would quietly carry a
legacy shape into the new runtime.

**M-5. Does the sidecar refuse a source whose content hash changed during staging?**
*Recommendation: **yes**, at publish time, as a refusal (§H.2(5)).* `protocol.html` §09's *No dual
authority* says concurrent writes on both sides are "two histories, not a migration", and `plan.md:81`
already makes quiescing the operator's obligation for slice 6. Making it an asserted precondition
rather than a trusted one costs nothing — the content hash is already computed for the equivalence
evidence — and it converts a silent corruption into a refusal.

**M-6. Five work packages, or fewer?**
*Recommendation: **five** (§J.1), with WP3 and WP4 in parallel worktrees after WP2's exit.* WP1/WP2
are split specifically so GF-3's refusal lives in the inventory pass and cannot drift to re-mint
time. If the arbiter prefers three, the merge is WP1+WP2 — but the brief must then pin the refusal's
placement explicitly, because that placement is the whole difference between refusing before the
target exists and refusing after three million records are written.

---

## Load-bearing claims for spot-check

| # | Claim | Cite | Provenance |
|---|---|---|---|
| 1 | Slice-4 scope: frozen LegacySource → Transformer → ArrivalSink, no compat mode in the runtime | `plan.md:57-65`; `design:arrival-break-implementation` | plan + ratified fact |
| 2 | Sidecar obligations list (7 items) incl. "exceptions" and "resumed only from a verified target head" | `protocol.html` §09 (offset 23434) | design source |
| 3 | Publication contract: staging location/namespace, unaddressable by ordinary writers, atomic descriptor change, legacy becomes read-only | `backend-contract.html` §11 (offset 30913) | design source |
| 4 | **"Backend batching must not rewrite one semantic batch into several fact records or vice versa"** | `backend-contract.html` §04 (offset 13208) | design source — **decides M-1, scope confirmed in L.3** |
| 5 | Sidecar mints an *ordinary signed* genesis; no keyless or containment-only genesis; claims live in the signed report + bootstrap receipt | `protocol.html` §09 *One genesis grammar* | design source |
| 6 | Legacy conversion is admission into a new lineage; backend movement is exact replication + re-custody | `protocol.html` §09 *Legacy conversion versus backend movement* | design source |
| 7 | "Merge that re-coordinates content is an admission operation into another lineage, not replication" | `backend-contract.html` §08 *Portable import* | design source |
| 8 | `body_of_batch` refuses mixed observers; type `ArrivalBodyError(ValueError)`; decided on each row body's `observer`, not the envelope's | `arrival_body.py:179-191,238,241-266,81-89` | code, verified |
| 9 | Enforced at encode **and** decode | `arrival_body.py:179-191,282-285` | code, verified |
| 10 | Two production callers of `body_of_batch`, both on the sidecar's path | `arrival_store.py:565`; `admission.py:486` | code, verified |
| 11 | Nothing in `libs/` or `apps/` catches `ArrivalBodyError` | repo-wide grep | verified |
| 12 | Inner commitment is `(kind, ts, observer, origin, payload_text)` — excludes framing, ordinal, batch membership | `admission.py:194-217`; `arrival_body.py:48-53`; `test_arrival_body.py:225-232` | code, verified |
| 13 | `fact_commitment_hash` moved from `sqlite_store.py` to `admission.py` in slice 2 | `admission.py:194-217`; `sqlite_store.py:39-41` | code, verified — **plan drift** |
| 14 | A legacy batch envelope admits only `t` and `rows` — no outer signature exists to lose | `jsonl_codec.py:142` | code, verified |
| 15 | The legacy codec permits mixed-observer batches; `_validate_batch` never checks `observer` | `jsonl_codec.py:381-427`; `test_arrival_body.py:157-167` | code, verified |
| 16 | No writer in this codebase can emit one: only `absorb_edit` reaches `serialize_batch`, and it takes one `observer` for the whole ceremony | `jsonl_store.py:679`; `sqlite_store.py:1803,1612-1619,1756-1774` | code, verified |
| 17 | Census: 44,481 lines scanned across repo + `~/.config/loops`; 9 batch lines (all negative fixtures); **0 mixed-observer batches**; no `.arrival` exists anywhere | empirical scan | verified this session |
| 18 | Arrival: one record = one ordinal (seq 0..N-1). Legacy jsonl: one batch line = N ordinals | `arrival_store.py:530-535`; `sqlite_store.py:1436-1442` | code, verified |
| 19 | `query_facts` promises no record is split across pages, enforced by shared ordinal | `store_reader.py:797-800,864-892` | code, verified |
| 20 | `receipt_group_span` tolerates contiguous ordinals; `WitnessPosition` identity is a fact id; `GlobalReceiptPosition` does not exist | `witness.py:231-274,19-24,26-30` | code, verified |
| 21 | An unsigned ordinary record is legal and skipped by the authority walk | `arrival.py:2044-2045` | code, verified |
| 22 | Genesis and key introductions are the only records structurally required to carry a signature | `arrival.py:551-596` | code, verified |
| 23 | Key validity rule: valid at N iff introduced at < N, or N=0 self-certifying; introductions signed by an already-valid key for the introducing observer | `arrival.py:1962-1970` | code, verified |
| 24 | A record's signature is tried only against keys valid for its **own** observer | `arrival.py:1971-1978` | code, verified |
| 25 | Envelope observer per kind: genesis=custodian, fact=author echo; outer signature is the arrival-content signature, the inner fact signature is what travels | `decision:design/arrival-wire-v1-pin` | ratified fact |
| 26 | `.vertex` observers carry public Ed25519 keys; private keys live at `<vertex dir>/keys/` | `lang/ast.py:664-672,743`; `add.py:306`; `init.py:201-202` | code, verified |
| 27 | `bootstrap()` at `:576-617`; validates level only; touches no store; **not idempotent**, no dedup | `arrival_head_seam.py:576-617` | code, verified |
| 28 | `JournalRead.bootstrap` is the journal's **first** entry — a late bootstrap is not the receipt slice 6 checks | `arrival_head_attestation.py:889-893` | code, verified |
| 29 | `mint` through the wrapper writes `bootstrap`/`MINT`; store-first, journal-second; failure raises `NotWitnessed` and the label is permanent | `arrival_head_seam.py:1642-1669`; `:232-259` | code, verified |
| 30 | The registry wraps unconditionally — no unwrapped ledger, no flag, no privileged path | `arrival_registry.py:189-229,202-216`; `arrival_head_seam.py:19-23` | code, verified |
| 31 | `FileQuery` builds its reader lazily so an unmaterialized target can be opened and minted into — slice 3 closed this for slice 4 | `arrival_file_backend.py:817-850` | code, verified |
| 32 | Delegation is explicit method-by-method; `truncate_torn_tail` and `import_prefix` are unreachable through the wrapper | `arrival_head_seam.py:915-923` | code, verified |
| 33 | The fence returns early when no `trust-reset` exists — inert for a migration that never resets | `arrival_head_seam.py:1319-1327` | code, verified |
| 34 | Re-mint at a remembered location refuses `StoreLost` before the ledger is handed back; `trust_reset` does not clear it | `arrival_head_seam.py:1164-1197`; `test_a_re_mint_under_a_remembered_location_refuses_too` | code + test, verified |
| 35 | `PRE_GENESIS` is the sidecar-about-to-mint branch and the seam makes no claim there | `arrival_head_attestation.py:466`; `arrival_head_seam.py:302-317` | code, verified |
| 36 | A torn tail routes to `StoreLost`; the repair is `ArrivalLog.truncate_torn_tail()` | `arrival.py:1254,1837` | code, verified |
| 37 | The journal lives at `$XDG_STATE_HOME/loops/heads/<lineage>.jsonl`, lineage-keyed, append-only | `arrival_head_attestation.py:598-637` | code, verified |
| 38 | Content-vs-storage: the type asserts what the read lacks; remedy is advisory prose chosen per cause | `arrival_head_attestation.py:228-263,266-280` | code, verified |
| 39 | Every early exit owes a skip record; per-cause × position weighting | `arrival_head_attestation.py:1189-1259,1098-1187` | code, verified |
| 40 | Rule 18 denies a mode flag for a safety property — "custody is structural, not configured" | `test_rule_18_arrival_vocabulary_denylist.py:94-111` | code, verified |
| 41 | Rule 4's `LIBS` is glob-derived, so a new lib auto-enrolls and the outward quarantine is free | `_helpers.py:30`; `test_rule_04_lib_dependency_dag.py:16-40` | code, verified |
| 42 | Rule 7 confines `sqlite3` to engine + store — needs a `migrate` entry | `test_rule_07_...py:13` | code, verified |
| 43 | `commands/store.py` is already on Rule 15's shrink-only EXCEPTIONS list, so a CLI→sidecar import grows no allowlist | `test_rule_15_...py:44` | code, verified |
| 44 | `rebirth.py` is sqlite→sqlite: raw `sqlite3` reads, raw `INSERT` writes, never touches `Head`/contract/registry | `rebirth.py:385,432-446` | code, verified |
| 45 | `_expected_rows` is the shared spine of write and verify — "same function, write then check" | `rebirth.py:281-320` | code, verified |
| 46 | Rebirth lands its receipt **inside** the target as a `rebirth` fact — the placement that does not carry over | `rebirth.py:439-446` | code, verified |
| 47 | Two source hashes with different jobs: content hash is verifiable, file hash is forensic | `rebirth.py:193-219` | code, verified |
| 48 | Transform determinism is what makes verification a re-run | `rebirth.py:96-99` | code, verified |
| 49 | Legacy ticks re-enter as `tick.<name>` facts with the chain envelope verbatim in the payload | `rebirth.py:251-278` | code, verified — **basis of M-4** |
| 50 | `_run_absorb` is `:948-1060` and bimodal; `_absorb_edit` `:1202-1379` is a live feature with 30+ tests | `commands/store.py:948-1060,1039-1060,1202-1379`; `tests/test_store_absorb.py` | code, verified — **plan drift** |
| 51 | `loops init` calls `_run_absorb([])` best-effort | `commands/init.py:472-480` | code, verified |
| 52 | `_run_reanchor` rewrites chain rows in place: `UPDATE facts SET signature = ? WHERE rowid = ?` | `commands/store.py:770-849`; `sqlite_store.py:2364,2415` | code, verified |
| 53 | `_run_adopt` is 56 lines of pure genesis-claim; `StoreDescriptor`/`descriptor_for` have zero CLI reach | `commands/store.py:1382-1437`; `arrival_contract.py:292`; `arrival_registry.py:68` | code, verified — **plan drift** |
| 54 | `StoreDescriptor.lineage` is checked against genesis rather than trusted; forcing consumer named as slice 5's adopt | `arrival_contract.py:302-303`; `arrival_registry.py:94-97` | code, verified |
| 55 | The store verb surface has three parallel spellings held by a parity test | `commands/store.py:1775-1792,1875-1885`; `cli/store_args.py:43-62`; `tests/test_store_completion.py:32,41` | code, verified |
| 56 | No KDL writer exists in `libs/lang`; `.vertex` files are written as raw text, non-atomically | `commands/init.py:181,267`; `libs/lang/src/lang/` grep | verified |
| 57 | F2 with the absent⇒create carve-out; refusal root narrow form; import is a procedure, not an op | `decision:design/arrival-slice2-contract-text` rulings 1, 2, 4 | ratified fact |
| 58 | `replicate` validates-never-assigns and checks the supplied record hash | `decision:design/arrival-slice2-contract-text` SD-3 | ratified fact |
| 59 | Admission boundary: admit does not mean believe | `decision:design/arrival-substrate-laws` | ratified fact |
| 60 | Spine: witness (3) before sidecar (4); sidecar (4) before deletions (5); CLI cut independent | `plan.md:111-113` | plan |
