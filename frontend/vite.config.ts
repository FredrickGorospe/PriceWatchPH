import react from '@vitejs/plugin-react';
import { defineConfig } from 'vitest/config';


const djangoTarget = process.env.VITE_DJANGO_PROXY_TARGET ?? 'http://localhost:8000';

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    strictPort: true,
    proxy: {
      '/api': { target: djangoTarget },
      '/admin': { target: djangoTarget },
      '/static': { target: djangoTarget },
    },
  },
  test: {
    environment: 'jsdom',
    setupFiles: './src/test/setup.ts',
    css: true,
  },
});
