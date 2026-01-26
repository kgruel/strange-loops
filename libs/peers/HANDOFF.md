# peers — Handoff

## 2026-01-26
Peer atom: `Peer(name, scope)` with `Scope(see, do, ask)` as frozen
dataclasses. Three pure functions: `grant` (union), `restrict`
(intersection), `delegate` (restrict + new Peer). Delegation cannot
escalate — monotonic narrowing. 11 tests.

## Open
- **Scope semantics**: Strings in see/do/ask are uninterpreted. Need real usage to drive filtering of Facts, Shapes, Lenses.
- **Needs/capabilities**: Defer until patterns emerge.
- **Pipeline bridging**: Topological, not structural — which peer observed the fact encodes participation level.
