module.exports = {
  darkMode: 'class', // Enable dark mode via .dark class
  content: [
    'app/templates/**/*.html', // All Flask/Jinja templates
    './app/static/**/*.js',      // Any JS that uses Tailwind classes
  ],
  safelist: [
    'text-green-500',
    'text-red-500',
    'bg-white',
    'dark:bg-slate-800',
    'text-sky-600',
    'dark:text-sky-400',
    'border-slate-200',
    'dark:border-slate-700',
    'border-b-white',
    'dark:border-b-slate-800',
    'shadow-sm',
    '-mb-px',
    'z-10',
    'bg-slate-100',
    'dark:bg-slate-900',
    'text-slate-600',
    'dark:text-slate-400',
    'border-transparent',
    'hover:bg-slate-200',
    'dark:hover:bg-slate-800',
  ],
  theme: {
    extend: {},
  },
  plugins: [],
};
