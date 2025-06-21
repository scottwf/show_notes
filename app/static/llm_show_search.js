// LLM Test Page Show Autocomplete
(function(){
  document.addEventListener('DOMContentLoaded', function(){
    const searchInput = document.getElementById('search-input');
    const searchResultsDiv = document.getElementById('search-results');
    const searchForm = document.getElementById('search-form');
    if(!searchInput || !searchResultsDiv || !searchForm) return;

    let controller;
    let currentHighlightIndex = -1;
    const keyboardSelectedClass = 'keyboard-selected';
    const originalDesktopResultsClasses = ['absolute', 'mt-1', 'shadow-lg', 'max-h-72', 'left-0', 'right-0', 'bg-white', 'dark:bg-gray-800', 'text-gray-900', 'dark:text-gray-100', 'rounded-lg', 'z-50', 'overflow-y-auto'];
    const mobileBreakpoint = 768;

    function updateHighlight() {
      const items = searchResultsDiv.children;
      for (let i = 0; i < items.length; i++) {
        items[i].classList.remove(keyboardSelectedClass);
      }
      if (currentHighlightIndex >= 0 && currentHighlightIndex < items.length) {
        const currentItem = items[currentHighlightIndex];
        currentItem.classList.add(keyboardSelectedClass);
        if (!searchResultsDiv.classList.contains('fixed')) {
            currentItem.scrollIntoView({ block: 'nearest' });
        }
      }
    }
    function applyMobileResultsStyle() {
        searchResultsDiv.classList.remove(...originalDesktopResultsClasses, 'hidden', 'sm:max-w-xl');
        searchResultsDiv.classList.add('fixed', 'inset-x-0', 'top-16', 'bottom-0', 'bg-white', 'dark:bg-gray-900', 'overflow-y-auto', 'z-[100]', 'p-4');
        document.body.classList.add('overflow-hidden');
        searchResultsDiv.classList.remove('hidden');
    }
    function applyDesktopResultsStyle() {
        searchResultsDiv.classList.remove('hidden', 'fixed', 'inset-x-0', 'top-16', 'bottom-0', 'bg-white', 'dark:bg-gray-900', 'overflow-y-auto', 'z-[100]', 'p-4');
        searchResultsDiv.classList.add(...originalDesktopResultsClasses);
        document.body.classList.remove('overflow-hidden');
        searchResultsDiv.classList.remove('hidden');
    }
    function hideResults() {
        searchResultsDiv.classList.add('hidden');
        searchResultsDiv.classList.remove('fixed', 'inset-x-0', 'top-16', 'bottom-0', 'overflow-y-auto', 'z-[100]', 'p-4');
        searchResultsDiv.classList.add(...originalDesktopResultsClasses);
        document.body.classList.remove('overflow-hidden');
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
            const filteredData = data.filter(item => item.type === 'show');
            if (filteredData.length > 0) {
                let html = '';
                filteredData.forEach(item => {
                    let itemTitle = item.title;
                    if (item.year) {
                        itemTitle += ` (${item.year})`;
                    }
                    const itemType = item.type ? `<span class="text-xs text-gray-500 dark:text-gray-400 ml-1">${item.type}</span>` : '';
                    const posterSrc = item.poster_url;
                    const onErrorScript = "this.onerror=null; this.src='/static/logos/placeholder_poster.png';";
                    const imageHtml = `<img src="${posterSrc}" alt="Poster for ${itemTitle}" class="w-10 h-15 object-cover rounded-sm mr-3 flex-shrink-0" onerror="${onErrorScript}">`;
                    const textHtml = `
                        <div class="flex-grow overflow-hidden">
                            <div class="font-medium text-gray-800 dark:text-gray-100 truncate" title="${itemTitle}">${itemTitle}</div>
                            <div class="text-xs text-gray-600 dark:text-gray-400">${item.year ? '('+item.year+')' : ''} ${itemType}</div>
                        </div>
                    `;
                    const innerFlexContainer = `<div class="flex items-center p-2 cursor-pointer">${imageHtml}${textHtml}</div>`;
                    html += `<div class="search-result-item" data-title="${item.title.replace(/&/g, '&amp;').replace(/"/g, '&quot;')}">${innerFlexContainer}</div>`;
                });
                searchResultsDiv.innerHTML = html;
                if (window.innerWidth < mobileBreakpoint) {
                    applyMobileResultsStyle();
                } else {
                    applyDesktopResultsStyle();
                }
            } else {
                searchResultsDiv.innerHTML = '<div class="px-4 py-2 text-gray-500 dark:text-gray-400">No results found.</div>';
                if (window.innerWidth < mobileBreakpoint) {
                    applyMobileResultsStyle();
                } else {
                    applyDesktopResultsStyle();
                }
            }
            updateHighlight();
        }catch(e){
            if(e.name!=='AbortError') {
                console.error(e);
                hideResults();
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
            searchResultsDiv.innerHTML = '';
        }
    });
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
          const showTitle = selectedItem.getAttribute('data-title');
          if (showTitle) searchInput.value = showTitle;
          hideResults();
          return;
        }
      } else if (event.key === 'Escape') {
        event.preventDefault();
        hideResults();
        searchInput.blur();
      }
    });
    searchResultsDiv.addEventListener('click', function(event) {
        let targetElement = event.target;
        while (targetElement != null && !targetElement.classList.contains('search-result-item')) {
            targetElement = targetElement.parentElement;
        }
        if (targetElement && targetElement.classList.contains('search-result-item')) {
            const showTitle = targetElement.getAttribute('data-title');
            if (showTitle) searchInput.value = showTitle;
            hideResults();
            return;
        }
    });
    document.addEventListener('click', function(event) {
        if (!searchForm.contains(event.target)) {
            hideResults();
        }
    });
    window.addEventListener('resize', function() {
        if (!searchResultsDiv.classList.contains('hidden') && searchInput.value.trim()) {
            if (searchResultsDiv.innerHTML.trim() !== '') {
                 if (window.innerWidth < mobileBreakpoint) {
                    applyMobileResultsStyle();
                } else {
                    applyDesktopResultsStyle();
                }
            } else {
                hideResults();
            }
        }
    });
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