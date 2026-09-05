import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// Complete Collision dashboard dev server.
// Pinned to 5182, strictPort:true — DO NOT let this drift.
// Sibling apps on this same Neon project's dashboards, for reference:
//   shell-dashboard   5173
//   vls-dashboard     5180
//   elektrica-dashboard 5181
//   complete-collision-dashboard (this app) 5182
// An earlier port-drift bug on this exact multi-app setup caused a stale
// bookmarked URL to silently serve the wrong app. strictPort:true makes
// Vite fail loudly instead of picking a random free port if 5182 is busy.
export default defineConfig({
  server: { port: 5182, strictPort: true },
  plugins: [react()],
})
