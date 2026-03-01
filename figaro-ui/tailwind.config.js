/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{js,ts,jsx,tsx}'],
  theme: {
    extend: {
      colors: {
        cctv: {
          bg: '#0a0a0a',
          panel: '#141414',
          border: '#2a2a2a',
          accent: '#00ff88',
          'accent-dim': '#00aa5a',
          text: '#e0e0e0',
          'text-dim': '#808080',
          error: '#ff4444',
          warning: '#ffaa00',
        },
      },
      fontFamily: {
        mono: ['JetBrains Mono', 'Fira Code', 'Consolas', 'monospace'],
      },
    },
  },
  plugins: [require('@tailwindcss/typography')],
};
