export default {
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  theme: {
    extend: {
      colors: {
        brain: {
          bg:      '#0d0d0d',
          surface: '#1a1a1a',
          border:  '#2a2a2a',
          accent:  '#6366f1',
          gate:    '#f59e0b',
          ok:      '#22c55e',
          fail:    '#ef4444',
          muted:   '#6b7280',
        }
      }
    }
  },
  plugins: []
}
