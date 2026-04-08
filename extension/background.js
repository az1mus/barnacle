/**
 * Barnacle Bridge - Background Service Worker
 *
 * Handles communication with Barnacle Python server via WebSocket,
 * manages tabs, and extracts page content.
 *
 * Auto-connects on startup, polling every second until connected,
 * then maintains connection with heartbeat every second.
 */

// Configuration
const DEFAULT_CONFIG = {
  wsUrl: 'ws://localhost:9877',
  taskTimeout: 10000,
};

let config = { ...DEFAULT_CONFIG };
let ws = null;
let isRunning = false;        // Whether polling/connection is active
let connectTimer = null;      // Timer for connection polling (1s interval)
let heartbeatTimer = null;    // Timer for heartbeat (1s interval)
let heartbeatFailures = 0;    // Count of consecutive heartbeat failures
const MAX_HEARTBEAT_FAILURES = 3;  // Max failures before returning to polling mode

// Task queue
let pendingTasks = new Map();
let currentTask = null;

/**
 * Initialize extension
 */
async function init() {
  // Load saved config
  const stored = await chrome.storage.local.get('config');
  if (stored.config) {
    config = { ...DEFAULT_CONFIG, ...stored.config };
  }

  console.log('[Barnacle] Extension initialized, WebSocket:', getWsUrl());
}

/**
 * Get WebSocket URL
 */
function getWsUrl() {
  return config.wsUrl || DEFAULT_CONFIG.wsUrl;
}

/**
 * Start polling for WebSocket connection
 * Attempts to connect every second until successful
 */
async function startPolling() {
  if (isRunning) return;

  isRunning = true;
  console.log('[Barnacle] Starting connection polling mode');

  // Start polling every second
  pollConnect();
}

/**
 * Poll for WebSocket connection every second
 */
function pollConnect() {
  if (!isRunning) return;

  console.log('[Barnacle] Attempting to connect to:', getWsUrl());

  // Stop heartbeat if running
  stopHeartbeat();

  // Close existing connection if any
  if (ws) {
    ws.close();
    ws = null;
  }

  try {
    ws = new WebSocket(getWsUrl());

    ws.onopen = () => {
      console.log('[Barnacle] WebSocket connected');
      heartbeatFailures = 0;

      // Notify server that extension is ready
      ws.send(JSON.stringify({ type: 'ready' }));

      // Stop polling and start heartbeat
      stopPollingTimer();
      startHeartbeat();
    };

    ws.onmessage = async (event) => {
      try {
        const message = JSON.parse(event.data);

        if (message.type === 'task' && message.task) {
          console.log('[Barnacle] Received task:', message.task.id, 'URL:', message.task.url);
          if (!currentTask) {
            currentTask = message.task;
            await executeTask(message.task);
          } else {
            // Queue task if one is already running
            pendingTasks.set(message.task.id, message.task);
          }
        } else if (message.type === 'pong') {
          // Heartbeat response - reset failure count
          heartbeatFailures = 0;
        } else if (message.type === 'ping') {
          // Respond to ping for keepalive
          ws.send(JSON.stringify({ type: 'pong' }));
        }
      } catch (error) {
        console.error('[Barnacle] Failed to parse WebSocket message:', error);
      }
    };

    ws.onclose = (event) => {
      console.log('[Barnacle] WebSocket closed:', event.code, event.reason);
      ws = null;

      if (isRunning) {
        // Schedule next poll attempt in 1 second (if no timer already running)
        if (!connectTimer) {
          connectTimer = setTimeout(() => {
            connectTimer = null;
            if (isRunning) {
              pollConnect();
            }
          }, 1000);
        }
      }
    };

    ws.onerror = (error) => {
      console.error('[Barnacle] WebSocket error:', error);
    };

  } catch (error) {
    console.error('[Barnacle] Failed to create WebSocket connection:', error);

    // Schedule next poll attempt in 1 second
    if (!connectTimer) {
      connectTimer = setTimeout(() => {
        connectTimer = null;
        if (isRunning) {
          pollConnect();
        }
      }, 1000);
    }
  }
}

/**
 * Return to polling mode after connection lost (e.g., heartbeat failures)
 */
function returnToPolling() {
  stopHeartbeat();
  heartbeatFailures = 0;

  // Close WebSocket if exists - onclose will schedule next poll
  if (ws) {
    ws.close();
    ws = null;
  } else {
    // No WebSocket, start polling directly
    pollConnect();
  }
}

