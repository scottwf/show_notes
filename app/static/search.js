// Search bar functionality
(function(){
  document.addEventListener('DOMContentLoaded', function(){
    const input = document.getElementById('search-input');
    const results = document.getElementById('search-results');
    if(!input || !results) return;
    let controller;
    input.addEventListener('input', async function(){
      const q = this.value.trim();
      if(controller){ controller.abort(); }
      if(!q){ results.classList.add('hidden'); results.innerHTML=''; return; }
      controller = new AbortController();
      try{
        const resp = await fetch('/search?q=' + encodeURIComponent(q), {signal: controller.signal});
        if(!resp.ok) throw new Error('search failed');
        const data = await resp.json();
        results.innerHTML = data.map(item => `<div class="p-2 cursor-pointer hover:bg-gray-200 dark:hover:bg-gray-700">${item.title}</div>`).join('');
        results.classList.remove('hidden');
      }catch(e){ if(e.name!=='AbortError') console.error(e); }
    });
    document.addEventListener('click', (e)=>{
      if(!results.contains(e.target) && e.target!==input){
        results.classList.add('hidden');
      }
    });
  });
})();
