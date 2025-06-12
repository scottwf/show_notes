// Search bar functionality
(function(){
  document.addEventListener('DOMContentLoaded', function(){
    const input = document.getElementById('search-input');
    const results = document.getElementById('search-results');
    if(!input || !results) return;

    let controller;
    let currentHighlightIndex = -1;
    const highlightClass = 'search-suggestion-highlight';

    function updateHighlight() {
      const items = results.children;
      for (let i = 0; i < items.length; i++) {
        items[i].classList.remove(highlightClass);
        // Each item is an <a> tag, its child <div> has the hover styles
        if (items[i].firstElementChild) {
            items[i].firstElementChild.classList.remove(highlightClass); // Remove from inner div too
        }
      }
      if (currentHighlightIndex >= 0 && currentHighlightIndex < items.length) {
        const currentItem = items[currentHighlightIndex];
        currentItem.classList.add(highlightClass);
         // The highlighting should apply to the <a> tag directly or its immediate child <div>
        // If the structure is <a><div>..</div></a>, applying to <a> is fine for bg color.
        // If Tailwind hover classes are on the div, we might need to target that.
        // For simplicity, let's assume applying to <a> is sufficient as per CSS.
        // The CSS targets .search-suggestion-highlight directly.
        currentItem.scrollIntoView({ block: 'nearest' });
      }
    }

    input.addEventListener('input', async function(){
      const q = this.value.trim();
      currentHighlightIndex = -1; // Reset highlight on new input
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
          // Note: The hover:bg-gray-200 dark:hover:bg-gray-700 are on the DIV inside the A tag.
          // The highlightClass will be applied to the A tag itself.
          const baseDivHtml = `<div class="p-2 cursor-pointer">${itemTitle}</div>`;

          if ((item.type === 'movie' || item.type === 'show') && item.tmdb_id) {
            const link = item.type === 'movie' ? `/movie/${item.tmdb_id}` : `/show/${item.tmdb_id}`;
            // The <a> tag will receive the highlight class.
            itemHtml = `<a href="${link}" class="block hover:bg-gray-200 dark:hover:bg-gray-700">${baseDivHtml}</a>`;
          } else {
            // For non-linkable items, the div itself is the child of 'results'
            itemHtml = `<div class="p-2">${itemTitle}</div>`; // Non-linked item
          }
          return itemHtml;
        }).join('');

        if(data.length > 0) {
          results.classList.remove('hidden');
        } else {
          results.classList.add('hidden');
        }
        updateHighlight(); // Call to remove any previous highlight if results are empty or repopulated
      }catch(e){ if(e.name!=='AbortError') console.error(e); }
    });

    input.addEventListener('keydown', function(event) {
      const items = results.children;
      if (results.classList.contains('hidden') || items.length === 0) {
        currentHighlightIndex = -1; // Ensure index is reset if no items visible
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
        input.blur();
      }
    });

    document.addEventListener('click', (e)=>{
      if(!results.contains(e.target) && e.target!==input){
        results.classList.add('hidden');
        currentHighlightIndex = -1; // Reset highlight when hiding results
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
