# Rung 06 — The Fact Graph: refs & cites

> **What you'll learn:** How fold keys make facts findable, how `ref=` links connect facts into a graph, how entity references pin ULIDs, and how `sl cite` bumps inbound weight on prior work.
> **Prerequisites:** [Rung 05 — The loops CLI: emit, read, fold](05-the-loops-cli-basics.md)
> **Time:** ~15 min

A fact store is a log. A fact *graph* is a log where emitters were disciplined about naming, linking, and attribution — and the structure that emerges enables navigation: "what does this build on?", "what's the lifecycle of this thread?", "what nodes did this session touch?"

The discipline has three parts: fold keys, outbound `ref=` links, and `sl cite` for inbound attribution.

---

## Fold keys

Every kind has a designated fold key — the payload field that determines where a fact lands in the accumulated state dict. Missing it stores the fact (append-only invariant), but the fact won't fold and will never be visible in `sl read` state.

| Kind | Fold key | Example |
|------|----------|---------|
| `decision` | `topic=` | `topic=auth/jwt` |
| `thread` | `name=` | `name=auth-refactor` |
| `task` | `name=` | `name=fix-null-check` |
| `friction` | `name=` | `name=stale-cli-install` |
| `hypothesis` | `name=` | `name=jwt-latency-acceptable` |
| `plan` | `name=` | `name=q2-refactor` |
| `observation` | `topic=` | `topic=design/simplification` |
| `cite` | — | refs only; no fold key |

**Wrong:**

```bash
# Missing fold key — fact stored but orphaned (never folds, never visible in read)
sl emit project decision "Use JWT over sessions"
```

**Correct:**

```bash
# topic= present — fact folds into decision["auth/jwt"]
sl emit project decision topic=auth/jwt "Use JWT over sessions"
```

The CLI emits a `WARN:` line when the fold key is missing (unless `--quiet`). With `--strict` it refuses the emit outright.

### Topic prefixes earn their namespace

The fold key value is also a namespace handle. Decisions under `auth/` cluster together; `design/` clusters separately. Use existing prefixes before adding new ones — ungrouped sprawl obscures the graph.

Existing namespaces in this repo: `design/` `architecture/` `paradigm/` `rendering/` `atoms/` `workflow/` `practice/` `implementation/` `test/` `ops/` `pattern/` `peer/` `session/`

---

## Outbound links: `ref=`

`ref=kind:key` declares outbound provenance — this fact was informed by, or builds on, that prior fact.

```bash
sl emit project decision topic=auth/strategy \
    ref=thread:auth-refactor \
    "JWT with short-lived tokens is the path forward"
```

The `ref=` value format is `kind:fold_key_value`. Multiple refs accumulate — they don't overwrite each other:

```bash
# Two separate ref= flags — both are preserved
sl emit project decision topic=auth/strategy \
    ref=decision:auth/jwt \
    ref=thread:auth-refactor \
    "..."

# Comma form — equivalent
sl emit project decision topic=auth/strategy \
    ref=decision:auth/jwt,thread:auth-refactor \
    "..."
```

Both forms produce `ref: "decision:auth/jwt,thread:auth-refactor"` in the payload.

Refs are stored as payload strings — they don't resolve ULIDs at emit time. For ULID-pinned provenance, use entity references (next section).

---

## Entity references: auto-resolved ULIDs

When a payload value matches the pattern `kind/fold_key_value` — and `kind` is a declared kind in the vertex — the CLI resolves it to the most recent fact ULID for that entity and adds a sibling `{field}_ref` field:

```bash
sl emit project task \
    name=fix-null-check \
    thread=thread/auth-refactor \
    "Fix the null check in auth middleware"
```

Because `thread` is declared on the vertex, `thread/auth-refactor` is recognized as an entity address. The CLI looks up the latest ULID for `thread` where `name=auth-refactor` and emits:

```
payload: {
    name: "fix-null-check",
    thread: "thread/auth-refactor",          # original value preserved
    thread_ref: "01JXABCDEF...",             # pinned ULID (provenance anchor)
    message: "Fix the null check...",
}
```

