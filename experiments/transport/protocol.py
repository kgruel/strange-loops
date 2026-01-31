"""Wire protocol and transport classes for Fact transmission over TCP.

Wire format: 4-byte big-endian length prefix + JSON-encoded Fact.

Classes:
- FactConnection: single TCP connection, send/receive facts
- FactClient: client with reconnection logic
- FactServer: server accepting multiple connections, dispatching facts

Extracted from experiments/network_transport.py for reuse.
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from typing import Callable

from data import Fact


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
    """Client that connects to a server and sends/receives facts.

    Handles reconnection with exponential backoff.
    """

    def __init__(self, host: str, port: int, name: str = "client"):
        self._host = host
        self._port = port
        self._name = name
        self._conn: FactConnection | None = None
        self._backoff = 1.0
        self._max_backoff = 30.0

    @property
    def connected(self) -> bool:
        """True if currently connected."""
        return self._conn is not None

    async def connect(self) -> bool:
        """Connect to server. Returns True on success."""
        try:
            reader, writer = await asyncio.open_connection(self._host, self._port)
            self._conn = FactConnection(reader, writer, name=self._name)
            self._backoff = 1.0
            return True
        except (ConnectionRefusedError, OSError) as e:
            print(f"[{self._name}] Connection failed: {e}")
            return False

    async def send(self, fact: Fact) -> bool:
        """Send a fact. Returns True on success."""
        if self._conn is None:
            return False
        try:
            await self._conn.send(fact)
            return True
        except (ConnectionResetError, BrokenPipeError, OSError):
            print(f"[{self._name}] Connection lost")
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
    """Server that accepts connections and dispatches facts to a handler.

    Supports broadcasting facts to all connected clients.
    """

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
