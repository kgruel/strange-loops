"""Real network transport: Facts over TCP.

Builds on network_observer.py patterns with actual TCP transport:
- Wire format = 4-byte length prefix + JSON (Fact.to_dict())
- Async TCP using asyncio streams
- Connection lifecycle: connect, reconnect, disconnect
- Two processes exchanging facts

Run:
    # Terminal 1 — start server
    uv run python experiments/network_transport.py server

    # Terminal 2 — start client
    uv run python experiments/network_transport.py client

    # Or run both in one process for testing
    uv run python experiments/network_transport.py demo
"""

from __future__ import annotations

import asyncio
import json
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable

from facts import Fact
from ticks import Vertex


# =============================================================================
# WIRE PROTOCOL
# =============================================================================

def encode_fact(fact: Fact) -> bytes:
    """Encode Fact for transmission: 4-byte length + JSON payload."""
    payload = json.dumps(fact.to_dict()).encode("utf-8")
    return len(payload).to_bytes(4, "big") + payload


async def decode_fact(reader: asyncio.StreamReader) -> Fact | None:
    """Decode Fact from stream. Returns None on EOF."""
    try:
        length_bytes = await reader.readexactly(4)
    except asyncio.IncompleteReadError:
        return None

    length = int.from_bytes(length_bytes, "big")
    try:
        payload_bytes = await reader.readexactly(length)
    except asyncio.IncompleteReadError:
        return None

    data = json.loads(payload_bytes.decode("utf-8"))
    return Fact.from_dict(data)


# =============================================================================
# TRANSPORT CLASSES
# =============================================================================

@dataclass
class FactConnection:
    """A single TCP connection that can send and receive facts."""

    reader: asyncio.StreamReader
    writer: asyncio.StreamWriter
    name: str = ""

    async def send(self, fact: Fact) -> None:
        """Send a fact over this connection."""
        self.writer.write(encode_fact(fact))
        await self.writer.drain()

    async def receive(self) -> Fact | None:
        """Receive a fact. Returns None on EOF/disconnect."""
        return await decode_fact(self.reader)

    async def close(self) -> None:
        """Close the connection."""
        self.writer.close()
        await self.writer.wait_closed()

    @property
    def remote(self) -> str:
        """Remote address as string."""
        peername = self.writer.get_extra_info("peername")
        return f"{peername[0]}:{peername[1]}" if peername else "unknown"


class FactClient:
    """Client that connects to a server and sends facts.

    Handles reconnection with exponential backoff.
    """

    def __init__(self, host: str, port: int, name: str = "client"):
        self._host = host
        self._port = port
        self._name = name
        self._conn: FactConnection | None = None
        self._backoff = 1.0  # Initial backoff in seconds
        self._max_backoff = 30.0

    async def connect(self) -> bool:
        """Connect to server. Returns True on success."""
        try:
            reader, writer = await asyncio.open_connection(self._host, self._port)
            self._conn = FactConnection(reader, writer, name=self._name)
            self._backoff = 1.0  # Reset backoff on success
            return True
        except (ConnectionRefusedError, OSError) as e:
            print(f"[{self._name}] Connection failed: {e}")
            return False

    async def send(self, fact: Fact) -> bool:
        """Send a fact, reconnecting if needed. Returns True on success."""
        if self._conn is None:
            if not await self.connect():
                return False

        try:
            await self._conn.send(fact)
            return True
        except (ConnectionResetError, BrokenPipeError, OSError):
            print(f"[{self._name}] Connection lost, will reconnect")
            self._conn = None
            return False

    async def receive(self) -> Fact | None:
        """Receive a fact from server."""
        if self._conn is None:
            return None
        return await self._conn.receive()

    async def reconnect(self) -> bool:
        """Reconnect with exponential backoff."""
        print(f"[{self._name}] Reconnecting in {self._backoff:.1f}s...")
        await asyncio.sleep(self._backoff)
        self._backoff = min(self._backoff * 2, self._max_backoff)
        return await self.connect()

    async def close(self) -> None:
        """Close the connection."""
        if self._conn:
            await self._conn.close()
            self._conn = None


class FactServer:
    """Server that accepts connections and dispatches facts to a handler."""

    def __init__(self, host: str, port: int, name: str = "server"):
        self._host = host
        self._port = port
        self._name = name
        self._server: asyncio.Server | None = None
        self._handler: Callable[[Fact, FactConnection], None] | None = None
        self._connections: list[FactConnection] = []

    def on_fact(self, handler: Callable[[Fact, FactConnection], None]) -> None:
        """Register handler called when a fact is received."""
        self._handler = handler

    async def start(self) -> None:
        """Start listening for connections."""
        self._server = await asyncio.start_server(
            self._handle_connection,
            self._host,
            self._port,
        )
        addr = self._server.sockets[0].getsockname()
        print(f"[{self._name}] Listening on {addr[0]}:{addr[1]}")

    async def _handle_connection(
        self,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
    ) -> None:
        """Handle a single client connection."""
        conn = FactConnection(reader, writer, name=f"{self._name}-conn")
        self._connections.append(conn)
        print(f"[{self._name}] Client connected from {conn.remote}")

        try:
            while True:
                fact = await conn.receive()
                if fact is None:
                    break
                if self._handler:
                    self._handler(fact, conn)
        except Exception as e:
            print(f"[{self._name}] Connection error: {e}")
        finally:
            print(f"[{self._name}] Client disconnected: {conn.remote}")
            self._connections.remove(conn)
            await conn.close()

    async def broadcast(self, fact: Fact) -> None:
        """Send a fact to all connected clients."""
        for conn in self._connections:
            try:
                await conn.send(fact)
            except Exception:
                pass  # Connection will be cleaned up in handler

    async def stop(self) -> None:
        """Stop the server and close all connections."""
        if self._server:
            self._server.close()
            await self._server.wait_closed()
        for conn in self._connections:
            await conn.close()
        self._connections.clear()


