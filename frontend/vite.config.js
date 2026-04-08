import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],

  // Dev server: proxy /api to the FastAPI backend
  server: {
    proxy: {
      '/api': {
        target: 'http://localhost:8000',
        changeOrigin: true,
      },
    },
  },

  // Production build optimisations
  build: {
    rollupOptions: {
      output: {
        manualChunks: {
          // Split heavy vendor libs into separate chunks for better caching
          react:    ['react', 'react-dom'],
          charts:   ['recharts'],
          icons:    ['lucide-react'],
          dropzone: ['react-dropzone'],
          axios:    ['axios'],
        },
      },
    },
    // Increase warning threshold for chart libraries
    chunkSizeWarningLimit: 600,
  },
})