/**
 * Start heartbeat - send ping every second
 */
function startHeartbeat() {
  if (heartbeatTimer) return;

  console.log('[Barnacle] Starting heartbeat');

  heartbeatTimer = setInterval(() => {
    if (!ws || ws.readyState !== WebSocket.OPEN) {
      heartbeatFailures++;
      console.log('[Barnacle] Heartbeat failed - connection not open, failures:', heartbeatFailures);

      if (heartbeatFailures >= MAX_HEARTBEAT_FAILURES) {
        console.log('[Barnacle] Max heartbeat failures reached, returning to polling mode');
        returnToPolling();
      }
      return;
    }

    try {
      ws.send(JSON.stringify({ type: 'ping' }));
      heartbeatFailures = 0;  // Reset on successful send
    } catch (error) {
      heartbeatFailures++;
      console.error('[Barnacle] Heartbeat send error:', error, 'failures:', heartbeatFailures);

      if (heartbeatFailures >= MAX_HEARTBEAT_FAILURES) {
        console.log('[Barnacle] Max heartbeat failures reached, returning to polling mode');
        returnToPolling();
      }
    }
  }, 1000);
}

/**
 * Stop heartbeat timer
 */
function stopHeartbeat() {
  if (heartbeatTimer) {
    clearInterval(heartbeatTimer);
    heartbeatTimer = null;
    console.log('[Barnacle] Heartbeat stopped');
  }
}

/**
 * Stop polling timer
 */
function stopPollingTimer() {
  if (connectTimer) {
    clearTimeout(connectTimer);
    connectTimer = null;
  }
}

/**
 * Stop WebSocket connection and polling
 */
async function stopPolling() {
  isRunning = false;

  // Stop all timers
  stopPollingTimer();
  stopHeartbeat();

  // Close WebSocket
  if (ws) {
    ws.close(1000, 'Extension stopped');
    ws = null;
  }

  console.log('[Barnacle] Stopped');
}

/**
 * Execute a fetch task
 */
async function executeTask(task) {
  const { id, url, options = {} } = task;
  const startTime = Date.now();
  
  let result = {
    taskId: id,
    success: false,
    url: url,
    finalUrl: url,
    status: 0,
    content: [],
    error: null,
    duration: 0
  };
  
  try {
    console.log('[Barnacle] Executing task:', id, 'URL:', url);
    
    // Create new tab
    const tab = await chrome.tabs.create({
      url: url,
      active: options.active !== false  // Default to active
    });
    
    // Wait for page load
    const loadResult = await waitForPageLoad(tab.id, options.timeout || 30000);
    
    if (!loadResult.success) {
      throw new Error(loadResult.error || 'Page load timeout');
    }
    
    // Get final URL after redirects
    const finalTab = await chrome.tabs.get(tab.id);
    result.finalUrl = finalTab.url;
    result.status = 200;
    
    // Wait additional time if specified
    if (options.wait > 0) {
      await sleep(options.wait);
    }
    
    // Extract content
    const content = await extractContent(tab.id, options);
    result.content = content;
    result.success = true;
    
    // Close tab if not keeping open
    if (options.keepOpen !== true) {
      await chrome.tabs.remove(tab.id);
    }
    
  } catch (error) {
    console.error('[Barnacle] Task error:', error);
    result.error = error.message;
    
    // Try to close tab if it exists
    try {
      const tabs = await chrome.tabs.query({ url: url });
      if (tabs.length > 0) {
        await chrome.tabs.remove(tabs[0].id);
      }
    } catch (e) {
      // Ignore cleanup errors
    }
  }
  
  result.duration = Date.now() - startTime;
  
  // Report result back to server
  await reportResult(result);
  
  currentTask = null;
}

/**
 * Wait for page to load
 */
function waitForPageLoad(tabId, timeout = 30000) {
  return new Promise((resolve) => {
    const startTime = Date.now();
    let resolved = false;
    
    const cleanup = () => {
      if (timeoutId) clearTimeout(timeoutId);
      if (listener) chrome.tabs.onUpdated.removeListener(listener);
      resolved = true;
    };
    
    const timeoutId = setTimeout(() => {
      if (!resolved) {
        cleanup();
        resolve({ success: false, error: 'Timeout waiting for page load' });
      }
    }, timeout);
    
    const listener = (updatedTabId, changeInfo, tab) => {
      if (updatedTabId !== tabId) return;
      
      if (changeInfo.status === 'complete') {
        cleanup();
        resolve({ success: true });
      } else if (changeInfo.status === 'loading') {
        // Reset timeout on navigation
      }
    };
    
    chrome.tabs.onUpdated.addListener(listener);
    
    // Check if already loaded
    chrome.tabs.get(tabId).then(tab => {
      if (tab.status === 'complete' && !resolved) {
        cleanup();
        resolve({ success: true });
      }
    });
  });
}

