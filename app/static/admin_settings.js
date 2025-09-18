document.addEventListener('DOMContentLoaded', function() {
    // --- General Setup ---
    const form = document.getElementById('settings-form');
    const successBanner = document.getElementById('success-banner');

    // --- API Key Helper Links ---
    function setApiKeyLinks() {
        const radarrUrl = document.getElementById('radarr_url').value;
        const sonarrUrl = document.getElementById('sonarr_url').value;
        const bazarrUrl = document.getElementById('bazarr_url').value;
        const radarrKeyLink = document.getElementById('radarr_key_link');
        const sonarrKeyLink = document.getElementById('sonarr_key_link');
        const bazarrKeyLink = document.getElementById('bazarr_key_link');

        if (radarrKeyLink) radarrKeyLink.href = radarrUrl ? radarrUrl.replace(/\/$/, '') + '/settings/security/apikey' : '#';
        if (sonarrKeyLink) sonarrKeyLink.href = sonarrUrl ? sonarrUrl.replace(/\/$/, '') + '/settings/general' : '#';
        if (bazarrKeyLink) bazarrKeyLink.href = bazarrUrl ? bazarrUrl.replace(/\/$/, '') + '/settings/general' : '#';
    }

    // --- Service Connection Testing ---
    function updateStatusDot(service, success) {
        const dot = document.getElementById(`${service}_status_dot`);
        if (dot) {
            dot.classList.remove('text-green-500', 'text-red-500', 'text-yellow-500');
            dot.classList.add(success ? 'text-green-500' : 'text-red-500');
            dot.title = success ? 'Connected' : 'Not Connected / Error';
        }
    }

    document.querySelectorAll('.test-btn').forEach(button => {
        button.addEventListener('click', async function() {
            const service = button.dataset.service;
            const urlInput = document.getElementById(`${service}_url`);
            const apiKeyInput = document.getElementById(`${service}_api_key`);
            const statusDot = document.getElementById(`${service}_status_dot`);

            if (statusDot) {
                statusDot.classList.remove('text-green-500', 'text-red-500');
                statusDot.classList.add('text-yellow-500');
                statusDot.title = 'Testing...';
            }

            const url = urlInput ? urlInput.value : '';
            const apiKey = apiKeyInput ? apiKeyInput.value : '';

            try {
                const response = await fetch('/admin/test-api', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ service: service, url: url, api_key: apiKey })
                });
                const data = await response.json();
                updateStatusDot(service, data.success);

                if (service === 'ollama' && data.success) {
                    fetchOllamaModels(url, document.getElementById('ollama_model_name').value);
                }
            } catch (error) {
                console.error(`Error testing ${service}:`, error);
                updateStatusDot(service, false);
            }
        });
    });
    
    const pushoverBtn = document.getElementById('pushover-test-btn');
    if (pushoverBtn) {
        pushoverBtn.addEventListener('click', async function() {
            const tokenInput = document.getElementById('pushover_token');
            const keyInput = document.getElementById('pushover_key');
            const statusElem = document.getElementById('pushover_status');

            statusElem.textContent = 'Testing...';
            statusElem.className = 'ml-2 text-sm text-yellow-500';
            pushoverBtn.disabled = true;

            try {
                const response = await fetch('/admin/test-pushover', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ token: tokenInput.value, user_key: keyInput.value })
                });
                const data = await response.json();
                if (data.success) {
                    statusElem.textContent = 'Success!';
                    statusElem.className = 'ml-2 text-sm text-green-600';
                } else {
                    statusElem.textContent = 'Failed: ' + (data.error || 'Unknown error');
                    statusElem.className = 'ml-2 text-sm text-red-600';
                }
            } catch (error) {
                console.error('Error testing Pushover:', error);
                statusElem.textContent = 'Failed: Client-side error.';
                statusElem.className = 'ml-2 text-sm text-red-600';
            } finally {
                pushoverBtn.disabled = false;
            }
        });
    }

    // --- Ollama Model Fetching ---
    const ollamaUrlInput = document.getElementById('ollama_url');
    const ollamaModelSelect = document.getElementById('ollama_model_name');
    const ollamaModelWarning = document.getElementById('ollama-model-warning');

    async function fetchOllamaModels(url, savedModel) {
        if (!url || !ollamaModelSelect) {
            if (ollamaModelSelect) ollamaModelSelect.innerHTML = '<option value="">-- Enter Ollama URL first --</option>';
            return;
        }
        
        if (ollamaModelWarning) {
            ollamaModelWarning.textContent = 'Fetching models...';
            ollamaModelWarning.className = 'text-xs text-slate-500 dark:text-slate-400 mt-1';
            ollamaModelWarning.style.display = 'block';
        }

        try {
            const response = await fetch(`/admin/api/ollama-models?url=${encodeURIComponent(url)}`);
            const data = await response.json();

            ollamaModelSelect.innerHTML = '<option value="">-- Select a model --</option>';

            if (response.ok && data.models) {
                let savedModelExists = false;
                data.models.forEach(model => {
                    const option = document.createElement('option');
                    option.value = model;
                    option.textContent = model;
                    if (model === savedModel) {
                        option.selected = true;
                        savedModelExists = true;
                    }
                    ollamaModelSelect.appendChild(option);
                });

                if (savedModel && !savedModelExists) {
                    const option = document.createElement('option');
                    option.value = savedModel;
                    option.textContent = `${savedModel} (saved, not available)`;
                    option.selected = true;
                    ollamaModelSelect.appendChild(option);
                }
                
                if (ollamaModelWarning) {
                    if (data.models.length > 0) {
                        ollamaModelWarning.style.display = 'none';
                    } else {
                        ollamaModelWarning.textContent = "No models found on the server.";
                        ollamaModelWarning.className = 'text-xs text-amber-600 dark:text-amber-400 mt-1';
                    }
                }

            } else {
                if (savedModel) {
                    const option = document.createElement('option');
                    option.value = savedModel;
                    option.textContent = `${savedModel} (saved, connection failed)`;
                    option.selected = true;
                    ollamaModelSelect.appendChild(option);
                }
                if (ollamaModelWarning) {
                    ollamaModelWarning.textContent = data.error || "Could not fetch models. Check URL and ensure Ollama is running.";
                    ollamaModelWarning.className = 'text-xs text-amber-600 dark:text-amber-400 mt-1';
                }
            }
        } catch (error) {
            console.error('Error fetching Ollama models:', error);
            ollamaModelSelect.innerHTML = '<option value="">-- Select a model --</option>';
            if (savedModel) {
                const option = document.createElement('option');
                option.value = savedModel;
                option.textContent = `${savedModel} (saved, client error)`;
                option.selected = true;
                ollamaModelSelect.appendChild(option);
            }
            if (ollamaModelWarning) {
                ollamaModelWarning.textContent = 'Could not fetch models. Client-side error.';
                ollamaModelWarning.className = 'text-xs text-amber-600 dark:text-amber-400 mt-1';
            }
        }
    }

    // --- Form Submission ---
    if (form) {
        form.addEventListener('submit', function() {
            setTimeout(() => {
                if (successBanner) {
                    successBanner.style.display = 'flex';
                    setTimeout(() => {
                        successBanner.style.display = 'none';
                    }, 5000);
                }
            }, 100);
        });
    }

    // --- Initial Page Load Actions ---
    setApiKeyLinks();
    ['radarr_url', 'sonarr_url', 'bazarr_url'].forEach(id => {
        const el = document.getElementById(id);
        if (el) el.addEventListener('input', setApiKeyLinks);
    });
    
    if (ollamaUrlInput) {
        const savedModelName = ollamaModelSelect ? ollamaModelSelect.dataset.savedModel : null;
        if (ollamaUrlInput.value && savedModelName) {
            fetchOllamaModels(ollamaUrlInput.value, savedModelName);
        }
        ollamaUrlInput.addEventListener('change', function() {
            fetchOllamaModels(this.value, null);
        });
    }
}); 