# -*- coding: utf-8 -*-
"""
WebSocket Extension Bridge.

WebSocket server that Chrome extension connects to.
Listens on port 9877 and handles task communication.
"""

import asyncio
import json
import logging
import time
import uuid
from dataclasses import dataclass, field
from typing import Optional, Dict, Any, Set

import websockets

logger = logging.getLogger(__name__)


@dataclass
class FetchTask:
    id: str
    url: str
    options: Dict[str, Any] = field(default_factory=dict)
    created_at: float = field(default_factory=time.time)


@dataclass
class TaskResult:
    task_id: str
    success: bool
    url: str
    final_url: str
    status: int
    content: list
    error: Optional[str] = None
    duration: float = 0.0


class ExtensionBridge:
    """WebSocket bridge server that Chrome extension connects to."""

    def __init__(self, host: str = "localhost", port: int = 9877):
        self.host = host
        self.port = port
        self.ws_url = f"ws://{host}:{port}"
        
        # WebSocket server
        self.server = None
        self.ws_clients: Set[websockets.WebSocketServerProtocol] = set()
        
        # Task management
        self._pending_tasks: Dict[str, FetchTask] = {}
        self._results: Dict[str, TaskResult] = {}
        self._result_events: Dict[str, asyncio.Event] = {}
        self._lock = asyncio.Lock()
        self._running = False

    async def start(self) -> None:
        """Start WebSocket server and listen for extension connections."""
        if self._running:
            return

        try:
            self.server = await websockets.serve(
                self._handle_connection,
                self.host,
                self.port,
            )
            self._running = True
            logger.info(f"WebSocket server started on {self.ws_url}")
        except Exception as e:
            logger.error(f"Failed to start WebSocket server: {e}")
            raise

    async def stop(self) -> None:
        """Stop WebSocket server and close all connections."""
        self._running = False
        
        # Close all client connections
        for ws in self.ws_clients.copy():
            await ws.close()
        self.ws_clients.clear()
        
        # Stop server
        if self.server:
            self.server.close()
            await self.server.wait_closed()
            self.server = None
        
        logger.info("WebSocket server stopped")

    async def _handle_connection(self, websocket, path=None) -> None:
        """Handle a new extension WebSocket connection."""
        self.ws_clients.add(websocket)
        logger.info(f"Extension connected, total clients: {len(self.ws_clients)}")
        
        try:
            async for message in websocket:
                try:
                    data = json.loads(message)
                    msg_type = data.get("type")

                    if msg_type == "ready":
                        logger.info("Extension reported ready")

                    elif msg_type == "result":
                        result = TaskResult(
                            task_id=data["taskId"],
                            success=data["success"],
                            url=data["url"],
                            final_url=data["finalUrl"],
                            status=data["status"],
                            content=data.get("content", []),
                            error=data.get("error"),
                            duration=data.get("duration", 0.0),
                        )
                        async with self._lock:
                            self._results[result.task_id] = result
                            if result.task_id in self._result_events:
                                self._result_events[result.task_id].set()
                                logger.info(f"Task {result.task_id} result received")

                except Exception as e:
                    logger.error(f"Failed to parse WebSocket message: {e}")
        except websockets.exceptions.ConnectionClosed:
            pass
        finally:
            self.ws_clients.discard(websocket)
            logger.info(f"Extension disconnected, total clients: {len(self.ws_clients)}")

    async def _broadcast(self, message: str) -> None:
        """Send message to all connected extensions."""
        if not self.ws_clients:
            logger.warning("No extensions connected")
            return
        
        for ws in self.ws_clients.copy():
            try:
                await ws.send(message)
            except websockets.exceptions.ConnectionClosed:
                self.ws_clients.discard(ws)

    async def fetch(
        self,
        url: str,
        options: Optional[Dict[str, Any]] = None,
        timeout: float = 60.0,
    ) -> TaskResult:
        """Submit a fetch task and wait for result."""
        if not self._running:
            raise RuntimeError("WebSocket server not started")

        if not self.ws_clients:
            raise RuntimeError("No extension connected")

        task_id = str(uuid.uuid4())[:8]
        event = asyncio.Event()

        async with self._lock:
            self._result_events[task_id] = event
            self._pending_tasks[task_id] = FetchTask(id=task_id, url=url, options=options or {})

        # Send task to all connected extensions
        task_message = json.dumps({
            "type": "task",
            "task": {
                "id": task_id,
                "url": url,
                "options": options or {},
            }
        })
        
        await self._broadcast(task_message)
        logger.info(f"Task {task_id} sent: {url}")

        try:
            await asyncio.wait_for(event.wait(), timeout=timeout)
        except asyncio.TimeoutError:
            logger.warning(f"Task {task_id} timed out")
            raise TimeoutError(f"Task {task_id} timed out after {timeout}s")
        finally:
            async with self._lock:
                self._pending_tasks.pop(task_id, None)
                self._result_events.pop(task_id, None)

        async with self._lock:
            result = self._results.pop(task_id, None)

        if result is None:
            raise RuntimeError(f"No result for task {task_id}")

        return result

    @property
    def is_connected(self) -> bool:
        """Check if any extension is connected."""
        return self._running and len(self.ws_clients) > 0


# Global bridge
_bridge: Optional[ExtensionBridge] = None
_lock = asyncio.Lock()


async def get_bridge(host: str = "localhost", port: int = 9877) -> ExtensionBridge:
    """Get or create the global extension bridge server."""
    global _bridge
    async with _lock:
        if _bridge is None:
            _bridge = ExtensionBridge(host=host, port=port)
    return _bridge


async def close_bridge() -> None:
    """Close the global extension bridge server."""
    global _bridge
    async with _lock:
        if _bridge:
            await _bridge.stop()
            _bridge = None
