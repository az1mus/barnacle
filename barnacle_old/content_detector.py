# -*- coding: utf-8 -*-
"""
Smart Content Detector Module.

This module provides intelligent HTML content detection that automatically identifies
the main content area of a webpage. It uses perplexity (via distilgpt2) as the primary
metric - higher perplexity indicates more informative/surprising content.
"""

import logging
import math
from hashlib import sha256
from re import compile as re_compile, IGNORECASE
from typing import Optional, List, Dict

from lxml.html import HtmlElement, fromstring

logger = logging.getLogger(__name__)

# Model state
_model = None
_tokenizer = None
_model_loaded = False


def init_model() -> bool:
    """
    Initialize distilgpt2 model at startup.
    
    Call this during MCP server initialization to avoid delay on first request.
    
    :return: True if model loaded successfully, False otherwise
    """
    global _model, _tokenizer, _model_loaded
    
    if _model_loaded:
        return _model is not None
    
    _model_loaded = True
    
    try:
        from transformers import AutoModelForCausalLM, AutoTokenizer
        import torch

        logger.info("Loading distilgpt2 model for perplexity calculation...")
        _tokenizer = AutoTokenizer.from_pretrained("distilgpt2")
        _model = AutoModelForCausalLM.from_pretrained("distilgpt2")
        _model.eval()
        logger.info("distilgpt2 model loaded successfully")
        return True
    except Exception as e:
        logger.warning(f"Failed to load distilgpt2: {e}. Perplexity scoring disabled.")
        _model = None
        _tokenizer = None
        return False


def _load_model():
    """Load distilgpt2 model and tokenizer (lazy loading fallback)."""
    global _model, _tokenizer, _model_loaded
    
    if not _model_loaded:
        init_model()
    
    return _model, _tokenizer


def calculate_perplexity(text: str, max_length: int = 512) -> float:
    """
    Calculate perplexity of text using distilgpt2.
    
    Higher perplexity = more "surprising" content = more likely to be main content.
    Lower perplexity = repetitive/template content = likely noise.
    
    :param text: Text to evaluate
    :param max_length: Maximum tokens to process
    :return: Perplexity score (higher is better for content detection)
    """
    model, tokenizer = _load_model()
    
    if model is None or tokenizer is None:
        return 0.0
    
    if not text or len(text.strip()) < 20:
        return 0.0
    
    try:
        import torch
        
        # Truncate text if too long
        encodings = tokenizer(
            text[:max_length * 4],
            return_tensors="pt",
            truncation=True,
            max_length=max_length,
        )
        
        with torch.no_grad():
            outputs = model(encodings.input_ids, labels=encodings.input_ids)
            loss = outputs.loss.item()
            
        # Perplexity = exp(loss)
        perplexity = math.exp(loss)
        return perplexity
        
    except Exception as e:
        logger.debug(f"Perplexity calculation failed: {e}")
        return 0.0


# Tags that are typically noise/navigation
NOISE_TAGS = ('nav', 'header', 'footer', 'aside', 'script', 'style', 'noscript', 'iframe', 'svg', 'form')

# Common class/ID patterns that indicate main content
CONTENT_PATTERNS = [
    r'(article|post|content|main|story|entry|text|body|document)',
    r'(post-content|article-content|entry-content|main-content)',
    r'(markdown|docs?|documentation|readme|tutorial)',
    r'(page-content|site-content|wrapper-content)',
    r'(文章|内容|正文|帖子|博客|热搜|榜单|排行)',
    r'(article-content|post-content|rich-text)',
    r'(content-area|content-wrapper|main-wrapper)',
    r'(data|list|table|rank|hot|realtime)',
]

# High-value ID patterns that strongly indicate main content
HIGH_VALUE_IDS = [
    'plc_main',
    'pl_top_realtimehot',
    'main',
    'content',
    'article',
    'post',
    'entry',
]

# Patterns that indicate noise/sidebar
NOISE_PATTERNS = [
    r'(sidebar|widget|nav|menu|footer|header|comment|advertisement|ad-|ads)',
    r'(related|share|social|tag|category|breadcrumb)',
    r'(pagination|pager|nav-links)',
    r'(sidebar|side-bar|left-bar|right-bar)',
    r'(using|instruction|protocol|agreement|terms|policy)',
]

# Compile patterns for efficiency
_CONTENT_PATTERN_RE = re_compile('|'.join(CONTENT_PATTERNS), IGNORECASE)
_NOISE_PATTERN_RE = re_compile('|'.join(NOISE_PATTERNS), IGNORECASE)


