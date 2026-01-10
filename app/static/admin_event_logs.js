// admin_event_logs.js
// Handles dynamic loading and filtering of system event logs

let currentPage = 1;
let totalPages = 1;
let userTimezone = 'UTC';
let currentFilters = {
    level: '',
    component: '',
    search: ''
};

async function loadLogs() {
    const desktopTbody = document.getElementById('logs-tbody-desktop');
    const mobileContainer = document.getElementById('logs-mobile');
    const loadingIndicator = createLoadingIndicator();

    // Show loading
    if (desktopTbody) {
        desktopTbody.innerHTML = '';
        desktopTbody.appendChild(loadingIndicator.desktop);
    }
    if (mobileContainer) {
        mobileContainer.innerHTML = '';
        mobileContainer.appendChild(loadingIndicator.mobile);
    }

    try {
        const params = new URLSearchParams({
            page: currentPage,
            per_page: 50
        });

        if (currentFilters.level) params.append('level', currentFilters.level);
        if (currentFilters.component) params.append('component', currentFilters.component);
        if (currentFilters.search) params.append('search', currentFilters.search);

        const response = await fetch(`/admin/api/event-logs?${params}`);
        const data = await response.json();

        if (!data.success) {
            throw new Error(data.error || 'Failed to load logs');
        }

        // Store timezone from response
        if (data.timezone) {
            userTimezone = data.timezone;
        }

        if (desktopTbody) desktopTbody.innerHTML = '';
        if (mobileContainer) mobileContainer.innerHTML = '';

        if (data.logs.length === 0) {
            const noDataMessage = createNoDataMessage();
            if (desktopTbody) desktopTbody.appendChild(noDataMessage.desktop);
            if (mobileContainer) mobileContainer.appendChild(noDataMessage.mobile);
            return;
        }

        data.logs.forEach(log => {
            if (desktopTbody) {
                const row = createDesktopLogRow(log);
                desktopTbody.appendChild(row);
            }
            if (mobileContainer) {
                const card = createMobileLogCard(log);
                mobileContainer.appendChild(card);
            }
        });

        // Update pagination
        totalPages = data.total_pages;
        updatePagination(data.total, data.page, data.per_page);

    } catch (error) {
        console.error('Error loading logs:', error);
        const errorMessage = createErrorMessage(error.message);
        if (desktopTbody) desktopTbody.innerHTML = '';
        if (mobileContainer) mobileContainer.innerHTML = '';
        if (desktopTbody) desktopTbody.appendChild(errorMessage.desktop);
        if (mobileContainer) mobileContainer.appendChild(errorMessage.mobile);
    }
}

function createLoadingIndicator() {
    const spinner = '<svg class="animate-spin h-5 w-5 mr-3" fill="none" viewBox="0 0 24 24"><circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle><path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path></svg>';

    const desktopRow = document.createElement('tr');
    desktopRow.innerHTML = `
        <td colspan="4" class="px-6 py-4 text-center text-gray-500 dark:text-gray-400">
            <div class="flex items-center justify-center">
                ${spinner}
                Loading logs...
            </div>
        </td>
    `;

    const mobileDiv = document.createElement('div');
    mobileDiv.className = 'bg-white dark:bg-slate-800 shadow rounded-lg border border-slate-200 dark:border-slate-700 p-6 text-center';
    mobileDiv.innerHTML = `
        <div class="flex items-center justify-center text-gray-500 dark:text-gray-400">
            ${spinner}
            Loading logs...
        </div>
    `;

    return { desktop: desktopRow, mobile: mobileDiv };
}

function createNoDataMessage() {
    const desktopRow = document.createElement('tr');
    desktopRow.innerHTML = '<td colspan="4" class="px-6 py-4 text-center text-gray-500 dark:text-gray-400">No logs found</td>';

    const mobileDiv = document.createElement('div');
    mobileDiv.className = 'bg-white dark:bg-slate-800 shadow rounded-lg border border-slate-200 dark:border-slate-700 p-6 text-center';
    mobileDiv.innerHTML = '<p class="text-gray-500 dark:text-gray-400">No logs found</p>';

    return { desktop: desktopRow, mobile: mobileDiv };
}

