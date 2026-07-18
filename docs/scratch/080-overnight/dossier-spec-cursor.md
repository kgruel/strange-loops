# Dossier chapter — loops-go SPEC on ordering, as-of, cursors, residence

Grounding for the 0.8.0 cursor-axis design session. Sources read in full,
2026-07-16:

- `/Users/kaygee/Code/loops-go/SPEC.md` (1260 lines; §9 status header confirms §9–§10 are PROVISIONAL, design-led)
- `/Users/kaygee/Code/loops-go/README.md` (52 lines)
- `/Users/kaygee/Code/loops-go/PLAN.md` (211 lines)
- `/Users/kaygee/Code/loops-go/FINDINGS.md` (596 lines)
- Go source spot-checks: `store/sqlite.go`, `internal/conform/merge_test.go`

All line numbers below are exact as of this read. Quotes are verbatim.

---

## 1. The two ordering authorities (SPEC §8.4 — normative)

The SPEC's single most load-bearing statement for the cursor-axis question is
§8.4, "Chain & the two ordering authorities (normative)". SPEC.md:850-856:

> **Ordering authority is split, and the split is normative** (incumbent fix
> `3b2ceb5`: id order ≠ append order in mixed-id-era stores):
>
> - **Event order `(ts, id)`** governs fold replay (§6.2). It answers *what
>   happened, in what observed sequence*.
> - **Witness order** (append/insertion order as recorded by the store — the
>   incumbent uses SQLite rowid) governs window membership and chain walking.
>   It answers *what this store received, in what order it received it*.

And SPEC.md:858-863:

> The chain attests **receipt, not chronology**. A late-arriving fact with an
> old event-time must not retroactively enter a sealed window — that is honest
> witnessing, not tamper. Neither order substitutes for the other; an
> implementation that conflates them produces either false tamper alarms or
> non-deterministic folds.

This split is anticipated at the invariant level. §0.5.4, SPEC.md:76-84:

> **Byte-exactness at the attestation tier.** [...] Set-determinacy
> deliberately does NOT hold there — the chain is a function of *witness
> order* (§8.4), receipt not chronology, and that is attested behavior, not
> a violation.

Conformance coverage owed for the split — §8.7, SPEC.md:916-921:

> [...] two-authorities differential (a
> late-arrival fixture where event order and witness order disagree — fold
> state must follow §6.2, window membership must follow §8.4).

## 2. Event order: the `(ts, id)` replay rule (SPEC §6.2 — normative)

The rule, SPEC.md:570-574:

> The set-determinacy invariant (§0.5.3) is **normative**. The mechanism:
>
> > Replay processes facts in **`(ts, id)` order** — observation time `ts`
> > ascending, with the stored ULID `id` as a unique, stable tie-break for equal
> > `ts`.

Why it is merge-stable and rowid is not, SPEC.md:576-586: `ts` and `id` "are
assigned at write time and **travel with the fact**"; merge copies them
verbatim and dedups on the `id` primary key; "Only SQLite's `rowid` is
regenerated, in merge-insertion order." The incumbent's `ORDER BY rowid`
replay is called out as the set-determinacy violation this rule dissolves.

The axis choice is explicit and was contested. SPEC.md:592-597:

> The order is **observation-time primary**: `ts` ascending, `id` as the
> exact-`ts` tie-break. This matches the aspiration's "events have a total
> order by ts" — a backdated, imported, or derived fact folds in event-time
> order. (The alternative, `id`-only / write-time order, was considered and
> rejected: it is barely simpler and folds backdated facts by when they were
> written, not when they happened.)

A free consequence, SPEC.md:598-601: under ts-primary order, `Latest`
"naturally yields the *maximum* observation time — so the order fix also
corrects `Latest` for out-of-order arrival [...] (assuming the `ts` column and
payload `_ts` agree, the normal case)."

Cross-implementation note, SPEC.md:588-590: "**No cross-implementation id
agreement is required.** Ids are assigned once at write and preserved, so any
implementation reading the *same* store sees the same `(ts, id)` order."

One stale-looking forward pointer: §2.2, SPEC.md:178, still says "The role of
`id` in replay order is an open question (§6.2)" — while §6.2 itself states
the rule as normative and FINDINGS records it shipped (see §8 below). Read
§2.2's sentence as a superseded pointer, not an open item.

