# Command Context

*The missing layer between CLI commands and operations.*

## The Problem

CLI commands accumulate boilerplate:

```python
async def __call__(
    self,
    config: Annotated[ConfigSource, cappa.Dep(get_config)],
    mode: Annotated[OutputMode, cappa.Dep(get_output_mode)],
    verbosity: Annotated[int, cappa.Dep(get_verbosity)],
    theme: Annotated[Theme, cappa.Dep(get_theme)],
    output: cappa.Output,
) -> None:
    stack = resolve_stack(config, self.stack_name)
    emitter = create_emitter(mode, theme, verbosity)

    if mode == OutputMode.RICH:
        with emitter:
            result = await check_stack(stack, emitter)
            emitter.finish(result)
    else:
        result = await check_stack(stack, emitter)
        emitter.finish(result)

    output.write(format_summary(result, mode))
    if not result.is_ok:
        raise SystemExit(result.code)
```

Every command repeats: dependency injection, resource resolution, emitter wiring, mode branching, exit code mapping.

## The Pattern

**CommandContext** bundles these concerns into a single injection point:

```python
@dataclass
class CommandContext:
    """Single dependency for CLI commands."""

    config: ConfigSource
    mode: OutputMode
    theme: Theme
    verbosity: int
    output: Output

    # Resolution
    def require_stack(self, name: str) -> Stack:
        """Resolve stack by name. Raises if not found."""
        stack = self.config.stacks.get(name)
        if not stack:
            raise ValueError(f"Unknown stack: {name}")
        return stack

    # Emitter factory
    @contextmanager
    def emitter(self, **kwargs) -> Iterator[Emitter]:
        """Create appropriate emitter for current mode."""
        em = create_emitter(self.mode, self.theme, self.verbosity, **kwargs)
        with em:
            yield em

    # Output
    def print_summary(self, result: Result) -> None:
        """Print result summary in current mode."""
        self.output.write(format_summary(result, self.mode))

    # Exit code mapping
    def exit_code(self, result: Result) -> int:
        """Map result to exit code."""
        return result.code
```

Commands become minimal:

```python
async def __call__(
    self,
    ctx: Annotated[CommandContext, cappa.Dep(get_command_context)],
) -> None:
    stack = ctx.require_stack(self.stack_name)

    with ctx.emitter() as emitter:
        result = await check_stack(stack, emitter)
        emitter.finish(result)

    ctx.print_summary(result)
    if not result.is_ok:
        raise SystemExit(ctx.exit_code(result))
```

## Why This Works

### 1. Single Injection Point

Instead of 5+ parameters per command, you have one. Adding new global state (a debug flag, a dry-run mode) only changes `CommandContext`, not every command.

### 2. Separation of Concerns

| Layer | Responsibility |
|-------|----------------|
| CLI command | Parse args, orchestrate flow |
| CommandContext | Resolve resources, create emitters, map outputs |
| Operation | Domain logic, emit events |
| Emitter | Render events |

Commands don't know about mode branching. Operations don't know about CLI frameworks. Clean seams.

### 3. Uniform Emitter Wiring

The `emitter()` context manager:
- Creates the right emitter for the mode
- Handles context management (Rich Live, file cleanup)
- Works uniformly across all commands

No more `if mode == RICH: with emitter:` in every command.

### 4. Testable in Isolation

Test command logic by mocking `CommandContext`:

```python
def test_status_command_requires_stack():
    ctx = MockCommandContext()
    ctx.require_stack.side_effect = ValueError("Unknown stack")

    with pytest.raises(ValueError):
        await StatusCommand(stack="nonexistent")(ctx)
```

Test operations by using `ListEmitter` directly:

```python
def test_check_stack_emits_status():
    emitter = ListEmitter()
    result = await check_stack(stack, emitter)

    assert_has_signal(emitter, "stack_status", stack="media")
```

## Provider Implementation

For frameworks like cappa or typer, create a provider:

```python
def get_command_context(app: App) -> CommandContext:
    """Build CommandContext from root command flags."""
    return CommandContext(
        config=load_config(app.config_path),
        mode=determine_mode(app.json, app.plain),
        theme=load_theme(app.theme_path),
        verbosity=app.verbose,
        output=app.output,
    )

def determine_mode(json: bool, plain: bool) -> OutputMode:
    if json:
        return OutputMode.JSON
    if plain or not sys.stdout.isatty():
        return OutputMode.PLAIN
    return OutputMode.RICH
```

## Customization

### Emitter Factories

Different commands might need different emitters:

```python
@contextmanager
def emitter(self, stacks: list[str] | None = None) -> Iterator[Emitter]:
    """Create emitter with optional stack context."""
    if self.mode == OutputMode.RICH:
        em = LiveStatusEmitter(stacks or [])
    elif self.mode == OutputMode.JSON:
        em = JsonEmitter()
    else:
        em = PlainEmitter(verbosity=self.verbosity)

    with em:
        yield em
```

### Resource Resolution

Add resolution methods as needed:

```python
def require_service(self, stack: str, service: str) -> Service:
    """Resolve a service within a stack."""
    ...

def require_file(self, path: str) -> Path:
    """Resolve and validate a file path."""
    ...
```

### Exit Code Policies

Customize exit code mapping:

```python
def exit_code(self, result: Result) -> int:
    if result.is_ok:
        return 0
    # Distinguish types of failures
    if "timeout" in result.summary.lower():
        return 124  # Standard timeout exit code
    return result.code or 1
```

## Related Patterns

- [Domain Emitters](domain-emitters.md) — Building emitters that understand your events
- [Emitter Archetypes](emitter-archetypes.md) — Streaming vs batch emitter patterns
- [Live Emitter](live-emitter.md) — Rich Live integration for status displays

## Summary

| Without CommandContext | With CommandContext |
|------------------------|---------------------|
| 5+ injected parameters | 1 injected parameter |
| Mode branching in commands | Mode branching in context |
| Repeated emitter setup | Factory method |
| Scattered resolution logic | Centralized resolution |
| Ad-hoc exit code handling | Consistent mapping |

CommandContext is the seam between "CLI framework concerns" and "domain operation concerns." Keep it thin, keep it focused, and your commands become orchestration glue.
