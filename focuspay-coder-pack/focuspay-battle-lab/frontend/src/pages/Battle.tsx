import { useCallback, useEffect, useState } from "react";
import {
  fetchHistory,
  getLabUser,
  placeBet,
  setLabUser,
} from "../api/client";
import type { HistoryItem } from "../api/client";
import { useBattlePoll } from "../hooks/useBattlePoll";

const PLAYERS = ["alice", "bob", "carol"] as const;

const fmt = (n: number) =>
  n.toLocaleString("ru-RU", { maximumFractionDigits: 0 });

export default function Battle() {
  const [user, setUser] = useState(getLabUser());
  const [history, setHistory] = useState<HistoryItem[]>([]);
  const [betting, setBetting] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);
  const { data, error, loading, refresh, justResolved, clearResolved } =
    useBattlePoll(2000);

  const loadHistory = useCallback(async () => {
    try {
      setHistory(await fetchHistory(20));
    } catch {
      /* ignore */
    }
  }, []);

  useEffect(() => {
    loadHistory();
    const id = setInterval(loadHistory, 5000);
    return () => clearInterval(id);
  }, [loadHistory]);

  useEffect(() => {
    if (justResolved) {
      const t = setTimeout(() => {
        clearResolved();
        loadHistory();
      }, 3500);
      return () => clearTimeout(t);
    }
  }, [justResolved, clearResolved, loadHistory]);

  const onUserChange = (id: string) => {
    setLabUser(id);
    setUser(id);
    refresh();
  };

  const bet = async (side: "red" | "blue", amount: number) => {
    setBetting(true);
    setMsg(null);
    try {
      await placeBet(side, amount);
      await refresh();
    } catch (e: unknown) {
      const detail =
        (e as { response?: { data?: { detail?: string } } })?.response?.data
          ?.detail ?? "Ошибка ставки";
      setMsg(String(detail));
    } finally {
      setBetting(false);
    }
  };

  const allIn = (side: "red" | "blue") => {
    if (!data) return;
    const avail = Math.floor(data.balance_available);
    if (avail >= 50) bet(side, Math.min(avail, 5000));
  };

  const locked = data ? data.status !== "open" || data.seconds_left <= 3 : false;

  return (
    <div className="min-h-screen bg-zinc-950 text-white px-4 py-6 max-w-md mx-auto">
      <header className="flex items-center justify-between mb-6">
        <div>
          <p className="text-xs text-zinc-500 uppercase tracking-wider">Баланс</p>
          <p className="text-2xl font-bold tabular-nums">
            {data ? fmt(data.balance_available) : "—"} ₽
          </p>
        </div>
        <select
          value={user}
          onChange={(e) => onUserChange(e.target.value)}
          className="bg-zinc-800 border border-zinc-700 rounded-lg px-3 py-2 text-sm"
        >
          {PLAYERS.map((p) => (
            <option key={p} value={p}>
              {p}
            </option>
          ))}
        </select>
      </header>

      {loading && !data && (
        <p className="text-center text-zinc-500">Загрузка…</p>
      )}
      {error && <p className="text-red-400 text-sm mb-4">{error}</p>}
      {msg && <p className="text-amber-400 text-sm mb-4">{msg}</p>}

      {data && (
        <>
          <div
            className={`relative rounded-2xl border border-zinc-800 bg-zinc-900 p-6 mb-6 text-center ${
              justResolved ? "resolve-flash" : ""
            }`}
          >
            <p className="text-5xl font-black tabular-nums mb-2">
              {data.seconds_left}
              <span className="text-lg text-zinc-500 font-normal"> сек</span>
            </p>
            <p className="text-sm text-zinc-500 mb-4">
              Раунд #{data.round_id} · банк {fmt(data.bank)} ₽
            </p>

            <div className="flex justify-center gap-4 text-xl font-bold mb-2">
              <span className="text-red-400">🔴 {data.red_pct}%</span>
              <span className="text-zinc-600">|</span>
              <span className="text-blue-400">🔵 {data.blue_pct}%</span>
            </div>
            <div className="flex justify-center gap-6 text-sm text-zinc-400">
              <span>{fmt(data.red_total)} ₽</span>
              <span>{fmt(data.blue_total)} ₽</span>
            </div>

            {data.my_bet && (
              <p className="mt-4 text-sm text-zinc-300">
                Ваша ставка:{" "}
                {data.my_bet.side === "red" ? "🔴" : "🔵"}{" "}
                {fmt(data.my_bet.amount)} ₽
              </p>
            )}

            {justResolved && (
              <div className="resolve-overlay">
                <span className="resolve-pulse">⚡</span>
                {justResolved.delta !== null && (
                  <p
                    className={
                      justResolved.delta >= 0 ? "text-green-400" : "text-red-400"
                    }
                  >
                    {justResolved.delta >= 0 ? "+" : ""}
                    {fmt(justResolved.delta)} ₽
                  </p>
                )}
              </div>
            )}
          </div>

          <div className="grid grid-cols-3 gap-2 mb-2">
            {[100, 500].map((amt) => (
              <button
                key={`r${amt}`}
                type="button"
                disabled={locked || betting}
                onClick={() => bet("red", amt)}
                className="btn-red"
              >
                🔴 {amt}
              </button>
            ))}
            <button
              type="button"
              disabled={locked || betting}
              onClick={() => allIn("red")}
              className="btn-red"
            >
              🔴 ALL
            </button>
          </div>
          <div className="grid grid-cols-3 gap-2 mb-8">
            {[100, 500].map((amt) => (
              <button
                key={`b${amt}`}
                type="button"
                disabled={locked || betting}
                onClick={() => bet("blue", amt)}
                className="btn-blue"
              >
                🔵 {amt}
              </button>
            ))}
            <button
              type="button"
              disabled={locked || betting}
              onClick={() => allIn("blue")}
              className="btn-blue"
            >
              🔵 ALL
            </button>
          </div>

          {locked && (
            <p className="text-center text-amber-500 text-sm mb-6">
              Ставки закрыты
            </p>
          )}
        </>
      )}

      <section>
        <h2 className="text-sm font-semibold text-zinc-500 uppercase mb-3">
          История
        </h2>
        <ul className="space-y-2">
          {history.map((h) => (
            <li
              key={h.round_id}
              className="flex justify-between items-center bg-zinc-900 rounded-lg px-3 py-2 text-sm"
            >
              <span>#{h.round_id}</span>
              <span>
                {h.winner === "red"
                  ? "🔴"
                  : h.winner === "blue"
                    ? "🔵"
                    : "↩ refund"}
              </span>
              <span className="text-zinc-500 tabular-nums">
                {fmt(h.red_total)} / {fmt(h.blue_total)}
              </span>
            </li>
          ))}
          {history.length === 0 && (
            <li className="text-zinc-600 text-sm">Пока пусто</li>
          )}
        </ul>
      </section>
    </div>
  );
}
