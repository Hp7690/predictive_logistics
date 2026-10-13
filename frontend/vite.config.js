import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

// The browser talks to /api/... and Vite forwards it to the FastAPI backend (no CORS setup needed).
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: { '/api': { target: 'http://localhost:8000', changeOrigin: true, ws: true, rewrite: (p) => p.replace(/^\/api/, '') } },
  },
});
