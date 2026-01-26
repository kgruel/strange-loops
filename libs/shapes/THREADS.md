# THREADS — shapes

## Shape.apply()
CLAUDE.md mentions `Shape (facets + folds + apply)` but no apply method
exists on Shape. Fold application currently lives in ShapeProjection in
experiments. Decision: does Shape get an `apply(state, event) -> state`
method, or does application stay in the experiments bridge?

Argument for: Shape becomes self-contained, any consumer can fold.
Argument against: Shape stays pure contract (declaration), application
is infrastructure (ticks domain).

## KDL parser
Shapes can be defined programmatically (Python API) or declaratively
(KDL specs). The KDL parser currently lives in experiments. Could
become a `shapes-kdl` package or move into shapes with an optional
dependency. Defer until the declarative path matures.

## Validation and coercion
Shape has type utilities (coerce_value, type_matches, initial_value)
but no validate/coerce methods on Shape itself. These live in types.py
as standalone functions. Consider whether Shape should expose
`shape.validate(event)` and `shape.coerce(event)` directly.
