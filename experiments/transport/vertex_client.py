"""Vertex client: sends facts to a Vertex server.

Run:
    uv run python -m experiments.transport.vertex_client
    uv run python -m experiments.transport.vertex_client --port 9999 --interval 0.5

Connects to 127.0.0.1:9876 by default. Sends periodic health facts,
receives tick facts broadcast by the server.
"""

from __future__ import annotations

import argparse
import asyncio
import signal

from facts import Fact

from .protocol import FactClient


class VertexClient:
    """Client that sends facts and receives tick broadcasts."""

    def __init__(self, host: str, port: int, name: str = "client"):
        self._host = host
        self._port = port
        self._name = name
        self._client = FactClient(host, port, name=name)
        self._stop_event = asyncio.Event()

    async def connect(self) -> bool:
        """Connect to server with retry."""
        while not self._stop_event.is_set():
            if await self._client.connect():
                print(f"[{self._name}] Connected to {self._host}:{self._port}")
                return True
            await asyncio.sleep(1.0)
        return False

    async def send(self, fact: Fact) -> bool:
        """Send a fact to the server."""
        success = await self._client.send(fact)
        if not success and not self._stop_event.is_set():
            # Try to reconnect
            while not self._stop_event.is_set():
                if await self._client.reconnect():
                    print(f"[{self._name}] Reconnected")
                    return await self._client.send(fact)
        return success

    async def receiver_loop(self) -> None:
        """Receive tick facts from server and print them."""
        while not self._stop_event.is_set():
            try:
                fact = await self._client.receive()
                if fact is None:
                    if not self._stop_event.is_set():
                        print(f"[{self._name}] Connection closed by server")
                        # Try to reconnect
                        if await self.connect():
                            continue
                    break
                print(f"[{self._name}] Received {fact.kind}: {dict(fact.payload)}")
            except Exception as e:
                if not self._stop_event.is_set():
                    print(f"[{self._name}] Receiver error: {e}")
                break

    async def sender_loop(self, interval: float) -> None:
        """Send periodic health facts."""
        seq = 0
        while not self._stop_event.is_set():
            seq += 1
            cpu = 0.3 + (seq % 10) * 0.05

            fact = Fact.of("health", observer=self._name, cpu=cpu, seq=seq)
            success = await self.send(fact)
            if success:
                print(f"[{self._name}] Sent health #{seq}: cpu={cpu:.2f}")

            # Every 5 facts, send a boundary to trigger tick
            if seq % 5 == 0:
                boundary = Fact.of("health.boundary", observer=self._name)
                await self.send(boundary)
                print(f"[{self._name}] Sent health.boundary (triggering tick)")

            await asyncio.sleep(interval)

    def stop(self) -> None:
        """Signal stop."""
        self._stop_event.set()

    async def close(self) -> None:
        """Close connection."""
        await self._client.close()


async def main(host: str, port: int, interval: float) -> None:
    """Run the vertex client."""
    client = VertexClient(host, port, name="client")

    print(f"Connecting to vertex server at {host}:{port}")
    print(f"Sending health facts every {interval}s")
    print("Boundary sent every 5 facts (triggers tick broadcast)")
    print("Press Ctrl+C to stop")
    print()

    # Handle SIGINT/SIGTERM gracefully
    def signal_handler():
        print("\n[client] Shutting down...")
        client.stop()

    loop = asyncio.get_event_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, signal_handler)

    # Connect
    if not await client.connect():
        print("[client] Failed to connect")
        return

    # Run sender and receiver concurrently
    try:
        await asyncio.gather(
            client.sender_loop(interval),
            client.receiver_loop(),
        )
    except asyncio.CancelledError:
        pass
    finally:
        await client.close()
        print("[client] Stopped")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Vertex client over TCP")
    parser.add_argument("--host", default="127.0.0.1", help="Server host (default: 127.0.0.1)")
    parser.add_argument("--port", type=int, default=9876, help="Server port (default: 9876)")
    parser.add_argument("--interval", type=float, default=1.0, help="Seconds between facts (default: 1.0)")
    args = parser.parse_args()

    asyncio.run(main(args.host, args.port, args.interval))
