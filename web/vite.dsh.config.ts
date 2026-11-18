import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import { resolve } from 'node:path'
export default defineConfig({
  plugins: [react()], base: './', define: { 'process.env.NODE_ENV': JSON.stringify('production') },
  build: { target: 'esnext', outDir: 'dist-dsh', copyPublicDir: false, assetsInlineLimit: 0,
    lib: { entry: resolve(__dirname, 'src/embed.tsx'), formats: ['es'], fileName: () => 'entry.js' },
    rollupOptions: { output: { assetFileNames: 'assets/[name]-[hash][extname]', chunkFileNames: 'assets/[name]-[hash].js' } },
  },
})
