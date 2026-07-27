# Ratchets — invariants that cannot drift

When a review establishes an invariant ("always X", "never Y"), the invariant
must not live only in review vigilance — vigilance drifts. This doc says how
to make it structural, in what order to try, and what each form costs.

Born from the 0.9.0 review wave (2026-07-26), where four ratchets met a
three-round adversarial review: the two construction ratchets held on first
contact; the two detection ratchets fell seven times between them before
converging. See `decision:practice/construction-vs-detection-ratchets` and
`retrospective:090-review-pipeline-high-tier` in the project store.

## The two species

**Construction ratchets** change the substrate so the defect is
*inexpressible*. No test exists because no code position can state the bad
thing.

- `dataclasses.replace(section, items=...)` instead of a field-by-field
  rebuild — a field added to `FoldSection` later can never be dropped by
  omission, because there is no enumeration to forget it from.
- The ambiguity refusal lives *inside* `_find_local_vertex` — an ungated
  caller is impossible because no ungated primitive exists to call.
- `allow_ambiguous is True` (literal) — the runtime and any checker share one
  definition of opt-out; there is no second encoding to drift.

Construction is dissolution: the invariant collapses into the substrate and
adds **zero ongoing surface**. This is always the first thing to try.

**Detection ratchets** build a parallel model of the code and scan it for
violations (AST walks, caller enumerations with allowlists). They are
miniature static analyzers, and they inherit static analysis's classic defect
classes — each of which arrived on schedule during the 0.9.0 hardening:

| Round | Defect class | Instance |
|---|---|---|
| 1 | granularity | string-grep matched modules, not call sites — one gated + one ungated call in a module passed |
| 2 | aliasing | call-name matching missed `import x as dg` |
| 3 | scoping | alias map was module-wide last-import-wins — a harmless local `as dg` shadowed the real binding |
| 3 | grammar coverage | hand-listed `body`/`orelse`/`finalbody` missed `Try.handlers` / `Match.cases` — an import inside `except:` escaped |
| 2 | model/runtime drift | ratchet said opt-out = literal `True`; runtime said truthy |

A detection ratchet is review vigilance *encoded* — and the encoding drifts
too. Only construction is a fixed point.

## The ordering rule

1. **Dissolve first.** Can the invariant become construction — a frozen type,
   a `replace()`, a refusal moved into the primitive, an argument the code
   can't receive? Then do that and write **no ratchet test at all** (a plain
   regression test for the original repro is still fine).
2. **Detect only the residue.** In Python the residue is essentially one
   thing: **ambient authority**. Any function can `import` its way to a store
   connection, so capability-passing (hand the renderer only a frozen
   evidence object) seals arguments but not imports. Detection ratchets are
   legitimate exactly at that boundary, and only there.
3. **Price detection honestly.** A detection ratchet verified only against
   the reintroduction its author imagined is a regression test wearing a
   ratchet's name. It needs an adversarial round of its own — someone
   *constructing* evasions (aliases, scope tricks, relocation) before it
   counts as load-bearing.

## Rules for detection ratchets

- **Never hand-enumerate a mirrored structure.** The unifying defect class
  across the whole 0.9.0 review wave — in the ratchets *and* in the behavior
  bugs they guarded — was the hand-maintained list mirroring a structure that
  evolves independently (field lists, name lists, AST-field lists). Every
  omission is a silent pass. Iterate the structure (`ast.iter_fields`,
  `dataclasses.fields`) and over-approximate: extra matches fail loudly,
  missed matches fail silently, so err wide.
- **Allowlists shrink, never grow silently.** The allowlist discipline itself
  never failed under adversarial review — all seven failures were in the
  matchers. Keep opt-outs as explicit, reviewable list entries.
- **Match bindings, not names**, and resolve them with lexical scope. If the
  walk re-implements a piece of Python semantics, assume the first
  implementation is wrong and get it adversarially checked.
- **Reuse the machinery.** The call-path walk, lexical alias resolution, and
  call-site enumeration in `tests/test_architecture.py` are the shared
  substrate. A new detection ratchet is a new *rule* on the existing walk,
  not a new bespoke matcher.

## Budget