function createErrorMessage(message) {
    const desktopRow = document.createElement('tr');
    desktopRow.innerHTML = `<td colspan="4" class="px-6 py-4 text-center text-red-500">Error loading logs: ${escapeHtml(message)}</td>`;

    const mobileDiv = document.createElement('div');
    mobileDiv.className = 'bg-white dark:bg-slate-800 shadow rounded-lg border border-slate-200 dark:border-slate-700 p-6 text-center';
    mobileDiv.innerHTML = `<p class="text-red-500">Error loading logs: ${escapeHtml(message)}</p>`;

    return { desktop: desktopRow, mobile: mobileDiv };
}

function formatTimestamp(timestamp) {
    try {
        let dateStr = timestamp;
        if (typeof timestamp === 'string' && !timestamp.includes('Z') && !timestamp.includes('+')) {
            dateStr = timestamp.replace(' ', 'T') + 'Z';
        }

        const date = new Date(dateStr);
        return date.toLocaleString('en-US', {
            timeZone: userTimezone,
            year: 'numeric',
            month: '2-digit',
            day: '2-digit',
            hour: '2-digit',
            minute: '2-digit',
            second: '2-digit',
            hour12: false
        });
    } catch (e) {
        return new Date(timestamp).toLocaleString();
    }
}

function getLevelBadgeClasses(level) {
    const levelColors = {
        info: 'bg-blue-100 text-blue-800 dark:bg-blue-900/30 dark:text-blue-300',
        success: 'bg-green-100 text-green-800 dark:bg-green-900/30 dark:text-green-300',
        warning: 'bg-yellow-100 text-yellow-800 dark:bg-yellow-900/30 dark:text-yellow-300',
        error: 'bg-red-100 text-red-800 dark:bg-red-900/30 dark:text-red-300',
        debug: 'bg-gray-100 text-gray-800 dark:bg-gray-900/30 dark:text-gray-300'
    };
    return levelColors[level] || levelColors.info;
}

function createDesktopLogRow(log) {
    const row = document.createElement('tr');
    row.className = 'hover:bg-slate-50 dark:hover:bg-slate-700 cursor-pointer transition-colors';
    row.onclick = () => showLogDetails(log.id);

    const timeStr = formatTimestamp(log.timestamp);
    const badgeClasses = getLevelBadgeClasses(log.level);

    row.innerHTML = `
        <td class="px-6 py-4 whitespace-nowrap text-sm text-gray-900 dark:text-gray-100">
            ${timeStr}
        </td>
        <td class="px-6 py-4 whitespace-nowrap">
            <span class="px-2 inline-flex text-xs leading-5 font-semibold rounded-full ${badgeClasses}">
                ${escapeHtml(log.level.toUpperCase())}
            </span>
        </td>
        <td class="px-6 py-4 whitespace-nowrap text-sm font-medium text-gray-900 dark:text-gray-100">
            ${escapeHtml(log.component)}
        </td>
        <td class="px-6 py-4 text-sm text-gray-700 dark:text-gray-300">
            <div class="line-clamp-2">${escapeHtml(log.message)}</div>
        </td>
    `;

    return row;
}

function createMobileLogCard(log) {
    const card = document.createElement('div');
    card.className = 'bg-white dark:bg-slate-800 shadow rounded-lg border border-slate-200 dark:border-slate-700 p-4 cursor-pointer hover:shadow-md transition-shadow';
    card.onclick = () => showLogDetails(log.id);

    const timeStr = formatTimestamp(log.timestamp);
    const badgeClasses = getLevelBadgeClasses(log.level);

    card.innerHTML = `
        <div class="flex items-start justify-between gap-3 mb-3">
            <span class="px-2 inline-flex text-xs leading-5 font-semibold rounded-full ${badgeClasses}">
                ${escapeHtml(log.level.toUpperCase())}
            </span>
            <span class="text-xs text-gray-600 dark:text-gray-400">${timeStr}</span>
        </div>
        <div class="mb-2">
            <span class="inline-flex items-center px-2.5 py-0.5 rounded text-xs font-medium bg-slate-100 dark:bg-slate-700 text-slate-800 dark:text-slate-200">
                ${escapeHtml(log.component)}
            </span>
        </div>
        <p class="text-sm text-gray-900 dark:text-gray-100 line-clamp-3">${escapeHtml(log.message)}</p>
    `;

    return card;
}

