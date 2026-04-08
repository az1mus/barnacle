# -*- coding: utf-8 -*-
"""Type definitions."""

from typing import Literal, Optional, List, TypedDict

ExtractionType = Literal["markdown", "html", "text"]


class ResponseResult(TypedDict):
    success: bool
    url: str
    status: int
    content: List[str]
    selector: Optional[str]
    error: Optional[str]
