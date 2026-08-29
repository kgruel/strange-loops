# Slice 3 design proposal — witness minimum (head attestation)

Arc: `design:arrival-break-implementation`. Slice: 3. Status: **proposed, awaiting arbiter
ratification** (ratify-gate-one-level-down — slice 4's sidecar writes the bootstrap receipt
this slice defines, and slice 6's adoption ceremony caches every store's head through it).

Design of record: `docs/architecture/arrival/witness-protocol.html` (Security draft v1),
especially §04 the head attestation, §05 issuance, §07 the comparison state machine, §09 the
audit layers, and §11 recovery. Ratified scope: `decision:design/arrival-suite-review-dispositions`
§1 (head cached outside every authority + bootstrap receipt at migration + compare on every
open + periodic full chain-plus-projection audit; signed grammar, notary and quorum DEFERRED)
and §2 (counts optional) and §3 (vocabulary: **head attestation** in code, `witness` stays the
read-path cursor). Plan of record: `plan.md:47-55` (slice 3), `plan.md:111` (spine constraint
5), `plan.md:98` (the comparison-state conformance family).

Every load-bearing claim carries a `file:line` cite, gathered in the spot-check table at the
end. **Four findings that change what the impl agent builds are reported in §0**, and **one
question for Kyle is flagged in §A.5**.

---

## 0. Four findings the plan could not have known, stated up front

Each of these changes the build. All four are cost or evidence facts about the landed slice-2
surface, not reinterpretations of the ratified scope.

### 0.1 The §07 pseudocode's descent check is O(entire history) in this backend

`witness-protocol.html:407` sketches `suffix = source.scan(after=known, through=presented)` for
the ADVANCED branch. `FileLedger.scan` iterates `self._log.walk()` from ordinal 0 and filters
(`arrival_file_backend.py:646`), and `ArrivalLog.walk` verifies every record from genesis
(`arrival.py:1112`). So "verify the suffix" costs a full walk regardless of how short the
suffix is. The same is true of `head_at`: it resolves through `ArrivalLog.read`, which is
documented as *"reached by a verified walk"* and scans from ordinal 0
(`arrival.py:1196-1209`).

ADVANCED is the common case for a naive design — every open after any write — so a per-open
descent check would put a full walk on the ingest path of a 111MB store. That is the O(n²)
shape the characterization work already found once.

**Resolution (§D.3): the writer journals its own commit.** An append that succeeded has
already compared the full head under the fence (`Commit.before`/`Commit.after`,
`arrival_contract.py:184-196`; F1 closed in slice 2 so the CAS compares all three head fields)
— which is the *strongest available* descent evidence, obtained for free. Recording the head
at commit time means the next open sees `P == K` and classifies UNCHANGED from one O(1) tail
read. The expensive descent check survives, but only on the branch where someone advanced the
lineage *without* journaling — a foreign host, a restore, an unwrapped legacy writer — which
is exactly the branch that deserves to pay.

This also means **no byte-offset hint is needed in the attestation record**, so the grammar
stays free of backend-scoped fields.

### 0.2 `head_at` is consumed on the divergent path, not per open

The slice-2 sitting admitted `head_at` as the tenth op with slice-3 compare-on-open named as
one of its two forcing consumers (`decision:design/arrival-slice2-contract-text`, ruling 3).
Given 0.1, this proposal consumes it where its cost is affordable and its answer is needed:
resolving a projection watermark into a verified head when the cheap comparison has *already*
said the projection and the ledger disagree, and inside the periodic full audit. Not on every
open. This reconciles with the ruling rather than contradicting it — the op is what turns
"these coordinates disagree" into a statement the ledger vouches for, and that is a diagnosis,
not a fast path.

### 0.3 Compare-on-open cannot be universal before slice 5, and the honest seam is the registry

There are two open species today and they do not share a funnel. Writes go
`open_canonical_store` → `ArrivalStore.__init__` → unconditional `catch_up()`
(`jsonl_store.py:272`, `arrival_store.py:143-182`). Reads mostly never construct a store at
all: `resolved_index` → `ensure_index` → `ensure_arrival_index` → a bare `StoreReader` over
the sqlite index (`jsonl_store.py:370,323`, `arrival_store.py:742`, `store_reader.py:53`), and
`loops ls` skips even that funnel, reading through the pure `residence.resolve_store_path`
(`vertices.py:7,139,237`), which by its own docstring *"does not check existence and does not
materialize a missing index"* (`residence.py:176-186`).

A seam that catches every open therefore cannot be placed in `ArrivalStore`. And there is a
second, decisive reason not to put it there — §D.2: `catch_up()`'s shrunk-log arm **rebuilds
the index**, which destroys the projection rows that testify to tail truncation. Detection
placed after open-time recovery is detection of a state the recovery just manufactured.

**Resolution: the seam is `BackendRegistry.open`** (`arrival_registry.py:181`), whose opener
performs no recovery at all — `_open_file_backend` constructs an `ArrivalLog`, which is
*"cheap to construct and holds no open file"* and does no I/O whatsoever
(`arrival.py:838-865`). Consequence, stated plainly: **"compare on
every open" becomes true when slice 5 rewires the ~30 `open_canonical_store` importers onto
the registry**, which is where the plan already puts that rewiring (`plan.md:69`,
`plan.md:108`). In slices 3–4 the seam covers the registry's callers — which is the sidecar,
the one store that matters, because it is the store being minted. Slice 6's exit criterion
"compare-on-open live" (`plan.md:80`) is satisfied at that point by construction.

The arbiter can veto this reading; the alternative is a second call site inside
`ArrivalStore.__init__` that slice 5 deletes, placed after a repair that can erase the
evidence. §D.2 argues that alternative is not merely redundant but wrong.

### 0.4 A landed-surface gap this design surfaces: `BackendRegistry.open` cannot open a store that has no projection yet

