# Domain-neutral primitives — grounding slice

Receipts for the claim in `observation:architecture/instrument-family-survey-read` (2026-07-26),
verdict (4):

> The three domain-neutral primitives (recency-rank, threshold-breach, bucket-partition)
> have five consumers and a ratified charter — overdue by our own promotion rule.

Grounding requested by `thread:010-surfacing-wave` (RIDER), which states the charter
"is not findable as a store fact." **That is wrong — the charter is findable.** The
problem is different and worse: the charter says something other than what the survey
says it says. Detail in §2.

Scope note: this document establishes receipts only. It records constraints on a landing
spot (§4) but deliberately recommends none.

---

## 1. The survey artifact

**Found.** It is a published Artifact, not a file in either repo:

- Title: *The instrument family — record, relevancy, view, surfacing*
- URL: https://claude.ai/code/artifact/2836a13c-e7b8-486f-8c06-ed35a2941da2
- Updated 2026-07-26, owned by Kyle. Eyebrow reads `architecture · grounded survey · 2026-07-26`.
- Footer: "Grounded in a five-agent survey of ~/Code/loops · libs: atoms · custody · engine ·
  lang · sign · store · apps: loops · hlab · tasks · forcing functions: siftd · tasked · vouch"

There is **no file copy** anywhere. `docs/scratch/` holds only `080-overnight/` and
`090-wave/`; `grep -rl "instrument-family"` across both repos hits exactly one file,
`ARCHITECTURE.md:97`, which cites the survey as the source of the four-layer table.
Worth noting for the wave: the survey is load-bearing on `ARCHITECTURE.md` and on
`design:architecture/surfacing-layer-charter`, and it exists only as a hosted page.

### What the survey actually says about the primitives

Section 05, *Evidence that relevance is a library*, opens:

> Five applications independently hand-roll the same three judgments. None share code.
> There is no `loops.relevancy` to call.

Then a 5-column × 5-row matrix. **The "five consumers" are five applications, one per
column — not five code sites.** Columns: `loops`, `hlab`, `tasks`, `siftd`, `tasked`.
Rows are judgments, and only the first three are the "domain-neutral primitives":

| Judgment | loops | hlab | tasks | siftd | tasked |
|---|---|---|---|---|---|
| rank by time-since | `_horizon_sort_key` | `last_scrape` | `_sort_recent_first` | `--sort recency` | activity order |
| threshold breach | `_approaching()` | `_is_healthy()` | **—** | score cutoff | cap / retry |
| bucket partition | never-sealed / armed | firing / healthy | `_CLOSED_STATUSES` | tag filters | status ladder |
| match ranking | FTS5 match, unranked | — | — | `RRF · MMR rerank` | — |
| what's next | — | — | — | — | `walker.py` — 1,401 lines |

Its verdict: *"library of domain-neutral primitives, plus an authored escape hatch"* —
recency, threshold, partition and match-rank *"recur across every app and generalize"*,
with siftd's per-preset RRF tuning kept authorable as "the 5%, not the shape."

Two things fall straight out of the survey's own table:

- **Rows 4 and 5 are not five-consumer.** Match-ranking is siftd-only (1/5); what's-next
  is tasked-only (1/5). The store observation's verdict (3) already ruled walker out as
  residue, and the survey's own §08 open question ("is *act* an edge or a second
  instrument?") contradicts its inclusion in the table. The observation is faithful here.
- **Threshold-breach is 4/5 by the survey's own hand** — the `tasks` cell is a dash. The
  claim of "five consumers" for all three primitives is not what the artifact says.

The survey **does not state a promotion rule** anywhere. "Overdue by our own promotion
rule" is the store observation's own framing, added on read. See §3.

---

## 2. The "ratified charter" — found, and mis-cited

The survey names it explicitly in the §05 callout:

> Your own doctrine already ratified the principle: `decision:design/grammar-domain-neutrality`
> — *"CLI/lens grammar concepts (e.g. 'staleness') must be domain-neutral, apply identically
> across design-thread and chat-memory data."* That is the relevance library's charter.
> It just never got a package.

