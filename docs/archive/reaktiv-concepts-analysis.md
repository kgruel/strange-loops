# Reaktiv: Conceptual and Documentation Analysis

## Executive Summary

**Reaktiv** is a Python library implementing fine-grained reactive programming through automatic dependency tracking and declarative state management. It brings concepts from modern frontend frameworks (Angular Signals, SolidJS) to Python backend applications.

## Core Mental Model

**The Excel Spreadsheet Analogy** is central to how Reaktiv explains itself:
- **Signals** = Excel cells with values (A1 = 5)
- **Computed** = Excel formulas (B1 = A1 * 2)
- **Effects** = Excel charts that update automatically
- When you change A1, B1 and charts recalculate instantly without manual intervention

This is the conceptual foundation across all documentation—it's simple, relatable, and makes the mental model immediately accessible to developers.

## The Three Core Primitives

### 1. Signals - Mutable reactive data containers
- Store a single value
- Notify dependents when changed via `.set()` or `.update()`
- Track who depends on them automatically
- Serve as the single source of truth

### 2. Computed Signals - Derived, read-only reactive values
- Automatically derive from other signals/computed values
- Lazy evaluation - only computed when accessed
- Smart memoization - cache until dependencies change
- Cannot be manually set (pure functions)
- Support decorator syntax (`@Computed`) or factory style

### 3. Effects - Reactive side effects
- Run when signals/computed values change
- Execute on creation and whenever dependencies change
- Track dependencies automatically
- Must be retained in a variable (explicit garbage collection management)
- Support synchronous and asynchronous functions

## Conceptual Layers

### Layer 1: The Problem Being Solved

The documentation articulates **three core pain points**:

1. **Manual State Synchronization** - Developers must remember to update all derived values when sources change
2. **Hidden State** - Computed values scattered throughout code become hard to track
3. **Dependency Complexity** - Complex dependency chains require manual ordering and maintenance

### Layer 2: The Solution Philosophy

- **Declare relationships once, never again**: State relationships are explicit and centralized
- **Automatic updates**: Dependency tracking is automatic; propagation is guaranteed
- **Fine-grained reactivity**: Only affected computations recalculate, improving performance
- **Lazy evaluation**: Computations happen only when results are needed

### Layer 3: Key Design Principles

1. **Push-Pull Pattern**:
   - **Push**: When Signal A changes, it notifies dependents (Signal B)
   - **Pull**: When B is accessed, it pulls current values to recompute

2. **Explicit Memory Management**:
   - Effects require explicit variable retention to prevent garbage collection
   - This design prevents accidental memory leaks and gives users control over effect lifetimes
   - Intentionally different from some reactive systems that auto-retain indefinitely

3. **Mutable vs. Immutable Objects**:
   - Default identity-based comparison (`is`) for mutable objects
   - Developers must create new instances for changes to be detected
   - Custom equality functions available for value-based comparison

## Advanced Concepts

### LinkedSignal - "Writable Computed with Auto-Reset"
Solves the pattern of "user overrides with smart defaults":
- Stores a user-provided override
- Automatically resets to computed default when context changes
- Use cases: pagination filters, wizard flows, form defaults

### Resource - "Async Data Loading with Automatic Management"
Brings async operations into the reactive system:
- Reactive parameters trigger auto-reload
- Automatic request cancellation (prevents race conditions)
- Status tracking (IDLE, LOADING, RELOADING, RESOLVED, ERROR, LOCAL)
- Seamless integration with Computed and Effect

### Batching - "Group Updates for Efficiency"
- Multiple signal changes can be grouped
- Effects trigger only once after batch completes
- Optimization pattern for bulk updates

### Untracked Reads - "Dependency Control"
- Read signals without creating dependencies
- Useful for logging, debugging, conditional logic
- Gives fine-grained control over dependency graph

## Documentation Organization

The documentation follows a clear progression:

1. **Conceptual Foundation** (Why & What)
   - `README.md` - Big picture with Excel analogy
   - `why-reaktiv.md` - Problem domain and pain points
   - `core-concepts.md` - Mental models and fundamentals

2. **Practical Guidance** (How To)
   - `quickstart.md` - Minimal working examples
   - `advanced-features.md` - Sophisticated patterns
   - `patterns-and-best-practices.md` - Real-world usage

3. **Reference** (API Details)
   - `api/signal.md`, `api/compute-signal.md`, `api/effect.md` - Function signatures
   - `resource-guide.md` - Comprehensive async data loading guide
   - `api/linked-signal.md`, `api/utils.md` - Specialized utilities

4. **Real-World Applications**
   - Examples folder with FastAPI, NiceGUI, NumPy/Pandas, IoT, Jupyter notebooks
   - Demonstrates integration patterns with existing ecosystems

## Key Terminology & Concepts

| Term | Definition |
|------|-----------|
| **Dependency Tracking** | Automatic detection of which signals a computation reads |
| **Fine-Grained Reactivity** | Only affected computations recalculate; unrelated ones stay cached |
| **Lazy Evaluation** | Computations occur only when their results are actually needed |
| **Memoization** | Results are cached until dependencies change |
| **Push Notification** | Signal notifies dependents of changes |
| **Pull Evaluation** | Dependent pulls fresh values when accessed |
| **Reactive Context** | The current scope (effect/computation) being executed |

## Use Cases & Problem Domains

**Excellent Fit:**
- Complex state dependencies (multi-step derivations)
- Configuration management with cascading overrides
- Data processing pipelines with reactive transformations
- Real-time monitoring and alerting systems
- Smart caching with automatic invalidation
- Reactive UIs and web frameworks

**Poor Fit:**
- Simple state (few dependencies)
- Pure event handling (fire-and-forget)
- Stream processing of massive datasets (consider RxPy instead)
- Extreme performance-critical systems

## Design Principles Expressed

1. **Explicit over Implicit**: Effects must be retained; untracked reads are optional
2. **Simplicity by Default**: Three primitives are sufficient for most use cases
3. **Python-Native**: Works with asyncio, type hints, and Python patterns
4. **Zero External Dependencies**: Only uses Python standard library
5. **Type-Safe**: Full type hint support for IDE autocompletion and static analysis

## Comparison Positioning

**vs. RxPy/ReactiveX**:
- Reaktiv = value-centric (how to keep values in sync)
- RxPy = stream-centric (how to process event streams)

**vs. Manual Observer Pattern**:
- Automatic vs. manual dependency tracking
- Fine-grained vs. coarse-grained updates
- Minimal vs. extensive boilerplate

## Critical Warnings in Documentation

1. **Effect Retention**: Most common mistake—effects must be assigned to variables
2. **Mutable Objects**: Identity-based comparison by default; requires new instances for changes
3. **Conditional Dependencies**: Dependencies established at effect execution time; conditional signal reads are error-prone
4. **Dependency Ordering**: Call dependent signals early in effects to ensure proper tracking

## Philosophy & Inspiration

The library explicitly positions itself as bringing **frontend reactive patterns to Python**:
- Inspired by: Angular Signals, SolidJS reactivity
- Core insight: Declaring reactive relationships reduces bugs versus manual updates
- Applicable beyond UIs: configuration, caching, data pipelines, monitoring

## Examples Pattern

Documentation provides examples at multiple levels:
- **Conceptual**: Excel analogy, shopping cart order calculations
- **Practical**: Flask WebSocket, NiceGUI todo app, data pipelines
- **Advanced**: Jupyter notebooks, IoT sensor monitoring, NumPy plotting

This progression helps developers understand both "why" and "how."
