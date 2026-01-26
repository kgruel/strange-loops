# Addendum: Second Consumer Analysis - lldap-invite

**Context:** Analysis of lldap-invite as the second ev ecosystem consumer, mapping patterns and identifying shared abstractions that justify ev-toolkit extraction.

## 1. Project Overview

**lldap-invite** is a self-service invite system for LLDAP with three interfaces:
- **Web**: Litestar + HTMX templates
- **REST API**: JSON endpoints
- **CLI**: Click-based command-line tools

**Stack**: Litestar, Piccolo ORM, SQLite, ldap3, Click, structlog

---

## 2. Current CLI Architecture

```
CLI (Click)
    ↓
CLIRunner.context()  [lifecycle manager]
    ↓
CLIContext          [service container]
    ↓
Services (InviteService, UserService, etc.)
```

### Key Patterns (Parallel to hlab)

| Pattern | lldap-invite | hlab |
|---------|-------------|------|
| **CLI Framework** | Click | cappa |
| **Context Manager** | `CLIRunner.context()` | `CommandContext` |
| **Service Injection** | `CLIContext` | `CommandContext.require_*()` |
| **Error Mapping** | `@handle_errors` decorator | Exception hierarchy |
| **Output Format** | `format_output(data, json_output)` | `OutputMode` + emitters |
| **Async Bridge** | `asyncio.run()` per command | Native async (`cappa.invoke_async`) |

### Current Output Handling

```python
# Simple formatter - no structured events
def format_output(data: dict | list | Any, json_output: bool = False) -> str:
    if json_output:
        return json.dumps(data, indent=2, default=_json_serializer)
    return _format_human(data)

# Commands just echo formatted output
click.echo(format_output(output, json_output))
```

**Gaps:**
- No progress tracking
- No streaming output
- No semantic distinction between operation types
- Tight coupling between error handling and exit codes

---

## 3. Pattern Mapping: ev Ecosystem → lldap-invite

### A. Event/Result Contract (ev core)

**Current state:** Services raise domain exceptions, CLI catches and formats.

**With ev:**
```python
# Service emits events during operation
async def create_invite(self, input: CreateInviteInput, emitter: Emitter) -> Result:
    emitter.emit(Event.log("Creating invite token..."))

    try:
        result = await self._create(input)
        emitter.emit(Event.artifact("invite.created", token=result.token))
        return Result.ok("Invite created", data={"token": result.token})
    except ValidationError as e:
        return Result.error(str(e), code=2)

# CLI just wires and displays
with ctx.emitter() as emitter:
    result = await invite_service.create(input, emitter)
    emitter.finish(result)
raise SystemExit(ctx.exit_code(result))
```

**Benefits:**
- Testable: Assert on events, not string output
- Multi-format: JSON/human output from same events
- Progress: Add `Event.progress()` for long operations (LDAP calls)

### B. OutputMode Detection (ev-runtime)

**Current state:** Manual `--json` flag handling in each command.

**With ev-runtime:**
```python
from ev_runtime import detect_mode, OutputMode

@cli.command()
@click.option("--json", "json_flag", is_flag=True)
@click.option("--plain", is_flag=True)
def invite_create(json_flag, plain):
    mode = detect_mode(json_flag=json_flag, plain_flag=plain)
    # Mode is RICH/PLAIN/JSON based on flags + TTY
```

**Shared policy:** `--json` > `--plain` > non-TTY > rich

### C. RuntimeContext (ev-runtime)

**Current state:** `CLIRunner.context()` + `CLIContext` provide lifecycle management.

**Mapping:**
```python
# Current CLIRunner pattern
async with ctx.obj["runner"].context() as cli_ctx:
    result = await cli_ctx.invite_service.create(...)

# Would become RuntimeContext pattern
ctx = RuntimeContext(
    mode=detect_mode(...),
    verbosity=detect_verbosity(...),
    resolver=ServiceResolver(services),  # or just direct injection
    emitter_factory=lldap_emitter_factory,
)

with ctx.emitter() as emitter:
    result = await invite_service.create(input, emitter)
    emitter.finish(result)
```

**Key insight:** `CLIRunner` is already doing what `RuntimeContext` does—lifecycle management + service injection. The seam is there; ev-runtime would standardize the API.

### D. Error Handling → Result

**Current state:** `@handle_errors` decorator maps exceptions to exit codes.

```python
@handle_errors
def invite_create(...):
    ...

# Decorator catches exceptions:
except ValidationError as e:
    click.echo(f"Validation error: {e}", err=True)
    raise SystemExit(2)
```

