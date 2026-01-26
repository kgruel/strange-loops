# THREADS — facts

## [resolved] Vocabulary rename: Event → Fact
Event renamed to Fact. Clean break — Event, Result, Emitter, and all CLI
output framework removed. Fact is the observation atom: kind + ts + payload.

## Kind conventions
Open thread: review kind conventions as usage patterns emerge. Kind is an
open string by design — no enum, no constrained set. As the pipeline gets
real usage, patterns will surface (e.g., common prefixes, naming conventions).
Defer codifying until patterns are grounded.
