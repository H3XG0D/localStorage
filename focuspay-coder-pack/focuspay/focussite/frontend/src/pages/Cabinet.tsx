import { useEffect, useState } from "react";
import { ArrowUpRight, Gift, Loader2, Wallet } from "lucide-react";
import { Link } from "react-router-dom";
import { toast } from "sonner";
import { CabinetLayout } from "@/components/CabinetLayout";
import { ReviewBonusCard } from "@/components/ReviewBonusCard";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { ApiError } from "@/lib/api";
import { STATUS_LABEL, parseCryptoSymbol } from "@/lib/orders";
import {
  getBalance,
  getMyOrders,
  getProfile,
  promoRedeemedText,
  redeemPromo,
  setCashbackOnNext,
  type BalanceStats,
  type HistoryOrder,
  type Profile,
} from "@/lib/user";
import { cn, formatCrypto, formatDate, formatMoney } from "@/lib/utils";

function statusTone(status: string): "muted" | "positive" | "warning" | "destructive" {
  if (["COMPLETED", "PAID"].includes(status)) return "positive";
  if (["FAILED", "CANCELED", "EXPIRED", "DISPUTE"].includes(status)) return "destructive";
  if (["AWAITING_CHECK", "PENDING", "OPERATOR_PENDING"].includes(status)) return "warning";
  return "muted";
}

