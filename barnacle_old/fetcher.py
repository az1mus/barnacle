# -*- coding: utf-8 -*-
"""
Barnacle Fetcher Module.

Browser-based fetch using local Chrome with anti-fingerprinting features.
"""

import asyncio
import logging
import tempfile
import os
from typing import Optional, Set
from pathlib import Path

from playwright.async_api import async_playwright, Browser, BrowserContext, Page, Error as PlaywrightError

from barnacle.types import ExtractionType, ResponseResult
from barnacle.extractor import extract_content

logger = logging.getLogger(__name__)

# Stealth browser arguments (anti-fingerprinting)
STEALTH_ARGS = [
    "--test-type",
    "--lang=en-US",
    "--mute-audio",
    "--disable-sync",
    "--hide-scrollbars",
    "--disable-logging",
    "--start-maximized",
    "--enable-async-dns",
    "--accept-lang=en-US",
    "--use-mock-keychain",
    "--disable-translate",
    "--disable-voice-input",
    "--window-position=0,0",
    "--ignore-gpu-blocklist",
    "--enable-tcp-fast-open",
    "--disable-cloud-import",
    "--disable-print-preview",
    "--disable-dev-shm-usage",
    "--metrics-recording-only",
    "--disable-crash-reporter",
    "--force-color-profile=srgb",
    "--font-render-hinting=none",
    "--aggressive-cache-discard",
    "--disable-cookie-encryption",
    "--disable-domain-reliability",
    "--enable-simple-cache-backend",
    "--disable-background-networking",
    "--enable-surface-synchronization",
    "--disable-renderer-backgrounding",
    "--disable-ipc-flooding-protection",
    "--safebrowsing-disable-auto-update",
    "--disable-background-timer-throttling",
    "--run-all-compositor-stages-before-draw",
    "--disable-client-side-phishing-detection",
    "--disable-backgrounding-occluded-windows",
    "--autoplay-policy=user-gesture-required",
    "--disable-blink-features=AutomationControlled",
    "--disable-component-extensions-with-background-pages",
]

# Resources to disable for speed
DISABLED_RESOURCES = {
    "font",
    "image",
    "media",
    "beacon",
    "object",
    "imageset",
    "texttrack",
    "websocket",
    "csp_report",
    "stylesheet",
}

# Login/auth URL patterns that indicate we should wait for redirect
LOGIN_URL_PATTERNS = [
    "passport",
    "login",
    "signin",
    "auth",
    "oauth",
    "verify",
    "captcha",
]

# Verification/captcha page indicators (in page content)
VERIFICATION_INDICATORS = [
    "验证",
    "captcha",
    "verify",
    "人机验证",
    "安全验证",
    "请完成验证",
    "滑动验证",
    "图形验证",
    "正在验证",
    "百度安全验证",
    "安全检测",
    "请完成下方验证",
]

# Login page indicators
LOGIN_INDICATORS = [
    "登录",
    "signin",
    "login",
    "账号登录",
    "用户登录",
    "密码登录",
    "扫码登录",
]


def _is_login_url(url: str) -> bool:
    """Check if URL looks like a login/auth page."""
    url_lower = url.lower()
    return any(pattern in url_lower for pattern in LOGIN_URL_PATTERNS)


def _is_verification_page(html_content: str, url: str) -> bool:
    """Check if page is a verification/captcha page."""
    url_lower = url.lower()
    html_lower = html_content.lower() if html_content else ""

    # Check URL patterns
    if any(p in url_lower for p in ["captcha", "verify", "waf"]):
        return True

    # Check page content for verification indicators
    indicator_count = sum(1 for ind in VERIFICATION_INDICATORS if ind in html_lower)
    if indicator_count >= 2:
        return True

    # Check for common captcha elements
    if any(p in html_lower for p in ["passmod", "geetest", "recaptcha", "nc_", "slide-verify"]):
        return True

    # Check if page is small and has verification keywords
    if len(html_content) < 5000 and indicator_count >= 1:
        return True

    return False


def _is_login_page(html_content: str, url: str) -> bool:
    """Check if page is a login page."""
    url_lower = url.lower()
    html_lower = html_content.lower() if html_content else ""

    # Check URL patterns
    if any(p in url_lower for p in ["login", "signin", "passport"]):
        # But not if it's a login page with lots of content (like a forum)
        if len(html_content) > 15000:
            return False
        return True

    # Check page content for login indicators
    indicator_count = sum(1 for ind in LOGIN_INDICATORS if ind in html_lower)
    if indicator_count >= 2 and len(html_content) < 15000:
        return True

    return False


