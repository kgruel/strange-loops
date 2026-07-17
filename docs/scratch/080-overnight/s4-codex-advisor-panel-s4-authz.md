# Panel review — AUTHORIZATION-SOUNDNESS lens on s4-codex-advisor.md (Digest)

*2026-07-17. Claude-family skeptic pass, last gate before implementation.
Method: every load-bearing claim re-derived against source or store, not taken
from the document or the prior codex pass. Commands run read-only (grep, sed,
sqlite3 `mode=ro`).*

## Verdict: AMEND

The core resolution — target-local grants, one projection from persisted
`GrantDecl.potential` into engine `Grant`, one evaluator for emit and Digest —
is a genuine dissolution, not a third path. I tried to break it and could not
break the *shape*. But the synthesis under-specifies four things that a naive
Gate 0 implementation would get wrong, two of which are live-production
privilege-isolation concerns. Named amendments below.

---

## 1. Verification ledger

### 1.1 The gate fact — found and verbatim

`store-dumps/facts-60d.txt:20` and `store-dumps/fold-current.txt:1331` carry
`observation:architecture/parallel-authorization-paths` (2026-07-16 audit).
The synthesis's blockquote in §3 matches the store dump **verbatim** — checked
word-for-word, including "Echoes convergence/consumer-more-substrate-aligned-
than-substrate (2026-05-13)".

### 1.2 Grant/Peer dataclass quotes — verbatim against source

The synthesis's §3 code block matches `libs/engine/src/engine/peer.py:13-51`
exactly, including both docstrings and the `substrate-friction/peer-assertion-
relation` reference. No drift.

### 1.3 The two paths — re-derived, both claims confirmed

**Path (a) is enforced.** `apps/loops/src/loops/commands/identity.py:240-247`:

```python
if decl.grant is not None and kind not in decl.grant.potential:
    allowed = sorted(decl.grant.potential)
    return ObserverCheck(
        "forbidden", ...
```

wired at `apps/loops/src/loops/commands/emit.py:631-634`:

```python
obs_check = check_emit(vertex_path, observer, kind)
if obs_check.status == "forbidden":
    _say(f"Error: {obs_check.message}")
    return 1
```

**Path (b) exists and is dead in production.** The engine gate is real —
`libs/engine/src/engine/vertex.py:507`:

```python
if grant is not None and grant.potential is not None and kind not in grant.potential:
    return Receipt(fact_id=None, tick=None, stored=False)
```

and every production receive site is bare: `emit.py:782`
(`receipt = program.receive(fact)`), `emit.py:1228` (`program.receive(fact)`),
`init.py:301` (`v.receive(fact)`). Grant-passing callers exist only in engine
internals (child forwarding `vertex.py:584`, executor, replay — replay passes
`grant=None` at `replay.py:32`) and benchmarks/tests. Confirmed: zero CLI
sites construct a Grant.

**Grant-horizon enforced nowhere.** Every "horizon" hit in `apps/loops/src`
is the Horizon *lens* (loop-boundary proximity: `palette.py:170`,
`fetch.py:1122`) — an unrelated concept sharing the word. No read path
consults `Grant.horizon`.

### 1.4 Schema claims — confirmed

`GrantDecl` is potential-only — `libs/lang/src/lang/ast.py:639-642`:

```python
@dataclass(frozen=True)
class GrantDecl:
    """Grant constraints for an observer."""
    potential: frozenset[str]  # kinds this observer can emit
```

`_decl.observer-defined` already persists `grant: {potential: [...]}` —
`libs/lang/src/lang/document.py:493-501`. So the synthesis's claim "no new
declaration kind, payload member, or Go oracle change is required" holds for
the potential-only projection. Horizon is correctly left out (it has no
persisted form; adding one WOULD be a payload-shape change requiring
Go-oracle coordination — dossier-digest §4.3 states this precisely).

### 1.5 Empirical wrinkle the synthesis doesn't know: grants are LIVE

The overnight docs treat grant enforcement somewhat abstractly. In fact
production grants exist right now — `~/.config/loops/tasks/tasks.vertex:79-90`:

