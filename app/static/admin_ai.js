// JavaScript for admin_ai.html - AI admin page interactivity
document.addEventListener('DOMContentLoaded', function() {

  // ======================== TAB SWITCHING ========================
  const tabButtons = document.querySelectorAll('.ai-tab');
  const tabPanels = document.querySelectorAll('[data-panel]');

  tabButtons.forEach(button => {
    button.addEventListener('click', () => {
      const targetPanel = button.dataset.tab;

      tabButtons.forEach(btn => {
        btn.classList.remove('bg-white', 'dark:bg-slate-800', 'text-sky-600', 'dark:text-sky-400', 'border-slate-200', 'dark:border-slate-700', 'border-b-white', 'dark:border-b-slate-800', 'shadow-sm', '-mb-px', 'z-10');
        btn.classList.add('bg-slate-100', 'dark:bg-slate-900', 'text-slate-600', 'dark:text-slate-400', 'border-transparent', 'hover:bg-slate-200', 'dark:hover:bg-slate-800');
      });
      button.classList.remove('bg-slate-100', 'dark:bg-slate-900', 'text-slate-600', 'dark:text-slate-400', 'border-transparent', 'hover:bg-slate-200', 'dark:hover:bg-slate-800');
      button.classList.add('bg-white', 'dark:bg-slate-800', 'text-sky-600', 'dark:text-sky-400', 'border-slate-200', 'dark:border-slate-700', 'border-b-white', 'dark:border-b-slate-800', 'shadow-sm', '-mb-px', 'z-10');

      tabPanels.forEach(panel => panel.classList.add('hidden'));
      document.querySelector(`[data-panel="${targetPanel}"]`).classList.remove('hidden');
    });
  });

  // ======================== CONNECTION TESTING ========================
  document.querySelectorAll('.test-btn').forEach(btn => {
    btn.addEventListener('click', async () => {
      const service = btn.dataset.service;
      const statusDot = document.getElementById(`${service}-status`);
      const form = document.getElementById('ai-settings-form');
      const formData = new FormData(form);

      btn.disabled = true;
      btn.textContent = 'Testing...';
      if (statusDot) {
        statusDot.style.color = '#eab308'; // yellow
        statusDot.title = 'Testing...';
      }

      try {
        const payload = { service };
        if (service === 'ollama') {
          payload.url = formData.get('ollama_url');
        } else if (service === 'openai') {
          payload.api_key = formData.get('openai_api_key');
          payload.model = formData.get('openai_model_name');
        } else if (service === 'openrouter') {
          payload.api_key = formData.get('openrouter_api_key');
          payload.model = formData.get('openrouter_model_name');
        }

        const resp = await fetch('/admin/ai/test-connection', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(payload)
        });
        const data = await resp.json();

        if (data.success) {
          if (statusDot) {
            statusDot.style.color = '#22c55e'; // green
            statusDot.title = 'Connected';
          }
          btn.textContent = 'Connected!';

          // If Ollama, populate models dropdown
          if (service === 'ollama' && data.models) {
            const select = document.getElementById('ollama-model-select');
            const currentVal = formData.get('ollama_model_name');
            select.innerHTML = '';
            data.models.forEach(m => {
              const opt = document.createElement('option');
              opt.value = m;
              opt.textContent = m;
              if (m === currentVal) opt.selected = true;
              select.appendChild(opt);
            });
          }
        } else {
          if (statusDot) {
            statusDot.style.color = '#ef4444'; // red
            statusDot.title = data.error || 'Connection failed';
          }
          btn.textContent = 'Failed';
        }
      } catch (e) {
        if (statusDot) {
          statusDot.style.color = '#ef4444';
          statusDot.title = 'Error: ' + e.message;
        }
        btn.textContent = 'Error';
      }

      setTimeout(() => {
        btn.disabled = false;
        btn.textContent = 'Test Connection';
      }, 3000);
    });
  });

  // ======================== RESET PROMPTS ========================
  document.querySelectorAll('.reset-prompt-btn').forEach(btn => {
    btn.addEventListener('click', async () => {
      const key = btn.dataset.key;
      if (!confirm(`Reset "${key}" prompt to its default template?`)) return;

      try {
        const resp = await fetch('/admin/ai/reset-prompt', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ prompt_key: key })
        });
        const data = await resp.json();
        if (data.success) {
          location.reload();
        } else {
          alert(data.error || 'Failed to reset prompt');
        }
      } catch (e) {
        alert('Error: ' + e.message);
      }
    });
  });

  // ======================== GENERATE SUMMARIES ========================
  const generateBtn = document.getElementById('generate-btn');
  if (generateBtn) {
    generateBtn.addEventListener('click', async () => {
      const showId = document.getElementById('generate-show-select').value;
      const seasonNum = document.getElementById('generate-season-input').value;

      if (!showId) {
        alert('Please select a show.');
        return;
      }

      generateBtn.disabled = true;
      generateBtn.textContent = 'Generating...';
      const outputDiv = document.getElementById('generate-output');
      const logPre = document.getElementById('generate-log');
      outputDiv.classList.remove('hidden');
      logPre.textContent = 'Starting summary generation...\n';

      try {
        const resp = await fetch('/admin/ai/generate', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ show_id: parseInt(showId), season_number: seasonNum ? parseInt(seasonNum) : null })
        });
        const data = await resp.json();

        if (data.success) {
          logPre.textContent += '\n' + (data.log || 'Generation complete.');
          logPre.textContent += `\n\nDone! Generated ${data.episode_count || 0} episode summaries and ${data.season_count || 0} season recaps.`;
        } else {
          logPre.textContent += '\nError: ' + (data.error || 'Unknown error');
        }
      } catch (e) {
        logPre.textContent += '\nError: ' + e.message;
      }

      generateBtn.disabled = false;
      generateBtn.textContent = 'Generate Summaries';
    });
  }

  // ======================== DELETE SUMMARIES ========================
  document.querySelectorAll('.delete-summaries-btn').forEach(btn => {
    btn.addEventListener('click', async () => {
      const showId = btn.dataset.showId;
      if (!confirm('Delete all AI summaries for this show?')) return;

      try {
        const resp = await fetch('/admin/ai/delete-summaries', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ show_id: parseInt(showId) })
        });
        const data = await resp.json();
        if (data.success) {
          location.reload();
        } else {
          alert(data.error || 'Failed to delete summaries');
        }
      } catch (e) {
        alert('Error: ' + e.message);
      }
    });
  });

  // ======================== REFRESH LOGS ========================
  const refreshLogsBtn = document.getElementById('refresh-logs-btn');
  if (refreshLogsBtn) {
    refreshLogsBtn.addEventListener('click', async () => {
      const provider = document.getElementById('log-provider-filter').value;
      try {
        const resp = await fetch(`/admin/ai/logs-data?provider=${encodeURIComponent(provider)}`);
        const data = await resp.json();
        const tbody = document.getElementById('logs-tbody');

        if (data.logs && data.logs.length > 0) {
          tbody.innerHTML = data.logs.map(log => `
            <tr>
              <td class="px-4 py-2 text-xs text-slate-600 dark:text-slate-400">${log.timestamp}</td>
              <td class="px-4 py-2 text-xs">
                <span class="px-2 py-0.5 rounded-full text-xs font-medium ${
                  log.provider === 'ollama' ? 'bg-green-100 text-green-700 dark:bg-green-900/30 dark:text-green-400' :
                  log.provider === 'openai' ? 'bg-blue-100 text-blue-700 dark:bg-blue-900/30 dark:text-blue-400' :
                  'bg-purple-100 text-purple-700 dark:bg-purple-900/30 dark:text-purple-400'
                }">${log.provider}</span>
              </td>
              <td class="px-4 py-2 text-xs text-slate-700 dark:text-slate-300 font-mono">${log.endpoint}</td>
              <td class="px-4 py-2 text-xs text-slate-600 dark:text-slate-400">${log.total_tokens || '--'}</td>
              <td class="px-4 py-2 text-xs text-slate-600 dark:text-slate-400">${log.cost_usd ? '$' + log.cost_usd.toFixed(5) : '--'}</td>
              <td class="px-4 py-2 text-xs text-slate-600 dark:text-slate-400">${log.processing_time_ms || '--'}</td>
            </tr>
          `).join('');
        } else {
          tbody.innerHTML = '<tr><td colspan="6" class="px-4 py-8 text-center text-sm text-slate-500">No API usage logged yet.</td></tr>';
        }
      } catch (e) {
        console.error('Failed to refresh logs:', e);
      }
    });
  }
});
