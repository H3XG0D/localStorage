import { useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { toast } from "sonner";
import { ApiError } from "@/lib/api";
import { quoteBuyFromCrypto, quoteBuyFromRub } from "@/lib/buyQuote";
import { createOrder, isRequisiteRetry, parseCryptoSymbol, payinFit, payinPreview, retryRequisiteRequest, roundUpOffer, type Direction, type PayinFitPreview, type RequisiteRetryDraft, type SubToken } from "@/lib/orders";
import { CRYPTO_META, getRates, type CryptoId, type RatesResponse } from "@/lib/public";
import { getMyOrders, type HistoryOrder } from "@/lib/user";
import { coin, rateRub, rub } from "../format";
import { PREVIEW } from "../preview";
import { Choice, Field, PrimaryButton, TextInput } from "../ui";

const ASSETS: CryptoId[] = ["usdt", "btc", "ltc", "trx"];

const PREVIEW_ORDERS: HistoryOrder[] = [
  { id: 1, order_id: "A", status: "PAID", direction: "buy", crypto: "BTC", crypto_amount: 0.01, fiat_amount: 90000, rate: 9000000, requisites: "bc1qfocuspayrecentwallet01xxxx", created_at: null, expires_at: null, required_receipt_type: null, deposit_wallet: null, payment: null },
  { id: 2, order_id: "B", status: "PAID", direction: "buy", crypto: "BTC", crypto_amount: 0.02, fiat_amount: 80000, rate: 9000000, requisites: "bc1qsecondrecentwallet02yyyy", created_at: null, expires_at: null, required_receipt_type: null, deposit_wallet: null, payment: null },
  { id: 3, order_id: "C", status: "PAID", direction: "buy", crypto: "USDT_TRC20", crypto_amount: 100, fiat_amount: 9000, rate: 90, requisites: "TXYZusdtrecentwallet", created_at: null, expires_at: null, required_receipt_type: null, deposit_wallet: null, payment: null },
];

function shorten(value: string) {
  if (value.length <= 22) return value;
  return `${value.slice(0, 8)}…${value.slice(-6)}`;
}

function recentRequisites(orders: HistoryOrder[], direction: Direction, asset: CryptoId, network: string) {
  const seen = new Set<string>();
  const out: string[] = [];
  for (const order of orders) {
    if (order.direction !== direction) continue;
    const parsed = parseCryptoSymbol(order.crypto || "");
    if (parsed.base.toLowerCase() !== asset) continue;
    if (asset === "usdt" && parsed.network && parsed.network !== network) continue;
    const value = (order.requisites || "").trim();
    if (value.length < 4) continue;
    const key = value.toLowerCase();
    if (seen.has(key)) continue;
    seen.add(key);
    out.push(value);
    if (out.length === 3) break;
  }
  return out;
}
type AmountUnit = "rub" | "coin";

function numeric(raw: string) {
  const value = Number(String(raw).trim().replace(/\s/g, "").replace(",", "."));
  return Number.isFinite(value) ? value : 0;
}

function trimCrypto(value: number) {
  if (!Number.isFinite(value) || value <= 0) return "";
  return value.toFixed(8).replace(/\.?0+$/, "");
}

function readAmount(raw: string, asset: string): { text: string; unit?: AmountUnit } {
  const compact = raw.trim().toLowerCase().replace(/\s+/g, "");
  const match = compact.match(/^(\d+(?:[.,]\d+)?)(rub|руб|usdt|btc|ltc|trx)?$/);
  if (!match) return { text: raw };
  const text = match[1].replace(",", ".");
  const suffix = match[2];
  if (suffix === "rub" || suffix === "руб") return { text, unit: "rub" };
  if (suffix === asset) return { text, unit: "coin" };
  return { text: raw.includes(",") ? raw.replace(",", ".") : raw };
}

const PAY: { value: SubToken; label: string; hint: string }[] = [
  { value: "SBPRUB", label: "СБП", hint: "По номеру телефона" },
  { value: "CARDRUB", label: "Карта", hint: "Перевод на карту" },
];

export function ExchangeScreen() {
  const navigate = useNavigate();
  const [rates, setRates] = useState<RatesResponse | null>(null);
  const [direction, setDirection] = useState<Direction>("buy");
  const [asset, setAsset] = useState<CryptoId>("usdt");
  const [network, setNetwork] = useState("TRC20");
  const [amount, setAmount] = useState(PREVIEW ? "50000" : "");
  const [amountUnit, setAmountUnit] = useState<AmountUnit>("rub");
  const [subToken, setSubToken] = useState<SubToken>("SBPRUB");
  const [requisites, setRequisites] = useState("");
  const [pastOrders, setPastOrders] = useState<HistoryOrder[]>(PREVIEW ? PREVIEW_ORDERS : []);
  const [warning, setWarning] = useState<string | null>(PREVIEW ? "Нет реквизитов на эту сумму." : null);
  const [fit, setFit] = useState<PayinFitPreview | null>(PREVIEW ? {
    kind: "round_up",
    offer: true,
    offer_mode: "happy",
    quote_rub: 50000,
    pay_rub: 51500,
    credit_rub: 1500,
    message: "Счастливая сделка: к оплате 51500 ₽ (−1500 ₽). Разница на баланс после оплаты.",
  } : null);
  const [retry, setRetry] = useState<RequisiteRetryDraft | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [retrying, setRetrying] = useState(false);

  const meta = CRYPTO_META[asset];
  const isUsdt = asset === "usdt";
  const inCoin = amountUnit === "coin";
  const entered = numeric(amount);
  const rate = rates?.rates?.[asset];
  const limits = rates?.public_tariffs?.buy_limits;
  const tiers = rates?.public_tariffs?.buy_spread_auto_tiers;
  const buyQuote = useMemo(() => {
    if (direction !== "buy") return null;
    return inCoin ? quoteBuyFromCrypto(entered, rate, tiers) : quoteBuyFromRub(entered, rate, tiers);
  }, [direction, entered, inCoin, rate, tiers]);
  const price = direction === "buy"
    ? (rate && buyQuote ? Number(rate.market) * (1 + buyQuote.pct / 100) : rate?.buy)
    : rate?.sell;
  const sellPrice = Number(price || (PREVIEW ? 92.4 : 0));
  const receive = direction === "buy"
    ? (inCoin ? (buyQuote?.pay ?? 0) : (PREVIEW && !rates ? 541.1256 : buyQuote?.crypto ?? 0))
    : (inCoin ? entered * sellPrice : (sellPrice ? entered / sellPrice : 0));
  const shownRate = price || (PREVIEW ? 92.4 : 0);
  const recent = recentRequisites(pastOrders, direction, asset, network);

  useEffect(() => {
    if (PREVIEW) return;
    let alive = true;
    getMyOrders(30, 0)
      .then((page) => alive && setPastOrders(page.orders || []))
      .catch(() => undefined);
    return () => {
      alive = false;
    };
  }, []);

  useEffect(() => {
    if (PREVIEW) return;
    let alive = true;
    const load = () => getRates().then((next) => alive && setRates(next)).catch(() => undefined);
    load();
    const timer = window.setInterval(load, 30_000);
    return () => {
      alive = false;
      window.clearInterval(timer);
    };
  }, []);

  useEffect(() => {
    if (isUsdt && !meta.networks.includes(network)) setNetwork(meta.networks[0]);
  }, [isUsdt, meta.networks, network]);

  useEffect(() => {
    const id = window.setInterval(() => {
      setRetry((current) => {
        if (!current?.retry_after_sec) return current;
        return { ...current, retry_after_sec: current.retry_after_sec - 1 };
      });
    }, 1000);
    return () => window.clearInterval(id);
  }, []);

  useEffect(() => {
    if (direction !== "buy") {
      setWarning(null);
      setFit(null);
      return;
    }
    if (PREVIEW) {
      setWarning("Нет реквизитов на эту сумму.");
      setFit({
        kind: "round_up",
        offer: true,
        offer_mode: "happy",
        quote_rub: 50000,
        pay_rub: 51500,
        credit_rub: 1500,
        message: "Счастливая сделка: к оплате 51500 ₽ (−1500 ₽). Разница на баланс после оплаты.",
      });
      return;
    }
    const pay = buyQuote?.pay ?? 0;
    if (!pay) {
      setWarning(null);
      setFit(null);
      return;
    }
    const handle = window.setTimeout(() => {
      payinPreview(pay, subToken)
        .then((preview) => setWarning(preview.mode === "reject" ? preview.message || "Нет реквизитов на эту сумму." : null))
        .catch(() => setWarning(null));
      payinFit(pay, subToken)
        .then((next) => setFit(next))
        .catch(() => setFit(null));
    }, 400);
    return () => window.clearTimeout(handle);
  }, [buyQuote?.pay, direction, subToken]);

  const offer = roundUpOffer(fit);

  async function submit(acceptRoundUp = false) {
    if (PREVIEW) {
      toast.success("Заявка создана");
      navigate("/order");
      return;
    }
    if (!requisites.trim()) {
      toast.error(direction === "buy" ? "Укажите кошелёк для зачисления" : "Укажите реквизиты для получения");
      return;
    }
    if (entered <= 0) {
      toast.error("Укажите сумму");
      return;
    }
    if ((direction === "buy" && !buyQuote) || (direction === "sell" && !sellPrice)) {
      toast.error("Курс временно недоступен. Попробуйте позже.");
      return;
    }
    setSubmitting(true);
    try {
      const order = await createOrder({
        direction,
        crypto: asset,
        network: isUsdt ? network : null,
        fiat_amount: inCoin ? null : entered,
        crypto_amount: inCoin ? entered : null,
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
      navigate("/order", { state: { orderId: order.order_id } });
    } catch (error) {
      const message = error instanceof ApiError ? error.message : "Не удалось создать заявку";
      if (error instanceof ApiError && error.status === 409) toast.info(message);
      else toast.error(message);
      if (error instanceof ApiError && error.status === 409) navigate("/order");
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
      navigate("/order", { state: { orderId: order.order_id } });
    } catch (error) {
      toast.error(error instanceof ApiError ? error.message : "Не удалось повторить запрос");
    } finally {
      setRetrying(false);
    }
  }

  const receiveUnit = inCoin ? "₽" : meta.label;
  const receiveLabel = direction === "buy"
    ? (inCoin ? "К оплате" : "Вы получите")
    : (inCoin ? "Вы получите" : "Нужно отправить");
  const receiveText = inCoin ? rub(receive, 0) : coin(receive);

  function onAmount(raw: string) {
    const next = readAmount(raw, asset);
    if (next.unit) setAmountUnit(next.unit);
    setAmount(next.text);
  }

  function switchUnit(next: AmountUnit) {
    if (next === amountUnit) return;
    const value = numeric(amount);
    if (value > 0) {
      if (amountUnit === "rub" && next === "coin") {
        const crypto = direction === "buy"
          ? quoteBuyFromRub(value, rate, tiers)?.crypto
          : (sellPrice ? value / sellPrice : 0);
        if (crypto) setAmount(trimCrypto(crypto));
      } else if (amountUnit === "coin" && next === "rub") {
        const fiat = direction === "buy"
          ? quoteBuyFromCrypto(value, rate, tiers)?.pay
          : value * sellPrice;
        if (fiat) setAmount(String(Math.round(fiat)));
      }
    }
    setAmountUnit(next);
  }

  return (
    <div>
      <section className="ex-hero">
        <p className="ex-kicker">Курс {direction === "buy" ? "покупки" : "продажи"} · 1 {meta.label}</p>
        <p className="ex-hero-rate"><span className="ex-mono">{rateRub(shownRate)}</span> <small>₽</small></p>
        <p className="ex-hero-get">
          {receiveLabel} <span className="ex-mono">{receiveText}</span> {receiveUnit}
        </p>
      </section>

      <div className="ex-seg" role="group" aria-label="Направление">
        <button type="button" aria-pressed={direction === "buy"} onClick={() => { setDirection("buy"); setAmountUnit("rub"); setAmount(""); }}>Покупаю</button>
        <button type="button" aria-pressed={direction === "sell"} onClick={() => { setDirection("sell"); setAmountUnit("coin"); setAmount(""); }}>Продаю</button>
      </div>

      <div className="ex-chips" aria-label="Актив">
        {ASSETS.map((id) => (
          <button key={id} type="button" className="ex-chip" aria-pressed={asset === id} onClick={() => setAsset(id)}>
            {CRYPTO_META[id].label}
          </button>
        ))}
      </div>

      {isUsdt ? (
        <div className="ex-chips mt-3" aria-label="Сеть">
          {meta.networks.map((item) => (
            <button key={item} type="button" className="ex-chip" aria-pressed={network === item} onClick={() => setNetwork(item)}>
              {item}
            </button>
          ))}
        </div>
      ) : null}

      <div className="mt-4 flex flex-col gap-4">
        <div>
          <div className="mb-2 flex items-center justify-between gap-3">
            <span className="text-xs font-medium text-muted-foreground">Сумма</span>
            <div className="ex-chips" role="group" aria-label="В чём сумма">
              <button type="button" className="ex-chip" aria-pressed={!inCoin} onClick={() => switchUnit("rub")}>₽</button>
              <button type="button" className="ex-chip" aria-pressed={inCoin} onClick={() => switchUnit("coin")}>{meta.label}</button>
            </div>
          </div>
          <TextInput
            inputMode="decimal"
            value={amount}
            onChange={(event) => onAmount(event.target.value)}
            placeholder={inCoin ? "2.37182" : "50000"}
          />
        </div>
        {direction === "buy" ? (
          <div>
            <p className="mb-2 text-xs font-medium text-muted-foreground">Способ оплаты</p>
            <div className="grid grid-cols-2 gap-2">
              {PAY.map((item) => (
                <Choice key={item.value} active={subToken === item.value} title={item.label} hint={item.hint} onClick={() => setSubToken(item.value)} />
              ))}
            </div>
          </div>
        ) : null}
        <Field label={direction === "buy" ? `Кошелёк ${meta.label}` : "Карта или телефон СБП"}>
          <TextInput
            value={requisites}
            onChange={(event) => setRequisites(event.target.value)}
            placeholder={direction === "buy" ? `Адрес ${meta.label}` : "Куда отправить рубли"}
            className="text-sm"
          />
        </Field>
        {recent.length > 0 ? (
          <ul className="ex-recent">
            {recent.map((value) => (
              <li key={value}>
                <span className="ex-mono">{shorten(value)}</span>
                <button type="button" onClick={() => setRequisites(value)}>Повторить</button>
              </li>
            ))}
          </ul>
        ) : null}
      </div>

      {direction === "buy" && limits ? (
        <p className="mt-3 text-xs text-muted-foreground">
          Лимиты: {rub(limits.min_fiat, 0)}–{rub(limits.max_fiat, 0)} ₽
        </p>
      ) : null}

      {warning ? (
        <p className="mt-3 rounded-xl border border-destructive/30 bg-destructive/10 px-3 py-2 text-sm text-destructive">{warning}</p>
      ) : null}

      {offer ? (
        <div className="mt-3 rounded-xl border border-border bg-muted/40 px-3 py-3 text-sm">
          {offer.mode === "happy" ? <p className="font-medium">Счастливая сделка</p> : null}
          <p className={offer.mode === "happy" ? "mt-1 leading-6 text-muted-foreground" : "leading-6"}>{offer.message}</p>
        </div>
      ) : null}

      {retry ? (
        <div className="mt-3 rounded-xl border border-border bg-muted/40 px-3 py-3 text-sm">
          <p>{retry.message || "Запрос реквизитов сохранён на 30 минут."}</p>
          <button
            type="button"
            className="mt-3 w-full rounded-xl border border-border px-3 py-2"
            disabled={retrying || (retry.retry_after_sec ?? 0) > 0 || retry.reason === "expired"}
            onClick={() => void repeatRequisites()}
          >
            {retrying ? "Ищем реквизиты…" : (retry.retry_after_sec ?? 0) > 0 ? `Повторить через ${Math.max(1, Math.ceil((retry.retry_after_sec ?? 0) / 60))} мин` : "Повторить запрос реквизитов"}
          </button>
        </div>
      ) : null}

      <div className="ex-dock">
        <PrimaryButton disabled={submitting} onClick={() => void submit(offer?.mode === "happy")}>
          {submitting ? "Создаём…" : offer?.mode === "happy" ? `Оформить на ${rub(offer.payRub, 0)} ₽` : "Создать заявку"}
        </PrimaryButton>
        {offer?.mode === "happy" ? (
          <button type="button" className="mt-2 w-full text-center text-xs text-muted-foreground" disabled={submitting} onClick={() => void submit(false)}>
            Оставить {rub(buyQuote?.pay || entered, 0)} ₽
          </button>
        ) : null}
      </div>
    </div>
  );
}
