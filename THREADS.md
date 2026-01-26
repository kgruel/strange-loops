# THREADS — monorepo

Cross-cutting concerns that span multiple libs or affect the monorepo
as a whole. Per-lib threads live in each lib's own THREADS.md.

## Naming — volta (under consideration)

Exploring renaming the monorepo from `prism` to `volta`. The word comes
from poetry (the turn in a sonnet where accumulated meaning shifts) and
music (prima volta / seconda volta — first time through, second time
through). Also carries the electrical association (Alessandro Volta,
circuits, stored potential).

Why volta over alternatives considered:
- **loops**: accurate but generic — collides with event loops, game loops,
  for-loops. The word is a CS primitive, not a distinctive concept.
- **turn**: semantically precise (one complete traversal where observation
  becomes action) but flat as a brand. Also "turns/facts" reads as a
  verb phrase.
- **prism** (current): neutral, doesn't mislead, but doesn't teach
  anything about the system's feedback nature.
- **volta**: carries the semantic accuracy of "turn" with brand texture,
  literary/scientific depth, and a story worth telling. Distinctive,
  searchable, low collision risk (NVIDIA Volta GPU is fading/different
  domain; `volta` on PyPI is abandoned, last commit 7+ years ago).

The name should carry: feedback is first-class, append-only accumulation,
closed causal circuit, observation is participation. Volta gets the first
three and implies the fourth through its poetic meaning (the turn where
the observer's understanding shifts).

Status: thinking on it. No rename work started.

## The pivot — shaped state as universal contract

The volta (complete traversal) has two halves separated by shaped state:

    facts, ticks, peers, shapes        ← below the pivot (universal)
    ─────────────────────────────────
          shaped state (a dict)         ← the pivot
    ─────────────────────────────────
    surface (cells, html, api, ...)    ← above the pivot (paradigm-specific)

Below the pivot: domain logic. Facts enter, shapes fold them, peers
scope them. Universal — doesn't know or care how state renders.

The pivot itself: the output of shape.apply(). A plain dict. The
universal intermediate representation. Format-agnostic.

Above the pivot: rendering and feedback. A surface takes shaped state,
renders it outward, emits interactions inward. Cells is the first
surface (character-grid paradigm, terminal adapter). Future surfaces
would consume the same dict through different paradigms.

Four atoms are universal (tick, fact, peer, shape). Cell is a surface
specialization — the first, not the only. This reframes cells from
"the fifth atom" to "the first surface."

Shaped state as a contract needs investigation: what guarantees does
shape.apply() make about its output? Is it always a dict? Can surfaces
depend on structure, or only on the shape's facet declarations?

Related: cells THREADS.md "Block serialization" and "Grid surface vs
terminal adapter" threads explore the cells-specific side of this.

## Conceptual vocabulary

The volta framing introduces vocabulary for talking about the system:

    volta       one complete traversal: fact → shape → cell → new fact
    close       when a surface emits feedback, completing the volta
    turn        what happens during a volta (the sequence of events)
    feedback    facts emitted by surfaces, re-entering the next volta
    pivot       shaped state — the universal handoff between domain and surface
    open volta  observation without emission (surface watches, doesn't respond)
    prima volta   first pass through new facts (musical: first time)
    seconda volta re-pass after feedback arrives (musical: second time)

Not all of these may earn their keep. prima/seconda volta in particular
need to prove useful in practice before committing to them.

## Surface as a general concept

A surface is the bidirectional boundary where the volta touches reality.
It renders shaped state outward and emits interactions inward as new
facts. Cells is the terminal surface (character-grid paradigm + ANSI
adapter). Other surfaces would use different paradigms:

    Surface type     Paradigm              Atom
    ─────────────────────────────────────────────────
    cells            character grid         Cell (char + style)
    (future) docs    document structure     section/fragment
    (future) api     structured data        endpoint/payload
    (future) web     DOM                    element/component

Each paradigm has its own rendering atom. They share the same contract:
consume shaped state, render outward, emit feedback inward.

Open questions:
- Does the monorepo need a Surface protocol, or is this just a pattern?
- How does emit generalize across surfaces? cells uses keyboard events;
  web would use clicks/forms; api would use request payloads.
- Layer (modal stacking) currently assumes key: str input. Generalizing
  to event-based input is needed before a second interactive surface.