export function Cabinet() {
  const [profile, setProfile] = useState<Profile | null>(null);
  const [balance, setBalance] = useState<BalanceStats | null>(null);
  const [orders, setOrders] = useState<HistoryOrder[]>([]);
  const [loading, setLoading] = useState(true);
  const [promo, setPromo] = useState("");
  const [redeeming, setRedeeming] = useState(false);
  const [togglingCashback, setTogglingCashback] = useState(false);

  async function reloadBalance() {
    const b = await getBalance().catch(() => null);
    if (b) setBalance(b);
  }

  useEffect(() => {
    Promise.allSettled([getProfile(), getBalance(), getMyOrders(20, 0)])
      .then(([p, b, o]) => {
        if (p.status === "fulfilled") setProfile(p.value);
        if (b.status === "fulfilled") setBalance(b.value);
        if (o.status === "fulfilled") setOrders(o.value.orders || []);
      })
      .finally(() => setLoading(false));
  }, []);

  async function onRedeem() {
    if (!promo.trim()) return;
    setRedeeming(true);
    try {
      const res = await redeemPromo(promo.trim());
      if (res.balance) setBalance(res.balance);
      else await reloadBalance();
      toast.success(promoRedeemedText(res));
      setPromo("");
    } catch (e) {
      toast.error(e instanceof ApiError ? e.message : "Не удалось активировать промокод");
    } finally {
      setRedeeming(false);
    }
  }

  async function onToggleCashback() {
    if (!balance) return;
    setTogglingCashback(true);
    const next = !balance.use_on_next;
    try {
      await setCashbackOnNext(next);
      setBalance({ ...balance, use_on_next: next });
      toast.success(next ? "Кэшбэк применится к следующей заявке" : "Кэшбэк отключён");
    } catch (e) {
      toast.error(e instanceof ApiError ? e.message : "Не удалось изменить настройку");
    } finally {
      setTogglingCashback(false);
    }
  }

  return (
    <CabinetLayout>
      {loading ? (
        <div className="flex justify-center py-24">
          <Loader2 className="size-6 animate-spin text-muted-foreground" />
        </div>
      ) : (
        <div className="space-y-6">
          <div>
            <h1 className="text-2xl font-bold tracking-tight">
              Привет, {profile?.user.display_name || profile?.user.username || "друг"}
            </h1>
            <p className="mt-1 text-sm text-muted-foreground">Ваши обмены и бонусы в одном месте.</p>
          </div>

          <ReviewBonusCard />

          {/* stat tiles */}
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
            <StatTile label="Всего заявок" value={String(profile?.stats.total_orders ?? 0)} />
            <StatTile label="Завершено" value={String(profile?.stats.completed_orders ?? 0)} />
            <StatTile label="Баланс, ₽" value={formatMoney(balance?.balance_rub ?? 0)} mono />
            <StatTile label="Доступно к выводу, ₽" value={formatMoney(balance?.available_rub ?? 0)} mono />
          </div>

          {/* balance + promo */}
          <div className="grid gap-4 lg:grid-cols-2">
            <Card>
              <CardHeader>
                <div className="flex items-center gap-2">
                  <Wallet className="size-5" />
                  <CardTitle>Бонусный баланс</CardTitle>
                </div>
                <CardDescription>Кэшбэк, промо и реферальные начисления.</CardDescription>
              </CardHeader>
              <CardContent className="space-y-3">
                <div className="grid grid-cols-3 gap-2 text-center">
                  <MiniStat label="Кэшбэк" value={balance?.cashback_rub ?? 0} />
                  <MiniStat label="Промо" value={balance?.promo_rub ?? 0} />
                  <MiniStat label="Рефералы" value={balance?.referral_rub ?? 0} />
                </div>
                <label className="flex items-center justify-between rounded-lg border border-border bg-muted/30 p-3">
                  <span className="text-sm">Использовать кэшбэк для следующей заявки</span>
                  <button
                    type="button"
                    role="switch"
                    aria-checked={!!balance?.use_on_next}
                    disabled={togglingCashback}
                    onClick={onToggleCashback}
                    className={cn(
                      "relative h-6 w-11 shrink-0 rounded-full transition-colors",
                      balance?.use_on_next ? "bg-foreground" : "bg-input",
                    )}
                  >
                    <span
                      className={cn(
                        "absolute top-0.5 size-5 rounded-full bg-background transition-transform",
                        balance?.use_on_next ? "translate-x-[22px]" : "translate-x-0.5",
                      )}
                    />
                  </button>
                </label>
                <Button variant="outline" className="w-full" asChild>
                  <Link to="/cabinet/referral">
                    Вывести средства
                    <ArrowUpRight data-icon="inline-end" />
                  </Link>
                </Button>
              </CardContent>
            </Card>

            <Card>
              <CardHeader>
                <div className="flex items-center gap-2">
                  <Gift className="size-5" />
                  <CardTitle>Промокод</CardTitle>
                </div>
                <CardDescription>На баланс или скидка на обмен от 3 000 ₽.</CardDescription>
              </CardHeader>
              <CardContent className="space-y-3">
                <div className="flex gap-2">
                  <Input
                    value={promo}
                    onChange={(e) => setPromo(e.target.value.toUpperCase())}
                    placeholder="Введите код"
                    className="font-mono uppercase"
                    onKeyDown={(e) => e.key === "Enter" && onRedeem()}
                  />
                  <Button onClick={onRedeem} disabled={redeeming || !promo.trim()}>
                    {redeeming ? <Loader2 className="size-4 animate-spin" /> : "Применить"}
                  </Button>
                </div>
                <p className="text-xs text-muted-foreground">
                  Сэкономлено с бонусами: <span className="font-mono text-foreground">{formatMoney(balance?.saved_rub ?? 0)} ₽</span>
                </p>
              </CardContent>
            </Card>
          </div>

          {/* order history */}
          <Card>
            <CardHeader>
              <CardTitle>История заявок</CardTitle>
              <CardDescription>Последние операции обмена.</CardDescription>
            </CardHeader>
            <CardContent>
              {orders.length === 0 ? (
                <div className="py-8 text-center">
                  <p className="text-sm text-muted-foreground">Заявок пока нет.</p>
                  <Button className="mt-4" asChild>
                    <Link to="/exchange">Создать первую заявку</Link>
                  </Button>
                </div>
              ) : (
                <div className="divide-y divide-border">
                  {orders.map((o) => {
                    const c = parseCryptoSymbol(o.crypto);
                    return (
                      <Link
                        key={o.order_id}
                        to={`/exchange/order/${o.order_id}`}
                        className="flex items-center justify-between gap-3 py-3 transition-colors hover:bg-muted/40"
                      >
                        <div className="min-w-0">
                          <p className="truncate font-mono text-sm font-medium">#{o.order_id}</p>
                          <p className="text-xs text-muted-foreground">
                            {o.direction === "buy" ? "Покупка" : "Продажа"} {c.base} · {formatDate(o.created_at)}
                          </p>
                        </div>
                        <div className="flex items-center gap-3">
                          <div className="text-right">
                            <p className="font-mono text-sm">{formatMoney(o.fiat_amount)} ₽</p>
                            <p className="font-mono text-xs text-muted-foreground">{formatCrypto(o.crypto_amount)} {c.base}</p>
                          </div>
                          <Badge variant={statusTone(o.status)}>{o.status_label || STATUS_LABEL[o.status] || o.status}</Badge>
                        </div>
                      </Link>
                    );
                  })}
                </div>
              )}
            </CardContent>
          </Card>
        </div>
      )}
    </CabinetLayout>
  );
}

function StatTile({ label, value, mono }: { label: string; value: string; mono?: boolean }) {
  return (
    <div className="rounded-xl border border-border bg-card p-4">
      <p className="text-xs text-muted-foreground">{label}</p>
      <p className={cn("mt-1 text-2xl font-semibold tracking-tight", mono && "font-mono")}>{value}</p>
    </div>
  );
}

function MiniStat({ label, value }: { label: string; value: number }) {
  return (
    <div className="rounded-lg border border-border bg-muted/30 p-2">
      <p className="text-[10px] uppercase tracking-wide text-muted-foreground">{label}</p>
      <p className="mt-0.5 font-mono text-sm font-medium">{formatMoney(value)} ₽</p>
    </div>
  );
}
