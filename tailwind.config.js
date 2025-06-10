module.exports = {
  darkMode: 'class', // Enable dark mode via .dark class
  content: [
    'app/templates/**/*.html', // All Flask/Jinja templates
    './app/static/**/*.js',      // Any JS that uses Tailwind classes
  ],
  safelist: [
    'text-green-500',
    'text-red-500',
  ],
  theme: {
    extend: {},
  },
  plugins: [],
};
