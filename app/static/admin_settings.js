// JavaScript for admin_settings.html
// Handles test buttons, API key links, feedback, etc.


// API Key Helper Links
function setApiKeyLinks() {
  const radarrUrl = document.getElementById('radarr_url').value;
  const sonarrUrl = document.getElementById('sonarr_url').value;
  const bazarrUrl = document.getElementById('bazarr_url').value;
  if (document.getElementById('radarr_key_link'))
    document.getElementById('radarr_key_link').href = radarrUrl ? radarrUrl.replace(/\/$/, '') + '/settings/api' : '#';
  if (document.getElementById('sonarr_key_link'))
    document.getElementById('sonarr_key_link').href = sonarrUrl ? sonarrUrl.replace(/\/$/, '') + '/settings/api' : '#';
  if (document.getElementById('bazarr_key_link'))
    document.getElementById('bazarr_key_link').href = bazarrUrl ? bazarrUrl.replace(/\/$/, '') + '/settings/api' : '#';
}

document.addEventListener('DOMContentLoaded', function() {
  console.log('[DEBUG] DOMContentLoaded fired');
  setApiKeyLinks();
  bindTests(); // Bind the test button handlers

  // Add listeners to update API key helper links on URL change
  if (document.getElementById('radarr_url'))
    document.getElementById('radarr_url').addEventListener('input', setApiKeyLinks);
  if (document.getElementById('sonarr_url'))
    document.getElementById('sonarr_url').addEventListener('input', setApiKeyLinks);
  if (document.getElementById('bazarr_url'))
    document.getElementById('bazarr_url').addEventListener('input', setApiKeyLinks);
});

// No-op: button appearance does not change
function updateBtnState(btn, state) {
  // Do nothing: keep button text and color unchanged, always enabled
}

// Updates the status dot color and title for a given service
function updateStatusDot(service, success) {
  const dot = document.getElementById(`${service}_status_dot`);
  if (dot) {
    dot.classList.remove('text-green-500', 'text-red-500');
    dot.classList.add(success ? 'text-green-500' : 'text-red-500');
    dot.title = success ? 'Connected' : 'Not Connected/Error';
  }
}

function bindTests() {
  const testBtns = document.querySelectorAll('.test-btn');
  testBtns.forEach(btn => {
    btn.addEventListener('click', function() {
      const service = btn.dataset.service;
      let url = '';
      let key = '';
      if (service === 'radarr') {
        url = document.getElementById('radarr_url').value;
        key = document.getElementById('radarr_api_key').value;
      } else if (service === 'sonarr') {
        url = document.getElementById('sonarr_url').value;
        key = document.getElementById('sonarr_api_key').value;
      } else if (service === 'bazarr') {
        url = document.getElementById('bazarr_url').value;
        key = document.getElementById('bazarr_api_key').value;
      } else if (service === 'ollama') {
        url = document.getElementById('ollama_url').value;
      } else if (service === 'tautulli') {
        url = document.getElementById('tautulli_url').value;
        key = document.getElementById('tautulli_api_key').value;
      }
      
      fetch('/admin/test-api', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ service, url, api_key: key })
      })
      .then(res => res.json())
      .then(data => {
        updateStatusDot(service, data.success);
      })
      .catch(() => {
        updateStatusDot(service, false);
      });
    });
  });
  // Pushover test (single card, robust targeting)
  const pushoverBtn = document.getElementById('pushover-test-btn');
  if (pushoverBtn) {
    pushoverBtn.addEventListener('click', function () {
      const tokenInput = document.getElementById('pushover_token');
      const keyInput = document.getElementById('pushover_key');
      const statusElem = document.getElementById('pushover_status');

      // Reset feedback
      statusElem.textContent = '';
      statusElem.className = 'ml-2 text-sm';

      const token = tokenInput ? tokenInput.value : '';
      const userKey = keyInput ? keyInput.value : '';
      if (!token || !userKey) {
        statusElem.textContent = 'Token and User Key required';
        statusElem.className = 'ml-2 text-sm text-red-600';
        return;
      }
      pushoverBtn.disabled = true;
      statusElem.textContent = 'Testing...';
      statusElem.className = 'ml-2 text-sm text-gray-600';
      fetch('/admin/test-pushover', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          token: token,
          user_key: userKey
        })
      })
      .then(res => res.json())
      .then(data => {
        if (data.success) {
          statusElem.textContent = 'Success!';
          statusElem.className = 'ml-2 text-sm text-green-600';
        } else {
          statusElem.textContent = 'Failed: ' + (data.error || 'Unknown error');
          statusElem.className = 'ml-2 text-sm text-red-600';
        }
      })
      .catch(() => {
        statusElem.textContent = 'Error';
        statusElem.className = 'ml-2 text-sm text-red-600';
      })
      .finally(() => {
        pushoverBtn.disabled = false;
      });
    });
  }
}


document.addEventListener('DOMContentLoaded', bindTests);
