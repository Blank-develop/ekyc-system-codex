import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import fs from "node:fs";

const httpsKey = process.env.VITE_HTTPS_KEY;
const httpsCert = process.env.VITE_HTTPS_CERT;
const https = httpsKey && httpsCert
  ? {
      key: fs.readFileSync(httpsKey),
      cert: fs.readFileSync(httpsCert)
    }
  : undefined;

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    https,
    allowedHosts: [".trycloudflare.com", ".myawswebsite.site"],
    proxy: {
      "/api": "http://localhost:8000"
    }
  }
});
