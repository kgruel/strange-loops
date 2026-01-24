# tbd Feedback: Conversation Archaeology

This document captures the experience of using `tbd ask` to reconstruct an intellectual history spanning ~2 months, ~12 workspaces, and hundreds of conversations. The goal was to produce a genesis narrative tracing the arc of thinking, experimentation, and discovery across the experiments ecosystem.

## What Worked Well

### Workspace filtering is essential

The `-w` flag was the single most important feature for this task. Queries like `tbd ask -v -n 15 -w experiments "reaktiv signal computed effect reactive"` consistently returned relevant results from the right context. Without it, cross-workspace noise would have been unmanageable.

The workspace model maps well to project boundaries. Each workspace is a coherent unit of work, and filtering to it feels natural.

### Embedding rerank finds semantic matches

The FTS5 + embeddings rerank pipeline worked surprisingly well for conceptual queries. Searching for "events are facts not instructions" (a conceptual phrase, not literal file content) surfaced the right conversations. Similarly, "cognitive effort collapse marginal cost generalization" found the relevant Obsidian clipping about cognitive debt alongside the actual conversations where these ideas were discussed.

Relevance scores were meaningful — 0.7+ results were almost always on-topic, 0.6-0.65 were often related but tangential, below 0.6 was noise.

### Verbose mode (`-v`) hits the sweet spot

The default snippets-with-scores mode gives enough to decide whether to dig deeper. For this archaeological task, `-v` was the workhorse — enough context to understand what was being discussed without the full prompt/response bulk.

### Chronological mode helps trace evolution

`--chrono` was useful for understanding when ideas appeared. Seeing that the reaktiv experiments cluster in 2026-01-22 while the streaming resource rewrite was 2026-01-05 tells you the sequence of discoveries.

### Conversation continuity summaries are goldmines

When tbd ingests conversations that include continuation summaries (the "This session is being continued from a previous conversation" blocks), those summaries are searchable and often contain the most concise articulation of what was accomplished. The gruel.network media-fix summary and the ev conversation summary were particularly rich finds.

## What Was Frustrating

### Can't search by user voice vs. assistant voice

The most powerful quotes for the genesis narrative were the user's own articulations — "This thing isn't going to stay a 214 line pattern" or "events are facts, not instructions." But tbd indexes prompts and responses together. There's no way to say "find conversations where the *user* said X" vs "find where the *assistant* explained X."

For archaeological/narrative work, the user's voice is the primary source. The assistant's is secondary context. They're currently undifferentiated.

### Result fragmentation across conversations

The same intellectual thread often spans 3-5 conversations (context limits, continuing next day, branching into subtasks). The thread about "events-primary architecture" spans at least 4 conversations in the experiments workspace. tbd treats each as independent — there's no "show me the thread" capability.

Queries return individual exchange snippets. Reconstructing the narrative arc required running the same query multiple times with slightly different formulations, then mentally stitching the timeline together.

### No "first mention" capability

A common archaeological question: "When was X first discussed?" For example, "When did we first talk about version counters replacing reaktiv?" There's no query mode that returns the chronologically *earliest* match. `--chrono` sorts results by time, but if the earliest mention scores lower on relevance, it may be buried below more recent (but derivative) discussions.

### Full exchange mode is too noisy for research

`--full` returns the complete prompt+response pair. For long coding sessions, this can be thousands of lines for a single match. There's no middle ground between "snippet" and "everything." A useful intermediate would be "the exchange where the match appears, plus 1-2 exchanges on either side" — which `--context N` partially addresses, but N=1 is often too little and N=5 is too much.

### Obsidian results are structurally different

Obsidian workspace results return JSON frontmatter blobs rather than conversation exchanges. The taxonomy, tags, and file metadata are useful context, but they render differently and require different mental parsing than conversation results. This isn't wrong — Obsidian content *is* different — but the mixed format in results was occasionally confusing.

### Query reformulation is trial-and-error

Some concepts were hard to find on first query. The "four consumers" pattern (display, record, act, generalize) required trying multiple formulations before finding the right exchange. "Four consumers display record act generalize" didn't find it. The actual pattern terminology turned out to live in the RETROSPECTIVE.md rather than in a conversation — so tbd correctly didn't find it in conversation data.

This reveals a gap: project documentation (README, HANDOFF, RETROSPECTIVE) captures crystallized knowledge that originated in conversations. tbd has the raw conversations, but the crystallized form isn't cross-referenced back.

## Feature Gaps

### Topic/thread tracking

The biggest gap: "show me the evolution of concept X across all conversations, chronologically." Right now this requires running 5-10 queries and manually assembling the timeline. A `tbd thread "events-primary"` command that finds all conversations touching a topic, orders them chronologically, and shows the progression would be transformative for this use case.

### Cross-workspace timeline

"Show me everything across all workspaces in the week of January 22nd" — a temporal slice across the full corpus. `--since` and date filters exist, but combining them with multi-workspace is awkward. A timeline view that shows which workspaces were active when, and what was discussed, would make project-level archaeology much easier.

