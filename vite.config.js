import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    // Only for plain `npm run dev` against a local uvicorn. On Vercel (and `vercel dev`) the
    // top-level /api rewrite in vercel.json routes these same-origin calls to the backend service.
    proxy: { "/api": "http://127.0.0.1:8000" },
  },
});
