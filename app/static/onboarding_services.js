// JavaScript for onboarding_services.html
// Handles test buttons for Radarr, Sonarr, Bazarr, Tautulli, Jellyseer, Ollama, and Pushover during onboarding.

document.addEventListener('DOMContentLoaded', function() {
  const testBtns = document.querySelectorAll('.test-btn');
  testBtns.forEach(btn => {
    btn.addEventListener('click', async function() {
      const service = btn.dataset.service;
      let url = '';
      let key = '';
      let statusElem = document.getElementById(`${service}_status`);
      if (statusElem) statusElem.textContent = 'Testing...';
      btn.disabled = true;
      btn.classList.add('opacity-60');
      try {
        if (service === 'radarr') {
          url = document.getElementById('radarr_url').value;
          key = document.getElementById('radarr_api_key').value;
        } else if (service === 'sonarr') {
          url = document.getElementById('sonarr_url').value;
          key = document.getElementById('sonarr_api_key').value;
        } else if (service === 'bazarr') {
          url = document.getElementById('bazarr_url').value;
          key = document.getElementById('bazarr_api_key').value;
        } else if (service === 'tautulli') {
          url = document.getElementById('tautulli_url').value;
          key = document.getElementById('tautulli_api_key').value;
        } else if (service === 'jellyseer') {
          url = document.getElementById('jellyseer_url').value;
          key = document.getElementById('jellyseer_api_key').value;
        } else if (service === 'ollama') {
          url = document.getElementById('ollama_url').value;
        } else if (service === 'pushover') {
          key = document.getElementById('pushover_token').value;
          url = document.getElementById('pushover_key').value;
        }
        // POST to a dedicated test endpoint for each service
        const resp = await fetch(`/onboarding/test-service`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ service, url, key })
        });
        const data = await resp.json();
        if (statusElem) {
          statusElem.textContent = data.success ? 'Success!' : (data.message || 'Failed');
          statusElem.className = data.success ? 'ml-2 text-xs text-green-600' : 'ml-2 text-xs text-red-600';
        }
      } catch (err) {
        if (statusElem) {
          statusElem.textContent = 'Error';
          statusElem.className = 'ml-2 text-xs text-red-600';
        }
      } finally {
        btn.disabled = false;
        btn.classList.remove('opacity-60');
      }
    });
  });
});
