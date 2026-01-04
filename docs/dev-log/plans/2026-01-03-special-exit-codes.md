---
status: completed
updated: 2026-01-03
---

# Special Exit Codes for Result

## Problem
Need a standardized way to communicate specific error types beyond the default generic error code.

## Approach
Introduced two special exit codes:
- `10`: Timeout errors
- `20`: Authentication errors

## Implementation
- Updated tests in `tests/test_result_with_special_codes.py`
- Leveraged existing `Result.error()` method's flexibility
- Added documentation explaining the special exit codes

## Rationale
By using specific exit codes, we provide more context about error types without changing the core `Result` implementation. This allows consumers to make more informed decisions based on the error.

## Example Usage
```python
# Timeout scenario
result = Result.error(summary="Operation timed out", code=10)

# Authentication scenario
result = Result.error(summary="Authentication failed", code=20)
```

## Lessons Learned
- Exit codes are a lightweight way to add semantic meaning to errors
- Existing `Result` design is flexible enough to support this without modification