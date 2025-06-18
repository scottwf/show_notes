// Search bar functionality
(function(){
  document.addEventListener('DOMContentLoaded', function(){
    const searchInput = document.getElementById('search-input');
    const searchResultsDiv = document.getElementById('search-results');
    const searchForm = document.getElementById('search-form'); // Parent form of input and results

    if(!searchInput || !searchResultsDiv || !searchForm) return;

    let controller;
    let currentHighlightIndex = -1;
    const keyboardSelectedClass = 'keyboard-selected';

    // Store original classes for desktop view to reapply them accurately
    const originalDesktopResultsClasses = ['absolute', 'mt-1', 'shadow-lg', 'max-h-72', 'left-0', 'right-0', 'bg-white', 'dark:bg-gray-800', 'text-gray-900', 'dark:text-gray-100', 'rounded-lg', 'z-50', 'overflow-y-auto'];
    // Tailwind sm breakpoint is 640px. Updated to md (768px) for better usability on tablets.
    const mobileBreakpoint = 768; // Tailwind 'md' breakpoint

    function updateHighlight() {
      const items = searchResultsDiv.children;
      for (let i = 0; i < items.length; i++) {
        items[i].classList.remove(keyboardSelectedClass);
      }
      if (currentHighlightIndex >= 0 && currentHighlightIndex < items.length) {
        const currentItem = items[currentHighlightIndex];
        currentItem.classList.add(keyboardSelectedClass);
        // scrollIntoView can be problematic with fixed position modal
        if (!searchResultsDiv.classList.contains('fixed')) {
            currentItem.scrollIntoView({ block: 'nearest' });
        }
      }
    }

    function applyMobileResultsStyle() {
        searchResultsDiv.classList.remove(...originalDesktopResultsClasses, 'hidden', 'sm:max-w-xl'); // Clear existing/desktop styles
        searchResultsDiv.classList.add('fixed', 'inset-x-0', 'top-16', 'bottom-0', 'bg-white', 'dark:bg-gray-900', 'overflow-y-auto', 'z-[100]', 'p-4');
        document.body.classList.add('overflow-hidden'); // Prevent body scroll
        searchResultsDiv.classList.remove('hidden'); // Ensure it's visible
    }

    function applyDesktopResultsStyle() {
        searchResultsDiv.classList.remove('hidden', 'fixed', 'inset-x-0', 'top-16', 'bottom-0', 'bg-white', 'dark:bg-gray-900', 'overflow-y-auto', 'z-[100]', 'p-4'); // Clear mobile modal styles
        searchResultsDiv.classList.add(...originalDesktopResultsClasses);
         // Add sm:max-w-xl or similar if it was part of original logic for sizing within parent
        // For now, relying on md:max-w-xl on searchForm's parent and w-full on input
        document.body.classList.remove('overflow-hidden');
        searchResultsDiv.classList.remove('hidden'); // Ensure it's visible
    }

    function hideResults() {
        searchResultsDiv.classList.add('hidden');
        searchResultsDiv.classList.remove('fixed', 'inset-x-0', 'top-16', 'bottom-0', 'overflow-y-auto', 'z-[100]', 'p-4'); // Clean mobile styles
        searchResultsDiv.classList.add(...originalDesktopResultsClasses); // Restore desktop classes in case of resize then hide
        document.body.classList.remove('overflow-hidden'); // Ensure body scroll is restored
        currentHighlightIndex = -1;
        updateHighlight();
    }

    async function fetchAndDisplayResults(query) {
        currentHighlightIndex = -1;
        if(controller){ controller.abort(); }
        if(!query){
            hideResults();
            searchResultsDiv.innerHTML='';
            return;
        }

        controller = new AbortController();
        try{
            const resp = await fetch('/search?q=' + encodeURIComponent(query), {signal: controller.signal});
            if(!resp.ok) throw new Error('search failed');
            const data = await resp.json();

            if (data.length > 0) {
                let html = '';
                data.forEach(item => {
                    let itemTitle = item.title;
                    if (item.year) {
                        itemTitle += ` (${item.year})`;
                    }
                    const itemType = item.type ? `<span class="text-xs text-gray-500 dark:text-gray-400 ml-1">${item.type}</span>` : '';

                    // Image for search result
                    // item.poster_url from the backend IS the correct full path to the static asset (actual image or placeholder)
                    const posterSrc = item.poster_url;
                    const onErrorScript = "this.onerror=null; this.src='/static/logos/placeholder_poster.png';"; // Hardcoded path to the known placeholder
                    const imageHtml = `<img src="${posterSrc}" alt="Poster for ${itemTitle}" class="w-10 h-15 object-cover rounded-sm mr-3 flex-shrink-0" onerror="${onErrorScript}">`;

                    const textHtml = `
                        <div class="flex-grow overflow-hidden">
                            <div class="font-medium text-gray-800 dark:text-gray-100 truncate" title="${itemTitle}">${itemTitle}</div>
                            <div class="text-xs text-gray-600 dark:text-gray-400">${item.year ? '('+item.year+')' : ''} ${itemType}</div>
                        </div>
                    `;

                    const innerFlexContainer = `<div class="flex items-center p-2 cursor-pointer">${imageHtml}${textHtml}</div>`;
                    let itemHtmlEntry = '';

                    if ((item.type === 'movie' || item.type === 'show') && item.tmdb_id) {
                        const link = item.type === 'movie' ? `/movie/${item.tmdb_id}` : `/show/${item.tmdb_id}`;
                        itemHtmlEntry = `<a href="${link}" class="block hover:bg-gray-200 dark:hover:bg-gray-700 search-result-item">${innerFlexContainer}</a>`;
                    } else {
                        // Fallback for items without a direct link (though tmdb_id is usually present for shows/movies)
                        itemHtmlEntry = `<div class="search-result-item">${innerFlexContainer}</div>`;
                    }
                    html += itemHtmlEntry;
                });
                searchResultsDiv.innerHTML = html;

                if (window.innerWidth < mobileBreakpoint) {
                    applyMobileResultsStyle();
                } else {
                    applyDesktopResultsStyle();
                }
            } else {
                // Show "No results found" message
                searchResultsDiv.innerHTML = '<div class="px-4 py-2 text-gray-500 dark:text-gray-400">No results found.</div>';
                if (window.innerWidth < mobileBreakpoint) {
                    applyMobileResultsStyle(); // Show it in mobile style
                } else {
                    applyDesktopResultsStyle(); // Show it in desktop style
                }
                // Do not call hideResults() here if we want to show "No results"
            }
            updateHighlight();
        }catch(e){
            if(e.name!=='AbortError') {
                console.error(e);
                // Optionally show an error message in the results div
                // searchResultsDiv.innerHTML = '<div class="px-4 py-2 text-red-500">Search failed. Please try again.</div>';
                // if (window.innerWidth < mobileBreakpoint) applyMobileResultsStyle(); else applyDesktopResultsStyle();
                hideResults(); // Or just hide on error
            }
        }
    }

    let debounceTimer;
    searchInput.addEventListener('input', function(e) {
        clearTimeout(debounceTimer);
        const query = e.target.value.trim();
        if (query) {
            debounceTimer = setTimeout(() => {
                fetchAndDisplayResults(query);
            }, 300);
        } else {
            hideResults();
            searchResultsDiv.innerHTML = ''; // Clear results when query is cleared
        }
    });

    // Prevent form submission if javascript is enabled, as search is live
    searchForm.addEventListener('submit', function(event) {
        event.preventDefault();
    });

    searchInput.addEventListener('keydown', function(event) {
      const items = searchResultsDiv.children;
      if (searchResultsDiv.classList.contains('hidden') || items.length === 0) {
        currentHighlightIndex = -1;
        return;
      }

      if (event.key === 'ArrowDown') {
        event.preventDefault();
        currentHighlightIndex++;
        if (currentHighlightIndex >= items.length) currentHighlightIndex = 0;
        updateHighlight();
      } else if (event.key === 'ArrowUp') {
        event.preventDefault();
        currentHighlightIndex--;
        if (currentHighlightIndex < 0) currentHighlightIndex = items.length - 1;
        updateHighlight();
      } else if (event.key === 'Enter') {
        event.preventDefault();
        if (currentHighlightIndex >= 0 && currentHighlightIndex < items.length) {
          const selectedItem = items[currentHighlightIndex];
          if (selectedItem && typeof selectedItem.click === 'function') {
            selectedItem.click(); // This will trigger navigation for <a> tags
          } else if (selectedItem && selectedItem.href) {
             window.location.href = selectedItem.href;
          }
        }
        // hideResults() will be called by the click listener on searchResultsDiv or global click listener
      } else if (event.key === 'Escape') {
        event.preventDefault(); // Prevent other escape key actions like clearing input
        hideResults();
        searchInput.blur(); // Optional: remove focus from input
      }
    });

    // Handle clicks on search result items
    searchResultsDiv.addEventListener('click', function(event) {
        let targetElement = event.target;
        while (targetElement != null && !targetElement.classList.contains('search-result-item')) {
            targetElement = targetElement.parentElement;
        }
        if (targetElement && targetElement.classList.contains('search-result-item')) {
            // If it's an A tag, navigation is handled by href. If it's a DIV, it does nothing.
            // We always hide results after a click on an item.
            hideResults();
            // searchInput.value = ''; // Optional: clear search input on selection
        }
    });

    // Global click listener to hide results when clicking outside search form (input + results)
    document.addEventListener('click', function(event) {
        if (!searchForm.contains(event.target)) {
            hideResults();
        }
    });

    // Adjust styles on window resize
    window.addEventListener('resize', function() {
        // Only restyle if results are currently visible and there's a query
        if (!searchResultsDiv.classList.contains('hidden') && searchInput.value.trim()) {
            // If there's content (actual results or "no results" message)
            if (searchResultsDiv.innerHTML.trim() !== '') {
                 if (window.innerWidth < mobileBreakpoint) {
                    applyMobileResultsStyle();
                } else {
                    applyDesktopResultsStyle();
                }
            } else {
                // If there's no content (e.g. query was cleared, then resize)
                hideResults();
            }
        }
    });

    // Optional: Mouse hover interaction for keyboard selection consistency
    searchResultsDiv.addEventListener('mouseover', function(e) {
        const items = Array.from(searchResultsDiv.children);
        let targetItem = e.target;
        while(targetItem && targetItem.parentNode !== searchResultsDiv) {
            targetItem = targetItem.parentNode;
        }
        if (targetItem && items.includes(targetItem)) {
            const oldHighlightIndex = currentHighlightIndex;
            currentHighlightIndex = items.indexOf(targetItem);
            if (oldHighlightIndex !== currentHighlightIndex) {
                 updateHighlight();
            }
        }
    });

  });
})();
