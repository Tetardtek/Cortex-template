import { defineConfig } from 'vite'
import { svelte } from '@sveltejs/vite-plugin-svelte'
import tailwindcss from '@tailwindcss/vite'

export default defineConfig({
  plugins: [svelte(), tailwindcss()],
  base: '/ui/',
  build: {
    outDir: 'dist',
  },
  server: {
    port: 5173,
    // En dev (`npm run dev`, port 5173), les vues appellent le moteur à la
    // racine — /docs, /agents, /intentions, /bsi… : sans ces relais, elles
    // tombaient sur Vite et disaient « le moteur ne répond pas ».
    proxy: {
      ...Object.fromEntries(['/docs', '/agents', '/intentions', '/bsi', '/visualize']
        .map((p) => [p, { target: 'http://localhost:7700', changeOrigin: true }])),
      '/api': {
        target: 'http://localhost:7700',
        changeOrigin: true,
        ws: true,
      },
    },
  },
})
