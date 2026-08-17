import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'
import { resolve } from 'node:path'

const isCapacitorBuild = process.env.BUILD_TARGET === 'capacitor';

// https://vite.dev/config/
export default defineConfig({
  define: {
    __BUILD_TIME__: JSON.stringify(new Date().toISOString()),
  },
  build: {
    manifest: true,
    rollupOptions: {
      // Three documents, not one. `embed.html` is the embedded Discover surface ADR-0017 gives its
      // own entry point; `visualizer.html` is the embedded visualizer ADR-0033 adds. Naming
      // `index.html` here is required as soon as `input` is set at all — Vite's default single
      // entry stops applying.
      //
      // Not built for Capacitor: the iOS app is the listening path (ADR-0013 point 2) and embeds
      // nothing, so the extra documents would be dead weight in the bundle it ships.
      input: isCapacitorBuild
        ? { index: resolve(__dirname, 'index.html') }
        : {
            index: resolve(__dirname, 'index.html'),
            embed: resolve(__dirname, 'embed.html'),
            visualizer: resolve(__dirname, 'visualizer.html'),
          },
      output: {
        manualChunks(id) {
          // Vendor chunks - split large dependencies
          if (/node_modules\/(react|react-dom|react-router|react-router-dom)\//.test(id)) return 'vendor-react';
          if (id.includes('node_modules/@tanstack/react-query')) return 'vendor-query';
          if (id.includes('node_modules/dexie')) return 'vendor-audio';
          if (id.includes('node_modules/lucide-react')) return 'vendor-icons';
          // Isolate three.js ecosystem into its own cacheable chunk (loaded lazily via UMAPExplorer)
          if (/node_modules\/(three|@react-three)\//.test(id)) return 'vendor-three';
        },
      },
    },
    // Increase chunk size warning limit slightly
    chunkSizeWarningLimit: 600,
  },
  plugins: [
    react(),
    tailwindcss(),
    // No service worker: ADR-0059 retired the PWA. `main.tsx` unregisters any worker a
    // previous visit installed — see the comment there before assuming that block is dead code.
  ],
  server: {
    port: 3000,
    proxy: {
      // More specific routes must come first - Vite matches in order
      '/api/v1/tracks': {
        target: process.env.VITE_API_TARGET || 'http://localhost:4400',
        changeOrigin: true,
        timeout: 0, // No timeout for streaming/downloads (can take 10+ minutes over slow connections)
      },
      '/api': {
        target: process.env.VITE_API_TARGET || 'http://localhost:4400',
        changeOrigin: true,
        timeout: 300000, // 5 minute timeout for long operations like Spotify sync
      },
    },
  },
})
