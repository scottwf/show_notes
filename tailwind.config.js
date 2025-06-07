module.exports = {
  darkMode: 'class', // Enable dark mode via .dark class
  content: [
    './app/templates/**/*.html', // All Flask/Jinja templates
    './app/static/**/*.js',      // Any JS that uses Tailwind classes
  ],
  theme: {
    extend: {},
  },
  plugins: [],
};
