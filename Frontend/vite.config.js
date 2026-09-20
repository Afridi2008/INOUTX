import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  build: {
    assetsDir: "react-assets"
  },
  server: {
    port: 5173,
    proxy: {
      "/api": "http://127.0.0.1:5000",
      "/socket.io": {
        target: "http://127.0.0.1:5000",
        ws: true
      },
      "/captured-frames": "http://127.0.0.1:5000"
    }
  }
});
