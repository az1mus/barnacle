# -*- coding: utf-8 -*-
"""
WebSocket Extension Bridge.

Replaces HTTP polling with WebSocket for real-time task communication.
"""

import asyncio
import json
import logging
import time
import uuid
from dataclasses import dataclass, field
from typing import Optional, Dict, Any

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
    """WebSocket bridge to Chrome extension."""

    def __init__(self, ws_url: str = "ws://localhost:9877"):
        self.ws_url = ws_url
        self.ws: Optional[websockets.WebSocketClientProtocol] = None
        self._pending_tasks: Dict[str, FetchTask] = {}
        self._results: Dict[str, TaskResult] = {}
        self._result_events: Dict[str, asyncio.Event] = {}
        self._lock = asyncio.Lock()
        self._running = False
        self._recv_task: Optional[asyncio.Task] = None

    async def start(self) -> None:
        """Connect to extension via WebSocket."""
        if self._running:
            return

        try:
            self.ws = await websockets.connect(self.ws_url)
            self._running = True
            self._recv_task = asyncio.create_task(self._recv_loop())
            logger.info(f"WebSocket connected to {self.ws_url}")
        except Exception as e:
            logger.error(f"WebSocket connection failed: {e}")
            raise

    async def stop(self) -> None:
        """Close WebSocket connection."""
        self._running = False
        if self._recv_task:
            self._recv_task.cancel()
        if self.ws:
            await self.ws.close()
            self.ws = None
        logger.info("WebSocket disconnected")

    async def _recv_loop(self) -> None:
        """Continuously receive messages from extension."""
        try:
            async for message in self.ws:
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

                except Exception as e:
                    logger.error(f"Failed to parse WebSocket message: {e}")
        except asyncio.CancelledError:
            pass
        except websockets.exceptions.ConnectionClosed:
            logger.warning("WebSocket connection closed")
            self._running = False

    async def fetch(
        self,
        url: str,
        options: Optional[Dict[str, Any]] = None,
        timeout: float = 60.0,
    ) -> TaskResult:
        """Submit a fetch task and wait for result."""
        if not self._running or not self.ws:
            raise RuntimeError("WebSocket not connected")

        task_id = str(uuid.uuid4())[:8]
        event = asyncio.Event()

        async with self._lock:
            self._result_events[task_id] = event
            self._pending_tasks[task_id] = FetchTask(id=task_id, url=url, options=options or {})

        # Send task to extension
        await self.ws.send(json.dumps({
            "type": "task",
            "task": {
                "id": task_id,
                "url": url,
                "options": options or {},
            }
        }))

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
        return self._running and self.ws is not None


# Global bridge
_bridge: Optional[ExtensionBridge] = None
_lock = asyncio.Lock()


async def get_bridge(ws_url: str = "ws://localhost:9877") -> ExtensionBridge:
    global _bridge
    async with _lock:
        if _bridge is None:
            _bridge = ExtensionBridge(ws_url=ws_url)
    return _bridge


async def close_bridge() -> None:
    global _bridge
    async with _lock:
        if _bridge:
            await _bridge.stop()
            _bridge = None
