# artifact

*A durable output produced by a CLI run.*

## What It Represents

An artifact is a reference to something persistent — something that survives the process boundary and can be acted on after the command exits:

- A file path
- A URL
- A handle or identifier
- A reference to a deployed resource

Examples:
- A generated config file
- A backup archive
- A diff file
- A report URL
- A deployed resource ID
- A log bundle path

**If it survives the process boundary, it's an artifact.**

## What It Is NOT

Most CLIs treat artifacts implicitly:
- "wrote file X"
- "see output above"
- "check logs"

That information is:
- Buried in text
- Unstructured
- Unrecoverable for automation
- Invisible to JSON output

By modeling artifact as a fact, you say: *This run produced something of lasting value.*

That's a semantic statement, not a formatting choice.

### Why Not Just `log`?

You could log: `"Wrote /tmp/plan.json"`

But then:
- Renderers can't reliably extract the path
- Automation can't act on it
- JSON output loses it
- UIs can't hyperlink it
- Tests can't assert it

Artifact gives you:
- A handle
- A lifecycle marker
- A durable reference

### Why Not `Result.data`?

Two reasons:

**1. Timing**

Artifacts often appear before the command ends:

```
progress → artifact → progress → artifact → result
```

Streaming matters.

**2. Multiplicity**

A run can produce many artifacts, incrementally, from different phases. Artifacts are events in the timeline, not just summary data.

## The Symmetry

The three non-log kinds form a complete picture:

| Kind | What it captures |
|------|------------------|
| `input` | A decision occurred |
| `progress` | Work advanced |
| `artifact` | Something durable exists |

Together they describe:
- **Why** something happened (input)
- **How** it unfolded (progress)
- **What** it produced (artifact)

## What Artifact Events Look Like

**File artifact:**
```python
Event.artifact("file", "Deployment plan", path="/tmp/plan.json")
```

**URL artifact:**
```python
Event.artifact("url", "Backup archive", href="s3://backups/db-2026-01-02.tar.gz")
```

**Resource artifact:**
```python
Event.artifact("resource", "Service instance", id="svc-abc123")
```

Same primitive. Different meaning via `data`.

## The `type` Requirement

The `type` parameter is **required** as the first positional argument to `Event.artifact()`. This enforces the convention that artifacts need a type for consumers to discriminate between them:

```python
Event.artifact("file", path="/tmp/report.pdf")           # type only, no message
Event.artifact("stack_status", "All healthy", count=3)   # type + message + data
```

The type ends up in `event.data["type"]`, enabling emitters to handle different artifacts appropriately. Use `event.topic` for filtering: an artifact with type `"file"` has topic `"artifact:file"`.

```python
def emit(self, event: Event) -> None:
    if event.kind != "artifact":
        return

    artifact_type = event.data.get("type")
    # or use event.topic == "artifact:file"

    if artifact_type == "file":
        self._render_file(event.data.get("path"))
    elif artifact_type == "url":
        self._render_link(event.data.get("href"))
    elif artifact_type == "stack_status":
        self._render_stack(event.data)
```

### Standard Types

facts doesn't mandate types, but these are conventional:

| Type | Typical Fields | Meaning |
|------|---------------|---------|
| `file` | `path` | Local file path |
| `url` | `href` | Web URL |
| `resource` | `id` | Cloud/service resource |

### Domain-Specific Types

Extend with your own types for domain-specific artifacts:

```python
# Infrastructure status
Event.artifact("stack_status", stack="media", healthy=True, services=["plex", "sonarr"])

# Build output
Event.artifact("build_artifact", format="docker", tag="myapp:1.2.3")

# Test result
Event.artifact("test_report", passed=42, failed=0, path="/tmp/report.html")
```

### Document Your Types

Domain-specific types form a contract between your domain code and your emitters. Document them:

```python
"""
Event Shapes for myapp:

artifact(type="deployment")
    - environment: str ("prod", "staging")
    - version: str
    - url: str (deployed URL)

artifact(type="backup")
    - database: str
    - size_bytes: int
    - path: str
"""
```

This documentation helps anyone writing an emitter for your events.

## What It Enables

### 1. UX Upgrades Without Domain Changes

A Rich renderer can:
- Print artifacts in a dedicated section
- Hyperlink file paths or URLs
- Collapse/expand artifact lists
- Add icons by type

A Plain renderer can:
- Print paths only

A JSON renderer can:
- Emit structured artifact lists

The command code doesn't change.

### 2. Automation Glue

Automation can:
- Watch for artifact events
- Copy files
- Upload outputs
- Notify users
- Trigger follow-on tasks

All without parsing text.

### 3. Replay & Audit

A run transcript can answer:
- What did this command produce?
- Where is it?
- What type of thing is it?

Critical for backups, deploys, compliance, debugging.

### 4. Product-Like CLI Behavior

CLIs feel like products when they:
- Produce named outputs
- Reference them consistently
- Let users act on them

Artifacts are the bridge from "command printed stuff" to "command created something."

## Artifact in Non-Interactive Mode

Just like progress and input, artifacts still exist even if nothing is rendered.

In CI, artifacts may be the *only* thing you care about — logs are noise. Artifact-as-fact keeps that clean.

## Boundaries

To keep the contract clean:

- ❌ No file creation logic
- ❌ No uploads
- ❌ No deletion
- ❌ No path normalization
- ❌ No assumptions about lifecycle

It only says: *"This thing exists because of this run."*

The domain creates the artifact. facts records that it exists.

## Why It Earns Its Place

Ask: *Can a renderer or automation reliably detect this without a dedicated primitive?*

For artifacts: **No.**

You can't reliably parse "Wrote /tmp/foo.json" from log output. You need structured data.

So artifact earns its slot.
