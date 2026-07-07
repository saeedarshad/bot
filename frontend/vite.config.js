import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Proxy API calls to the Django dev server so cookies stay same-origin.
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      "/api": "http://localhost:8000",
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