# Canvas noise injection script
CANVAS_NOISE_SCRIPT = """
// Add random noise to canvas operations to prevent fingerprinting
const originalGetContext = HTMLCanvasElement.prototype.getContext;
HTMLCanvasElement.prototype.getContext = function(type, attributes) {
    if (type === '2d' || type === 'webgl' || type === 'webgl2') {
        const context = originalGetContext.call(this, type, attributes);
        if (type === '2d') {
            const originalGetImageData = context.getImageData;
            context.getImageData = function(x, y, w, h) {
                const data = originalGetImageData.call(this, x, y, w, h);
                // Add subtle noise
                for (let i = 0; i < data.data.length; i += 4) {
                    data.data[i] = data.data[i] ^ (Math.random() * 2);
                    data.data[i + 1] = data.data[i + 1] ^ (Math.random() * 2);
                    data.data[i + 2] = data.data[i + 2] ^ (Math.random() * 2);
                }
                return data;
            };
        }
        return context;
    }
    return originalGetContext.call(this, type, attributes);
};
"""

# WebRTC leak prevention script
WEBRTC_BLOCK_SCRIPT = """
// Block WebRTC to prevent IP leak
if (window.RTCPeerConnection) {
    window.RTCPeerConnection = undefined;
}
if (window.webkitRTCPeerConnection) {
    window.webkitRTCPeerConnection = undefined;
}
"""


