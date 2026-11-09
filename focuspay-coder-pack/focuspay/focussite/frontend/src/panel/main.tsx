import React from "react";
import ReactDOM from "react-dom/client";
import { BrowserRouter } from "react-router-dom";
import { Toaster } from "sonner";
import { PanelApp } from "@/panel/PanelApp";
import { DevJumpBar } from "@/lib/DevJumpBar";
import "@/panel/panel.css";

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <BrowserRouter>
      <DevJumpBar />
      <PanelApp />
      <Toaster position="bottom-right" theme="dark" richColors />
    </BrowserRouter>
  </React.StrictMode>,
);