Detection ratchets are counted. There are **four** (Rule 9:
`resolve_local_vertex` caller enumeration; Rule 10: disclosure renderers
perform no store I/O; Rule 11: record-layer libs never import surfacing-layer
libs; Rule 12: `run_cli` sites bind `renderer=`, never the deprecated
`render=`, and no lens entry point takes a `piped` argument), all at a genuine
ambient-authority boundary. If the count grows faster than the number of such
boundaries, the rule is over-firing and we are building a shadow linter —
stop and dissolve instead.

The budget counts *rules*, not *matchers*, and the 0.10.0 round is why that
distinction has to be enforced downward too: Rule 3's input (`APPS`) and Rule
12's walk were both found evadable in the same review. Every derived
enumeration owes an anti-vacuity assertion, and Rule 3 now carries one
(`assert APPS`) for the same reason Rule 12 always did.

Rule 11 (added with the surfacing-layer charter) is the cheap case the budget
is meant to allow: it is a new *rule* on the import boundary Rule 4 already
walks, not a new matcher. Its hand-maintained input — the lib→layer mapping —
is made safe by a completeness test over the filesystem-derived lib list, so
an unassigned lib fails loudly instead of being exempt by omission. That
completeness test is also what forced `LIBS` itself to stop being a
hand-written tuple mirroring `libs/`.

Rule 12 (0.10.0 S1) is the ordering rule working as intended. The invariant —
piped output implies `width=None` — was *dissolved*, not detected: deleting
the `piped=` kwarg from every lens entry point left the register derivable
only from the offered width, so a render claiming the pipe while holding a
concrete width became inexpressible rather than merely untaken. Two test
cases that asserted the old forcing behaviour were deleted with it: nothing
left to assert. What the rule detects is the *residue* — a `piped` parameter
growing back, or a `run_cli` site dropping to the deprecated `render=`
contract that would let a callback fabricate a width by hand. Both ride one
walk over filesystem-derived source roots, and both carry anti-vacuity
assertions: a walk that finds no `run_cli` sites, no `lenses/` packages, or
no resolvable `renderer=` bindings fails loudly rather than passing green on
an empty enumeration. That guard is the one the 0.9.0 defect table did not
have a column for, and it is cheap.

**Rule 12's own adversarial round (sol HIGH, 0.10.0 r1).** The anti-vacuity
guard held; the *matcher* did not. All three classic classes returned, in a
walk written with the 0.9.0 table in hand:

| Defect class | Instance | Fix |
|---|---|---|
| aliasing | `runner = run_cli; runner(…, render=…)` — imports were followed, plain assignment was not | assignment aliases propagate to a fixed point, no reassignment invalidation |
| scoping | one def per spelling module-wide; apps/tasks' six sibling nested `renderer` closures all collapsed onto whichever overwrote the map | real lexical scope chain, nearest enclosing scope, all candidates in it |
| granularity | a `renderer=` name imported from another repo module was `continue`d | imports (absolute + relative + one re-export hop) resolve across source roots; unresolved repo-local bindings **fail closed** |

Two lessons the table generalises. First: **the walk's declared "known
boundary" is where the next evasion lives.** Rule 12's preamble named
variable-threaded runners and cross-module bindings as accepted limits, and
those are precisely the two sol constructed — a documented limitation is an
advertised hole, not a defence. Second: **skipping is a silent pass, so
"cannot resolve" must be loud.** `if target is None: continue` reads as
caution and behaves as an exemption; fail-closed with a shrink-only allowlist
puts the same judgment on the record where it can be reviewed.

Their regression suite is deliberately *synthetic* (`tests/test_architecture.py`,
the Rule 12 evasion block): each case reconstructs the evading source rather
than asserting against the repository as it currently looks, which is the only
form that stays a ratchet after the repository changes.

## Cost accounting (why the lumpiness is fine)

Vigilance-only invariants cost a review round per recurrence, forever,
invisibly (fetch-then-disclose recurred three times before its ratchet).
Ratchets cost once, visibly. The 0.9.0 release paid the one-time analyzer
tax (walk + alias machinery + adversarial hardening); subsequent ratchets
ride it at low marginal cost. Lumpy-and-visible beats
distributed-and-hidden.