**Location:** project store, `decision:design/grammar-domain-neutrality`, 2026-07-03,
tier=mid, N=1, inbound=2. Read with
`sl read project decision/design/grammar-domain-neutrality --full --plain`.

**Actual text** (verbatim, in full):

> Kyle's catch (2026-07-02, echoing the painted semantic-renderer reframing): the grammar
> layer must not bake THIS vertex's domain vocabulary into rendering — 'status-aware ⊘'
> assumed a status=open lifecycle field that is our schema, not loops'. Data-equivalent of
> semantic staleness exists in two layers: (1) the three-term salience contract is already
> domain-neutral, and digest-coverage IS data-level staleness (dissolved when covered, not
> when old — identical for a design thread covered by a decision and a chat memory covered
> by a consolidation digest); (2) interim ⊘ follows the DECLARED-semantics pattern (fold
> keys, typed edges): a kind declares its lifecycle field (e.g. lifecycle "status"
> open="open,in-progress"), late-bound + retroactive; ⊘ = aged-while-open per declaration;
> undeclaring stores never rail ⊘. General principle: grammar consumes declared semantics,
> never assumes field vocabulary. Doc §5b amended.

Three problems, escalating in severity.

**(a) The quotation is fabricated.** The quote-marked string in the survey does not appear
in the fact. It is a paraphrase wearing quotation marks. The paraphrase is directionally
fair — domain-neutrality of grammar concepts is the subject, and design-thread-vs-chat-memory
is the fact's own example — but nothing in the fact reads that way, and a reader checking
the citation finds no such sentence.

**(b) The charter's own prescription is the opposite of a package.** The fact's named
remedy is the **DECLARED-semantics pattern** — "a kind declares its lifecycle field …
late-bound + retroactive" — and its closing general principle is "grammar **consumes
declared semantics**, never assumes field vocabulary." That is a dissolve-into-the-declaration
instruction. "That is the relevance library's charter. It just never got a package" is the
survey's inference laid on top; the charter itself points the other way.

This is not a subtle reading. The store observation caught the same thing independently
from a different angle — verdict (2), the stale-cell finding: the survey's `lifecycle`
row ("executed ad hoc in each app") predates the 090-S5 unification, where the record
layer executed a relevance-shaped declaration *by growing the substrate*. The charter
prescribed declaration; the substrate delivered declaration; the survey read the
pre-delivery state and concluded a package was owed.

**(c) A naming collision hides the trail.** The charter's clause (1) refers to "the
three-term salience contract" — that is a **different** triple, `decision:design/salience-three-term-contract`
(RATIFIED Kyle 2026-07-01, tier=mid, N=1, inbound=3): `salience = f(recency, inbound-refs,
digest-coverage)`. Those three terms are *not* the survey's three primitives
(recency-rank / threshold-breach / bucket-partition). Two distinct triples, both called
"three-term," in adjacent facts.

This explains the thread's "not findable" note exactly: `sl read project --match "three-term"`
returns **one** result (a closed session thread), and searching salience lands on the
salience contract, which is visibly not a charter for these primitives. The charter is
reachable only by name, not by content search. Related and also distinct:
`decision:design/salience-dials-vertex-declared` (2026-07-03) — "the grammar owns the
contract's SHAPE …; the vertex declares the weights/cutoffs/lifecycle," another
declaration-not-package ruling on the same material.

---

## 3. The promotion rule

`sl read project --match "promotion rule"` returns nothing but the survey-read observation
itself. There is no fact keyed as a promotion rule. The rule being appealed to is the
**N=2 bar**, articulated in two places:

- `paradigm/cross-repo-consumer-runtime-contract` (tier=high, N=4, inbound=9) — the
  operative statement: *"When reaching to add substrate enforcement for ANY discipline on
  this list, burden of proof is high; the discriminating questions are (1) is there a second
  consumer with concrete divergent constraints needing this TODAY? (N=2 bar) and (2) does
  the discipline genuinely not live at consumer-runtime?"*
- `decision:practice/emit-shape-discipline-hypothesis-vs-decision` (2026-05-15) — sharpens
  it: N=2 must come from **independent** sites, not within-arc, or the right kind is
  `hypothesis status=proposed`, not a decision.

