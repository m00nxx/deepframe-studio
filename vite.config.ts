import path from "node:path"
import tailwindcss from "@tailwindcss/vite"
import react from "@vitejs/plugin-react"
import { defineConfig } from "vite"

export default defineConfig({
  plugins: [react(), tailwindcss()],
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "./src"),
    },
  },
  clearScreen: false,
  test: {
    include: ["src/**/*.test.{ts,tsx}"],
    exclude: ["node_modules", "dist", "vendor", "artifacts", "backend", "codexcli_reborn", "src-tauri"],
  },
  server: {
    strictPort: true,
    port: 5173,
    watch: {
      ignored: [
        "**/_backups/**",
        "**/artifacts/**",
        "**/backend/**",
        "**/codexcli_reborn/**",
        "**/dist/**",
        "**/src-tauri/target/**",
        "**/vendor/**",
        "**/vs-plugins/**",
      ],
    },
  },
  envPrefix: ["VITE_", "TAURI_"],
})
