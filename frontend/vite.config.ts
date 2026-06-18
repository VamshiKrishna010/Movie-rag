import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";

export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    port: 5173,
    proxy: {
      "/auth": "http://localhost:8000",
      "/movies": "http://localhost:8000",
      "/genres": "http://localhost:8000",
      "/query": "http://localhost:8000",
    },
  },
});
