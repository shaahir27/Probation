import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

const apiTarget = process.env.PROBATION_D6_E2E_API_TARGET ?? "http://127.0.0.1:8000";
const proxy = {
  "/api": {
    target: apiTarget,
    changeOrigin: true,
  },
};

// https://vitejs.dev/config/
export default defineConfig({
  plugins: [react()],
  server: { port: 5173, proxy },
  // The D6 browser acceptance run serves the built bundle, so the preview server needs
  // the same same-origin /api proxy the dev server had.
  preview: { port: Number(process.env.PROBATION_D6_E2E_WEB_PORT ?? 4173), proxy },
});
