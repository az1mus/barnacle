/**
 * Barnacle Bridge - Content Script
 * 
 * Injected into pages to extract content and handle special cases.
 */

(function() {
  'use strict';

  // Mark that content script is loaded
  window.__barnacleLoaded = true;

  /**
   * Listen for messages from background script
   */
  chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
    if (message.type === 'extractContent') {
      const result = extractContent(message.options);
      sendResponse(result);
      return true;
    }

    if (message.type === 'getPageInfo') {
      sendResponse({
        url: window.location.href,
        title: document.title,
        readyState: document.readyState
      });
      return true;
    }

    if (message.type === 'scrollToBottom') {
      scrollToBottom(message.options?.delay || 500);
      sendResponse({ success: true });
      return true;
    }

    return false;
  });

  /**
   * Extract content from page
   */
  function extractContent(options = {}) {
    const {
      cssSelector = null,
      autoFilter = true,
      includeHidden = false,
      removeScripts = true,
      removeStyles = true
    } = options;

    try {
      // Detect main content selector
      const detectedSelector = autoFilter ? detectMainContent() : null;
      const selector = cssSelector || detectedSelector;

      let targetEl = selector ? document.querySelector(selector) : null;
      if (!targetEl) {
        targetEl = document.body;
      }

      // Clone element for processing
      const clone = targetEl.cloneNode(true);

      // Remove unwanted elements
      if (removeScripts) {
        clone.querySelectorAll('script, noscript').forEach(el => el.remove());
      }
      if (removeStyles) {
        clone.querySelectorAll('style').forEach(el => el.remove());
      }

      // Remove hidden elements unless requested
      if (!includeHidden) {
        clone.querySelectorAll('[style*="display: none"], [style*="display:none"], [hidden]').forEach(el => el.remove());
      }

      // Get text content
      const text = clone.innerText || clone.textContent || '';

      // Get HTML
      const html = clone.innerHTML;

      // Get metadata
      const metadata = extractMetadata();

      return {
        success: true,
        html: html,
        text: text.trim(),
        title: document.title,
        url: window.location.href,
        detectedSelector: selector,
        metadata: metadata
      };

    } catch (error) {
      return {
        success: false,
        error: error.message
      };
    }
  }

  /**
   * Detect main content area
   */
  function detectMainContent() {
    // Priority list of selectors to try
    const selectors = [
      // Semantic HTML5
      'article',
      '[role="main"]',
      'main',

      // Common content classes
      '.post-content',
      '.article-content',
      '.entry-content',
      '.post-body',
      '.article-body',
      '.content-body',

      // Common content IDs
      '#article-content',
      '#post-content',

      // Generic content areas
      '.content',
      '#content',
      '#main',
      '.main',

      // Blog/News specific
      '.post',
      '.article',
      '.entry',

      // Fallback
      '.container'
    ];

    // Score each candidate
    let bestSelector = null;
    let bestScore = 0;

    for (const selector of selectors) {
      const elements = document.querySelectorAll(selector);

      for (const el of elements) {
        const score = scoreElement(el);
        if (score > bestScore) {
          bestScore = score;
          bestSelector = selector;
        }
      }
    }

    return bestScore > 100 ? bestSelector : null;
  }

  /**
   * Score an element for content likelihood
   */
  function scoreElement(el) {
    let score = 0;

    // Text length
    const text = el.innerText || '';
    score += Math.min(text.length, 5000);

    // Paragraph count
    const paragraphs = el.querySelectorAll('p');
    score += paragraphs.length * 50;

    // Link density (lower is better for content)
    const links = el.querySelectorAll('a');
    const linkText = Array.from(links).reduce((sum, a) => sum + (a.innerText?.length || 0), 0);
    const linkDensity = text.length > 0 ? linkText / text.length : 0;
    score -= linkDensity * 500;

    // Presence of article-like elements
    if (el.querySelector('h1, h2, h3')) score += 100;
    if (el.querySelector('img')) score += 50;

    // Penalize navigation-like elements
    if (el.querySelector('nav')) score -= 200;
    if (el.querySelector('header')) score -= 100;
    if (el.querySelector('footer')) score -= 100;

    return Math.max(0, score);
  }

  /**
   * Extract metadata from page
   */
  function extractMetadata() {
    const metadata = {
      description: '',
      keywords: '',
      author: '',
      publishDate: '',
      ogTitle: '',
      ogDescription: '',
      ogImage: ''
    };

    // Standard meta tags
    const description = document.querySelector('meta[name="description"]');
    if (description) metadata.description = description.content;

    const keywords = document.querySelector('meta[name="keywords"]');
    if (keywords) metadata.keywords = keywords.content;

    const author = document.querySelector('meta[name="author"]');
    if (author) metadata.author = author.content;

    // Open Graph
    const ogTitle = document.querySelector('meta[property="og:title"]');
    if (ogTitle) metadata.ogTitle = ogTitle.content;

    const ogDescription = document.querySelector('meta[property="og:description"]');
    if (ogDescription) metadata.ogDescription = ogDescription.content;

    const ogImage = document.querySelector('meta[property="og:image"]');
    if (ogImage) metadata.ogImage = ogImage.content;

    // Article dates
    const publishDate = document.querySelector('meta[property="article:published_time"], time[datetime]');
    if (publishDate) {
      metadata.publishDate = publishDate.getAttribute('datetime') || publishDate.content;
    }

    return metadata;
  }

  /**
   * Scroll to bottom of page (useful for lazy-loaded content)
   */
  async function scrollToBottom(delay = 500) {
    const scrollHeight = document.documentElement.scrollHeight;
    const viewportHeight = window.innerHeight;

    for (let pos = 0; pos < scrollHeight; pos += viewportHeight / 2) {
      window.scrollTo(0, pos);
      await new Promise(resolve => setTimeout(resolve, delay));
    }

    window.scrollTo(0, document.body.scrollHeight);
  }

})();