**With ev:** The exit code lives in `Result.code`:
```python
# Service returns Result instead of raising
result = Result.error(str(e), code=2)

# CLI uses RuntimeContext.exit_code()
raise SystemExit(ctx.exit_code(result))  # Returns result.code
```

**Benefit:** Semantic exit codes flow through the contract, not decorator magic.

---

## 4. Shared Patterns → ev-toolkit Candidates

Comparing hlab and lldap-invite reveals shared abstractions:

### A. Emitter Factory Pattern

Both need mode-aware emitter creation:

```python
# hlab pattern
def create_summary_emitter(mode: OutputMode, stack_names: list[str], ...):
    match mode:
        case OutputMode.RICH: return HlabLiveEmitter(...)
        case OutputMode.PLAIN: return PlainEmitter(...)
        case OutputMode.JSON: return HlabJsonEmitter(...)

# lldap-invite would need similar
def create_invite_emitter(mode: OutputMode, ...):
    match mode:
        case OutputMode.RICH: return LldapRichEmitter(...)
        case OutputMode.PLAIN: return PlainEmitter(...)
        case OutputMode.JSON: return LldapJsonEmitter(...)
```

**Shared abstraction:** `EmitterFactory` protocol + `create_emitter()` helper

### B. Plain/JSON Emitters

Both need basic batch emitters:

| hlab | lldap-invite (proposed) |
|------|------------------------|
| `PlainEmitter` | `PlainEmitter` (identical) |
| `HlabJsonEmitter` | `JsonEmitter` (identical) |

**Shared abstraction:** Generic `PlainEmitter` and `JsonEmitter` that format events/results. Domain-specific rendering can override `_format_event()`.

### C. Error-to-Result Mapping

Both have domain exceptions with `.code` attributes:

```python
# lldap-invite exceptions
class ValidationError(Exception):
    def __init__(self, message, code="VALIDATION_ERROR", field=None):
        self.code = code
        self.field = field

# hlab exceptions
class HlabError(Exception):
    def __init__(self, message, suggestion=None):
        self.message = message
        self.suggestion = suggestion
```

**Shared abstraction:** `CLIError` base (already in ev-runtime) that both can extend.

### D. Format Output Pattern

Both have human vs JSON formatting needs:

```python
# lldap-invite
def format_output(data, json_output):
    if json_output:
        return json.dumps(data, ...)
    return _format_human(data)

# hlab (via emitters)
match mode:
    case OutputMode.JSON: JsonEmitter renders
    case OutputMode.PLAIN: PlainEmitter renders
```

**Shared abstraction:** `ResultFormatter` that takes `Result` and produces output string.

---

## 5. ev-toolkit Extraction Scope

Given two consumers, the following extractions are justified:

### Tier 1: Extract Now

1. **Generic PlainEmitter** - Batch emitter that formats events as `[LEVEL] message`
2. **Generic JsonEmitter** - Batch emitter that outputs JSON result
3. **exit_code() fix** - Respect `result.code` field
4. **CLIError base** - Already in ev-runtime, both projects can adopt

### Tier 2: Extract When Patterns Stabilize

5. **EmitterFactory helper** - Generic factory with mode→emitter routing
6. **format_output()** - Standardized human/JSON output formatter
7. **Signal rendering** - Generic `signal_name key=value` format for unknown signals

### Tier 3: Not Yet Needed

8. **Rich/Live emitters** - Too domain-specific (hlab has trees, lldap-invite would have tables)
9. **ev-present atoms** - lldap-invite doesn't need Rich output yet
10. **Concurrency (.bind())** - Neither project needs parallel tasks currently

---

## 6. Integration Path for lldap-invite

### Phase 1: Adopt ev Core (Low Risk)

1. Add `ev` dependency
2. Modify services to accept optional `emitter` parameter
3. Emit `Event.log()` for narrative, `Event.artifact()` for results
4. Return `Result` instead of dict from services

```python
# Before
async def create(self, input: CreateInviteInput) -> dict:
    result = await self._create(input)
    return {"token": result.token, ...}

# After
async def create(self, input: CreateInviteInput, emitter: Emitter = NullEmitter()) -> Result:
    emitter.emit(Event.log("Creating invite..."))
    result = await self._create(input)
    emitter.emit(Event.artifact("invite.created", token=result.token))
    return Result.ok("Invite created", data={"token": result.token, ...})
```

### Phase 2: Adopt ev-runtime (Medium Risk)