Under the rule as written, "overdue" is **not** established:

- Question (1), the count bar, clears easily — far more than two sites for recency-rank and
  bucket-partition (see §4 and the sweep inventory below).
- Question (2) is **unanswered**, and the charter's own remedy is an affirmative answer that
  the discipline *does* live at declaration/consumer-runtime. The promotion rule's second
  question is the one that decides this, and the grounding cuts against promotion.

Also live: `CLAUDE.md`'s dissolution test ("can X be expressed as a property or composition
of what already exists?"), and the `ARCHITECTURE.md` relevance-layer gate — *"Whether
relevance becomes a package or stays a declaration vocabulary is decided on evidence, after
the third declaration-executed judgment lands, not before. Until then nothing claims the
relevance name."* Lifecycle was the first. A package promotion now pre-empts a gate the
repo set eight days ago on this exact question.

---

## 4. The five consumers — cell-by-cell verification

Two read-only sweeps (loops CLI + libs; hlab/tasks/engine/lang) plus external-repo checks.
Verdict per survey cell:

### recency-rank — 4/5, one cell refuted

| Cell | Verdict | Evidence |
|---|---|---|
| loops `_horizon_sort_key` | CONFIRMED, but **double-counted** | `apps/loops/src/loops/commands/fetch.py:1586`. It is a 3-stratum range partition *combined with* in-stratum ranking — i.e. it is the same function the survey also cites in its bucket-partition row ("never-sealed / armed"). One function, two cells. |
| hlab `last_scrape` | **REFUTED** | `last_scrape` occurs exactly twice in hlab: a parse field at `apps/hlab/src/hlab/loops/prometheus/targets.loop:18` and an **unused** dataclass field at `apps/hlab/src/hlab/lenses/alerts.py:54`. It is never read for age, ordering, or ranking anywhere. The sweep found **zero** recency-rank hand-rolls in hlab. This cell is a dead field, not a judgment. |
| tasks `_sort_recent_first` | CONFIRMED | `apps/tasks/src/strange_loops/commands/dashboard.py:336` — `sorted(tasks, key=lambda t: t.activity or epoch, reverse=True)`. |
| siftd `--sort recency` | CONFIRMED (external) | `siftd/cli/search.py:230`, `siftd/serve/routes.py:1000`. |
| tasked activity order | plausible (external, not line-verified) | — |

### threshold-breach — 4/5 by the survey's own table; the loops cell is misclassified

| Cell | Verdict | Evidence |
|---|---|---|
| loops `_approaching()` | **MISCLASSIFIED — this is substrate working correctly** | `apps/loops/src/loops/lenses/horizon.py:83` `_approaching` holds **no** threshold. It delegates: `return count > 0 and p.horizon_approaching(row["window_facts"] / count)` (`horizon.py:96`). The cutoff lives at `apps/loops/src/loops/palette.py:183`, constants `_HORIZON_WARN=0.6` / `_HORIZON_CRITICAL=0.85` at `palette.py:32-33`, whose docstring reads: *"The threshold lives here — the lens carries no proximity constant."* `lenses/horizon.py` holds zero local constants. This is the single-sourced pattern already in place. |
| hlab `_is_healthy()` | CONFIRMED — **worse than claimed** | Four copies: `lenses/status.py:36`, `folds.py:33`, `commands/enrichment.py:94`, `commands/enrichment.py:136`. Two disagree: `state == "running" and health in ("healthy","")` vs `state != "running" or health == "unhealthy"`. A `starting` container is healthy to `folds.py` (which computes the healthy count) and unhealthy to `enrichment.py` (which decides who gets inspected/log-tailed) — a stack can report `4/4 healthy` while enriching a container as unhealthy. Live latent defect, worth its own emit regardless of the promotion. |
| tasks | survey says **—** | The sweep found a fillable one: `apps/tasks/src/strange_loops/harness.py:97` — `exhausted = exit_code == 0 and "max turns" in last_line.lower()`, a worker-limit breach detected by string-sniffing the last output line. The dash is the survey's, not reality's; but the survey's claim is 4/5 as printed. |
| siftd score cutoff | plausible (external) | — |
| tasked cap / retry | plausible (external) | — |

