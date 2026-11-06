import { defineConfig } from 'vite';

// Dev: `npm run dev` proxies /ws to the bridge (python -m web.bridge on :8080).
// Production: `npm run build` -> dist/, served by the bridge itself.
export default defineConfig({
  base: './',
  server: {
    host: '127.0.0.1',
    port: 5188,
    strictPort: true,
    proxy: { '/ws': { target: 'ws://127.0.0.1:8080', ws: true } },
  },
  preview: {
    host: '127.0.0.1',
    port: 4188,
    strictPort: true,
  },
  build: {
    sourcemap: false,
    chunkSizeWarningLimit: 900,
  },
});
