# Addendum: API Surface Review (`ev-runtime`)

**Context:** Specific technical critique of the `ev-runtime` implementation.

## 1. Exit Code Precedence Conflict

**The Issue:**
In the `ev` core contract (`types.py`), `Result` has a `code` field intended to be authoritative.
However, `ev-runtime`'s `exit_code()` method ignores this field entirely.

**Current Implementation (`ev-runtime/context.py`):**
```python
def exit_code(self, result: Any) -> int:
    """Map result to Unix exit code."""
    # CRITIQUE: This ignores result.code if present!
    return 0 if getattr(result, "is_ok", False) else 1
```

**Proposed Fix:**
Prioritize `result.code` if it exists (and is non-zero, or explicitly set), falling back to `is_ok` mapping.

```python
def exit_code(self, result: Any) -> int:
    # 1. Prefer explicit code if present
    code = getattr(result, "code", None)
    if code is not None and isinstance(code, int):
        return code
    
    # 2. Fallback to status mapping
    return 0 if getattr(result, "is_ok", False) else 1
```

## 2. TTY Detection Ambiguity

**The Issue:**
The `detect_mode` function currently checks `sys.stdout.isatty()` to decide if "Rich Mode" (Live Display) should be enabled.
This is logically incorrect for tools that send logs/progress to **stderr** and data to **stdout**.

**Current Implementation (`ev-runtime/mode.py`):**
```python
def detect_mode(..., is_tty: bool | None = None, ...):
    if is_tty is None:
        is_tty = sys.stdout.isatty() # CRITIQUE: Checks stdout only

    if not is_tty:
        return OutputMode.PLAIN
    return OutputMode.RICH
```

**The Scenario:**
User runs: `mytool > output.json`
*   `stdout` is NOT a TTY (piped to file).
*   `stderr` IS a TTY (user terminal).
*   **Result:** `detect_mode` sees non-TTY stdout and forces `PLAIN` mode.
*   **Desired:** User wants to see the Progress Bar (on stderr) while piping data (on stdout).

**Proposed Fix:**
Split detection logic.
1.  `detect_mode` should prioritize `stderr` for "Rich vs Plain" decision (interactive UX).
2.  `stdout` check should only influence whether the *Result* is colorized, not the *Events*.

## 3. Protocol Typing

**The Issue:**
`EmitterLike` protocol accepts `Any` for `emit(event)`. This is safe duck-typing but misses an opportunity for stronger hints.

**Proposed Improvement:**
Use a Protocol for `EventLike` to document expectations.

```python
class EventLike(Protocol):
    kind: str
    data: Mapping[str, Any]
    # ...

class EmitterLike(Protocol):
    def emit(self, event: EventLike | Any) -> None: ...
```