### bucket-partition — 5/5, one cell shared with recency

| Cell | Verdict | Evidence |
|---|---|---|
| loops never-sealed / armed | CONFIRMED — same site as the recency cell | `apps/loops/src/loops/commands/fetch.py:1586` `_horizon_sort_key`. |
| hlab firing / healthy | CONFIRMED | `apps/hlab/src/hlab/lenses/alerts.py:184` (count→severity style), `:202` (two-way partition by health). |
| tasks `_CLOSED_STATUSES` | CONFIRMED | `apps/tasks/src/strange_loops/commands/dashboard.py:442`. |
| siftd tag filters | plausible (external) | — |
| tasked status ladder | plausible (external) | `tasked/src/tasked/walker.py` confirmed at 1,401 lines. |

### The finding that inverts the survey's thesis

The survey's argument is *"no package exists, therefore five apps hand-roll."* Inside
`apps/loops` the causation runs the other way for two of the three primitives. **A canonical
home already exists, is correctly consumed by roughly 20 call sites, and the duplications
are forks that bypass it.**

The existing homes:

- **bucket-partition + threshold-breach:** `apps/loops/src/loops/surface.py:525` `_tier_thresholds`,
  `:549` `_tier_for`, `:560` `tiers_for_scores`, `:574` `_assign_tiers` — canonical quantile
  tiering into `high`/`mid`/`tail`; `:710` `tier_map` (documented as the single inheritance
  handle, "tier is assigned exactly once"); `:733` `tier_max`.
- **threshold-breach:** `apps/loops/src/loops/palette.py:160` `freshness_style` (4-band,
  constants `_FRESH`/`_RECENT`/`_STALE` at `:22-24`), `:170` `horizon_meter_style`,
  `:183` `horizon_approaching`.
- **recency-rank:** `apps/loops/src/loops/lenses/_grammar.py:78` `recency()`, `:130` `duration()`;
  `apps/loops/src/loops/surface.py:1015` `budget()` (the declared read-path rank primitive).

Correct consumers (import, do not recompute): `commands/fetch.py:516,608,676,721,782,797`,
`commands/ls.py:333,474`, `lenses/confluence.py:151`, `lenses/fold.py:35`,
`lenses/horizon.py:96,388`, `lenses/vertices.py:24`, `lenses/declarations.py:23`,
`lenses/_statview.py:95`, `lenses/ticks.py:92`, `lenses/stream.py:153`, `lenses/graph.py:263`,
`.loops/lenses/session_landing.py:43`, `~/.config/loops/lenses/session_start.py:25`.

So within loops the defect is **"the home is app-local and unenforced,"** not "there is no
home." That is a relocation-plus-ratchet problem, not a greenfield-package problem — a
materially different piece of work with a different risk profile. And the survey's own
loops threshold-breach exemplar (`_approaching`) is not evidence of the gap; it is loops'
proof that it already closed it.

### Forks that bypass the existing home (the real backlog)

Sharpest, from the sweeps — these are the drift, and they are what a ratchet would have to catch:

- **Two independent 7-day staleness cutoffs, opposite comparison directions.**
  `.loops/lenses/session_landing.py:166` (`_STALE_THRESHOLD_SECS = 7 * 86400`, used at `:202`/`:212`)
  and `.loops/lenses/reconcile.py:190-193` (`(now - item.ts) > 7 * 86400` inline). Same concept,
  two literals, no shared helper. Clearest duplicate pair in the repo.
- **Namespace grouping forked three times.** `apps/loops/src/loops/lenses/fold.py:1450`
  `_group_by_namespace`, re-implemented at `.loops/lenses/session_landing.py:806-810` and
  `~/.config/loops/lenses/session_start.py:259-263`.
- **A complete parallel tier system.** `.loops/lenses/session_landing.py:962` `_compute_marks`
  + `:1046` `_mark_priority` — a bespoke 5-level ladder (`added=4/updated=3/cited=2/stale=1/unmarked=0`)
  running alongside `surface._assign_tiers`' `high/mid/tail` and touching none of it. Largest
  hand-rolled tiering in the repo.
