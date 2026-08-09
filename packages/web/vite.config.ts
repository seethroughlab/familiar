import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'
import { VitePWA } from 'vite-plugin-pwa'
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
    // Skip PWA/service worker for Capacitor builds — native app doesn't need it
    ...(!isCapacitorBuild ? [VitePWA({
      registerType: 'autoUpdate',
      // Registered by hand in `main.tsx` rather than injected, because injection is per-*build*
      // and not per-entry: the plugin puts `registerSW.js` into every HTML document it emits,
      // which silently included `embed.html`. The embedded surface must not register a service
      // worker — it runs inside a `WKWebView` in the Mac app, where a worker would serve that
      // window cached assets on a schedule nobody watching could see, and ADR-0017 gives it its
      // own entry point precisely so it shares nothing it does not need.
      injectRegister: null,
      includeAssets: ['icons/*.png', 'icons/*.svg'],
      manifest: false, // Using our custom manifest.json
      workbox: {
        // Cache app shell and static assets
        globPatterns: ['**/*.{js,css,html,ico,png,svg,woff,woff2}'],
        // Allow larger chunks to be cached (default is 2 MiB)
        maximumFileSizeToCacheInBytes: 4 * 1024 * 1024, // 4 MiB
        // Don't serve SPA for API routes (especially OAuth callbacks)
        navigateFallbackDenylist: [/^\/api\//],
        // Runtime caching strategies
        runtimeCaching: [
          {
            // Never cache OAuth callbacks - let browser handle redirects
            urlPattern: /\/api\/v1\/spotify\/callback/,
            handler: 'NetworkOnly',
          },
          {
            // Never cache OAuth auth requests
            urlPattern: /\/api\/v1\/spotify\/auth/,
            handler: 'NetworkOnly',
          },
          {
            // Cache album artwork (legacy track-based)
            urlPattern: /\/api\/v1\/tracks\/.*\/artwork/,
            handler: 'CacheFirst',
            options: {
              cacheName: 'artwork-cache',
              expiration: {
                maxEntries: 500,
                maxAgeSeconds: 60 * 60 * 24 * 30, // 30 days
              },
            },
          },
          {
            // Cache album artwork (hash-based)
            urlPattern: /\/api\/v1\/artwork\/[a-f0-9]+\/(full|thumb)/,
            handler: 'CacheFirst',
            options: {
              cacheName: 'artwork-cache',
              expiration: {
                maxEntries: 500,
                maxAgeSeconds: 60 * 60 * 24 * 30, // 30 days
              },
            },
          },
          {
            // Cache API responses (except streaming and OAuth)
            urlPattern: /\/api\/v1\/(?!tracks\/.*\/stream|tracks\/.*\/video|spotify\/callback|spotify\/auth)/,
            handler: 'NetworkFirst',
            options: {
              cacheName: 'api-cache',
              expiration: {
                maxEntries: 100,
                maxAgeSeconds: 60 * 5, // 5 minutes
              },
              networkTimeoutSeconds: 10,
            },
          },
          {
            // Don't cache audio streams - always fetch fresh
            urlPattern: /\/api\/v1\/tracks\/.*\/stream/,
            handler: 'NetworkOnly',
          },
        ],
      },
      devOptions: {
        enabled: false, // Disable in dev mode
      },
    })] : []),
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
