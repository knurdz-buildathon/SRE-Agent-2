/** @type {import('tailwindcss').Config} */
export default {
  content: [
    "./index.html",
    "./src/**/*.{js,ts,jsx,tsx}",
  ],
  theme: {
    extend: {
      colors: {
        panel: '#1a1d23',
        card: '#22262e',
        border: '#2d3139',
        accent: '#3b82f6',
        healthy: '#22c55e',
        unhealthy: '#ef4444',
        warn: '#f59e0b',
        degraded: '#f97316',
        muted: '#9ca3af',
      },
    },
  },
  plugins: [],
};