Downstream users of the `(ts, id)` order inside the spec:
- `TopN` tie-break IS `(ts, id)` arrival order (§4.6, SPEC.md:396-400).
- Ref resolution is bounded under it (§6.3, below).
- FINDINGS H4 generalizes it: "most-recent reads order by `(ts, id)`, never
  `rowid`" (FINDINGS.md:462-467) — the rowid-DESC anti-pattern exists at
  `sqlite_store.py:234, 311, 326` beyond `resolve_entity_id`.

### 2.1 The residual: `(ts, id)` is set-determinacy, not temporal truth

FINDINGS R5 (FINDINGS.md:301-312) is directly relevant to any cursor built on
`ts`:

> **R5. Within-ms last-write-wins is a residual, not temporal — `decision
> (disclosure)`.** Under the §6.2 `(ts,id)` fix, same-`ts` same-key `Upsert`s
> (and `TopN` ties) break by `id` = a ULID. `python-ulid` is monotonic
> **intra**-process, but the operational emit path is **one ULID per process**
> (`sl emit` = fresh process), so cross-process within-ms order is **~50/50
> random vs emit order** (verified, 4000 pairs). So `(ts,id)` buys
> **set-determinacy** but **not** temporally-correct last-write-wins [...]

The adjudication (FINDINGS.md:481-489) confirms: intra-process python-ulid is
monotonic, oklog is not; they match cross-process only "by the
one-process-per-emit accident"; "the `(ts, id)` rule, whose guarantee is
set-determinacy (what the property oracle certifies), not sub-tie temporal
last-write-wins." PLAN.md:125's claim that oklog "Matches python-ulid's plain
`ULID()`" is flagged false in R5 ("Also **PLAN.md:125 is false**") — wording
fix only.

## 3. What "as-of" means — every occurrence, by section

The SPEC uses "as-of" against **both** ordering authorities, in different
places. This is the empirical center of the cursor-axis question.

### 3.1 Ref resolution: as-of = event time (§6.3)

SPEC.md:619-625:

> **Resolution is as-of the referencing fact's observation time.** For a
> referencing fact at `ts = T`:
>
> > `resolve(kind:key)` = the ULID of the **most-recent fact of `kind` with
> > `key_field == key` and `ts ≤ T`**, under the §6.2 `(ts, id)` total order;
> > *unresolved* if none exists.

SPEC.md:630-633: "This rule is **pure, replay-stable, and content-derived**:
it does not float as later facts arrive. It also **dissolves the emit-vs-read
duality**" — precompute at emit or compute at read, "the choice is
representational, not semantic."

### 3.2 Historical fold reads: as-of = a time cutoff over the §6 order (§9.1, §9.2)

§9.1 frames the problem as ts-shaped: "Any historical read (a fold "as of T")
replayed old facts through *today's* ontology" (SPEC.md:944-946).

§9.2 makes declaration state a fold and its as-of a time cutoff,
SPEC.md:974-979:

> Consequence: **current vertex state is a stock `Latest` fold (§4.1) keyed by
> `(lineage, kind, subject)` and restricted to the store's own lineage**
> (*Lineage*, below), and state-as-of-T is the same fold under a time cutoff
> (§6).

Note the cross-reference target: "(§6)" is the replay section whose order is
event-time `(ts, id)`. Read literally, declaration-state-as-of-T is an
**event-time** cutoff.

### 3.3 Key verification: as-of = witness position (§9.2, historized observer keys)

SPEC.md:1056-1061:

> Key rotation is a new `observer-defined` event, never an overwrite.
> Verification (§8.6) of a signature MUST resolve the observer's key *as of
> the signed row's witness position*, not the registry head — signatures from
> a prior key era verify against the key that was declared then.

This is the one place §9 pins an as-of to **witness order** explicitly.

### 3.4 The two-cursor model (§9.3 — "normative for historical reads")

SPEC.md:1110-1119 in full:

