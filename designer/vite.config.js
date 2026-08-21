import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    proxy: {
      '/api': 'http://127.0.0.1:8000',
      // the handbooks in docs/, which the in-app guided tour links to
      '/help': 'http://127.0.0.1:8000',
    },
  },
})
