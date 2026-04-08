# -*- coding: utf-8 -*-
"""Content Extractor Module."""

import re
from copy import deepcopy
from typing import List, Optional

from lxml.html import HtmlElement, fromstring, tostring
from markdownify import markdownify as md

from server.content_detector import detect_main_content

NOISE_TAGS = ('script', 'style', 'noscript', 'svg', 'iframe', 'nav', 'header', 'footer', 'aside')


def extract_content(
    html: str | bytes,
    extraction_type: str = "markdown",
    auto_filter: bool = False,
    css_selector: Optional[str] = None,
    url: str = "",
) -> List[str]:
    """Extract content from HTML in specified format."""
    if isinstance(html, bytes):
        html = html.decode('utf-8', errors='ignore')

    try:
        root = fromstring(html)
    except Exception:
        return [html]

    # Strip noise
    clean = deepcopy(root)
    for tag in NOISE_TAGS:
        for elem in clean.xpath(f'//{tag}'):
            elem.drop_tree()

    # Smart content detection
    if auto_filter and not css_selector:
        detected = detect_main_content(html, url)
        if detected:
            for sel in detected:
                if _select(clean, sel):
                    css_selector = sel
                    break

    # Select elements
    elems = _select(clean, css_selector) if css_selector else (clean.xpath('//body') or [clean])

    results = []
    for elem in elems:
        content = _extract(elem, extraction_type)
        if content:
            results.append(content)

    return results if results else [""]


def _select(root: HtmlElement, selector: str) -> List[HtmlElement]:
    if selector.startswith('#'):
        return root.xpath(f'//*[@id="{selector[1:]}"]')
    elif selector.startswith('.'):
        return root.xpath(f'//*[contains(@class, "{selector[1:]}")]')
    elif '[' in selector:
        m = re.match(r'\[(\w+)="?(\w+)"?\]', selector)
        if m:
            return root.xpath(f'//*[@{m.group(1)}="{m.group(2)}"]')
    elif '.' in selector:
        tag, cls = selector.split('.', 1)
        return root.xpath(f'//{tag}[contains(@class, "{cls}")]')
    else:
        return root.xpath(f'//{selector}')
    return []


def _extract(elem: HtmlElement, extraction_type: str) -> str:
    html_str = tostring(elem, encoding='unicode', pretty_print=False)

    if extraction_type == "markdown":
        result = md(html_str, heading_style="ATX", bullets="-", strip=['script', 'style'])
        return re.sub(r'\n{3,}', '\n\n', result).strip()
    elif extraction_type == "text":
        text = re.sub(r'[ \t]+', ' ', elem.text_content())
        return re.sub(r'\n{3,}', '\n\n', text).strip()
    return html_str.strip()
