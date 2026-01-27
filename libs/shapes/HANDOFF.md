# shapes — Handoff

## 2026-01-27
Added `Boundary(kind: str, reset: bool)` frozen dataclass in `boundary.py`.
Added `boundary: Boundary | None = None` field to Shape. Boundary declares which
fact kind completes a fold cycle and whether state resets or carries. Purely
declarative — Shape.apply() does not check boundary; the fold engine checks it
externally. A Shape with no boundary folds continuously (no cycle, no Tick).
12 new tests across 2 test classes (TestBoundary, TestShapeBoundary). 72 total.

## 2026-01-26
Shape.apply() fold engine: `engine.py` with fold closures (latest, count,
sum, collect, upsert) built from Fold descriptors. Shape.apply(state, payload)
is pure dict->dict, no cross-lib imports. 58 tests across 6 test classes.

First concrete shape: container-health. Upsert by container name + count
observations. Input facets: container, image, status, health. State facets:
containers (dict), count (int). Validated end-to-end with Fact and Projection.

Added `py.typed` marker and `.gitignore` (previously had neither).

## Open
- **KDL parser**: Defer until declarative path matures.
- **Validation/coercion**: Defer until apply() is in use — likely a boundary concern.
