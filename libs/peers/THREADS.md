# THREADS — peers

## Horizon/potential semantics
What do horizon/potential concretely mean when cascading through the pipeline?
e.g., `horizon={"metrics"}` — does that filter which Facts a peer receives?
Which Shapes they can read? Which Lenses render for them? The strings
are uninterpreted right now. Need concrete examples from real usage to
ground them.

Previously "scope semantics" with see/do/ask. Vocabulary corrected to
horizon + potential. Strings still uninterpreted — same open question,
clearer vocabulary.

## Needs and capabilities
Different from permissions (horizon/potential). Needs = what a peer requires to
function. Capabilities = what a peer can offer. Discussed as a
Must/Should/May gradient. The capability-as-fact pattern
(`experiments/capability.py`) demonstrates the direction: capabilities are
facts, folded via Shape into derived potential. Revocation is a fact too.
Authorization becomes event-sourced.

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
