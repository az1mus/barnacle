# -*- coding: utf-8 -*-
"""
Smart Content Detector using ONNX model for perplexity calculation.

Model is loaded asynchronously to ensure fast server startup.
"""

import asyncio
import logging
import math
import re
from hashlib import sha256
from pathlib import Path
from typing import Optional, List, Dict

import numpy as np
from lxml.html import HtmlElement, fromstring
from optimum.onnxruntime import ORTModelForCausalLM
from transformers import AutoTokenizer

logger = logging.getLogger(__name__)

_model = None
_tokenizer = None
_model_ready = asyncio.Event()
_model_loading = False


async def load_model_async(model_path: str = None) -> None:
    """
    Asynchronously load ONNX model in background.
    Call this during server startup; it won't block.
    """
    global _model, _tokenizer, _model_loading, _model_ready

    if model_path is None:
        model_path = str(Path(__file__).parent.parent / "onnx-models" / "distilgpt2")

    if _model_loading or _model_ready.is_set():
        return

    _model_loading = True
    loop = asyncio.get_event_loop()

    def _load():
        global _model, _tokenizer
        logger.info(f"Loading ONNX model: {model_path}")
        tokenizer = AutoTokenizer.from_pretrained(model_path)
        model = ORTModelForCausalLM.from_pretrained(model_path)
        return model, tokenizer

    try:
        _model, _tokenizer = await loop.run_in_executor(None, _load)
        _model_ready.set()
        logger.info("ONNX model loaded successfully")
    except Exception as e:
        logger.error(f"Failed to load ONNX model: {e}")
        _model_loading = False


def get_perplexity(text: str, max_length: int = 512) -> float:
    """Calculate perplexity using ONNX model. Blocks briefly if model not ready."""
    if not _model_ready.is_set():
        return 0.0

    if not text or len(text.strip()) < 20:
        return 0.0

    try:
        import torch
        inputs = _tokenizer(
            text[:max_length * 4],
            return_tensors="pt",
            truncation=True,
            max_length=max_length,
        )

        with torch.no_grad():
            outputs = _model(**inputs)
            logits = outputs.logits
            # Shift for language modeling loss
            shift_logits = logits[..., :-1, :].contiguous()
            shift_labels = inputs["input_ids"][..., 1:].contiguous()
            loss_fct = torch.nn.CrossEntropyLoss()
            loss = loss_fct(
                shift_logits.view(-1, shift_logits.size(-1)),
                shift_labels.view(-1),
            ).item()

        return math.exp(min(loss, 20.0))  # Cap to avoid overflow
    except Exception as e:
        logger.debug(f"Perplexity calculation failed: {e}")
        return 0.0


NOISE_TAGS = ('nav', 'header', 'footer', 'aside', 'script', 'style', 'noscript', 'iframe', 'svg', 'form')

CONTENT_PATTERNS = [
    r'(article|post|content|main|story|entry|text|body|document)',
    r'(post-content|article-content|entry-content|main-content)',
    r'(markdown|docs?|documentation|readme|tutorial)',
    r'(文章|内容|正文|帖子|博客|热搜|榜单|排行)',
]

NOISE_PATTERNS = [
    r'(sidebar|widget|nav|menu|footer|header|comment|advertisement|ad-|ads)',
    r'(related|share|social|tag|category|breadcrumb|pagination)',
]

_CONTENT_RE = re.compile('|'.join(CONTENT_PATTERNS), re.IGNORECASE)
_NOISE_RE = re.compile('|'.join(NOISE_PATTERNS), re.IGNORECASE)


class SmartContentDetector:
    MIN_TEXT_LENGTH = 50
    MAX_CANDIDATES = 50

    def __init__(self):
        self._cache: Dict[str, Optional[List[str]]] = {}

    def detect(self, html: str | bytes, url: str = "") -> Optional[List[str]]:
        cache_key = sha256(f"{url}:{(html[:1000] if isinstance(html, str) else html[:1000])}".encode()).hexdigest()[:16]
        if cache_key in self._cache:
            return self._cache[cache_key]

        try:
            if isinstance(html, bytes):
                html = html.decode('utf-8', errors='ignore')

            root = fromstring(html)

            # Quick semantic tag check
            for tag in ('article', 'main', '[role="main"]'):
                elems = root.xpath(f'//{tag}') if not tag.startswith('[') else root.xpath(f'//*[@role="main"]')
                for el in elems:
                    if len(el.text_content().strip()) > self.MIN_TEXT_LENGTH:
                        self._cache[cache_key] = [tag]
                        return [tag]

            # Find candidates
            candidates = []
            for tag in ('div', 'section', 'article', 'main'):
                for elem in root.xpath(f'//{tag}'):
                    if elem.tag in NOISE_TAGS:
                        continue
                    text = elem.text_content().strip()
                    if len(text) < self.MIN_TEXT_LENGTH:
                        continue
                    if _NOISE_RE.search(elem.get('class', '') + ' ' + elem.get('id', '')):
                        continue
                    candidates.append((elem, text))
                    if len(candidates) >= self.MAX_CANDIDATES:
                        break
                if len(candidates) >= self.MAX_CANDIDATES:
                    break

            if not candidates:
                self._cache[cache_key] = None
                return None

            # Score candidates
            scored = []
            for elem, text in candidates:
                ppl = get_perplexity(text)
                pattern_score = len(_CONTENT_RE.findall(elem.get('class', '') + ' ' + elem.get('id', ''))) * 0.5
                total = pattern_score * 2.0 + min(len(text) / 1000, 5.0)
                if 1 < ppl < 1000:
                    total += 5.0
                elif ppl > 1000:
                    total -= 50.0
                scored.append((elem, text, total))

            scored.sort(key=lambda x: x[2], reverse=True)

            if scored:
                selectors = [self._selector(e) for e, _, _ in scored[:3]]
                self._cache[cache_key] = selectors
                return selectors

            self._cache[cache_key] = None
            return None

        except Exception as e:
            logger.warning(f"Detection failed: {e}")
            return None

    def _selector(self, elem: HtmlElement) -> str:
        id_attr = elem.get('id')
        if id_attr:
            return f"#{id_attr}"
        classes = elem.get('class', '').split()
        if classes:
            return f"{elem.tag}.{classes[0]}"
        return elem.tag

    def clear_cache(self):
        self._cache.clear()


_detector: Optional[SmartContentDetector] = None


def get_content_detector() -> SmartContentDetector:
    global _detector
    if _detector is None:
        _detector = SmartContentDetector()
    return _detector


def detect_main_content(html: str | bytes, url: str = "") -> Optional[List[str]]:
    return get_content_detector().detect(html, url)
