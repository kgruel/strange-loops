# peers — Handoff

## 2026-01-27
Replaced `Scope(see, do, ask)` with `horizon` + `potential` directly on Peer.
`ask` collapsed into `potential` — asking IS doing (emitting a request fact
is an action). `grant`/`restrict` now operate on `Peer` instead of `Scope`.
Monotonic invariant preserved. 11 tests reorganized.

## 2026-01-26
Peer atom: `Peer(name, scope)` with `Scope(see, do, ask)` as frozen
dataclasses. Three pure functions: `grant` (union), `restrict`
(intersection), `delegate` (restrict + new Peer). Delegation cannot
escalate — monotonic narrowing. 12 tests.

Dev deps moved from `[project.optional-dependencies]` to
`[dependency-groups]` (modern uv convention).

## Open
- **Horizon/potential semantics**: Strings in horizon/potential are uninterpreted. Need real usage to drive filtering of Facts, Shapes, Lenses.
- **Capability-as-Fact**: Demonstrated in `experiments/capability.py`. Capabilities as immutable facts, folded via Shape into current potential. Direction for dynamic permission management.
- **Pipeline bridging**: Topological, not structural — which peer observed the fact encodes participation level.