- **Five forks of `_grammar.recency`/`duration`:** `.loops/lenses/reconcile.py:72` `_recency_tag`
  (own bands plus `w`/`mo` buckets the substrate lacks), `apps/loops/src/loops/lenses/sync.py:12`
  `_format_ago` and `:24` `_format_interval`, `~/.config/loops/lenses/comms.py:40` `_relative_time`,
  `.loops/lenses/session_landing.py:1198` `_fmt_duration` (in a module that *already imports*
  `_recency_tag` — half-consumes, half-forks).
- **Two sparkline bucketers that disagree.** `apps/loops/src/loops/commands/store.py:38`
  `_sparkline_str` vs `apps/loops/src/loops/lenses/_statview.py:58` `spark` — different rounding,
  different zero-handling (`" "` vs `"·"`). A behavioural divergence, not a style one.
- **A magic salience cutoff declared twice:** `_SALIENCE_BODY_THRESHOLD = 2` at
  `~/.config/loops/lenses/session_start.py:43` and `.loops/lenses/session_landing.py:80`,
  bypassing `surface.py`'s tier vocabulary. Plus a bare `r.salience > 1` at `surface.py:1035-1038`,
  inside `budget()`, beside the quantile machinery.
- **Substrate self-duplication worth a separate ticket:** `libs/engine/src/engine/handle.py:1505-1546`
  (`changes`) and `:1601-1636` (`changes_async`) hold byte-identical coalesce/`max_latency`/`idle_timeout`
  deadline arithmetic. A fix to one silently misses the other.
- **Non-loops apps:** hlab `_is_healthy` ×4 (above); `apps/hlab/src/hlab/commands/media_audit.py:88`
  — a two-tier `< 0.3` / `< 0.6` cutoff whose branches assign identical `status` and `reason`,
  so the 0.3 boundary is dead code; `apps/tasks/.../dashboard.py:78` `_status_style` vs
  `apps/tasks/.../store.py:141` `_tick_status_style` — two status→style ladders with divergent
  fallbacks, so the dashboard and the log timeline paint the same task different colors.

### Substrate that resembles the primitives but is not a hand-rolled consumer

Checked and cleared — these exist *to be* the general mechanism, parameterized from the DSL:

- `libs/engine/src/engine/loop.py:111` — the count-boundary firing primitive (`boundary_count`,
  modes `when`/`after`/`every`); count is declared, `fire()` owns reset/exhaustion at `:158`.
- `libs/engine/src/engine/vertex.py:106` `_eval_condition` — **the** threshold-breach evaluator,
  operator-driven, target and value from the declaration. `_eval_conditions` at `:145` is the
  AND-fold. This is the mechanism the hlab/tasks consumers each re-implement locally.
- `libs/lang/src/lang/ast.py:419` `BoundaryCondition` — the grammar tier of the above, with the
  validated operator vocabulary `{">=","<=",">","<","==","!="}`; parsed at `lang/loader.py:345`.
- `libs/engine/src/engine/cadence.py:66` `should_run` — the shared elapsed/triggered predicate.
- `libs/engine/src/engine/witness.py:752` `resolve_tick_floor`; `:205` `receipt_group_span`;
  `:300` `group_boundary` floor/refuse modes — substrate window addressing and boundary policy.
- `libs/engine/src/engine/handle.py:659` `_fold_sections` / `:663` `_section_index`;
  `libs/engine/src/engine/vertex_reader.py:660` (`vertex_summary` per-kind earliest/latest);
  `libs/engine/src/engine/compiler.py:247` (`Collect(max=…)`, `Window(size=…)` as declared
  bucket/limit primitives); `libs/engine/src/engine/store.py:202` `between`.
- **`libs/engine/src/engine/peer.py` — cleared explicitly.** Grant/Peer `horizon` is pure
  frozenset union (`grant`/`expand_grant`) and intersection (`restrict`/`delegate`). No numeric
  comparison, no cutoff, and no `horizon` *check* site exists in engine at all. It resembles
  threshold-breach only lexically ("horizon check").
