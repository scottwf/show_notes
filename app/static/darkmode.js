// Simple dark mode toggle with localStorage persistence
(function() {
  const darkIcon = document.getElementById('theme-toggle-dark-icon');
  const lightIcon = document.getElementById('theme-toggle-light-icon');

  function setDarkMode(on) {
    if (on) {
      document.documentElement.classList.add('dark');
      localStorage.setItem('theme', 'dark');
    } else {
      document.documentElement.classList.remove('dark');
      localStorage.setItem('theme', 'light');
    }
    updateIcons(); // Update icons immediately after setting mode
  }

  function updateIcons() {
    if (!darkIcon || !lightIcon) return; // SVGs might not be on every page
    if (document.documentElement.classList.contains('dark')) {
      darkIcon.classList.remove('hidden');
      lightIcon.classList.add('hidden');
    } else {
      darkIcon.classList.add('hidden');
      lightIcon.classList.remove('hidden');
    }
  }

  document.addEventListener('DOMContentLoaded', function() {
    // Check for SVGs again in DOMContentLoaded as they are part of layout.html
    // This ensures darkIcon and lightIcon are assigned if script runs before full DOM load.
    if (!darkIcon) darkIcon = document.getElementById('theme-toggle-dark-icon');
    if (!lightIcon) lightIcon = document.getElementById('theme-toggle-light-icon');

    const savedTheme = localStorage.getItem('theme');
    const prefersDark = window.matchMedia('(prefers-color-scheme: dark)').matches;

    if (savedTheme === 'dark') {
      setDarkMode(true);
    } else if (savedTheme === 'light') {
      setDarkMode(false);
    } else if (prefersDark) {
      setDarkMode(true); // Prefer OS setting if no localStorage
    } else {
      setDarkMode(false); // Default to light if no preference or localStorage
    }
    // Initial call to set icons based on loaded theme
    // updateIcons(); // This is now called within setDarkMode

    const btn = document.getElementById('darkmode-toggle');
    if (btn) {
      btn.addEventListener('click', function() {
        setDarkMode(!document.documentElement.classList.contains('dark'));
        // updateIcons(); // This is now called within setDarkMode
      });
    }
  });
})();
