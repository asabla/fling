/** @type {import('tailwindcss').Config} */
module.exports = {
  darkMode: 'class',
  content: [
    './src/fling/web/templates/**/*.html',
    './src/fling/web/routes/**/*.py',
  ],
  safelist: [
    'bg-method-get/20',
    'bg-method-get/30',
    'hover:bg-method-get/30',
    'border-surface-lighter/50',
    // Method badge colors (used via dynamic Jinja2 classes)
    'text-method-get',
    'text-method-post',
    'text-method-put',
    'text-method-patch',
    'text-method-delete',
    'text-method-head',
    'text-method-options',
    // Depth-based margins for file tree
    'ml-0',
    'ml-3',
    'ml-6',
    'ml-9',
    'ml-12',
  ],
  theme: {
    extend: {
      colors: {
        surface: {
          DEFAULT: '#1e1e2e',
          light: '#313244',
          lighter: '#45475a',
        },
        accent: {
          DEFAULT: '#89b4fa',
          dim: '#585b70',
        },
        method: {
          get: '#a6e3a1',
          post: '#f9e2af',
          put: '#89b4fa',
          patch: '#94e2d5',
          delete: '#f38ba8',
          head: '#cba6f7',
          options: '#6c7086',
        },
        status: {
          success: '#a6e3a1',
          redirect: '#f9e2af',
          error: '#f38ba8',
        },
      },
    },
  },
  plugins: [],
}
