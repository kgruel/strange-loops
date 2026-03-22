# Autoresearch Ideas: atoms Coverage Efficiency

## Current state: 89.5% line, 83.5% branch — 74 lines uncovered

## Uncovered lines by file (priority order)

### parse.py — 31 miss (biggest opportunity)
- L266: Skip with `field` mode on non-dict value
- L291: Split on non-string value
- L308: Pick on non-list value
- L323: Rename on non-list value  
- L338: Transform on non-dict value
- L345: Transform field not in dict
- L384: Coerce on non-dict value
- L390: Coerce field missing from dict
- L452,514-516: _apply_where/explode/project edge cases
- Several lines in run_parse_many stream pipeline dispatch
- Key insight: most misses are type-guard "return None" branches on non-dict/non-list inputs. 
  A single parametrized test with wrong-type inputs could cover many.

### source.py — 19 miss
- L91,103-113: _emit_lines, _emit_json — async process-based emission (needs subprocess mock)
- L133-134,162: _emit_json JSON parse paths
- More subprocess/async boundaries
- Harder to test efficiently — async + subprocess mocking

### fact.py — 8 miss
- L64: __class_getitem__ (Fact[str] syntax)
- L81-82: __setattr__ raising FrozenInstanceError
- L86: __delattr__ raising FrozenInstanceError
- L93-94,97,102: __eq__ NotImplemented, __hash__ with unhashable payload
- All cheap to test — pure data class protocol methods

### types.py — 7 miss
- L76,87,90: coerce_value edge cases (int-from-float, bool coercion)
- L104,110-112: type_matches for set/list/datetime/unknown types
- Cheap parametrized tests

### engine.py — 6 miss
- L79-82,87: fold function builder edge cases (Avg, Window folds)
- L216: Unknown fold type ValueError
- Moderate — need fold op construction

### sequential.py — 2 miss
- L41,46: kind/command properties when sources list is empty
- Trivial to test

### __init__.py — 1 miss
- L130: lazy import AttributeError for unknown attribute
- Trivial

## Strategy
1. Start with fact.py + types.py + sequential.py + __init__.py — trivial wins, ~18 lines
2. Then parse.py type-guard branches — one parametrized test covers many
3. Then engine.py fold edges
4. source.py last — async subprocess mocking is expensive in LOC

## Compression opportunities
- test_parse.py is 694 LOC — look for repeated setup patterns
- test_source.py is 521 LOC — fixture extraction potential
- test_shapes.py is 505 LOC — may overlap with test_fact.py + test_parse.py
