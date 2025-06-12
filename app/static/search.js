// Search bar functionality
(function(){
  document.addEventListener('DOMContentLoaded', function(){
    const input = document.getElementById('search-input');
    const results = document.getElementById('search-results');
    if(!input || !results) return;

    let controller;
    let currentHighlightIndex = -1;
    const keyboardSelectedClass = 'keyboard-selected'; // Changed from highlightClass

    function updateHighlight() {
      const items = results.children;
      for (let i = 0; i < items.length; i++) {
        // Ensure class is removed only from the <a> tag itself
        items[i].classList.remove(keyboardSelectedClass);
      }
      if (currentHighlightIndex >= 0 && currentHighlightIndex < items.length) {
        const currentItem = items[currentHighlightIndex];
        // Ensure class is added only to the <a> tag itself
        currentItem.classList.add(keyboardSelectedClass);
        currentItem.scrollIntoView({ block: 'nearest' });
      }
    }

    input.addEventListener('input', async function(){
      const q = this.value.trim();
      currentHighlightIndex = -1; // Reset highlight on new input
      // updateHighlight(); // Ensure any visual keyboard selection is cleared immediately. This will be called later if results are populated.
      if(controller){ controller.abort(); }
      if(!q){ results.classList.add('hidden'); results.innerHTML=''; return; }

      controller = new AbortController();
      try{
        const resp = await fetch('/search?q=' + encodeURIComponent(q), {signal: controller.signal});
        if(!resp.ok) throw new Error('search failed');
        const data = await resp.json();
        results.innerHTML = data.map(item => {
          let itemHtml = '';
          let itemTitle = item.title;
          if (item.year) {
            itemTitle += ` (${item.year})`;
          }
          // The hover:bg-gray-200 dark:hover:bg-gray-700 are on the A tag.
          // The keyboardSelectedClass will be applied to the A tag itself.
          const baseDivHtml = `<div class="p-2 cursor-pointer">${itemTitle}</div>`;

          if ((item.type === 'movie' || item.type === 'show') && item.tmdb_id) {
            const link = item.type === 'movie' ? `/movie/${item.tmdb_id}` : `/show/${item.tmdb_id}`;
            itemHtml = `<a href="${link}" class="block hover:bg-gray-200 dark:hover:bg-gray-700">${baseDivHtml}</a>`;
          } else {
            // For non-linkable items, the div itself is the child of 'results'
            // These non-linkable items won't be navigable by keyboard in the current setup,
            // as 'items' in addEventListener('keydown') only looks at 'results.children' which are <a> tags.
            // This is existing behavior.
            itemHtml = `<div class="p-2">${itemTitle}</div>`; // Non-linked item
          }
          return itemHtml;
        }).join('');

        if(data.length > 0) {
          results.classList.remove('hidden');
        } else {
          results.classList.add('hidden');
        }
        updateHighlight(); // Call to remove any previous highlight or apply to index 0 if input changes quickly
      }catch(e){ if(e.name!=='AbortError') console.error(e); }
    });

    input.addEventListener('keydown', function(event) {
      const items = results.children;
      if (results.classList.contains('hidden') || items.length === 0) {
        currentHighlightIndex = -1;
        updateHighlight(); // Clear any existing keyboard highlight if results are hidden or empty
        return;
      }

      if (event.key === 'ArrowDown') {
        event.preventDefault();
        currentHighlightIndex++;
        if (currentHighlightIndex >= items.length) {
          currentHighlightIndex = 0; // Wrap around
        }
        updateHighlight();
      } else if (event.key === 'ArrowUp') {
        event.preventDefault();
        currentHighlightIndex--;
        if (currentHighlightIndex < 0) {
          currentHighlightIndex = items.length - 1; // Wrap around
        }
        updateHighlight();
      } else if (event.key === 'Enter') {
        event.preventDefault();
        if (currentHighlightIndex >= 0 && currentHighlightIndex < items.length) {
          const selectedItem = items[currentHighlightIndex];
          if (selectedItem && typeof selectedItem.click === 'function') {
            // If it's an <a> tag, it will have an href and click will navigate.
            // If it's a div (non-linkable), click won't do anything here.
            selectedItem.click();
          } else if (selectedItem && selectedItem.href) { // Fallback for non-clickable <a>
             window.location.href = selectedItem.href;
          }
        }
        results.classList.add('hidden');
        currentHighlightIndex = -1;
      } else if (event.key === 'Escape') {
        results.classList.add('hidden');
        currentHighlightIndex = -1;
        updateHighlight(); // Clear keyboard highlight
        input.blur();
      }
    });

    document.addEventListener('click', (e)=>{
      if(!results.contains(e.target) && e.target!==input){
        results.classList.add('hidden');
        currentHighlightIndex = -1;
        updateHighlight(); // Clear keyboard highlight when hiding results
      }
    });

    // Optional: Mouse hover interaction
    results.addEventListener('mouseover', function(e) {
        const items = Array.from(results.children);
        let targetItem = e.target;
        // Traverse up if the event target is a child of an item (e.g., the inner div)
        while(targetItem && targetItem.parentNode !== results) {
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
