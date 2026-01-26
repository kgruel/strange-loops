# THREADS — peers

## Scope semantics
What do see/do/ask concretely mean when cascading through the pipeline?
e.g., `see={"metrics"}` — does that filter which Facts a peer receives?
Which Shapes they can read? Which Lenses render for them? The strings
are uninterpreted right now. Need concrete examples from real usage to
ground them.

## Needs and capabilities
Different from permissions (scope). Needs = what a peer requires to
function. Capabilities = what a peer can offer. Discussed as a
Must/Should/May gradient. Likely frozenset-based composable types
matching the Scope pattern. Defer until patterns emerge from real usage.

## Stance convenience
Participation level (direct/guided/delegated/automated/observing) is
encoded in the delegation hierarchy — root peer = direct, child peers
= delegated/automated. A convenience function `stance(peer) -> str`
could read the hierarchy and label it. Not a type, just a utility.
Low priority.

## Pipeline bridging
Peer observes Facts and receives rendered state, but there's no
structural affordance for this in the atom. The bridging lives in
experiments (pipeline wiring). Question: does Peer need any expression
of "I am an emitter" or "I am a consumer", or is that purely
topological?