> Once the ontology is historized, a historical read has two independent
> cursors: **facts-as-of** (which facts replay) and **ontology-as-of** (which
> declaration state interprets them). The default MUST be equal cursors — an
> honest snapshot of what a reader at T would have seen. Unequal cursors
> (today's ontology over old facts, or the reverse) are legitimate *deliberate
> reinterpretation* and MUST be explicitly requested, never a silent default.
> Non-critical state (lenses) MAY follow the reading session's present without
> violating honesty.

Observations about what §9.3 does NOT say: it does not name the axis (ts vs
witness position) either cursor moves along; it says "a reader at T" (a time
framing) but never defines T's coordinate system. The equal-cursors default
and the explicit-request rule for unequal cursors are the only normative
content.

The unequal-cursor posture recurs in Lineage (SPEC.md:1084-1087): "Rendering
imported facts under their native lineage is deliberate reinterpretation —
same posture as unequal cursors (§9.3): available, never silent."

### 3.5 The "undefined within windows" phrase — exact context (§9.4)

The prompt characterized this as being "about ts-based as-of". **That is not
what the text literally says.** The phrase appears inside the resolved
`internal-row-placement` decision, as the argument against a third-table
residence for declaration events. SPEC.md:1128-1136:

> **Resolved — `internal-row-placement`: declaration events are rows in
> `facts` under a reserved kind namespace.** The deciding test was merge:
> merge MUST NOT be lossy about meaning, and only fact-residence puts
> interpretive history in the same substance merge already moves — facts
> about facts travel as facts. The alternatives fail it structurally: a
> third table has no shared witness order with the facts it interprets
> ("as of" becomes undefined within windows, and the §10 stream needs an
> interleaving the store never recorded); chain-row residence cannot travel
> at all, since chains do not merge.

Literal subject: a **third table lacking shared witness order** with facts.
The "within windows" refers to tick windows `(window_start, fact_cursor]`,
which are witness-order intervals (§8.2). The implication — that a ts-only
coordinate cannot define a position inside a witness-order window — is an
*inference from* this sentence, not its stated claim. Downstream agents citing
"the SPEC says ts-based as-of is undefined within windows" would be
paraphrasing beyond the text; the accurate citation is: as-of becomes
undefined within windows **when the interpreting rows have no shared witness
order with the facts** (SPEC.md:1133-1135).

The same paragraph's cost/benefit list names what fact-residence inherits,
SPEC.md:1140-1142: "Window membership, chain coverage, witness interleaving,
key-as-of, and dump totality are all inherited rather than built."

### 3.6 Pre-genesis as-of (§9.2 Lineage, era transition)

SPEC.md:1097-1105:

> **Existing stores open the era; they are not reborn.** Migrating a
> pre-lineage store is an era transition (§8.5), not an identity change:
> append one `genesis` event absorbing the current declaration document
> whole. Everything already in the store becomes the **pre-lineage era**
> — rendered honestly as legacy, never retro-claimed; an ontology-as-of
> read before the genesis reports *unhistorized*, earliest known state =
> the genesis document. The genesis MUST pin the store's chain head (or
> fact cursor) at absorption time, so "everything before me predates
> historization" is a verifiable claim, not an inference from row order.

This is the "genesis cursor pinning" the prompt asked about. Note the pinned
coordinate is "the store's chain head (or fact cursor)" — both
attestation-tier / witness-order artifacts, not a ts.

## 4. Cursors — exact vocabulary map

The SPEC never uses the phrases "temporal cursor", "ontology cursor", or
"fact cursor vs ontology cursor" as a pair. Its actual vocabulary:

| SPEC term | Where | Meaning | Axis |
|---|---|---|---|
| `fact_cursor` | §8.2 tick envelope (SPEC.md:807-808) | tick-envelope field; the window's end position | witness order |
| `window_start` | §8.2, §8.4 (SPEC.md:807, 846-848) | window's open position; "continues from the predecessor's `fact_cursor`" | witness order |
| "Unresolvable cursors" | §8.2 window hash (SPEC.md:818-819) | "yield the hash of the empty sequence (the empty commitment — claims nothing rather than guessing)" | witness order |
| **facts-as-of** | §9.3 (SPEC.md:1112-1113) | "which facts replay" — cursor #1 of a historical read | unstated (see §3.4) |
| **ontology-as-of** | §9.3 (SPEC.md:1113-1114) | "which declaration state interprets them" — cursor #2 | unstated |
| "equal cursors" | §9.3 (SPEC.md:1114), §9.5 (SPEC.md:1158-1159) | the mandated default; "an honest snapshot of what a reader at T would have seen"; "A historical read with equal cursors (§9.3) is the observer observing their own past focusing" | — |
| "unequal cursors" | §9.3 (SPEC.md:1115-1117), Lineage (SPEC.md:1086-1087) | deliberate reinterpretation; "MUST be explicitly requested, never a silent default" | — |
| "witness position" | §9.2 historized keys (SPEC.md:1058-1059) | the coordinate key-as-of resolves against | witness order |
| "time cutoff (§6)" | §9.2 (SPEC.md:977-978) | the mechanism for state-as-of-T on the declaration fold | event time |
| "epoch marker" | §8.4 (SPEC.md:847-848) | `window_start` when the predecessor is pre-chain: "the window opens at the new era, retro-claiming nothing" | witness order |
| "chain head (or fact cursor)" | §9.2 genesis pinning (SPEC.md:1103-1104) | what genesis MUST pin at absorption | witness order |
| "imported window/cursor" | §9.2 `merged` receipt (SPEC.md:1023, 1078-1080) | part of a merge receipt's payload | witness order (of the source) |

