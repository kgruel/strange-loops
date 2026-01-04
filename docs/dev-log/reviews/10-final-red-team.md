# Addendum: Final Red Team Review

**Context:** A final "Red Team" analysis of the ecosystem to identify subtle inconsistencies, logical gaps, or "unknown unknowns" before freezing the architecture.

## 1. The "Duck Typing" Vulnerability (ev-runtime)

**Observation:**
`ev-runtime` avoids importing `ev` to maintain loose coupling. Consequently, `RuntimeContext.exit_code(result)` relies on runtime inspection:
```python
return 0 if getattr(result, "is_ok", False) else 1
```

**The Risk:**
If a user employs a result object from a different library (e.g., one using `success=True` instead of `is_ok`), `exit_code` will silently return `1` (Error) because the attribute lookup fails. This "silent failure" mode is dangerous for CLI exit codes.

**Mitigation:**
*   **Short Term:** Document this requirement explicitly in `RuntimeContext` docstrings.
*   **Long Term:** `ev-runtime` should define a `ResultLike` Protocol.
*   **Toolkit Fix:** `ev-toolkit` (the unifier) will likely bind `RuntimeContext` specifically to `ev.Result`, eliminating this ambiguity for 90% of users.

## 2. Docstring Coupling Leak (ev-present)

**Observation:**
In `ev_present/ir.py`, the `Line` class docstring states:
> "Backends convert to rich.Text, str, etc."

**The Critique:**
While helpful, explicitly naming `rich.Text` in the core IR module violates the "Backend Neutral" philosophy at the documentation level. It primes the user to think "Rich is required."

**Correction:**
Future refactors should change this to "Backends convert to terminal primitives or native strings."

## 3. Timestamp Precision (ev)

**Observation:**
`Event.ts` uses `time.time()` (float seconds).

**The Critique:**
While sufficient for UI rendering (spinners, logs), `float` precision can be insufficient for micro-benchmarking or high-frequency tracing (where nanoseconds matter). If `ev` is ever used as a performance tracing tool (competing with Rust's `tracing`), this will be a bottleneck.

**Decision:**
Acceptable for `v1`. UI observability operates at "human speed" (milliseconds).

## 4. The "Reserved Key" Conflict

**Observation:**
`Event.log_signal` raises `ValueError` if `data` contains `"signal"`.
However, `Event.log` does *not* enforce this.

**The Risk:**
A user manually creating `Event.log(..., data={"signal": "noise"})` effectively "spoofs" a Signal event without going through the `log_signal` factory. This could confuse renderers that rely on `event.is_signal` (which checks for the key).

**Mitigation:**
Renderers must be robust. The `is_signal` property is the source of truth. If a user manually injects the key, they *are* creating a signal, intentionally or not. This is likely acceptable behavior ("Power User Escape Hatch").

## Conclusion

The architecture holds up under scrutiny. The identified risks are:
1.  **Ergonomic** (Duck typing confusion).
2.  **Cosmetic** (Docstring wording).
3.  **Future-proofing** (Timestamp precision).

None are critical blockers for the current roadmap.
