/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{js,ts,jsx,tsx}'],
  theme: {
    extend: {
      colors: {
        base: '#09090b',
        sidebar: '#0c0c0e',
        surface: '#141416',
        elevated: '#1c1c1f',
        border: '#27272a',
        muted: '#71717a',
        accent: {
          DEFAULT: '#6366f1',
          hover: '#5558e3',
          muted: '#6366f133',
        },
      },
      fontFamily: {
        sans: ['system-ui', '-apple-system', 'Segoe UI', 'Roboto', 'sans-serif'],
      },
    },
  },
  plugins: [],
};
