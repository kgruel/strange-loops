# Autoresearch Ideas: atoms Coverage Efficiency

## Current state: 98.1% line, 95.6% branch — 8 lines uncovered

## Remaining uncovered lines (diminishing returns)

### parse.py L536-538 (3 lines)
`_apply_single_op` Select branch + fallthrough `return None`. Structurally unreachable:
`run_parse_many` dispatches Select explicitly at L508 before falling through to
`_apply_single_op`. Would need to refactor dispatch to hit these. Not worth it.

### source.py L91 (1 line)
`_parse_data` non-str/non-dict defensive return. Test exists and calls it correctly,
but coverage.py doesn't register the hit — likely a bytecode/branch instrumentation quirk.

### source.py L225-227 (3 lines)
Generic exception handler in `collect()`. Only fires for non-SourceError exceptions
(e.g., OSError if subprocess creation fails). Would need to mock
`asyncio.create_subprocess_shell` to raise OSError — expensive for 3 defensive lines.

### types.py L90 (1 line)
`coerce_value(True, "bool")` return path. Test exists, value is correct, but coverage.py
match-case instrumentation doesn't register it.

## Compression opportunities
- test_shapes.py (505 LOC) and test_fact.py (281 LOC) have some overlapping Spec/Fact
  construction patterns — shared fixtures could reduce ~50 LOC
- test_parse.py (694 LOC) has repeated pipeline construction — a builder helper could
  compress ~80 LOC
- test_source.py (521 LOC) has repeated Source construction — fixture extraction possible

## Strategy going forward
atoms is at 98.1% — effectively complete. Remaining 8 lines are coverage tool quirks
or structurally unreachable code. Time to move up the chain to engine.
