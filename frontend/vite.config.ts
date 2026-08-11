import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  server: {
    proxy: { '/api': 'http://localhost:8721', '/mcp': 'http://localhost:8721', '/ws': { target: 'ws://localhost:8721', ws: true } }
  },
  build: {
    outDir: '../src/kaiyang/webui',
    emptyOutDir: false,
  },
})
