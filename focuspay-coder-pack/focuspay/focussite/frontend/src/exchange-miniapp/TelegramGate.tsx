import { useEffect, useRef, useState, type ReactNode } from "react";
import { api } from "@/lib/api";
import type { LoginSuccess } from "@/lib/auth";
import { useSession } from "@/lib/session";
import { PREVIEW } from "./preview";
import { getTelegramInitData, getTelegramUserId } from "./telegram";

let inFlight: Promise<LoginSuccess> | null = null;
let inFlightKey = "";

export function TelegramGate({ children }: { children: ReactNode }) {
  const { adopt, loading, isAuthed } = useSession();
  const initData = getTelegramInitData();
  const tgUserId = getTelegramUserId();
  const [verified, setVerified] = useState(false);
  const [error, setError] = useState("");
  const [attempt, setAttempt] = useState(0);
  const lastTgId = useRef<number | null>(null);

  useEffect(() => {
    if (PREVIEW || !initData || loading) return;
    if (tgUserId !== null && lastTgId.current !== null && tgUserId !== lastTgId.current) {
      setVerified(false);
    }
    lastTgId.current = tgUserId;
    if (isAuthed && verified) return;
    if (verified) return;
    let alive = true;
    setError("");
    const key = `${tgUserId ?? "unknown"}:${initData.slice(-16)}`;
    if (!inFlight || inFlightKey !== key) {
      inFlightKey = key;
      inFlight = api<LoginSuccess>("/auth/exchange/telegram-miniapp", {
        method: "POST",
        scope: null,
        body: { init_data: initData },
      }).finally(() => {
        if (inFlightKey === key) {
          inFlight = null;
          inFlightKey = "";
        }
      });
    }
    void inFlight.then((result) => {
      if (alive) {
        adopt(result);
        setVerified(true);
      }
    }).catch((err: unknown) => {
      if (!alive) return;
      setError(err instanceof Error && err.message ? err.message : "Не удалось войти через Telegram");
    });
    return () => {
      alive = false;
    };
  }, [initData, tgUserId, loading, verified, attempt, adopt, isAuthed]);

  if (PREVIEW) return children;

  if (!initData) {
    return (
      <main className="ex-app">
        <div className="ex-scroll flex flex-col justify-center">
          <h1 className="text-[22px] font-bold tracking-tight">FocusPay</h1>
          <p className="mt-2 text-sm leading-6 text-muted-foreground">
            Откройте приложение кнопкой «Приложение» в Telegram-боте. В обычном браузере вход недоступен.
          </p>
        </div>
      </main>
    );
  }

  if (!verified) {
    return (
      <main className="ex-app">
        <div className="ex-scroll flex flex-col justify-center">
          <p className="text-sm leading-6">{error || "Входим через Telegram…"}</p>
          {error ? (
            <button type="button" className="mt-4 h-12 rounded-xl bg-primary text-sm font-semibold text-primary-foreground" onClick={() => setAttempt((value) => value + 1)}>
              Повторить вход
            </button>
          ) : null}
        </div>
      </main>
    );
  }

  return children;
}
