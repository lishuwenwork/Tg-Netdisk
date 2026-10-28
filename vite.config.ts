import { defineConfig } from "vite";
import vue from "@vitejs/plugin-vue";
import tailwindcss from "@tailwindcss/vite";
export default defineConfig({
  root: "frontend",
  base: "./",
  plugins: [vue(), tailwindcss()],
  server: { host: "127.0.0.1", port: 5173, strictPort: true },
  build: { outDir: "../dist", emptyOutDir: true, chunkSizeWarningLimit: 900 },
  worker: { format: "es" },
});