The original field is preserved (navigable address). The `_ref` sibling pins the exact fact. If the address looks like a declared kind but no matching entity is found, the CLI emits a `WARN: ref '...' did not resolve — dropped` line.

**The emitted kind's own fold key is excluded from the scan.** Namespaced fold key values like `topic=pattern/foo` won't be misread as entity references to a `pattern` kind, even if `pattern` is declared in the topology.

---

## Inbound attribution: `sl cite`

`sl cite` bumps the inbound weight on prior work — "this turn was informed by these facts, no new claim."

```bash
sl cite decision:auth/jwt thread:auth-refactor -m "revisiting auth strategy"
```

`cite` dissolves into an emit with `kind=cite`. The refs become the payload's `ref` field:

```bash
# These are equivalent
sl cite REF1 REF2 -m "context"
sl emit project cite ref=REF1,REF2 message="context"
```

`cite` has no fold key — it doesn't accumulate into a state dict. Its value is the inbound signal: over time, facts that get cited often are findable as load-bearing nodes in the graph.

Flags:

| Flag | Effect |
|------|--------|
| `-m "text"` | Context message (optional) |
| `--context NAME` | Named context label |
| `--dry-run` | Parse without storing |

---

## Emit-with-graph-fidelity

The combination of these three practices — fold keys, outbound refs, and cite — is the discipline that turns a flat log into a navigable graph:

1. **Topic prefix** picks the cluster. Use an existing namespace; dissolve before adding.
2. **Stable name** makes the fact citable. Choose like an API name, not a commit message. `auth/jwt` is stable; `thoughts-on-auth` isn't.
3. **`ref=`** links outbound to prior work that informed this one.
4. **`sl cite`** bumps inbound count on prior work at the moment of use — not at session end.
5. **`_ref` siblings** pin exact ULIDs for provenance when cross-kind addressing.

Salience emerges from this discipline. When the graph clusters interestingly under `sl read project --refs`, it's because emission was structured enough to make clustering visible. The scan doesn't create the graph — the discipline does.

### The loop: build → cite → decision

```bash
# 1. Open a thread when a question lands
sl emit project thread name=auth-refactor status=open "Should we refactor auth?"

# 2. Design against it (the thread is the prior work)
sl emit project decision topic=auth/strategy \
    ref=thread:auth-refactor \
    "JWT with short expiry; refresh tokens rotated on use"

# 3. When prior work informs a new session — cite it before adding claims
sl cite decision:auth/strategy -m "still holds; JWT strategy in scope"

# 4. When the thread resolves — re-emit (don't delete; append-only)
sl emit project thread name=auth-refactor status=resolved \
    ref=decision:auth/strategy \
    "Resolved by JWT strategy decision"
```

Re-emitting a thread with `status=resolved` overwrites the prior value in the fold state (latest-per-key semantics) while preserving the full history in the fact log.

---

## Read-path navigation

Different questions need different traversal modes:

| Question | Command |
|----------|---------|
| What's in this namespace? | `sl read project --kind decision --key auth/` |
| What does this topic build on? | `sl read project --refs` |
| What's the lifecycle of this thread? | `sl read project --kind thread --facts` |
| What friction is open? | `sl read project --kind friction --plain` |
| What changed recently? | `sl read project --since 7d` |

`--key` scopes a read to a specific fold key prefix — the workhorse for entering a domain.

---

## What you've learned

- Every kind has a fold key; missing it orphans the fact (stored, never folds).
- Topic prefixes create navigable clusters — use existing ones before adding.
- `ref=kind:key` declares outbound provenance; multiple refs accumulate (no overwrite).
- Entity references (`kind/fold_key_value` in a payload field) auto-resolve to `{field}_ref=<ULID>` sibling; original value preserved.
- `sl cite REF1 REF2 -m "..."` bumps inbound weight on prior work at the moment of use.
- The graph is earned by discipline at emit time, not by tooling at read time.

---

**Next:** [Rung 07 — Reading and Lenses](07-reading-and-lenses.md)
**See also:** [CLI cheatsheet](../CLI-CHEATSHEET.md) · [guide index](README.md)