`_open_file_backend` eagerly constructs `FileQuery(index_path_for(location))`
(`arrival_registry.py:144`), and `FileQuery.__init__` eagerly constructs a `StoreReader`
(`arrival_file_backend.py:818-820`), which **raises `FileNotFoundError` when the index does not
exist** — by its own docstring, *"Does not create the file or parent directories"*
(`store_reader.py:45-57`). So opening a descriptor whose store has never been materialised
fails before any op can run.

Two consequences, both slice-3-relevant and neither invented here:

1. **`mint` is unreachable through the registry.** Slice 4's sidecar mints a fresh lineage at a
   location where neither the `.arrival` nor the `.db` exists. If it opens through the registry
   — which §D.4 says it should, so that the bootstrap receipt needs no privileged path — it
   cannot get as far as `mint()`.
2. **It contradicts the F2 carve-out.** Ruling 1 states that *materialising a projection that
   does not yet exist is not repair* (`decision:design/arrival-slice2-contract-text`), i.e. the
   contract explicitly anticipates an absent projection; the adapter cannot currently represent
   one.

This is not slice 3's to redesign, and it is deliberately *not* folded into a WP as a contract
change. The minimal fix inside slice 3's own seam is for the opener to build `FileQuery`'s
reader lazily (the query half already opens its `store_meta` connection per call for exactly
this kind of freshness reason, `arrival_file_backend.py:777-796`), which is a change confined
to the adapter and changes no contract text. **Flagged for the arbiter**: confirm this belongs
to WP3 rather than deferring it to slice 4, where it would block the sidecar on its first day.

---

## A. The head-cache home

### A.1 The test every candidate must pass

The dispositions state the failure being closed: *"the resume mark lives in the sqlite index —
inside the same rewrite boundary as the thing it would witness"*
(`decision:design/arrival-suite-review-dispositions` §1). So the home must satisfy: **a single
restore, checkout, rsync, or `rm -rf` that reverts the store must not also revert the cache.**
`witness-protocol.html:358-365` states the weaker form as a warning — a witness colocated with
the authority *"may be one copy; it cannot be the only copy."*

### A.2 The candidates, and why four of them fail

| Candidate | Verdict |
|---|---|
| Sibling file beside the store (`<name>.arrival.heads`) | **Fails.** Same directory, same backup set, same restore. Restoring `.loops/data/` from an old backup restores the cache with it. Reachable by every operation that reaches the store. |
| `.loops/state/` — inside `.loops/`, outside `data/` | **Fails.** One directory of separation inside one gitignored subtree (`.gitignore:37` ignores `.loops/` wholesale, so nothing there is git-durable either). A `.loops/`-level restore moves both. |
| Under `~/.config/loops/` | **Fails, and fails worst.** The live config-level stores *are* `~/.config/loops/*/data/*` — for those stores this is the sibling-file case with extra steps. Parts of that tree also carry their own `.gitignore` files, i.e. it is partly dotfile-tracked, so a dotfile restore is a second whole-tree rewrite boundary. |
| Git-tracked in the repo | **Fails as the sole home.** Only one store (the project store) lives in a repo at all, and slice 6 has an unmade decision about whether the migrated `.arrival` becomes git-tracked (`plan.md:83`). If it does, a `git checkout` of an old commit reverts store and cache together. See A.5. |
| A per-user **state** root, separate from both config and repo | **Passes.** Outside `$XDG_CONFIG_HOME` (where the config stores live) and outside every repo (where the project store lives). No single restore of either store location touches it. |

### A.3 Recommendation: `$XDG_STATE_HOME/loops/heads/`, keyed by **lineage**

```
$XDG_STATE_HOME/loops/heads/<lineage>.jsonl     # one append-only journal per lineage
$XDG_STATE_HOME/loops/heads/bindings.jsonl      # location → lineage, transitional (A.6)
```

`$XDG_STATE_HOME` defaults to `~/.local/state`. The repo has no state-root precedent — only
`XDG_CONFIG_HOME`, re-derived inline at three sites (`vertex_reader.py:59`,
`resolve.py:69`, plus the mutants copy). This slice adds **one** helper rather than a fourth
inline copy, and honors the environment override so tests can point it at `tmp_path` the way
`test_cli.py:221` already does for the config root.

**Keyed by lineage, not by path.** This is the load-bearing half of the recommendation:

- **Worktrees resolve correctly by construction.** `.loops/` is gitignored, so a worktree gets
  no project store; a store opened from any path with lineage *L* finds *L*'s journal. A
  path-keyed cache would manufacture a fresh first-contact per worktree, and per absolute path
  generally — silent re-acceptance through the back door, on the most ordinary operation there
  is.
- **Moving or copying a store keeps its memory.** A restored old backup at a *new* path still
  presents lineage *L*, still finds *L*'s journal, and is still classified ROLLBACK.
  Path-keying would have let "copy the store somewhere else and open it" bypass the cache
  entirely.
- **The cross-host case degrades honestly.** A store rsynced from another host arrives with no
  journal on this host and is first contact — which is precisely the limitation
  `witness-protocol.html:411-417` names, with the doc's own answer (fetch a checkpoint from an
  already trusted device). Named as a non-goal in §F rather than papered over.

**Filename safety.** `lin` is validated only as a non-empty string (`arrival.py:463-464`);
`mint_lineage()` produces a ULID (`arrival.py:360-361`) but a foreign or hostile genesis need
not. Resolving a journal path therefore refuses any lineage outside a conservative safe-name
charset, with a typed refusal naming the lineage rather than interpolating it into a path.
Scope-the-claim: that is a location claim ("this cache cannot key on that string"), not a
verdict about the store.

### A.4 Why an append-only journal, not a single cached value

The ratified scope names three artifacts: a cached head, a bootstrap receipt at migration, and
a periodic full-audit entry. **They dissolve into one structure.** A journal of typed entries
answers all three — the cached head is the highest-ordinal entry, the bootstrap receipt is the
first entry, the audit entry is an entry — and it is *simpler* than three artifacts with three
lifecycles:

- A single overwritten value cannot hold the bootstrap receipt, because the first subsequent
  advance would erase it — yet slice 6's exit criterion is "all live stores migrated **with
  bootstrap receipts cached**" (`plan.md:84`).
- Append-only means no read-modify-write, so no torn partial update and no lock.
- **Retaining every previously accepted head is what makes an under-evidenced advance
  recoverable** rather than a loss (§C.4). This is the property that lets the per-open check be
  cheap without becoming dishonest.
- It matches the substrate's own model, and it makes accidental cache reset visible —
  `witness-protocol.html:333-335`.

This is a dissolution of the ratified minimum, **not** an upgrade to §06's "personal stronger"
tier: no signatures, no `previous`/`attestation_id` chaining, no issuer, no key. Those are the
deferred signed grammar.

### A.5 One question for Kyle — genuinely either-way, and it belongs to slice 6

The primary home is not either-way; A.2 rules out four candidates on the threat model. The
open question is narrower: **should the project store's journal additionally be committed to
git as a second copy?**

For: off-host durability, review-visible history of head advances, and a second copy in a
different administrative domain — which is exactly the posture
`witness-protocol.html:358-365` asks for. Against: it couples to the unmade slice-6 decision
about tracking the migrated `.arrival` (`plan.md:83`) — if that store becomes tracked, a
tracked journal shares its rewrite boundary and the second copy is worth nothing.

**Recommendation: defer to slice 6 and decide it together with tracked-vs-gitignored.** It
costs slice 3 nothing to defer, because a second copy is a copy of the same grammar and
requires no design change — which is what makes this a scheduling question rather than an
architecture one.

### A.6 The location→lineage binding — transitional, and its sweep is named now

Lineage-keying leaves one hole: **wholesale replacement.** A store rewritten with a *new*
lineage finds no journal, is classified first contact, and is trust-on-first-use accepted —
the "Replacement or explicit re-custody" row of §07 silently passing. Detecting it requires
knowing which lineage this location *should* present.

Architecturally that is `StoreDescriptor.lineage` — *"when already known, is checked against
genesis rather than trusted as a replacement for it"* (`arrival_contract.py:302-303`). But
slice 2 deliberately left it unparsed, with its forcing consumer named as slice 5's adopt
(`arrival_registry.py:94-97`), and growing the `.vertex` grammar out of sequence here would
take a decision slice 3 was not given.

**Recommendation: a small `bindings.jsonl` in the state root now — location, lineage,
observed_at, append-only — superseded by the declared lineage at slice 5.** The in-arc
precedent is the registry's own transitional arm, which carries a `DELETE IN SLICE 5` marker
and states why its deletion is a residue sweep rather than a behavior change
(`arrival_registry.py:114-122`). This binding gets the same marker and the same obligation,
written where slice 5 will find it. Flagged for the arbiter: this is the one piece slice 3
knowingly builds to be deleted.

---

## B. Types, module placement, serialization

### B.1 One new module: `libs/engine/src/engine/arrival_head_attestation.py`

Slice 2 split three ways because import cost differed (a caller naming a `Head` must not drag
sqlite3 and a 1845-line codec, `arrival_contract.py:9-16`). That argument does not apply here:
every part of this slice is stdlib plus `arrival_contract`. The classifier is pure, the journal
is `pathlib`/`json`/`os`, and the ledger wrapper delegates through the contract Protocols
without touching an adapter. One module, and a ratchet test pinning that importing it drags
neither `sqlite3` nor `engine.arrival` — the shape of
`test_importing_the_registry_does_not_drag_the_adapter_in`.

**The name is the Rule 18 join, and it is mechanical.**
`test_every_arrival_named_engine_module_is_scanned` globs
`libs/engine/src/engine/arrival*.py` and fails if a new one is absent from `_SCAN_TARGETS`
(`test_rule_18_arrival_vocabulary_denylist.py:393-407`). Naming the module `arrival_*` enrolls
it in the vocabulary ratchet **by birth**; naming it `head_attestation.py` would require a
manual `_SCAN_TARGETS` edit that a future reader can forget. Ratchet test: prefer the name
that makes the join structural. No `_DENIED` entry is needed — nothing here names retired
vocabulary — and no glossary amendment either, because "head attestation" was already ratified
into the glossary by dispositions §3.

**Vocabulary hazard, stated so the impl agent does not walk into it.** "Attestation" is already
load-bearing in this codebase for a *different* concept: `FactAttestation`/`TickAttestation`
are the signed receipt on a committed row (`vertex.py:135-136`), and "genesis is the lineage's
attestation root" recurs across `arrival.py:885`, `sqlite_store.py:963-964`, `ceremony.py:517`.
The disposition ruled our vocabulary anyway, and it is right — but "distinct types, distinct
serialization names" (`plan.md:52`) is doing real work here, not just separating us from
`witness.py`. Hence the `type` string in B.3 is `arrival-head-observation`, not the doc's
signed `arrival-head`, which also leaves the future signed corpus unencumbered.

### B.2 The types

```python
class Kind(Enum):        # why this entry exists
    BOOTSTRAP   = "bootstrap"    # first entry for a lineage
    ADVANCE     = "advance"      # the head moved
    AUDIT       = "audit"        # a full chain-plus-projection audit ran
    TRUST_RESET = "trust-reset"  # an operator ceremony re-established trust

class Level(Enum):       # what evidence backed this entry's head
    MINT          = "mint"           # this process minted the genesis
    FIRST_CONTACT = "first-contact"  # trust on first use; nothing was proven
    COMMIT        = "commit"         # this process appended it under the full-head fence
    DESCENDANT    = "descendant"     # a verified suffix walk from the previous head
    FULL          = "full"           # verified from genesis

@dataclass(frozen=True)
class HeadAttestation:
    head: Head                 # lineage + ordinal + record_hash — the comparison keys
    kind: Kind
    level: Level
    observed_at: float
    location: str = ""         # where it was seen; diagnosis only, never a key
    note: str = ""             # trust-reset gap description, audit result
```

