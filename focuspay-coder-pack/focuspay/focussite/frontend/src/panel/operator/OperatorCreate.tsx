import { useEffect, useState } from "react";
import { Calculator } from "lucide-react";
import { useNavigate } from "react-router-dom";
import { toast } from "sonner";
import { PanelApiError } from "@/panel/lib/panelApi";
import {
  closeClientHold,
  createOrder,
  getCoingeckoRate,
  getMe,
  getRate,
  getUser,
  getUserDiscounts,
  type CreateOrderInput,
  type RateInfo,
} from "@/panel/lib/operatorApi";
import { ClientSearch, type ClientHit } from "@/panel/ui/ClientSearch";
import { Button, Card, Field, Input, PageHeader, Select, cx } from "@/panel/ui/primitives";
import { getPayoutWalletMode, previewNewOrderWalletSend, type WalletPayoutMode } from "@/panel/lib/operatorApi";
import { ProjectWalletSendModal } from "@/panel/operator/ProjectWalletSendModal";

const CRYPTOS = ["usdt", "btc", "ltc", "trx"];
const TYPES: { key: CreateOrderInput["order_type"]; label: string }[] = [
  { key: "buy", label: "Покупка (клиент купил крипту)" },
  { key: "sell", label: "Продажа (клиент продал крипту)" },
  { key: "sell_qr", label: "Продажа QR" },
];

interface BuyerDiscount {
  id: number;
  promo_code: string;
  amount_rub: number;
  min_order_rub: number;
  preview_applied_rub?: number;
  preview_fiat_to_pay?: number | null;
}

function num(v: string) {
  const value = Number(String(v).replace(",", "."));
  return Number.isFinite(value) ? value : 0;
}

function rub(v: number) {
  return new Intl.NumberFormat("ru-RU", { maximumFractionDigits: 2 }).format(v);
}

function cryptoQty(v: number) {
  return new Intl.NumberFormat("ru-RU", { maximumFractionDigits: 8 }).format(v);
}

function roundedInput(value: number, fractionDigits: number) {
  if (!Number.isFinite(value) || value <= 0) return "";
  const factor = 10 ** fractionDigits;
  const rounded = Math.round((value + Number.EPSILON) * factor) / factor;
  const formatted = rounded.toFixed(fractionDigits);
  return fractionDigits === 0 ? formatted : formatted.replace(/\.?0+$/, "");
}

function buyerIdOf(buyer: ClientHit | null): number | undefined {
  if (!buyer) return undefined;
  const id = buyer.user_id ?? buyer.id;
  return typeof id === "number" ? id : Number(id) || undefined;
}

