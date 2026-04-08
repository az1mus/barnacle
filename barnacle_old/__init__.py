# -*- coding: utf-8 -*-
"""
Barnacle - A minimal web scraper MCP server.

Provides tools:
- get: Simple HTTP GET request with curl_cffi
- fetch: Fetch via Chrome extension (no automation detection)
"""

__version__ = "0.2.0"

from barnacle.getter import barnacle_get
from barnacle.fetcher import barnacle_fetch, close_browser
from barnacle.extension_fetcher import fetch as extension_fetch, close_extension_fetcher
from barnacle.extension_server import ExtensionBridge