// admin_logbook.js
// Handles dynamic loading and filtering of playback activity

document.addEventListener('DOMContentLoaded', function () {
    const userSelect = document.getElementById('logbook-user');
    const showInput = document.getElementById('logbook-show');
    const mediaTypeSelect = document.getElementById('logbook-media-type');
    const daysSelect = document.getElementById('logbook-days');
    const logbookTableDiv = document.getElementById('logbook-table-div');
    const loadingDiv = document.getElementById('logbook-loading');

    // Load user list for dropdown
    function loadUsers() {
        fetch('/admin/logbook/users')
            .then(response => response.json())
            .then(data => {
                if (data.users && data.users.length > 0) {
                    data.users.forEach(username => {
                        const option = document.createElement('option');
                        option.value = username;
                        option.textContent = username;
                        userSelect.appendChild(option);
                    });
                }
            })
            .catch(err => {
                console.error('Error loading users:', err);
            });
    }

    function buildQueryParams() {
        const params = new URLSearchParams();
        params.append('category', 'plex'); // Only fetch Plex events
        if (userSelect && userSelect.value) params.append('user', userSelect.value);
        if (showInput && showInput.value) params.append('show', showInput.value);
        if (mediaTypeSelect && mediaTypeSelect.value) params.append('media_type', mediaTypeSelect.value);
        if (daysSelect && daysSelect.value) params.append('days', daysSelect.value);
        return params.toString();
    }

    function getEventIcon(eventType) {
        const icons = {
            'Play': `<svg class="w-5 h-5 text-green-500" fill="currentColor" viewBox="0 0 20 20"><path d="M6.3 2.841A1.5 1.5 0 004 4.11V15.89a1.5 1.5 0 002.3 1.269l9.344-5.89a1.5 1.5 0 000-2.538L6.3 2.84z"/></svg>`,
            'Pause': `<svg class="w-5 h-5 text-yellow-500" fill="currentColor" viewBox="0 0 20 20"><path d="M5.75 3a.75.75 0 00-.75.75v12.5c0 .414.336.75.75.75h1.5a.75.75 0 00.75-.75V3.75A.75.75 0 007.25 3h-1.5zM12.75 3a.75.75 0 00-.75.75v12.5c0 .414.336.75.75.75h1.5a.75.75 0 00.75-.75V3.75a.75.75 0 00-.75-.75h-1.5z"/></svg>`,
            'Resume': `<svg class="w-5 h-5 text-blue-500" fill="currentColor" viewBox="0 0 20 20"><path d="M6.3 2.841A1.5 1.5 0 004 4.11V15.89a1.5 1.5 0 002.3 1.269l9.344-5.89a1.5 1.5 0 000-2.538L6.3 2.84z"/></svg>`,
            'Stop': `<svg class="w-5 h-5 text-red-500" fill="currentColor" viewBox="0 0 20 20"><path d="M5.25 3A2.25 2.25 0 003 5.25v9.5A2.25 2.25 0 005.25 17h9.5A2.25 2.25 0 0017 14.75v-9.5A2.25 2.25 0 0014.75 3h-9.5z"/></svg>`,
            'Scrobble': `<svg class="w-5 h-5 text-purple-500" fill="currentColor" viewBox="0 0 20 20"><path fill-rule="evenodd" d="M10 18a8 8 0 100-16 8 8 0 000 16zm3.857-9.809a.75.75 0 00-1.214-.882l-3.483 4.79-1.88-1.88a.75.75 0 10-1.06 1.061l2.5 2.5a.75.75 0 001.137-.089l4-5.5z" clip-rule="evenodd"/></svg>`
        };
        return icons[eventType] || icons['Play'];
    }

    function escapeHtml(text) {
        const div = document.createElement('div');
        div.textContent = text;
        return div.innerHTML;
    }

    function fetchLogbookData() {
        if (loadingDiv) loadingDiv.classList.remove('hidden');
        fetch(`/admin/logbook/data?${buildQueryParams()}`)
            .then(response => response.json())
            .then(data => {
                renderLogbookTable(data);
                if (loadingDiv) loadingDiv.classList.add('hidden');
            })
            .catch(err => {
                logbookTableDiv.innerHTML = '<div class="bg-red-50 dark:bg-red-900/20 border border-red-200 dark:border-red-800 text-red-700 dark:text-red-300 px-4 py-3 rounded">Error loading playback activity.</div>';
                if (loadingDiv) loadingDiv.classList.add('hidden');
            });
    }

    function renderLogbookTable(data) {
        if (!data.plex_logs || data.plex_logs.length === 0) {
            logbookTableDiv.innerHTML = `
                <div class="bg-white dark:bg-slate-800 shadow-lg rounded-lg border border-slate-200 dark:border-slate-700 p-8 text-center">
                    <svg class="mx-auto h-12 w-12 text-slate-400" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M20 13V6a2 2 0 00-2-2H6a2 2 0 00-2 2v7m16 0v5a2 2 0 01-2 2H6a2 2 0 01-2-2v-5m16 0h-2.586a1 1 0 00-.707.293l-2.414 2.414a1 1 0 01-.707.293h-3.172a1 1 0 01-.707-.293l-2.414-2.414A1 1 0 006.586 13H4"/>
                    </svg>
                    <p class="mt-4 text-slate-600 dark:text-slate-400">No playback activity found</p>
                </div>
            `;
            return;
        }

        // Desktop table view (hidden on mobile)
        let tableHtml = `
            <div class="hidden md:block bg-white dark:bg-slate-800 shadow-lg rounded-lg border border-slate-200 dark:border-slate-700 overflow-hidden">
                <table class="min-w-full divide-y divide-slate-200 dark:divide-slate-700">
                    <thead class="bg-slate-50 dark:bg-slate-900">
                        <tr>
                            <th scope="col" class="px-6 py-3 text-left text-xs font-medium text-slate-500 dark:text-slate-400 uppercase tracking-wider">User</th>
                            <th scope="col" class="px-6 py-3 text-left text-xs font-medium text-slate-500 dark:text-slate-400 uppercase tracking-wider">Event</th>
                            <th scope="col" class="px-6 py-3 text-left text-xs font-medium text-slate-500 dark:text-slate-400 uppercase tracking-wider">Title</th>
                            <th scope="col" class="px-6 py-3 text-left text-xs font-medium text-slate-500 dark:text-slate-400 uppercase tracking-wider">Time</th>
                        </tr>
                    </thead>
                    <tbody class="bg-white dark:bg-slate-800 divide-y divide-slate-200 dark:divide-slate-700">
        `;

        data.plex_logs.forEach(row => {
            const eventIcon = getEventIcon(row.event_type_fmt);

            // Build title with clickable links
            let titleHtml = '';
            if (row.show_title && row.title) {
                // TV Show - make show title and episode title separately clickable
                const showLink = row.show_detail_url ?
                    `<a href="${row.show_detail_url}" class="text-sky-600 dark:text-sky-400 hover:text-sky-700 dark:hover:text-sky-300 hover:underline">${escapeHtml(row.show_title)}</a>` :
                    escapeHtml(row.show_title);

                const episodeLink = row.episode_detail_url ?
                    `<a href="${row.episode_detail_url}" class="text-sky-600 dark:text-sky-400 hover:text-sky-700 dark:hover:text-sky-300 hover:underline">${escapeHtml(row.title)}</a>` :
                    escapeHtml(row.title);

                titleHtml = `${showLink} – ${episodeLink}`;
            } else if (row.episode_detail_url || row.show_detail_url) {
                // Single link
                const url = row.episode_detail_url || row.show_detail_url;
                titleHtml = `<a href="${url}" class="text-sky-600 dark:text-sky-400 hover:text-sky-700 dark:hover:text-sky-300 hover:underline">${escapeHtml(row.display_title)}</a>`;
            } else {
                // No link available
                titleHtml = escapeHtml(row.display_title || '');
            }

            tableHtml += `
                <tr class="hover:bg-slate-50 dark:hover:bg-slate-700/50 transition-colors">
                    <td class="px-6 py-4 whitespace-nowrap text-sm text-slate-900 dark:text-slate-100">${escapeHtml(row.plex_username)}</td>
                    <td class="px-6 py-4 whitespace-nowrap">
                        <div class="flex items-center gap-2" title="${row.event_type_fmt}">
                            ${eventIcon}
                        </div>
                    </td>
                    <td class="px-6 py-4 text-sm text-slate-900 dark:text-slate-100">${titleHtml}</td>
                    <td class="px-6 py-4 whitespace-nowrap text-sm text-slate-600 dark:text-slate-400">${row.event_timestamp_fmt || row.event_timestamp}</td>
                </tr>
            `;
        });

        tableHtml += `
                    </tbody>
                </table>
            </div>
        `;

        // Mobile card view (hidden on desktop)
        let cardsHtml = `<div class="md:hidden space-y-3">`;

        data.plex_logs.forEach(row => {
            const eventIcon = getEventIcon(row.event_type_fmt);

            // Build title with clickable links (same logic as desktop)
            let titleHtml = '';
            if (row.show_title && row.title) {
                // TV Show - make show title and episode title separately clickable
                const showLink = row.show_detail_url ?
                    `<a href="${row.show_detail_url}" class="text-sky-600 dark:text-sky-400 hover:text-sky-700 dark:hover:text-sky-300 hover:underline font-medium">${escapeHtml(row.show_title)}</a>` :
                    `<span class="font-medium text-slate-900 dark:text-slate-100">${escapeHtml(row.show_title)}</span>`;

                const episodeLink = row.episode_detail_url ?
                    `<a href="${row.episode_detail_url}" class="text-sky-600 dark:text-sky-400 hover:text-sky-700 dark:hover:text-sky-300 hover:underline font-medium">${escapeHtml(row.title)}</a>` :
                    `<span class="font-medium text-slate-900 dark:text-slate-100">${escapeHtml(row.title)}</span>`;

                titleHtml = `${showLink} – ${episodeLink}`;
            } else if (row.episode_detail_url || row.show_detail_url) {
                // Single link
                const url = row.episode_detail_url || row.show_detail_url;
                titleHtml = `<a href="${url}" class="text-sky-600 dark:text-sky-400 hover:text-sky-700 dark:hover:text-sky-300 hover:underline font-medium">${escapeHtml(row.display_title)}</a>`;
            } else {
                // No link available
                titleHtml = `<span class="font-medium text-slate-900 dark:text-slate-100">${escapeHtml(row.display_title || '')}</span>`;
            }

            cardsHtml += `
                <div class="bg-white dark:bg-slate-800 shadow rounded-lg border border-slate-200 dark:border-slate-700 p-4">
                    <div class="flex items-start justify-between gap-3">
                        <div class="flex items-start gap-3 flex-1 min-w-0">
                            <div class="mt-0.5" title="${row.event_type_fmt}">
                                ${eventIcon}
                            </div>
                            <div class="flex-1 min-w-0">
                                <div class="text-sm mb-1">${titleHtml}</div>
                                <div class="flex items-center gap-3 text-xs text-slate-600 dark:text-slate-400">
                                    <span>${escapeHtml(row.plex_username)}</span>
                                    <span>•</span>
                                    <span>${row.event_timestamp_fmt || row.event_timestamp}</span>
                                </div>
                            </div>
                        </div>
                    </div>
                </div>
            `;
        });

        cardsHtml += `</div>`;

        logbookTableDiv.innerHTML = tableHtml + cardsHtml;
    }

    // Event listeners with debounce
    let debounceTimer;
    function debounce(func, delay = 300) {
        clearTimeout(debounceTimer);
        debounceTimer = setTimeout(func, delay);
    }

    if (userSelect) {
        userSelect.addEventListener('change', fetchLogbookData);
    }
    if (showInput) {
        showInput.addEventListener('input', () => debounce(fetchLogbookData));
    }
    if (mediaTypeSelect) {
        mediaTypeSelect.addEventListener('change', fetchLogbookData);
    }
    if (daysSelect) {
        daysSelect.addEventListener('change', fetchLogbookData);
    }

    // Initial loads
    loadUsers();
    fetchLogbookData();
});
