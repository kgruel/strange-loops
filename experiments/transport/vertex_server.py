"""Vertex server: hosts a Vertex over TCP.

Run:
    uv run python -m experiments.transport.vertex_server
    uv run python -m experiments.transport.vertex_server --port 9999

Listens on 127.0.0.1:9876 by default. Receives facts from clients,
routes them through a Vertex, broadcasts resulting ticks back to all clients.
"""

from __future__ import annotations

import argparse
import asyncio
import signal

from atoms import Fact
from engine import Vertex

from .protocol import FactConnection, FactServer


def health_fold(state: dict, payload) -> dict:
    """Fold health observations into running state."""
    count = state.get("count", 0) + 1
    cpu = payload.get("cpu") if hasattr(payload, "get") else None
    seq = payload.get("seq") if hasattr(payload, "get") else None
    return {
        "count": count,
        "last_cpu": cpu,
        "last_seq": seq,
    }


class VertexServer:
    """Server hosting a Vertex that processes facts and broadcasts ticks."""

    def __init__(self, host: str, port: int, name: str = "vertex"):
        self._host = host
        self._port = port
        self._name = name
        self._vertex = Vertex(name)
        self._server = FactServer(host, port, name=name)
        self._server.on_fact(self._handle_fact)

    def register(
        self,
        kind: str,
        initial,
        fold,
        *,
        boundary: str | None = None,
        reset: bool = True,
    ) -> None:
        """Register a fold on the hosted Vertex."""
        self._vertex.register(kind, initial, fold, boundary=boundary, reset=reset)

    def _handle_fact(self, fact: Fact, conn: FactConnection) -> None:
        """Handle incoming fact: route through Vertex, broadcast tick if produced."""
        print(f"[{self._name}] Received {fact.kind} from {fact.observer}")

        tick = self._vertex.receive(fact)

        state = self._vertex.state(fact.kind) if fact.kind in self._vertex.kinds else None
        if state is not None:
            print(f"[{self._name}]   state: {state}")

        if tick is not None:
            print(f"[{self._name}]   tick produced: {tick.name}")
            tick_fact = self._vertex.to_fact(tick)
            # Schedule broadcast (we're in sync handler, need to schedule async)
            asyncio.create_task(self._server.broadcast(tick_fact))

    async def start(self) -> None:
        """Start the server."""
        await self._server.start()

    async def stop(self) -> None:
        """Stop the server."""
        await self._server.stop()

    async def run_forever(self) -> None:
        """Run until cancelled."""
        await self.start()
        try:
            await asyncio.Event().wait()  # Wait forever
        finally:
            await self.stop()


async def main(host: str, port: int) -> None:
    """Run the vertex server."""
    server = VertexServer(host, port, name="server")

    # Register folds
    server.register(
        "health",
        {"count": 0},
        health_fold,
        boundary="health.boundary",
        reset=True,
    )

    print(f"Starting vertex server on {host}:{port}")
    print("Registered folds: health (boundary: health.boundary)")
    print("Press Ctrl+C to stop")
    print()

    # Handle SIGINT/SIGTERM gracefully
    stop_event = asyncio.Event()

    def signal_handler():
        print("\n[server] Shutting down...")
        stop_event.set()

    loop = asyncio.get_event_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, signal_handler)

    await server.start()

    # Wait for stop signal
    await stop_event.wait()
    await server.stop()
    print("[server] Stopped")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Vertex server over TCP")
    parser.add_argument("--host", default="127.0.0.1", help="Host to bind (default: 127.0.0.1)")
    parser.add_argument("--port", type=int, default=9876, help="Port to listen on (default: 9876)")
    args = parser.parse_args()

    asyncio.run(main(args.host, args.port))