- **`libs/atoms` and `libs/store` are clean of all three.** `atoms/fold.py:108` `TopN` and
  `:216` `Window` are declarative op specs, not implementations; `store/merge.py:101,109`
  uses SQL `ORDER BY ts, id` for merge determinism, not ranking.
- **`libs/lang` validator holds no cutoff computation** — shape inference and error accumulation only.

One boundary case that belongs with the hand-rolls: `apps/hlab/src/hlab/folds.py:31` —
`containers[-50:]  # cap to match DSL spec` — a Python line hand-duplicating `Collect`'s
declared cap. A hand-roll *shadowing* substrate.

Also negative: **no `ticked` daemon source exists.** Only docstring/test references
(`libs/engine/src/engine/handle.py:5,16,1000,1307,1443,1449`,
`libs/engine/tests/test_handle_bench.py:113`, `apps/loops/tests/test_integration.py:1241`).
It is a *planned* consumer of `Handle.changes()`, not code. Do not count it.

---

## 5. Constraints on the eventual landing spot

Recorded, not resolved. No recommendation.

**C1 — the relevance-layer gate is already set, and a promotion pre-empts it.**
`ARCHITECTURE.md` (§ Layers — the instrument families): relevance is *deliberately homeless*;
*"Whether relevance becomes a package or stays a declaration vocabulary is decided on evidence,
after the third declaration-executed judgment lands, not before. Until then nothing claims the
relevance name."* Lifecycle was the first. Whatever lands must either not claim the relevance
name, or reopen that gate explicitly.

**C2 — layer designation is mandatory and DAG-enforced.** `tests/test_architecture.py:248`
`_LIB_ALLOWED_RUNTIME`: `atoms`, `lang`, `sign` have **empty** allowed sets; `engine → {lang, atoms}`;
`store → {engine}`; `custody → {sign, engine}`. Per `ARCHITECTURE.md`, a new library must declare
its layer or the suite fails (Rule 11), and **record never imports surfacing**. The stated law
for relevance is *"injection, not import"* following custody's precedent — so anything the record
layer must *call* cannot be imported by record.

**C3 — the current homes are app-local, so promotion moves code downward.** All three canonical
implementations live under `apps/loops/src/loops/` (`surface.py`, `palette.py`, `lenses/_grammar.py`).
Libs cannot import from apps. Promoting them reverses the current direction of travel and forces a
prior decision about which layer they belong to — note that tier-assignment and freshness-styling
are arguably **view**-adjacent, and `painted` (external, PyPI) already owns palette-shaped concerns.
That boundary is undecided.

**C4 — two of five consumers are external repos, with incompatible dependency footings.**
This is the hardest constraint and the survey does not address it.

- **tasked** (`/Users/kaygee/Code/tasked`): depends on `strange-loops>=0.8.1` and `painted>=0.13.0`.
  Its `pyproject.toml:9-12` pins the policy in a comment: *"Dependencies come only from released
  artifacts on PyPI, never path/editable sources (`decision:design/deps-released-loops-only`).
  Tight co-development uses an uncommitted local `[tool.uv.sources]` override — that override must
  never be committed."* Anything tasked consumes must ship in a **published** strange-loops release first.
- **siftd** (`/Users/kaygee/Code/siftd`): depends on `painted>=0.4.0`, `numpy`, `httpx`, `mistune`,
  `asyncssh`, `tomlkit` — and **does not depend on strange-loops at all.** A loops-hosted primitives
  package would require siftd to take a brand-new dependency on the entire strange-loops distribution
  to obtain three functions. If siftd is counted as a consumer, then `painted` is the only shared
  dependency both external consumers already have — and painted is view-layer, in its own repo,
  consumed from PyPI, with the version-collision footgun already on record.

Consequence worth stating plainly: the consumer set spans three independently versioned
distributions, and the two external members share no loops dependency. "Five consumers" is
not five call sites in one import graph.

