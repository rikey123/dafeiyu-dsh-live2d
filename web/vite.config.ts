import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
// DAFEIYU_GATEWAY lets dev/QA point at an isolated gateway (for example the acceptance server on 8875).
const gateway = process.env.DAFEIYU_GATEWAY || '127.0.0.1:8765'
export default defineConfig({ plugins: [react()], build: { target: 'esnext' }, optimizeDeps: { esbuildOptions: { target: 'esnext' } }, server: { proxy: { '/api': `http://${gateway}`, '/ws': { target: `ws://${gateway}`, ws: true } } } })
