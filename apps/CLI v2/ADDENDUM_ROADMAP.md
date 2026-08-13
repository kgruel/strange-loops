# CLI v2 addendum: product direction and potential roadmap

Status: exploratory addendum  
Relationship to `PLAN.md`: ideas here are candidates after the three-command MVP, not additional MVP requirements.

## The larger opportunity

Loops is not merely an append-only event database with a terminal wrapper. Its libraries describe four progressively richer ways to encounter the same store:

```text
inventory  →  declared meaning  →  temporal review  →  automation
```

Each level should remain useful on its own:

1. **Inventory** answers what is physically present without assuming a domain.
2. **Declared meaning** interprets facts through the vertex's evolving ontology.
3. **Temporal review** explains what was known, received, declared, and sealed at a chosen point.
4. **Automation** runs sources and reacts to boundaries while retaining the same facts, receipts, and provenance.

This progression can make one CLI approachable for a notebook while still rigorous enough for an operational system.

## 1. Inventory: begin with evidence

The first experience should not require users to understand folds, boundaries, witnesses, or declaration lineage.

```text
loops read journal.vertex
loops read journal.vertex --facts --limit 20
loops read journal.vertex --id 01K4Q
```

The inventory layer exposes:

- kinds and their frequency;
- observer and time ranges;
- recent raw facts;
- ticks and store freshness;
- canonical backend and agreement status;
- undeclared/unfolded data.

### The unfolded inbox

Loops has a valuable schema-later property: a fact of an undeclared kind can be stored now and interpreted later. The CLI should make that visible rather than treating it only as a warning.

```text
loops read project --unfolded

unfolded kind       facts  sample fields
idea                    8  title, body, related
scene.note             14  chapter, text, character
```

Potential follow-up:

```text
loops kind suggest project.vertex scene.note
```

`kind suggest` must remain advisory. It may report observed fields, cardinality, missing-field frequency, apparent scalar types, and possible key candidates, but it must never mutate the declaration or assert domain meaning. For example, “`slug` is unique in 98/100 sampled facts” is evidence; “`slug` is the identity” is a decision only the user can make.

### Store health as part of inventory

Every read should be able to disclose, without overwhelming the default view:

- which artifact is canonical;
- whether a JSONL-derived index agrees with its log;
- whether declaration state came from the store or a pre-genesis file;
- how many facts remain on the unsealed live edge;
- whether search coverage is absent or stale.

Suggested drill-down:

```text
loops read project --explain
loops store status project.vertex
```

`--explain` means “show the provenance of this answer,” not “print debug logs.”

## 2. Declared meaning: use the ontology without hard-coding a domain

A vertex declaration changes the question from “what rows exist?” to “what does this store currently say?”

```text
loops read project.vertex --state
loops read story.vertex --state --kind character
```

The renderer should consume `FoldState` generically:

- keyed folds render stable entity addresses;
- collect folds render ordered observations;
- scalar folds render counts, sums, extrema, and averages;
- preview declarations select concise human context;
- lifecycle declarations filter the default active view while disclosing hidden counts;
- edge declarations make relationships navigable.

### Addresses as the common navigation language

The CLI encounters several identifiers that must remain visibly distinct:

| Identifier | Example | Meaning |
|---|---|---|
| Entity address | `decision:auth` | Current folded entity selected by kind and key |
| Fact ID | `01K4Q...` | One immutable observation/receipt |
| Witness position | durable handle or fact cursor | A prefix of one store's receipt order |
| Tick | tick name plus stored identity | A sealed boundary snapshot |

Commands should not accept a single ambiguous `ID` argument and guess among these spaces. Make the address form explicit in help and JSON output.

Potential navigation:

```text
loops read project decision:auth
loops facts project decision:auth
loops graph project decision:auth --depth 2
```

### Graphs that remain domain-neutral

Typed edges are useful across very different stores:

```text
service:billing       --depends-on→ service:postgres
scene:departure       --features→   character:mara
decision:auth         --supersedes→ decision:session-cookies
```

A graph command can therefore be structural rather than infrastructure-specific:

```text
loops graph story.vertex character:mara
loops graph platform.vertex service:billing --depth 2
loops graph project.vertex decision:auth --incoming
```

The first implementation should show declared outbound edges. Inbound traversal needs an explicit indexed or bounded library query; it should not scan an unbounded store invisibly.

### Lenses as optional presentation, not hidden semantics