```kdl
orchestrator {
  key "SYBM..."
  grant {
    potential "task" "route" "slice" "work" "review" "judgement" \
              "escalation" "task.close" "seal" "cite"
  }
}
"orchestrator/claude-opus" { grant { potential "work" } }
"orchestrator/claude-sonnet" { grant { potential "work" } }
"orchestrator/codex-sol" { grant { potential "work" "review" } }
"orchestrator/claude-fable" { grant { potential "work" "judgement" } }
```

with the comment (tasks.vertex:72-76): "Matching is exact for namespaced
names, so wrapper identities carry their own grant and cannot inherit the
orchestrator's breadth." The tasked multi-agent workflow's privilege isolation
depends on path (a)'s exact current matching and precedence behavior. Gate 0's
"existing emit behavior remains pinned" exit criterion is therefore a real,
non-vacuous constraint with a concrete production consumer. (Contrast: the
repo's own `project` vertex and the global `~/.config/loops/.vertex` declare
observers with NO grants, and the project store contains zero `_decl.*` rows —
`sqlite3 .loops/data/project.db "SELECT DISTINCT kind FROM facts WHERE kind
LIKE '_decl%'"` returns empty — so declarations still resolve from files for
this vertex. The store-backed resolver (SPEC §9.5, `identity.py:64-76`) is the
right seam, but the file-fallback path is the one live today.)

---

## 2. Does the resolution dissolve, or add a third path?

**Dissolves — conditionally.** The fork was two schemas (potential-only
`GrantDecl` vs horizon+potential `Grant`) times two enforcement points (one
live, one dead). The resolution keeps one persisted schema (`GrantDecl` riding
`_decl.observer-defined`), one semantics (kind-sets scoped by the vertex whose
constitution is evaluated), and revives the dead gate by feeding it the
projected value. Both call sites derive from one source. That is a dissolution.

Supporting observation the synthesis could state more strongly: **target-local
scoping is not new semantics — it is path (a)'s existing semantics,
formalized.** `check_emit(vertex_path, ...)` already evaluates per-vertex; the
orchestrator grant in the tasks vertex already constrains only tasks-vertex
emits, because other vertices' chains resolve `orchestrator` from the
grant-less global declaration. The proposal is "path (a)'s schema and locality
are correct; path (b)'s enforcement point is correct; project (a) into (b)."
That framing makes the dissolution's correctness nearly self-evident — nothing
about authorization *meaning* changes, only where the check runs.

But three under-specifications would let a naive implementation reintroduce a
fork (or worse). These are the amendments.

### 2.1 The three-state semantics is not expressible in `Grant` (A1)

`ObserverCheck` is three-valued — `identity.py:20-26`: `ok` / `undeclared`
(FORGIVABLE: default emit WARNs and stores, strict refuses — `emit.py:635-649`)
/ `forbidden` (always hard). The engine gate is two-valued and can only see a
projected `Grant`. An undeclared observer projects to no-decl → `grant=None` →
**unrestricted** at the engine gate. So:

- The forgiven-undeclared write survives the projection by accident of
  `None = unrestricted` — fine.
- But strict-mode refusal of undeclared, and the WARN, are *classifier*
  outputs, not grant outputs. The canonical evaluator therefore **cannot be
  the engine gate**; it must be the decl-chain classifier (a `check_emit`
  successor), with the engine gate consuming its projection as defense in
  depth.

The synthesis gestures at this ("app preflight for diagnostics and an engine
gate for defense in depth only if both call the same canonical evaluator") but
never says which one is canonical. If an implementer reads "route production
emit through the engine gate" literally and demotes the classifier, the
undeclared tier's semantics (declare-observer hints, strict mode, WARN
survival under `-q`) silently degrade. Gate 0 must name the classifier as the
canonical evaluator and the engine gate as its enforcement shadow.

### 2.2 Matching and precedence must be golden-pinned (A2)

Two implicit behaviors are load-bearing for the live tasks grants:

- **Matching**: `engine/observer.py:32-48` — `observer_matches` does
  leaf-matching between namespaced and bare names (`kyle/loops-claude` matches
  bare `loops-claude`), exact-only between two namespaced names. So
  `orchestrator/claude-opus` does NOT match the bare `orchestrator`
  declaration (leaf `claude-opus` != `orchestrator`) — that is the entire
  mechanism by which wrappers "cannot inherit the orchestrator's breadth."
- **Precedence**: `identity.py:191-196` — first match over the ordered
  concatenation vertex → project `.loops/.vertex` → global → combine/discover
  sources. When one observer name resolves at multiple chain levels with
  different grants, chain order decides which grant applies. This is
  deterministic but documented nowhere.

If evaluator unification changes either (e.g., suffix-matching wrappers to the
bare parent, or reordering the cascade), `orchestrator/claude-opus` could
inherit `potential={task, route, ..., seal}` — a privilege escalation in a
deployed multi-agent workflow. Gate 0's exit criteria must include golden
tests pinning both behaviors against the live tasks-vertex shapes. Per the
project's ratchet principle, evaluator singleness itself should be a test
(one shared function, or a test that diffs classifier verdict against
projected-gate verdict over an enumerated matrix), not review vigilance.

### 2.3 `Receipt` carries no rejection reason (A3)

`vertex.py:507-514`: a grant rejection and an observer-state-ownership
rejection return byte-identical `Receipt(fact_id=None, tick=None,
stored=False)`. The engine gate cannot say *why*. Two consequences the
synthesis doesn't surface:

- Diagnostics necessarily live in the preflight — which is pressure toward
  exactly the duplicated-membership-test fork the synthesis warns against.
  Either accept this explicitly (preflight = canonical, gate = shadow, ratchet
  test keeps them equal) or add a reason field to `Receipt` in Gate 0. Pick
  one; don't leave it to the implementer.
- Digest's re-authorize-at-head step (§5 pipeline, "re-authorize target head →
  sign → receive") can still race: if the head declaration changes between
  re-auth and `receive`, the gate rejects silently and the CLI must map a
  bare `stored=False` to a user-facing reason it can no longer reconstruct.
  Small window, but the error path should be specified.

---

## 3. The owner-only bypass — steelman and verdict

The synthesis rejects owner-only with: "filesystem/key custody is not a grant"
and "a design dodge, not an honest first Digest slice." The conclusion is
right for the *write contract*; one argument is wrong, and the wrongness
matters because it hides a legitimate option.

**Steelman, stated precisely.** Emit today needs no grant: with no observers
declared, `check_emit` returns ok (open system, `identity.py:216-218`); with
observers declared and no grant, any declared observer emits any kind. A
digest whose target equals its source and whose final bytes are adopted and
signed by the human observer, routed through the ordinary emit path
(`check_emit` + `program.receive`), consults **zero new authorization
surface**. It builds on path (a) — the enforced path — exactly as every
`sl emit` in two years of store history has. It forks nothing, because it adds
no second authority; it is authorization-*neutral*, precisely as sound and as
unsound as emit itself. "Custody is not a grant" proves too much: it indicts
the baseline the project already accepts for every human emit.

**Why the synthesis's conclusion still stands.** Three grounds, and they are
charter/consistency grounds, not soundness grounds:

1. The ratified roadmap fact (dossier-digest §1.1, Kyle 2026-07-01) sequenced
   Digest last *because* it is the "first concrete in-repo Peer/Grant
   consumer" — an owner-only contract evades the confrontation the sequencing
   was designed to force.
2. The motivating mock is an upward cross-vertex write (project →
   loops/roadmap); a self-target slice does not demonstrate the feature.
3. The *unattended* default observer (`digest/<profile>`) is not the human.
   Under current reality it would be an undeclared observer writing under
   WARN-and-store — writable, but exactly the sloppy ambient authority the
   feature exists to replace. The only authorization-neutral variant is the
   human-adopted one; the moment the synthesizer observer signs unattended,
   you need its declaration and grant, and you are in Gate 0 territory anyway.