class ChromeFetcher:
    """
    Browser fetcher using local Chrome with anti-fingerprinting.
    """

    def __init__(
        self,
        hide_canvas: bool = True,
        block_webrtc: bool = True,
        allow_webgl: bool = True,
        disable_resources: bool = False,
        user_data_dir: Optional[str] = None,
    ):
        """
        Initialize Chrome fetcher.

        :param hide_canvas: Add noise to canvas to prevent fingerprinting
        :param block_webrtc: Block WebRTC to prevent IP leak
        :param allow_webgl: Enable WebGL (many WAFs check for this)
        :param disable_resources: Disable images/stylesheets for speed
        :param user_data_dir: Path to Chrome user data directory
        """
        self.hide_canvas = hide_canvas
        self.block_webrtc = block_webrtc
        self.allow_webgl = allow_webgl
        self.disable_resources = disable_resources
        self.user_data_dir = user_data_dir or tempfile.mkdtemp(prefix="barnacle_")

        self._playwright = None
        self._browser: Optional[Browser] = None
        self._context: Optional[BrowserContext] = None
        self._lock = asyncio.Lock()

    async def start(self) -> None:
        """Start Chrome browser."""
        if self._context is not None:
            return

        async with self._lock:
            if self._context is not None:
                return

            logger.info("Starting local Chrome browser...")
            self._playwright = await async_playwright().start()

            # Build browser launch options
            launch_options = {
                "channel": "chrome",  # Use local Chrome
                "headless": False,    # Must be visible for local Chrome
                "args": STEALTH_ARGS,
            }

            # Add WebGL args
            if self.allow_webgl:
                launch_options["args"].extend([
                    "--enable-webgl",
                    "--enable-accelerated-2d-canvas",
                ])
            else:
                launch_options["args"].extend([
                    "--disable-webgl",
                ])

            # Build context options
            context_options = {
                "viewport": {"width": 1920, "height": 1080},
                "user_agent": self._get_chrome_useragent(),
                "locale": "en-US",
                "timezone_id": "America/New_York",
            }

            try:
                # Launch persistent context (keeps cookies/session)
                self._context = await self._playwright.chromium.launch_persistent_context(
                    user_data_dir=self.user_data_dir,
                    **launch_options,
                    **context_options,
                )

                # Inject anti-fingerprint scripts
                await self._inject_scripts()

                logger.info("Chrome browser started successfully")

            except PlaywrightError as e:
                logger.error(f"Failed to start Chrome: {e}")
                if "Executable doesn't exist" in str(e):
                    logger.error("Chrome not found. Please install Chrome browser.")
                raise

    def _get_chrome_useragent(self) -> str:
        """Get Chrome user agent string."""
        return "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/136.0.0.0 Safari/537.36"

    async def _inject_scripts(self) -> None:
        """Inject anti-fingerprinting scripts into context."""
        if self.hide_canvas:
            await self._context.add_init_script(CANVAS_NOISE_SCRIPT)
            logger.debug("Canvas noise injection enabled")

        if self.block_webrtc:
            await self._context.add_init_script(WEBRTC_BLOCK_SCRIPT)
            logger.debug("WebRTC blocking enabled")

    async def close(self) -> None:
        """Close browser and cleanup."""
        if self._context:
            await self._context.close()
            self._context = None

        if self._playwright:
            await self._playwright.stop()
            self._playwright = None

        # Cleanup temp directory if we created it
        if self.user_data_dir and self.user_data_dir.startswith(tempfile.gettempdir()):
            try:
                import shutil
                shutil.rmtree(self.user_data_dir, ignore_errors=True)
            except Exception:
                pass

        logger.info("Chrome browser closed")

    async def _block_resources(self, route) -> None:
        """Block unnecessary resources for speed."""
        resource_type = route.request.resource_type
        if resource_type in DISABLED_RESOURCES:
            await route.abort()
        else:
            await route.continue_()

    async def fetch(
        self,
        url: str,
        extraction_type: ExtractionType = "markdown",
        auto_filter: bool = True,
        timeout: int = 30000,
        wait: int = 0,
        css_selector: Optional[str] = None,
    ) -> ResponseResult:
        """
        Fetch URL using Chrome browser.

        :param url: Target URL
        :param extraction_type: Output format - 'markdown', 'html', or 'text'
        :param auto_filter: Use smart content detection
        :param timeout: Page load timeout in milliseconds
        :param wait: Additional wait time after page load in milliseconds
        :param css_selector: Optional CSS selector to target specific elements
        :return: ResponseResult with content and metadata
        """
        # Ensure browser is started
        if self._context is None:
            await self.start()

        # Track redirect chain
        redirect_chain = [url]

        try:
            logger.info(f"Fetching: {url}")

            # Create new tab/page
            page = await self._context.new_page()

            # Setup resource blocking if enabled
            if self.disable_resources:
                await page.route("**/*", self._block_resources)

            try:
                # Navigate to URL
                response = await page.goto(
                    url,
                    timeout=timeout,
                    wait_until="domcontentloaded",
                )

                # Wait for page to be ready
                try:
                    await page.wait_for_load_state("load", timeout=min(timeout, 10000))
                except PlaywrightError:
                    logger.debug("Load state timeout, continuing with current content")

                # Track initial URL after navigation
                current_url = page.url
                if current_url != url:
                    redirect_chain.append(current_url)

                # Wait for URL to stabilize (handle JS redirects)
                await page.wait_for_timeout(2000)
                new_url = page.url
                if new_url != current_url:
                    redirect_chain.append(new_url)
                    current_url = new_url

                # Check for verification/captcha page and wait for user
                html_content = await page.content()
                if _is_verification_page(html_content, current_url):
                    logger.info(f"Verification page detected: {current_url}")
                    logger.info("Waiting for user to complete verification...")
                    
                    # Wait for page content to change (user completed verification)
                    max_verify_wait = 60000  # 60 seconds max
                    verify_interval = 1000
                    total_verify_wait = 0
                    original_content_hash = hash(html_content[:2000])
                    
                    while total_verify_wait < max_verify_wait:
                        await page.wait_for_timeout(verify_interval)
                        total_verify_wait += verify_interval
                        
                        new_content = await page.content()
                        new_url = page.url
                        
                        # Check if page changed (URL or content)
                        if new_url != current_url:
                            logger.info(f"Redirected to: {new_url}")
                            redirect_chain.append(new_url)
                            current_url = new_url
                            break
                        
                        if hash(new_content[:2000]) != original_content_hash:
                            logger.info("Page content changed, verification likely completed")
                            html_content = new_content
                            break
                        
                        # Also check if verification indicators are gone
                        if not _is_verification_page(new_content, current_url):
                            logger.info("Verification page cleared")
                            html_content = new_content
                            break
                    
                    if total_verify_wait >= max_verify_wait:
                        logger.warning("Verification wait timeout, proceeding anyway")

                # Check for login page and wait for user
                html_content = await page.content()
                if _is_login_page(html_content, current_url):
                    logger.info(f"Login page detected: {current_url}")
                    logger.info("Waiting for user to login...")
                    
                    max_login_wait = 120000  # 2 minutes max for login
                    login_interval = 1000
                    total_login_wait = 0
                    
                    while total_login_wait < max_login_wait:
                        await page.wait_for_timeout(login_interval)
                        total_login_wait += login_interval
                        
                        new_url = page.url
                        new_content = await page.content()
                        
                        # Check if navigated away from login page
                        if new_url != current_url:
                            logger.info(f"Redirected to: {new_url}")
                            redirect_chain.append(new_url)
                            current_url = new_url
                            html_content = new_content
                            break
                        
                        # Check if page is no longer a login page
                        if not _is_login_page(new_content, current_url):
                            logger.info("Login page cleared")
                            html_content = new_content
                            break
                    
                    if total_login_wait >= max_login_wait:
                        logger.warning("Login wait timeout, proceeding anyway")

                # Final URL
                final_url = page.url
                if final_url != redirect_chain[-1]:
                    redirect_chain.append(final_url)

                # Additional wait if specified
                if wait > 0:
                    await page.wait_for_timeout(wait)

                # Get final content
                html_content = await page.content()

                # Detect content selectors
                detected_selector = None
                if auto_filter and not css_selector:
                    from barnacle.content_detector import detect_main_content
                    detected_selector = detect_main_content(html_content, final_url)

                # Extract content
                content_list = extract_content(
                    html_content=html_content,
                    extraction_type=extraction_type,
                    auto_filter=auto_filter,
                    css_selector=css_selector,
                    url=final_url,
                )

                status = response.status if response else 200

                return ResponseResult(
                    success=True,
                    url=final_url,
                    status=status,
                    content=content_list,
                    selector=detected_selector,
                    redirects=redirect_chain if len(redirect_chain) > 1 else None,
                    error=None,
                )

            finally:
                # Close the tab
                await page.close()

        except PlaywrightError as e:
            logger.error(f"Fetch failed: {e}")
            return ResponseResult(
                success=False,
                url=url,
                status=0,
                content=[],
                selector=None,
                redirects=redirect_chain if len(redirect_chain) > 1 else None,
                error=f"Browser error: {str(e)}",
            )

        except Exception as e:
            logger.error(f"Unexpected error: {e}")
            return ResponseResult(
                success=False,
                url=url,
                status=0,
                content=[],
                selector=None,
                redirects=redirect_chain if len(redirect_chain) > 1 else None,
                error=f"Error: {str(e)}",
            )


