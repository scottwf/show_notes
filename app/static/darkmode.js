// Simple dark mode toggle with localStorage persistence
(function() {
  function setDarkMode(on) {
    if (on) {
      document.documentElement.classList.add('dark');
      localStorage.setItem('theme', 'dark');
    } else {
      document.documentElement.classList.remove('dark');
      localStorage.setItem('theme', 'light');
    }
  }
  function updateSwitch() {
    const btn = document.getElementById('darkmode-toggle');
    if (!btn) return;
    if (document.documentElement.classList.contains('dark')) {
      btn.innerHTML = '<svg class="w-6 h-6" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" d="M12 3v1m0 16v1m8.66-8.66l-.7.7M4.34 4.34l-.7.7M21 12h-1M4 12H3m16.66 4.66l-.7-.7M4.34 19.66l-.7-.7M16 12a4 4 0 11-8 0 4 4 0 018 0z"/></svg>';
    } else {
      btn.innerHTML = '<svg class="w-6 h-6" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" d="M21 12.79A9 9 0 1111.21 3a7 7 0 009.79 9.79z"/></svg>';
    }
  }
  document.addEventListener('DOMContentLoaded', function() {
    const saved = localStorage.getItem('theme');
    if (saved === 'dark') setDarkMode(true);
    else if (saved === 'light') setDarkMode(false);
    updateSwitch();
    const btn = document.getElementById('darkmode-toggle');
    if (btn) {
      btn.addEventListener('click', function() {
        setDarkMode(!document.documentElement.classList.contains('dark'));
        updateSwitch();
      });
    }
  });
})();
