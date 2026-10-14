import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// The portal talks straight to Supabase from the browser (with the signed-in user's own token), so there is no
// proxy to the admin API: the admin app is never reachable from here.
export default defineConfig({
  plugins: [react()],
  server: { port: 5174, strictPort: true },
})
