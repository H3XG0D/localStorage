import { useEffect, useRef, useState } from "react";
import { Loader2, Sparkles, Timer, Trophy } from "lucide-react";
import { toast } from "sonner";
import { CabinetLayout } from "@/components/CabinetLayout";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { ApiError } from "@/lib/api";
import {
  battleBet,
  battleCurrent,
  battleEnabled,
  battleHistory,
  type BattleHistoryItem,
  type BattleRound,
  type BattleSide,
} from "@/lib/user";
import { cn, formatMoney } from "@/lib/utils";

const POLL_MS = 2000;

export function CabinetBattle() {
  const [enabled, setEnabled] = useState<boolean | null>(null);
  const [round, setRound] = useState<BattleRound | null>(null);
  const [history, setHistory] = useState<BattleHistoryItem[]>([]);
  const [amount, setAmount] = useState("100");
  const [side, setSide] = useState<BattleSide>("red");
  const [betting, setBetting] = useState(false);
  const timer = useRef<number | null>(null);

  useEffect(() => {
    let alive = true;
    battleEnabled()
      .then((r) => {
        if (!alive) return;
        setEnabled(r.enabled);
        if (r.enabled) {
          const poll = () => battleCurrent().then((c) => alive && setRound(c)).catch(() => undefined);
          poll();
          battleHistory(20).then((h) => alive && setHistory(h)).catch(() => undefined);
          timer.current = window.setInterval(poll, POLL_MS);
        }
      })
      .catch(() => alive && setEnabled(false));
    return () => {
      alive = false;
      if (timer.current) window.clearInterval(timer.current);
    };
  }, []);

  async function placeBet() {
    if (Number(amount) <= 0) return toast.error("Укажите сумму ставки");
    setBetting(true);
    try {
      const updated = await battleBet(side, Number(amount));
      setRound(updated);
      toast.success("Ставка принята");
    } catch (e) {
      toast.error(e instanceof ApiError ? e.message : "Не удалось сделать ставку");
    } finally {
      setBetting(false);
    }
  }

  return (
    <CabinetLayout>
      <div className="space-y-6">
        <div>
          <h1 className="flex items-center gap-2 text-2xl font-bold tracking-tight">
            <Sparkles className="size-6" />
            FocusLucky
          </h1>
          <p className="mt-1 text-sm text-muted-foreground">Ставьте бонусным балансом на исход раунда.</p>
        </div>

        {enabled === null ? (
          <div className="flex justify-center py-24">
            <Loader2 className="size-6 animate-spin text-muted-foreground" />
          </div>
        ) : !enabled ? (
          <Card>
            <CardContent className="py-12 text-center">
              <p className="text-sm text-muted-foreground">Игра временно недоступна. Загляните позже.</p>
            </CardContent>
          </Card>
        ) : (
          <>
            {/* round */}
            <Card>
              <CardHeader>
                <div className="flex items-center justify-between">
                  <CardTitle>Раунд #{round?.round_id ?? "…"}</CardTitle>
                  <span className="inline-flex items-center gap-1 font-mono text-sm text-muted-foreground">
                    <Timer className="size-4" />
                    {round ? `${round.seconds_left}s` : "…"}
                  </span>
                </div>
                <CardDescription>
                  Банк: <span className="font-mono text-foreground">{formatMoney(round?.bank ?? 0)} ₽</span>
                  {" · "}Доступно: <span className="font-mono text-foreground">{formatMoney(round?.balance_available ?? 0)} ₽</span>
                </CardDescription>
              </CardHeader>
              <CardContent className="space-y-4">
                {/* bar */}
                <div className="flex h-3 overflow-hidden rounded-full border border-border">
                  <div className="bg-foreground/80" style={{ width: `${round?.red_pct ?? 50}%` }} />
                  <div className="bg-muted-foreground/40" style={{ width: `${round?.blue_pct ?? 50}%` }} />
                </div>
                <div className="grid grid-cols-2 gap-3">
                  {(["red", "blue"] as BattleSide[]).map((s) => {
                    const isRed = s === "red";
                    const total = isRed ? round?.red_total : round?.blue_total;
                    const pct = isRed ? round?.red_pct : round?.blue_pct;
                    return (
                      <button
                        key={s}
                        type="button"
                        onClick={() => setSide(s)}
                        className={cn(
                          "flex flex-col items-start rounded-xl border p-4 text-left transition-colors active:scale-[0.99]",
                          side === s ? "border-foreground bg-muted/60" : "border-border hover:bg-muted/40",
                        )}
                      >
                        <span className="text-sm font-semibold">{isRed ? "Красная" : "Синяя"} сторона</span>
                        <span className="mt-1 font-mono text-lg">{Math.round(pct ?? 50)}%</span>
                        <span className="text-xs text-muted-foreground">{formatMoney(total ?? 0)} ₽ в ставках</span>
                      </button>
                    );
                  })}
                </div>

                {round?.my_bet && (
                  <div className="rounded-lg border border-border bg-muted/30 p-3 text-sm">
                    Ваша ставка: <span className="font-medium">{round.my_bet.side === "red" ? "Красная" : "Синяя"}</span> ·{" "}
                    <span className="font-mono">{formatMoney(round.my_bet.amount)} ₽</span>
                  </div>
                )}

                <div className="flex gap-2">
                  <Input
                    inputMode="decimal"
                    value={amount}
                    onChange={(e) => setAmount(e.target.value)}
                    className="font-mono"
                    placeholder="Сумма ставки, ₽"
                  />
                  <Button onClick={placeBet} disabled={betting || round?.status !== "open"}>
                    {betting ? <Loader2 className="size-4 animate-spin" /> : "Поставить"}
                  </Button>
                </div>
                {round && round.status !== "open" && (
                  <p className="text-center text-xs text-muted-foreground">Приём ставок закрыт — ждём следующий раунд.</p>
                )}
              </CardContent>
            </Card>

            {/* history */}
            {history.length > 0 && (
              <Card>
                <CardHeader>
                  <div className="flex items-center gap-2">
                    <Trophy className="size-5" />
                    <CardTitle>История раундов</CardTitle>
                  </div>
                </CardHeader>
                <CardContent>
                  <div className="divide-y divide-border">
                    {history.map((h) => (
                      <div key={h.round_id} className="flex items-center justify-between py-2 text-sm">
                        <span className="font-mono text-muted-foreground">#{h.round_id}</span>
                        <span className="font-medium">
                          {h.winner === "red" ? "🔴 Красная" : h.winner === "blue" ? "🔵 Синяя" : "—"}
                        </span>
                        <span className="font-mono text-xs text-muted-foreground">
                          {formatMoney(h.red_total + h.blue_total)} ₽
                        </span>
                      </div>
                    ))}
                  </div>
                </CardContent>
              </Card>
            )}
          </>
        )}
      </div>
    </CabinetLayout>
  );
}
