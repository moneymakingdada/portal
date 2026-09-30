import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";

// In development the Vite dev server proxies /api to Django, so the browser sees
// one origin: session and CSRF cookies just work and no CORS is needed.
// (In production put both behind one domain, e.g. nginx: / -> dist, /api -> gunicorn.)
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      "/api": { target: process.env.API_PROXY_TARGET || "http://127.0.0.1:8000", changeOrigin: false },
    },
  },
  test: {
    environment: "jsdom",
    setupFiles: "./src/test/setup.js",
    css: false,
    globals: true,
  },
});
