# THREADS — shapes

## [resolved] Shape.apply()
Shape now has `apply(state: dict, payload: dict) -> dict`. Fold engine
lives in `engine.py` — closures built from Fold descriptors, pure dict
manipulation. Shape is self-contained: declare + execute. The
experiments bridge (ShapeProjection) dissolves into a one-liner:
`Projection(initial=shape.initial_state(), fold=shape.apply)`.

## KDL parser
Shapes can be defined programmatically (Python API) or declaratively
(KDL specs). The KDL parser currently lives in experiments. Could
become a `shapes-kdl` package or move into shapes with an optional
dependency. Defer until the declarative path matures.

## Validation and coercion
Shape has type utilities (coerce_value, type_matches, initial_value)
but no validate/coerce methods on Shape itself. These live in types.py
as standalone functions. Defer until Shape.apply() is in use and we
see where validation naturally fits in the fold pipeline (likely a
boundary concern — before apply, not during).
