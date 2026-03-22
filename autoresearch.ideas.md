# Autoresearch Ideas

## Completed packages
- **atoms**: 98.1% (done — remaining 8 lines are coverage quirks)
- **engine**: 92.5% (132 miss — mostly combine/discover in vertex_reader)
- **store**: 99.6% (1 miss — effectively done)

## Current: lang 93.3% (58 miss)
- loader.py: 20 miss (boundary edge cases, observer grants, source blocks)
- population.py: 29 miss (list_file_header, eq/repr, template resolution)
- validator.py: 4 miss (project on non-dict, validate_loop_file, validate_vertex_file, shape eq)
- ast.py: 3 miss (frozen init positional args, frozen eq AttributeError)
- errors.py: 1 miss (Location eq same-type comparison)
- __init__.py: 1 miss (lazy import)

### Loader remaining (20 miss)
- L71: _require_arg missing arg (need a node with missing required arg)
- L80-83: _node_map helper (branch coverage — needs > 0 nodes)
- L189: where exists default op
- L194,199: where in/not_in empty values
- L328-342: boundary block edges (run clause, children, no trigger)
- L426,445,536: unknown template/source/sources-mode blocks
- L608,610: observer grant validation

### Population remaining (29 miss)
- list_file_header (8 miss)
- eq/repr/setattr/delattr for population types (10 miss)
- template resolution edges (4 miss)
- detect_indent (2 miss)
- read_population edge (1 miss)

## Future packages
- **loops app**: 59.9% (1,878 miss) — massive opportunity but very large
- **tasks app**: unknown — may have broken tests (CliContext.zoom)
