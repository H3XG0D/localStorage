import { useEffect, useRef } from "react";
import { toast } from "sonner";
import type { CasinoV2TableView } from "@/lib/public";
import { haptic } from "./telegram";
import { CASINO_BALANCE_EVENT } from "./gameCatalog";
import { v2MyRoundResult, v2NoticeKey } from "./v2RoundResult";

export function useV2RoundNotice(table: CasinoV2TableView | null) {
  const seen = useRef("");
  useEffect(() => {
    if (!table || table.status !== "finished") return;
    const key = v2NoticeKey(table);
    if (seen.current === key) return;
    window.dispatchEvent(new Event(CASINO_BALANCE_EVENT));
    try {
      if (sessionStorage.getItem(key)) {
        seen.current = key;
        return;
      }
      sessionStorage.setItem(key, "1");
    } catch {
      /* private mode */
    }
    seen.current = key;
    const result = v2MyRoundResult(table);
    if (!result) return;
    haptic(result.kind === "win" ? "win" : result.kind === "loss" ? "lose" : "selection");
    if (result.kind === "win") toast.success(`${result.title} ${result.signedLabel}`);
    else if (result.kind === "loss") toast.error(`${result.title} ${result.signedLabel}`);
    else toast.info(`${result.title} ${result.signedLabel}`);
  }, [table]);
}
