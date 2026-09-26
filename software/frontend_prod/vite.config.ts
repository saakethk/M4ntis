import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

export default defineConfig({
  plugins: [react()],
  // Repo-root .env (same file as .env.example), two levels above this app.
  envDir: '../..',
  server: {
    host: '0.0.0.0',
    port: 8002,
    strictPort: true,
  },
})