The default renderer should always work from typed state. A declared lens may then improve presentation for a particular domain, but it should not become the only way to access data.

Potential precedence:

```text
--raw               raw facts
--state             generic typed state
--lens default      declared presentation
--lens NAME         explicit alternate presentation
```

Machine output should encode state, not terminal layout. Lenses should either emit a structured presentation model or be limited to human formats.

### Applications as skins over the substrate

The project README offers a useful product boundary: an application is a store plus a skin. CLI v2 should preserve that separation.

The generic CLI owns substrate operations:

```text
read, emit, declare, review, verify, transfer
```

A skin may add:

- a domain write vocabulary and defaults;
- declaration templates;
- guided authoring forms;
- lens selection and labels;
- saved queries and navigation;
- shortcuts that lower visibly to generic commands.

For example, a fiction skin might offer `scene note` and an infrastructure skin might offer `service observe`, but both must produce an ordinary fact and return the ordinary receipt. A skin does not get a private persistence path, hidden update semantics, or a second notion of identity.

The extension mechanism need not ship in the MVP. The command layer should simply avoid hard-coding one domain's nouns and keep request/result models reusable by future skins.

## 3. Temporal review: make the different meanings of “then” explicit

Loops carries several temporal axes:

- **Observation/event time:** when the fact says it happened.
- **Witness/receipt order:** when this store received the fact.
- **Declaration time:** which ontology interpreted the facts at a point.
- **Boundary time:** when accumulated state was sealed into a tick.

These axes should never collapse into one generic `--time` switch.

### Event-time projection

```text
loops read project --state --as-of 2026-08-01T12:00:00Z
```

Question answered: “Using event time, what state and ontology project at this timestamp?”

### Witness-position reconstruction

```text
loops read project --state --at 01K4Q...
```

Question answered: “What had this particular store received at this durable position?”

This distinction matters for backdated facts: they change later reconstructions by event time but must not appear at a witness position that predates their receipt.

### Tick review

```text
loops read project --tick deploy@latest
loops review project --tick 01K4T...
```

A tick is a published boundary snapshot, not merely another timestamp. A review view can show:

- the snapshot payload;
- its fact window and cursor;
- the contributing facts;
- chain and signature status;
- the ontology used to interpret it;
- the facts now on the live edge after it.

### Diff as a first-class review operation

```text
loops diff project --from 01J... --to 01K...
loops diff project --from 2026-08-01 --to 2026-08-13 --mode event-time
```

Diff output should separate:

- facts received;
- folded entities added, changed, or removed;
- declaration changes;
- ticks produced;
- changes in provenance or verification status.

The engine already models structural fold changes in held sessions. A complete historical diff should use library-owned reconstruction and comparison rather than app-specific payload heuristics.

### Ontology history

Because declarations themselves are historized, users should be able to review how interpretation changed:

```text
loops vertex history project.vertex
loops vertex diff project.vertex --from 01J... --to head
```

Example output:

```text
kind task added
  fold: items by name
  search: name, description

kind service modified
  + edge database targets service
  + lifecycle status active=running,degraded
```

This makes “the schema changed” an inspectable event rather than an invisible deployment detail.

## 4. Provenance: a consistent confidence vocabulary

Provenance should be present on every surface but progressive in detail.

Suggested terms:

| Signal | Meaning |
|---|---|
| `stored` | The fact has a durable receipt in this store |
| `signed` / `unsigned` | Authorship signature is present or absent |
| `sealed` / `live-edge` | A tick commits to the fact, or it remains outside the newest seal |
| `verified` / `unchecked` / `broken` | Available verification was run and passed, was unavailable, or failed |
| `historized` / `file-pre-genesis` / `unhistorized` | Provenance of the ontology used for the answer |
| `canonical-agreement` | A JSONL log and derived index agree at the requested audit depth |

Potential commands:

```text
loops explain project decision:auth
loops verify project.vertex
loops verify project.vertex --deep
```

`explain` should answer how a displayed entity was derived:

```text
decision:auth
  current value from fact 01K4...
  4 facts folded by topic
  declaration generation sha256:...
  latest contributing fact signed by kay
  sealed through tick project@01K5...
```

The CLI should never turn unavailable verification into a green check. “Unchecked” is meaningful state.

## 5. Automation: sources and boundaries are a separate trust boundary

Manual emission and source execution should remain separate commands.

```text
loops emit project.vertex decision --data ...
loops source sync status.vertex
loops source run status.vertex disk
```