### Conversation-level summaries

Right now search returns exchanges (prompt/response pairs). But often what you want is the *conversation* — its overall topic, when it happened, how long it was, what was accomplished. A mode that returns conversation-level metadata with a generated or extracted summary would reduce the number of queries needed for broad research.

### Semantic similarity between conversations

"Find conversations similar to this one" — given a conversation ID, find others with overlapping concepts, decisions, or patterns. This would help discover connections between workspaces that aren't obvious from keyword matching.

### Role-filtered search

As noted above: `tbd ask --role user "pattern"` to search only user prompts, or `--role assistant` for responses. For narrative reconstruction, user voice is gold.

### Export/collect mode

During this research, I ran ~30 queries and mentally assembled the narrative. A `tbd collect` mode that lets you tag/bookmark specific results, then export the collected set as a single document, would make the research→writing pipeline smoother.

## The Meta-Question

### Can you reconstruct intellectual history from conversation fragments?

**Partially, yes.** The core ideas, decisions, and pivots are findable. Key quotes are recoverable. The chronological sequence of discoveries can be assembled with effort.

**What's lost:**
- The *feeling* of discovery — the moment something clicked isn't captured in text
- The dead ends that were silently abandoned (you only find conversations that discuss something, not the ones where an idea was tried and dropped without comment)
- The cross-pollination timing — "I was reading about Ratatui *while* working on hlab logs, and that's why the render layer happened" requires inference from timestamps, not explicit connection
- Casual observations that led to major shifts — offhand comments that don't match any search term but were the seed of a later idea

**What would make it better:**
- A way to mark conversations with retrospective annotations ("this is where X started")
- Automatic topic extraction that surfaces the *new* concepts in each conversation (not just keywords, but "this conversation introduced the idea of version counters replacing Signals")
- A "provenance trail" — given a concept in its current form, trace backward through the conversations that shaped it

### How well does tbd serve as cognitive context capture?

For the "remember when we talked about..." use case — well. You can find specific conversations, see what was decided, recover the reasoning.

For the "reconstruct the intellectual journey" use case — adequately but with significant manual effort. The fragments are there, but assembly is entirely on the researcher.

For the "what's the shape of my thinking?" meta-cognitive use case — not yet. There's no view that shows topic clusters, evolution over time, or patterns in how ideas develop. The data is there to build this, but the query interface doesn't expose it.

## Concrete Suggestions (ranked by value for archaeological research)

1. **Thread reconstruction** — Given a concept/keyword, assemble all touching conversations chronologically, with extracted key moments from each. This would have turned 30 queries into 3.

2. **Role-filtered search** — Search user prompts separately from assistant responses. User voice is the primary source for narrative work.

3. **Conversation-level search** — Return conversation metadata + summary instead of individual exchanges. Reduces noise, enables faster scanning of the corpus.

4. **"First mention" mode** — Chronologically earliest match, regardless of relevance score. Essential for "when did this idea emerge?"

5. **Topic evolution visualization** — Even just a timeline of when a keyword/concept appears across workspaces would reveal patterns invisible in individual queries.

6. **Bookmark/collect workflow** — Tag individual results during research, export collected set. The research→writing pipeline needs a buffer.

7. **Cross-workspace timeline** — Temporal slice showing all activity across workspaces in a time range. Reveals concurrent threads of work.

8. **Configurable context window** — Something between "snippet" and "full exchange." "The matched exchange plus N words before/after" would be more useful than "plus N exchanges."

9. **Project documentation cross-reference** — Index README/HANDOFF/RETROSPECTIVE alongside conversations. These crystallized documents are the product of conversations and often contain the clearest articulations.

10. **Retrospective annotations** — Let users mark conversations after the fact: "this is where we decided X" or "this was a dead end." Adds the wisdom of hindsight to the corpus.

## Final Observation

tbd as it exists today is a competent search tool over a conversation corpus. For point queries ("find where we discussed X"), it works well. For archaeological research ("trace the evolution of X across months of work"), it works but requires significant researcher effort — running dozens of queries, mentally stitching timelines, inferring connections.

The gap between "search tool" and "cognitive context capture system" is primarily about *synthesis* capabilities. The data is there. The chunking and embedding are adequate. What's missing is the ability to ask higher-order questions: "How did my thinking about event architecture change over time?" "What dead ends did I explore before arriving at stream topology?" "Which conversations were the pivotal ones?"

These are questions about the *shape* of a corpus, not its *contents*. FTS5 + embeddings answer content questions well. Shape questions need a different kind of index — something temporal, something that tracks concept emergence and evolution, something that understands narrative arc rather than keyword presence.

The irony isn't lost: this is exactly the kind of "derived view over an event stream" that the experiments project itself is building. The conversations *are* the event stream. The intellectual history *is* a projection. tbd could eat its own tail — apply the Stream → Consumer → Projection pattern to its own corpus. The question is whether that's clever or whether it's the obvious next step.
