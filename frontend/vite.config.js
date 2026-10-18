import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  // The container serves the built files; `npm run dev` works the same way.
  server: { host: true, port: 5173 },
  preview: { host: true, port: 5173 },
})
