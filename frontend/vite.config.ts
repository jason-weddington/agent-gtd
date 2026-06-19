/// <reference types="vitest" />
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    allowedHosts: true,
    proxy: {
      '/api': {
        target: 'http://localhost:8000',
        changeOrigin: true,
      },
    },
  },
  build: {
    commonjsOptions: {
      include: [/react-transition-group/, /node_modules/],
    },
  },
  test: {
    environment: 'happy-dom',
    globals: true,
    setupFiles: ['./src/test-setup.ts'],
    // Cap worker pool so a dispatch build on a shared host can't fan vitest out
    // to host-CPU-count and OOM the box (see kb-01857; mirrors grit-mile's cap).
    minWorkers: 1,
    maxWorkers: 4,
  },
})