export function OperatorCreate() {
  const navigate = useNavigate();
  const [buyer, setBuyer] = useState<ClientHit | null>(null);
  const [orderType, setOrderType] = useState<CreateOrderInput["order_type"]>("buy");
  const [crypto, setCrypto] = useState("usdt");
  const [network, setNetwork] = useState("TRC20");
  const [fiat, setFiat] = useState("");
  const [cryptoAmount, setCryptoAmount] = useState("");
  const [manualSpreadPct, setManualSpreadPct] = useState("");
  const [receivedFiatAmount, setReceivedFiatAmount] = useState("");
  const [requisiteTicket, setRequisiteTicket] = useState("");
  const [txHash, setTxHash] = useState("");
  const [wallet, setWallet] = useState("");
  const [requisites, setRequisites] = useState("");
  const [note, setNote] = useState("");
  const [rateInfo, setRateInfo] = useState<RateInfo | null>(null);
  const [cgRate, setCgRate] = useState<number | null>(null);
  const [cgLoading, setCgLoading] = useState(false);
  const [cgError, setCgError] = useState<string | null>(null);
  const [cgRub, setCgRub] = useState("");
  const [lastAmountEdited, setLastAmountEdited] = useState<"fiat" | "crypto" | null>(null);
  const [busy, setBusy] = useState(false);
  const [shiftOpen, setShiftOpen] = useState<boolean | null>(null);
  const [isFinance, setIsFinance] = useState<boolean | null>(null);

  const [buyerAvailableRub, setBuyerAvailableRub] = useState(0);
  const [applyBalance, setApplyBalance] = useState(false);
  const [buyerDiscounts, setBuyerDiscounts] = useState<BuyerDiscount[]>([]);
  const [discountsLoading, setDiscountsLoading] = useState(false);
  const [selectedDiscountId, setSelectedDiscountId] = useState<number | null>(null);
  const [activeOrder, setActiveOrder] = useState<{
    order_id?: string;
    status?: string;
    fiat_amount?: number;
    crypto?: string;
    direction?: string;
  } | null>(null);
  const [closingHold, setClosingHold] = useState(false);

  const [walletMode, setWalletMode] = useState<WalletPayoutMode | null>(null);
  const [ownWallet, setOwnWallet] = useState(false);
  const [sendBody, setSendBody] = useState<CreateOrderInput | null>(null);

  const isBuy = orderType === "buy";
  const projectWalletAvailable =
    isBuy && isFinance === true && walletMode?.mode === "project" && walletMode.coins.includes(crypto);
  const payFromProject = projectWalletAvailable && !ownWallet;
  const requiresTxHash = isBuy && isFinance === true && !payFromProject;
  const buyerId = buyerIdOf(buyer);

  useEffect(() => {
    getPayoutWalletMode()
      .then(setWalletMode)
      .catch(() => setWalletMode(null));
  }, []);

  useEffect(() => {
    getMe()
      .then((me) => {
        setShiftOpen(!!me.active_shift);
        const roles = Array.isArray(me.operator?.operator_roles)
          ? me.operator.operator_roles
          : [me.operator?.operator_role ?? "client"];
        setIsFinance(roles.includes("finance"));
      })
      .catch((e) => {
        setShiftOpen(false);
        toast.error(e instanceof PanelApiError ? e.message : "Не удалось проверить смену");
      });
  }, []);

  useEffect(() => {
    let active = true;
    getRate(crypto)
      .then((nextRate) => {
        if (!active) return;
        setRateInfo(nextRate);
        if (isBuy) setManualSpreadPct((current) => current || String(nextRate.buy_commission_pct));
      })
      .catch((e) => {
        if (!active) return;
        toast.error(e instanceof PanelApiError ? e.message : "Не удалось получить курс");
      });
    return () => {
      active = false;
    };
  }, [crypto, isBuy]);

  useEffect(() => {
    if (!isBuy) {
      setCgRate(null);
      setCgError(null);
      setCgLoading(false);
      return;
    }
    setCgLoading(true);
    setCgError(null);
    const timer = window.setTimeout(() => {
      let active = true;
      getCoingeckoRate(crypto)
        .then((res) => {
          if (!active) return;
          setCgRate(Number(res.rub_rate) > 0 ? Number(res.rub_rate) : null);
          setCgLoading(false);
        })
        .catch((e) => {
          if (!active) return;
          setCgRate(null);
          setCgLoading(false);
          setCgError(e instanceof PanelApiError ? e.message : "CoinGecko недоступен");
        });
      return;
    }, 500);
    return () => {
      window.clearTimeout(timer);
    };
  }, [crypto, isBuy]);
  useEffect(() => {
    if (!buyerId) {
      setActiveOrder(null);
      return;
    }
    let cancelled = false;
    getUser(buyerId)
      .then((p) => {
        if (cancelled) return;
        const order = (p?.active_order ?? null) as {
          order_id?: string;
          status?: string;
          fiat_amount?: number;
          crypto?: string;
          direction?: string;
        } | null;
        setActiveOrder(order && order.order_id ? order : null);
      })
      .catch(() => {
        if (!cancelled) setActiveOrder(null);
      });
    return () => {
      cancelled = true;
    };
  }, [buyerId]);

  useEffect(() => {
    if (!isBuy || !buyerId) {
      setBuyerAvailableRub(0);
      setApplyBalance(false);
      return;
    }
    let cancelled = false;
    getUser(buyerId)
      .then((p) => {
        if (cancelled) return;
        const balances = (p?.balances ?? {}) as Record<string, unknown>;
        const available = Number(balances.available_rub ?? balances.balance_rub ?? 0);
        setBuyerAvailableRub(Number.isFinite(available) ? Math.max(0, available) : 0);
        setApplyBalance(false);
      })
      .catch(() => {
        if (!cancelled) {
          setBuyerAvailableRub(0);
          setApplyBalance(false);
        }
      });
    return () => {
      cancelled = true;
    };
  }, [isBuy, buyerId]);

  useEffect(() => {
    if (!isBuy || !buyerId) {
      setBuyerDiscounts([]);
      setSelectedDiscountId(null);
      setDiscountsLoading(false);
      return;
    }
    const fiatAmount = num(fiat);
    let cancelled = false;
    setDiscountsLoading(true);
    const timer = window.setTimeout(() => {
      getUserDiscounts(buyerId, fiatAmount > 0 ? fiatAmount : undefined)
        .then((d) => {
          if (cancelled) return;
          const list = (Array.isArray(d.discounts) ? d.discounts : []) as BuyerDiscount[];
          setBuyerDiscounts(list);
          setSelectedDiscountId((prev) => {
            if (prev != null && list.some((x) => x.id === prev)) return prev;
            const auto = list.find((x) => (x.preview_applied_rub ?? 0) > 0);
            return auto?.id ?? null;
          });
        })
        .catch(() => {
          if (!cancelled) setBuyerDiscounts([]);
        })
        .finally(() => {
          if (!cancelled) setDiscountsLoading(false);
        });
    }, 300);
    return () => {
      cancelled = true;
      window.clearTimeout(timer);
    };
  }, [isBuy, buyerId, fiat]);

  const manualSpread = num(manualSpreadPct);
  const manualSpreadValid = manualSpread >= 14 && manualSpread <= 25;
  const rate = rateInfo
    ? isBuy && manualSpreadValid
      ? rateInfo.market_rate * (1 + manualSpread / 100)
      : isBuy
        ? rateInfo.buy_rate
        : rateInfo.sell_rate
    : null;
  const adjustmentPct = rateInfo ? (isBuy ? manualSpread : rateInfo.sell_commission_pct) : null;
  const sellMarkup = !isBuy && rateInfo?.sell_pricing_mode === "markup";
  const adjustmentLabel = isBuy ? "Наценка" : sellMarkup ? "Доплата" : "Скидка";

  const selectedDiscount = buyerDiscounts.find((d) => d.id === selectedDiscountId);
  const discountPreviewRub = selectedDiscount?.preview_applied_rub ?? 0;
  const fiatBeforeDiscount = num(fiat);
  const fiatAfterDiscount =
    discountPreviewRub > 0 && fiatBeforeDiscount > 0
      ? Math.max(1, fiatBeforeDiscount - discountPreviewRub)
      : null;
  const fiatForBalance = fiatAfterDiscount != null ? fiatAfterDiscount : fiatBeforeDiscount;
  const balancePreviewRub =
    applyBalance && buyerAvailableRub > 0 && fiatForBalance > 0
      ? Math.min(buyerAvailableRub, Math.max(0, fiatForBalance - 1))
      : 0;
  const fiatAfterBalance =
    balancePreviewRub > 0 ? Math.max(1, fiatForBalance - balancePreviewRub) : null;
  const expectedFiat = fiatAfterBalance ?? fiatForBalance;
  const overpayRub = isBuy ? Math.max(0, num(receivedFiatAmount) - expectedFiat) : 0;
  const overpayCreditRub = isBuy && manualSpreadValid ? overpayRub * (1 - manualSpread / 100) : 0;

  function calculateCrypto(value: string) {
    const amount = num(value);
    return rate && amount > 0 ? roundedInput(amount / rate, 8) : "";
  }

  function calculateFiat(value: string) {
    const amount = num(value);
    return rate && amount > 0 ? roundedInput(amount * rate, 2) : "";
  }

  function handleFiatChange(value: string) {
    setFiat(value);
    setLastAmountEdited("fiat");
    setCryptoAmount(value.trim() && num(value) > 0 ? calculateCrypto(value) : "");
  }

  function handleCryptoChange(value: string) {
    setCryptoAmount(value);
    setLastAmountEdited("crypto");
    setFiat(value.trim() && num(value) > 0 ? calculateFiat(value) : "");
  }

  function pickBuyer(next: ClientHit) {
    setBuyer(next);
    setApplyBalance(false);
    setSelectedDiscountId(null);
    setBuyerDiscounts([]);
    setBuyerAvailableRub(0);
  }

  function clearBuyer() {
    setBuyer(null);
    setApplyBalance(false);
    setSelectedDiscountId(null);
    setBuyerDiscounts([]);
    setBuyerAvailableRub(0);
    setActiveOrder(null);
  }

  useEffect(() => {
    if (!rate || !lastAmountEdited) return;
    if (lastAmountEdited === "fiat" && num(fiat) > 0) setCryptoAmount(calculateCrypto(fiat));
    if (lastAmountEdited === "crypto" && num(cryptoAmount) > 0) setFiat(calculateFiat(cryptoAmount));
    // Recalculate the dependent field when the asset or direction changes.
    // The edited field remains the source of truth until the next user input.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [rate, lastAmountEdited]);

  // Compare against the market rate; amount fields use the effective rate with the service tariff.
  const marketValue = rateInfo && num(cryptoAmount) > 0 ? rateInfo.market_rate * num(cryptoAmount) : null;
  const cgCryptoFromRub = cgRate != null && cgRate > 0 && num(cgRub) > 0 ? num(cgRub) / cgRate : null;

  if (shiftOpen !== true) {
    return (
      <>
        <PageHeader title="Зафиксировать обмен" subtitle="Ручная заявка доступна только во время смены" />
        <Card>
          <div className="flex flex-col items-start gap-3 py-4">
            <p className="text-[13px] text-[var(--text-secondary)]">
              {shiftOpen === null ? "Проверяем состояние смены…" : "Откройте смену, чтобы создать заявку."}
            </p>
            {shiftOpen === false && (
              <Button variant="primary" onClick={() => navigate("/ops")}>
                Перейти к смене
              </Button>
            )}
          </div>
        </Card>
      </>
    );
  }

  async function submit() {
    if (!buyerId) return toast.error("Выберите клиента");
    if (num(fiat) <= 0) return toast.error("Укажите сумму в рублях");
    if (isBuy && !manualSpreadValid) return toast.error("Укажите процент от 14,00% до 25,00%");
    if (isBuy && num(receivedFiatAmount) <= 0) return toast.error("Укажите полученную на реквизит сумму");
    if (requiresTxHash && !txHash.trim()) return toast.error("Укажите хэш транзакции");
    if (payFromProject && !wallet.trim()) return toast.error("Укажите кошелёк клиента");
    const body = buildBody(buyerId);
    if (payFromProject) {
      setSendBody(body);
      return;
    }
    setBusy(true);
    try {
      const result = await createOrder(body);
      toast.success(
        isBuy && !isFinance
          ? `Заявка #${result.order.order_id} передана финансовому оператору`
          : `Заявка #${result.order.order_id} зафиксирована`,
      );
      navigate("/ops/orders");
    } catch (e) {
      toast.error(e instanceof PanelApiError ? e.message : "Не удалось зафиксировать");
    } finally {
      setBusy(false);
    }
  }

  function buildBody(buyerUserId: number): CreateOrderInput {
    return {
        order_type: orderType,
        buyer_user_id: buyerUserId,
        crypto,
        network: crypto === "usdt" ? network : undefined,
        fiat_amount: num(fiat) > 0 ? num(fiat) : undefined,
        crypto_amount:
          orderType === "sell_qr" || lastAmountEdited !== "fiat" ? num(cryptoAmount) : undefined,
        tx_hash: requiresTxHash ? txHash.trim() : undefined,
        wallet_address: wallet.trim() || undefined,
        requisites: requisites || undefined,
        note: note || undefined,
        // record-fact: суммы, что реально прошли
        crypto_received: !isBuy ? num(cryptoAmount) || undefined : undefined,
        fiat_paid_out: !isBuy ? num(fiat) || undefined : undefined,
        ...(isBuy
          ? {
              apply_balance: applyBalance,
              exchange_discount_id: selectedDiscountId ?? undefined,
              manual_spread_pct: manualSpread,
              received_fiat_amount: num(receivedFiatAmount),
              requisite_ticket: requisiteTicket.trim() || undefined,
            }
          : {}),
    };
  }

  return (
    <>
      <PageHeader title="Зафиксировать обмен" subtitle="Ручная заявка — фиксация уже совершённого обмена" />

      <Card>
        <div className="mb-3 text-[13.5px] font-semibold">1 · Клиент</div>
        {buyer ? (
          <div className="flex items-center justify-between rounded-[var(--radius)] bg-[var(--bg-elevated)] p-3">
            <span className="text-[13px]">
              {buyer.first_name || (buyer.username ? `@${buyer.username}` : "")} · ID {buyer.user_id ?? buyer.id}
            </span>
            <Button size="sm" variant="ghost" onClick={clearBuyer}>
              Сменить
            </Button>
          </div>
        ) : (
          <ClientSearch onPick={pickBuyer} autoFocus />
        )}
        {activeOrder?.order_id ? (
          <div className="mt-3 rounded-[var(--radius)] border border-[var(--yellow)]/30 bg-[var(--yellow-bg)] px-3 py-3">
            <div className="text-[13px] font-medium text-[var(--yellow)]">Клиента держит заявка</div>
            <div className="mt-1 text-[12px] text-[var(--text-secondary)]">
              #{activeOrder.order_id}
              {activeOrder.crypto ? ` · ${String(activeOrder.crypto).toUpperCase()}` : ""}
              {activeOrder.fiat_amount != null ? ` · ${rub(Number(activeOrder.fiat_amount))} ₽` : ""}
              {activeOrder.status ? ` · ${activeOrder.status}` : ""}
            </div>
            <Button
              className="mt-2"
              size="sm"
              variant="danger"
              disabled={closingHold}
              onClick={async () => {
                if (!window.confirm(`Закрыть #${activeOrder.order_id}? Клиент сможет начать новый обмен.`)) return;
                setClosingHold(true);
                try {
                  await closeClientHold(String(activeOrder.order_id));
                  toast.success("Заявка закрыта");
                  setActiveOrder(null);
                } catch (e) {
                  toast.error(e instanceof PanelApiError ? e.message : "Не удалось закрыть");
                } finally {
                  setClosingHold(false);
                }
              }}
            >
              {closingHold ? "Закрываю…" : "Закрыть заявку"}
            </Button>
          </div>
        ) : null}
      </Card>

      <Card>
        <div className="mb-3 text-[13.5px] font-semibold">2 · Что произошло</div>
        <div className="flex flex-col gap-3">
          <div className="flex w-fit flex-wrap gap-1 rounded-[var(--radius)] border border-[var(--border)] p-1">
            {TYPES.filter((t) => t.key !== "sell_qr" || isFinance === true).map((t) => (
              <button
                key={t.key}
                onClick={() => setOrderType(t.key)}
                className={cx(
                  "rounded-[var(--radius-sm)] px-3 py-1.5 text-[12.5px] font-medium transition-colors",
                  orderType === t.key
                    ? "bg-[var(--bg-elevated)] text-[var(--text-primary)]"
                    : "text-[var(--text-secondary)] hover:text-[var(--text-primary)]",
                )}
              >
                {t.label}
              </button>
            ))}
          </div>

          <div className="grid grid-cols-2 gap-3 max-[520px]:grid-cols-1">
            <Field label="Актив">
              <Select value={crypto} onChange={(e) => setCrypto(e.target.value)}>
                {CRYPTOS.map((c) => (
                  <option key={c} value={c}>
                    {c.toUpperCase()}
                  </option>
                ))}
              </Select>
            </Field>
            {crypto === "usdt" && (
              <Field label="Сеть">
                <Select value={network} onChange={(e) => setNetwork(e.target.value)}>
                  {["TRC20", "ERC20", "BEP20"].map((n) => (
                    <option key={n} value={n}>
                      {n}
                    </option>
                  ))}
                </Select>
              </Field>
            )}
            <Field label="Сумма, ₽">
              <Input
                inputMode="decimal"
                value={fiat}
                onChange={(e) => handleFiatChange(e.target.value)}
                className="font-mono"
                placeholder="0"
                min="0"
                step={isBuy ? "1" : "0.01"}
              />
            </Field>
            <Field label={`Крипта, ${crypto.toUpperCase()}`}>
              <Input
                inputMode="decimal"
                value={cryptoAmount}
                onChange={(e) => handleCryptoChange(e.target.value)}
                className="font-mono"
                placeholder="0"
                min="0"
                step="0.00000001"
              />
            </Field>
          </div>

          {isBuy && (
            <div className="grid grid-cols-2 gap-3 max-[520px]:grid-cols-1">
              <Field label="Индивидуальная наценка, %">
                <Input
                  inputMode="decimal"
                  value={manualSpreadPct}
                  onChange={(e) => setManualSpreadPct(e.target.value)}
                  className="font-mono"
                  placeholder="14.00–25.00"
                  min="14"
                  max="25"
                  step="0.01"
                />
              </Field>
              <Field label="Получено на реквизит, ₽">
                <Input
                  inputMode="decimal"
                  value={receivedFiatAmount}
                  onChange={(e) => setReceivedFiatAmount(e.target.value)}
                  className="font-mono"
                  placeholder="0"
                  min="0"
                  step="0.01"
                />
              </Field>
              <Field label="Код реквизита (необязательно)">
                <Input
                  value={requisiteTicket}
                  onChange={(e) => setRequisiteTicket(e.target.value.toUpperCase())}
                  className="font-mono"
                  placeholder="MAN-AB12CD"
                  maxLength={10}
                />
              </Field>
              <p className="col-span-full text-[11px] text-[var(--text-secondary)]">
                Код из бота, если реквизит брали командой «сбп 5400». Без него выдача отменится через 30 минут.
              </p>
              {!manualSpreadValid && manualSpreadPct.trim() && (
                <p className="col-span-full text-[11px] text-[var(--red)]">Допустимый процент: от 14,00% до 25,00%.</p>
              )}
            </div>
          )}

          <div className="grid grid-cols-2 gap-3 max-[900px]:grid-cols-1">
          <div className="rounded-[var(--radius)] border border-[var(--border)] bg-[var(--bg-elevated)] p-3">
            <div className="flex items-center gap-2 text-[12px] font-semibold text-[var(--text-primary)]">
              <Calculator className="size-4 text-[var(--blue)]" />
              Калькулятор курса
            </div>
            <div className="mt-2 grid grid-cols-3 gap-3 text-[12px] max-[520px]:grid-cols-1">
              <div>
                <div className="text-[10px] uppercase tracking-wide text-[var(--text-muted)]">Курс с тарифом</div>
                <div className="mt-0.5 font-mono text-[13px]">
                  {rate ? `${new Intl.NumberFormat("ru-RU", { maximumFractionDigits: 2 }).format(rate)} ₽` : "—"}
                </div>
              </div>
              <div>
                <div className="text-[10px] uppercase tracking-wide text-[var(--text-muted)]">{adjustmentLabel}</div>
                <div className="mt-0.5 font-mono text-[13px]">
                  {adjustmentPct != null
                    ? `${isBuy || sellMarkup ? "+" : "−"}${new Intl.NumberFormat("ru-RU", { maximumFractionDigits: 2 }).format(adjustmentPct)}%`
                    : "—"}
                </div>
              </div>
              <div>
                <div className="text-[10px] uppercase tracking-wide text-[var(--text-muted)]">Рыночная стоимость</div>
                <div className="mt-0.5 font-mono text-[13px]">
                  {marketValue != null
                    ? `${new Intl.NumberFormat("ru-RU", { maximumFractionDigits: 2 }).format(marketValue)} ₽`
                    : "—"}
                </div>
              </div>
            </div>
            {isBuy && num(receivedFiatAmount) > 0 && (
              <div className="mt-3 grid grid-cols-3 gap-3 border-t border-[var(--border)] pt-3 text-[12px] max-[520px]:grid-cols-1">
                <div>
                  <div className="text-[10px] uppercase tracking-wide text-[var(--text-muted)]">Ожидаемая оплата</div>
                  <div className="mt-0.5 font-mono text-[13px]">{rub(expectedFiat)} ₽</div>
                </div>
                <div>
                  <div className="text-[10px] uppercase tracking-wide text-[var(--text-muted)]">Переплата</div>
                  <div className="mt-0.5 font-mono text-[13px]">{rub(overpayRub)} ₽</div>
                </div>
                <div>
                  <div className="text-[10px] uppercase tracking-wide text-[var(--text-muted)]">Дополнительный баланс</div>
                  <div className="mt-0.5 font-mono text-[13px] font-semibold text-[var(--green)]">+{rub(overpayCreditRub)} ₽</div>
                </div>
              </div>
            )}
            {rateInfo?.frozen ? (
              <div className="mt-2 text-[11px] text-[var(--text-muted)]">
                Последний зафиксированный курс · Rapira недоступна. Бот считает по нему же.
              </div>
            ) : null}
          </div>
          {isBuy && (
          <div className="rounded-[var(--radius)] border border-[var(--border)] bg-[var(--bg-elevated)] p-3">
            <div className="flex items-center gap-2 text-[12px] font-semibold text-[var(--text-primary)]">
              <Calculator className="size-4 text-[var(--green)]" />
              CoinGecko · справка
            </div>
            <div className="mt-2 text-[12px]">
              <div className="text-[10px] uppercase tracking-wide text-[var(--text-muted)]">
                Курс 1 {crypto.toUpperCase()}
              </div>
              <div className="mt-0.5 font-mono text-[13px]">
                {cgLoading ? "…" : cgRate ? `${new Intl.NumberFormat("ru-RU", { maximumFractionDigits: 2 }).format(cgRate)} ₽` : "—"}
              </div>
            </div>
            <div className="mt-3">
              <Field label="Сумма, ₽">
                <Input
                  inputMode="decimal"
                  value={cgRub}
                  onChange={(e) => setCgRub(e.target.value)}
                  className="font-mono"
                  placeholder="0"
                  min="0"
                  step="0.01"
                  aria-label="Сумма в рублях для справки CoinGecko"
                />
              </Field>
              <div className="mt-2 text-[12px]">
                <div className="text-[10px] uppercase tracking-wide text-[var(--text-muted)]">
                  Крипта, {crypto.toUpperCase()}
                </div>
                <div className="mt-0.5 font-mono text-[15px] font-semibold">
                  {cgLoading && num(cgRub) > 0
                    ? "…"
                    : cgCryptoFromRub != null
                      ? cryptoQty(cgCryptoFromRub)
                      : "—"}
                </div>
                {!cgLoading && num(cgRub) <= 0 && (
                  <div className="mt-1 text-[11px] text-[var(--text-muted)]">
                    Введите сумму в рублях — посчитаем количество крипты по курсу CoinGecko.
                  </div>
                )}
              </div>
            </div>
            {cgError && !cgLoading && (
              <div className="mt-2 text-[11px] text-[var(--red)]">{cgError}</div>
            )}
            <div className="mt-2 text-[11px] text-[var(--text-muted)]">Справочно, в заявку не сохраняется.</div>
          </div>
          )}
          </div>

          {isBuy && buyer && (
            <div className="rounded-[var(--radius)] border border-[var(--border)] bg-[var(--bg-elevated)] p-3 space-y-3">
              <div className="text-[12px] font-semibold text-[var(--text-primary)]">Баланс клиента</div>
              <div className="flex items-center justify-between gap-3">
                <div>
                  <div className="text-[10px] uppercase tracking-wide text-[var(--text-muted)]">Доступно к списанию</div>
                  <div className="mt-0.5 font-mono text-[13px] font-semibold">{rub(buyerAvailableRub)} ₽</div>
                </div>
                <button
                  type="button"
                  role="switch"
                  aria-checked={applyBalance}
                  aria-label="Списать баланс"
                  disabled={buyerAvailableRub <= 0}
                  onClick={() => setApplyBalance((v) => !v)}
                  className={cx(
                    "inline-flex items-center gap-2 select-none",
                    buyerAvailableRub > 0 ? "cursor-pointer" : "opacity-50 cursor-not-allowed",
                  )}
                >
                  <span className="text-[13px] text-[var(--text-secondary)]">Списать баланс</span>
                  <span
                    className={cx(
                      "relative h-6 w-11 rounded-full transition-colors",
                      applyBalance ? "bg-[var(--yellow)]" : "bg-[var(--border)]",
                    )}
                  >
                    <span
                      className={cx(
                        "absolute top-0.5 left-0.5 h-5 w-5 rounded-full bg-white transition-transform",
                        applyBalance ? "translate-x-5" : "translate-x-0",
                      )}
                    />
                  </span>
                </button>
              </div>
              {applyBalance && balancePreviewRub > 0 && (
                <div className="rounded-[var(--radius-sm)] border border-[var(--border)] bg-[var(--bg)] p-3 text-[12px] space-y-1">
                  <div className="flex justify-between">
                    <span className="text-[var(--text-muted)]">Списание с баланса</span>
                    <span className="font-medium text-[var(--yellow)]">−{rub(balancePreviewRub)} ₽</span>
                  </div>
                  {fiatAfterBalance != null && (
                    <div className="flex justify-between border-t border-[var(--border)] pt-2">
                      <span className="text-[var(--text-secondary)]">Клиент платит картой/СБП</span>
                      <span className="font-semibold">{rub(fiatAfterBalance)} ₽</span>
                    </div>
                  )}
                  <p className="text-[11px] text-[var(--text-muted)] pt-1">
                    Крипта остаётся по полной сумме заказа. Списывается до оплаты картой.
                  </p>
                </div>
              )}
              {applyBalance && buyerAvailableRub > 0 && fiatForBalance <= 0 && (
                <p className="text-[11px] text-[var(--text-muted)]">Укажите сумму — покажем сколько спишется с баланса.</p>
              )}
              {buyerAvailableRub <= 0 && (
                <p className="text-[11px] text-[var(--text-muted)]">У клиента нет доступного баланса для списания.</p>
              )}
            </div>
          )}

          {isBuy && buyer && (
            <div className="rounded-[var(--radius)] border border-[var(--border)] bg-[var(--bg-elevated)] p-3 space-y-3">
              <div className="text-[12px] font-semibold text-[var(--text-primary)]">Купоны клиента</div>
              {discountsLoading ? (
                <p className="text-[11px] text-[var(--text-muted)]">Загрузка купонов…</p>
              ) : buyerDiscounts.length === 0 ? (
                <p className="text-[11px] text-[var(--text-muted)]">
                  У клиента нет активных купонов на скидку.
                  {fiatBeforeDiscount > 0 ? " Выдайте купон в разделе «Промо»." : " Укажите сумму — покажем подходящие купоны."}
                </p>
              ) : (
                <div className="space-y-2">
                  <Field label="Применить купон">
                    <Select
                      value={selectedDiscountId ?? ""}
                      onChange={(e) => {
                        const v = e.target.value;
                        setSelectedDiscountId(v ? parseInt(v, 10) : null);
                      }}
                    >
                      <option value="">Без купона</option>
                      {buyerDiscounts.map((d) => {
                        const applied = d.preview_applied_rub ?? 0;
                        const min = d.min_order_rub > 0 ? ` · от ${rub(d.min_order_rub)} ₽` : "";
                        const suffix =
                          applied > 0
                            ? ` (−${rub(applied)} ₽)`
                            : fiatBeforeDiscount > 0
                              ? " (не подходит к сумме)"
                              : "";
                        return (
                          <option key={d.id} value={d.id}>
                            {d.promo_code}: {rub(d.amount_rub)} ₽{min}
                            {suffix}
                          </option>
                        );
                      })}
                    </Select>
                  </Field>
                  {selectedDiscount && discountPreviewRub > 0 && (
                    <div className="rounded-[var(--radius-sm)] border border-[var(--border)] bg-[var(--bg)] p-3 text-[12px] space-y-1">
                      <div className="flex justify-between">
                        <span className="text-[var(--text-muted)]">Скидка по купону</span>
                        <span className="font-medium text-[var(--yellow)]">−{rub(discountPreviewRub)} ₽</span>
                      </div>
                      {fiatAfterDiscount != null && (
                        <div className="flex justify-between border-t border-[var(--border)] pt-2">
                          <span className="text-[var(--text-secondary)]">После купона</span>
                          <span className="font-semibold">{rub(fiatAfterDiscount)} ₽</span>
                        </div>
                      )}
                    </div>
                  )}
                  {selectedDiscount &&
                    discountPreviewRub <= 0 &&
                    fiatBeforeDiscount > 0 &&
                    (selectedDiscount.min_order_rub ?? 0) > fiatBeforeDiscount && (
                      <p className="text-[11px] text-[var(--text-muted)]">
                        Купон действует от {rub(selectedDiscount.min_order_rub)} ₽.
                      </p>
                    )}
                </div>
              )}
            </div>
          )}

          {payFromProject ? (
            <div className="flex flex-wrap items-center justify-between gap-2 rounded-[var(--radius)] bg-[var(--green-bg)] p-3 text-[12px] text-[var(--green)]">
              <span>Крипту отправит кошелёк проекта — после проверки суммы и кода 2FA.</span>
              <button type="button" className="underline underline-offset-2" onClick={() => setOwnWallet(true)}>
                Отправил со своего — вставить хэш
              </button>
            </div>
          ) : requiresTxHash ? (
            <Field label="Хэш транзакции выплаты">
              <Input value={txHash} onChange={(e) => setTxHash(e.target.value)} className="font-mono" placeholder="tx hash" />
              {projectWalletAvailable && (
                <button
                  type="button"
                  className="mt-1 text-[11px] text-[var(--text-muted)] underline underline-offset-2"
                  onClick={() => {
                    setOwnWallet(false);
                    setTxHash("");
                  }}
                >
                  Отправить с кошелька проекта
                </button>
              )}
            </Field>
          ) : isBuy ? (
            <div className="rounded-[var(--radius)] bg-[var(--yellow-bg)] p-3 text-[12px] text-[var(--yellow)]">
              После сохранения заявка попадёт в очередь финансового оператора. Хэш выплаты вводит только роль «Финансы».
            </div>
          ) : null}

          <Field label={isBuy ? "Кошелёк клиента (куда зачислена крипта)" : "Реквизиты выплаты клиенту"}>
            <Input
              value={isBuy ? wallet : requisites}
              onChange={(e) => (isBuy ? setWallet(e.target.value) : setRequisites(e.target.value))}
              className="font-mono"
            />
          </Field>

          <Field label="Заметка (необязательно)">
            <Input value={note} onChange={(e) => setNote(e.target.value)} />
          </Field>

          <Button variant="primary" disabled={busy || !buyer} onClick={submit}>
            {busy
              ? "Фиксируем…"
              : isBuy && !isFinance
                ? "Передать финансовому оператору"
                : payFromProject
                  ? `Отправить ${crypto.toUpperCase()} с кошелька проекта`
                  : "Зафиксировать обмен"}
          </Button>
        </div>
      </Card>
      {sendBody && (
        <ProjectWalletSendModal
          open
          onClose={() => setSendBody(null)}
          loadPreview={() => previewNewOrderWalletSend(sendBody)}
          send={(wallet_send) => createOrder({ ...sendBody, wallet_send }) as Promise<{ txid?: string }>}
          onDone={() => navigate("/ops/orders")}
        />
      )}
    </>
  );
}
