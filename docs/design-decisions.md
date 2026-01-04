# Design Decisions for ev Library

## Result Semantics

Result represents the final outcome of a command. It captures both the success or failure state and additional contextual information.

### Special Exit Codes

Two pre-defined exit codes have special semantic meaning:

- `10`: Timeout errors - indicates an operation that exceeded its allowed time
- `20`: Authentication errors - indicates a failure in authorization or authentication processes

Example usage:
```python
# Timeout example
timeout_result = Result.error(
    summary="Operation timed out",
    code=10,
    data={"timeout_duration": "30s"}
)

# Authentication error example
auth_error_result = Result.error(
    summary="Authentication failed",
    code=20,
    data={"auth_method": "oauth"}
)
```