# Spec-Driven Data Contracts

This document captures the conceptual foundation for the spec-driven approach used in this project.

## The Thesis

We're not doing "config-driven UI" — we're doing **spec-driven data contracts** where UI rendering is a convention layer on top of projected state.

```
Event Spec → Fold Ops → State Spec → Render Convention → UI
     ↑                        ↑
     └── input contract       └── derived contract
```

The spec declares *what data looks like* and *how it transforms*. The renderer just interprets state shapes.

## Three Layers of Declaration

### 1. Event Spec (Input Contract)

What events look like when they arrive:

```kdl
event "container.status" {
    container "str"
    service "str"
    state "str"
    health "str?"      // optional
    healthy "bool"
}
```

This is a schema for inbound data. Events that don't match should be rejected or logged.

### 2. State Spec (Derived Contract)

What the projected state looks like:

```kdl
state {
    containers "dict"
    last_update "datetime?"
}
```

State is always derivable from events via fold ops. The spec declares the shape, the runtime initializes from types.

### 3. Fold Ops (Transformation Rules)

How events become state:

```kdl
fold {
    upsert "containers" key="container"
    latest "last_update"
}
```

Declarative transformations. No custom code per projection.

## Why KDL

| Need | KDL Feature |
|------|-------------|
| Readable nested structures | Node-based syntax |
| Type annotations | Arguments + properties |
| Formal validation | Schema spec (to implement) |
| Queryable | KDL Query Language (CSS-like) |
| Hot-reload | Text files, easy to watch |

KDL hits a sweet spot: more structured than YAML, less verbose than XML, readable by humans.

## Comparison to Existing Patterns

### vs Textual CSS

Textual separates *appearance* from *behavior* via CSS files:
```
Python (widget tree + logic) + TCSS (styling) → UI
```

We separate *data contracts* from *rendering*:
```
KDL (event + state + fold) + Python (conventions) → UI
```

Textual's CSS says "how it looks". Our specs say "what shape data has and how it transforms".

### vs Kubernetes CRDs

Kubernetes declares resource shapes and desired state:
```yaml
apiVersion: v1
kind: Pod
spec:
  containers:
    - name: web
      image: nginx
```

Controllers reconcile actual → desired.

We declare event shapes and fold semantics:
```kdl
projection "vm-health" {
    event "container.status" { ... }
    state { containers "dict" }
    fold { upsert "containers" key="container" }
}
```

Projections fold events → state. Similar pattern, different domain.

### vs Config-Driven UI

Typical config-driven UI:
```json
{
  "type": "form",
  "fields": [
    {"name": "email", "type": "text", "required": true}
  ]
}
```

Config describes *UI structure*. Renderer builds components.

Our specs describe *data structure*. Renderer infers UI from state shapes:
- `dict` → table
- `list` → scrolling list
- `set` → tag row

The UI is derived, not declared.

## The Edit-and-See Pattern

```
1. Edit .projection.kdl file
2. SpecWatcher detects mtime change
3. Re-parse spec
4. Replace SpecProjection instances
5. Next render picks up new structure
```

No restart. Change the contract, see the result.

This works because:
- Specs are pure data (no code to reload)
- Projections are stateless transforms (can rebuild from spec)
- Rendering is convention-based (adapts to state shape)

## Validation Strategy

Specs declare contracts. Runtime should enforce them.

### Event Validation

Before fold, check event against EventSpec:
- Required fields present
- Types match (str, bool, int, etc.)
- Reject or log violations

### State Invariants

After fold, state should match StateSpec:
- Fields have correct types
- Optional fields are null or correct type

### Implementation Path

1. **Immediate**: Validate in `SpecProjection.consume()` before fold
2. **Future**: KDL Schema files + Python validator
3. **Optional**: Generate Python dataclasses from specs

## Principles

1. **Spec is source of truth** — code interprets specs, not the reverse
2. **Projection is the primitive** — all derived state comes from folding events
3. **Rendering is convention** — state shape implies UI, no custom code per projection
4. **Validation at boundaries** — check events on ingest, not deep in fold logic
5. **Hot-reload by default** — specs are files, files can be watched

## References

- [KDL Document Language](https://kdl.dev/)
- [KDL Schema Spec](https://github.com/kdl-org/kdl/blob/main/SCHEMA-SPEC.md)
- [Spec-Driven Development (InfoQ)](https://www.infoq.com/articles/spec-driven-development/)
- [Textual CSS](https://textual.textualize.io/guide/CSS/)
- [Declarative Config Overview (KCL)](https://www.kcl-lang.io/blog/2022-declarative-config-overview)
