# -*- coding: utf-8 -*-
"""
Barnacle Extension Bridge Server.

Local HTTP server for communication with Chrome extension.
"""

import asyncio
import json
import logging
import time
import uuid
from dataclasses import dataclass, field
from typing import Optional, Dict, Any, List
from aiohttp import web

logger = logging.getLogger(__name__)


@dataclass
class FetchTask:
    """Represents a fetch task for the extension."""
    id: str
    url: str
    options: Dict[str, Any] = field(default_factory=dict)
    created_at: float = field(default_factory=time.time)


@dataclass
class TaskResult:
    """Result from extension after completing a task."""
    task_id: str
    success: bool
    url: str
    final_url: str
    status: int
    content: List[Dict[str, Any]]
    error: Optional[str] = None
    duration: float = 0.0


class ExtensionBridge:
    """
    Bridge between Python and Chrome extension.
    
    Provides an HTTP server that:
    - Extension polls for tasks
    - Extension reports results back
    """

    def __init__(self, port: int = 9876, host: str = "localhost"):
        self.port = port
        self.host = host
        self.app: Optional[web.Application] = None
        self.runner: Optional[web.AppRunner] = None
        self.site: Optional[web.TCPSite] = None

        # Task management
        self._pending_tasks: Dict[str, FetchTask] = {}
        self._results: Dict[str, TaskResult] = {}
        self._result_events: Dict[str, asyncio.Event] = {}
        self._lock = asyncio.Lock()

    async def start(self) -> None:
        """Start the HTTP server."""
        if self.app is not None:
            return

        self.app = web.Application()
        self.app.router.add_get("/task/get", self._handle_get_task)
        self.app.router.add_post("/task/result", self._handle_task_result)
        self.app.router.add_get("/health", self._handle_health)
        self.app.router.add_post("/task/submit", self._handle_submit_task)

        # Enable CORS for extension access
        self.app.middlewares.append(self._cors_middleware)

        self.runner = web.AppRunner(self.app)
        await self.runner.setup()

        self.site = web.TCPSite(self.runner, self.host, self.port)
        await self.site.start()

        logger.info(f"Extension bridge server started on http://{self.host}:{self.port}")

    async def stop(self) -> None:
        """Stop the HTTP server."""
        if self.site:
            await self.site.stop()
            self.site = None

        if self.runner:
            await self.runner.cleanup()
            self.runner = None

        self.app = None
        logger.info("Extension bridge server stopped")

    @web.middleware
    async def _cors_middleware(self, request: web.Request, handler):
        """Add CORS headers for extension access."""
        # Handle OPTIONS preflight request
        if request.method == "OPTIONS":
            response = web.Response(status=204)
        else:
            try:
                response = await handler(request)
            except Exception as e:
                logger.error(f"Request handler error: {e}")
                response = web.json_response({"error": str(e)}, status=500)
        
        # Always add CORS headers
        response.headers["Access-Control-Allow-Origin"] = "*"
        response.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
        response.headers["Access-Control-Allow-Headers"] = "Content-Type"
        return response

    async def _handle_health(self, request: web.Request) -> web.Response:
        """Health check endpoint."""
        return web.json_response({
            "status": "ok",
            "pending_tasks": len(self._pending_tasks),
            "results": len(self._results)
        })

    async def _handle_get_task(self, request: web.Request) -> web.Response:
        """Endpoint for extension to poll for tasks."""
        async with self._lock:
            if self._pending_tasks:
                task_id, task = self._pending_tasks.popitem()
                logger.info(f"Task {task_id} picked up by extension")
                return web.json_response({
                    "task": {
                        "id": task.id,
                        "url": task.url,
                        "options": task.options
                    }
                })

        return web.json_response({"task": None})

    async def _handle_task_result(self, request: web.Request) -> web.Response:
        """Endpoint for extension to report task results."""
        try:
            data = await request.json()
            logger.info(f"Received task result: {json.dumps(data, indent=2)}")
            result = TaskResult(
                task_id=data["taskId"],
                success=data["success"],
                url=data["url"],
                final_url=data["finalUrl"],
                status=data["status"],
                content=data.get("content", []),
                error=data.get("error"),
                duration=data.get("duration", 0.0)
            )

            async with self._lock:
                # Store result first, then signal event
                self._results[result.task_id] = result

                # Signal waiting coroutine - result is now guaranteed to be available
                if result.task_id in self._result_events:
                    self._result_events[result.task_id].set()
                    logger.debug(f"Event set for task {result.task_id}")
                else:
                    logger.warning(f"No event registered for task {result.task_id}")

            logger.info(f"Task {result.task_id} completed: success={result.success}")
            return web.json_response({"status": "ok"})

        except Exception as e:
            logger.error(f"Error handling task result: {e}")
            return web.json_response({"error": str(e)}, status=400)

    async def _handle_submit_task(self, request: web.Request) -> web.Response:
        """Endpoint to submit a new task (for testing)."""
        try:
            data = await request.json()
            task_id = await self._create_task(
                url=data["url"],
                options=data.get("options", {})
            )
            return web.json_response({"taskId": task_id})
        except Exception as e:
            logger.error(f"Error submitting task: {e}")
            return web.json_response({"error": str(e)}, status=400)

    async def _create_task(
        self,
        url: str,
        options: Optional[Dict[str, Any]] = None
    ) -> str:
        """
        Create a fetch task without waiting for result.

        :param url: URL to fetch
        :param options: Fetch options
        :return: Task ID
        """
        async with self._lock:
            task_id = str(uuid.uuid4())[:8]
            task = FetchTask(
                id=task_id,
                url=url,
                options=options or {}
            )

            # Create event for this task
            self._result_events[task_id] = asyncio.Event()

            # Add to pending queue
            self._pending_tasks[task_id] = task

            logger.info(f"Task {task_id} created: {url}")
            return task_id

    async def submit_task(
        self,
        url: str,
        options: Optional[Dict[str, Any]] = None,
        timeout: float = 60.0
    ) -> str:
        """
        Submit a fetch task and wait for result.

        :param url: URL to fetch
        :param options: Fetch options (timeout, wait, cssSelector, etc.)
        :param timeout: Maximum time to wait for result
        :return: Task ID
        """
        task_id = await self._create_task(url, options)

        # Wait for result event
        event = self._result_events[task_id]

        try:
            await asyncio.wait_for(event.wait(), timeout=timeout)
        except asyncio.TimeoutError:
            logger.warning(f"Task {task_id} timed out")
            # Clean up
            async with self._lock:
                self._pending_tasks.pop(task_id, None)
            self._result_events.pop(task_id, None)
            raise TimeoutError(f"Task {task_id} timed out after {timeout}s")

        return task_id

    async def fetch(
        self,
        url: str,
        options: Optional[Dict[str, Any]] = None,
        timeout: float = 60.0
    ) -> TaskResult:
        """
        Submit a fetch task and return the result.

        :param url: URL to fetch
        :param options: Fetch options
        :param timeout: Maximum time to wait
        :return: TaskResult with content
        """
        task_id = await self._create_task(url, options)
        event = self._result_events[task_id]

        try:
            await asyncio.wait_for(event.wait(), timeout=timeout)
        except asyncio.TimeoutError:
            logger.warning(f"Task {task_id} timed out")
            async with self._lock:
                self._pending_tasks.pop(task_id, None)
                self._result_events.pop(task_id, None)
            raise TimeoutError(f"Task {task_id} timed out after {timeout}s")

        # Get result - use lock to prevent race condition with result storage
        async with self._lock:
            result = self._results.pop(task_id, None)
            self._result_events.pop(task_id, None)

        if result is None:
            # This shouldn't happen normally, but could occur if result 
            # was submitted before event was properly registered
            logger.error(f"No result for task {task_id}")
            raise RuntimeError(f"No result for task {task_id}")

        return result

    def is_extension_connected(self) -> bool:
        """Check if extension is actively connected (has polled recently)."""
        # Simple check - could be enhanced with heartbeat tracking
        return True


