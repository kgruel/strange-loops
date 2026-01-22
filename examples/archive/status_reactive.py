#!/usr/bin/env python3
"""
Reactive rewrite of gruel.network's status.py

Demonstrates the pattern:
- State lives in Signals
- UI derived from Signals (automatic updates)
- Events emitted via reactive bridges (automatic)
- Result built from final state

Compare with the original 675-line status.py:
- No manual _update() calls
- No manual event emission loops
- State -> UI is declarative, not imperative

Run with: uv run examples/status_reactive.py
"""

# /// script
# requires-python = ">=3.11"
# dependencies = [
#     "reaktiv",
#     "rich",
#     "typing_extensions",
#     "ev @ file:///Users/kaygee/Code/ev",
# ]
# [tool.uv.sources]
# reaktiv_cli = { path = "../reaktiv_cli" }
# ///

from __future__ import annotations

import asyncio
import random
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

# Add parent to path for local development
sys.path.insert(0, str(Path(__file__).parent.parent))

from reaktiv_cli import ReactiveEmitter, Signal, Computed, batch
from rich.console import Console
from rich.text import Text
from rich.tree import Tree
from rich.spinner import Spinner

from ev import Result, ListEmitter


# =============================================================================
# DOMAIN TYPES
# =============================================================================


@dataclass(frozen=True)
class ServiceStatus:
    """Status of a single container/service."""

    name: str
    state: str  # running, exited, etc.
    health: str | None  # healthy, unhealthy, None
    uptime_seconds: int | None = None

    @property
    def is_healthy(self) -> bool:
        if self.state != "running":
            return False
        return self.health in (None, "healthy")


@dataclass(frozen=True)
class StackResult:
    """Result of checking a stack."""

    name: str
    status: str  # healthy, unhealthy, error, pending, checking
    services: tuple[ServiceStatus, ...] = ()
    error: str | None = None
    duration_ms: float | None = None

    @property
    def healthy_count(self) -> int:
        return sum(1 for s in self.services if s.is_healthy)

    @property
    def total_count(self) -> int:
        return len(self.services)

    @property
    def unhealthy_services(self) -> list[ServiceStatus]:
        return [s for s in self.services if not s.is_healthy]


# =============================================================================
# UI COMPONENTS (reactive)
# =============================================================================


class StatusTreeComponent:
    """
    Reactive status tree component.

    Reads from a Signal[dict[str, StackResult]] and produces a Rich Tree.
    Automatically re-renders when the signal changes.
    """

    ICONS = {
        "healthy": "\u2713",
        "unhealthy": "\u2717",
        "error": "\u26a0",
        "pending": "\u25cb",
        "checking": "\u25d0",
    }

    STYLES = {
        "healthy": "green",
        "unhealthy": "red",
        "error": "yellow",
        "pending": "dim",
        "checking": "yellow",
    }

    def __init__(
        self,
        stacks: Callable[[], dict[str, StackResult]],
        stack_order: list[str],
    ):
        self._stacks = stacks
        self._stack_order = stack_order

    def render(self) -> Tree:
        """Produce a Rich Tree from current state."""
        stacks = self._stacks()
        root = Tree(Text("Status", style="bold"))

        for name in self._stack_order:
            result = stacks.get(name)

            if result is None or result.status == "pending":
                spinner = Spinner("dots", text=f" {name}...", style="dim")
                root.add(spinner)
                continue

            if result.status == "checking":
                spinner = Spinner("dots", text=f" {name}...", style="yellow")
                node = root.add(spinner)
                for svc in result.services:
                    node.add(Text(f"  \u2022 {svc.name}", style="dim"))
                continue

            node = root.add(self._render_stack_line(result))
            self._add_service_children(node, result)

        return root

    def _render_stack_line(self, result: StackResult) -> Text:
        icon = self.ICONS.get(result.status, "?")
        style = self.STYLES.get(result.status, "white")

        if result.status == "healthy":
            text = Text(f"{icon} {result.name}: {result.healthy_count}/{result.total_count} healthy")
        elif result.status == "unhealthy":
            unhealthy = result.total_count - result.healthy_count
            text = Text(f"{icon} {result.name}: {unhealthy}/{result.total_count} unhealthy")
        elif result.status == "error":
            text = Text(f"{icon} {result.name}: {result.error or 'error'}")
        else:
            text = Text(f"{icon} {result.name}: {result.status}")

        text.stylize(style)
        return text

    def _add_service_children(self, node: Tree, result: StackResult) -> None:
        if result.status not in ("healthy", "unhealthy"):
            return

        for svc in result.unhealthy_services:
            icon = "\u2717" if not svc.is_healthy else "\u2713"
            style = "red" if not svc.is_healthy else "green"
            node.add(Text(f"  {icon} {svc.name}: {svc.state}", style=style))


# =============================================================================
# OPERATION (reactive version)
# =============================================================================


async def check_stack_mock(name: str, on_service: Callable[[ServiceStatus], None]) -> StackResult:
    """
    Mock stack check. In real code, this would SSH and run docker compose ps.

    The key difference from imperative: we call on_service() for each service found,
    which updates a Signal, which automatically triggers UI updates.
    """
    await asyncio.sleep(random.uniform(0.3, 1.5))

    num_services = random.randint(2, 5)
    services = []

    for i in range(num_services):
        await asyncio.sleep(random.uniform(0.1, 0.3))

        is_healthy = random.random() < 0.8
        svc = ServiceStatus(
            name=f"{name}-svc-{i + 1}",
            state="running" if is_healthy else random.choice(["running", "exited"]),
            health="healthy" if is_healthy else random.choice(["unhealthy", None]),
            uptime_seconds=random.randint(100, 100000) if is_healthy else None,
        )
        services.append(svc)
        on_service(svc)

    healthy_count = sum(1 for s in services if s.is_healthy)
    status = "healthy" if healthy_count == len(services) else "unhealthy"

    return StackResult(
        name=name,
        status=status,
        services=tuple(services),
        duration_ms=random.uniform(500, 2000),
    )


