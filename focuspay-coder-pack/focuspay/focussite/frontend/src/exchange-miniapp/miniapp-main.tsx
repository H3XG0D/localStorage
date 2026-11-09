import React from "react";
import ReactDOM from "react-dom/client";
import { BrowserRouter } from "react-router-dom";
import { Toaster } from "sonner";
import { SessionProvider } from "@/lib/session";
import { Shell } from "./Shell";
import { TelegramGate } from "./TelegramGate";
import { bootTelegram } from "./telegram";
import "@/index.css";
import "./exchange.css";

bootTelegram();

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <BrowserRouter basename="/exchange/tg">
      <SessionProvider>
        <TelegramGate>
          <Shell />
        </TelegramGate>
        <Toaster position="top-center" theme="system" />
      </SessionProvider>
    </BrowserRouter>
  </React.StrictMode>,
);
