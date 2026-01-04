# ProgressTree Pattern

*Hierarchical progress tracking for GitHub Actions-style workflows.*

## The Problem

ev's progress events are flat measurements:

```python
Event.progress("Downloading", current=37, total=100)
```

But some workflows have nested structure:

```
✓ Deploy stack: media
  ✓ Decrypt secrets (5/5)
  → Sync files (37/100)
  ○ Restart services (pending)
```

How do you represent parent-child relationships in a renderer-agnostic way?

## Why ev Doesn't Include This

ev's design rule: "Only add a primitive if a renderer capability cannot be reliably implemented without it."

Most CLIs don't need hierarchy. Adding `id`/`parent_id` to ev's recommended fields would bloat the simple case (90% of progress events) to support the complex case (10%).

## The Pattern

Apps that need hierarchy add `id` and `parent_id` to `Event.data`:

```python
# Top-level task
Event.progress("Deploy stack: media", id="deploy", status="running")

# Child tasks
Event.progress("Decrypt secrets", id="decrypt", parent_id="deploy", current=5, total=5, status="ok")
Event.progress("Sync files", id="sync", parent_id="deploy", current=37, total=100, status="running")
Event.progress("Restart services", id="restart", parent_id="deploy", status="pending")
```

These are plain ev events — any emitter can serialize them. But a hierarchy-aware renderer can reconstruct the tree.

## ProgressTree Utility

ev-toolkit provides a `ProgressTree` that tracks hierarchy state:

```python
from ev_toolkit import ProgressTree

tree = ProgressTree()

# Update from events
tree.update(Event.progress("Deploy", id="deploy", status="running"))
tree.update(Event.progress("Decrypt", id="decrypt", parent_id="deploy", status="ok"))
tree.update(Event.progress("Sync", id="sync", parent_id="deploy", current=37, total=100))

# Query structure
root = tree.root("deploy")
children = tree.children("deploy")  # ["decrypt", "sync"]

# Get node state
node = tree.get("sync")
# ProgressNode(id="sync", parent_id="deploy", message="Sync", current=37, total=100, status="running")
```

## Renderer Integration

A Rich-based renderer might use `ProgressTree` like this:

```python
class TreeEmitter:
    def __init__(self):
        self._tree = ProgressTree()

    def emit(self, event: Event) -> None:
        if event.kind == "progress" and "id" in event.data:
            self._tree.update(event)
            self._render_tree()

    def _render_tree(self) -> None:
        # Build Rich Tree from ProgressTree state
        for root_id in self._tree.roots():
            self._render_node(root_id, indent=0)

    def _render_node(self, node_id: str, indent: int) -> None:
        node = self._tree.get(node_id)
        icon = {"ok": "✓", "running": "→", "pending": "○", "error": "✗"}[node.status]
        # ... render with Rich
        for child_id in self._tree.children(node_id):
            self._render_node(child_id, indent + 1)
```

## Data Shape

Events with hierarchy should include:

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `id` | str | Yes | Unique identifier for this task |
| `parent_id` | str | No | Parent task id (omit for root tasks) |
| `status` | str | Yes | "pending", "running", "ok", "error" |
| `current` | int/float | No | Progress numerator |
| `total` | int/float | No | Progress denominator |

## When to Use This

Use hierarchical progress when:
- You have nested operations (deploy → decrypt → sync → restart)
- You want tree-style display (GitHub Actions, Docker Compose)
- You're building a dashboard or TUI with task trees

Don't use it when:
- Simple linear progress is sufficient
- You're emitting many high-frequency updates (overhead)
- Your renderer doesn't support tree display

## Alternatives

If you don't want the `ProgressTree` utility:

1. **Naming convention**: Use dotted ids (`deploy.decrypt`, `deploy.sync`) and parse in renderer
2. **Temporal inference**: Assume events between "start" and "end" are children
3. **App-layer state**: Track hierarchy in your app, emit flat events

The `ProgressTree` pattern is opt-in. ev's core stays minimal.
