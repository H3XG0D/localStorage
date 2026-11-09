import { useEffect, useRef, useState, type ReactNode } from "react";
import { api } from "@/lib/api";
import type { LoginSuccess } from "@/lib/auth";
import { useSession } from "@/lib/session";
import { getTelegramInitData, getTelegramUserId } from "./telegram";

let inFlight: Promise<LoginSuccess> | null = null;
let inFlightKey = "";

export function TelegramSession({ children }: { children: ReactNode }) {
  const { adopt, loading, isAuthed, refresh, user } = useSession();
  const initData = getTelegramInitData();
  const tgUserId = getTelegramUserId();
  const [verified, setVerified] = useState(false);
  const [error, setError] = useState("");
  const [attempt, setAttempt] = useState(0);
  const lastTgId = useRef<number | null>(null);

  useEffect(() => {
    if (!initData || loading) return;
    // Telegram identity changed (another account opened the Mini App):
    // force re-verification even if a session already exists.
    if (tgUserId !== null && lastTgId.current !== null && tgUserId !== lastTgId.current) {
      setVerified(false);
    }
    lastTgId.current = tgUserId;
    // The stored session already belongs to this Telegram user — nothing to do.
    if (isAuthed && verified) return;
    if (isAuthed && !verified && user?.telegram_id === tgUserId && tgUserId !== null) {
      void refresh().then(() => setVerified(true));
      return;
    }
    if (verified) return;
    let alive = true;
    setError("");
    const key = `${tgUserId ?? "unknown"}:${initData.slice(-16)}`;
    if (!inFlight || inFlightKey !== key) {
      inFlightKey = key;
      inFlight = api<LoginSuccess>("/auth/casino/telegram-miniapp", {
        method: "POST", scope: null, body: { init_data: initData },
      }).finally(() => {
        if (inFlightKey === key) {
          inFlight = null;
          inFlightKey = "";
        }
      });
    }
    const current = inFlight;
    void current.then((result) => {
      if (alive) { adopt(result); setVerified(true); }
    }).catch((err: unknown) => {
      if (!alive) return;
      // Show the backend detail as-is: signature mismatch and stale auth_date
      // are different problems ("Некорректная подпись" = wrong bot token on
      // the server, stale = reopen). Never mask it with a generic text.
      setError(err instanceof Error && err.message ? err.message : "Не удалось войти через Telegram");
    });
    return () => { alive = false; };
  }, [initData, tgUserId, loading, verified, attempt, adopt, isAuthed, refresh, user?.telegram_id]);

  if (!initData) {
    return (
      <main className="casino-shell" aria-live="polite">
        <p>Откройте казино из Telegram-бота — в браузере вход через Mini App недоступен.</p>
      </main>
    );
  }
  if (!verified) return (
    <main className="casino-shell" aria-live="polite">
      <p>{error || "Входим через Telegram…"}</p>
      {error && <button type="button" onClick={() => setAttempt((value) => value + 1)}>Повторить вход</button>}
    </main>
  );
  return children;
}