# =============================================================================
# DEMO: TWO VERTICES EXCHANGING FACTS
# =============================================================================

def health_fold(state: dict, payload) -> dict:
    """Fold health observations."""
    count = state.get("count", 0) + 1
    # payload is fact.payload (a MappingProxyType or dict)
    cpu = payload.get("cpu") if hasattr(payload, "get") else None
    seq = payload.get("seq") if hasattr(payload, "get") else None
    return {
        "count": count,
        "last_cpu": cpu,
        "last_seq": seq,
    }


async def run_server(host: str, port: int, stop_event: asyncio.Event) -> None:
    """Server process: receives health facts, folds them."""

    vertex = Vertex("beta")
    vertex.register("health", {"count": 0}, health_fold)

    server = FactServer(host, port, name="server")

    def handle_fact(fact: Fact, conn: FactConnection) -> None:
        vertex.receive(fact)
        state = vertex.state("health")
        print(f"[server] Received {fact.kind} from {fact.observer} | state: {state}")

    server.on_fact(handle_fact)
    await server.start()

    # Wait for stop signal
    await stop_event.wait()
    await server.stop()
    print("[server] Stopped")


async def run_client(host: str, port: int, stop_event: asyncio.Event) -> None:
    """Client process: sends health facts periodically."""

    vertex = Vertex("alpha")
    vertex.register("health", {"count": 0}, health_fold)

    client = FactClient(host, port, name="client")

    # Initial connection with retry
    while not stop_event.is_set():
        if await client.connect():
            print(f"[client] Connected to {host}:{port}")
            break
        await asyncio.sleep(1.0)

    # Send health facts
    seq = 0
    while not stop_event.is_set():
        seq += 1
        cpu = 0.3 + (seq % 10) * 0.05  # Varying CPU values

        fact = Fact.of("health", observer="alpha", cpu=cpu, seq=seq)
        vertex.receive(fact)

        success = await client.send(fact)
        if success:
            print(f"[client] Sent health fact #{seq}: cpu={cpu:.2f}")
        else:
            # Try to reconnect
            while not stop_event.is_set():
                if await client.reconnect():
                    print("[client] Reconnected")
                    break

        await asyncio.sleep(1.0)

    await client.close()
    print("[client] Stopped")


async def demo_in_process() -> None:
    """Run server and client in same process for testing."""

    print("=" * 60)
    print("Network Transport Demo (in-process)")
    print("=" * 60)
    print()

    host = "127.0.0.1"
    port = 9876
    stop_event = asyncio.Event()

    # Start server and client as concurrent tasks
    server_task = asyncio.create_task(run_server(host, port, stop_event))

    # Give server time to start
    await asyncio.sleep(0.1)

    client_task = asyncio.create_task(run_client(host, port, stop_event))

    # Run for 5 seconds
    await asyncio.sleep(5.0)

    # Stop
    stop_event.set()
    await asyncio.gather(server_task, client_task)

    print()
    print("=" * 60)
    print("Demo complete")
    print("=" * 60)


async def standalone_server() -> None:
    """Run as standalone server."""
    host = "127.0.0.1"
    port = 9876
    stop_event = asyncio.Event()

    print("Starting server... (Ctrl+C to stop)")

    try:
        await run_server(host, port, stop_event)
    except KeyboardInterrupt:
        stop_event.set()


async def standalone_client() -> None:
    """Run as standalone client."""
    host = "127.0.0.1"
    port = 9876
    stop_event = asyncio.Event()

    print("Starting client... (Ctrl+C to stop)")

    try:
        await run_client(host, port, stop_event)
    except KeyboardInterrupt:
        stop_event.set()


# =============================================================================
# MAIN
# =============================================================================

def main():
    if len(sys.argv) < 2:
        print("Usage: python network_transport.py [server|client|demo]")
        print()
        print("  server  - Run as TCP server (listens on 127.0.0.1:9876)")
        print("  client  - Run as TCP client (connects to 127.0.0.1:9876)")
        print("  demo    - Run both in same process for testing")
        sys.exit(1)

    mode = sys.argv[1]

    if mode == "server":
        asyncio.run(standalone_server())
    elif mode == "client":
        asyncio.run(standalone_client())
    elif mode == "demo":
        asyncio.run(demo_in_process())
    else:
        print(f"Unknown mode: {mode}")
        sys.exit(1)


if __name__ == "__main__":
    main()
