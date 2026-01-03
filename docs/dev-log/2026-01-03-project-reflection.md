# Project Reflection: ev at v0.3.0

A step back to assess where ev is, how it got here, and where it might go.

## What ev Is Trying to Be

The core insight: **events are facts, not instructions**.

CLIs today conflate "what happened" with "how to show it." Domain code imports Rich directly, JSON output is bolted on late, every command reinvents verbosity handling, testing requires mocking print statements.

ev says: describe what happened semantically, let renderers decide presentation. The ViewModel pattern, applied to CLIs.

## The Evolution Pattern

The project has followed a healthy development loop:

```
Initial design (minimal types)
     ↓
Real usage (hlab integration)
     ↓
Friction captured (retrospectives)
     ↓
Thoughtful responses (factories, patterns, ev-toolkit)
     ↓
Principles maintained (core stays frozen)
```

Key changes driven by real friction, not speculation:

| Friction | Response |
|----------|----------|
| String matching error-prone (`status == "ok"`) | `Result.is_ok`, `Result.is_error` properties |
| Artifact type was convention, not enforced | `Event.artifact(type, ...)` requires type |
| Timestamps easy to forget | Auto-populated `ts` on all events |
| Result invariants unenforced | ok→code=0, error→code≠0 in factories |
| Reference emitters not directly usable | Pattern documentation, domain emitter guidance |
| Convenience utilities would bloat core | Separate ev-toolkit package |

## What's Working

**The primitive set is complete without being bloated.** Five event kinds cover the semantic space:

- `log` — narrative context
- `progress` — work advancement
- `artifact` — durable outputs
- `metric` — quantitative facts
- `input` — recorded decisions

Plus `Result` for the authoritative outcome. Can't think of a CLI scenario that doesn't fit.

**Factory/raw split is elegant.** Factories encode best practices (timestamps, type requirements, invariants). Raw constructors remain available for edge cases. "Blessed path with escape hatch."

**Immutability is the right default.** Frozen dataclasses, MappingProxyType—events are values, not mutable state. Safe to share, replay, test against.

**ev-toolkit separation is wise.** Core contract stays frozen and minimal. Convenience utilities evolve faster in a separate package. itertools-style "import or copy-paste" reduces dependency anxiety.

**Documentation explains *why*, not just *what*.** The docs don't just describe—they explain rationale. That's what changes how people think.

## Interesting Tensions

**Minimal protocol vs complex emitters.** `emit(event)` + `finish(result)` is simple. Real emitters need batch vs streaming patterns, state management, aggregation, live display. The patterns documentation bridges this, but there's inherent complexity where domain knowledge lives.

**Type flexibility vs safety.** `event.data` is `dict[str, Any]`—flexible but untyped. The `data.type` convention helps, but consumers need to know shapes. Documentation becomes the contract. Probably the right tradeoff; strict schemas would ossify too fast.

**Domain-specific shapes are unavoidable.** ev provides generic primitives, but every project needs its own event shapes. The library can't prescribe these. Each adopter reinvents some wheel—but the value is in shared *structure*, not shared *vocabulary*.

## Usefulness Assessment

**High value for:**
- Homelab/infra CLI authors (Rich for humans, JSON for automation)
- Teams with multiple CLI tools (shared semantics, renderers, testing)
- Anyone who's felt: "I need JSON but also pretty output," "Testing this CLI is painful"

**Adoption challenges:**
- Paradigm shift (emit events, not print)
- Emitter authoring curve (patterns to learn)
- No ecosystem yet (early adopters build everything)
- Python 3.13+ requirement

**What would accelerate adoption:**
- More polished reference emitters (production Rich with live display)
- Integration guides (Typer, Click, Cappa)
- More real-world examples beyond hlab
- ev-toolkit maturation

## Honest Take

ev solves a real problem most CLI authors don't realize they have—until they've felt the pain. The risk is it's "too thoughtful"—requiring upfront investment over just `print()`. The value proposition needs to be visceral: pay the cost of structured events now, get testability and flexibility for free.

The Black-style opinionation is a feature. Few options, strong opinions, stability over flexibility. That forces coherence.

The project is at a good inflection point:
- Core contract stabilizing
- Convenience layer emerging
- Real usage informing design

The feedback loop—use, reflect, refine—is exactly how good libraries evolve.

## Version History

- **v0.1.0** — Initial release (core types, reference emitters)
- **v0.2.0** — Factory methods, Result invariants, is_ok/is_error, is_kind()
- **v0.3.0** — Artifact type required, auto-populated timestamps
