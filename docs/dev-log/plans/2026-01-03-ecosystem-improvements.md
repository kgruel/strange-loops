---
status: completed
updated: 2026-01-03
---

# ev Ecosystem Improvements

Coordinated improvements across ev core and ev-toolkit, extracted from practical usage analysis of hlab.

## Deliverables (Revised)

| # | Item | Repo | Type | Priority |
|---|------|------|------|----------|
| 1 | CommandContext pattern documentation | ev | docs/patterns | High |
| 2 | Test assertion helpers | ev-toolkit | recipes | High |
| 3 | Uniform context protocol | ev | core | Medium |
| 4 | Generic signal fallback in Plain/Rich | ev | emitters | Medium |

**Dropped:** BatchRenderEmitter — already exists as `BatchCollector` in ev-toolkit recipes.

## Origin

These emerged from deep analysis of:
- `ev` core architecture
- `hlab` practical implementation (pain points, workarounds)
- `ev-toolkit` existing patterns

## Key Decisions (from discussion)

### Signal Render Hooks: Manual, No Registry

**Decision:** Keep signal rendering manual. No registry in ev core.

**Rationale:**
- `log_signal` is telemetry, not authority
- Telemetry is allowed to be partially rendered, filtered, or ignored
- A registry becomes framework surface area and quasi-API to support
- Friction is a feature—forces thinking about whether a signal matters

**Policy codified:**
- JSONEmitter: always includes signals (no special casing needed)
- Plain/Rich: generic signal fallback + optional hand-written "pretty" rendering

### TypedDict for Signal Schemas: Experiment in hlab

**Decision:** Don't bake into ev core. Document as optional pattern.

**Rationale:**
- TypedDicts help with many contributors, lots of signals, long-lived code
- Making it first-class creates coupling pressure ("do I import schemas from ev?")
- Better as internal hlab experiment, documented pattern in ev

**Path forward:**
- ev stays schema-agnostic
- hlab defines TypedDicts for its own signals
- ev docs include pattern page: "TypedDict schemas for signals (optional)"

### Uniform Context Protocol: Worth It

**Decision:** Yes, add `__enter__/__exit__` to all emitters.

**Rationale:**
- Simplifies everything without adding machinery
- Unlocks uniform command plumbing
- Makes tee/file/live composition painless
- `with ctx.emitter() as e:` is a visible pattern, not hidden magic

---

## Pre-Implementation Review

### Philosophy Alignment Check

**ev's core rule:** Only add a primitive if a renderer capability cannot be reliably implemented without it.

| Item | Adds primitives? | Adds machinery? | Verdict |
|------|------------------|-----------------|---------|
| CommandContext docs | No | No (docs only) | ✓ Safe |
| Test helpers | No | No (recipes) | ✓ Safe |
| Context protocol | No (no-op methods) | Minimal | ✓ Safe |
| Signal fallback | No | Render behavior | ✓ Safe |

**Core contract unchanged:** No new Event kinds, no new Result fields, Emitter protocol shape preserved.

### Item Scrutiny

**CommandContext docs:** Risk of scope creep into "framework" territory. Mitigated by framing as "integration pattern" not "the way to build CLIs." Lives alongside existing patterns (domain-emitters, live-emitter).

**Test helpers:** Weakest addition—solves pain for user base of one (hlab). Justified because: recipes are explicitly copy-paste territory, trivial maintenance burden (~25 lines), if unused they rot harmlessly.

**Context protocol:** Strongest addition. Technically a protocol change, but:
- Duck typing means existing emitters still work
- v0.4.0 is the right time for such changes
- Methods are no-ops (6 lines each)
- Win is significant: universal `with emitter:`, sane composition

**Signal fallback:** Medium risk—format matters. Decision: minimal format `name key=value`. Signals inherit level, so debug signals filtered by verbosity anyway. Better than silent ignoring.

### Expendability Order (if forced to cut)

1. Test helpers (most speculative)
2. CommandContext docs (nice, not essential)
3. Signal fallback (real usability gap)
4. Context protocol (definitely keep—most impactful)

### Second-Order Effects

