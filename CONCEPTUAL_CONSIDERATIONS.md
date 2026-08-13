# Loops: conceptual considerations

Status: reflective and non-normative  
Purpose: preserve design questions, architectural observations, safeguards, and documentation notes that arose while developing the [conceptual model](./CONCEPTUAL_MODEL.md).

This document is intentionally separate from the conceptual model. The model describes Loops affirmatively; this document records places where the model creates obligations, tensions, risks, or opportunities for later work.

The README observations refer to the intended README at commit `f3f0031bbdeee2dcef48099a278f55646e6d0404`.

## The loop's central risk: recursive authority

The README's attention framing reveals the system's principal conceptual risk.

If conclusions re-enter as observations, a system can begin accumulating evidence produced by its own prior interpretations. A summary may be folded into a higher summary, returned through an observer, and emitted again. Without visible derivation, repetition can look like independent corroboration. Attention can become self-reinforcing: what was surfaced once becomes more likely to be surfaced again, while material omitted by the fold or lens becomes progressively less visible.

This is not a reason to break the loop. It is a reason to preserve its lineage.

Interfaces and future protocols should make it possible to distinguish:

- a primary observation from a derived conclusion;
- several independent observers from one conclusion copied through several levels;
- new evidence from a restatement of already-folded evidence;
- a fact omitted because it was irrelevant from one hidden by a bounded fold, lifecycle projection, or lens;
- a causal feedback cycle from a legitimate recursive hierarchy.

`origin`, contributing-fact windows, entity/fact identity, tick envelopes, and declaration generation provide pieces of that answer. Over time the model may need a more explicit derivation path or depth so clients can detect double counting and circular support without inferring it from strings.

The raw-fact escape hatch is therefore not only a debugging convenience. It is an epistemic safeguard. Any attention surface should make it possible to descend from the conclusion to what produced it and to see what the chosen compression left out.

The healthiest version of the loop is not one that continually confirms itself. It is one that can focus attention while remaining interruptible by new, dissenting, or previously unfolded observations.

## Architectural tension

The concepts are coherent, but a correct client currently has to compose more of them than it should.

A writer may need to understand:

- canonical versus derived residence;
- declaration authority;
- observer grants;
- operation-fresh custody;
- fact and tick signing;
- boundaries;
- stale declaration heads;
- committed-error semantics;
- JSONL recovery rules.

Those concepts belong in the substrate, but they should be concentrated behind a few high-level operations. Otherwise every application becomes a partial protocol implementation.

The model should not be simplified by erasing distinctions. Access to the model should be simplified:

```text
resolve target
read answer with provenance
emit observation
plan declaration change
apply declaration change
review publication
```

Each operation should return a rich typed result. Applications and CLIs should mostly coordinate and render those results.

The second tension is vocabulary. Fact, kind, spec, fold, loop, vertex, boundary, tick, observer, origin, address, witness, lineage, declaration, residence, and custody are defensible terms, but no user should need all of them on the first day.

A progressive interface can begin with:

```text
read → emit → declare
```

It can reveal state, boundaries, provenance, and history as the user's questions become deeper.

## Did the code outrun the ambition?

The code has certainly outrun the project's public explanation. It may also have outrun the initially imagined product surface. But much of its complexity does not feel random.

The original premise contains demanding consequences:

- If conclusions re-enter as observations, identity and origin matter.
- If observations can arrive late, event time and receipt order must diverge.
- If interpretation can evolve, declaration history must be addressable.
- If stores combine, lineage and member-local time matter.
- If conclusions are meant to be trusted, signatures and sealing claims must be precise.
- If the canonical artifact becomes a log with a derived index, authority and recovery must be explicit.

The code appears to have explored these consequences faster than the project's story has been consolidated.

Some of the resulting complexity should be compressed behind better library seams. Some incomplete transitions, particularly JSONL declaration and maintenance ceremonies, need finishing. But the central distinctions are not obviously excess. They are the cost of trying to make a recursive attention system honest about its own evidence and interpretation.

## What should be protected

As the project evolves, preserve these invariants:

- Raw facts remain accessible beneath every interpretation.
- A fact, folded entity, and tick remain distinct concepts.
- Event time never substitutes for receipt order.
- Declaration changes remain historized after adoption.
- Derived indexes never masquerade as canonical artifacts.
- “Unchecked” never renders as “verified.”
- Signatures attest claims, not external truth.
- Domain vocabulary stays in declarations and payloads, not the substrate.
- Aggregates never pretend to possess one witness history.
- New presentation features always lead back to contributing facts.
- Attention remains connected to explanation rather than becoming opaque ranking.

Avoid reducing Loops to a conventional schema registry, graph database, task manager, monitoring system, or writing tool. It can support all those domains precisely because it is not reducible to any one of them.

## What should be simplified

- Consolidate protocol-sensitive workflows into high-level library operations.
- Give every answer a consistent provenance envelope.
- Make declaration authority visible at every mutation boundary.
- Establish one result codec shared by CLI, TUI, and future clients.
- Keep source execution separate from observation emission.
- Use one domain-neutral default renderer, with lenses as optional presentation.
- Teach vocabulary progressively through the interface.
- Make recovery states actionable rather than merely diagnosable.

The project does not primarily need fewer ideas. It needs clearer altitude boundaries between substrate, orchestration, and presentation.

## Reading the intended README

The intended README is not merely a better introduction. It is a coherent statement of the project's philosophy, and it independently reaches much of the conceptual center described in the model.

Its strongest move is the opening inversion:

```text
ordinary database: preserve conclusion, discard evidence
Loops:             preserve evidence, derive conclusion
```

