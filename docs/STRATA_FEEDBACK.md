# Strata Feedback

Observations from using strata to reconstruct the prism genesis document (2026-01-27).

## What worked well

1. **Rich recall across workspaces.** Every query returned material spanning multiple sessions and repositories. The cross-workspace synthesis is the killer feature — no single conversation transcript could have produced the genesis document. The tool stitched together `ev`, `rill`, `cells`, and `prism` workspace histories into a coherent narrative.

2. **Natural language query interface.** Conceptual questions ("what were the intellectual pivots?") worked without needing filenames or timestamps. The queries behaved like asking a historian, not searching a database.

3. **Density of returned material.** Each response was genuinely substantive — full quotes, commit hashes, specific conversation IDs, chronological ordering. No need for follow-up "tell me more about X" queries to get depth.

## What would improve the experience

1. **Conversation citation format.** Results reference conversation IDs (e.g., `01KFYDMRKDHM`) but there's no way to jump to that conversation. A deep link or at minimum a workspace + date would make citations actionable. Can't verify quotes or get surrounding context without manual searching.

2. **Temporal ordering controls.** No way to ask "what happened first?" vs "what happened most recently?" with confidence. The tool returns thematically organized material. A chronological mode — "give me the timeline of X" — would be valuable for genesis-type work specifically. Chronology had to be inferred from commit hashes and content clues.

3. **Deduplication across queries.** Running 6 queries produced significant overlap — the Event-to-Fact rename, the Fold ownership dialectic, and the Tick collapse question appeared in nearly every result. A session-aware mode where subsequent queries know what's already been returned would reduce redundancy and allow going deeper faster.

4. **Query scoping.** No way to scope to a specific workspace or time range. For a project with a clear predecessor (`ev` to `facts`), being able to say "only conversations from the ev workspace" or "only January 2026" would help isolate a specific era rather than getting the full sweep.

5. **Confidence indicators.** Some returned material felt like confident direct recall, other parts felt like plausible inference. The tool doesn't distinguish "this is a direct quote from conversation X" from "this is my synthesis across several conversations." For a genesis document, that distinction matters.

6. **Incremental refinement.** The skill runs as a forked execution — fire and forget. No dialogue within a strata session. Can't say "that's great, now go deeper on the reactive detour specifically." Each query starts fresh. A conversational mode within the skill would allow drilling down without re-providing context.

## Skill-level suggestions

7. **Expose strata as a tool, not just a skill.** The current invocation (Skill -> strata) is opaque from the orchestrating agent's perspective. A single text blob comes back. If strata exposed structured results (conversations referenced, confidence scores, date ranges covered), the orchestrating agent could make better decisions about follow-up queries.

8. **Batch query support.** Wanted to run 6 queries in parallel but the Skill tool runs sequentially (each invocation forks). A batch mode — "here are 6 questions, return 6 answers" — would cut wall-clock time significantly for research tasks.

9. **Semantic tagging integration.** ~~The ability to tag strata elements with labels for future queries.~~ **Update:** This already exists — `strata tag`, `strata tags`, and `strata query -l` provide exactly this. The gap was discoverability: the strata skill never surfaced these capabilities. I wrote the original feedback assuming tagging didn't exist because the skill interface gave no indication it did. Only when prompted to run `strata --help` directly did the full CLI surface become visible. See the tagging experience section below.

## Tagging experience

After discovering that `strata tag` and `strata query -l` exist, I applied 10 semantic tags to 58 conversations across the archive. The workflow and observations:

### The workflow

1. **Conceptual query via `strata ask --conversations --json`** — semantic search with `--conversations` mode ranks whole conversations by relevance score. This was the discovery step: "which conversations discuss dissolution?" returns scored conversation IDs.

2. **Score-based selection** — each tag search returned 15 candidates with scores from ~0.65 to ~0.85. I selected conversations above a relevance threshold per tag (roughly 0.68-0.70 for most, 0.80+ for `forcing-function` which had very strong signal in gruel.network).

