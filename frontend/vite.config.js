import react from '@vitejs/plugin-react';
import { defineConfig } from 'vite';

// В разработке фронт живёт на 5173, а запросы к /api уходят на сервер FastAPI на 8000.
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: { '/api': 'http://127.0.0.1:8000' },
  },
});