Name-collision hazard, stated empirically: `fact_cursor` (§8.2, a
witness-order chain field) and "facts-as-of" (§9.3, a replay cutoff) are
different concepts with adjacent names. §9.2's genesis rule ("chain head (or
fact cursor)") uses "fact cursor" in the §8.2 sense.

## 5. Tick windows and their relation to ordering

Definition of window membership and hashing, §8.2 SPEC.md:816-819:

> **Window hash:** for the window `(window_start, fact_cursor]` in witness
> order (§8.4), the incremental SHA-256 of the concatenated ASCII-hex fact row
> hashes, in order.

Chain linkage, §8.4 SPEC.md:845-848: "`window_start` continues from the
predecessor's `fact_cursor` (a pre-chain predecessor yields the epoch marker:
the window opens at the new era, retro-claiming nothing)."

Verification, §8.6 SPEC.md:900-901: "`verify` walks ticks in witness order,
recomputing `prev_hash` linkage and window hashes".

Sealed-window immutability, §8.4 SPEC.md:858-860 (quoted in §1 above): a
late-arriving fact with an old event-time "must not retroactively enter a
sealed window — that is honest witnessing, not tamper."

Interchange preserves witness order: §10.1 SPEC.md:1193-1196 — the dump is
"one JSONL stream carrying every row — facts, declaration events, ticks — in
**witness order** (§8.4), the order carried explicitly per line so a rebuild
reproduces it exactly." §10.5 owes "a witness-order fixture where event order
disagrees (the §8.7 two-authorities fixture, round-tripped)" (SPEC.md:1238-1240).

Tick payload contents relate to fold state (event-order product): §7.2
SPEC.md:678-683 — "A tick's payload is the **fold-state snapshot** at the
boundary, keyed by kind, with a `_boundary` provenance key merged in." (But
FINDINGS C3, FINDINGS.md:241-255, corrects the shape to TWO shapes:
loop-scope ticks carry bare projection state; only vertex-scope ticks carry
`{loop-name: state}` — an M4 write-path gate.)

So a tick is a hybrid object: its *window* is witness-order-bounded (§8.2/§8.4)
while its *payload* is a snapshot of event-order fold state (§7.2). The SPEC
states both halves but nowhere discusses their interaction (e.g., what fold
state "at the boundary" means when event order and witness order disagree
inside the window — the §8.7 fixture exercises exactly this disagreement but
only asserts each half follows its own authority).

## 6. Era-opening and genesis (SPEC §8.5, §9.2)

The era rule, §8.5 SPEC.md:882-887: "**hash inclusion follows data
presence.** Optional commitment fields (`signature`) enter an envelope only
when non-null, so every pre-era row hashes byte-identically forever and no
era transition re-anchors history."

Generalization, SPEC.md:889-896:

> **Era-opening is a protocol-level move, not a signing-specific one.** The
> pattern — open an era by *appending* its first row, render everything
> prior as honest legacy, never retro-claim — now has three instances:
> chain (this section), signature (this section), and lineage (§9.2, the
> pre-lineage era of a store that predates self-description). Any future
> capability that partitions a store's history into before/after MUST take
> this shape: capabilities arrive by append, the past is reported as it
> was, and no transition rewrites or re-anchors what came before.

Genesis identity, §9.2 Lineage SPEC.md:1063-1066: "A store's identity is its
genesis: the `id` of the `genesis` event IS the **lineage id** — minted once,
immutable, present in every dump, byte-identical across rebuilds." Genesis
cursor pinning quoted in full at §3.6 above (SPEC.md:1103-1105).

