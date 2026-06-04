"""WebSocket progress broadcasting."""

from __future__ import annotations

import asyncio
from typing import Any

from fastapi import WebSocket


class ConnectionManager:
    """Tracks active WebSocket connections per project and broadcasts events."""

    def __init__(self) -> None:
        self._connections: dict[int, set[WebSocket]] = {}
        self._lock = asyncio.Lock()

    async def connect(self, project_id: int, ws: WebSocket) -> None:
        await ws.accept()
        async with self._lock:
            self._connections.setdefault(project_id, set()).add(ws)

    async def disconnect(self, project_id: int, ws: WebSocket) -> None:
        async with self._lock:
            conns = self._connections.get(project_id)
            if conns and ws in conns:
                conns.discard(ws)
            if conns is not None and not conns:
                self._connections.pop(project_id, None)

    async def emit(self, project_id: int, event: dict[str, Any]) -> None:
        """Send a JSON event to all listeners of ``project_id``."""
        conns = list(self._connections.get(project_id, set()))
        for ws in conns:
            try:
                await ws.send_json(event)
            except Exception:  # noqa: BLE001 - drop broken connections silently
                await self.disconnect(project_id, ws)


manager = ConnectionManager()
