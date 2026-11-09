import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";
import { devPanelAuthPlugin, devPanelProxyConfigure } from "./vite.dev-panel-auth";
import { devWeekSnapshotPlugin } from "./vite.dev-week-snapshot";

// Dev proxy: forward /api to the live FocusPay backend so screens can be
// developed against real data. Production serves same-origin /api via nginx.
const API_TARGET =
  (globalThis as { process?: { env?: Record<string, string | undefined> } }).process?.env?.VITE_API_TARGET ||
  "https://focuspay.org";

export default defineConfig({
  plugins: [
    {
      name: "panel-html-for-x8-ops",
      configureServer(server) {
        server.middlewares.use((req, _res, next) => {
          const incoming = req as { url?: string };
          const url = incoming.url ?? "";
          if (url.startsWith("/x8") || url.startsWith("/ops")) {
            const q = url.indexOf("?");
            incoming.url = "/panel.html" + (q >= 0 ? url.slice(q) : "");
          } else if (url.startsWith("/casino/tg")) {
            const q = url.indexOf("?");
            incoming.url = "/casino.html" + (q >= 0 ? url.slice(q) : "");
          } else if (
            (url === "/casino" || url.startsWith("/casino/")) &&
            !/\.[a-z0-9]+($|\?)/i.test(url)
          ) {
            // casino.html is a Vite entry, so /casino would otherwise open the mini app.
            // Leave /casino/*.svg and other files alone.
            const q = url.indexOf("?");
            incoming.url = "/index.html" + (q >= 0 ? url.slice(q) : "");
          } else if (url === "/exchange/tg" || url.startsWith("/exchange/tg/") || url.startsWith("/exchange/tg?")) {
            const q = url.indexOf("?");
            incoming.url = "/exchange.html" + (q >= 0 ? url.slice(q) : "");
          }
          next();
        });
      },
    },
    devPanelAuthPlugin(API_TARGET),
    devWeekSnapshotPlugin(),
    react(),
    tailwindcss(),
  ],
  resolve: { alias: { "@": "/src" } },
  server: {
    host: "0.0.0.0",
    port: 5173,
    proxy: {
      "/api": {
        target: API_TARGET,
        changeOrigin: true,
        secure: true,
        configure: devPanelProxyConfigure(),
      },
    },
  },
  build: {
    outDir: "dist",
    emptyOutDir: true,
    rollupOptions: {
      // Public site, admin/operator panel, casino Mini App, exchange Mini App.
      input: {
        index: "index.html",
        panel: "panel.html",
        casino: "casino.html",
        exchange: "exchange.html",
      },
    },
  },
});
