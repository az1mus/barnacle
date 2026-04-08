/**
 * Barnacle Bridge - Popup Script
 *
 * Handles popup UI interactions.
 */

document.addEventListener('DOMContentLoaded', async () => {
  const statusEl = document.getElementById('status');
  const serverUrlEl = document.getElementById('serverUrl');
  const wsUrlInput = document.getElementById('wsUrlInput');
  const currentTaskEl = document.getElementById('currentTask');
  const taskRow = document.getElementById('taskRow');
  const startBtn = document.getElementById('startBtn');
  const stopBtn = document.getElementById('stopBtn');
  const saveConfigBtn = document.getElementById('saveConfig');

  /**
   * Update UI with current status
   */
  async function updateStatus() {
    try {
      const response = await chrome.runtime.sendMessage({ type: 'getStatus' });

      if (response.isRunning) {
        if (response.wsConnected) {
          statusEl.textContent = 'Connected';
          statusEl.className = 'status-value running';
          statusEl.style.color = '';
        } else {
          statusEl.textContent = 'Polling...';
          statusEl.className = 'status-value';
          statusEl.style.color = '#FF9800';
        }
        startBtn.disabled = true;
        stopBtn.disabled = false;
      } else {
        statusEl.textContent = 'Stopped';
        statusEl.className = 'status-value stopped';
        statusEl.style.color = '';
        startBtn.disabled = false;
        stopBtn.disabled = true;
      }

      serverUrlEl.textContent = response.wsUrl || '-';
      wsUrlInput.value = response.wsUrl || 'ws://localhost:9877';

      if (response.currentTask) {
        taskRow.style.display = 'flex';
        currentTaskEl.textContent = response.currentTask;
      } else {
        taskRow.style.display = 'none';
      }

    } catch (error) {
      statusEl.textContent = 'Error';
      statusEl.className = 'status-value error';
      console.error('Failed to get status:', error);
    }
  }

  /**
   * Start polling
   */
  startBtn.addEventListener('click', async () => {
    try {
      startBtn.disabled = true;
      startBtn.textContent = 'Starting...';

      await chrome.runtime.sendMessage({ type: 'start' });
      await updateStatus();

    } catch (error) {
      console.error('Failed to start:', error);
      startBtn.disabled = false;
      startBtn.textContent = 'Start';
    }
  });

  /**
   * Stop polling
   */
  stopBtn.addEventListener('click', async () => {
    try {
      stopBtn.disabled = true;
      stopBtn.textContent = 'Stopping...';

      await chrome.runtime.sendMessage({ type: 'stop' });
      await updateStatus();

    } catch (error) {
      console.error('Failed to stop:', error);
      stopBtn.disabled = false;
      stopBtn.textContent = 'Stop';
    }
  });

  /**
   * Save configuration
   */
  saveConfigBtn.addEventListener('click', async () => {
    const wsUrl = wsUrlInput.value.trim();

    if (!wsUrl) {
      alert('Please enter a WebSocket URL');
      return;
    }

    try {
      saveConfigBtn.disabled = true;
      saveConfigBtn.textContent = 'Saving...';

      await chrome.runtime.sendMessage({
        type: 'setConfig',
        config: { wsUrl }
      });

      await updateStatus();

      saveConfigBtn.textContent = 'Saved!';
      setTimeout(() => {
        saveConfigBtn.textContent = 'Save';
        saveConfigBtn.disabled = false;
      }, 1000);

    } catch (error) {
      console.error('Failed to save config:', error);
      saveConfigBtn.textContent = 'Error';
      saveConfigBtn.disabled = false;
    }
  });

  // Initial status update
  await updateStatus();

  // Periodic status update
  setInterval(updateStatus, 2000);
});