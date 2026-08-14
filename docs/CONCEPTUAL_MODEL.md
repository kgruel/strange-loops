# Loops: a conceptual model

## The shortest account

Loops focuses attention by preserving the passage from observation to
interpretation to publication — and back again.

It does not store truth. It stores observations, interpretations, and
attestations, and works not to confuse them.

A fact is an observation from an observer. A fold is a declared way of
interpreting observations as state. A tick publishes that state at a
boundary. Declaration history records how interpretation itself changed.
Witness order records what a particular store had received. Signatures and
chains attest to specific claims without pretending those claims are
reality.

```text
world
  ↓ observed by someone
Fact
  ↓ interpreted through a declaration
folded state
  ↓ published at a boundary
Tick
  ↓ bridged, may re-enter another level as a
Fact
```

The essential final step is outside the mechanism:

```text
publication → observer → attention, judgment, action → new observation
```

The loop does not close because the engine can turn a tick back into a
fact. It closes through an observer.

## Attention is the purpose

"A system for focusing attention" is the design constraint the storage
answers to, not a tagline over it.

- Sources sense possible observations.
- Facts preserve what was observed.
- Folds compress many observations into intelligible state.
- Boundaries judge that an accumulation is worth surfacing.
- Ticks publish the resolved state of an interval.
- Lenses shape publication for a particular observer.
- Observers judge, act, and observe again.

So a fold is not a materialized view; it is an attention reducer. A
boundary is not a timer; it encodes a judgment that a moment has arrived.
A tick is not an event; it is a candidate object of attention. The
provenance obsession has a plain purpose: focused attention must never
require surrendering the ability to ask why this, why now.

## Three loops

**Temporal.** Observations accumulate into state; boundaries seal state
into ticks; a bridged tick is a fact at another level.

```text
facts → fold → tick → fact → higher fold → higher tick
```

The model closes across scales without changing shape: a service check
becomes a health tick becomes a platform fact; a writing session becomes a
checkpoint becomes project history. The loop is strange not because there
is feedback but because the substrate cannot refuse its own outputs as
inputs of equal kind — a tick re-enters as a fact, and references are the
only discriminator between a raw observation and a fold of folds. Levels
are not tiers; they are traces of prior resolutions.

**Semantic.** The rules for interpreting facts are themselves historized
facts. The store holds observations about the domain and observations
defining how the domain is interpreted. Genuine self-reference, kept from
becoming arbitrary self-modification by genesis, lineage, reserved kinds,
signatures, and edit ceremonies.

**Observer.** Outputs return to a human or agent whose changed attention
changes what gets noticed, decided, emitted next. Without this loop the
system is a recursive event processor. With it, Loops is an instrument for
directing attention over time — which is also where its one real danger
lives (below).

## State is an answer

Facts are durable. State is reconstructed. Reconstruction is governed by a
declaration, and the declaration has history. State is an answer to a
question:

> What do these facts mean, under this ontology, at this temporal
> position?

One precision: live state is always derived; a published conclusion is
deliberately preserved as a tick. Both halves matter — reconstruction
keeps the present honest, preservation makes past conclusions citable.

The productive tension at the center:

```text
facts are open
interpretation is governed
```

An undeclared fact is not invalid; it is evidence whose interpretation has
not yet been chosen. A later declaration illuminates earlier material
without rewriting it. That makes the natural order of exploratory work
legal: observe, inspect what accumulated, declare meaning, replay.

## The ontology has history too

Most event-sourced systems keep old events but replay them through today's
code — silently reinterpreting history under rules that did not exist when
it happened. Loops preserves the evidence and the history of the machinery
that interpreted it, which holds four questions apart:

- What do historical facts mean under today's declaration?
- What would they have meant under the declaration of their day?
- What had this store actually received at a given witness position?
- What state was explicitly published?

The file-to-store authority transition follows. Before genesis, the
`.vertex` file is the available authority; after genesis, the store
carries the historized declaration and the file becomes ingress and cache.
Letting an unrecorded file edit override the store would destroy the claim
that past interpretation is reviewable. The transition is sound and
operationally surprising; interfaces must disclose it.

## Time has more than one honest meaning

There is no single universal time in the model, on purpose:

- when an observer says something happened;
- when a store received the saying;
- when an interpretation changed;
- when accumulated state was sealed;
- for aggregates, several independent receipt histories.

Event-time projection and witness-position reconstruction answer different
questions:

> What do we now believe happened before Tuesday?
> What had we actually been told by Tuesday?

A backdated fact must affect the first and must not appear in the second.
An aggregate has no honest single witness order — each member store has
its own receipt history — so witness-time aggregation takes a vector of
member positions, never a fabricated global cursor. Refusing an invalid
scalar is better architecture than manufacturing a convenient lie.

## Ticks are publications

A stored tick says: this window ended; this was the folded state; these
facts contributed through this cursor; this snapshot followed the
preceding chain state; this signer may have attested it.

That generalizes past monitoring: this was the approved project state;
this writing session closed here; this research batch was reviewed; this
release contained these decisions.

