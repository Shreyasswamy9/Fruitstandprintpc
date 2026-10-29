import { cpSync, existsSync, mkdirSync } from "node:fs";
import { resolve } from "node:path";
import { defineConfig, type Plugin } from "vite";
import react from "@vitejs/plugin-react";

// pdf.js needs character maps, standard fonts and wasm decoders at runtime.
// Copy them into public/ so previews work fully offline (no CDN).
function pdfjsAssets(): Plugin {
  return {
    name: "printhub-pdfjs-assets",
    buildStart() {
      const src = resolve(import.meta.dirname, "node_modules/pdfjs-dist");
      const dest = resolve(import.meta.dirname, "public/pdfjs");
      mkdirSync(dest, { recursive: true });
      for (const dir of ["cmaps", "standard_fonts", "wasm"]) {
        if (existsSync(resolve(src, dir))) cpSync(resolve(src, dir), resolve(dest, dir), { recursive: true });
      }
    },
  };
}

export default defineConfig({
  plugins: [react(), pdfjsAssets()],
  server: {
    port: 5173,
    proxy: { "/api": "http://127.0.0.1:8080" },
  },
  build: { outDir: "dist", sourcemap: false, chunkSizeWarningLimit: 1500 },
});
