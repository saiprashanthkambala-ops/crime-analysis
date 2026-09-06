import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  server: {
    host: '0.0.0.0',
    port: 5173,
    proxy: {
      '/auth': 'http://localhost:8000',
      '/cases': 'http://localhost:8000',
      '/documents': 'http://localhost:8000',
      '/processing': 'http://localhost:8000',
      '/search': 'http://localhost:8000',
      '/persons': 'http://localhost:8000',
      '/relationships': 'http://localhost:8000',
      '/evidence': 'http://localhost:8000',
      '/timeline': 'http://localhost:8000',
      '/graph': 'http://localhost:8000',
      '/audit': 'http://localhost:8000',
      '/admin': 'http://localhost:8000',
      '/health': 'http://localhost:8000',
    },
  },
  build: {
    outDir: 'dist',
  },
})
