# -*- coding: utf-8 -*-
"""
Barnacle MCP Server.

Provides tools:
- fetch: Fetch via Chrome extension (no automation detection)
- close: Close browser instances
- clear_cache: Clear content detection cache
"""

import asyncio
import logging
from contextlib import asynccontextmanager
from typing import Optional

from mcp.server.fastmcp import FastMCP

from barnacle.types import ExtractionType
from barnacle.fetcher import close_browser
from barnacle.extension_fetcher import fetch as do_extension_fetch, close_extension_fetcher, get_extension_fetcher
from barnacle.content_detector import get_content_detector, init_model

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastMCP):
    """Lifespan context manager to start/stop extension bridge."""
    logger.info("Pre-starting extension bridge server...")
    try:
        fetcher = await get_extension_fetcher()
        await fetcher.start()
        logger.info("Extension bridge server started on port 9876")
    except Exception as e:
        logger.warning(f"Could not start extension bridge: {e}")
    
    yield  # Server runs here
    
    # Cleanup
    logger.info("Stopping extension bridge server...")
    await close_extension_fetcher()


# Create MCP server with lifespan
mcp = FastMCP("Barnacle", lifespan=lifespan)


# @mcp.tool()
# async def fetch(
#     url: str,
#     extraction_type: ExtractionType = "markdown",
#     auto_filter: bool = True,
#     timeout: int = 30000,
#     wait: int = 0,
#     hide_canvas: bool = True,
#     block_webrtc: bool = True,
#     allow_webgl: bool = True,
#     disable_resources: bool = False,
#     css_selector: Optional[str] = None,
# ) -> dict:
#     """
#     Browser-based fetch using local Chrome with anti-fingerprinting features.

#     Use this for pages that require JavaScript rendering or have anti-bot protection.
#     Opens a new tab in Chrome browser for each request.

#     Anti-fingerprinting features:
#     - Canvas noise injection (hide_canvas): Prevents canvas fingerprinting
#     - WebRTC blocking (block_webrtc): Prevents local IP leak
#     - WebGL support (allow_webgl): Many WAFs check for WebGL capability

#     :param url: Target URL to fetch
#     :param extraction_type: Output format - 'markdown', 'html', or 'text' (default: markdown)
#     :param auto_filter: Use smart content detection to filter noise (default: True)
#     :param timeout: Page load timeout in milliseconds (default: 30000)
#     :param wait: Additional wait time after load in milliseconds (default: 0)
#     :param hide_canvas: Add noise to canvas for fingerprint protection (default: True)
#     :param block_webrtc: Block WebRTC to prevent IP leak (default: True)
#     :param allow_webgl: Enable WebGL for WAF bypass (default: True)
#     :param disable_resources: Disable images/stylesheets for speed (default: False)
#     :param css_selector: Optional CSS selector to target specific elements
#     :return: Response dict with success, url, status, content, selector, error
#     """
#     logger.info(f"barnacle_fetch: {url}")
#     result = await barnacle_fetch(
#         url=url,
#         extraction_type=extraction_type,
#         auto_filter=auto_filter,
#         timeout=timeout,
#         wait=wait,
#         hide_canvas=hide_canvas,
#         block_webrtc=block_webrtc,
#         allow_webgl=allow_webgl,
#         disable_resources=disable_resources,
#         css_selector=css_selector,
#     )
#     return dict(result)


@mcp.tool()
async def fetch(
    url: str,
    extraction_type: ExtractionType = "markdown",
    auto_filter: bool = True,
    timeout: int = 60000,
    wait: int = 0,
    css_selector: Optional[str] = None,
    active: bool = True,
    keep_open: bool = False,
) -> dict:
    """
    Fetch URL using Chrome extension in user's browser.

    This method uses a Chrome extension installed in the user's own browser,
    providing several advantages over the Playwright-based fetch:

    - NO automation detection banner ("Chrome is controlled by...")
    - Uses user's existing login sessions and cookies
    - Harder for websites to detect as automation
    - No separate browser process needed

    REQUIREMENTS:
    - Install the Barnacle Bridge extension in Chrome
    - Start the extension by clicking its icon and pressing "Start"
    - Extension must be polling for tasks (shows "ON" badge)

    Use this when:
    - You need to access sites that block automation
    - You need to use existing login sessions
    - Anti-bot detection is a concern

    :param url: Target URL to fetch
    :param extraction_type: Output format - 'markdown', 'html', or 'text' (default: markdown)
    :param auto_filter: Use smart content detection to filter noise (default: True)
    :param timeout: Page load timeout in milliseconds (default: 60000)
    :param wait: Additional wait time after load in milliseconds (default: 0)
    :param css_selector: Optional CSS selector to target specific elements
    :param active: Open tab as active/visible (default: True)
    :param keep_open: Keep tab open after fetching (default: False)
    :return: Response dict with success, url, status, content, selector, error
    """
    logger.info(f"fetch: {url}")
    result = await do_extension_fetch(
        url=url,
        extraction_type=extraction_type,
        auto_filter=auto_filter,
        timeout=timeout,
        wait=wait,
        css_selector=css_selector,
        active=active,
        keep_open=keep_open,
    )
    return dict(result)


@mcp.tool()
async def close() -> str:
    """
    Close all browser instances and extension bridge.

    Call this when you're done with all fetch operations to release resources.
    """
    await close_browser()
    await close_extension_fetcher()
    return "All browser instances closed successfully"


@mcp.tool()
def clear_cache() -> str:
    """
    Clear the content detection cache.

    Call this if you want to reset the smart content detection cache.
    """
    detector = get_content_detector()
    detector.clear_cache()
    return "Content detection cache cleared"


def run_server():
    """Run the MCP server."""
    logger.info("Starting Barnacle MCP server...")
    
    # Pre-load distilgpt2 model at startup
    logger.info("Pre-loading distilgpt2 model...")
    if init_model():
        logger.info("Model loaded successfully, ready to serve requests.")
    else:
        logger.warning("Model loading failed, perplexity scoring will be disabled.")
    
    mcp.run()


if __name__ == "__main__":
    run_server()