Sources may execute commands, use environment-backed parameters, and cause boundary `run` hooks. Those side effects deserve explicit invocation and clear previewing.

Potential safety surface:

```text
loops source plan status.vertex
loops source sync status.vertex --allow-run
```

Default automation policy should disclose commands and suppress boundary run hooks unless the user explicitly enters an execution-capable command or supplies an opt-in flag.

### Watch and continuous clients

The held vertex API already supports immutable snapshots and typed change batches. That enables:

```text
loops watch project.vertex
loops watch project.vertex --format jsonl
loops watch project.vertex --kind task
```

A watch event should contain receipts, ticks, structural row changes, ontology changes, and cursor positions. Terminal highlighting is just one renderer of that event.

This same stream can support a future TUI or daemon without inventing a second state model.

## 6. Batch and integration workflows

Once single-fact emission is dependable, add an NDJSON protocol:

```text
loops emit project.vertex --batch facts.ndjson
cat facts.ndjson | loops emit project.vertex --batch - --format jsonl
```

Questions that must be settled before shipping batch mode:

- Is the batch atomic, or is each line independently committed?
- How are partial completion and retry represented?
- Can callers provide stable fact IDs for idempotency?
- Are boundary effects produced per fact or after the batch?
- Does one bad row stop, skip, or quarantine later rows?

The safest initial contract is independent receipts with an explicit processed count and no claim of whole-file atomicity. Caller-supplied IDs should not be exposed until their security and collision semantics are deliberate.

### A future client/daemon split

CLI v2 should keep command handlers independent of direct terminal parsing. Today they may call local libraries; later the same request/result objects could travel to a daemon holding vertex handles.

```text
terminal parser → command request → local or remote client → result model → renderer
```

This separation offers:

- long-lived handles and efficient watches;
- centralized key custody;
- fewer concurrent local writers;
- remote workspaces;
- one JSON contract shared by CLI, TUI, and integrations.

It should not be built prematurely, but the first CLI should avoid making direct database objects part of its command-layer interface.

## 7. Proposed roadmap beyond the MVP

### Release A: trustworthy inspection

- `read` inventory, raw facts, state, ticks, and fact lookup.
- Canonical backend and declaration-provenance disclosure.
- Versioned JSON/JSONL results.
- Explicit internal-fact visibility.

### Release B: trustworthy writing

- Single-fact vertex emission.
- Observer grants and operation-fresh custody.
- Exact receipts and committed-error handling.
- SQLite and JSONL canonical write tests.

### Release C: evolving meaning

- `kind list/show/add/edit/retire`.
- Declaration preview, signed application, and recovery.
- JSONL-safe declaration ceremonies.
- Unfolded inbox and evidence-only `kind suggest`.

### Release D: review and provenance

- Event-time and witness-position reads.
- Tick review and contributing-fact traversal.
- Fold and ontology diffs.
- `explain` and consistent verification vocabulary.

### Release E: relationships and discovery

- Typed-edge graph traversal.
- Explicit search coverage and reindex workflow.
- Declared lenses and structured presentation models.
- Skin manifests for domain vocabulary, declaration templates, and guided authoring, all lowering to generic operations.
- Shell completion driven by kinds and entity addresses.

### Release F: continuous operation

- Source plan/run/sync.
- Watch as text and JSONL.
- TUI consuming the same result/event models.
- Optional daemon transport when multiple clients justify it.

### Release G: exchange and maintenance

- Batch emission with explicit partial-completion semantics.
- Slice, merge, receive, export, rebuild, compact, and rebirth.
- A canonical-backend support matrix enforced by the libraries.
- Remote transports once custody and conflict behavior are designed.

## 8. Product guardrails

### Do

- Preserve raw facts even when a richer view exists.
- State which declaration generation interpreted an answer.
- Distinguish event time from witness position.
- Treat canonical storage and derived indexes honestly.
- Make mutations explicit and recoverable.
- Let technical and narrative stores use the same primitives.
- Build text, JSON, watch, and TUI surfaces over shared result models.
- Distinguish primary observations from conclusions re-entering as derived facts.
- Preserve a descent from every surfaced conclusion to its contributing evidence.

### Do not

- Infer universal identity or status fields from payload names.
- Treat an entity address, fact ID, tick, and witness cursor as interchangeable.
- hide stale search coverage or unsealed live-edge facts.
- mutate a derived index as though it were canonical.
- execute source or boundary shell commands as an incidental effect of reading.
- report missing verification as successful verification.
- impose a global witness order on an aggregate of independent stores.
- present repeated derived conclusions as independent corroborating observations.
- let a lens or bounded fold make omitted evidence unreachable.

