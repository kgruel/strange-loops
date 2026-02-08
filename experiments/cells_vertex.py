"""Cells-Vertex integration: counter with undo.

Proves the full loop:
- User input (j/k/u) → emit → Fact
- Fact → Vertex.receive() → fold → state
- state → Tick → render → Block → display

Run:
    uv run python experiments/cells_vertex.py
"""

from __future__ import annotations

import asyncio
import time
from datetime import datetime, timezone

from atoms import Fact
from vertex import Peer, Vertex
from cells import Block, Style, join_vertical, border
from cells.tui import Surface


# Observer identity for this session
USER = Peer("user")


# -- Fold --------------------------------------------------------------------

def counter_fold(state: dict, payload: dict) -> dict:
    """Fold action or undo into counter state.

    Actions:
    - delta present: increment/decrement count, append to history
    - undo present: revert last action from history
    """
    if "delta" in payload:
        delta = payload["delta"]
        return {
            "count": state["count"] + delta,
            "history": state["history"] + [delta],
            "last_ts": payload.get("ts", state["last_ts"]),
        }
    elif payload.get("undo"):
        if state["history"]:
            last = state["history"][-1]
            return {
                "count": state["count"] - last,
                "history": state["history"][:-1],
                "last_ts": payload.get("ts", state["last_ts"]),
            }
    return state


INITIAL = {"count": 0, "history": [], "last_ts": 0.0}


# -- Render ------------------------------------------------------------------

DIM = Style(dim=True)
BOLD = Style(bold=True)
COUNT_STYLE = Style(fg="cyan", bold=True)
HISTORY_STYLE = Style(fg="green")
PLUS_STYLE = Style(fg="green")
MINUS_STYLE = Style(fg="red")


def render_counter(state: dict, width: int) -> Block:
    """Render counter state to Block."""
    lines: list[Block] = []

    # Count display
    count_text = f"Counter: {state['count']}"
    lines.append(Block.text(count_text, COUNT_STYLE, width=width))
    lines.append(Block.empty(width, 1))

    # History header
    lines.append(Block.text("History", BOLD, width=width))
    lines.append(Block.text("─" * min(8, width), DIM, width=width))

    # History entries (last 5, reversed for newest-first)
    history = state["history"]
    if history:
        for i, delta in enumerate(reversed(history[-5:])):
            idx = len(history) - 1 - i
            sign = "+" if delta > 0 else ""
            style = PLUS_STYLE if delta > 0 else MINUS_STYLE
            text = f"[{idx}] {sign}{delta}"
            lines.append(Block.text(text, style, width=width))
    else:
        lines.append(Block.text("(empty)", DIM, width=width))

    lines.append(Block.empty(width, 1))

    # Last action timestamp
    if state["last_ts"] > 0:
        ts_str = datetime.fromtimestamp(state["last_ts"]).strftime("%H:%M:%S")
        lines.append(Block.text(f"last action: {ts_str}", DIM, width=width))
    else:
        lines.append(Block.text("last action: --:--:--", DIM, width=width))

    # Help
    lines.append(Block.empty(width, 1))
    lines.append(Block.text("j/k: dec/inc  u: undo  q: quit", DIM, width=width))

    return join_vertical(*lines)


# -- App ---------------------------------------------------------------------

class CounterApp(Surface):
    """Interactive counter that demonstrates cells-vertex integration."""

    def __init__(self):
        super().__init__(fps_cap=30, on_emit=self._handle_emit)
        self._w = 40
        self._h = 16

        # Vertex setup: single kind "counter"
        self.vertex = Vertex("counter-app")
        self.vertex.register("counter", INITIAL, counter_fold)

        # Latest tick for rendering
        self.current_tick = None

    def _handle_emit(self, kind: str, data: dict) -> None:
        """Convert UI events to facts, fold, tick.

        This is where cells → vertex happens:
        1. Surface.emit() calls this callback
        2. We create a Fact from the emission
        3. Vertex receives and folds the fact
        4. We tick to snapshot the state
        5. mark_dirty() triggers re-render
        """
        fact = None

        if kind == "counter.action":
            fact = Fact.of("counter", USER.name, delta=data["delta"], ts=time.time())
        elif kind == "counter.undo":
            fact = Fact.of("counter", USER.name, undo=True, ts=time.time())

        if fact is not None:
            self.vertex.receive(fact, USER)
            self.current_tick = self.vertex.tick("counter", datetime.now(timezone.utc))
            self.mark_dirty()

    def layout(self, width: int, height: int) -> None:
        self._w = width
        self._h = height

    def render(self) -> None:
        if self._buf is None:
            return

        # Get state from tick, or use initial
        if self.current_tick:
            state = self.current_tick.payload.get("counter", INITIAL)
        else:
            state = INITIAL

        # Render state to block
        inner_w = min(self._w - 4, 36)  # account for border
        content = render_counter(state, inner_w)
        block = border(content, title="cells + vertex")

        # Clear and paint
        self._buf.fill(0, 0, self._buf.width, self._buf.height, " ", Style())
        block.paint(self._buf.region(0, 0, self._buf.width, self._buf.height), 0, 0)

    def on_key(self, key: str) -> None:
        """Handle keypresses by emitting domain facts."""
        if key in ("j", "Down"):
            self.emit("counter.action", delta=-1)
        elif key in ("k", "Up"):
            self.emit("counter.action", delta=+1)
        elif key == "u":
            self.emit("counter.undo")
        elif key in ("q", "escape"):
            self.quit()


# -- Main --------------------------------------------------------------------

async def main():
    app = CounterApp()
    await app.run()


if __name__ == "__main__":
    asyncio.run(main())
