import { useEffect, useMemo, useRef, useState } from "react";
import { AnimatePresence, motion } from "framer-motion";
import { ArrowRight, Info, Loader2, LogIn } from "lucide-react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { toast } from "sonner";
import { PublicHeader } from "@/components/PublicHeader";
import { StatusDot } from "@/components/StatusDot";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { ApiError } from "@/lib/api";
import { quoteBuyFromRub } from "@/lib/buyQuote";
import { CRYPTO_META, getRates, type CryptoId, type RatesResponse } from "@/lib/public";
import { createOrder, isRequisiteRetry, payinFit, payinPreview, retryRequisiteRequest, roundUpOffer, type Direction, type PayinFitPreview, type RequisiteRetryDraft, type SubToken } from "@/lib/orders";
import { useSession } from "@/lib/session";
import { cn, formatMoney } from "@/lib/utils";

const ASSETS: CryptoId[] = ["usdt", "btc", "ltc", "trx"];
const RATES_POLL_MS = 30_000;
const SUB_TOKENS: { value: SubToken; label: string; hint: string }[] = [
  { value: "SBPRUB", label: "СБП", hint: "Система быстрых платежей" },
  { value: "CARDRUB", label: "Карта", hint: "Перевод на карту банка" },
];

export function Exchange() {
  const [params] = useSearchParams();
  const navigate = useNavigate();
  const { isAuthed, loading: sessionLoading } = useSession();

  const [rates, setRates] = useState<RatesResponse | null>(null);
  const [direction, setDirection] = useState<Direction>((params.get("direction") as Direction) || "buy");
  const [asset, setAsset] = useState<CryptoId>((params.get("asset") as CryptoId) || "usdt");
  const [network, setNetwork] = useState<string>("TRC20");
  const [amount, setAmount] = useState(params.get("amount") || "50000");
  const [subToken, setSubToken] = useState<SubToken>("SBPRUB");
  const [requisites, setRequisites] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [preview, setPreview] = useState<string | null>(null);
  const [fit, setFit] = useState<PayinFitPreview | null>(null);
  const [retry, setRetry] = useState<RequisiteRetryDraft | null>(null);
  const [retrying, setRetrying] = useState(false);
  const timer = useRef<number | null>(null);

  const meta = CRYPTO_META[asset];
  const networks = meta.networks;
  const isUsdt = asset === "usdt";
  const rate = rates?.rates?.[asset];
  const limits = rates?.public_tariffs?.buy_limits;
  const buyQuote = useMemo(() => {
    if (direction !== "buy") return null;
    return quoteBuyFromRub(Number(amount || 0), rate, rates?.public_tariffs?.buy_spread_auto_tiers);
  }, [amount, direction, rate, rates?.public_tariffs?.buy_spread_auto_tiers]);
  const price = direction === "buy"
    ? (rate && buyQuote ? Number(rate.market) * (1 + buyQuote.pct / 100) : rate?.buy)
    : rate?.sell;
  const result = useMemo(() => {
    if (direction === "buy") return buyQuote?.crypto ?? 0;
    const p = Number(price || 0);
    if (!p) return 0;
    return Number(amount || 0) * p;
  }, [amount, buyQuote, direction, price]);

  useEffect(() => {
    let alive = true;
    const load = () => getRates().then((r) => alive && setRates(r)).catch(() => undefined);
    load();
    timer.current = window.setInterval(load, RATES_POLL_MS);
    return () => {
      alive = false;
      if (timer.current) window.clearInterval(timer.current);
    };
  }, []);

  // Reset network default when switching to USDT.
  useEffect(() => {
    if (isUsdt && !networks.includes(network)) setNetwork(networks[0]);
  }, [isUsdt, networks, network]);

  useEffect(() => {
    const id = window.setInterval(() => {
      setRetry((current) => {
        if (!current?.retry_after_sec) return current;
        return { ...current, retry_after_sec: current.retry_after_sec - 1 };
      });
    }, 1000);
    return () => window.clearInterval(id);
  }, []);

  // Debounced pay-in preview for buy orders.
  useEffect(() => {
    if (direction !== "buy") {
      setPreview(null);
      setFit(null);
      return;
    }
    const pay = buyQuote?.pay ?? 0;
    if (!pay || pay <= 0 || !isAuthed) {
      setPreview(null);
      setFit(null);
      return;
    }
    const handle = window.setTimeout(() => {
      payinPreview(pay, subToken)
        .then((p) => setPreview(p.mode === "reject" ? p.message || "Нет реквизитов на эту сумму." : null))
        .catch(() => setPreview(null));
      payinFit(pay, subToken)
        .then((next) => setFit(next))
        .catch(() => setFit(null));
    }, 400);
    return () => window.clearTimeout(handle);
  }, [buyQuote?.pay, subToken, direction, isAuthed]);

  const requisitesLabel = direction === "buy" ? `Кошелёк ${meta.label} для зачисления` : "Реквизиты для получения рублей (карта/СБП)";
  const requisitesPlaceholder =
    direction === "buy" ? `Адрес ${meta.label}${isUsdt ? ` (${network})` : ""}` : "Номер карты или телефон для СБП";

  const offer = roundUpOffer(fit);

  async function submit(acceptRoundUp = false) {
    if (!isAuthed) {
      toast.info("Войдите, чтобы оформить обмен");
      navigate("/login", { state: { from: "/exchange", direction, asset, amount } });
      return;
    }
    if (!requisites.trim()) {
      toast.error(direction === "buy" ? "Укажите кошелёк для зачисления" : "Укажите реквизиты для получения");
      return;
    }
    if (direction === "buy" && !buyQuote) {
      toast.error("Курс CoinGecko временно недоступен. Попробуйте позже.");
      return;
    }
    setSubmitting(true);
    try {
      const order = await createOrder({
        direction,
        crypto: asset,
        network: isUsdt ? network : null,
        fiat_amount: Number(amount),
        requisites: requisites.trim(),
        sub_token: direction === "buy" ? subToken : null,
        payin_round_up: acceptRoundUp || offer?.mode === "silent",
      });
      if (isRequisiteRetry(order)) {
        setRetry(order);
        toast.info(order.message || "Запрос реквизитов сохранён на 30 минут");
        return;
      }
      setRetry(null);
      toast.success("Заявка создана");
      navigate(`/exchange/order/${order.order_id}`);
    } catch (e) {
      const msg = e instanceof ApiError ? e.message : "Не удалось создать заявку";
      // 409 = active order already exists — extract its id and route there.
      if (e instanceof ApiError && e.status === 409) {
        const m = /#?([A-Za-z0-9]{6,})/.exec(msg);
        toast.info(msg);
        if (m) navigate(`/exchange/order/${m[1]}`);
      } else {
        toast.error(msg);
      }
    } finally {
      setSubmitting(false);
    }
  }

  async function repeatRequisites() {
    setRetrying(true);
    try {
      const order = await retryRequisiteRequest();
      if (isRequisiteRetry(order)) {
        setRetry(order);
        toast.info(order.message || "Реквизитов всё ещё нет");
        return;
      }
      setRetry(null);
      toast.success("Заявка создана");
      navigate(`/exchange/order/${order.order_id}`);
    } catch (e) {
      toast.error(e instanceof ApiError ? e.message : "Не удалось повторить запрос");
    } finally {
      setRetrying(false);
    }
  }

  return (
    <div className="min-h-screen bg-background">
      <PublicHeader back={{ to: "/", label: "На главную" }} />
      <main className="mx-auto max-w-2xl px-4 py-10 sm:px-6 sm:py-16 lg:px-8">
        <motion.div initial={{ opacity: 0, y: 16 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.4 }}>
          <div className="mb-6">
            <h1 className="text-3xl font-bold tracking-tight sm:text-4xl">Обмен криптовалюты</h1>
            <p className="mt-2 text-sm leading-6 text-muted-foreground">
              Прозрачный расчёт по актуальному курсу. Реквизиты вы увидите после создания заявки.
            </p>
          </div>

          <Card className="overflow-hidden shadow-xl shadow-foreground/5">
            <CardHeader className="border-b border-border bg-muted/40 pb-4">
              <div className="flex items-center justify-between gap-3">
                <div>
                  <CardTitle>Параметры обмена</CardTitle>
                  <CardDescription className="mt-1">Курс обновляется автоматически</CardDescription>
                </div>
                <StatusDot label={rates ? "Курс актуален" : "Загрузка…"} tone={rates ? "positive" : "neutral"} />
              </div>
              <Tabs value={direction} onValueChange={(v) => setDirection(v as Direction)} className="mt-3">
                <TabsList className="grid w-full grid-cols-2">
                  <TabsTrigger value="buy">Покупаю крипту</TabsTrigger>
                  <TabsTrigger value="sell">Продаю крипту</TabsTrigger>
                </TabsList>
              </Tabs>
            </CardHeader>

            <CardContent className="flex flex-col gap-4 pt-5">
              {/* asset + network */}
              <div className={cn("grid gap-3", isUsdt ? "sm:grid-cols-2" : "grid-cols-1")}>
                <div className="flex flex-col gap-2">
                  <Label htmlFor="asset">Актив</Label>
                  <Select value={asset} onValueChange={(v) => setAsset(v as CryptoId)}>
                    <SelectTrigger id="asset">
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      {ASSETS.map((id) => (
                        <SelectItem key={id} value={id}>
                          {CRYPTO_META[id].label}
                          <span className="ml-1 text-muted-foreground">· {CRYPTO_META[id].detail}</span>
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </div>
                {isUsdt && (
                  <div className="flex flex-col gap-2">
                    <Label htmlFor="network">Сеть</Label>
                    <Select value={network} onValueChange={setNetwork}>
                      <SelectTrigger id="network">
                        <SelectValue />
                      </SelectTrigger>
                      <SelectContent>
                        {networks.map((n) => (
                          <SelectItem key={n} value={n}>
                            {n}
                          </SelectItem>
                        ))}
                      </SelectContent>
                    </Select>
                  </div>
                )}
              </div>

              {/* amount */}
              <div className="flex flex-col gap-2">
                <Label htmlFor="amount">{direction === "buy" ? "Нужная сумма крипты, RUB" : `Сумма к продаже, ${meta.label}`}</Label>
                <div className="relative">
                  <Input
                    id="amount"
                    inputMode="decimal"
                    value={amount}
                    onChange={(e) => setAmount(e.target.value)}
                    className="pr-16 font-mono text-lg"
                  />
                  <span className="pointer-events-none absolute right-3 top-1/2 -translate-y-1/2 text-xs font-medium text-muted-foreground">
                    {direction === "buy" ? "RUB" : meta.label}
                  </span>
                </div>
                {direction === "buy" && limits && (
                  <p className="text-xs text-muted-foreground">
                    Лимиты: {formatMoney(limits.min_fiat)} – {formatMoney(limits.max_fiat)} ₽
                  </p>
                )}
              </div>

              {/* payment method for buy */}
              {direction === "buy" && (
                <div className="flex flex-col gap-2">
                  <Label>Способ оплаты</Label>
                  <div className="grid grid-cols-2 gap-2">
                    {SUB_TOKENS.map((s) => (
                      <button
                        key={s.value}
                        type="button"
                        onClick={() => setSubToken(s.value)}
                        className={cn(
                          "flex flex-col items-start rounded-lg border p-3 text-left transition-colors active:scale-[0.99]",
                          subToken === s.value ? "border-foreground bg-muted/60" : "border-border hover:bg-muted/40",
                        )}
                      >
                        <span className="text-sm font-medium">{s.label}</span>
                        <span className="text-xs text-muted-foreground">{s.hint}</span>
                      </button>
                    ))}
                  </div>
                </div>
              )}

              {/* rate + result */}
              <div className="rounded-lg border border-dashed border-border bg-muted/30 p-3">
                <div className="flex items-center justify-between text-xs text-muted-foreground">
                  <span>Курс {direction === "buy" ? "покупки" : "продажи"}</span>
                  <span className="font-mono text-foreground">{price ? `1 ${meta.label} ≈ ${formatMoney(price)} ₽` : "—"}</span>
                </div>
                {direction === "buy" && Number(amount || 0) > 0 && !buyQuote && (
                  <p className="mt-2 text-xs text-destructive">Курс CoinGecko временно недоступен. Попробуйте позже.</p>
                )}
                <div className="mt-3 flex items-end justify-between gap-3">
                  <span className="text-sm text-muted-foreground">Вы получите примерно</span>
                  <span className="font-mono text-2xl font-semibold tracking-tight">
                    {result.toLocaleString("ru-RU", { maximumFractionDigits: 6 })}{" "}
                    <span className="text-sm font-medium text-muted-foreground">{direction === "buy" ? meta.label : "RUB"}</span>
                  </span>
                </div>
                {direction === "buy" && buyQuote && (
                  <div className="mt-2 flex items-end justify-between gap-3 text-sm">
                    <span className="text-muted-foreground">К оплате</span>
                    <span className="font-mono font-semibold">{formatMoney(buyQuote.pay)} ₽</span>
                  </div>
                )}
              </div>

              <AnimatePresence>
                {preview && (
                  <motion.div
                    initial={{ opacity: 0, height: 0 }}
                    animate={{ opacity: 1, height: "auto" }}
                    exit={{ opacity: 0, height: 0 }}
                    className="flex items-start gap-2 rounded-lg border border-destructive/40 bg-destructive/10 p-3 text-xs text-destructive"
                  >
                    <Info className="mt-0.5 size-4 shrink-0" />
                    <span>{preview}</span>
                  </motion.div>
                )}
              </AnimatePresence>

              {/* requisites */}
              <div className="flex flex-col gap-2">
                <Label htmlFor="requisites">{requisitesLabel}</Label>
                <Input
                  id="requisites"
                  value={requisites}
                  onChange={(e) => setRequisites(e.target.value)}
                  placeholder={requisitesPlaceholder}
                  className="font-mono"
                />
              </div>

              {offer ? (
                <div className="rounded-lg border border-border bg-muted/40 p-3 text-sm">
                  {offer.mode === "happy" ? <p className="font-medium">Счастливая сделка</p> : null}
                  <p className={offer.mode === "happy" ? "mt-1 leading-6 text-muted-foreground" : "leading-6"}>{offer.message}</p>
                </div>
              ) : null}

              {retry ? (
                <div className="rounded-lg border border-border bg-muted/40 p-3 text-sm">
                  <p className="leading-6">{retry.message || "Запрос реквизитов сохранён на 30 минут."}</p>
                  <Button
                    type="button"
                    className="mt-3 w-full"
                    variant="secondary"
                    disabled={retrying || (retry.retry_after_sec ?? 0) > 0 || retry.reason === "expired"}
                    onClick={() => repeatRequisites()}
                  >
                    {retrying ? "Ищем реквизиты…" : (retry.retry_after_sec ?? 0) > 0 ? `Повторить через ${Math.max(1, Math.ceil((retry.retry_after_sec ?? 0) / 60))} мин` : "Повторить запрос реквизитов"}
                  </Button>
                </div>
              ) : null}

              <Button size="lg" className="w-full" disabled={submitting || Number(amount) <= 0 || (direction === "buy" && !buyQuote)} onClick={() => submit(offer?.mode === "happy")}>
                {submitting ? (
                  <>
                    <Loader2 className="size-4 animate-spin" data-icon="inline-start" />
                    Создаём заявку…
                  </>
                ) : !sessionLoading && !isAuthed ? (
                  <>
                    <LogIn data-icon="inline-start" />
                    Войти и оформить
                  </>
                ) : offer?.mode === "happy" ? (
                  <>
                    Оформить на {formatMoney(offer.payRub)} ₽
                    <ArrowRight data-icon="inline-end" />
                  </>
                ) : (
                  <>
                    Создать заявку
                    <ArrowRight data-icon="inline-end" />
                  </>
                )}
              </Button>
              {offer?.mode === "happy" && isAuthed ? (
                <button type="button" className="text-center text-xs text-muted-foreground underline-offset-2 hover:underline" disabled={submitting} onClick={() => submit(false)}>
                  Оставить {formatMoney(buyQuote?.pay || Number(amount) || 0)} ₽
                </button>
              ) : null}
              <p className="text-center text-xs leading-relaxed text-muted-foreground">
                Без предоплаты. Реквизиты для перевода появятся после создания заявки.
                {direction === "buy" ? " Оплата с МТС Банка и Уралсиба не принимается." : ""}
              </p>
            </CardContent>
          </Card>
        </motion.div>
      </main>
    </div>
  );
}
