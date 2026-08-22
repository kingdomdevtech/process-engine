import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

export default defineConfig({
  plugins: [react(), tailwindcss()],
  // In production the built app calls the engine at VITE_API_BASE (see
  // .env.example); this proxy only serves `npm run dev` against a local engine.
  server: {
    proxy: {
      '/api': 'http://127.0.0.1:8000',
      // the handbooks in docs/, which the in-app guided tour links to
      '/help': 'http://127.0.0.1:8000',
    },
  },
})