# Global bridge instance
_bridge: Optional[ExtensionBridge] = None
_bridge_lock = asyncio.Lock()


async def get_bridge(port: int = 9876, force_new: bool = False) -> ExtensionBridge:
    """
    Get or create the global extension bridge.

    :param port: Port for the bridge server
    :param force_new: If True, close existing bridge and create new one on specified port
    :return: ExtensionBridge instance
    """
    global _bridge
    async with _bridge_lock:
        # Force close existing bridge if requested
        if force_new and _bridge is not None:
            logger.info(f"Force closing existing bridge on port {_bridge.port}")
            await _bridge.stop()
            _bridge = None
            await asyncio.sleep(0.5)  # Allow port to be released (Windows needs longer)

        if _bridge is None:
            _bridge = ExtensionBridge(port=port)
            # Try to start with retries on Windows
            max_retries = 3
            for attempt in range(max_retries):
                try:
                    await _bridge.start()
                    logger.info(f"Created new bridge on port {port}")
                    break
                except OSError as e:
                    if "10048" in str(e) or "Address already in use" in str(e):
                        logger.warning(f"Port {port} in use, retrying... (attempt {attempt + 1}/{max_retries})")
                        await asyncio.sleep(0.5)
                        if attempt == max_retries - 1:
                            raise RuntimeError(f"Failed to start bridge on port {port} after {max_retries} attempts: {e}")
                    else:
                        raise
        elif _bridge.port != port:
            logger.warning(f"Bridge exists on port {_bridge.port}, requested port {port} ignored. Use force_new=True to replace.")
    return _bridge


async def close_bridge() -> None:
    """Close the global extension bridge."""
    global _bridge
    async with _bridge_lock:
        if _bridge is not None:
            await _bridge.stop()
            _bridge = None
            await asyncio.sleep(0.5)  # Allow port to be released (Windows needs longer)
            logger.info("Bridge closed and port released")