import React from "react";
import ReactDOM from "react-dom/client";
import { BrowserRouter } from "react-router-dom";
import { Toaster } from "sonner";
import App from "./App";
import { SessionProvider } from "@/lib/session";
import { ThemeProvider } from "@/lib/theme";
import { DevJumpBar } from "@/lib/DevJumpBar";
import "./index.css";

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <ThemeProvider>
      <BrowserRouter>
        <SessionProvider>
          <DevJumpBar />
          <App />
          <Toaster position="bottom-right" richColors theme="system" />
        </SessionProvider>
      </BrowserRouter>
    </ThemeProvider>
  </React.StrictMode>,
);
