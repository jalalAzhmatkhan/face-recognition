/// <reference types="vitest/config" />
import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  server: {
    watch: {
      // WSL2/Docker Desktop bind-mounts of a Windows-host directory don't
      // reliably forward inotify events into the Linux container, so
      // Vite's default file watcher (chokidar) never sees edits made from
      // the host -- HMR silently stops working (found live running via
      // docker-compose.dev.yml). Polling is the standard workaround for
      // this, gated behind CHOKIDAR_USEPOLLING (set by that compose
      // file's `frontend` service only) so a native, non-Docker
      // `npm run dev` doesn't pay the extra CPU cost of polling for no
      // reason.
      usePolling: process.env.CHOKIDAR_USEPOLLING === 'true',
    },
  },
  test: {
    environment: 'jsdom',
    globals: false,
    setupFiles: ['./src/setupTests.ts'],
    css: false,
  },
})
