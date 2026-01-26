# shapes — Handoff

## 2026-01-26
Shape.apply() fold engine: `engine.py` with fold closures (latest, count,
sum, collect, upsert) built from Fold descriptors. Shape.apply(state, payload)
is pure dict->dict, no cross-lib imports. 17 tests.

First concrete shape: container-health. Upsert by container name + count
observations. Input facets: container, image, status, health. State facets:
containers (dict), count (int). Validated end-to-end with Fact and Projection.

## Open
- **KDL parser**: Defer until declarative path matures.
- **Validation/coercion**: Defer until apply() is in use — likely a boundary concern.
