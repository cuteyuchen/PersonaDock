import { fileURLToPath, URL } from 'node:url'

import tailwindcss from '@tailwindcss/vite'
import vue from '@vitejs/plugin-vue'
import { defineConfig } from 'vite'

export default defineConfig({
  base: '/assets/vue/',
  plugins: [vue(), tailwindcss()],
  resolve: {
    alias: {
      '@': fileURLToPath(new URL('./src', import.meta.url)),
    },
  },
  build: {
    outDir: '../src/persona_dock/web/static/vue',
    emptyOutDir: true,
    assetsDir: '',
    rollupOptions: {
      output: {
        entryFileNames: 'app.js',
        chunkFileNames: 'chunk-[name]-[hash].js',
        assetFileNames: 'app.[ext]',
      },
    },
  },
  test: {
    environment: 'jsdom',
    globals: true,
  },
})