That is clearer and more concrete than beginning with event sourcing, folds, or append-only storage. It names an everyday failure: a mutable row says “the world is X” after the individual observations and observers which produced it have disappeared. Loops keeps the smaller claims and makes the larger claim reproducible.

The README also contributes several important formulations.

### A Spec is a contract for attention

Calling a Spec “the contract for attention, not a schema for storage” is excellent. It connects a technical declaration to the system's purpose. A Spec selects what matters, how it accumulates, and when the accumulation should resolve. That is exactly the right altitude.

### Fidelity belongs to the observer

The README's human-and-agent comparison gives lenses a reason to exist beyond formatting. One observer needs glance width; another can consume full fidelity. Sharing the record while varying the view avoids both forcing humans through a firehose and starving machines with a summary designed for a terminal.

This suggests that a lens is not simply a theme. It is a declared allocation of attention and fidelity for a particular observer or task.

### Applications are stores plus skins

“An application is a store plus a skin” is a consequential product insight.

A skin can supply:

- a write vocabulary;
- declaration defaults;
- authoring affordances;
- lens configuration;
- domain-specific labels and navigation;
- safe shortcuts which lower to generic substrate operations.

The underlying fact, declaration, fold, tick, address, and provenance models do not change. This is how Loops can support monitoring, project memory, task orchestration, and fiction production without turning the core into a union of their schemas.

It also gives CLI v2 a clean architectural direction: build an honest generic substrate client, then let skins improve domain use without forking persistence semantics.

### Scale is residence and topology

The README refuses to equate scale with enlarging one canonical database. Facts move; stores compose; larger systems emerge as topology. That fits the member-local witness model more deeply than a conventional “supports federation” claim would.

The human-scale boundary is valuable discipline. It says the project need not optimize one store toward an imaginary global present. A store can remain a tractable experienced history, and scale can come from additional stores, observers, and explicit composition.

### The system refuses consensus

“Contradiction is data” is one of the best lines in the document. Two observers can report incompatible observations without forcing the write path to select a winner.

The system still has local authorities: an observer authors a fact, a store has its own lineage, and a declaration governs a projection. Those are scoped claims, not global consensus. The distinction matters. Refusing universal agreement does not mean refusing identity, custody, or local interpretive authority.

### Its intellectual lineage follows the implementation

The Weaver, Uexküll, and Hofstadter correspondences give useful frames without claiming the code was deduced from them. “Confirmations, not blueprints” is an unusually healthy posture.

The Weaver correspondence is especially strong:

- the record layer remains technically verifiable because it does not need to settle meaning;
- declarations and folds occupy the semantic layer;
- attention, lenses, and observer action occupy the effectiveness layer.

Uexküll's umwelt supplies a better model than “partial copy of the world”: a store is a situated experienced reality. Hofstadter names the recursion among levels and observers. Recording those intellectual discoveries back into the described store is genuine dogfooding of the semantic loop.

## Precision notes for the README

The README is conceptually compelling. A handful of statements could eventually be qualified so its public claims match the libraries' finer distinctions.

### Receipt order is not a field on a Fact

“Facts are observations ... in the order they were received” combines two layers. A Fact carries event time. A particular store supplies receipt/witness order. The same signed fact may occupy a different receipt position in another store after transport or merge.

A precise formulation would be: facts carry when they claim the observation occurred; stores witness the order in which they received facts.

### Meaning binds at read, but the record is not meaningless

Domain interpretation binds at read: folds, relationships, lifecycle, search, previews, and lenses can change retroactively. Some meaning is nevertheless fixed at observation time: kind, timestamp, observer, origin, payload, and signature are commitments. Admission policy and reserved namespaces can also constrain writes.

The later “not schema-free” section acknowledges this well. The earlier absolute wording could distinguish stable record semantics from re-bindable domain projection.

### Current state is derived; published state can be stored

“State is always derived, never stored” is true for current fold state. A tick deliberately stores a snapshot of folded state at a boundary. This is not a contradiction if the distinction is explicit:

- live/current state is reconstructed;
- a published historical conclusion is preserved as a tick.

That distinction is part of what makes ticks valuable.

### A tick is fact-shaped, not literally the same stored row type

Conceptually a tick is free to re-enter another loop as a fact. In the libraries, `Tick` and `Fact` remain distinct types and occupy separate storage axes; an explicit bridge converts the tick into a fact. The prose is right at the compositional level, but API documentation should retain the type-level distinction.

### Signing and sealing are era- and window-scoped

The libraries permit honest unsigned eras and observers without local signing material. A tick chain commits sealed windows; facts on the live edge are not yet covered by the next tick. Verification is also an operation that must actually be performed.

Consequently, “facts are signed” and “the record was not rewritten” are best stated as available, scoped guarantees rather than universal properties of every row at every moment.

### A store can contain several observers

“One store is one observer's experienced reality” is evocative but stricter than the data model. One store can contain contradictory facts from several observers and can declare several observer identities.

The umwelt may belong to the observer for whom the store is assembled or read, rather than to the author of every fact within it. “One store is one situated stance” may be the more general formulation.

### The three-shape vocabulary deserves one settled account

The README names Fact, Spec, and Fold as the three shapes, then introduces Tick as the resolved output. Elsewhere in the library documentation, Fact, Spec, and Tick are called primitives while folds are rules within a Spec.

Both taxonomies are intelligible, but a public conceptual vocabulary should choose one distinction, perhaps:

```text
three declarative/runtime shapes: Fact, Spec, Tick
one transition:                 Fold(state, fact) → state
one execution pattern:          Vertex
```

or explicitly explain why Fold, rather than Tick, is counted among the three. The important thing is not the number; it is avoiding two authoritative primitive lists.

These notes do not weaken the README's thesis. They are places where the code has already earned more precise language than an introductory manifesto normally carries.