Field choices, against the §04 table (`witness-protocol.html:210-233`):

- **The whole `Head`, always** — §04's `lineage`/`ordinal`/`record_hash` are exactly
  `arrival_contract.Head`, and reusing the ratified type rather than restating three fields
  means the comparison cannot drift from the CAS pin's notion of a head
  (`arrival_contract.py:120-133`).
- **Counts omitted.** Dispositions §2: they are projection corroboration smuggled into a
  custody claim. Not optional-and-unset — absent from the type.
- **`sig`/`issuer`/`key_id`/`previous` absent.** Deferred grammar (dispositions §1). Their
  absence is the honest shape of an unsigned local cache; adding empty fields would advertise
  a claim this slice does not make.
- **`protocol`/`wire` omitted from the record**, carried by the file header instead (B.3) —
  they are properties of the journal, not of each entry, and re-stating them per line is a
  field nothing reads. Same discipline the registry applied to `lineage`/`role`
  (`arrival_registry.py:94-97`): parsing fields nothing consumes is how speculative grammar
  ossifies.
- **`observed_at` kept.** It is what makes a refusal actionable ("your cached head is from
  three weeks ago") and what answers audit staleness at open. §04 is explicit that it is
  witness metadata and never ledger order.
- **`level` is the scope-the-claim field** and it is the one addition to §04's table. It states
  how much was actually established, so an entry can never be read as a stronger claim than
  the evidence behind it. §12's checkpoint discussion asks for exactly this
  (`witness-protocol.html:583-589`: a checkpoint retains "completion status").

The **bootstrap receipt** is `Kind.BOOTSTRAP` — with `Level.MINT` when slice 4's sidecar minted
the genesis in this process, and `Level.FIRST_CONTACT` when an already-existing store was
opened for the first time. **Slice 6's verification depends on that distinction**: a journal
beginning at `mint` was witnessed from genesis forward and every head in it is accounted for;
one beginning at `first-contact` was trusted on sight. Slice 4 must produce the former for
every migrated store, and slice 6 checks it.

The **periodic full-audit entry** is `Kind.AUDIT` / `Level.FULL`, carrying the head the audit
covered and, in `note`, the projection-agreement result.

### B.3 Serialization

One JSON object per line, appended with `O_APPEND`; a single line is one write. The first line
of a new journal is a header stating what the file is:

```json
{"v":1,"type":"arrival-head-observation","protocol":1,"wire":1}
{"v":1,"kind":"bootstrap","level":"mint","lineage":"01ARZ…","ordinal":0,
 "record_hash":"<64-hex>","observed_at":1787779020.0,"location":"/…/project.arrival"}
```

- **JSONL, not the wire codec.** The wire-v1 body grammar constrains *arrival records*; a head
  attestation is not one and must not be written by the record codec. Deliberate: the journal
  must remain readable when the store it witnesses cannot be opened at all, which is the
  situation it exists for.
- **`protocol`/`wire` in the header** so a journal written under wire v1 is not silently
  compared against a v2 head whose hashes derive differently.
- **These outlive process restarts and outlive the store**, so the grammar is versioned (`v`)
  and unknown fields are preserved-and-ignored on read rather than refused — a journal written
  by a later build must not make an older build refuse to compare.

**Three read rules, all load-bearing:**

0. **A `trust-reset` entry opens a new trust epoch; the read scope is the entries after the
   last one.** Without this the ceremony can never take effect: after an operator accepts a
   restore from ordinal 100 back to 90, the abandoned entries at 91–100 still hold the maximum
   ordinal, *K* reads as the head that was deliberately abandoned, and every subsequent open
   refuses `ROLLBACK` forever. Epoch-scoping applies to all three of: which entry is *K*, the
   equivocation check below, and the audit's all-journaled-heads check (C.4). Pre-reset entries
   are retained **as evidence, not as claims** — that is the whole point of recording the gap.

1. **The known head *K* is the entry with the maximum ordinal, not the last line.** Two writers
   append concurrently (the arrival flock serializes their *appends*, not their journal
   writes), so lines can land out of order: A commits ordinal 5, B commits 6 and journals it, A
   journals 5 last. Last-line semantics would then read K=5 and classify a genuine rollback to
   5 as UNCHANGED. Max-ordinal closes it, and duplicate entries at one ordinal are harmless.
2. **Two entries at the maximum ordinal with different `record_hash` is a typed refusal** —
   journal-internal equivocation. The journal has recorded two incompatible histories and it is
   not the journal's place to choose.

A torn last line is tolerated on read (the entry is skipped) and reported. It costs at most the
newest observation, which is the same exposure §02's detection window already names
(`witness-protocol.html:150-157`).

---

## C. The comparison state machine

### C.1 Six outcomes as one pure function

```python
def compare(known: HeadAttestation | None,
            presented: Head,
            at_known: Head | None) -> Outcome
```

Pure, stdlib-only, no I/O — which is what makes it directly vector-testable and what keeps the
vectors free of any implementation's exception family. `at_known` is the head the ledger
vouches for at *K*'s coordinate, or `None` when it will not vouch for anything there; the
caller gathers it (§D.3) and the classifier only judges.

| Outcome | Condition | Posture |
|---|---|---|
| `FIRST_CONTACT` | `known is None` | proceed, TOFU (C.3) |
| `UNCHANGED` | `presented == known.head` | proceed |
| `ADVANCED` | same lineage, `presented.ordinal > known.ordinal`, and descent established | proceed |
| `ROLLBACK` | same lineage, `presented.ordinal < known.ordinal` | **refuse** |
| `SAME_HEIGHT_FORK` | same lineage and ordinal, different hash | **refuse** |
| `REWRITE` | higher ordinal, but `at_known != known.head` or descent not established | **refuse** |
| `LINEAGE_REPLACED` | different lineage | **refuse** |

Seven rows for six states because §07 lists first contact separately from the five comparisons
(`witness-protocol.html:378-393`). The outcome *strings* are what the conformance vectors pin —
never a Python exception type, for the same reason the replicate family gives
(`test_conformance_replicate.py:9-13`): naming one implementation's exception family in a
language-neutral vector pins that family on every other implementation.

### C.2 Refusals root in this module, not under `ContractRefusal` — argued from the contract text

**Recommendation: a separate `AttestationRefusal` root**, with `HeadRollback`, `HeadFork`,
`HeadRewrite`, `LineageReplaced`, `JournalEquivocation`.

The slice-2 narrow-form ruling is explicit about what the root covers: *"conditions the
contract text names… everything else backend-specific BY DESIGN (scope-the-claim: the root
covers what the contract asserts, no more)"* (`decision:design/arrival-slice2-contract-text`,
ruling 2; restated at `arrival_contract.py:519-523`). Rollback, rewrite and replacement are
**not** named by `backend-contract.html` — they live in `witness-protocol.html`, a different
document, about a different layer that sits *above* the contract and compares two heads it
obtained through it. Joining them to `ContractRefusal` would assert that every conforming
backend owes these refusals, which is a claim only a contract-text line can make.

