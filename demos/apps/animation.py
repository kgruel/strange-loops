#!/usr/bin/env python3
# /// script
# requires-python = ">=3.11"
# dependencies = ["painted"]
# ///
"""Animation — update() + mark_dirty() driven rendering.

This demo shows the other half of the Surface render loop: timer-driven state
changes. `update()` runs every iteration; when it changes state, it must call
`mark_dirty()` to trigger a re-render even when there's no input.

Controls:
  space  pause/resume
  r      reset
  q      quit

Run: uv run demos/apps/animation.py
"""

from __future__ import annotations

import asyncio

from painted import Style
from painted.tui import Surface
from painted.views import ProgressState, SpinnerState, progress_bar, spinner


class AnimationApp(Surface):
    def __init__(self) -> None:
        super().__init__(fps_cap=20)
        self.paused = False
        self._started = False  # keep first frame at the initial state

        self.frame = 0
        self.counter = 0
        self.spinner_state = SpinnerState()
        self.progress_state = ProgressState(value=0.0)

    def update(self) -> None:
        if self.paused:
            return

        if not self._started:
            self._started = True
            return

        self.frame += 1

        self.spinner_state = self.spinner_state.tick()

        next_value = self.progress_state.value + 0.03
        if next_value >= 1.0:
            next_value = 0.0
        self.progress_state = self.progress_state.set(next_value)

        self.counter = (self.counter + 1) % 10_000

        self.mark_dirty()

    def render(self) -> None:
        self._buf.fill(0, 0, self._buf.width, self._buf.height, " ", Style())

        status = f" Animation Demo | frame={self.frame:04d} | {'PAUSED' if self.paused else 'RUNNING'} "
        self._buf.put_text(0, 0, status[: self._buf.width], Style(fg="black", bg="white"))

        y = 2
        self._buf.put_text(2, y, "update() advances state; mark_dirty() triggers render()", Style(dim=True))
        y += 2

        self._buf.put_text(2, y, "Spinner:", Style(dim=True))
        spinner(self.spinner_state, style=Style(fg="cyan", bold=True)).paint(self._buf, 12, y)
        self._buf.put_text(14, y, "tick() each update", Style())
        y += 2

        self._buf.put_text(2, y, "Progress:", Style(dim=True))
        bar_w = max(10, min(40, self._buf.width - 18))
        progress_bar(
            self.progress_state,
            width=bar_w,
            filled_style=Style(fg="green", bold=True),
            empty_style=Style(dim=True),
        ).paint(self._buf, 12, y)
        pct = int(self.progress_state.value * 100)
        self._buf.put_text(12 + bar_w + 1, y, f"{pct:3d}%", Style())
        y += 2

        self._buf.put_text(2, y, "Counter:", Style(dim=True))
        self._buf.put_text(12, y, f"{self.counter}", Style(fg="yellow"))

        controls = " space: pause/resume | r: reset | q: quit "
        self._buf.put_text(0, self._buf.height - 1, controls[: self._buf.width], Style(dim=True))

    def on_key(self, key: str) -> None:
        if key == "q":
            self.quit()
            return
        if key == "space":
            self.paused = not self.paused
            return
        if key == "r":
            self.paused = False
            self._started = False
            self.frame = 0
            self.counter = 0
            self.spinner_state = SpinnerState()
            self.progress_state = ProgressState(value=0.0)


async def main() -> None:
    await AnimationApp().run()


if __name__ == "__main__":
    asyncio.run(main())