# Global fetcher instance
_fetcher: Optional[ChromeFetcher] = None
_fetcher_lock = asyncio.Lock()


async def get_fetcher(
    hide_canvas: bool = True,
    block_webrtc: bool = True,
    allow_webgl: bool = True,
    disable_resources: bool = False,
) -> ChromeFetcher:
    """Get or create global Chrome fetcher instance."""
    global _fetcher
    async with _fetcher_lock:
        if _fetcher is None:
            _fetcher = ChromeFetcher(
                hide_canvas=hide_canvas,
                block_webrtc=block_webrtc,
                allow_webgl=allow_webgl,
                disable_resources=disable_resources,
            )
    return _fetcher


async def barnacle_fetch(
    url: str,
    extraction_type: ExtractionType = "markdown",
    auto_filter: bool = True,
    timeout: int = 30000,
    wait: int = 0,
    hide_canvas: bool = True,
    block_webrtc: bool = True,
    allow_webgl: bool = True,
    disable_resources: bool = False,
    css_selector: Optional[str] = None,
) -> ResponseResult:
    """
    Fetch URL using local Chrome browser with anti-fingerprinting.

    :param url: Target URL
    :param extraction_type: Output format - 'markdown', 'html', or 'text'
    :param auto_filter: Use smart content detection
    :param timeout: Page load timeout in milliseconds
    :param wait: Additional wait time after load in milliseconds
    :param hide_canvas: Add noise to canvas for fingerprint protection
    :param block_webrtc: Block WebRTC to prevent IP leak
    :param allow_webgl: Enable WebGL (recommended for WAF bypass)
    :param disable_resources: Disable images/stylesheets for speed
    :param css_selector: Optional CSS selector to target specific elements
    :return: ResponseResult with content and metadata
    """
    fetcher = await get_fetcher(
        hide_canvas=hide_canvas,
        block_webrtc=block_webrtc,
        allow_webgl=allow_webgl,
        disable_resources=disable_resources,
    )
    return await fetcher.fetch(
        url=url,
        extraction_type=extraction_type,
        auto_filter=auto_filter,
        timeout=timeout,
        wait=wait,
        css_selector=css_selector,
    )


async def close_browser() -> None:
    """Close the global browser instance."""
    global _fetcher
    if _fetcher is not None:
        await _fetcher.close()
        _fetcher = None