**Flag for the arbiter:** if the ruling is that the witness layer *should* be contract-level,
that needs a `backend-contract.html` addendum and it is Kyle's call, not the impl agent's. The
recommendation is outside-the-root, on the narrow-form precedent.

**Naming collision, called out explicitly.** `arrival_contract.SameHeightFork` already exists
(`arrival_contract.py:466`) and means something adjacent but different: replication found a
conflicting record at the height it was about to fill. Ours is a comparison of two heads at the
same ordinal. Same ratified *state* name, different operation, different type. Hence
`HeadFork` for the exception while the outcome string stays `same-height-fork` — the state
machine's own vocabulary is preserved where it is normative (the vectors) and the Python names
stay unambiguous where a collision would bite.

`LINEAGE_REPLACED` partially **dissolves into an op that already exists**: `FileLedger.head`
raises `NotAuthority` when asked about a lineage the log does not hold
(`arrival_file_backend.py:593-598`). Where the expected lineage is known, that refusal fires
first and is already correct. The classifier still owns the outcome, because the classifier is
what the vectors exercise and because a caller that reached the comparison without a declared
lineage still needs the row.

### C.3 First contact: TOFU, labeled, never silent

§07 offers three ways to establish trust at first contact — migration receipt, pinned witness,
explicit trust reset (`witness-protocol.html:384`). A fourth, weaker one is what v1 actually
does for a store that predates the journal: trust it on sight. Refusing instead would make a
fresh clone unable to read anything.

**The design's answer is not to pretend otherwise: the bootstrap entry records
`level: first-contact`, and that label is permanent.** A journal that begins there can never be
read as proof of anything before it. A store migrated by slice 4 is never in this state — its
journal begins at `mint`, before its first open — which is exactly why spine constraint 5
orders slice 3 before slice 4 (`plan.md:111`).

### C.4 Never silent re-acceptance, and what recovery looks like

Two mechanisms, and they are different:

**Refusals are terminal for the open.** No automatic path may write an entry that abandons a
refused comparison. Recovery is an explicit operator ceremony that appends
`Kind.TRUST_RESET` with the gap recorded in `note` — the abandoned known head, the refused
presented head, and the reason. §11's last row asks for exactly this: *"Perform explicit trust
reset from archives or operator ceremony and record the gap"*, against the unsafe shortcut
*"Treat first presented database as historically proven"* (`witness-protocol.html:557`). The
ceremony's CLI surface is slice 5's (the CLI cut); slice 3 provides the entry kind and the
producer function, so slice 4 and 6 have something to call.

**An under-evidenced ADVANCE is not a loss, because the journal is append-only.** *K* stays in
the journal forever. So the periodic full audit does not merely re-verify the current chain —
it checks that **every head journaled in the current trust epoch is still present at its own
ordinal with its own hash**. That single walk is what makes the cheap per-open check safe: an
advance accepted today on partial evidence is re-examined against the complete record of
everything accepted since the last reset. A single-value cache could not offer this at any
price, because it would have forgotten *K*.

The epoch scope is not a convenience — it is what keeps the ceremony and the audit from
contradicting each other. A legitimately accepted restore leaves heads in the journal that the
restored store does not and cannot contain; auditing against them would fail permanently and
train an operator to ignore the audit, which is worse than not running one.

§11's recovery table maps to named responses, and the impl carries them in the refusal
messages: rollback → locate a replica or backup at-or-above the witnessed head, never move the
witness backward; fork → freeze both branches, collect evidence, explicit incident procedure,
never pick the taller branch; projection ahead of the ledger → `rederive_projections`, never
edit the ledger to match the projection.

---

## D. Compare-on-every-open

### D.1 Where the seam goes

`BackendRegistry.open` returns the ledger half wrapped:

```python
def open(self, descriptor) -> tuple[ArrivalLedger, ArrivalQuery]:
    ledger, query = opener(descriptor)
    return AttestedLedger(ledger, journal_for(descriptor)), query
```

`AttestedLedger` satisfies `ArrivalLedger` by delegation, adds no operation outside
`LEDGER_MUTATIONS` (`arrival_contract.py:334`), and does two things: it compares at
construction, and it journals after a successful `mint`, `append` or `replicate`.

**Always on, never a flag.** A configuration switch for a safety property is the shape Rule
18's own denylist rejects — `receipt_mode` is denied with the reason *"there is no mode —
custody is structural, not configured"* (`test_rule_18_arrival_vocabulary_denylist.py:94-111`).
The sidecar needs no exemption: minting through the wrapper *is* how the bootstrap receipt gets
written (§D.4).

### D.2 The compare must precede any open-time recovery — the argument for this seam

