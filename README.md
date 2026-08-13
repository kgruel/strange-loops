# strange-loops

Open any application's database. Somewhere in it is a row that says the world
is X — a balance, a status, a current title. Nobody ever witnessed that row.
It is a conclusion: merged from many writes, stripped of who saw what and
when, updated in place until it agrees with itself. Every writer only ever
possessed something smaller and more honest — *I observed X at time t* — and
the row is what remains after that evidence is discarded. When the meaning of
the data shifts, the conclusion is wrong shape, and you migrate.

This system stores the evidence and derives the conclusions.

## The truths

**Time is fundamental.** The past happened. Facts are observations of what
occurred, in the order they were received. You are always in the present,
observing an ordered past.

**The observer is first-class.** A fact exists because someone witnessed it
and cared enough to record it. Who observed is part of what the observation
means. Two observers can record contradictory facts; contradiction is data,
not a conflict to resolve. There is no consensus present anywhere in the
system — that premise is refused, not deferred.

**Meaning binds at read.** The record never learns your schema. Facts are
written plain — a kind, a time, a payload, an observer — and everything they
*mean* is a function applied when someone looks: how they accumulate, how
they relate, what surfaces. Declare a new relationship today and facts from
months ago participate in it. Writes never migrate. Meaning re-binds.

**Witnessing travels.** Facts are signed by their observer and sealed in
chained windows. The guarantees live in the data, not the deployment: a fact
signed here verifies anywhere, so history can cross store boundaries — to a
collaborator, an agent, another machine — without a central authority to
vouch for it. The chain attests receipt, not chronology: it proves what an
observer had witnessed by each boundary, and proves the record was not
rewritten after.

**Everything is loops.** Observations flow in, accumulate into state,
boundaries resolve, ticks flow out — and a tick is itself a fact, free to
enter another loop. There are no endpoints. Depth is not designed; it
emerges from resolutions feeding forward.

**Scale is residence.** A store is a stance, not a place. Facts carry
identity that is safe to merge from anywhere, so combining stores is an
ordinary local operation, and where a store lives — a file in a repo, an
index beside it, something larger — is a detail the model never names.
Scale is the same composition, iterated.

## The shapes

Three shapes. Everything else is composition or configuration.

```
Fact    something observed     kind + ts + payload + observer
Spec    something expected     fields + folds + boundary
Fold    how observation accumulates    state + fact → new state
```

A **Fact** is a single observation, immutable, append-only. Correction is a
new fact, never an edit. You read an essay one morning and it mattered:
`kind=read`, the address, the moment, you. That row is complete. It claims
nothing about the world — only that you witnessed something.

A **Spec** declares what a vertex expects: which kinds matter, how each
accumulates, when accumulation resolves. It is the contract for attention,
not a schema for storage — the facts beneath it never change shape to
satisfy it.

A **Fold** is a pure function from state and fact to new state. State is
always derived, never stored: replay the facts through the folds and it
reconstructs. Your morning's read joins a week of reads; the fold holds
what the week is becoming.

When a boundary resolves, accumulated state seals into a **tick** — what a
period became, signed, chaining the window of facts it witnessed. The week
of reading closes: one tick, holding its residue, sealing its evidence.
And a tick is a fact. It can flow into another vertex and accumulate there.

## The pattern

One pattern executes the model.

A **vertex** receives facts, routes them by kind, accumulates state through
folds, and produces ticks at boundaries. An observer sees the state through
a **lens** — a perspective at some fidelity, from a raw dump to a rendered
view — and acts by emitting new facts. The loop closes through the observer,
not through the mechanism.

Fidelity is per-observer because perception is. An agent reads a firehose
of logs whole; a human cannot, and no single view serves both — one
drowns, the other starves. Sharing the view fails; sharing the record
does not. The same store, one lens at glance width, another at full
depth, and every observer grounded in the same ordered past. A human and
a machine can finally be looking at the same thing.

Because ticks are facts, vertices compose. One store's resolution is
another store's signal. Your reading store ticks into an attention vertex;
so does a store of what you bookmarked, and a store compressed from your
browsing. None of them was built to know the others. Combined, they rank a
mass of unread material by what you have demonstrably cared about — over
any window, chosen after the fact, under salience dials that did not exist
when the facts were written. "What mattered to me that week" is a query,
not a project. Every silo fails at exactly this composition, because each
froze its meaning at write. Here there is nothing to integrate: everything
is already the same three shapes.

## Applications

An application is a store plus a skin: a write vocabulary and a lens
configuration for one domain. The substrate does not change.

This repo runs several. A design store accumulates this system's own
architecture — decisions, open threads, falsifiable predictions — and each
working session opens by reading its fold. A homelab skin turns the same
shapes into monitoring: services observed, boundaries firing, attention
routed to what drifted. A task skin runs work orchestration — tasks as
loops, workers as observers. Elsewhere the same substrate wears a
fiction-production skin, tracking a novel's process. Rendering is shared:
one semantic renderer serves every skin's lenses.

The stores differ only in what their observers care about. The shapes
never change.

## Boundaries of the model

It is not a database of state. It never stores "the world is X" — that row
is a conclusion nobody witnessed. There is no update, and no single truth
even at scale.

It is not consensus machinery. It spends nothing on agreement because it
rejects the premise that a single present exists to agree on.

It is not schema-free. The schema moved: out of the storage engine, into
read-time declarations and into discipline. Kinds, stable names, and fold
keys are real commitments — cheap, additive, retroactive, and held by
practice rather than enforced at write. Domains that need writes that
cannot be nonsense — a payments ledger, an inventory count — want their
schema at write, and should keep it.

It is human-scale by construction. One store is one observer's experienced
reality, sized to a life. Anything larger is topology: more stores, more
observers, signed facts crossing between them.

## Lineage

The frames arrived after the shape. Most of this was built first — the
separations found through work — and the search for kindred thinking came
later, to give the rest of the thinking form. What the search found:

**Weaver's three levels.** The communication problem splits into technical,
semantic, and effectiveness layers — and Shannon could prove theorems about
the technical layer precisely because he refused to let meaning into it.
The record layer here repeats that refusal: it can be signed, chained, and
verified because it never learns what its facts mean. The layers were
separated in the code before the correspondence was noticed.

**Uexküll's umwelt.** No organism inhabits "the world"; each lives in the
world it can perceive. A store is an umwelt — one observer's experienced
reality, not a fragment of some shared one. Combining stores does not
approximate the world; it composes a richer umwelt for whoever is looking.

**Hofstadter's strange loop** is the exception — it was there from the
start, in the name: a system whose levels fold back through themselves,
observed by observers whose observations re-enter it. And the **fold**
carries functional programming's own meaning, unchanged: state and fact
in, new state out, the past replayable from the record.

These are confirmations, not blueprints. Each search happened after the
thing it names existed, and each is itself recorded — a dated, signed
fact in the store this document describes. The provenance of the thinking
has provenance.

---

*A system for focusing attention. The mechanism is data. The purpose is
focus. The strange part is that there's more than one of you.*
