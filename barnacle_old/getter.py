# -*- coding: utf-8 -*-
"""
Barnacle Getter Module.

Simple HTTP GET requests using curl_cffi with browser impersonation.
"""

import logging
from typing import Optional, Union

from curl_cffi import requests
from curl_cffi.requests.exceptions import RequestException, Timeout, ConnectionError, CurlError

from barnacle.types import ExtractionType, ImpersonateType, ResponseResult
from barnacle.extractor import extract_content
from barnacle.ssl_config import DEFAULT_VERIFY, get_ssl_verify_setting

logger = logging.getLogger(__name__)

# Default impersonate browser
DEFAULT_IMPERSONATE = "chrome136"


def barnacle_get(
    url: str,
    extraction_type: ExtractionType = "markdown",
    auto_filter: bool = True,
    timeout: int = 30,
    impersonate: ImpersonateType = DEFAULT_IMPERSONATE,
    css_selector: Optional[str] = None,
    verify: Optional[Union[bool, str]] = None,
) -> ResponseResult:
    """
    Simple HTTP GET request using curl_cffi.

    SSL Verification Notes:
        - Windows: Disabled by default due to curl_cffi certificate issues
        - Linux/macOS: Uses system CA bundle or certifi
        - Override with BARNACLE_SSL_VERIFY environment variable
        - Set to a path string to use custom CA bundle

    :param url: Target URL
    :param extraction_type: Output format - 'markdown', 'html', or 'text'
    :param auto_filter: Use smart content detection to filter noise
    :param timeout: Request timeout in seconds
    :param impersonate: Browser to impersonate for TLS fingerprint
    :param css_selector: Optional CSS selector to target specific elements
    :param verify: SSL verification - None (auto), False, True, or path to CA bundle
    :return: ResponseResult with content and metadata
    """
    try:
        logger.info(f"GET request to: {url}")

        # Determine SSL verification setting
        if verify is None:
            verify_path = DEFAULT_VERIFY
        elif verify is True:
            verify_path = get_ssl_verify_setting()
        elif verify is False:
            verify_path = False
        else:
            verify_path = str(verify)  # Custom CA path

        response = requests.get(
            url,
            impersonate=impersonate,
            timeout=timeout,
            allow_redirects=True,
            verify=verify_path,
        )

        html_content = response.content

        # Extract content
        content_list = extract_content(
            html_content=html_content,
            extraction_type=extraction_type,
            auto_filter=auto_filter,
            css_selector=css_selector,
            url=url,
        )

        # Get detected selector if auto_filter was used
        detected_selector = None
        if auto_filter and not css_selector:
            from barnacle.content_detector import detect_main_content
            detected_selector = detect_main_content(html_content, url)

        return ResponseResult(
            success=True,
            url=str(response.url),
            status=response.status_code,
            content=content_list,
            selector=detected_selector,
            error=None,
        )

    except Timeout:
        logger.error(f"Request timeout: {url}")
        return ResponseResult(
            success=False,
            url=url,
            status=0,
            content=[""],
            selector=None,
            error="Request timeout",
        )

    except ConnectionError as e:
        logger.error(f"Connection error: {e}")
        return ResponseResult(
            success=False,
            url=url,
            status=0,
            content=[""],
            selector=None,
            error=f"Connection error: {str(e)}",
        )

    except CurlError as e:
        logger.error(f"Curl error: {e}")
        return ResponseResult(
            success=False,
            url=url,
            status=0,
            content=[""],
            selector=None,
            error=f"Curl error: {str(e)}",
        )

    except RequestException as e:
        logger.error(f"Request error: {e}")
        return ResponseResult(
            success=False,
            url=url,
            status=0,
            content=[""],
            selector=None,
            error=f"Request error: {str(e)}",
        )

    except Exception as e:
        logger.error(f"Request failed: {e}")
        return ResponseResult(
            success=False,
            url=url,
            status=0,
            content=[""],
            selector=None,
            error=f"Request failed: {str(e)}",
        )