class ContentCandidate:
    """Represents a potential main content element with scoring."""

    __slots__ = ('element', 'selector', 'text', 'text_length', 'link_length',
                 'tag_count', 'perplexity', 'pattern_score', 'total_score')

    def __init__(
        self,
        element: HtmlElement,
        selector: str,
        text: str,
        text_length: int,
        link_length: int,
        tag_count: int,
        perplexity: float,
        pattern_score: float,
    ):
        self.element = element
        self.selector = selector
        self.text = text
        self.text_length = text_length
        self.link_length = link_length
        self.tag_count = tag_count
        self.perplexity = perplexity
        self.pattern_score = pattern_score
        
        # Calculate perplexity score:
        # - Very high perplexity (>1000) = abnormal page (captcha, error) = bad
        # - Low perplexity (<10) = data list (hot search, ranking) = good
        # - Medium perplexity (10-100) = normal content = okay
        if perplexity > 1000:
            # Abnormal page, heavily penalize
            ppl_score = -50.0
        elif perplexity < 1:
            # No perplexity calculated (model not loaded), use pattern only
            ppl_score = 0.0
        elif perplexity < 10:
            # Data list - low perplexity is GOOD, give bonus
            ppl_score = 15.0 - perplexity  # Higher score for lower perplexity
        elif perplexity < 50:
            # Normal content - medium score
            ppl_score = 5.0
        elif perplexity < 100:
            # Somewhat unusual content
            ppl_score = 2.0
        else:
            # Unusual content, penalize
            ppl_score = -10.0
        
        # Total score
        self.total_score = ppl_score + pattern_score * 2.0 + min(text_length / 1000, 5.0)

    def __repr__(self) -> str:
        return f"ContentCandidate(selector={self.selector}, ppl={self.perplexity:.1f}, score={self.total_score:.2f})"