/**
 * Extract content from page
 */
async function extractContent(tabId, options = {}) {
  const { extractionType = 'markdown', cssSelector = null, autoFilter = true } = options;
  
  try {
    // Execute content script to extract page data
    const results = await chrome.scripting.executeScript({
      target: { tabId },
      func: extractPageContent,
      args: [cssSelector, autoFilter]
    });
    
    if (!results || results.length === 0) {
      return [];
    }
    
    const pageData = results[0].result;
    
    if (!pageData || !pageData.html) {
      return [];
    }
    
    // Convert to requested format
    // For now, return HTML and let Python side handle conversion
    return [{
      type: extractionType,
      content: pageData.html,
      title: pageData.title,
      url: pageData.url,
      selector: pageData.detectedSelector
    }];
    
  } catch (error) {
    console.error('[Barnacle] Content extraction error:', error);
    return [];
  }
}

/**
 * Function to run in page context to extract content
 */
function extractPageContent(cssSelector, autoFilter) {
  // Detect main content selector
  function detectMainContent() {
    const candidates = [
      'article',
      '[role="main"]',
      'main',
      '.post-content',
      '.article-content',
      '.entry-content',
      '.content',
      '#content',
      '#main',
      '.main'
    ];
    
    for (const selector of candidates) {
      const el = document.querySelector(selector);
      if (el && el.innerText.length > 200) {
        return selector;
      }
    }
    return null;
  }
  
  const selector = cssSelector || (autoFilter ? detectMainContent() : null);
  let targetEl = selector ? document.querySelector(selector) : document.body;
  
  if (!targetEl) {
    targetEl = document.body;
  }
  
  return {
    html: targetEl.innerHTML,
    title: document.title,
    url: window.location.href,
    detectedSelector: selector
  };
}

/**
 * Report task result back to server via WebSocket
 */
async function reportResult(result) {
  const message = JSON.stringify({
    type: 'result',
    ...result
  });

  if (ws && ws.readyState === WebSocket.OPEN) {
    try {
      ws.send(message);
      console.log('[Barnacle] Reported result for task:', result.taskId, 'via WebSocket');
      return;
    } catch (error) {
      console.error('[Barnacle] WebSocket send failed:', error);
    }
  }

  console.error('[Barnacle] Failed to report result: WebSocket not connected');
}

/**
 * Sleep helper
 */
function sleep(ms) {
  return new Promise(resolve => setTimeout(resolve, ms));
}

/**
 * Handle messages from popup
 */
chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
  console.log('[Barnacle] Received message:', message.type);

  if (message.type === 'getStatus') {
    const wsState = ws ? ws.readyState : WebSocket.CLOSED;
    sendResponse({
      isRunning,
      wsUrl: getWsUrl(),
      wsConnected: wsState === WebSocket.OPEN,
      wsState: wsState,
      currentTask: currentTask ? currentTask.id : null
    });
    return true;
  }

  if (message.type === 'start') {
    // Handle async operation
    (async () => {
      await init();
      await startPolling();
      sendResponse({ success: true });
    })();
    return true;  // Keep channel open for async response
  }

  if (message.type === 'stop') {
    stopPolling();
    sendResponse({ success: true });
    return true;
  }

  if (message.type === 'setConfig') {
    config = { ...config, ...message.config };
    chrome.storage.local.set({ config });

    // Reconnect if running
    if (isRunning) {
      console.log('[Barnacle] Reconnecting due to config change');
      returnToPolling();
    }

    sendResponse({ success: true });
    return true;
  }

  return false;
});

// Initialize on install and auto-start polling
chrome.runtime.onInstalled.addListener(() => {
  init();
  console.log('[Barnacle] Extension installed, auto-starting polling');
  startPolling();
});

// Initialize on startup and auto-start polling
chrome.runtime.onStartup.addListener(() => {
  init();
  console.log('[Barnacle] Browser started, auto-starting polling');
  startPolling();
});