## 9. Roadmap commitments from the final review

The following ideas appeared throughout this addendum; they are promoted here so they remain visible during prioritization rather than surviving only as scattered implications.

### Make declaration authority visible

Before genesis, the `.vertex` file is authoritative. After genesis, the store owns the historized declaration and the file is an ingress form/cache. Every vertex status and mutation surface should disclose the current authority, lineage, and declaration generation. A file edit that has not entered the authoritative store must never look enacted.

Roadmap home: Releases A and C.

### Treat ticks as reviewable publications

A stored tick is a sealed boundary snapshot with an interval, contributing-fact window, and optional attestation—not merely another event row. Give ticks stable review, compare, and explain surfaces suitable for operational checkpoints, releases, writing sessions, approvals, and research milestones.

Roadmap home: Release D.

### Make schema-later discovery a first-class workflow

Undeclared facts are durable evidence waiting for interpretation, not malformed leftovers. Support the progression `emit → inspect unfolded → suggest → declare → replay history`, while keeping suggestions evidence-only and mutations explicit.

Roadmap home: Release C.

### Represent aggregate time honestly

An aggregate has independent member witness orders, not one global receipt sequence. Event-time aggregate reads are valid; witness-mode aggregate history requires a vector of per-member positions. Until that representation exists, refuse a scalar aggregate witness cursor.

Roadmap home: Release D, with a later aggregate-vector design.

### Use precise mutation language

Do not collapse correction, upsert-by-new-fact, lifecycle inactivation, kind retirement, declaration editing, and physical data maintenance into generic `edit`, `delete`, or `rm` verbs. Command names and receipts should reveal the append-only or ceremonial operation actually performed.

Roadmap home: every mutation release, beginning with B and C.

### Add humane narrative authoring without a second data model

JSON remains the generic wire format. Later, add `--text`, stdin, `$EDITOR`, or declaration-guided forms for long prose. Every authoring affordance must still resolve to an ordinary fact and display the exact payload before or after emission.

Roadmap home: Release E, after the JSON contract stabilizes.

### Preserve a future client boundary

Keep terminal parsing, command requests, substrate operations, result models, and rendering separate. The first implementation may call local libraries, but the same request/result contracts should be able to travel to a long-lived daemon later for watches, centralized custody, concurrency, and remote workspaces.

Roadmap home: Release F when real multi-client pressure justifies it.

## 10. Open design questions worth deciding deliberately

1. **Default human view:** Should `loops read VERTEX` always show inventory, or may a declared default lens take over? Recommendation: inventory remains stable; `--state` or a future `view` command opts into presentation.
2. **Observer discovery:** Is an undeclared observer accepted in non-strict vertices, refused, or accepted unsigned with a warning? This must be a library policy, not a CLI guess.
3. **Narrative authoring:** JSON is the correct generic wire form but awkward for long prose. A later `--text`, `$EDITOR`, or declaration-guided form can improve authoring without changing the fact model.
4. **Entity correction:** Is correction always another fact, or should the CLI offer an `edit` affordance that transparently emits a replacement/upsert fact? Any such command must describe the actual append-only operation.
5. **Deletion language:** Kind retirement, lifecycle inactivation, and fact removal are different operations. Avoid one ambiguous `rm` command.
6. **Aggregate history:** Witness order is per store. Historical aggregate views need a vector of member positions or must remain explicitly event-time-only.
7. **Trust defaults:** Which reads run a cheap canonical agreement audit automatically, and which require explicit verification? Verification must never repair before inspecting.
8. **Command naming:** Decide whether specialized views remain flags under `read` or graduate to nouns (`facts`, `graph`, `diff`). Optimize for composability and help clarity, not the smallest possible verb count.

## Closing direction

The most distinctive CLI is not the one with the most commands. It is the one that makes the substrate's honesty understandable:

- facts may arrive before meaning is declared;
- meaning itself evolves as witnessed history;
- state can be reconstructed along more than one temporal axis;
- a boundary can publish and attest a snapshot;
- relationships remain domain-neutral because their predicates are declared;
- every richer interpretation still leads back to the underlying facts.

If CLI v2 keeps that chain visible, it can feel simple at the beginning without becoming simplistic as the store grows.
