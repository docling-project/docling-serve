import path from "node:path";
import tailwindcss from "@tailwindcss/vite";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// The UI is served by docling-serve at /ui. A relative base keeps asset URLs
// working behind a reverse proxy with a root path (UVICORN_ROOT_PATH).
export default defineConfig({
  base: "./",
  plugins: [react(), tailwindcss()],
  resolve: {
    alias: { "@": path.resolve(__dirname, "src") },
  },
  build: {
    outDir: "../docling_serve/ui_static",
    emptyOutDir: true,
    chunkSizeWarningLimit: 1000,
  },
  server: {
    // `npm run dev` proxies the API to a local docling-serve.
    proxy: Object.fromEntries(
      ["/v1", "/health", "/ready", "/version", "/openapi.json"].map((p) => [
        p,
        { target: process.env.DOCLING_SERVE_URL ?? "http://localhost:5001", ws: true },
      ]),
    ),
  },
});
