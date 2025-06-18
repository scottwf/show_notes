document.addEventListener('DOMContentLoaded', function () {
    const searchInput = document.getElementById('admin-search-input');
    const searchResultsDiv = document.getElementById('admin-search-results');
    const searchForm = document.getElementById('admin-search-form');
    let debounceTimer;
    let currentHighlightIndex = -1;
    const highlightClass = 'bg-gray-100 dark:bg-gray-700';

    if (!searchInput || !searchResultsDiv || !searchForm) {
        // console.warn('Admin search elements not found. Skipping admin search initialization.');
        return;
    }

    // Fetch and display results
    async function fetchAndDisplayResults(query) {
        if (!query) {
            searchResultsDiv.classList.add('hidden');
            searchResultsDiv.innerHTML = '';
            return;
        }
        try {
            const response = await fetch(`/admin/search?q=${encodeURIComponent(query)}`);
            if (!response.ok) {
                console.error('Admin search request failed with status:', response.status);
                searchResultsDiv.classList.add('hidden');
                searchResultsDiv.innerHTML = `<div class="px-4 py-2 text-sm text-red-500">Search request failed.</div>`;
                searchResultsDiv.classList.remove('hidden');
                return;
            }
            const data = await response.json();

            if (data.length > 0) {
                let html = '';
                data.forEach(item => {
                    const yearText = item.year ? ` (${item.year})` : '';
                    const itemTitle = item.title || 'Untitled';
                    const itemCategory = item.category || 'General';

                    html += `<a href="${item.url}" class="block px-4 py-3 text-sm hover:bg-gray-100 dark:hover:bg-gray-700 admin-search-item transition-colors duration-75">
                                 <div class="font-medium text-gray-800 dark:text-gray-100 truncate" title="${itemTitle}${yearText}">${itemTitle}${yearText}</div>
                                 <div class="text-xs text-gray-500 dark:text-gray-400">${itemCategory}</div>
                              </a>`;
                });
                searchResultsDiv.innerHTML = html;
                searchResultsDiv.classList.remove('hidden');
            } else {
                searchResultsDiv.innerHTML = '<div class="px-4 py-3 text-sm text-gray-500 dark:text-gray-400">No results found.</div>';
                searchResultsDiv.classList.remove('hidden');
            }
            currentHighlightIndex = -1; // Reset highlight
        } catch (error) {
            console.error('Error fetching admin search results:', error);
            searchResultsDiv.classList.add('hidden');
            searchResultsDiv.innerHTML = `<div class="px-4 py-2 text-sm text-red-500">Error fetching results.</div>`;
            searchResultsDiv.classList.remove('hidden');
        }
    }

    searchInput.addEventListener('input', function (e) {
        clearTimeout(debounceTimer);
        const query = e.target.value.trim();
        if (query.length > 1 || query.length === 0) { // Fetch if query length > 1 or if query is cleared (to hide results)
            debounceTimer = setTimeout(() => fetchAndDisplayResults(query), 300);
        } else { // Query is 1 char, too short, hide
            searchResultsDiv.classList.add('hidden');
            searchResultsDiv.innerHTML = '';
        }
    });

    // Hide results when clicking outside
    document.addEventListener('click', function (event) {
        if (searchForm && !searchForm.contains(event.target)) {
            searchResultsDiv.classList.add('hidden');
        }
    });

    // Show results on focus if there's text and results are hidden
    searchInput.addEventListener('focus', function() {
        if (searchInput.value.trim().length > 1 && searchResultsDiv.classList.contains('hidden') && searchResultsDiv.innerHTML.trim() !== '') {
            searchResultsDiv.classList.remove('hidden');
        }
    });


    function updateHighlight(items) {
        items.forEach((item, index) => {
            if (index === currentHighlightIndex) {
                item.classList.add(highlightClass);
                item.scrollIntoView({ block: 'nearest' });
            } else {
                item.classList.remove(highlightClass);
            }
        });
    }

    searchInput.addEventListener('keydown', function(e) {
        const items = searchResultsDiv.querySelectorAll('.admin-search-item');
        if (searchResultsDiv.classList.contains('hidden') || items.length === 0) return;

        if (e.key === 'ArrowDown') {
            e.preventDefault();
            currentHighlightIndex = (currentHighlightIndex + 1) % items.length;
            updateHighlight(items);
        } else if (e.key === 'ArrowUp') {
            e.preventDefault();
            currentHighlightIndex = (currentHighlightIndex - 1 + items.length) % items.length;
            updateHighlight(items);
        } else if (e.key === 'Enter') {
            e.preventDefault();
            if (currentHighlightIndex >= 0 && items[currentHighlightIndex]) {
                items[currentHighlightIndex].click(); // Navigate
                searchResultsDiv.classList.add('hidden'); // Hide after selection
            } else if (items.length > 0) {
                 // If no specific item is highlighted but there are results,
                 // potentially submit the form or navigate to the first result.
                 // For now, we require explicit selection or just let form submit (if not prevented).
            }
        } else if (e.key === 'Escape') {
            searchResultsDiv.classList.add('hidden');
            // searchInput.blur(); // Optional: remove focus
        }
    });

    // Prevent form submission if user hits Enter in input field without selecting
    if (searchForm) {
       searchForm.addEventListener('submit', function(event) {
           event.preventDefault();
           // Optionally, navigate to the first search result if one is available and highlighted
            const items = searchResultsDiv.querySelectorAll('.admin-search-item');
            if (currentHighlightIndex >= 0 && items[currentHighlightIndex]) {
                 items[currentHighlightIndex].click();
            } else if (items.length > 0 && searchInput.value.trim()) {
                // Or navigate to a dedicated search page if no item is selected
                // window.location.href = `/admin/search_page?q=${encodeURIComponent(searchInput.value.trim())}`;
            }
       });
    }

    // Global shortcut (Ctrl+K or Cmd+K) to focus search
    document.addEventListener('keydown', function(e) {
        if ((e.ctrlKey || e.metaKey) && e.key === 'k') {
            e.preventDefault();
            searchInput.focus();
        }
    });
});
