import React from "react";
import ReactDOM from "react-dom/client";
import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";
import { Toaster } from "sonner";
import { WalletConfirmGate } from "@/components/WalletConfirmNotice";
import { SessionProvider } from "@/lib/session";
import { CasinoShell } from "./CasinoShell";
import { casinoChildRoutes } from "./casinoRoutes";
import { CASINO_TG_BASENAME } from "./casinoPaths";
import { bootTelegram } from "./telegram";
import { TelegramSession } from "./TelegramSession";
import "@/index.css";

bootTelegram();

function MiniAppRoutes() {
  return (
    <Routes>
      <Route path="/" element={<CasinoShell />}>
        {casinoChildRoutes}
      </Route>
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <BrowserRouter basename={CASINO_TG_BASENAME}>
      <SessionProvider>
        <TelegramSession>
          <MiniAppRoutes />
          <WalletConfirmGate surface="casino" />
        </TelegramSession>
        <Toaster position="top-center" richColors theme="system" />
      </SessionProvider>
    </BrowserRouter>
  </React.StrictMode>,
);
