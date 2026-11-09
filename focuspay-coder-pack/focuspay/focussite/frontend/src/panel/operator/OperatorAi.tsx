import { useEffect } from "react";
import { Navigate } from "react-router-dom";
import { openOpsAi } from "@/panel/operator/OperatorAiWidget";

/** Старый /ops/ai → открываем плавающий виджет и уходим на дашборд. */
export function OperatorAi() {
  useEffect(() => {
    openOpsAi();
  }, []);
  return <Navigate to="/ops" replace />;
}
