import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Proxy API calls to the Django dev server so cookies stay same-origin.
export default defineConfig({
  plugins: [react()],
  server: {
    // PORT lets a second dev server (e.g. a preview session) use a free port.
    port: Number(process.env.PORT) || 5173,
    proxy: {
      "/api": {
        target: "http://localhost:8000",
        // Django's CSRF origin check trusts http://localhost:5173. When the dev
        // server runs on another port (PORT env), present the canonical dev
        // origin so writes still pass. Dev-only; the session cookie is
        // SameSite=Lax so this doesn't open cross-site writes.
        configure: (proxy) =>
          proxy.on("proxyReq", (proxyReq, req) => {
            if (req.headers.origin) proxyReq.setHeader("origin", "http://localhost:5173");
          }),
      },
    },
  },
  build: {
    rollupOptions: {
      output: {
        // Split heavy, cacheable vendors out of the main bundle.
        manualChunks: {
          react: ["react", "react-dom", "react-router-dom"],
          motion: ["framer-motion"],
          charts: ["recharts"],
        },
      },
    },
  },
});
