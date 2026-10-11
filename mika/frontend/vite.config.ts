import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

export default defineConfig({
  plugins: [react()],
  // Always 5173: the Acer client's /ws/chat only accepts pages from it (ClientSettings.allowed_origins).
  // Any other path (/avatar, /admin) gets index.html, and the app picks the page.
  server: { port: 5173, strictPort: true },
  build: {
    rolldownOptions: { input: { app: 'index.html', check: 'check.html' } },
    chunkSizeWarningLimit: 1000, // PixiJS and easy-live2d make one large chunk; the pages load it from this machine
  },
})
