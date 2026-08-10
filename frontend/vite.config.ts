import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import { readFileSync } from 'node:fs'

// 前端构建版本号：与 electron/package.json 保持一致（构建期注入，运行时可见）
const appVersion = JSON.parse(readFileSync(new URL('../electron/package.json', import.meta.url), 'utf-8')).version || '0.0.0'

export default defineConfig({
  plugins: [react()],
  define: {
    __APP_VERSION__: JSON.stringify(appVersion),
  },
  server: {
    port: 5174,
    proxy: {
      '/api': 'http://localhost:8000',
      '/uploads': 'http://localhost:8000',
    },
  },
})
