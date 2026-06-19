import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";

/** Let the SPA handle HTML navigations; proxy only API calls to FastAPI. */
function proxyApi() {
  return {
    target: "http://localhost:8000",
    changeOrigin: true,
    bypass(req: { method?: string; headers: { accept?: string } }) {
      if (req.method === "GET" && req.headers.accept?.includes("text/html")) {
        return "/index.html";
      }
    },
  };
}

export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    port: 5173,
    proxy: {
      "/auth": proxyApi(),
      "/admin": proxyApi(),
      "/movies": "http://localhost:8000",
      "/genres": "http://localhost:8000",
      "/query": "http://localhost:8000",
    },
  },
});