async function showLogDetails(logId) {
    const modal = document.getElementById('log-modal');
    const modalContent = document.getElementById('modal-content');

    modalContent.innerHTML = '<p class="text-gray-500 dark:text-gray-400">Loading...</p>';
    modal.classList.remove('hidden');

    try {
        const response = await fetch(`/admin/api/event-logs/${logId}`);
        const data = await response.json();

        if (!data.success) {
            throw new Error(data.error || 'Failed to load log details');
        }

        const log = data.log;

        let detailsHTML = '';
        if (log.details) {
            try {
                const details = JSON.parse(log.details);
                detailsHTML = '<pre class="bg-slate-50 dark:bg-slate-900 p-4 rounded-md overflow-x-auto text-sm">' +
                    escapeHtml(JSON.stringify(details, null, 2)) + '</pre>';
            } catch (e) {
                detailsHTML = '<p class="text-sm text-gray-700 dark:text-gray-300">' + escapeHtml(log.details) + '</p>';
            }
        }

        modalContent.innerHTML = `
            <div class="space-y-3">
                <div>
                    <label class="text-sm font-semibold text-gray-700 dark:text-gray-300">Time:</label>
                    <p class="text-sm text-gray-900 dark:text-gray-100">${formatTimestamp(log.timestamp)}</p>
                </div>
                <div>
                    <label class="text-sm font-semibold text-gray-700 dark:text-gray-300">Level:</label>
                    <p class="text-sm text-gray-900 dark:text-gray-100">${escapeHtml(log.level.toUpperCase())}</p>
                </div>
                <div>
                    <label class="text-sm font-semibold text-gray-700 dark:text-gray-300">Component:</label>
                    <p class="text-sm text-gray-900 dark:text-gray-100">${escapeHtml(log.component)}</p>
                </div>
                <div>
                    <label class="text-sm font-semibold text-gray-700 dark:text-gray-300">Message:</label>
                    <p class="text-sm text-gray-900 dark:text-gray-100">${escapeHtml(log.message)}</p>
                </div>
                ${log.details ? '<div><label class="text-sm font-semibold text-gray-700 dark:text-gray-300">Details:</label>' + detailsHTML + '</div>' : ''}
                ${log.user_id ? '<div><label class="text-sm font-semibold text-gray-700 dark:text-gray-300">User ID:</label><p class="text-sm text-gray-900 dark:text-gray-100">' + escapeHtml(log.user_id) + '</p></div>' : ''}
                ${log.ip_address ? '<div><label class="text-sm font-semibold text-gray-700 dark:text-gray-300">IP Address:</label><p class="text-sm text-gray-900 dark:text-gray-100">' + escapeHtml(log.ip_address) + '</p></div>' : ''}
            </div>
        `;

    } catch (error) {
        console.error('Error loading log details:', error);
        modalContent.innerHTML = '<p class="text-red-500">Error loading log details: ' + escapeHtml(error.message) + '</p>';
    }
}

function closeModal() {
    document.getElementById('log-modal').classList.add('hidden');
}

function updatePagination(total, page, perPage) {
    const start = ((page - 1) * perPage) + 1;
    const end = Math.min(page * perPage, total);

    document.getElementById('pagination-info').textContent =
        `Showing ${start}-${end} of ${total} events`;

    document.getElementById('prev-page').disabled = page <= 1;
    document.getElementById('next-page').disabled = page >= totalPages;
}

function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

// Event listeners
document.addEventListener('DOMContentLoaded', () => {
    document.getElementById('level-filter').addEventListener('change', (e) => {
        currentFilters.level = e.target.value;
        currentPage = 1;
        loadLogs();
    });

    document.getElementById('component-filter').addEventListener('change', (e) => {
        currentFilters.component = e.target.value;
        currentPage = 1;
        loadLogs();
    });

    let searchTimeout;
    document.getElementById('search-filter').addEventListener('input', (e) => {
        clearTimeout(searchTimeout);
        searchTimeout = setTimeout(() => {
            currentFilters.search = e.target.value;
            currentPage = 1;
            loadLogs();
        }, 500);
    });

    document.getElementById('refresh-btn').addEventListener('click', () => {
        loadLogs();
    });

    document.getElementById('prev-page').addEventListener('click', () => {
        if (currentPage > 1) {
            currentPage--;
            loadLogs();
        }
    });

    document.getElementById('next-page').addEventListener('click', () => {
        if (currentPage < totalPages) {
            currentPage++;
            loadLogs();
        }
    });

    // Initial load
    loadLogs();

    // Auto-refresh every 30 seconds
    setInterval(loadLogs, 30000);
});