async def status_operation_reactive(
    rem: ReactiveEmitter,
    stack_names: list[str],
    concurrency: int = 3,
) -> Result:
    """
    Reactive version of the status operation.

    Key differences from imperative:
    1. State is in Signals, not instance variables
    2. UI updates automatically when Signals change
    3. Events emit automatically via watchers
    4. No manual _update() calls anywhere
    """

    # =========================================================================
    # STATE LAYER (Signals)
    # =========================================================================

    stacks = Signal[dict[str, StackResult]](
        {name: StackResult(name=name, status="pending") for name in stack_names}
    )

    checking_services = Signal[dict[str, list[ServiceStatus]]]({})

    # =========================================================================
    # DERIVED STATE (Computed)
    # =========================================================================

    def merged_stacks() -> dict[str, StackResult]:
        result = dict(stacks())
        for name, services in checking_services().items():
            if name in result and result[name].status == "checking":
                result[name] = StackResult(
                    name=name,
                    status="checking",
                    services=tuple(services),
                )
        return result

    merged = Computed(merged_stacks)

    counts = Computed(
        lambda: {
            "total": len(stacks()),
            "healthy": sum(1 for r in stacks().values() if r.status == "healthy"),
            "unhealthy": sum(1 for r in stacks().values() if r.status == "unhealthy"),
            "error": sum(1 for r in stacks().values() if r.status == "error"),
            "pending": sum(1 for r in stacks().values() if r.status in ("pending", "checking")),
        }
    )

    # =========================================================================
    # UI LAYER (Component)
    # =========================================================================

    tree_component = StatusTreeComponent(merged, stack_names)
    rem.set_ui(tree_component.render)

    # =========================================================================
    # EVENT BRIDGES (automatic emission)
    # =========================================================================

    rem.watch_notable(
        lambda: [r for r in stacks().values() if r.status == "unhealthy"],
        "status.unhealthy_stacks",
        is_notable=lambda lst: len(lst) > 0,
        to_data=lambda lst: {
            "count": len(lst),
            "stacks": [r.name for r in lst],
        },
        level="warn",
    )

    rem.watch_each(
        lambda: {name: r for name, r in stacks().items() if r.status not in ("pending", "checking")},
        "status.stack",
        to_data=lambda name, r: {
            "stack": name,
            "status": r.status,
            "healthy_count": r.healthy_count,
            "total_count": r.total_count,
            "duration_ms": r.duration_ms,
        },
    )

    # =========================================================================
    # EXECUTION
    # =========================================================================

    semaphore = asyncio.Semaphore(concurrency)

    async def check_one(name: str):
        async with semaphore:
            stacks.update(lambda s: {**s, name: StackResult(name=name, status="checking")})
            checking_services.update(lambda cs: {**cs, name: []})

            def on_service(svc: ServiceStatus):
                checking_services.update(lambda cs: {**cs, name: [*cs.get(name, []), svc]})

            try:
                result = await check_stack_mock(name, on_service)
            except Exception as e:
                result = StackResult(name=name, status="error", error=str(e))

            with batch():
                stacks.update(lambda s: {**s, name: result})
                checking_services.update(lambda cs: {k: v for k, v in cs.items() if k != name})

    await asyncio.gather(*[check_one(name) for name in stack_names])

    # =========================================================================
    # RESULT
    # =========================================================================

    c = counts()
    data = {
        "stacks": [
            {
                "name": r.name,
                "status": r.status,
                "healthy_count": r.healthy_count,
                "total_count": r.total_count,
                "services": [
                    {"name": s.name, "state": s.state, "health": s.health, "healthy": s.is_healthy}
                    for s in r.services
                ],
            }
            for r in stacks().values()
        ],
        "counts": c,
    }

    if c["unhealthy"] == 0 and c["error"] == 0:
        return Result.ok(f"{c['healthy']}/{c['total']} stacks healthy", data=data)
    else:
        parts = []
        if c["unhealthy"]:
            parts.append(f"{c['unhealthy']} unhealthy")
        if c["error"]:
            parts.append(f"{c['error']} errors")
        summary = f"{c['healthy']}/{c['total']} stacks healthy ({', '.join(parts)})"
        return Result.error(summary, code=1, data=data)


# =============================================================================
# MAIN
# =============================================================================


def main():
    print("\n" + "=" * 60)
    print("REACTIVE STATUS DEMO")
    print("=" * 60)
    print("\nThis is a reactive rewrite of gruel.network's status.py")
    print("Watch the UI update automatically as checks complete.\n")

    stack_names = ["infra", "media", "dev", "monitoring", "minecraft"]

    emitter = ListEmitter()
    console = Console(stderr=True)

    async def run():
        rem = ReactiveEmitter(emitter, console=console)

        with rem:
            result = await status_operation_reactive(rem, stack_names, concurrency=2)

        return result

    result = asyncio.run(run())
    emitter.finish(result)

    console.print()
    style = "green" if result.is_ok else "red"
    console.print(f"[{style}]{result.summary}[/{style}]")

    console.print("\n[bold]Captured Events:[/bold]")
    for e in emitter.events:
        level_marker = {"warn": "[yellow]\u26a0[/yellow]", "error": "[red]\u2717[/red]"}.get(e.level, " ")
        console.print(f"  {level_marker} {e.signal_name}: {e.data}")

    console.print(f"\n[dim]Total events: {len(emitter.events)}[/dim]")

    return result.code


if __name__ == "__main__":
    raise SystemExit(main())
