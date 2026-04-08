# -*- coding: utf-8 -*-
"""
Content Extractor Module.

Converts HTML content to various formats: Markdown, HTML, Text.
"""

import re
from typing import List, Optional, Generator
from copy import deepcopy

from lxml.html import HtmlElement, fromstring, tostring
from markdownify import markdownify as md

from barnacle.content_detector import detect_main_content
from barnacle.types import ExtractionType


# Tags to strip for noise reduction
NOISE_TAGS = ('script', 'style', 'noscript', 'svg', 'iframe', 'nav', 'header', 'footer', 'aside')


def extract_content(
    html_content: str | bytes,
    extraction_type: ExtractionType = "markdown",
    auto_filter: bool = False,
    css_selector: Optional[str] = None,
    url: str = "",
) -> List[str]:
    """
    Extract content from HTML in specified format.

    :param html_content: HTML content as string or bytes
    :param extraction_type: Output format - 'markdown', 'html', or 'text'
    :param auto_filter: Whether to use smart content detection
    :param css_selector: Optional CSS selector to target specific elements
    :param url: URL for content detection caching
    :return: List of extracted content strings
    """
    if isinstance(html_content, bytes):
        html_content = html_content.decode('utf-8', errors='ignore')

    try:
        root = fromstring(html_content)
    except Exception:
        # If parsing fails, return raw content
        return [html_content]

    # Strip noise tags first
    clean_root = _strip_noise_tags(root)

    # Apply smart content detection if enabled
    if auto_filter and not css_selector:
        detected_selectors = detect_main_content(html_content, url)
        if detected_selectors:
            # Try each selector until we find content
            for sel in detected_selectors:
                elements = _css_select(clean_root, sel)
                if elements:
                    css_selector = sel
                    break

    # Find target elements
    if css_selector:
        elements = _css_select(clean_root, css_selector)
    else:
        # Use body or entire document
        body = clean_root.xpath('//body')
        if body:
            elements = [body[0]]
        else:
            elements = [clean_root]

    # Extract content from each element
    results = []
    for elem in elements:
        content = _extract_element(elem, extraction_type)
        if content:
            results.append(content)

    return results if results else [""]


def _strip_noise_tags(root: HtmlElement) -> HtmlElement:
    """Remove noise tags from the HTML tree."""
    clean_root = deepcopy(root)
    for tag in NOISE_TAGS:
        for elem in clean_root.xpath(f'//{tag}'):
            elem.drop_tree()
    return clean_root


def _css_select(root: HtmlElement, selector: str) -> List[HtmlElement]:
    """
    Select elements using CSS-like selector.

    Supports basic CSS selectors: tag, .class, #id, [attr=value]
    """
    elements = []

    # Parse selector type
    if selector.startswith('#'):
        # ID selector
        id_val = selector[1:]
        elements = root.xpath(f'//*[@id="{id_val}"]')
    elif selector.startswith('.'):
        # Class selector
        class_val = selector[1:]
        elements = root.xpath(f'//*[contains(@class, "{class_val}")]')
    elif '[' in selector:
        # Attribute selector like [role="main"]
        # Convert to XPath
        attr_match = re.match(r'\[(\w+)="?(\w+)"?\]', selector)
        if attr_match:
            attr_name, attr_value = attr_match.groups()
            elements = root.xpath(f'//*[@{attr_name}="{attr_value}"]')
        else:
            # Fallback: try as tag with attribute
            tag_match = re.match(r'(\w+)\[.*\]', selector)
            if tag_match:
                tag = tag_match.group(1)
                elements = root.xpath(f'//{tag}')
    elif '.' in selector:
        # Tag with class like "div.content"
        parts = selector.split('.', 1)
        tag = parts[0]
        class_val = parts[1]
        elements = root.xpath(f'//{tag}[contains(@class, "{class_val}")]')
    else:
        # Simple tag selector
        elements = root.xpath(f'//{selector}')

    return elements if elements else []


def _extract_element(elem: HtmlElement, extraction_type: ExtractionType) -> str:
    """Extract content from a single element in specified format."""
    try:
        html_str = tostring(elem, encoding='unicode', pretty_print=False)

        match extraction_type:
            case "markdown":
                return _convert_to_markdown(html_str)
            case "html":
                return html_str.strip()
            case "text":
                return _extract_text(elem)
            case _:
                return html_str.strip()
    except Exception:
        return ""


def _convert_to_markdown(html_str: str) -> str:
    """Convert HTML to Markdown."""
    # Use markdownify with some options
    result = md(
        html_str,
        heading_style="ATX",  # Use # for headings
        bullets="-",  # Use - for bullets
        strip=['script', 'style', 'noscript', 'svg', 'iframe'],
    )
    # Clean up excessive whitespace
    result = re.sub(r'\n{3,}', '\n\n', result)
    return result.strip()


def _extract_text(elem: HtmlElement) -> str:
    """Extract plain text from element."""
    # Get text content, excluding certain tags
    text = elem.text_content()

    # Clean up whitespace
    text = re.sub(r'[ \t]+', ' ', text)
    text = re.sub(r'\n{3,}', '\n\n', text)
    text = re.sub(r' +\n', '\n', text)

    return text.strip()