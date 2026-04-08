# -*- coding: utf-8 -*-
"""Type definitions for Barnacle."""

from typing import Literal, Optional, Dict, Any, List, TypedDict

# Extraction types
ExtractionType = Literal["markdown", "html", "text"]

# Browser impersonate types (from curl_cffi)
ImpersonateType = Literal[
    "chrome",
    "edge",
    "safari",
    "chrome99",
    "chrome100",
    "chrome101",
    "chrome104",
    "chrome107",
    "chrome110",
    "chrome116",
    "chrome119",
    "chrome120",
    "chrome123",
    "chrome124",
    "chrome131",
    "chrome136",
    "chrome142",
    "chrome99_android",
    "chrome131_android",
    "safari153",
    "safari155",
    "safari170",
    "safari180",
    "safari184",
    "safari260",
    "firefox133",
    "firefox135",
    "firefox144",
]


class ResponseResult(TypedDict):
    """Standard response result structure."""

    success: bool
    url: str  # Final URL after all redirects
    status: int
    content: List[str]
    selector: Optional[List[str]]  # Top 3 candidate selectors
    redirects: Optional[List[str]]  # Redirect chain: [original_url, ...intermediate, final_url]
    error: Optional[str]


class FetchParams(TypedDict, total=False):
    """Parameters for barnacle_fetch."""

    url: str
    extraction_type: ExtractionType
    auto_filter: bool
    timeout: int
    wait: int
    hide_canvas: bool
    block_webrtc: bool
    allow_webgl: bool
    disable_resources: bool
    css_selector: Optional[str]


class GetParams(TypedDict, total=False):
    """Parameters for barnacle_get."""

    url: str
    extraction_type: ExtractionType
    auto_filter: bool
    timeout: int
    impersonate: ImpersonateType
    css_selector: Optional[str]