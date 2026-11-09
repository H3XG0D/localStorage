import { useEffect, useState } from "react";
import { Copy, Dice5, Loader2, Share2, Users, Wallet } from "lucide-react";
import { toast } from "sonner";
import { CabinetLayout } from "@/components/CabinetLayout";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { ApiError } from "@/lib/api";
import { CARD_WITHDRAW_PROMISE } from "@/lib/cardWithdrawCopy";
import { applyReferral, getReferral, referralWithdraw, type BalanceStats, type WithdrawMethod } from "@/lib/user";
import { formatMoney } from "@/lib/utils";
import {
  cryptoWithdrawBlocked,
  cryptoWithdrawBlockedMessage,
  payoutRailRemaining,
} from "@/casino/casinoWalletRules";

const CRYPTOS = ["usdt", "btc", "ltc", "trx"];
const NETWORKS: Record<string, string[]> = { usdt: ["TRC20", "ERC20", "BEP20"], btc: ["mainnet"], ltc: ["mainnet"], trx: ["mainnet"] };

export function CabinetReferral() {
  const [data, setData] = useState<BalanceStats | null>(null);
  const [loading, setLoading] = useState(true);

  const [applyToken, setApplyToken] = useState("");
  const [applying, setApplying] = useState(false);

  const [method, setMethod] = useState<WithdrawMethod>("card");
  const [amount, setAmount] = useState("");
  const [requisites, setRequisites] = useState("");
  const [crypto, setCrypto] = useState("usdt");
  const [network, setNetwork] = useState("TRC20");
  const [withdrawing, setWithdrawing] = useState(false);
  const remainingFiatOutRub = payoutRailRemaining(data?.payout_rail);
  const cryptoLocked = cryptoWithdrawBlocked(remainingFiatOutRub);

  useEffect(() => {
    if (cryptoLocked && method === "crypto") setMethod("card");
  }, [cryptoLocked, method]);

  async function reload() {
    const d = await getReferral().catch(() => null);
    if (d) setData(d);
  }

  useEffect(() => {
    getReferral()
      .then(setData)
      .catch(() => undefined)
      .finally(() => setLoading(false));
  }, []);

  const inviteLink = data?.web_invite_link || (data?.ref_token ? `${window.location.origin}/ref/${data.ref_token}` : "");

  function copy(text: string) {
    navigator.clipboard?.writeText(text).then(
      () => toast.success("Скопировано"),
      () => toast.error("Не удалось скопировать"),
    );
  }

  async function onApply() {
    if (!applyToken.trim()) return;
    setApplying(true);
    try {
      const r = await applyReferral(applyToken.trim());
      toast[r.applied ? "success" : "info"](r.applied ? "Реферер применён" : "Реферер уже назначен или недоступен");
      setApplyToken("");
      await reload();
    } catch (e) {
      toast.error(e instanceof ApiError ? e.message : "Не удалось применить");
    } finally {
      setApplying(false);
    }
  }

  async function onWithdraw() {
    if (data?.has_pending_withdrawal) return toast.info("У вас уже есть заявка на вывод");
    if (cryptoLocked && method === "crypto") {
      return toast.error(cryptoWithdrawBlockedMessage(remainingFiatOutRub));
    }
    if (Number(amount) <= 0) return toast.error("Укажите сумму");
    if (requisites.trim().length < 5) return toast.error("Укажите реквизиты");
    setWithdrawing(true);
    try {
      await referralWithdraw({
        amount_rub: Number(amount),
        method,
        requisites: requisites.trim(),
        crypto: method === "crypto" ? crypto : null,
        network: method === "crypto" && crypto === "usdt" ? network : null,
      });
      toast.success("Заявка на вывод создана");
      setAmount("");
      setRequisites("");
      await reload();
    } catch (e) {
      toast.error(e instanceof ApiError ? e.message : "Не удалось создать вывод");
    } finally {
      setWithdrawing(false);
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
            <h1 className="text-2xl font-bold tracking-tight">Реферальная программа</h1>
            <p className="mt-1 text-sm text-muted-foreground">Приглашайте друзей и получайте вознаграждение.</p>
          </div>

          <div className="grid gap-3 sm:grid-cols-3">
            <Stat label="Приглашено" value={String(data?.referred_count ?? 0)} icon={<Users className="size-4" />} />
            <Stat label="Оплачено заявок" value={String(data?.paid_orders_count ?? 0)} />
            <Stat label="Начислено, ₽" value={formatMoney(data?.referral_total_accrual_rub ?? 0)} mono />
          </div>

          {/* Casino earnings section */}
          {(data?.casino_total_rub ?? 0) > 0 && (
            <Card className="border-emerald-500/20 bg-emerald-500/5">
              <CardHeader>
                <div className="flex items-center gap-2">
                  <Dice5 className="size-5 text-emerald-500" />
                  <CardTitle className="text-emerald-500">Доход от казино</CardTitle>
                </div>
                <CardDescription>Реферальные комиссии от игр ваших рефералов</CardDescription>
              </CardHeader>
              <CardContent>
                <div className="grid gap-3 sm:grid-cols-3">
                  <div>
                    <div className="text-xs text-muted-foreground">Всего от казино</div>
                    <div className="mt-1 font-mono text-lg font-semibold text-emerald-500">
                      {formatMoney(data?.casino_total_rub ?? 0)} ₽
                    </div>
                  </div>
                  {(data?.casino_l1_rub ?? 0) > 0 && (
                    <div>
                      <div className="text-xs text-muted-foreground">Уровень 1</div>
                      <div className="mt-1 font-mono text-lg font-semibold">
                        {formatMoney(data?.casino_l1_rub ?? 0)} ₽
                      </div>
                    </div>
                  )}
                  {(data?.casino_l2_rub ?? 0) > 0 && (
                    <div>
                      <div className="text-xs text-muted-foreground">Уровень 2</div>
                      <div className="mt-1 font-mono text-lg font-semibold">
                        {formatMoney(data?.casino_l2_rub ?? 0)} ₽
                      </div>
                    </div>
                  )}
                </div>
              </CardContent>
            </Card>
          )}

          {/* invite link */}
          <Card>
            <CardHeader>
              <div className="flex items-center gap-2">
                <Share2 className="size-5" />
                <CardTitle>Ваша реферальная ссылка</CardTitle>
              </div>
              <CardDescription>Поделитесь ссылкой — бонус начислится за оплаченные заявки друзей и за их VPN.</CardDescription>
            </CardHeader>
            <CardContent className="space-y-3">
              <div className="flex gap-2">
                <Input readOnly value={inviteLink} className="font-mono text-xs" />
                <Button variant="outline" size="icon" aria-label="Копировать" onClick={() => copy(inviteLink)}>
                  <Copy className="size-4" />
                </Button>
              </div>
              {data?.telegram_link && (
                <div className="flex gap-2">
                  <Input readOnly value={data.telegram_link} className="font-mono text-xs" />
                  <Button variant="outline" size="icon" aria-label="Копировать Telegram" onClick={() => copy(data.telegram_link)}>
                    <Copy className="size-4" />
                  </Button>
                </div>
              )}
            </CardContent>
          </Card>

          {/* apply referrer */}
          <Card>
            <CardHeader>
              <CardTitle>Ввести код пригласившего</CardTitle>
              <CardDescription>Если вас пригласили — введите его код (один раз).</CardDescription>
            </CardHeader>
            <CardContent>
              <div className="flex gap-2">
                <Input value={applyToken} onChange={(e) => setApplyToken(e.target.value)} placeholder="Реф-код" className="font-mono" />
                <Button onClick={onApply} disabled={applying || !applyToken.trim()}>
                  {applying ? <Loader2 className="size-4 animate-spin" /> : "Применить"}
                </Button>
              </div>
            </CardContent>
          </Card>

          {/* withdraw */}
          <Card>
            <CardHeader>
              <div className="flex items-center gap-2">
                <Wallet className="size-5" />
                <CardTitle>Вывод средств</CardTitle>
              </div>
              <CardDescription>
                Доступно: <span className="font-mono text-foreground">{formatMoney(data?.available_rub ?? 0)} ₽</span>
                {data?.min_withdraw_card_rub ? ` · мин. по карте ${formatMoney(data.min_withdraw_card_rub)} ₽` : ""}
                {cryptoLocked ? ` · ${cryptoWithdrawBlockedMessage(remainingFiatOutRub)}` : ""}
              </CardDescription>
            </CardHeader>
            <CardContent className="space-y-3">
              <Tabs value={method} onValueChange={(v) => setMethod(v as WithdrawMethod)}>
                <TabsList className="grid w-full grid-cols-2">
                  <TabsTrigger value="card">На карту</TabsTrigger>
                  <TabsTrigger value="crypto" disabled={cryptoLocked}>
                    В крипте
                  </TabsTrigger>
                </TabsList>
              </Tabs>
              {cryptoLocked ? (
                <p className="text-sm text-muted-foreground">{cryptoWithdrawBlockedMessage(remainingFiatOutRub)}</p>
              ) : null}
              {method === "card" ? (
                <p className="text-sm text-muted-foreground">
                  {CARD_WITHDRAW_PROMISE}
                </p>
              ) : null}

              {method === "crypto" && (
                <div className="grid grid-cols-2 gap-2">
                  <div className="flex flex-col gap-2">
                    <Label>Актив</Label>
                    <Select value={crypto} onValueChange={setCrypto}>
                      <SelectTrigger><SelectValue /></SelectTrigger>
                      <SelectContent>
                        {CRYPTOS.map((c) => <SelectItem key={c} value={c}>{c.toUpperCase()}</SelectItem>)}
                      </SelectContent>
                    </Select>
                  </div>
                  {crypto === "usdt" && (
                    <div className="flex flex-col gap-2">
                      <Label>Сеть</Label>
                      <Select value={network} onValueChange={setNetwork}>
                        <SelectTrigger><SelectValue /></SelectTrigger>
                        <SelectContent>
                          {NETWORKS.usdt.map((n) => <SelectItem key={n} value={n}>{n}</SelectItem>)}
                        </SelectContent>
                      </Select>
                    </div>
                  )}
                </div>
              )}

              <div className="flex flex-col gap-2">
                <Label htmlFor="amount">Сумма, ₽</Label>
                <Input id="amount" inputMode="decimal" value={amount} onChange={(e) => setAmount(e.target.value)} className="font-mono" />
              </div>
              <div className="flex flex-col gap-2">
                <Label htmlFor="req">{method === "card" ? "Номер карты" : "Адрес кошелька"}</Label>
                <Input id="req" value={requisites} onChange={(e) => setRequisites(e.target.value)} className="font-mono" placeholder={method === "card" ? "0000 0000 0000 0000" : "Адрес получателя"} />
              </div>
              <Button className="w-full" onClick={onWithdraw} disabled={withdrawing || !!data?.has_pending_withdrawal || (cryptoLocked && method === "crypto")}>
                {withdrawing ? <Loader2 className="size-4 animate-spin" data-icon="inline-start" /> : null}
                {data?.has_pending_withdrawal ? "Заявка на вывод уже в обработке" : "Создать заявку на вывод"}
              </Button>
            </CardContent>
          </Card>
        </div>
      )}
    </CabinetLayout>
  );
}

function Stat({ label, value, mono, icon }: { label: string; value: string; mono?: boolean; icon?: React.ReactNode }) {
  return (
    <div className="rounded-xl border border-border bg-card p-4">
      <p className="flex items-center gap-1.5 text-xs text-muted-foreground">{icon}{label}</p>
      <p className={`mt-1 text-2xl font-semibold tracking-tight ${mono ? "font-mono" : ""}`}>{value}</p>
    </div>
  );
}