3. **Batch tagging via `strata tag ID tagname`** — applied in shell loops, one tag at a time. Prefix matching on conversation IDs works, which is ergonomic.

4. **Verification via `strata query -l tagname`** — confirmed retrieval. `strata query -l dissolution` instantly returns the 10 tagged conversations spanning ev (Jan 4) through prism (Jan 27).

### What worked well

- **`strata ask --conversations`** is the right primitive for this. Ranking whole conversations rather than chunks gives exactly the granularity needed for tagging — you want to tag a session, not a paragraph.

- **Prefix matching on IDs** makes the CLI pleasant. Full ULIDs are unwieldy; being able to use `01KFYDMRKDHM` instead of the full 26-char ID removes friction.

- **Tags as first-class query filters.** `strata query -l dissolution` returns clean results immediately. The tags become a durable semantic index — future agents or sessions can retrieve by concept without re-running semantic search.

- **Tag coexistence with auto-tags.** The `shell:test`, `shell:vcs` etc. auto-tags and the manually-applied semantic tags live in the same namespace. `strata tags` shows both. No collision, no confusion about which is which.

### What would improve the tagging workflow

1. **Tag removal.** No `strata untag` or `strata tag --remove` visible in the help. The `test-prefix-match` tag I applied during exploration is now permanent. For an iterative tagging workflow where you refine boundaries, removal is essential.

2. **Bulk tagging from search results.** The workflow was: run `strata ask --conversations --json`, extract IDs in Python, then loop `strata tag` per ID. A pipeline mode — `strata ask --conversations "dissolution" | strata tag --stdin dissolution` — would collapse three steps into one.

3. **Score visibility during tagging.** When deciding which conversations to tag, I had to eyeball scores from the JSON output. A `strata ask --conversations --threshold 0.72 "dissolution"` that shows scores inline (without `--json`) would make the selection step faster.

4. **Tag descriptions.** Tags are bare strings. A `strata tag --describe dissolution "Questions that dissolved rather than being answered — false distinctions revealed"` would make the tag index self-documenting. Currently the meaning of each tag exists only in the genesis document.

5. **Skill awareness of CLI capabilities.** The biggest gap: the strata skill (invoked via Claude Code's Skill tool) doesn't surface the tagging, querying, or `ask --conversations` capabilities. I used the skill for research and the CLI for tagging — two completely separate interfaces to the same system. If the skill knew about tags, it could say "I found these 10 conversations relevant to your query — want me to tag them?" Or better: "retrieving conversations tagged `dissolution` from a previous session" as a retrieval shortcut.

6. **Cross-tag queries.** `strata query -l dissolution -l vocabulary-as-architecture` to find conversations tagged with both. Some conversations (like `01KG0815BAV6` and `01KFXBA5B1B2`) appeared in 4-5 tag searches — they're conceptual nexus points. Being able to find multi-tagged conversations would surface the densest sessions.

### Tag distribution

Applied 10 tags to 58 conversation-tag pairs across the archive:

| Tag | Count | Primary workspaces |
|-----|-------|--------------------|
| `dissolution` | 10 | prism, experiments, ev, cells |
| `forcing-function` | 8 | gruel.network |
| `vocabulary-as-architecture` | 8 | prism, cells |
| `self-similarity` | 7 | prism, cells |
| `the-great-deletion` | 7 | experiments |
| `the-missing-middle` | 7 | experiments, ev-present, cells |
| `inciting-friction` | 6 | ev, cells, experiments, gruel.network |
| `co-creation` | 6 | cells, prism |
| `declaration-over-procedure` | 6 | prism, ev |
| `observation-as-participation` | 6 | prism, ev, experiments, cells |

Score range across all searches: 0.65–0.85. `forcing-function` had the strongest signal (0.85+, gruel.network sessions are an obvious match). `inciting-friction` had the weakest (0.72 ceiling — the concept is abstract and conversations embodying it don't use those words).
