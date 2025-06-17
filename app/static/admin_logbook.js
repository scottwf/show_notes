// admin_logbook.js
// Handles dynamic loading and filtering of logbook events

document.addEventListener('DOMContentLoaded', function () {
    const categorySelect = document.getElementById('logbook-category');
    const userInput = document.getElementById('logbook-user');
    const showInput = document.getElementById('logbook-show');
    const logbookTableDiv = document.getElementById('logbook-table-div');
    const loadingDiv = document.getElementById('logbook-loading');

    function buildQueryParams() {
        const params = new URLSearchParams();
        if (categorySelect && categorySelect.value) params.append('category', categorySelect.value);
        if (userInput && userInput.value) params.append('user', userInput.value);
        if (showInput && showInput.value) params.append('show', showInput.value);
        return params.toString();
    }

    function fetchLogbookData() {
        if (loadingDiv) loadingDiv.style.display = 'block';
        fetch(`/admin/logbook/data?${buildQueryParams()}`)
            .then(response => response.json())
            .then(data => {
                renderLogbookTable(data);
                if (loadingDiv) loadingDiv.style.display = 'none';
            })
            .catch(err => {
                logbookTableDiv.innerHTML = '<div class="text-red-500">Error loading logbook data.</div>';
                if (loadingDiv) loadingDiv.style.display = 'none';
            });
    }

    function renderLogbookTable(data) {
        let html = '';
        if (data.sync_logs && data.sync_logs.length > 0) {
            html += `<h2 class="text-xl font-semibold mb-2">Service Sync Events</h2>`;
            html += `<div class="overflow-x-auto"><table class="min-w-full divide-y divide-gray-200 dark:divide-gray-600 bg-white dark:bg-gray-700 rounded-lg shadow">
                <thead><tr class="bg-gray-100 dark:bg-gray-600">
                    <th class="px-4 py-2">Service</th>
                    <th class="px-4 py-2">Status</th>
                    <th class="px-4 py-2">Last Attempt</th>
                </tr></thead><tbody>`;
            data.sync_logs.forEach(row => {
                html += `<tr class="hover:bg-gray-50 dark:hover:bg-gray-800">
                    <td class="px-4 py-2">${row.service_name}</td>
                    <td class="px-4 py-2">${row.status}</td>
                    <td class="px-4 py-2">${row.last_attempted_sync_at}</td>
                </tr>`;
            });
            html += '</tbody></table></div>';
        }
        if (data.plex_logs && data.plex_logs.length > 0) {
            html += `<h2 class="text-xl font-semibold mt-8 mb-2">Recent Plex Activity</h2>`;
            html += `<div class="overflow-x-auto"><table class="min-w-full divide-y divide-gray-200 dark:divide-gray-600 bg-white dark:bg-gray-700 rounded-lg shadow">
                <thead><tr class="bg-gray-100 dark:bg-gray-600">
                    <th class="px-4 py-2">User</th>
                    <th class="px-4 py-2">Event</th>
                    <th class="px-4 py-2">Title</th>
                    <th class="px-4 py-2">Time</th>
                </tr></thead><tbody>`;
            data.plex_logs.forEach(row => {
                let titleCell = row.episode_detail_url && row.display_title ?
                    `<a href="${row.episode_detail_url}" class="text-blue-600 dark:text-blue-300 hover:underline">${row.display_title}</a>` :
                    (row.display_title || '');
                html += `<tr class="hover:bg-gray-50 dark:hover:bg-gray-800">
                    <td class="px-4 py-2">${row.plex_username}</td>
                    <td class="px-4 py-2">${row.event_type_fmt || ''}</td>
                    <td class="px-4 py-2">${titleCell}</td>
                    <td class="px-4 py-2">${row.event_timestamp_fmt || row.event_timestamp}</td>
                </tr>`;
            });
            html += '</tbody></table></div>';
        }
        if (!html) {
            html = '<div class="text-gray-600 dark:text-gray-200">No logbook events found for this filter.</div>';
        }
        logbookTableDiv.innerHTML = html;
    }

    // Event listeners
    if (categorySelect) categorySelect.addEventListener('change', fetchLogbookData);
    if (userInput) userInput.addEventListener('input', fetchLogbookData);
    if (showInput) showInput.addEventListener('input', fetchLogbookData);

    // Initial load
    fetchLogbookData();
});