class SmartContentDetector:
    """Intelligent content detector using perplexity-based scoring."""

    MIN_TEXT_LENGTH = 50
    MAX_CANDIDATES = 50
    TOP_N_SELECTORS = 3

    def __init__(self):
        self._cache: Dict[str, Optional[List[str]]] = {}

    def detect(self, html_content: str | bytes, url: str = "") -> Optional[List[str]]:
        """
        Detect the top CSS selectors for main content.
        
        :param html_content: HTML content as string or bytes
        :param url: Optional URL for caching purposes
        :return: List of top 3 CSS selector strings or None
        """
        cache_key = self._get_cache_key(html_content, url)
        if cache_key in self._cache:
            logger.debug(f"Using cached selectors: {self._cache[cache_key]}")
            return self._cache[cache_key]

        try:
            if isinstance(html_content, bytes):
                html_content = html_content.decode('utf-8', errors='ignore')

            root = fromstring(html_content)

            # Check for obvious semantic tags first
            semantic_selector = self._check_semantic_tags(root)
            if semantic_selector:
                self._cache[cache_key] = [semantic_selector]
                return [semantic_selector]

            # Find all candidate elements
            candidates = self._find_candidates(root)

            if not candidates:
                logger.debug("No content candidates found")
                self._cache[cache_key] = None
                return None

            # Score candidates using perplexity
            scored_candidates = self._score_candidates(candidates)

            # Select top N candidates
            top_candidates = self._select_top_n(scored_candidates)

            if top_candidates:
                selectors = [c.selector for c in top_candidates]
                logger.debug(f"Top selectors: {[f'{c.selector}(ppl={c.perplexity:.1f})' for c in top_candidates]}")
                self._cache[cache_key] = selectors
                return selectors

            self._cache[cache_key] = None
            return None

        except Exception as e:
            logger.warning(f"Content detection failed: {e}")
            return None

    def _get_cache_key(self, html_content: str | bytes, url: str) -> str:
        """Generate cache key from content and URL."""
        content_sample = html_content[:1000] if isinstance(html_content, str) else html_content[:1000]
        return sha256(f"{url}:{content_sample}".encode()).hexdigest()[:16]

    def _check_semantic_tags(self, root: HtmlElement) -> Optional[str]:
        """Quick check for obvious semantic HTML5 tags."""
        for tag in ('article', 'main'):
            elements = root.xpath(f'//{tag}')
            for elem in elements:
                if len(elem.text_content().strip()) > self.MIN_TEXT_LENGTH:
                    parent_tags = [p.tag for p in elem.iterancestors()]
                    if not any(pt in NOISE_TAGS for pt in parent_tags):
                        logger.debug(f"Found semantic tag: {tag}")
                        return tag

        # Check for role="main" attribute
        elements_with_role = root.xpath('//*[@role="main"]')
        for elem in elements_with_role:
            if len(elem.text_content().strip()) > self.MIN_TEXT_LENGTH:
                parent_tags = [p.tag for p in elem.iterancestors()]
                if not any(pt in NOISE_TAGS for pt in parent_tags):
                    logger.debug("Found element with role='main'")
                    return '[role="main"]'

        return None

    def _find_candidates(self, root: HtmlElement) -> List[HtmlElement]:
        """Find potential content container elements."""
        candidates = []

        for tag in ('div', 'section', 'article', 'main', 'table', 'ul', 'ol'):
            elements = root.xpath(f'//{tag}')
            for elem in elements:
                if self._is_noise_element(elem):
                    continue

                text = elem.text_content().strip()
                if len(text) < self.MIN_TEXT_LENGTH:
                    continue

                candidates.append(elem)

                if len(candidates) >= self.MAX_CANDIDATES:
                    break

            if len(candidates) >= self.MAX_CANDIDATES:
                break

        return candidates

    def _is_noise_element(self, elem: HtmlElement) -> bool:
        """Check if element is likely a noise/navigation element."""
        if elem.tag in NOISE_TAGS:
            return True

        classes = elem.get('class', '')
        id_attr = elem.get('id', '')
        combined = f"{classes} {id_attr}"

        if _NOISE_PATTERN_RE.search(combined):
            return True

        for parent in elem.iterancestors():
            if parent.tag in NOISE_TAGS:
                return True
            parent_classes = parent.get('class', '')
            parent_id = parent.get('id', '')
            if _NOISE_PATTERN_RE.search(f"{parent_classes} {parent_id}"):
                return True

        return False

    def _score_candidates(self, candidates: List[HtmlElement]) -> List[ContentCandidate]:
        """Score each candidate element using perplexity."""
        scored = []

        for elem in candidates:
            selector = self._generate_selector(elem)
            text = elem.text_content().strip()
            text_length = len(text)

            link_elements = elem.xpath('.//a')
            link_text_length = sum(len(link.text_content().strip()) for link in link_elements)

            tag_count = len(elem.xpath('.//*'))

            # Calculate perplexity (primary metric)
            perplexity = calculate_perplexity(text)

            # Pattern score for bonus
            pattern_score = self._calculate_pattern_score(elem)

            candidate = ContentCandidate(
                element=elem,
                selector=selector,
                text=text,
                text_length=text_length,
                link_length=link_text_length,
                tag_count=tag_count,
                perplexity=perplexity,
                pattern_score=pattern_score,
            )
            scored.append(candidate)

        scored.sort(key=lambda c: c.total_score, reverse=True)
        return scored

    def _calculate_pattern_score(self, elem: HtmlElement) -> float:
        """Calculate score based on class/ID patterns."""
        score = 0.0

        classes = elem.get('class', '')
        id_attr = elem.get('id', '')
        combined = f"{classes} {id_attr}"

        matches = _CONTENT_PATTERN_RE.findall(combined)
        score += len(matches) * 0.5

        # High bonus for specific high-value IDs
        for hv_id in HIGH_VALUE_IDS:
            if id_attr and id_attr.lower() == hv_id.lower():
                score += 3.0
                break

        return min(score, 5.0)

    def _generate_selector(self, elem: HtmlElement) -> str:
        """Generate a CSS selector for the element."""
        id_attr = elem.get('id')
        if id_attr and not id_attr.startswith('auto_'):
            return f"#{id_attr}"

        classes = elem.get('class', '').split()
        if classes:
            meaningful_classes = [
                c for c in classes
                if len(c) > 3 and not c.startswith('_') and not _NOISE_PATTERN_RE.search(c)
            ]
            if meaningful_classes:
                return f"{elem.tag}.{meaningful_classes[0]}"

        return elem.tag

    def _select_top_n(self, candidates: List[ContentCandidate]) -> List[ContentCandidate]:
        """Select the top N candidates from scored list."""
        if not candidates:
            return []

        # Filter candidates with minimum requirements
        # - Must have minimum text length
        # - Must not be abnormal page (perplexity > 1000)
        valid_candidates = [
            c for c in candidates
            if c.text_length >= self.MIN_TEXT_LENGTH and c.perplexity < 1000
        ]

        if not valid_candidates:
            logger.debug("No valid candidates found")
            # Fallback: return top candidates anyway
            return [c for c in candidates if c.text_length >= self.MIN_TEXT_LENGTH][:self.TOP_N_SELECTORS]

        return valid_candidates[:self.TOP_N_SELECTORS]

    def clear_cache(self) -> None:
        """Clear the detection cache."""
        self._cache.clear()
        logger.debug("Content detector cache cleared")


# Global instance
_detector: Optional[SmartContentDetector] = None


def get_content_detector() -> SmartContentDetector:
    """Get the global content detector instance."""
    global _detector
    if _detector is None:
        _detector = SmartContentDetector()
    return _detector


def detect_main_content(html_content: str | bytes, url: str = "") -> Optional[List[str]]:
    """Convenience function to detect top 3 main content selectors."""
    detector = get_content_detector()
    return detector.detect(html_content, url)