Related lineage rules bearing on as-of reads (SPEC.md:1072-1096):
self-resolution folds own lineage only ("A foreign lineage's events are inert
citizens: carried, attestable, never folded into self-description",
SPEC.md:1074-1076); merge SHOULD append a `merged` receipt so "fact → merge
receipt → source lineage → that lineage's declaration fold as-of" is
resolvable inside one store (SPEC.md:1078-1082); "Slice preserves identity;
fork is a new genesis" (SPEC.md:1090).

## 7. Residence (SPEC §9.2, §9.5, §10.4, §7.4)

"Residence" carries two related senses in the SPEC:

**(a) Host-boundness of declarations** — §9.2's portability axis,
SPEC.md:999-1004: "*Portable* asks whether the declaration travels with the
store as live configuration, or is bound to a **residence** — a capability of
one host (its paths, credentials, network position) that a recipient can
neither exercise nor is authorized to. A host-bound declaration transits as a
**provenance receipt shaped like configuration**: a true record of how facts
came to exist, conferring nothing." Enactment rule, SPEC.md:1035-1043: "An
implementation MUST NOT auto-enact a host-bound declaration that arrived by
transit or merge [...] A recipient who wants continued ingress declares their
own source, a new `source-defined` event in *their* witness order." The three
things held outside the store: key custody (§8.6), the locator (§9.5), and
ingress enactment (§9.2) — "the three things a store records but never
confers" (SPEC.md:1168-1170).

**(b) Where the store canonically lives** — §10.4 SPEC.md:1224-1229:
"Which encoding is *canonical at rest* is per-vertex configuration, outside
the protocol: **sqlite-resident** (the `.db` is the working store; JSONL is
wire/exchange) or **text-resident** (JSONL lives in version control; the
`.db` is a rebuilt local index)."

The `.vertex` file is demoted from residence: §9.5 SPEC.md:1161-1167 — "Under
this layer the `.vertex` file is not a residence. The store is canonical and
self-describing; a KDL document is an **ingress or render form** [...]
Nothing lives in the file between transits; a file that does persist is a
cache of a fold head, never an authority." §7.4's supersession note
(SPEC.md:736-743) says the same from the other side: "the KDL document
demotes from *residence* to *ingress/render syntax*".

Also relevant to residence-of-meaning: declaration events are
"subject-scoped documents" — complete current definitions, no facet deltas
(§9.2 SPEC.md:971-975), with the principled asymmetry "*facts are deltas
composed by declared folds; declarations are documents composed by nothing*"
(SPEC.md:986-987).

## 8. How the Go implementation actually treats ordering

- **Read path is `(ts, id)` with `_ts` injection.** `store/sqlite.go:41`:
  `SELECT kind, ts, observer, origin, payload, id FROM facts ORDER BY ts, id`.
  The doc comment (`store/sqlite.go:23-33`) states: "ReadFacts returns all
  facts in (ts, id) replay order [...] Mirrors the incumbent's
  `sqlite_store.since_raw / facts_for_replay` (ORDER BY ts, id @ loops
  14eb723)." The `ts` column is injected as `payload["_ts"]` (line ~60,
  "§6.2 _ts injection").
- **Column wins over payload `_ts`.** FINDINGS.md:584-596 (2026-06-12
  observation): injection "**overwrites** a payload-resident `_ts`"; "This
  matches the incumbent [...] It is **not** drift against Python — both
  overwrite. [...] a silent precedence rule (column wins over payload) [...]
  No action; the emit-side contract (`ts == payload _ts`) belongs to §7.1."
- **History:** the Go reader "was still `ORDER BY rowid` with no `_ts`
  injection (M1-era, deferred)" until the 2026-06-12 delta
  (FINDINGS.md:568-573).
- **Merge-commutativity is certified fixture-differentially, not natively.**
  `TestMergeCommutativity` reads two Python-merged stores (`merge_ab.db`,
  `merge_ba.db`) and must reproduce identical state from both directions
  (FINDINGS.md:574-582; SPEC.md:603-611). "Go has no merge primitive yet (M5
  unported), so the merge is performed by the reference engine and Go
  certifies the *replay-order* half end-to-end."
