"""Lens as code: explicit primitive for view projection.

Building on review_lens.py findings. This experiment explores:

1. Lens as explicit dataclass (not tied to cells rendering)
2. Lens = zoom + scope as orthogonal dimensions
3. Lens vs Projection: read-side vs write-side projections
4. Where does Lens belong? ticks vs cells vs new lib

KEY INSIGHT
-----------
Projection and Lens are dual:

    Projection: Facts → state     (reduce over time, accumulate)
    Lens:       state → view      (reduce for display, filter)

Both are projections in the mathematical sense — many-to-fewer. But they
serve different purposes:
- Projection is infrastructure: how state accumulates
- Lens is presentation: how state renders

The pipeline is:
    Facts → Projection(fold) → state → Lens(zoom, scope) → view → Surface

DESIGN QUESTION
---------------
Where should Lens live?

Option A: ticks (alongside Projection)
  - Pro: Lens pairs with Projection conceptually
  - Con: ticks is about temporal accumulation, Lens is about display

Option B: cells (surface concern)
  - Pro: Lens controls rendering depth/filtering
  - Con: Lens is data-level, not widget-level

Option C: new lib (lens or views)
  - Pro: Clean separation, Lens as first-class concept
  - Con: More libs, possibly overkill

This experiment uses a standalone Lens to let the code reveal where it wants.

Run:
    uv run python experiments/lens_code.py
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any, Callable, Generic, TypeVar

from ticks import Projection


# ============================================================================
# LENS AS PRIMITIVE
# ============================================================================

@dataclass(frozen=True, slots=True)
class Lens:
    """View configuration: how content renders, not what content exists.

    Two orthogonal dimensions:
    - zoom: detail level (0=minimal, 1=summary, 2=full, 3+=verbose)
    - scope: visible kinds (None=all, frozenset=filtered)

    Lens is orthogonal to Peer:
    - Peer.horizon gates what data you CAN see (access control)
    - Lens.scope gates what data you DO see (presentation filter)
    - Peer.potential gates what you CAN emit (capability)
    - Lens.zoom controls rendering depth (detail level)

    Lens is immutable. Use with_zoom/with_scope for modifications.
    """

    zoom: int = 1
    scope: frozenset[str] | None = None

    def with_zoom(self, zoom: int) -> "Lens":
        """Return new Lens with adjusted zoom (clamped to 0+)."""
        return replace(self, zoom=max(0, zoom))

    def with_scope(self, scope: frozenset[str] | None) -> "Lens":
        """Return new Lens with adjusted scope."""
        return replace(self, scope=scope)

    def includes(self, kind: str) -> bool:
        """Check if kind passes through this lens.

        None scope means all kinds pass through.
        """
        if self.scope is None:
            return True
        return kind in self.scope

    def zoom_in(self) -> "Lens":
        """Increase detail level."""
        return self.with_zoom(self.zoom + 1)

    def zoom_out(self) -> "Lens":
        """Decrease detail level."""
        return self.with_zoom(self.zoom - 1)


# Preset lenses for common use cases
LENS_MINIMAL = Lens(zoom=0)
LENS_SUMMARY = Lens(zoom=1)
LENS_FULL = Lens(zoom=2)
LENS_VERBOSE = Lens(zoom=3)


# ============================================================================
# LENS + PROJECTION COMPARISON
# ============================================================================

S = TypeVar("S")  # State type
T = TypeVar("T")  # Event type
V = TypeVar("V")  # View type


@dataclass(frozen=True, slots=True)
class LensedProjection(Generic[S, T, V]):
    """Projection with an attached Lens.

    Demonstrates the pairing:
    - projection: T → S (accumulate events into state)
    - lens_fn: (S, Lens) → V (project state through lens into view)

    This is a teaching construct showing how Projection and Lens compose.
    In practice, they'd be separate and combined at the rendering layer.
    """

    projection: Projection[S, T]
    lens_fn: Callable[[S, Lens], V]
    lens: Lens = LENS_SUMMARY

    def apply(self, event: T) -> None:
        """Apply event through projection."""
        self.projection.fold_one(event)

    def view(self, lens: Lens | None = None) -> V:
        """Get view through lens."""
        use_lens = lens if lens is not None else self.lens
        return self.lens_fn(self.projection.state, use_lens)

    @property
    def state(self) -> S:
        """Access raw state (bypasses lens)."""
        return self.projection.state


# ============================================================================
# CONCRETE EXAMPLE: LOG PROJECTION + LENS
# ============================================================================

@dataclass
class LogEntry:
    """A log entry."""
    ts: float
    level: str
    message: str
    metadata: dict[str, Any] | None = None


@dataclass
class LogState:
    """Accumulated log state."""
    entries: list[LogEntry]
    by_level: dict[str, int]  # count per level
    total: int

    @staticmethod
    def initial() -> "LogState":
        return LogState(entries=[], by_level={}, total=0)


def log_fold(state: LogState, entry: LogEntry) -> LogState:
    """Fold a log entry into state."""
    by_level = dict(state.by_level)
    by_level[entry.level] = by_level.get(entry.level, 0) + 1
    return LogState(
        entries=state.entries + [entry],
        by_level=by_level,
        total=state.total + 1,
    )


def log_lens(state: LogState, lens: Lens) -> dict[str, Any]:
    """Project log state through lens.

    Zoom levels:
    - 0: Count only
    - 1: Summary (counts by level)
    - 2: Recent entries (last 5)
    - 3+: All entries with metadata
    """
    view: dict[str, Any] = {"total": state.total}

    if lens.zoom >= 1:
        view["by_level"] = state.by_level

    if lens.zoom >= 2:
        # Filter entries by scope if specified
        entries = state.entries
        if lens.scope is not None:
            entries = [e for e in entries if e.level in lens.scope]
        view["recent"] = entries[-5:]

    if lens.zoom >= 3:
        # All entries with metadata
        entries = state.entries
        if lens.scope is not None:
            entries = [e for e in entries if e.level in lens.scope]
        view["all_entries"] = entries

    return view


def create_log_projection() -> LensedProjection[LogState, LogEntry, dict[str, Any]]:
    """Create a log projection with lens support."""
    projection = Projection(LogState.initial(), fold=log_fold)
    return LensedProjection(projection=projection, lens_fn=log_lens)


# ============================================================================
# CONCRETE EXAMPLE: HEALTH PROJECTION + LENS
# ============================================================================

@dataclass
class HealthEvent:
    """A health check event."""
    container: str
    status: str
    ts: float


@dataclass
class HealthState:
    """Accumulated health state."""
    current: dict[str, str]  # container -> status
    history: list[HealthEvent]
    checks: int

    @staticmethod
    def initial() -> "HealthState":
        return HealthState(current={}, history=[], checks=0)


def health_fold(state: HealthState, event: HealthEvent) -> HealthState:
    """Fold a health event into state."""
    current = dict(state.current)
    current[event.container] = event.status
    return HealthState(
        current=current,
        history=state.history + [event],
        checks=state.checks + 1,
    )


def health_lens(state: HealthState, lens: Lens) -> dict[str, Any]:
    """Project health state through lens.

    Zoom levels:
    - 0: Just OK/WARN/FAIL summary
    - 1: Current status per container
    - 2: Current + recent history
    - 3+: Full history
    """
    view: dict[str, Any] = {}

    # Scope filtering: if scope is set, only show those containers
    containers = (
        set(state.current.keys())
        if lens.scope is None
        else set(state.current.keys()) & lens.scope
    )

    if lens.zoom == 0:
        # Summary only
        statuses = [state.current.get(c, "unknown") for c in containers]
        ok = sum(1 for s in statuses if s == "running")
        warn = sum(1 for s in statuses if s == "unhealthy")
        fail = sum(1 for s in statuses if s == "stopped")
        view["summary"] = f"OK:{ok} WARN:{warn} FAIL:{fail}"
        return view

    if lens.zoom >= 1:
        # Current status per container
        view["current"] = {c: state.current[c] for c in containers if c in state.current}

    if lens.zoom >= 2:
        # Add recent history
        history = state.history
        if lens.scope is not None:
            history = [e for e in history if e.container in lens.scope]
        view["recent"] = history[-10:]

    if lens.zoom >= 3:
        # Full history
        history = state.history
        if lens.scope is not None:
            history = [e for e in history if e.container in lens.scope]
        view["history"] = history

    return view


def create_health_projection() -> LensedProjection[HealthState, HealthEvent, dict[str, Any]]:
    """Create a health projection with lens support."""
    projection = Projection(HealthState.initial(), fold=health_fold)
    return LensedProjection(projection=projection, lens_fn=health_lens)


# ============================================================================
# PER-PEER LENS
# ============================================================================

@dataclass
class PeerLensConfig:
    """Default lens configuration per peer.

    Each peer can have a default lens that reflects their role:
    - Operators: full detail, all kinds
    - Monitors: summary, domain-only (no infrastructure)
    - Dashboards: minimal, specific metrics
    """
    default_zoom: int = 1
    default_scope: frozenset[str] | None = None

    def create_lens(self) -> Lens:
        """Create a lens from this config."""
        return Lens(zoom=self.default_zoom, scope=self.default_scope)


# Example peer lens configs
PEER_LENS_CONFIGS = {
    "kyle": PeerLensConfig(default_zoom=2, default_scope=None),  # Full detail, everything
    "monitor": PeerLensConfig(default_zoom=1, default_scope=frozenset({"error", "warn"})),  # Summary, errors only
    "dashboard": PeerLensConfig(default_zoom=0, default_scope=None),  # Minimal, all kinds
}


# ============================================================================
# DEMONSTRATION
# ============================================================================

def demonstrate_log_projection():
    """Show Projection + Lens working together on log data."""
    print("=" * 60)
    print("LOG PROJECTION + LENS")
    print("=" * 60)
    print()

    lp = create_log_projection()

    # Feed some events
    import time
    base_ts = time.time()
    events = [
        LogEntry(base_ts + 0, "info", "Server starting"),
        LogEntry(base_ts + 1, "debug", "Loading config", {"path": "/etc/app.conf"}),
        LogEntry(base_ts + 2, "info", "Listening on port 8080"),
        LogEntry(base_ts + 3, "warn", "High memory usage", {"percent": 85}),
        LogEntry(base_ts + 4, "error", "Connection refused", {"host": "db.local"}),
        LogEntry(base_ts + 5, "info", "Retry succeeded"),
        LogEntry(base_ts + 6, "debug", "Request received", {"path": "/api/health"}),
    ]

    for e in events:
        lp.apply(e)

    print(f"Applied {len(events)} log events")
    print(f"Raw state: {lp.state.total} entries, {lp.state.by_level}")
    print()

    # View through different zoom levels
    for zoom in range(4):
        lens = Lens(zoom=zoom)
        view = lp.view(lens)
        print(f"Zoom {zoom}: {view}")
    print()

    # View with scope filter
    errors_only = Lens(zoom=2, scope=frozenset({"error", "warn"}))
    view = lp.view(errors_only)
    print(f"Errors only (zoom=2, scope={{error,warn}}): {view}")
    print()


def demonstrate_health_projection():
    """Show Projection + Lens working together on health data."""
    print("=" * 60)
    print("HEALTH PROJECTION + LENS")
    print("=" * 60)
    print()

    hp = create_health_projection()

    # Feed some events
    import time
    base_ts = time.time()
    containers = ["nginx", "api", "redis", "postgres", "worker"]
    statuses = ["running", "running", "unhealthy", "running", "stopped"]

    for i, (c, s) in enumerate(zip(containers, statuses)):
        hp.apply(HealthEvent(container=c, status=s, ts=base_ts + i))

    # Add some history
    hp.apply(HealthEvent(container="redis", status="running", ts=base_ts + 10))
    hp.apply(HealthEvent(container="worker", status="running", ts=base_ts + 11))

    print(f"Applied {hp.projection.cursor} health events")
    print(f"Current: {hp.state.current}")
    print()

    # View through different zoom levels
    for zoom in range(4):
        lens = Lens(zoom=zoom)
        view = hp.view(lens)
        print(f"Zoom {zoom}: {view}")
    print()

    # View with scope filter (only nginx and api)
    infra_only = Lens(zoom=1, scope=frozenset({"nginx", "api"}))
    view = hp.view(infra_only)
    print(f"Infra only (nginx, api): {view}")
    print()


def demonstrate_per_peer_lens():
    """Show per-peer lens configuration."""
    print("=" * 60)
    print("PER-PEER LENS")
    print("=" * 60)
    print()

    hp = create_health_projection()

    # Feed events
    import time
    base_ts = time.time()
    for i, (c, s) in enumerate([
        ("nginx", "running"),
        ("api", "running"),
        ("redis", "unhealthy"),
    ]):
        hp.apply(HealthEvent(container=c, status=s, ts=base_ts + i))

    # Show view for each peer
    for peer_name, config in PEER_LENS_CONFIGS.items():
        lens = config.create_lens()
        view = hp.view(lens)
        print(f"{peer_name}'s view (zoom={lens.zoom}, scope={lens.scope}):")
        print(f"  {view}")
    print()


def demonstrate_lens_api():
    """Show the Lens API."""
    print("=" * 60)
    print("LENS API")
    print("=" * 60)
    print()

    # Create and modify
    lens = Lens()
    print(f"Default: {lens}")

    lens2 = lens.zoom_in()
    print(f"After zoom_in: {lens2}")

    lens3 = lens2.with_scope(frozenset({"error", "warn"}))
    print(f"After with_scope: {lens3}")

    # Check filtering
    print()
    print(f"lens3.includes('error'): {lens3.includes('error')}")
    print(f"lens3.includes('info'): {lens3.includes('info')}")
    print()

    # Presets
    print("Preset lenses:")
    print(f"  LENS_MINIMAL: {LENS_MINIMAL}")
    print(f"  LENS_SUMMARY: {LENS_SUMMARY}")
    print(f"  LENS_FULL: {LENS_FULL}")
    print(f"  LENS_VERBOSE: {LENS_VERBOSE}")
    print()


# ============================================================================
# PLACEMENT ANALYSIS
# ============================================================================

def analyze_placement():
    """Analyze where Lens should live based on usage patterns."""
    print("=" * 60)
    print("LENS PLACEMENT ANALYSIS")
    print("=" * 60)
    print()

    print("Lens usage patterns:")
    print()
    print("1. CREATION: Lens is created by configuration or user action")
    print("   - Per-peer defaults (PeerLensConfig)")
    print("   - User toggles (d for debug, -/= for zoom)")
    print("   - Preset selection")
    print()
    print("2. APPLICATION: Lens transforms state → view at render time")
    print("   - lens_fn(state, lens) → view")
    print("   - Called in render loop, not fold loop")
    print()
    print("3. STORAGE: Lens can be stored as facts")
    print("   - `emit('lens', zoom=2)` in review_lens.py")
    print("   - Enables persistence, replay, sharing")
    print()

    print("-" * 60)
    print("PLACEMENT OPTIONS:")
    print("-" * 60)
    print()

    print("Option A: ticks (alongside Projection)")
    print("  Structure: Projection handles write-side, Lens handles read-side")
    print("  Conceptual fit: Both are projections (many → fewer)")
    print("  Problem: ticks is about temporal accumulation; Lens is about display")
    print("  Verdict: Partial fit — concept pairing, but different concerns")
    print()

    print("Option B: cells (surface concern)")
    print("  Structure: Lens renders data for display")
    print("  Conceptual fit: Rendering is a cells concern")
    print("  Problem: cells.Lens is widget-specific (Block rendering)")
    print("           Core Lens is data-level (zoom + scope filtering)")
    print("  Verdict: SPLIT — core Lens separate from render Lens")
    print()

    print("Option C: peers (observer configuration)")
    print("  Structure: Lens is per-peer, like horizon/potential")
    print("  Conceptual fit: Lens configures what the observer sees")
    print("  Problem: Peer is identity, Lens is view configuration")
    print("  Verdict: Wrong level — Lens configures view, not identity")
    print()

    print("Option D: specs (alongside Shape)")
    print("  Structure: Shape defines state, Lens defines view")
    print("  Conceptual fit: Both are contracts")
    print("  Problem: Shape is write-contract, Lens is read-transform")
    print("  Verdict: Possible but stretched")
    print()

    print("-" * 60)
    print("RECOMMENDATION:")
    print("-" * 60)
    print()
    print("Split Lens into two concepts:")
    print()
    print("1. CORE LENS (ticks or standalone)")
    print("   - Lens dataclass: zoom + scope")
    print("   - Pure data, no rendering")
    print("   - Pairs conceptually with Projection")
    print()
    print("2. RENDER LENS (cells)")
    print("   - Current cells._lens module")
    print("   - shape_lens, tree_lens, chart_lens")
    print("   - Block rendering at zoom levels")
    print()
    print("Core Lens goes in ticks because:")
    print("  - It pairs with Projection (write-side / read-side)")
    print("  - It's used to project state, which is a ticks concern")
    print("  - It's not about widgets or terminals (cells)")
    print()
    print("cells.Lens stays in cells because:")
    print("  - It renders Blocks for terminal display")
    print("  - It's surface-specific implementation")
    print()


# ============================================================================
# MAIN
# ============================================================================

def main():
    demonstrate_lens_api()
    demonstrate_log_projection()
    demonstrate_health_projection()
    demonstrate_per_peer_lens()
    analyze_placement()

    print("=" * 60)
    print("SUMMARY")
    print("=" * 60)
    print()
    print("1. Lens = zoom + scope, immutable dataclass")
    print("   - zoom: detail level (0=minimal, 1=summary, 2=full, 3+=verbose)")
    print("   - scope: kind filter (None=all, frozenset=specific)")
    print()
    print("2. Projection + Lens are dual:")
    print("   - Projection: Facts → state (write-side, accumulate)")
    print("   - Lens: state → view (read-side, filter/project)")
    print()
    print("3. Per-peer lens works:")
    print("   - Each peer has default lens (role-based)")
    print("   - Any peer can adjust their lens")
    print("   - Lens changes can be facts (persist, replay)")
    print()
    print("4. Placement recommendation:")
    print("   - Core Lens → ticks (pairs with Projection)")
    print("   - Render Lens → cells (Block rendering)")
    print()


if __name__ == "__main__":
    main()
