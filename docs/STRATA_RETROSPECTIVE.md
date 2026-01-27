# Strata Retrospective

Notes on the experience of using strata for the genesis document task (2026-01-27).

## The arc of the session

This was fundamentally a **research and synthesis** task, not a coding task. Strata served as an oracle — posed increasingly specific conceptual questions, collected material, then synthesized into a document with editorial structure and semantic tagging.

The experience felt like interviewing a historian who has read every primary source but can only answer in essays. Each answer was valuable, thorough, and somewhat verbose. No ability to interrupt or redirect mid-answer. The pattern was: ask a big question, receive a big answer, mentally note what was already covered, figure out what angle the previous answer missed, craft the next question to fill the gap.

## What surprised me

**The quality of narrative reconstruction.** Strata didn't just find facts — it reconstructed causal chains. "This happened because that constraint led to this frustration which produced this insight." That's historiography, not search. Whether that narrative was always accurate to the original conversations can't be verified (see: citation format feedback), but it was internally coherent and matched the codebase evidence.

**The overlapping returns.** By the 4th query, diminishing returns on new material. The Event-to-Fact rename and the five-atom crystallization appeared in every single response. This suggests the tool's retrieval is biased toward the most densely-discussed topics. Rarer, more peripheral threads (the `datetime` to float simplification, the shallow copy purity bug) only appeared when asked about specifically via the dead-ends query.

## What I'd do differently

If doing this again: **front-load with one very broad query** to get the lay of the land, then **use narrow, specific queries** targeting gaps: "tell me only about the shapes vocabulary crisis," "tell me only about the monorepo naming debate." The broad-then-narrow pattern would reduce redundancy.

Also: **draft the document structure first** (acts, sections, semantic tags) and then query strata to fill specific sections, rather than collecting all material first and structuring after. The tool is better as a targeted recall system than as an open-ended brainstorm partner.

## The meta-observation

There's something recursive about using strata — an AI tool that archives AI conversations — to write the genesis story of a project whose core principle is that observation-feedback loops nest at every timescale. This session is itself a loop: queried archived observations, folded them through an editorial shape, and produced a document (a Tick) that could enter the next conversation as atomic input. The tool being evaluated is a participant in the architecture being documented.

That's either elegant or dizzying. Possibly both.