Two distinctions keep it honest. A produced tick and its stored
attestation envelope are separate concepts — collapsing them would imply
every in-memory tick is witnessed. And "conclusion" is the right word for
a tick only in its situated sense: state resolved under a particular
declaration at a particular boundary, never timeless truth.

## Relationships remain interpretations

Loops stores payload values and lifts declared fields into typed edges at
read. The graph is an interpretation of facts, not a second authoritative
representation needing synchronization. Declaring an edge today lights up
relationships already present in old payloads.

```text
stored evidence remains stable
declared interpretation can evolve
```

The substrate never learns the universal meaning of `depends-on` or
`supersedes`; predicates belong to declarations. The honesty cost is
provenance: an edge can exist now because of a declaration made after the
payload was stored, so the declaration generation behind a graph answer
must stay discoverable.

## An epistemic data system

"Event" implies something objectively occurred. "Observation" leaves room
for perspective, disagreement, incompleteness, and correction. Loops
carries the observer inside the fact, preserves raw facts no parse or fold
can yet use, and prefers a named incomplete state to a false binary:

unfolded · live edge · file-pre-genesis · unhistorized · unchecked ·
stale coverage · aggregate witness unsupported · committed but incomplete

These are not error cases. They are statements of where the system's
knowledge or authority ends.

Signatures fit this model only while their claims stay precise. A fact
signature attests that a key signed content — not that the observation is
true. A tick chain commits to a store's sealed windows — it attests
receipt, not chronology, and does not make the folded conclusion
infallible. "Unchecked" must never render as "verified," and "verified"
must always say what was verified.

## The loop's central risk

If conclusions re-enter as observations, a system can accumulate evidence
produced by its own prior interpretations. Without visible derivation,
repetition looks like independent corroboration.

The substrate carries its half of the answer: refs, origin,
contributing-fact windows, tick envelopes, and declaration generations
discriminate a primary observation from a derived conclusion. But those
references are optional to consult, and that optionality is where the
open problem lives — at the read path, not the substrate. What a lens
surfaces once becomes more likely to be surfaced again, while material a
bounded fold or lens omits becomes progressively less visible, with
nothing distinguishing omitted-because-irrelevant from hidden-by-the-
compression. Lineage machinery cannot help if the reading practice never
invokes it.

This is not a reason to break the loop; it is a reason to make its
compression disclosable. The raw-fact escape hatch is an epistemic
safeguard, not a debugging convenience. The open design question is
whether a lens can declare what it dropped, cheaply enough that the
disclosure actually fires. The healthiest version of the loop focuses
attention while remaining interruptible by new, dissenting, or previously
unfolded observations.

## Access, not the model, needs simplifying

The concepts are coherent, but a correct client currently composes too
many of them: residence, declaration authority, grants, custody, signing,
boundaries, stale heads, committed-error semantics, recovery. Those belong
in the substrate — concentrated behind a few high-level operations
(resolve, read-with-provenance, emit, plan and apply declaration changes,
review publication) returning rich typed results, so applications
coordinate and render instead of each becoming a partial protocol
implementation. This consolidation is already the project's ratified
direction; an outside reader deriving the same seam from the code alone is
evidence it is the right one.

One caution inside it: "give every answer a consistent provenance
envelope" is right when the envelope carries the answer's own basis, and
wrong when it smuggles in fresh current-state — a read's basis is stable;
"current state" is a separate, racy question. Keep them apart.

Vocabulary is the second access problem. Fact, spec, fold, vertex,
boundary, tick, observer, witness, lineage, declaration, residence,
custody — all defensible, none first-day. The interface teaches
progressively: read → emit → declare, revealing more as the user's
questions deepen.

## What is protected

- Raw facts remain accessible beneath every interpretation.
- Fact, folded entity, and tick remain distinct concepts.
- Event time never substitutes for receipt order.
- Declaration changes remain historized after adoption.
- Derived indexes never masquerade as canonical artifacts.
- "Unchecked" never renders as "verified."
- Signatures attest claims, not external truth.
- Domain vocabulary stays in declarations and payloads, not the substrate.
- Aggregates never pretend to possess one witness history.
- Every presentation surface leads back to contributing facts.
- Attention stays connected to explanation; ranking never goes opaque.

Loops can serve monitoring, project memory, task orchestration, and
fiction production precisely because it is not reducible to any one of
them. An application is a store plus a skin; the shapes never change.

## Overall reading

A cross between an append-only field notebook, an event-sourced
materialized-view engine, a versioned ontology, an instrument for focusing
attention, and a system of notarized checkpoints. Its identity is not any
single primitive but the preserved chain:

```text
observation → interpretation → accumulated state → publication
  → attestation → attention → higher-level observation
```

Most systems discard several of those transitions and keep only the final
answer. Loops keeps the answer inspectable all the way back to its basis:
why does it say that? which observations, whose, under which
interpretation — and which interpretation existed then? had this store
received it yet? was this ever published? what exactly was attested? why
was this brought to my attention now?
