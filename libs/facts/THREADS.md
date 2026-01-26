# THREADS — facts

## Vocabulary rename: Event vs Fact
Prior session (Jan 25) planned Event -> Fact, Result -> Verdict as part
of the ecosystem vocabulary grounding. Code in prism still uses
Event/Result. The pipeline reads naturally with "Event" and the name has
earned its place. Decision needed: commit to the rename or keep Event?

If renaming:
- Event -> Fact
- Result -> Verdict
- EventKind -> FactKind
- EventLevel -> FactLevel
- ResultStatus -> VerdictStatus
- Emitter stays (still emits)

## API refinement
The original ecosystem discussion noted facts needs vocabulary and API
work to refine. Specifics not yet scoped. The factory methods
(Event.log, Event.progress, Event.artifact, Event.metric, Event.input,
Event.log_signal) work but may need review against the grounded
vocabulary.

## Emitter protocol
Emitter.emit() + Emitter.finish() with "finish exactly once" invariant.
Solid design from the ev days. May need review for how it integrates
with the Stream[Event] pattern in ticks — currently Emitter is
synchronous, Stream is async.
