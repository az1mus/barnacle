# -*- coding: utf-8 -*-
"""
Barnacle Extension Fetcher Module.

Fetch pages using user's Chrome browser via extension.
No automation detection - uses existing browser session.
"""

import asyncio
import logging
from typing import Optional, Dict, Any, List

from barnacle.types import ExtractionType, ResponseResult
from barnacle.extractor import extract_content
from barnacle.extension_server import ExtensionBridge, get_bridge, close_bridge

logger = logging.getLogger(__name__)


class ExtensionFetcher:
    """
    Fetcher that uses Chrome extension in user's browser.
    
    Advantages over Playwright:
    - No "controlled by automation" banner
    - Uses user's existing login sessions
    - Harder to detect as automation
    - No separate browser process needed
    """

    def __init__(self, port: int = 9876):
        """
        Initialize extension fetcher.

        :param port: Port for local HTTP server
        """
        self.port = port
        self._bridge: Optional[ExtensionBridge] = None
        self._lock = asyncio.Lock()

    async def start(self) -> None:
        """Start the extension bridge server."""
        if self._bridge is not None:
            return

        async with self._lock:
            if self._bridge is not None:
                return

            self._bridge = await get_bridge(port=self.port)
            logger.info(f"Extension fetcher started on port {self.port}")

    async def close(self) -> None:
        """Close the extension bridge server."""
        if self._bridge:
            await close_bridge()
            self._bridge = None
            logger.info("Extension fetcher closed")

    async def fetch(
        self,
        url: str,
        extraction_type: ExtractionType = "markdown",
        auto_filter: bool = True,
        timeout: int = 60000,
        wait: int = 0,
        css_selector: Optional[str] = None,
        active: bool = True,
        keep_open: bool = False,
    ) -> ResponseResult:
        """
        Fetch URL using Chrome extension.

        :param url: Target URL
        :param extraction_type: Output format - 'markdown', 'html', or 'text'
        :param auto_filter: Use smart content detection
        :param timeout: Page load timeout in milliseconds
        :param wait: Additional wait time after page load in milliseconds
        :param css_selector: Optional CSS selector to target specific elements
        :param active: Whether to open tab as active (visible)
        :param keep_open: Keep tab open after fetching
        :return: ResponseResult with content and metadata
        """
        # Ensure bridge is started
        if self._bridge is None:
            await self.start()

        try:
            logger.info(f"Fetching via extension: {url}")

            # Submit task to extension
            options = {
                "timeout": timeout,
                "wait": wait,
                "cssSelector": css_selector,
                "autoFilter": auto_filter,
                "active": active,
                "keepOpen": keep_open,
            }

            result = await self._bridge.fetch(
                url=url,
                options=options,
                timeout=timeout / 1000.0 + 10.0  # Add buffer
            )

            logger.info(f"Extension result: success={result.success}, error={result.error}, content_count={len(result.content)}")

            if not result.success:
                logger.error(f"Extension fetch failed: {result.error}")
                return ResponseResult(
                    success=False,
                    url=url,
                    status=0,
                    content=[],
                    selector=None,
                    redirects=None,
                    error=result.error or "Extension fetch failed"
                )

            # Process content
            content_list = []
            for item in result.content:
                html_content = item.get("content", "")
                if html_content:
                    # Extract using our extractor
                    extracted = extract_content(
                        html_content=html_content,
                        extraction_type=extraction_type,
                        auto_filter=auto_filter,
                        css_selector=css_selector,
                        url=result.final_url
                    )
                    content_list.extend(extracted)

            return ResponseResult(
                success=True,
                url=result.final_url,
                status=result.status,
                content=content_list,
                selector=css_selector,
                redirects=None,
                error=None
            )

        except asyncio.TimeoutError:
            logger.error(f"Extension fetch timeout: {url}")
            return ResponseResult(
                success=False,
                url=url,
                status=0,
                content=[],
                selector=None,
                redirects=None,
                error="Timeout waiting for extension response"
            )

        except Exception as e:
            logger.error(f"Extension fetch error: {e}")
            return ResponseResult(
                success=False,
                url=url,
                status=0,
                content=[],
                selector=None,
                redirects=None,
                error=str(e)
            )


# Global fetcher instance
_extension_fetcher: Optional[ExtensionFetcher] = None
_extension_fetcher_lock = asyncio.Lock()


async def get_extension_fetcher(port: int = 9876) -> ExtensionFetcher:
    """Get or create global extension fetcher instance."""
    global _extension_fetcher
    async with _extension_fetcher_lock:
        if _extension_fetcher is None:
            _extension_fetcher = ExtensionFetcher(port=port)
    return _extension_fetcher


async def fetch(
    url: str,
    extraction_type: ExtractionType = "markdown",
    auto_filter: bool = True,
    timeout: int = 60000,
    wait: int = 0,
    css_selector: Optional[str] = None,
    active: bool = True,
    keep_open: bool = False,
) -> ResponseResult:
    """
    Fetch URL using Chrome extension.

    :param url: Target URL
    :param extraction_type: Output format - 'markdown', 'html', or 'text'
    :param auto_filter: Use smart content detection
    :param timeout: Page load timeout in milliseconds
    :param wait: Additional wait time after load in milliseconds
    :param css_selector: Optional CSS selector to target specific elements
    :param active: Whether to open tab as active (visible)
    :param keep_open: Keep tab open after fetching
    :return: ResponseResult with content and metadata
    """
    fetcher = await get_extension_fetcher()
    return await fetcher.fetch(
        url=url,
        extraction_type=extraction_type,
        auto_filter=auto_filter,
        timeout=timeout,
        wait=wait,
        css_selector=css_selector,
        active=active,
        keep_open=keep_open
    )


async def close_extension_fetcher() -> None:
    """Close the global extension fetcher."""
    global _extension_fetcher
    if _extension_fetcher is not None:
        await _extension_fetcher.close()
        _extension_fetcher = None