- Context protocol becomes expected way to use emitters → Good (more Pythonic)
- Signal fallback makes pretty handlers feel optional → Good (that's the goal)
- Test helpers set expectation for more utilities → "Recipes" framing handles this

### Verdict

Proceed. Plan aligns with ev's philosophy, solves real friction from hlab, carries low risk.

---

## Understand Phase

### 1. CommandContext Pattern (docs)

**What it is:** A single injection point that bundles config, emitter factories, exit code mapping. Discovered in hlab as the cleanest CLI→Operation boundary.

**Pattern shape:**
```python
class CommandContext:
    def __init__(self, config, mode, theme, verbosity): ...
    def require_stack(self, name) -> Stack: ...  # Resolution
    def emitter(self, **kw) -> Emitter: ...      # Factory
    def exit_code(self, result) -> int: ...      # Mapping
    def print_summary(self, result): ...         # Output
```

**Why document:** New CLI authors reinvent this. hlab proves it works.

**Location:** `docs/patterns/command-context.md`

### 2. Test Assertion Helpers (ev-toolkit recipe)

**Pain point:** Testing signal flows is verbose.

**Minimal set (v0):**
```python
def find_signals(emitter: ListEmitter, name: str) -> list[Event]:
    """Return all signals with given name."""

def assert_has_signal(emitter: ListEmitter, name: str, **expected_data) -> Event:
    """Assert at least one signal matches name and data. Returns first match."""

def last_signal(emitter: ListEmitter, name: str) -> Event | None:
    """Return most recent signal with name, or None."""

def assert_signal_count(emitter: ListEmitter, name: str, n: int) -> None:
    """Assert exactly n signals with given name."""
```

**Location:** `src/ev_toolkit/recipes.py` (new section)

### 3. Uniform Context Protocol (ev core)

**Change:** All emitters support `__enter__/__exit__` as no-ops by default.

**Affected files:**
- `src/ev/emitter.py` — Protocol gets `__enter__`, `__exit__` methods
- `src/ev/emitter.py` — ListEmitter, NullEmitter get no-op implementations
- `src/ev/emitters/json.py` — JsonEmitter gets no-op implementation
- `src/ev/emitters/plain.py` — PlainEmitter gets no-op implementation
- `src/ev/emitters/rich.py` — RichEmitter already has them (verify)
- `src/ev/emitters/tee.py` — FileEmitter, TeeEmitter get implementations

**TeeEmitter nuance:** Should manage nested contexts deterministically (call `__enter__` on all children, `__exit__` on all children).

### 4. Generic Signal Fallback in Plain/Rich

**Change:** Signals are never silently ignored. Unknown signals get generic rendering.

**Format:**
```
signal_name key1=value1 key2=value2
```

Example:
```
stack_status stack=media healthy=True
deploy.connected host=db.local
```

**Affected files:**
- `src/ev/emitters/plain.py` — Add signal fallback in `_format_event`
- `src/ev/emitters/rich.py` — Add signal fallback in emit

**Design:** Pretty handlers remain additive polish. Generic fallback is the baseline.

---

## Dependencies

```
1. CommandContext docs        ─── independent
2. Test assertion helpers     ─── independent
3. Uniform context protocol   ─── independent
4. Generic signal fallback    ─── independent
```

All four can be done in parallel.

## File Ownership Matrix

| Deliverable | Files | Repo |
|-------------|-------|------|
| 1 | `docs/patterns/command-context.md` | ev |
| 2 | `src/ev_toolkit/recipes.py`, `tests/test_recipes.py` | ev-toolkit |
| 3 | `src/ev/emitter.py`, `src/ev/emitters/*.py`, `tests/test_emitter.py`, `tests/test_*.py` | ev |
| 4 | `src/ev/emitters/plain.py`, `src/ev/emitters/rich.py`, tests | ev |

## Test Requirements

### 1. CommandContext Pattern (docs)

No code tests. Documentation only.

**Review criteria:**
- [ ] Pattern is clear and self-contained
- [ ] Example code is copy-paste ready
- [ ] Rationale explains *why* not just *what*
- [ ] Links to related patterns (emitter archetypes, domain emitters)

### 2. Test Assertion Helpers

```python
# tests/test_recipes.py additions

class TestSignalHelpers:
    def test_find_signals_returns_matching(self):
        # Setup: emitter with 3 signals, 2 matching name
        # Assert: find_signals returns list of 2

    def test_find_signals_empty_when_none(self):
        # Setup: emitter with signals, none matching
        # Assert: returns []

    def test_assert_has_signal_passes_on_match(self):
        # Setup: emitter with matching signal
        # Assert: no exception, returns the event

    def test_assert_has_signal_fails_on_no_match(self):
        # Setup: emitter without matching signal
        # Assert: raises AssertionError

    def test_assert_has_signal_matches_data(self):
        # Setup: two signals same name, different data
        # Assert: returns one matching expected_data

    def test_last_signal_returns_most_recent(self):
        # Setup: emitter with 3 signals same name
        # Assert: returns the last one

    def test_last_signal_none_when_missing(self):
        # Setup: emitter without matching signal
        # Assert: returns None

    def test_assert_signal_count_passes_on_correct(self):
        # Setup: emitter with exactly n signals
        # Assert: no exception

    def test_assert_signal_count_fails_on_wrong(self):
        # Setup: emitter with m != n signals
        # Assert: raises AssertionError
```

### 3. Uniform Context Protocol

```python
# tests/test_emitter.py additions

class TestContextProtocol:
    def test_list_emitter_context_manager(self):
        with ListEmitter() as e:
            e.emit(Event.log("test"))
        # Assert: works, events captured

    def test_null_emitter_context_manager(self):
        with NullEmitter() as e:
            e.emit(Event.log("test"))
        # Assert: works, no errors

    def test_context_enter_returns_self(self):
        emitter = ListEmitter()
        assert emitter.__enter__() is emitter

    def test_context_exit_safe_on_exception(self):
        # Assert: __exit__ doesn't suppress exceptions
        with pytest.raises(ValueError):
            with ListEmitter() as e:
                raise ValueError("test")

# tests/test_json_emitter.py, test_plain_emitter.py additions
# Same pattern: verify context manager works

# tests/test_tee_emitter.py additions
class TestTeeEmitterContext:
    def test_enters_all_children(self):
        # Setup: mock emitters tracking __enter__ calls
        # Assert: all children receive __enter__

    def test_exits_all_children(self):
        # Setup: mock emitters tracking __exit__ calls
        # Assert: all children receive __exit__

    def test_exits_all_even_on_exception(self):
        # Assert: if one child raises in __exit__, others still called
```

### 4. Generic Signal Fallback

```python
# tests/test_plain_emitter.py additions

class TestSignalFallback:
    def test_renders_unknown_signal(self):
        # Setup: emit signal with name="foo", data={bar: 1, baz: "x"}
        # Assert: output contains "foo bar=1 baz=x" (or similar)

    def test_renders_signal_name_only_when_no_data(self):
        # Setup: emit signal with empty data (just the name)
        # Assert: output contains signal name

    def test_signal_key_excluded_from_output(self):
        # The 'signal' key in data is the marker, not a value
        # Assert: output shows "foo key=val", not "foo signal=foo key=val"

# tests/test_rich_emitter.py additions
# Same pattern for RichEmitter
```

---

## Execution Strategy

All 4 deliverables are independent. Can execute in parallel.

**Recommended approach:**
- Items 3 & 4 touch the same codebase (ev) — sequential within ev to avoid conflicts
- Item 2 is in ev-toolkit — can be parallel with ev work
- Item 1 is docs — can be parallel

**Execution order:**
1. Start with uniform context protocol (3) — foundational
2. Then signal fallback (4) — builds on same files
3. Test helpers (2) in parallel — different repo
4. CommandContext docs (1) in parallel — no code

## Current State (for context recovery)

**Progress:**
- [x] Initial analysis complete (from prior exploration)
- [x] Understand phase complete
- [x] Key decisions made (signal hooks, TypedDict, context protocol)
- [x] Scope adjusted (dropped BatchRenderEmitter, added signal fallback)
- [x] Test requirements defined
- [x] Implementation complete

**Completed:**
- Uniform context protocol: All emitters now support `with emitter:` uniformly
- Signal fallback: Plain/Rich emitters render unknown signals as `name key=value`
- Test assertion helpers: 4 functions in ev-toolkit recipes
- CommandContext pattern docs: New pattern documentation

**Verification:**
- ev: 167 tests, 100% coverage
- ev-toolkit: 48 tests, 95% coverage

---

## Retrospective

### What Went Well

**Plan document as context anchor.** This plan preserved decisions, rationale, and test requirements. When conversation context compacted, the plan had everything needed to understand "why" not just "what."

**Pre-implementation review caught scope issues.** The philosophy review identified that BatchRenderEmitter already existed as `BatchCollector` in ev-toolkit—dropped before wasting effort.

**Philosophy alignment check was valuable.** Explicitly asking "does this add primitives? add machinery?" against ev's design rule kept scope tight. All 4 items passed: no new Event kinds, no new Result fields, protocol shape preserved.

**Independent deliverables.** All 4 items could execute without blocking each other. Clean file ownership meant no merge conflicts.

### Surprises / Gotchas

| Issue | Impact | Fix |
|-------|--------|-----|
| `ev_toolkit` path was actually `ev-toolkit` | Initial agent failed to find repo | Path discovery after error |
| BatchCollector test used old `Event.artifact()` API | Test failure | Updated to `Event.artifact("file", ...)` |
| Lint issues (UP037, SIM117) emerged post-implementation | CI would fail | Fixed quotes and nested `with` |
| RichEmitter `_render_signal` message branch uncovered | 99% coverage | Added specific test case |

### What We'd Do Differently

1. **Verify repo paths before launching parallel agents.** A quick `ls ~/Code | grep ev` would have caught the hyphen vs underscore issue.

2. **Run lint earlier.** Could have caught UP037/SIM117 before test phase instead of after.

3. **Handoff note before compaction risk.** The "Current State" section existed but wasn't updated right before compaction. Should be more aggressive about updating it.

### Learnings Worth Preserving

**For ev:**
- Generic signal fallback (`name key=value`) is the right baseline—pretty handlers are additive polish
- Context protocol on emitters is Pythonic and unlocks uniform composition
- "Recipes" framing in ev-toolkit sets correct expectations (copy-paste, not API)

**For dev-flow:**
- Plan documents survive compaction better than conversation context
- The "expendability order" section was useful—forces ranking what matters most
- Philosophy alignment check should be standard for any core library changes
