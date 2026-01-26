# CLAUDE.md

## Build & Test

```bash
uv sync
uv run pytest
```

## What is peers?

**peers** is the identity layer of a five-library ecosystem. It answers: *Who is acting? What can they see/do?*

### The Atom

```python
Peer = name + scope
Scope = see + do + ask
```

### The Key Insight

**Scope cascades through everything.** A Peer's scope defines boundaries that flow through all other layers:
- What **facts** you can emit/see
- What **ticks** you can read/write
- What **forms** you can use
- What **cells** you can render

## The Ecosystem

Five libraries, five atoms, five questions:

| Dimension | Library | Atom | Question |
|-----------|---------|------|----------|
| **Who** | peers | Peer (name + scope) | Who is acting? What can they see/do? |
| **What** | facts | Fact (kind + ts + data) | What semantic meaning? |
| **When** | ticks | Tick (ts + payload) | When did it happen? How does it flow? |
| **How** | forms | Field (name + type) | What shape? How does it transform? |
| **Where** | cells | Cell (char + style) | Where does it appear? How does it look? |

```
Peer (scoped identity)
  └─ emits → Fact → Store → Projection → State → Lens → Block
                                          ↑
                                        Form
```

## Vocabulary

| Primitive | Purpose |
|-----------|---------|
| Peer | name + scope (atomic identity) |
| Scope | see + do + ask (boundaries) |
| grant | expand scope |
| restrict | narrow scope (intersection) |
| delegate | create child peer with restricted scope |

## Design Patterns

Following cells conventions:
- **Frozen state + pure functions** — Peer and Scope are immutable dataclasses
- **Composition via functions** — grant, restrict, delegate are pure
- **Explicit over implicit** — scope boundaries are visible data

## Open Questions

### Scope Semantics
- What do see/do/ask mean concretely?
- Are they glob patterns? URIs? Tags?
- How do wildcards work? (`*`, `**`, `~/*`)

### Needs Gradient
- Must/Should/May for capability requirements
- How does this interact with scope?

### Cascading Mechanics
- How does scope flow to facts/ticks/forms/cells?
- Is it checked at emit time? Read time? Both?
- What happens on scope violation?

### Delegation Chains
- Can a delegate create further delegates?
- Is there a depth limit?
- How do you trace provenance?

## Repository Locations

| Library | Repository | Status |
|---------|------------|--------|
| **peers** | ~/Code/peers | Starting |
| facts | ~/Code/ev | Aliases added |
| ticks | ~/Code/rill | Renamed |
| forms | ~/Code/experiments/forms | Extracted |
| cells | ~/Code/cells | Active |