**C5 — a landing spot without a ratchet becomes a third place to fork from.** Two of the three
primitives already have a canonical home with ~20 correct consumers *and* a documented fork
backlog (§4). This is the same argument `design:architecture/surfacing-layer-charter` used against
a mega-lib — *"a mega-lib would just be a third place to misfile into."*

**C6 — the ratchet for this is detection-shaped, which the repo has priced as expensive.**
Per `decision:practice/construction-vs-detection-ratchets` and `docs/RATCHETS.md`: "don't fork
the primitive" is enforceable only by building a parallel model and scanning (AST-walking for
local `now - ts` arithmetic, enumerating callers) — unless the primitive can be *constructed* so
a fork is inexpressible. The 090 wave's finding was that detection ratchets fell 3-4 adversarial
rounds running, and that the unifying defect class was hand-enumeration. Budget accordingly, or
find the construction form.

---

## 6. Summary of discrepancies

| # | Claim | Grounding |
|---|---|---|
| 1 | charter "not findable as a store fact" (`thread:010-surfacing-wave`) | **Wrong** — `decision:design/grammar-domain-neutrality`, 2026-07-03. Findable by name; invisible to content search because "three-term" collides with `decision:design/salience-three-term-contract`. |
| 2 | the charter ratifies a relevance *library* | **No** — it prescribes the DECLARED-semantics pattern and closes with "grammar consumes declared semantics." Dissolve-into-declaration, not promote-into-package. The survey's quotation of it is a paraphrase in quote marks; the string does not appear in the fact. |
| 3 | five consumers, all three primitives | **4/5 for threshold-breach by the survey's own table** (tasks is a dash). recency-rank is 4/5 in reality — hlab's `last_scrape` is a dead field, never read for ordering. loops' recency and partition cells are **one function**, `_horizon_sort_key`. |
| 4 | "overdue by our own promotion rule" | No fact states a promotion rule. The N=2 bar (`paradigm/cross-repo-consumer-runtime-contract`) has two questions; the count clears, but question (2) — "does the discipline genuinely not live at consumer-runtime?" — is unanswered and the charter answers it affirmatively. |
| 5 | "no package exists → five apps hand-roll" | **Inverted inside loops** for two of three primitives. A canonical home exists (`surface.py` tiering, `palette.py` thresholds, `_grammar.recency`) with ~20 correct consumers; the duplications are forks *away* from it. The survey's own loops threshold exemplar `_approaching` is a correct consumer of that home, not a hand-roll. |

**Incidental defects surfaced, worth emitting independently of the promotion:**
hlab's four-way `_is_healthy` divergence (`folds.py` vs `enrichment.py` disagree on `starting`);
`media_audit.py:88`'s dead `< 0.3` branch; the two disagreeing sparkline bucketers;
`handle.py`'s duplicated `changes`/`changes_async` deadline arithmetic.

---

## 7. Layer-sort — species of each fork consolidated

Slice A converged the **in-repo** forks from §4 onto the homes that already
existed. §4 above is left as the dated pre-consolidation receipt; this section
records the disposition and, for the wave's promotable-subset question, the
*species* of each fork. Species vocabulary: **judgment** (a decision follows
from the result), **data-shaping** (restructures values, decides nothing),
**display** (renders an already-computed quantity for a human).

| Fork site | Species | Converged on |
|---|---|---|
| `lenses/sync.py:11` `_format_ago` | display | `lenses/_grammar.recency` |
| `lenses/sync.py:23` `_format_interval` | display | `lenses/_grammar.duration_secs` (new seconds-taking core of `duration`) |
| `commands/store.py:38` `_sparkline_str` | display | `lenses/_statview.spark` |
| `surface.py:1035` bare `r.salience > 1` in `budget()` | judgment | `surface.SALIENCE_ATTENDED_MIN` / `is_attended` (named in place) |
| `.loops/lenses/reconcile.py:190` + `session_landing.py:166` 7d cutoffs | judgment | `surface.STALE_AFTER_SECS` / `is_stale` (home built; the two consumers migrate in the lens slice) |

### What the sort shows

**The species split cleanly by home, and the two homes sit in different layers.**
Every display fork wanted `lenses/` (`_grammar` for time, `_statview` for
glyphs); every judgment fork wanted `surface.py`. Not one fork wanted both, and
no fork was mis-sorted by the consolidation.

