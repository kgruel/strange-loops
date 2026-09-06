# C6 boundary continuity — September 6, 2026

Status: implemented, validated, and accepted after Fable-low implementation review.
Baseline `ef8b21b2` on `arrival/finish`, the accepted C3 checkpoint.
Sol owns engine production and integration tests, Terra SDK integration and
real-store acceptance, Luna the independent history matrix/audit/validation,
and root design decisions, integration review and retained review triage.

## Behavior

Ordinary in-place edits inherit a boundary's recorded consumption history.
Changing folds, routes, parse, trigger/count/mode, presentation, or disabling a
boundary while retaining its loop does not silently start a new incarnation.
Facts are re-folded under the current declaration; old tick payloads remain
unchanged evidence and are not deserialized into current fold state.

The supported Arrival runtime and declaration preparation/semantic preview now
analyze complete bounded self-declaration history before consuming old ticks or
preparing a successor. A ticked loop name retired and then recreated refuses.
A tick with no provable historical loop role is reported as unproven, rather
than described as a proven prior incarnation. Relevant vertex-identity gaps
also fail the `(vertex, role, name)` continuity check.

A historical loop/vertex name collision refuses only when the target consumes
its ambiguous vertex-period stream. A corrected target without that vertex
boundary can run; proposing the consumer again rechecks the same old evidence
and refuses. Retired streams absent from the target remain evidence. Foreign
and originless ticks do not become local consumption edges. Pre-genesis ticks
cannot obtain a role from an early overlay before the own declaration genesis.

Explicit `cite` removal still leaves the implicit runtime `cite` loop, so that
name remains continuous. Declaration rows in one wire batch form one atomic
namespace revision; transient intermediate documents do not invent retirement.
An adapter claiming an owned tick and self-declaration fact at one ordinal
contradicts the fact-only batch profile and receives a typed refusal.

## Shared implementation

`arrival_boundary_continuity.py` owns the shared receipt-history reconstruction,
parameter evidence collector, immutable issue/result values and pure analyzer.
It scopes overlays to the own lineage before considering source paths, includes
intermediate retired source pins, and evaluates every relevant tick rather than
only the newest pending edge. A namespace is present, absent, or unknown:
direct/implicit declarations and literal generated names prove presence even
alongside an unresolved generator.

Historical parameter files can supply evidence when available bytes match their
recorded pin. The collector hashes and parses one byte read through the same
parser used by normal compilation; default text decoding and newline behavior
are preserved. Unverified or unavailable bytes remain unknown. Environment
values are not substituted into historical evidence; whole-value `$NAME` and
the `$$` escape follow the compiler's existing rules. A current compiled
namespace must contain every provable name and have no unexplained extra name.

Runtime construction already verifies current source/parameter pins before
compiling; C6 does not duplicate that gate. It keeps two explicit tick selections:
the full finite timestamp range for continuity and the existing nonnegative
selection for hydration/pending planning. Both come from the same CURRENT
snapshot. The candidate builder now passes its captured fact/runtime-tick tuples
onward rather than querying them again for the capture object.

Runtime conflicts raise `BoundaryContinuityRefused` with actual basis, full H,
effective declaration and issue coordinates. The local planning attempt exposes
the existing C2 prepare/custody-not-entered proof. Declaration preparation and
semantic preview retain `DeclarationPreparationRefused`, actual H and an explicit
`BoundaryContinuityConflict` cause. The existing SDK serializer retains scalar
tick/declaration evidence without a new error schema or invented Commit.
Diagnostic attribution retains declaration kind and subject together; a loop
retirement cannot cite an unrelated observer with the same subject. Where no
single causal declaration row is established, the issue retains the revision
ordinal and leaves the fact ID absent.
An earlier registry open may have affected witness state; this proof concerns
custody append in the planning attempt, not every possible external effect.

Evidence reads, state reinterpretation, inspection, verification, export,
declaration CAS/recovery, and legacy attached replay keep their existing roles.
The new execution check is not an independent audit of every adapter row and
does not authenticate an origin label. Credential D0/D2, explicit restart/carry
and semantic aliases remain separate work. A fresh loop name gives future ticks
a distinct identity but does not exclude older facts from replay.

## Count semantics preserved

- With a retained tick, `every M` replays K later routed facts and keeps count K.
  If K already meets M, the next routed ingress fires; hydration does not fire
  or dispatch retrospectively.
- Without a tick, the existing repeating recovery uses K modulo M.
- `after M` with an old tick remains exhausted. Without one, K >= M older routed
  facts also exhaust it, including under a newly chosen name.
- Changing from `after` to `every` resumes repeating interpretation from the
  retained boundary and subsequent facts, not from the edit's receipt.

The [accepted design](consistency-c6-boundary-design-2026-09-06.md) contains the
full contract matrix and consciously deferred transition behavior.

## Evidence and review

Two Fable 5.1 high-effort design reviews preceded implementation. The first led
to consumer-scoped ambiguity, precise count semantics, typed refusal evidence
and verified historical parameter rows. Root rejected the second review's sole
new blocker after source, focused tests and an exact drift probe demonstrated
the existing pin gate. Both raw verdicts remain REVISE; design acceptance is
root's source-backed triage, not a claimed Fable ACCEPT. See the
[design review triage](reviews/consistency-c6-design-2026-09-06/primary-triage.md).

Retained disposable baseline probes demonstrate old acceptance of a ticked
retirement/recreation and an ambiguous vertex-period consumer. The corrected
no-consumer configuration and inherited `after` exhaustion remain desired
positives. These are explicitly labeled source-backed fake-query probes;
new engine/SDK integration tests exercise real isolated Arrival stores.

Focused SDK acceptance covers refusal without append, preserved reads/export,
in-place count/fold and boundary-disable edits, consumer-scoped collision repair,
and a ticked file-parameter-generated loop across preview, signed edit and later
emission. The engine matrix covers intermediate/atomic history, unknown
generated intervals, implicit `cite`, foreign evidence, exact role diagnostics,
pre-genesis and negative timestamps, and both compiled-name mismatch directions.

Final full suites after the diagnostic correction passed: engine **2,597 passed,
1 skipped**; SDK **545 passed**; architecture **101 passed**. The focused engine
continuity/runtime/declaration group passed **93 tests**, and focused SDK
acceptance passed **105 tests**. See the
[validation report](consistency-c6-validation-2026-09-06.md) for exact commands,
source hashes, and retained logs. Scoped Ruff is clean; the broader compiler
check reproduces 57 existing baseline findings, with no unrelated cleanup.

Fable-low returned **ACCEPT**, no blockers. All six optional notes are triaged
in the [implementation review](reviews/consistency-c6-implementation-2026-09-06/primary-triage.md).
A post-review real-store inline-parameter case closes its main coverage question;
final SDK is **546 passed**, with production byte-identical to review. The new
test was validated natively after the external review. Nameless malformed
historical vertex documents remain refused; canonical documents already carry
the required name. Snapshot-resolver pre-genesis overlay handling and possible
imported vertex singleton validation are separately recorded hardening work.

Changes are checkpointed with this report on `arrival/finish`; nothing pushed
or applied to live stores or keys. History analysis
reconstructs captured declarations and checks namespace revisions for each
relevant tick; this slice makes no incremental-query performance claim.
