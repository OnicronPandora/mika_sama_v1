import { defineConfig } from 'vite'

export default defineConfig({
  // Always 5173: the Acer client's /ws/chat only accepts pages from it (ClientSettings.allowed_origins).
  server: { port: 5173, strictPort: true },
  // PixiJS and easy-live2d make one large chunk; the pages load it from this machine.
  build: { rolldownOptions: { input: { check: 'check.html' } }, chunkSizeWarningLimit: 1000 },
})