That bears directly on **C3** and on the promotable-subset question. The forked
population is not one undifferentiated "primitives" set:

- The **display** primitives are view-layer. They are formatting vocabularies —
  `recency`'s calendar cutover, `spark`'s glyph ramp — and `painted` (external,
  PyPI, already a dependency of *both* external consumers per C4) is the
  package that owns concerns of that shape. Nothing about them needs a store.
- The **judgment** primitives are relevance-layer, and they are the ones behind
  the `ARCHITECTURE.md` gate (**C1**). They are also the smaller set.

So "promote the primitives" is at least two decisions with different answers,
different layers, and different consumer footings — the recency/threshold/
partition triple the survey names cuts *across* the split rather than along it
(`recency` is display; `is_stale` is a threshold-breach over the same axis and
is judgment). Any promotable subset should be enumerated by species, not by the
survey's three-row table.

**Second finding: the display forks were not neutral duplicates.** Both carried
a behaviour regression relative to the home they bypassed, so consolidating
changed output for the better in both cases:

- `_sparkline_str` mapped its levels by *floor* over a space-first 9-glyph
  alphabet, so any bucket under ⅛ of the series max rendered as `" "` —
  real activity painted as absence. `spark` rounds every non-zero bucket up to
  at least `▁` and marks zero as `·`. Measured live on this repo's store:
  buckets `[10, 0, 16, 14, 5, 3, 1, 1]` rendered `"▅ █▇▂▁  "` under the fork and
  render `"▆·██▄▃▂▂"` under `spark` — the two trailing buckets each hold a real
  tick and the fork drew them as empty columns, indistinguishable from the
  genuinely-zero bucket at position 2.
- `_format_ago` had no calendar cutover, so a source last run months ago
  rendered `"197d ago"` where `recency` gives `"Feb 27"` — the drift
  `_grammar`'s docstring names as the reason the cutover exists.

Neither divergence was deliberate: the only place the sync fork was documented
(`tests/golden/test_sync.py`, `tests/golden/fixtures.py`) described it as a
*testing consequence* ("reads `time.time()` directly … the clock is frozen
here"), never as a contract. Drift, consolidated.

**Third finding: `> 1` and `>= 2` were never drifted values.** §4's last bullet
reads as two thresholds, 1 and 2. `salience` is an `int`, so `salience > 1` and
`salience >= 2` are the *same* boundary spelled two ways — one judgment, two
comparison forms, which is exactly why the duplication was invisible to review.
The consequences differ (`budget` drops the row; the session lenses withhold
the body) but the cutoff does not, so it is named once. Watch for this shape
elsewhere in the inventory: forks that disagree *syntactically* while agreeing
*arithmetically* will not show up in a grep for a literal.

The same applies to the two 7d cutoffs, which §4 records as "opposite
comparison directions." They are opposite in *form* — `session_landing`
excludes on `item.ts >= now - 7d`, `reconcile` includes on `(now - item.ts) >
7d` — and identical in *semantics*, boundary included: neither treats an item
exactly 7d old as stale, and both treat `ts is None` as not-stale. `is_stale`
preserves both properties (strict `>`, `None → False`) so the migration is
behaviour-preserving at both sites.

### Residue found while sorting, not touched

- **A sixth `recency` fork**, in-repo and absent from §4's list of five:
  `apps/loops/src/loops/tui/store_app.py:468` `_relative_time` — a fifth `Ns
  ago` ladder, with a `"just now"` branch for negative deltas that no other
  fork has. Left alone: the TUI is a separate arc with its own goldens on main.
  Note it shares a *name* with the untracked `~/.config/loops/lenses/comms.py:40`
  fork, so the two are one grep apart.
- `commands/store.py`'s `_bucket_timestamps` (the data-shaping half of the
  sparkline pair) was **never forked** — only the display half was. It stays in
  `commands/store.py`, which is the honest place for it: it shapes store data
  and decides nothing. The species split runs through the middle of what §4
  described as a single "sparkline bucketer" fork.
