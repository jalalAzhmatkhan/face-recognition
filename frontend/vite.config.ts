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
    // Headroom for `asyncUtilTimeout` (3000 ms, see setupTests.ts): a test
    // doing two sequential async waits on a contended worker can legitimately
    // need more than the 5000 ms default, and a test that blows its budget
    // for machine reasons reports as an unrelated assertion failure rather
    // than as a timeout -- see setupTests.ts for why.
    testTimeout: 15000,
    // A spy that outlives its test is a cross-test coupling waiting to
    // happen. Restoring centrally means no suite can forget to (three of the
    // four suites in EnrollmentCapturePage.test.tsx called
    // `vi.restoreAllMocks()`; the fourth did not).
    restoreMocks: true,
  },
})