1. Add `ev-runtime` dependency
2. Replace `@handle_errors` with `Result` pattern
3. Use `detect_mode()` and `detect_verbosity()`
4. Use `RuntimeContext` or keep `CLIRunner` (they're equivalent)

### Phase 3: Consider ev-present (Future)

Only if/when lldap-invite wants Rich terminal output (spinners, progress bars, styled tables). Current human output is adequate for the use case.

---

## 7. lldap-invite-Specific Signals

If adopting ev, these signals would be domain-specific:

```python
# Invite domain
Event.log_signal("invite.created", token="abc123", group="users", expires_hours=48)
Event.log_signal("invite.revoked", token="abc123")
Event.log_signal("invite.used", token="abc123", user="newuser")

# User domain
Event.log_signal("user.created", username="newuser", email="...", groups=["users"])
Event.log_signal("user.check", identifier="email@example.com", available=True)

# Signup domain
Event.log_signal("signup.approved", request_id="123", invite_token="...")
Event.log_signal("signup.denied", request_id="123", note="...")

# Config domain
Event.log_signal("settings.updated", key="signup_mode", value="invite-only")
Event.log_signal("config.imported", mode="merge", settings=5, services=3, groups=2)
```

---

## 8. Comparison Table

| Aspect | hlab | lldap-invite | Shared |
|--------|------|-------------|--------|
| **CLI Framework** | cappa | Click | Different |
| **Async** | Native | `asyncio.run()` bridge | Different |
| **Context Pattern** | `CommandContext` | `CLIRunner.context()` | Same concept |
| **Mode Detection** | ev-runtime | Manual flags | → ev-runtime |
| **Emitter Lifecycle** | Context manager | N/A currently | → ev pattern |
| **Error Handling** | Exception hierarchy | `@handle_errors` | → Result pattern |
| **JSON Output** | `JsonEmitter` | `json.dumps()` | → Generic JsonEmitter |
| **Plain Output** | `PlainEmitter` | `_format_human()` | → Generic PlainEmitter |
| **Rich Output** | `HlabLiveEmitter` | Not needed | Domain-specific |
| **Testing** | `ListEmitter` | Assert on dict returns | → ListEmitter |

---

## 9. Updated Recommendations

Given lldap-invite as second consumer and **ev-toolkit Trifecta now complete**:

### Completed (ev-toolkit Trifecta)

1. ✅ **RecordingEmitter + Run** - test capture utility
2. ✅ **TeeEmitter context manager** - `__enter__`/`__exit__` support
3. ✅ **FileEmitter** - JSONL output for debugging/LLM
4. ✅ **RichEmitter with ev-present** - full semantic pipeline
5. ✅ **Golden tests** - validates ev → ev-present → rich pipeline

**Test status**: 79 tests, 92% coverage, all passing.

### Immediate (This Week)

1. **ev-runtime**: Implement `exit_code()` fix (respects `result.code`)
2. **ev-toolkit**: Update plan status from `not-started` to `completed`
3. **Documentation**: Add "Second Consumer" section to ev README

### Near-Term (This Month)

4. **lldap-invite**: Experimental ev integration branch using:
   - ev core (`Event`, `Result`)
   - ev-toolkit's `get_emitter()` for mode detection
   - ev-toolkit's `RichEmitter` (if Rich output desired)
   - ev's `PlainEmitter`/`JsonEmitter` for batch output
5. **ev-toolkit**: Consider adding convenience helpers:
   - `exit_code(result)` - 5-line helper (or use ev-runtime)

### Medium-Term (When Proven)

6. **ev-present**: Add `StateLine`, `FieldLine` if both projects need them
7. **Coordinate**: Remove duplicate emitters from ev core (FileEmitter, TeeEmitter now in toolkit)

### Architecture Clarification

| Package | Scope | lldap-invite Uses | Status |
|---------|-------|------------------|--------|
| **ev** | Contract (Event/Result) | Yes - core | Stable |
| **ev-toolkit** | Utilities (wrappers, helpers) | Yes - `get_emitter()`, `RichEmitter` | **Ready** |
| **ev-runtime** | CLI conventions (RuntimeContext) | Maybe - if complexity grows | Stable |
| **ev-present** | Display IR (Line/Segment) | Via RichEmitter | Stable |

The simpler path for lldap-invite is ev + ev-toolkit. RuntimeContext pattern is optional.

---

## 10. Conclusion

**lldap-invite validates ev-toolkit extraction.** The shared patterns are clear:

- Mode detection (`detect_mode`)
- Emitter lifecycle (context manager)
- Result-based error handling
- Generic batch emitters (Plain, JSON)

The differences are also clear:
- CLI framework (Click vs cappa) - ev-runtime is framework-agnostic
- Rich output needs - hlab needs trees, lldap-invite needs tables (if at all)

**Recommended approach:**
1. Start with ev core adoption in lldap-invite (low risk)
2. Extract proven patterns to ev-toolkit
3. Let domain-specific rendering stay in apps

*"Two consumers reveal the seam. Extract what's shared, leave what's specific."*
