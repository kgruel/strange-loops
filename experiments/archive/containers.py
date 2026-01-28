"""Container health dashboard: all five atoms, end to end.

Run:
    uv run python experiments/containers.py

Polls the local Docker daemon, folds container status through a Shape,
renders through a Lens on a Surface. q to quit.
"""

from __future__ import annotations

import asyncio
import json
import re

from facts import Fact
from ticks import Stream, Projection
from shapes import Shape, Facet, Fold
from cells import (
    Surface, Block, Style,
    shape_lens,
    join_vertical, border,
)
from peers import Peer


# -- Shape ------------------------------------------------------------------

container_health = Shape(
    name="container-health",
    about="Live container status from Docker",
    input_facets=(
        Facet("container", "str"),
        Facet("image", "str"),
        Facet("status", "str"),
        Facet("health", "str"),
    ),
    state_facets=(
        Facet("containers", "dict"),
        Facet("count", "int"),
    ),
    folds=(
        Fold("upsert", "containers", props={"key": "container"}),
        Fold("count", "count"),
    ),
)


# -- Bridge: Fact → Shape ---------------------------------------------------

def _make_fold(shape: Shape):
    """Extract Fact payload and delegate to shape.apply."""
    def fold(state: dict, fact: Fact) -> dict:
        return shape.apply(state, dict(fact.payload))
    return fold


# -- Source: Docker ---------------------------------------------------------

async def poll_docker() -> list[dict]:
    """Get container info from docker ps."""
    proc = await asyncio.create_subprocess_exec(
        "docker", "ps", "-a", "--format", "{{json .}}",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, _ = await proc.communicate()
    containers = []
    for line in stdout.decode().strip().split("\n"):
        if not line:
            continue
        data = json.loads(line)
        status_str = data.get("Status", "")
        health_match = re.search(r"\((healthy|unhealthy|starting)\)", status_str)
        health = health_match.group(1) if health_match else "none"
        containers.append({
            "container": data.get("Names", ""),
            "image": data.get("Image", ""),
            "status": data.get("State", "unknown"),
            "health": health,
        })
    return containers


async def run_source(stream: Stream, interval: float = 2.0):
    """Poll Docker and emit Facts to stream."""
    try:
        while True:
            containers = await poll_docker()
            for c in containers:
                fact = Fact.of("container-health", **c)
                await stream.emit(fact)
            await asyncio.sleep(interval)
    except asyncio.CancelledError:
        pass


# -- App --------------------------------------------------------------------

class ContainerApp(Surface):
    def __init__(self, stream: Stream, projection: Projection, peer: Peer):
        super().__init__(fps_cap=15)
        self.stream = stream
        self.proj = projection
        self.peer = peer
        self._last_version = -1
        self._width = 80
        self._height = 24
        self._poll_task: asyncio.Task | None = None

    async def on_start(self) -> None:
        self._poll_task = asyncio.create_task(run_source(self.stream))

    def layout(self, width: int, height: int) -> None:
        self._width = width
        self._height = height

    def update(self) -> None:
        if self.proj.version != self._last_version:
            self._last_version = self.proj.version
            self.mark_dirty()

    def render(self) -> None:
        state = self.proj.state
        containers = state.get("containers", {})
        count = state.get("count", 0)

        header = Block.text(
            f" {self.peer.name} — {len(containers)} containers, {count} observations",
            Style(bold=True),
            width=self._width,
        )

        content = shape_lens(containers, zoom=2, width=self._width - 4)
        body = border(content, title="container-health")

        composed = join_vertical(header, body)

        if self._buf is not None:
            self._buf.fill(0, 0, self._buf.width, self._buf.height, " ", Style())
            composed.paint(
                self._buf.region(0, 0, self._buf.width, self._buf.height),
                0, 0,
            )

    def on_key(self, key: str) -> None:
        if key in ("q", "escape"):
            asyncio.ensure_future(self._shutdown())

    async def _shutdown(self) -> None:
        if self._poll_task and not self._poll_task.done():
            self._poll_task.cancel()
            try:
                await self._poll_task
            except asyncio.CancelledError:
                pass
        self.quit()


# -- Main -------------------------------------------------------------------

async def main():
    peer = Peer(name="kyle")

    stream: Stream = Stream()
    proj: Projection = Projection(
        container_health.initial_state(),
        fold=_make_fold(container_health),
    )
    stream.tap(proj)

    app = ContainerApp(stream, proj, peer)
    await app.run()


if __name__ == "__main__":
    asyncio.run(main())