**Amendment (A4):** reframe §3's rejection accordingly. As written ("local
custody proves ability, not permission") it argues soundness and overreaches;
the honest statement is: a human-adopted, self-target digest through the
ordinary emit path is authorization-neutral and *could* ship before Gate 0
without forking anything — excluding it is a charter/sequencing choice, and
that choice belongs to Kyle, not to this synthesis. The synthesis currently
pre-decides it while simultaneously (and correctly) reserving Gate 0
ratification to Kyle — an inconsistency in its own blocker discipline.

---

## 4. Kyle-level judgments a night session must not ratify

Named explicitly, per the task:

1. **The Gate 0 dissolution itself.** The synthesis says this (Gate 0 exit:
   "Kyle/arbiter ratifies the dissolution"). Correct.
2. **The normative force of an observation.**
   `architecture/parallel-authorization-paths` is kind `observation` — by this
   project's own kind table, "note something true, no prescription." Its "must
   resolve BEFORE Digest builds on either path" is a prescription carried in a
   non-prescriptive kind, authored by an audit agent, never re-emitted as a
   `decision`. The synthesis calls it "the binding architecture fact" — that
   *promotion to binding gate* is itself a judgment. Treating it as binding is
   the conservative direction and I endorse it as the working posture, but
   Gate 0 ratification should include Kyle explicitly adopting (or amending)
   the observation's prescription, ideally by re-emitting it as a decision.
3. **Whether the owner-only human-adopted variant ships before Gate 0**
   (§3 above). Charter call, not soundness call.
4. **Behavior changes to the live tasks-vertex enforcement.** Any observable
   change to matching/precedence semantics under evaluator unification touches
   a deployed multi-agent privilege boundary (tasked has Kyle's in-flight
   work). Even a "compatible" refactor here needs his eyes on the pinned
   golden set.

---

## 5. Minor notes (no amendment required)

- The synthesis's claim that `Grant.horizon` "stays out of scope and
  unenforced rather than being smuggled into Digest" is the right call and is
  consistent with the persisted schema (no horizon member in the
  `observer-defined` payload — adding one is exactly the Go-oracle
  coordination the deferral list excludes).
- The `_digest` envelope riding an ordinary domain kind's payload correctly
  avoids the `ReservedKindError` write-time guard (`vertex.py:523-527`) —
  verified the guard fires only on `_decl.*` (`is_internal_kind`), so no
  collision.
- §2's signing rule ("target's `fact_signer_for(target)`", no cross-custody
  signing) is consistent with the custody lib's string-pinned domain
  separation; I did not audit custody internals — outside this lens.
- Dossier-digest §4.3's three-option framing (extend payload / mint kinds /
  dissolve into enforced path) is faithfully resolved by the synthesis as
  option (c). Confirmed the frozen-vocab table at `document.py:128-151` has no
  `peer-*`/`grant-*` kinds, so options (a)/(b) would indeed be coordinated
  vocab changes.

## Amendments (summary)

- **A1 — name the canonical evaluator.** The decl-chain classifier (three-state
  ok/undeclared/forbidden, strict-mode aware) is canonical; the engine gate
  consumes its projection as enforcement shadow. `Grant` cannot express the
  undeclared-forgiven tier; say so in Gate 0's spec.
- **A2 — golden-pin matching and precedence.** `observer_matches` leaf-matching
  and the vertex→project→global→combine first-match order are load-bearing for
  live tasks-vertex wrapper isolation; pin both with tests shaped like the
  deployed grants, plus a ratchet test for evaluator singleness.
- **A3 — decide the rejection-reason story.** Engine-gate rejections are
  reasonless `Receipt`s; either add a reason in Gate 0 or explicitly designate
  preflight as sole diagnostic authority with a divergence ratchet; specify the
  re-auth/append race's error path.
- **A4 — reframe the owner-only rejection as charter-based.** The
  human-adopted, self-target, ordinary-emit-path variant is
  authorization-neutral; excluding it is Kyle's sequencing call, not a
  soundness necessity. Also: Gate 0 ratification should include promoting the
  parallel-paths *observation* to a *decision* if it is to bind as a gate.