`catch_up()` runs on every `ArrivalStore` open, and its documented triggers for a full index
**rebuild** include a shrunk log (`arrival_store.py:228-334`, and the engine CLAUDE.md store
section states the rule). A shrunk log with an index that still holds rows past the log's new
head is *the* signature of tail truncation — and the rebuild erases the rows that testify to
it. Detection placed downstream of that repair can only report the agreement the repair just
manufactured.

This is F2's principle ("verification never repairs",
`decision:design/arrival-slice2-contract-text` ruling 1, `arrival_file_backend.py:670-688`)
applied one level out: *the witness must observe before the runtime heals.* The registry path
satisfies it structurally rather than by discipline — its opener performs no recovery, because
`ArrivalLog` construction does no I/O at all (`arrival.py:838-865`). Note the ordering this
forces on the seam: **evidence is gathered from the ledger half, and the projection comparison
is a second, separable step** — which is also what keeps the seam working when the projection
is absent (§0.4).

This is the finding that makes §0.3 a correctness argument rather than a sequencing
preference, and it is WP3's empirical gate.

### D.3 What the comparison costs, branch by branch

Evidence gathering is per-backend (a small function beside the adapter); classification is
neutral. The gatherer's first move is `ledger.verify(Open())` — genesis validated plus the
adopted head record, via a constant-time reverse tail read
(`arrival_file_backend.py:689-697`, `arrival.py:1225-1267`) — never `head()`, which walks.

| Branch | Evidence needed | Cost |
|---|---|---|
| `UNCHANGED` | `verify(Open())` only | **O(1)** — the dominant case |
| `ROLLBACK` / `SAME_HEIGHT_FORK` / `LINEAGE_REPLACED` | `verify(Open())` only | **O(1)**, then refuse |
| `FIRST_CONTACT` | `verify(Open())` only | **O(1)** |
| `ADVANCED` | descent from *K* to *P* | **O(history)** — see below |

The advance branch is rare **by construction**, because a writer journals its own commit
(§0.1): a successful `append` returns `Commit(before, records, after)` having compared the full
head under the fence, so the writer already holds the strongest descent evidence there is and
records it at `Level.COMMIT`. The next open then sees `P == K`. An advance observed *at open*
therefore means an unjournaled writer touched the lineage — a foreign host, a restore, a
crashed process, or (during slices 3–4) the legacy `ArrivalStore` path — and paying a verified
walk there is correct, not a regression. **The walk captures the record at *K*'s ordinal and
compares it to `known.head.record_hash` — that comparison is `at_known`, and it is the
ADVANCED/REWRITE discriminator.** A walk that checks only that it reached *P* has verified the
current chain while answering nothing about continuity with what was previously accepted, which
is precisely the "never accept height as proof of continuity" failure. On success the entry
lands at `Level.DESCENDANT`; on failure it is `REWRITE` and refuses. A crashed writer costs
exactly one walk, then the journal is current again.

Sequencing note: during slices 3–4 the ordinary write path is still the unwrapped
`ArrivalStore`, so any registry open of a store written by it takes the advance branch. This
does not bite in-arc because nothing but the sidecar routes through the registry until slice 5
(`arrival_registry.py:26-30`), and after slice 5 every writer is wrapped.

