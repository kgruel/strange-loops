"""Base simulator: async lifecycle with state machine, crash/restart, and rate control."""

from __future__ import annotations

import asyncio
import random
from enum import Enum
from typing import Callable


class SimState(Enum):
    STOPPED = "stopped"
    STARTING = "starting"
    RUNNING = "running"
    STOPPING = "stopping"
    CRASHED = "crashed"


class BaseSimulator:
    """Async simulator with state machine lifecycle and rate-aware crash/restart.

    Subclass and implement:
      - emit_event(message, level): called to emit log-like events during RUNNING
      - on_state_change(from_state, to_state): called on every state transition
      - generate_messages(): override to yield (level, message) tuples for the run loop

    The lifecycle:
      STOPPED -> STARTING -> RUNNING (emitting events, may crash) -> STOPPING -> STOPPED
      On crash: RUNNING -> CRASHED, then auto-restart after delay.
    """

    def __init__(
        self,
        entity_id: str,
        *,
        rate_multiplier: Callable[[], float] = lambda: 1.0,
        crash_prob: float = 0.05,
        event_freq: float = 1.0,
    ):
        self.entity_id = entity_id
        self._rate_multiplier = rate_multiplier
        self.crash_prob = crash_prob
        self.event_freq = event_freq
        self._task: asyncio.Task | None = None
        self._stop_requested = False

    @property
    def is_running(self) -> bool:
        return self._task is not None and not self._task.done()

    async def start(self) -> None:
        self._stop_requested = False
        self._task = asyncio.create_task(self._run())

    async def stop(self) -> None:
        self._stop_requested = True
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

    # -------------------------------------------------------------------------
    # Override points
    # -------------------------------------------------------------------------

    def emit_event(self, message: str, level: str = "info") -> None:
        """Subclass implements to record events (e.g., add to EventStore)."""
        raise NotImplementedError

    def on_state_change(self, from_state: SimState, to_state: SimState) -> None:
        """Subclass implements to record state transitions."""
        raise NotImplementedError

    def generate_message(self) -> tuple[str, str]:
        """Return (level, message) for the next log event.

        Default: generic messages. Override for domain-specific content.
        """
        messages = [
            ("info", "Processing request"),
            ("info", "Operation completed"),
            ("warn", "High resource usage"),
            ("debug", "Heartbeat"),
        ]
        return random.choice(messages)

    # -------------------------------------------------------------------------
    # Lifecycle
    # -------------------------------------------------------------------------

    async def _run(self) -> None:
        prev_state = SimState.STOPPED

        while not self._stop_requested:
            # STARTING
            self.on_state_change(prev_state, SimState.STARTING)
            start_delay = random.uniform(0.5, 2.0)
            await asyncio.sleep(start_delay / self._rate_multiplier())

            # RUNNING
            self.on_state_change(SimState.STARTING, SimState.RUNNING)

            crashed = False
            try:
                while not self._stop_requested:
                    level, message = self.generate_message()
                    self.emit_event(message, level)

                    # Rate-aware crash probability
                    effective_crash_prob = self.crash_prob / self._rate_multiplier()
                    if random.random() < effective_crash_prob:
                        self.emit_event("Fatal error: process terminated unexpectedly", "error")
                        self.on_state_change(SimState.RUNNING, SimState.CRASHED)
                        crashed = True
                        break

                    # Rate-scaled delay between events
                    base_delay = 1.0 / self.event_freq
                    delay = base_delay / self._rate_multiplier() + random.uniform(-0.2, 0.5)
                    await asyncio.sleep(max(0.01, delay))

            except asyncio.CancelledError:
                break

            if crashed:
                # Auto-restart after delay
                restart_delay = random.uniform(2.0, 3.0) / self._rate_multiplier()
                await asyncio.sleep(restart_delay)
                prev_state = SimState.CRASHED
                continue

            break

        # Graceful stop
        if self._stop_requested:
            self.on_state_change(SimState.RUNNING, SimState.STOPPING)
            await asyncio.sleep(random.uniform(0.3, 1.0))
            self.on_state_change(SimState.STOPPING, SimState.STOPPED)
