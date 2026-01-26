# input

*An input interaction occurred.*

## Recording, Not Prompting

**facts records that an input event happened. It does not prompt for input.**

This is intentional separation of concerns:
- **Prompting** (asking the question, getting the answer) → Your CLI framework (Click, Typer, Rich Prompt)
- **Recording** (noting that it happened) → facts

This means you write the prompt logic separately, then emit an input event:

```python
# Your prompt logic (not facts' job)
response = typer.confirm("Delete 47 files?")

# Record that it happened (facts' job)
emitter.emit(Event.input("Delete 47 files?", response=response))
```

**Why this separation?**
1. facts is not a prompting library — that would duplicate Click, Typer, Rich, etc.
2. facts describes facts after they happen, not instructions for what to do
3. The `input` event enables audit, replay, and debugging without being coupled to any specific prompt UI

## What It Represents

A record that a human decision point existed and was resolved:

```python
Event(
    kind="input",
    message="Continue despite version mismatch?",
    data={
        "response": "yes",
        "context": "version_check"
    }
)
```

This event says:
- A question existed
- A human decision was required
- A specific response was given

Nothing more.

## What It Is NOT

| Allowed | Forbidden |
|---------|-----------|
| Record question asked | Define how to ask |
| Record response given | Validate response |
| Record metadata (source, policy) | Apply policy |
| Record that interaction occurred | Control whether it occurs |

Hard boundaries:

- ❌ No `prompt()` calls
- ❌ No blocking
- ❌ No validation rules
- ❌ No defaulting logic
- ❌ No branching decisions

The moment `input` gains any agency, it becomes a prompt library. That's not the point.

## Temporal Contract

**Input events are emitted after the interaction completes, never before.**

The CLI framework (Click, Cappa, Rich Prompt, etc.) handles the actual prompting. The domain logic handles branching. facts just records: "this interaction occurred."

## What It Enables

### 1. Auditing & Replay

Answer questions that are typically invisible:
- What confirmations were required?
- Which risky actions were manually approved?
- Was this deploy forced or consented?

A future tool could replay a run in "dry replay" mode, showing every decision point and where humans intervened.

### 2. Renderer-Level UX Decisions

Because input is recorded after the fact, renderers choose presentation:

| Renderer | Behavior |
|----------|----------|
| Rich | Shows confirmation panel, maybe collapses unless verbose |
| JSON | Includes in an `inputs` array |
| Plain | Prints a single line |
| Audit | Extracts only input events |

Domain logic never changes.

### 3. Non-Interactive Policy Handling

If the system is non-interactive, the absence of input is also a fact:

```python
Event(
    kind="input",
    message="Continue despite version mismatch?",
    data={
        "response": "skipped",
        "reason": "non-interactive",
        "policy": "fail-safe"
    }
)
```

Now:
- Automation runs don't hang
- Results are still explainable
- Policies are transparent

### 4. "Why Did This Happen?" Debugging

Imagine reading a CI log: "Deploy failed."

With input events, you can see:
- A confirmation was required
- Default was "no"
- User wasn't present

That's the difference between opaque and understandable tooling.

### 5. Diff Between Runs

Two runs, same code, different outcomes. Compare event streams. Find the divergent input event. Done.

### 6. Test Fixtures for Decision Trees

Record a real run's input events, replay them in tests. No mocking prompt libraries.

## Why It Earns Its Place

Recall the minimality rule:

> Only add a primitive if a renderer capability cannot be reliably implemented without it.

Without an `input` primitive:
- Confirmations disappear from structured output
- JSON mode loses critical context
- Audit trails are incomplete
- Replay becomes guesswork

So `input` earns its place—even in a minimal v1.

## Examples

**Simple confirmation:**
```python
Event(
    kind="input",
    message="Delete 47 files?",
    data={"response": "yes"}
)
```

**With context:**
```python
Event(
    kind="input",
    message="Continue despite version mismatch?",
    data={
        "response": "yes",
        "expected_version": "2.0.0",
        "actual_version": "1.8.3",
        "context": "dependency_check"
    }
)
```

**Non-interactive skip:**
```python
Event(
    kind="input",
    message="Approve production deploy?",
    data={
        "response": "skipped",
        "reason": "non-interactive",
        "policy": "require-explicit-approval",
        "outcome": "aborted"
    }
)
```

**Sensitive input (redacted):**
```python
Event(
    kind="input",
    message="Enter API token",
    data={
        "response": "[REDACTED]",
        "source": "stdin"
    }
)
```

Redaction is the domain's responsibility, not facts'.