**Where `head_at` is consumed.** The projection comparison: `query.projected_through()` is a
`Watermark`, a coordinate and not a head (`arrival_contract.py:137-151`). Comparing its
*ordinal* against the presented head is free and gives the classification — behind (ordinary
staleness, catch-up's job), level (fine), or **ahead of the ledger**, which is tail-truncation
evidence that survives independently of the journal. Only when they disagree does the seam call
`head_at` to turn the coordinate into a head the ledger vouches for, and the same call is made
inside the periodic audit. That is the divergent path of §0.2. Note that on the ahead-of-ledger
branch `head_at` refuses rather than answering (`ArrivalLog.read` finds no record at that
ordinal, `arrival.py:1209`) — and the refusal *is* the answer.

### D.4 First open ever, and the bootstrap receipt

- **No journal for the lineage** → `FIRST_CONTACT` → the wrapper writes
  `bootstrap`/`first-contact` and proceeds (C.3).
- **`mint` through the wrapper** → `bootstrap`/`mint` for head 0. Slice 4's sidecar gets the
  bootstrap receipt by using the ordinary registry-opened ledger; there is no privileged path
  and no special API, which mirrors the sink's own rule that migration appends through ordinary
  `append` (`plan.md:65`). **This is the path §0.4 currently blocks** — a store with no
  projection cannot be opened through the registry at all — which is why the lazy-reader fix is
  proposed inside WP3 rather than left for slice 4.
- **The store is absent** — the inverse case, and it splits on whether the journal remembers
  anything. `verify(Open())` on an absent or empty log refuses with `GenesisRefused`
  (`arrival.py:1049` for a missing file, `arrival.py:1245` for an empty one), so the wrapper
  must branch on it rather than treat it as corruption. **No log, and no journal or binding for
  this location** → pre-genesis; proceed, because this is the sidecar about to mint and
  refusing would make minting impossible. **No log, but the journal holds a head** → this is
  the attack matrix's "delete store and every backup" row, where the witness *proves what was
  lost, not its contents* (`witness-protocol.html:440`). It must refuse, and in particular it
  must never permit a silent re-mint under a remembered lineage — a fresh genesis at a location
  whose journal remembers ordinal 4217 is a replacement wearing the old name. Recovery is the
  explicit trust-reset ceremony (C.4), which is §11's "all witness state lost" row inverted.
- **Journal write failure is surfaced, never swallowed.** The append already committed, so the
  store has advanced past its witness — which is precisely §05's `committed` vs `witnessed`
  distinction (`witness-protocol.html:293-303`). The caller is told which one it got rather
  than having both collapsed into "saved".

### D.5 The periodic audit

Slice 3 ships the producer, not a scheduler. `audit(ledger, query, journal)` runs `verify(Full)`
through the presented head, checks every journaled head is still at its ordinal with its hash
(C.4), takes the projection-agreement result as an input (so the neutral module never imports
`canonical_audit`), and appends `audit`/`full`.

"Periodic" is operator cadence. The open path **reports** staleness — days since the last
`audit` entry — and never triggers one, because a full walk at open is exactly what the adapter
refused to pay under an `Open` label (`arrival_file_backend.py:689-697`). Wiring
`sl store verify --deep` (`store.py:311-360`) to append an audit entry is slice 5's CLI cut.

Writing an audit entry from a verification path is not the thing F2 forbids: F2 forbids
repairing *the store under judgment*. Recording evidence outside it is the entire purpose of a
witness.

---

## E. Work packages

Three, sized against slice 2's five. Each exits on its own gate.

### WP1 — the module: types, journal, classifier

Build `engine/arrival_head_attestation.py`: `Kind`/`Level`/`HeadAttestation`, the journal
(state-root resolution with `XDG_STATE_HOME` honored, lineage safe-name refusal, append,
max-ordinal read, equivocation refusal, torn-tail tolerance), the pure `compare`, the
`AttestationRefusal` family, and the transitional `bindings.jsonl` carrying its
`DELETE IN SLICE 5` marker and sweep obligation (§A.6).

*Exit:* unit tests for every classifier row and every journal read rule; the import ratchet
(no `sqlite3`, no `engine.arrival`); Rule 18 green with the module auto-enrolled by name;
concurrent-append test proving max-ordinal beats last-line; a lineage-with-a-slash refusing to
resolve a path; **and the epoch test — after a `trust-reset` accepting a lower head, the next
open classifies against the reset head and not the abandoned one, and the audit's
all-journaled-heads check does not fail on the pre-reset entries** (B.3 rule 0, C.4).

### WP2 — the `comparison` conformance family

New family under `spec/conformance/`: `generate_comparison.py`, `vectors/comparison/`,
`libs/engine/tests/test_conformance_comparison.py`, and a `SCHEMA.md` section. Follow the
**replicate tier** — the strongest existing pattern — with a `VECTOR_INVENTORY` naming every
vector under its family prefix and a test asserting exact two-way equality with what is on disk
(`test_conformance_replicate.py:56-73,90-110`), so a deleted fixture fails by name and an
unclassified one fails too. Vector shape follows replicate's: raw log lines as `input.log`,
`input.known` and `input.presented` as head objects, `expected.outcome` as the state *string*.

*Exit:* the plan's three named refusals (`plan.md:98`) — rollback, same-height fork, rewrite —
plus replacement, unchanged, advanced, first contact, and journal equivocation; inventory test
green; Rule 17 green (the generator's case descriptions join its scan set,
`test_rule_17_fold_order_prose_is_receipt_order.py:160-164`).

### WP3 — the seam, the bootstrap receipt, the audit producer

`AttestedLedger`, the file-backend evidence gatherer, the registry integration, the audit
producer, staleness reporting, and the trust-reset producer. Plus the §0.4 adapter fix, subject
to the arbiter's confirmation: build `FileQuery`'s reader lazily so a store with no projection
can be opened, minted into, and witnessed.

*Empirical gate* — against real stores, not mocks:

1. Truncate a store's tail with a stale-ahead index; open through the registry. Assert: typed
   refusal, **and the index bytes are unchanged afterwards** (§D.2 — this is the gate that
   proves detection precedes repair).
2. Restore an older copy over a store; assert `ROLLBACK` and that the journal was not advanced.
3. Rewrite-and-rehash a store from an interior record; assert `REWRITE`.
4. Replace a store with a freshly minted lineage at the same location; assert
   `LINEAGE_REPLACED` via the binding.
5. Unchanged open writes **zero** journal bytes (byte-compare before and after) — the rule that
   keeps reads off the write path.
6. Commit-then-open is O(1): the second open takes the unchanged branch, not the advance
   branch. Assert by evidence gathered, not by wall clock.
7. Mint through the wrapper produces `bootstrap`/`mint`; slice 4 can consume it.
8. Both store-absent branches (§D.4): a fresh location mints cleanly; a location whose journal
   holds a head with the log deleted refuses, and a re-mint under that lineage refuses too.

---

## F. Non-goals

Explicit, so the impl agent and the reviewers hold the same line.

- **Nothing signed.** No `sig`, `issuer`, `key_id`, `previous`, no `attestation_id`, no
  signing domain strings, no golden signed corpus. Deferred until a consumer forces it
  (dispositions §1). The `type` string differs from the doc's signed `arrival-head` so the
  future corpus arrives unencumbered (§B.1).
- **No notary, no quorum, no gossip, no receipt transport.** Including cross-host: a store
  arriving from another machine is first contact, and the doc's own answer is to fetch a
  checkpoint from a trusted device (`witness-protocol.html:411-417`).
- **No Merkle accumulator** (`witness-protocol.html:601-608` — do not pre-pay the complexity).
- **No `committed`-vs-`witnessed` API status flag** beyond surfacing a journal write failure
  (§D.4); the two-strength acknowledgment is the deferred signed layer's.
- **No scheduler.** "Periodic" is operator cadence; the open path reports staleness only.
- **No store migration.** Slice 4 owns the sidecar; this slice owns only the receipt primitive
  it will call.
- **No consumer rewiring beyond the compare-on-open seam itself.** The CLI resolvers, the SDK's
  canonical surface and the `open_canonical_store` importers stay on today's path; rewiring is
  slice 5's (`plan.md:69`).
- **No witnessing of jsonl- or sqlite-canonical stores.** They have no lineage and no head;
  there is nothing to compare. The journal begins at migration.
- **No journal compaction or retention policy.** Append-only, unbounded, by design — the
  retention question is §13's open deployment ruling and has no forcing consumer yet.
- **No `.vertex` grammar growth.** `StoreDescriptor.lineage` stays unparsed until slice 5
  (§A.6).

---

## Load-bearing claims for spot-check

| # | Claim | Cite | Provenance |
|---|---|---|---|
| 1 | Ratified scope is head cached outside every authority + bootstrap receipt + compare on every open + periodic full audit; signed grammar deferred | `decision:design/arrival-suite-review-dispositions` §1 | ratified fact |
| 2 | The hole being closed: the resume mark lives in the sqlite index, inside the same rewrite boundary | same fact, §1 | ratified fact |
| 3 | Counts are optional corroboration, never required | same fact, §2; `witness-protocol.html:224-225` | ratified fact + design source |
| 4 | Code vocabulary is "head attestation"; `witness` stays the read cursor | same fact, §3; `plan.md:52` | ratified fact + plan |
| 5 | Six comparison states, refusals typed, never silent re-acceptance | `witness-protocol.html:378-393`; `plan.md:53` | design source + plan |
| 6 | §07's descent check is `scan(after, through)` | `witness-protocol.html:407` | design source |
| 7 | `FileLedger.scan` walks from ordinal 0 — descent check is O(history) | `arrival_file_backend.py:646`; `arrival.py:1112` | code, verified |
| 8 | `head_at` resolves through `ArrivalLog.read`, a verified walk from ordinal 0 | `arrival.py:1201-1214`; `arrival_file_backend.py:610` | code, verified |
| 9 | `head_at` joined the op table with slice-3 compare-on-open as a forcing consumer | `decision:design/arrival-slice2-contract-text` ruling 3 | ratified fact |
| 10 | `verify(Open())` is a constant-time tail read, deliberately not `head()` | `arrival_file_backend.py:689-697`; `arrival.py:1225-1267` | code, verified |
| 11 | `ArrivalLog` construction does no I/O | `arrival.py:838-865` | code, verified |
| 12 | `ArrivalStore.__init__` runs `catch_up()` unconditionally; a shrunk log triggers an index rebuild | `arrival_store.py:143-182,228-334`; `libs/engine/CLAUDE.md` store section | code + doc |
| 13 | `Commit` carries full `before`/`after` heads; the CAS compares all three fields (F1 closed) | `arrival_contract.py:184-196`; `plan.md:44` | code + plan |
| 14 | Reads mostly never construct a store; `loops ls` bypasses even the index funnel | `jsonl_store.py:370,323`; `store_reader.py:53`; `vertices.py:7,139,237`; `residence.py:176-186` | code, verified |
| 15 | Nothing routes through the registry in production until slice 5 | `arrival_registry.py:26-30`; `plan.md:69,108` | code + plan |
| 16 | `BackendRegistry.open`'s opener performs no recovery | `arrival_registry.py:129-144` | code, verified |
| 16b | …but it eagerly builds a `StoreReader`, which raises `FileNotFoundError` on a missing index — so a store with no projection cannot be opened through the registry (§0.4) | `arrival_registry.py:144`; `arrival_file_backend.py:818-820`; `store_reader.py:45-57` | code, verified |
| 17 | Refusal-root narrow form: the root covers what the contract text names, no more | `decision:design/arrival-slice2-contract-text` ruling 2; `arrival_contract.py:519-523` | ratified fact + code |
| 18 | `SameHeightFork` already exists in the contract for a different operation | `arrival_contract.py:466-473` | code, verified |
| 19 | `head(lineage=…)` already refuses a foreign lineage with `NotAuthority` | `arrival_file_backend.py:593-598` | code, verified |
| 20 | `Watermark` is a coordinate, not a head; only the ledger can complete it | `arrival_contract.py:137-151` | code, verified |
| 21 | `StoreDescriptor.lineage` is deliberately unparsed; forcing consumer is slice 5's adopt | `arrival_registry.py:94-97`; `arrival_contract.py:302-303` | code, verified |
| 22 | The registry's transitional arm is the in-arc precedent for a marked delete-in-slice-5 unit | `arrival_registry.py:114-122` | code, verified |
| 23 | Rule 18 auto-enrolls `libs/engine/src/engine/arrival*.py` by glob | `test_rule_18_arrival_vocabulary_denylist.py:393-407` | code, verified |
| 24 | Rule 18 denies `receipt_mode` because custody is structural, not configured | `test_rule_18_arrival_vocabulary_denylist.py:94-111` | code, verified |
| 25 | Rule 17's scan set includes `spec/conformance/generate_*.py` | `test_rule_17_fold_order_prose_is_receipt_order.py:160-164` | code, verified |
| 26 | The replicate family is the strongest conformance tier: exact two-way inventory equality | `test_conformance_replicate.py:56-73,90-110` | code, verified |
| 27 | Vectors never name a Python exception family | `test_conformance_replicate.py:9-13`; `SCHEMA.md:359,363` | code + spec |
| 28 | `.loops/` is gitignored wholesale — nothing under it is git-durable | `.gitignore:37` | verified |
| 29 | `XDG_CONFIG_HOME` is the only XDG precedent, re-derived inline at three sites | `vertex_reader.py:59`; `resolve.py:69`; `test_cli.py:221` | code, verified |
| 30 | `lin` is validated only as a non-empty string; `mint_lineage` produces a ULID | `arrival.py:463-464,360-361` | code, verified |
| 31 | F2: verification never repairs, at any level | `decision:design/arrival-slice2-contract-text` ruling 1; `arrival_file_backend.py:670-688` | ratified fact + code |
| 32 | A colocated witness may be one copy, never the only copy | `witness-protocol.html:358-365` | design source |
| 33 | An append-only receipt journal preserves head history and makes cache reset visible | `witness-protocol.html:333-335` | design source |
| 34 | §11: explicit trust reset records the gap; never treat the first presented database as proven | `witness-protocol.html:557` | design source |
| 34b | "Delete store and every backup": the witness proves what was lost, not its contents | `witness-protocol.html:440` | design source |
| 34c | `genesis()` refuses a missing log; `_tail_record` refuses an empty one — the store-absent branch is typed, not a crash | `arrival.py:1049,1245` | code, verified |
| 35 | Slice 6 exits on bootstrap receipts cached; spine constraint 5 orders slice 3 before slice 4 | `plan.md:84,111` | plan |
