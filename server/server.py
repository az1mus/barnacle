# -*- coding: utf-8 -*-
"""
Barnacle MCP Server.

Tools:
- fetch: Fetch pages via Chrome extension (WebSocket)
- close: Close extension bridge
- clear_cache: Clear content detection cache

Features:
- WebSocket communication with Chrome extension
- ONNX model loaded asynchronously (non-blocking startup)
"""

import logging
from contextlib import asynccontextmanager
from typing import Optional

from mcp.server.fastmcp import FastMCP

from server.extension_bridge import get_bridge, close_bridge
from server.content_detector import load_model_async, get_content_detector
from server.extractor import extract_content
from server.types import ResponseResult

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastMCP):
    """Start bridge and load model in background."""
    logger.info("Starting extension bridge...")
    try:
        bridge = await get_bridge()
        await bridge.start()
        logger.info("Extension bridge connected")
    except Exception as e:
        logger.warning(f"Bridge connection failed (will retry on fetch): {e}")

    # Load ONNX model asynchronously - non-blocking
    logger.info("Loading ONNX model in background...")
    import asyncio
    asyncio.create_task(load_model_async())

    yield

    logger.info("Stopping extension bridge...")
    await close_bridge()


mcp = FastMCP("Barnacle", lifespan=lifespan)


@mcp.tool()
async def fetch(
    url: str,
    extraction_type: str = "markdown",
    auto_filter: bool = True,
    timeout: int = 60000,
    wait: int = 0,
    css_selector: Optional[str] = None,
    active: bool = True,
    keep_open: bool = False,
) -> dict:
    """
    Fetch URL using Chrome extension in user's browser.

    Uses WebSocket for real-time communication.
    Requires Barnacle Bridge extension to be running.

    :param url: Target URL
    :param extraction_type: 'markdown', 'html', or 'text'
    :param auto_filter: Use smart content detection
    :param timeout: Page load timeout in milliseconds
    :param wait: Additional wait after load in milliseconds
    :param css_selector: Optional CSS selector
    :param active: Open tab as active
    :param keep_open: Keep tab open after fetching
    :return: Dict with success, url, status, content, selector, error
    """
    logger.info(f"fetch: {url}")

    try:
        bridge = await get_bridge()
        if not bridge.is_connected:
            await bridge.start()

        options = {
            "timeout": timeout,
            "wait": wait,
            "cssSelector": css_selector,
            "autoFilter": auto_filter,
            "active": active,
            "keepOpen": keep_open,
        }

        result = await bridge.fetch(
            url=url,
            options=options,
            timeout=timeout / 1000.0 + 10.0,
        )

        if not result.success:
            return ResponseResult(
                success=False,
                url=url,
                status=0,
                content=[],
                selector=None,
                error=result.error or "Fetch failed",
            )

        # Extract content
        content_list = []
        for item in result.content:
            html_content = item.get("content", "")
            if html_content:
                extracted = extract_content(
                    html_content,
                    extraction_type=extraction_type,
                    auto_filter=auto_filter,
                    css_selector=css_selector,
                    url=result.final_url,
                )
                content_list.extend(extracted)

        return ResponseResult(
            success=True,
            url=result.final_url,
            status=result.status,
            content=content_list,
            selector=css_selector,
            error=None,
        )

    except TimeoutError as e:
        logger.error(f"Timeout: {url}")
        return ResponseResult(
            success=False,
            url=url,
            status=0,
            content=[],
            selector=None,
            error="Timeout waiting for extension",
        )
    except Exception as e:
        logger.error(f"Fetch error: {e}")
        return ResponseResult(
            success=False,
            url=url,
            status=0,
            content=[],
            selector=None,
            error=str(e),
        )


@mcp.tool()
async def close() -> str:
    """Close extension bridge connection."""
    await close_bridge()
    return "Extension bridge closed"


@mcp.tool()
def clear_cache() -> str:
    """Clear content detection cache."""
    detector = get_content_detector()
    detector.clear_cache()
    return "Cache cleared"


def run():
    logger.info("Starting Barnacle MCP server...")
    mcp.run()


if __name__ == "__main__":
    run()