- **No witness-order machinery exists in Go.** `grep -rn witness --include
  "*.go"` returns nothing; no ticks, windows, chain, or cursor code. README
  status (README.md:15-27): M0 and M1 done; M2–M6 unstarted; "M4 boundaries +
  ticks [...] temporal parity; the order-fix + tick-payload decisions land
  here" (README.md:21). PLAN.md:143 (M4 row): "Where the **order-fix** and
  **silent-coercion** decisions land. [...] The order-fix is also what
  *licenses leaving concurrency unspecified*." PLAN's open decision 1
  (PLAN.md:180-184) — fix-both `(ts, id)` vs replicate rowid — is resolved:
  FINDINGS #2 (FINDINGS.md:74-84) dispositions it fix-both, and the
  2026-06-12 section records it shipped in both impls (incumbent `loops
  14eb723`, Go `store.ReadFacts`).
- **`TopN` tie-break nonconformance is known and open.** Go "tie-breaks by
  **key string**" and "must be brought to `(ts, id)` order to conform — a
  concrete fix-both task" (SPEC.md:402-406; FINDINGS.md:86-99). No tie vector
  exists in the corpus yet.

## 9. Divergences from the prompt's framing (empirical corrections)

1. **"ts-based as-of is 'undefined within windows'" is a paraphrase, not a
   quote.** The SPEC sentence (SPEC.md:1133-1135) is about a *third-table
   residence* having "no shared witness order with the facts it interprets";
   "ts-based" appears nowhere in it. The ts-reading is a plausible inference
   (the only shared coordinate a third table would have is ts), but any 0.8.0
   design citing this must cite the residence argument, not a ts prohibition.
2. **"Ontology cursor" / "fact cursor" as a cursor pair is not SPEC
   vocabulary.** §9.3's pair is **facts-as-of** / **ontology-as-of**;
   `fact_cursor` is an §8.2 tick-envelope field on the witness axis. Using
   "fact cursor" for the §9.3 replay cutoff would collide with the
   attestation-tier field name.
3. **The SPEC does not pick a single axis for the §9.3 cursors.** It binds
   specific as-ofs to specific axes piecemeal: ref resolution → event time
   (§6.3); declaration-state-as-of-T → "a time cutoff (§6)" i.e. event time
   (SPEC.md:977-978); key verification → witness position (SPEC.md:1058);
   window membership → witness order (§8.2/§8.4). The facts-as-of /
   ontology-as-of cursors themselves are axis-unspecified. This unresolved
   assignment — event-time cutoff for the declaration fold (§9.2) vs the
   witness-order framing of §9.4's residence argument and §9.2's key-as-of —
   is the live tension the 0.8.0 cursor-axis session has to settle; the SPEC
   as written contains both readings.
4. Everything else the prompt asserted exists and is where claimed: §9.2,
   §9.3, §9.4, §9.5, §10 all present; equal-cursors default present; genesis
   pinning present; era-opening generalization present.

## 10. Pointers for the cursor-axis session

Claims the session will lean on, in one place:

- Event order answers "what happened"; witness order answers "what this store
  received" — SPEC.md:850-856. Conflation ⇒ "false tamper alarms or
  non-deterministic folds" — SPEC.md:860-863.
- `(ts, id)` guarantees set-determinacy, NOT sub-millisecond temporal
  last-write-wins — FINDINGS R5 (FINDINGS.md:301-312) + adjudication
  (FINDINGS.md:481-489).
- The general read rule: "most-recent reads order by `(ts, id)`, never
  `rowid`" — FINDINGS H4 (FINDINGS.md:462-467).
- Windows are witness-order intervals `(window_start, fact_cursor]` —
  SPEC.md:816-817; sealed windows never admit late arrivals — SPEC.md:858-860.
- Historical reads: two cursors, equal by default, unequal only on explicit
  request — SPEC.md:1110-1119.
- Declaration state is a `Latest` fold keyed `(lineage, kind, subject)`,
  self-lineage only; as-of-T = "time cutoff (§6)" — SPEC.md:974-979,
  1072-1076.
- Key-as-of resolves at witness position — SPEC.md:1056-1061.
- Genesis pins chain head (or fact cursor) at absorption; pre-genesis
  ontology reads report "unhistorized" — SPEC.md:1097-1105.
- Declaration events live in `facts` under a reserved kind namespace;
  witness interleaving is inherited — SPEC.md:1128-1143.
- The dump is witness-order JSONL, byte-deterministic, round-trip-exact —
  SPEC.md:1193-1220.
- §9–§10 are PROVISIONAL: "design-led, not discovered [...] All rules here
  are PROVISIONAL pending the incumbent build and its vectors" —
  SPEC.md:929-935.
