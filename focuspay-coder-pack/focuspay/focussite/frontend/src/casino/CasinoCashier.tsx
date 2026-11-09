import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react";
import { Link, useLocation, useNavigate } from "react-router-dom";
import { Bitcoin, Check, Coins, CreditCard, Hexagon, Landmark, Wallet, X } from "lucide-react";
import { toast } from "sonner";
import { ApiError } from "@/lib/api";
import { CARD_WITHDRAW_PROMISE } from "@/lib/cardWithdrawCopy";
import { getCasinoPlayer, getRates } from "@/lib/public";
import {
  getBalance,
  getWithdrawals,
  cancelWithdrawal,
  withdraw,
  getCasinoCryptoDeposits,
  issueCasinoCryptoAddress,
  type CasinoCryptoAddress,
  type CasinoCryptoCoin,
  type CasinoCryptoDeposit,
  type WithdrawalRow,
} from "@/lib/user";
import { formatCasinoAmount, formatFeeLabel, useCasinoCurrency } from "./casinoCurrency";
import { CASINO_BALANCE_EVENT } from "./gameCatalog";
import { CASINO_DEPOSIT_HASH, CASINO_WITHDRAW_HASH, casinoTo } from "./casinoPaths";
import { CasinoWithdrawalCard } from "./CasinoWithdrawalCard";
import {
  CARD_MIN_WITHDRAW_RUB,
  CARD_STEP_RUB,
  CASHIER_WITHDRAW_METHODS,
  DEPOSIT_CHIPS_RUB,
  WITHDRAW_CHIPS_RUB,
  WITHDRAWAL_PHASE_COPY,
  availableAfterWagering,
  casinoCreateBlockReason,
  cashierWithdrawFeeSubtitle,
  cashierWithdrawSpec,
  cryptoWithdrawBlocked,
  cryptoWithdrawBlockedMessage,
  isActiveWithdrawal,
  isCryptoCashierWithdraw,
  isFiatCashierMethod,
  latestWithdrawalCreatedAtMs,
  parseRubAmount,
  payoutAmountRub,
  payoutRailRemaining,
  withdrawNetworkFeeRub,
  withdrawSubmitError,
  type CashierMethodId,
  type CashierTab,
} from "./casinoWalletRules";

type CashierContextValue = {
  open: boolean;
  tab: CashierTab;
  openCashier: (tab?: CashierTab) => void;
  closeCashier: () => void;
  setTab: (tab: CashierTab) => void;
};

const CasinoCashierContext = createContext<CashierContextValue>({
  open: false,
  tab: "deposit",
  openCashier: () => undefined,
  closeCashier: () => undefined,
  setTab: () => undefined,
});

export function useCasinoCashier(): CashierContextValue {
  return useContext(CasinoCashierContext);
}

function tabFromHash(hash: string): CashierTab | null {
  if (hash === `#${CASINO_DEPOSIT_HASH}`) return "deposit";
  if (hash === `#${CASINO_WITHDRAW_HASH}`) return "withdraw";
  return null;
}

export function CasinoCashierProvider({ children }: { children: ReactNode }) {
  const location = useLocation();
  const navigate = useNavigate();
  const pathRef = useRef(location.pathname);
  const initialTab = tabFromHash(location.hash);
  const [open, setOpen] = useState(Boolean(initialTab));
  const [tab, setTab] = useState<CashierTab>(initialTab ?? "deposit");

  const clearHash = useCallback(() => {
    if (location.hash !== `#${CASINO_DEPOSIT_HASH}` && location.hash !== `#${CASINO_WITHDRAW_HASH}`) return;
    navigate({ pathname: location.pathname, search: location.search, hash: "" }, { replace: true });
  }, [location.hash, location.pathname, location.search, navigate]);

  const openCashier = useCallback((next: CashierTab = "deposit") => {
    setTab(next);
    setOpen(true);
  }, []);

  const closeCashier = useCallback(() => {
    setOpen(false);
    clearHash();
  }, [clearHash]);

  useEffect(() => {
    if (pathRef.current === location.pathname) return;
    pathRef.current = location.pathname;
    setOpen(false);
  }, [location.pathname]);

  useEffect(() => {
    if (location.hash === `#${CASINO_DEPOSIT_HASH}`) {
      setTab("deposit");
      setOpen(true);
      return;
    }
    if (location.hash === `#${CASINO_WITHDRAW_HASH}`) {
      setTab("withdraw");
      setOpen(true);
    }
  }, [location.hash]);

  const value = useMemo(
    () => ({ open, tab, openCashier, closeCashier, setTab }),
    [closeCashier, open, openCashier, tab],
  );

  return <CasinoCashierContext.Provider value={value}>{children}</CasinoCashierContext.Provider>;
}

export function CasinoCashierHost() {
  const { open, tab, closeCashier } = useCasinoCashier();
  if (!open) return null;
  return <CasinoCashierDialog key={tab} tab={tab} onClose={closeCashier} />;
}

function CasinoCashierDialog({
  tab,
  onClose,
}: {
  tab: CashierTab;
  onClose: () => void;
}) {
  const [methodId, setMethodId] = useState<CashierMethodId | null>(null);
  const [amount, setAmount] = useState(String(CARD_STEP_RUB));
  const [requisites, setRequisites] = useState("");
  const [error, setError] = useState("");
  const [availableRub, setAvailableRub] = useState<number | null>(null);
  const [usdtRub, setUsdtRub] = useState<number | null>(null);
  const [remainingFiatOutRub, setRemainingFiatOutRub] = useState(0);
  const [submitting, setSubmitting] = useState(false);
  const [withdrawals, setWithdrawals] = useState<WithdrawalRow[]>([]);
  const [cancelling, setCancelling] = useState(false);
  const { currency } = useCasinoCurrency();

  const methods = CASHIER_WITHDRAW_METHODS;
  const method = methods.find((row) => row.id === methodId) ?? null;
  const parsed = parseRubAmount(amount);
  const withdrawSpec = methodId ? cashierWithdrawSpec(methodId) : null;
  const fee = withdrawSpec
    ? withdrawNetworkFeeRub(withdrawSpec.method, withdrawSpec.crypto, usdtRub)
    : { feeRub: null, feeUsd: null };
  const payout = parsed != null && fee.feeRub != null ? payoutAmountRub(parsed, fee.feeRub) : null;
  const feeLabel = formatFeeLabel(fee, currency, usdtRub);
  const cryptoLocked = cryptoWithdrawBlocked(remainingFiatOutRub);
  const railLockCopy = cryptoLocked ? cryptoWithdrawBlockedMessage(remainingFiatOutRub) : "";
  const activeWithdrawals = useMemo(() => withdrawals.filter(isActiveWithdrawal), [withdrawals]);
  const createBlock = casinoCreateBlockReason({
    activeCount: activeWithdrawals.length,
    lastCreatedAtMs: latestWithdrawalCreatedAtMs(withdrawals),
  });

  useEffect(() => {
    const prev = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      document.body.style.overflow = prev;
    };
  }, []);

  useEffect(() => {
    setMethodId(null);
    setError("");
    setRequisites("");
    setAmount(String(CARD_STEP_RUB));
  }, [tab]);

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.key !== "Escape") return;
      if (methodId) {
        setMethodId(null);
        setError("");
        return;
      }
      onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [methodId, onClose]);

  useEffect(() => {
    let cancelled = false;
    function reloadMoney() {
      Promise.allSettled([getBalance(), getCasinoPlayer("me"), getWithdrawals(30, "casino")]).then(
        ([balanceResult, playerResult, wdResult]) => {
          if (cancelled) return;
          const row = balanceResult.status === "fulfilled" ? balanceResult.value : null;
          const payload = playerResult.status === "fulfilled" ? playerResult.value : null;
          const locked = Number(payload?.own?.wagering.locked_rub ?? 0);
          const raw = Number(row?.available_rub ?? row?.balance_rub ?? payload?.own?.available_rub ?? 0);
          setAvailableRub(availableAfterWagering(raw, locked));
          const rail = payload?.own?.payout_rail ?? row?.payout_rail;
          setRemainingFiatOutRub(payoutRailRemaining(rail));
          if (wdResult.status === "fulfilled") {
            setWithdrawals(Array.isArray(wdResult.value.withdrawals) ? wdResult.value.withdrawals : []);
          }
        },
      );
    }
    reloadMoney();
    window.addEventListener(CASINO_BALANCE_EVENT, reloadMoney);
    const poll = window.setInterval(reloadMoney, 5000);
    getRates()
      .then((payload) => {
        if (cancelled) return;
        const rate = payload.rates.usdt?.sell || payload.rates.usdt?.market || 0;
        setUsdtRub(Number(rate) > 0 ? Number(rate) : null);
      })
      .catch(() => setUsdtRub(null));
    return () => {
      cancelled = true;
      window.clearInterval(poll);
      window.removeEventListener(CASINO_BALANCE_EVENT, reloadMoney);
    };
  }, []);

  function backToMethods() {
    setMethodId(null);
    setError("");
  }

  function pickMethod(id: CashierMethodId) {
    if (tab === "withdraw" && cryptoLocked && isCryptoCashierWithdraw(id)) {
      setError(railLockCopy);
      toast.error(railLockCopy);
      return;
    }
    setMethodId(id);
    setError("");
    setAmount(String(isFiatCashierMethod(id) ? CARD_MIN_WITHDRAW_RUB : CARD_STEP_RUB));
    setRequisites("");
  }

  async function onWithdraw() {
    if (!methodId || !withdrawSpec || submitting) return;
    if (createBlock) {
      setError(createBlock);
      toast.error(createBlock);
      return;
    }
    const err = withdrawSubmitError({
      amountRub: parsed,
      method: withdrawSpec.method,
      crypto: withdrawSpec.crypto,
      usdtRub,
      requisites,
      availableRub,
      remainingFiatOutRub,
    });
    if (err) {
      setError(err);
      toast.error(err);
      return;
    }
    setSubmitting(true);
    try {
      const created = await withdraw({
        amount_rub: parsed as number,
        method: withdrawSpec.method,
        requisites: requisites.trim(),
        crypto: withdrawSpec.crypto,
        network: withdrawSpec.network,
        source: "casino",
      });
      setError("");
      toast.success("Заявка на вывод создана");
      setWithdrawals((prev) => {
        if (prev.some((row) => row.id === created.id)) return prev;
        return [
          {
            id: created.id,
            amount_rub: created.amount_rub,
            status: created.status,
            phase: "awaiting",
            cancellable: true,
            status_label: WITHDRAWAL_PHASE_COPY.awaiting.label,
            status_hint: WITHDRAWAL_PHASE_COPY.awaiting.hint,
            method: withdrawSpec.method,
            crypto: withdrawSpec.crypto,
            network: withdrawSpec.network,
            requisites: requisites.trim(),
            created_at: new Date().toISOString(),
            source: "casino",
          },
          ...prev,
        ];
      });
      window.dispatchEvent(new Event(CASINO_BALANCE_EVENT));
      setMethodId(null);
      setRequisites("");
    } catch (caught) {
      const message = caught instanceof ApiError ? caught.message : "Не удалось создать вывод";
      setError(message);
      toast.error(message);
    } finally {
      setSubmitting(false);
    }
  }

  async function onCancelActive(id: number) {
    if (cancelling) return;
    setCancelling(true);
    try {
      await cancelWithdrawal(id);
      toast.success("Заявка отменена");
      window.dispatchEvent(new Event(CASINO_BALANCE_EVENT));
    } catch (caught) {
      const message = caught instanceof ApiError ? caught.message : "Не удалось отменить вывод";
      setError(message);
      toast.error(message);
    } finally {
      setCancelling(false);
    }
  }

  return (
    <div
      className="casino-cashier"
      role="dialog"
      aria-modal="true"
      aria-label={tab === "deposit" ? "Пополнение" : "Вывод"}
      data-casino-cashier=""
      data-casino-deposit={tab === "deposit" ? "" : undefined}
      data-casino-withdraw={tab === "withdraw" ? "" : undefined}
      data-casino-deposit-modal={tab === "deposit" ? "" : undefined}
      data-casino-withdraw-modal={tab === "withdraw" ? "" : undefined}
      onClick={onClose}
    >
      <div className="casino-cashier-sheet" onClick={(event) => event.stopPropagation()}>
        <header className="casino-cashier-head">
          <div>
            <h2>{tab === "deposit" ? "Пополнение" : "Вывод"}</h2>
            <p className="casino-muted">
              {tab === "deposit"
                ? "Баланс FocusBet"
                : availableRub != null
                  ? `Доступно к выводу ${formatCasinoAmount(availableRub, currency, usdtRub)}`
                  : "Баланс FocusBet"}
            </p>
            {tab === "withdraw" && cryptoLocked ? (
              <p className="casino-muted" data-casino-payout-rail-lock="">
                {railLockCopy}
              </p>
            ) : null}
          </div>
          <button type="button" className="casino-icon-btn" aria-label="Закрыть" onClick={onClose}>
            <X size={18} />
          </button>
        </header>

        {tab === "deposit" ? (
          <DepositPane />
        ) : (
          <>
            {activeWithdrawals.length ? (
              <div className="casino-cashier-active" data-casino-cashier-active="">
                {activeWithdrawals.map((row) => (
                  <CasinoWithdrawalCard
                    key={row.id}
                    row={row}
                    onCancel={onCancelActive}
                    cancelling={cancelling}
                  />
                ))}
              </div>
            ) : null}
            {createBlock ? (
              <p className="casino-muted" data-casino-withdraw-gate="">
                {createBlock}
              </p>
            ) : method ? (
          <div className="casino-cashier-step">
            <button type="button" className="casino-cashier-back" onClick={backToMethods}>
              ← Все способы
            </button>
            <div className="casino-cashier-picked">
              <span className="casino-cashier-method-icon" aria-hidden>
                {methodIcon(method.id)}
              </span>
              <div>
                <strong>{method.title}</strong>
                <p className="casino-muted">{cashierWithdrawFeeSubtitle(method.id, feeLabel)}</p>
              </div>
            </div>
            {isFiatCashierMethod(method.id) ? (
              <div className="casino-chip-row" role="group" aria-label="Сумма">
                {(tab === "withdraw" ? WITHDRAW_CHIPS_RUB : DEPOSIT_CHIPS_RUB).map((chip) => (
                  <button
                    key={chip}
                    type="button"
                    className={Number(amount) === chip ? "is-on" : ""}
                    onClick={() => {
                      setAmount(String(chip));
                      setError("");
                    }}
                  >
                    {chip} ₽
                  </button>
                ))}
              </div>
            ) : null}
            <label className="casino-field">
              Сумма, ₽
              <input
                inputMode="numeric"
                className="casino-mono"
                value={amount}
                onChange={(event) => {
                  setAmount(event.target.value);
                  setError("");
                }}
              />
            </label>
            <p className="casino-muted">
              Комиссия {feeLabel}
              {payout != null
                ? ` · к выплате ${formatCasinoAmount(payout, currency, usdtRub)}`
                : fee.feeUsd != null && fee.feeRub == null
                  ? " · к выплате после курса"
                  : null}
            </p>
            {tab === "withdraw" && withdrawSpec?.method === "card" ? (
              <>
                <p className="casino-muted">{CARD_WITHDRAW_PROMISE}</p>
                <p className="casino-muted">
                  На карту может прийти меньше на 10% — недостающее зачислим на баланс. Если больше, разницу доплатит FocusPay.
                </p>
              </>
            ) : null}
            <label className="casino-field">
              {withdrawSpec?.method === "card" ? "Номер карты" : "Адрес кошелька"}
              <input
                className="casino-mono"
                value={requisites}
                onChange={(event) => setRequisites(event.target.value)}
                placeholder={withdrawSpec?.method === "card" ? "0000 0000 0000 0000" : "Адрес получателя"}
              />
            </label>
            {error ? <p className="casino-duel-error">{error}</p> : null}
            <button
              type="button"
              className="casino-btn casino-wallet-submit"
              disabled={submitting}
              onClick={() => void onWithdraw()}
            >
              {submitting ? "Отправка…" : "Вывести средства"}
            </button>
          </div>
        ) : (
          <div
            className="casino-cashier-methods"
            data-casino-cashier-methods={tab}
            data-casino-payout-rail-lock={cryptoLocked ? "" : undefined}
          >
            {methods.map((row) => {
              const locked = cryptoLocked && isCryptoCashierWithdraw(row.id);
              const spec = cashierWithdrawSpec(row.id);
              const rowFee = withdrawNetworkFeeRub(spec.method, spec.crypto, usdtRub);
              const subtitle = locked
                ? railLockCopy
                : cashierWithdrawFeeSubtitle(row.id, formatFeeLabel(rowFee, currency, usdtRub));
              return (
                <button
                  key={row.id}
                  type="button"
                  className="casino-cashier-method"
                  disabled={locked}
                  aria-disabled={locked || undefined}
                  onClick={() => pickMethod(row.id)}
                >
                  <span className="casino-cashier-method-icon" aria-hidden>
                    {methodIcon(row.id)}
                  </span>
                  <span className="casino-cashier-method-copy">
                    <strong>{row.title}</strong>
                    <span>{subtitle}</span>
                  </span>
                </button>
              );
            })}
          </div>
            )}
          </>
        )}

        <p className="casino-cashier-history-link">
          <Link to={casinoTo("/casino/wallet")} onClick={onClose}>
            Кошелёк и история
          </Link>
        </p>
      </div>
    </div>
  );
}

const CRYPTO_DEPOSIT_COINS: { id: CasinoCryptoCoin; title: string }[] = [
  { id: "btc", title: "Bitcoin" },
  { id: "ltc", title: "Litecoin" },
];

function DepositPane() {
  return (
    <>
      <CryptoDepositBlock />
      <PromoDepositBlock />
    </>
  );
}

function CryptoDepositBlock() {
  const [coin, setCoin] = useState<CasinoCryptoCoin | null>(null);
  const [address, setAddress] = useState<CasinoCryptoAddress | null>(null);
  const [deposits, setDeposits] = useState<CasinoCryptoDeposit[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [copied, setCopied] = useState(false);
  const seenCredited = useRef<number | null>(null);

  const loadDeposits = useCallback(async () => {
    try {
      const res = await getCasinoCryptoDeposits();
      setDeposits(Array.isArray(res.deposits) ? res.deposits : []);
    } catch {
      /* История не блокирует показ адреса. */
    }
  }, []);

  const creditedCount = deposits.filter((row) => row.status === "credited").length;

  useEffect(() => {
    if (seenCredited.current != null && creditedCount > seenCredited.current) {
      window.dispatchEvent(new Event(CASINO_BALANCE_EVENT));
    }
    seenCredited.current = creditedCount;
  }, [creditedCount]);

  useEffect(() => {
    if (!coin) return;
    const timer = window.setInterval(() => {
      void loadDeposits();
    }, 15000);
    return () => window.clearInterval(timer);
  }, [coin, loadDeposits]);

  async function choose(next: CasinoCryptoCoin) {
    if (next === coin && address?.coin === next && !error) return;
    setCoin(next);
    if (address?.coin !== next) setAddress(null);
    setError("");
    setCopied(false);
    setLoading(true);
    try {
      const issued = await issueCasinoCryptoAddress(next);
      setAddress(issued);
      await loadDeposits();
    } catch (err) {
      const message = err instanceof ApiError ? err.message : "Адрес сейчас недоступен";
      setError(message || "Адрес сейчас недоступен");
    } finally {
      setLoading(false);
    }
  }

  async function copyAddress() {
    if (!address?.address) return;
    try {
      await navigator.clipboard.writeText(address.address);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1500);
    } catch {
      toast.error("Не удалось скопировать адрес");
    }
  }

  const visible = deposits.filter((row) => row.coin === (address?.coin ?? coin));
  const chosen = CRYPTO_DEPOSIT_COINS.find((row) => row.id === coin);
  const rateLabel = address?.rate != null && Number.isFinite(address.rate)
    ? new Intl.NumberFormat("ru-RU", { maximumFractionDigits: 2 }).format(address.rate)
    : "";
  const minLabel = address?.min_rub
    ? new Intl.NumberFormat("ru-RU").format(address.min_rub)
    : "";

  return (
    <div data-casino-crypto-deposit="">
      <p className="casino-promo-deposit-title">Выберите монету</p>
      <p className="casino-muted">У каждого игрока свой адрес. Перевод придёт только в выбранной монете.</p>
      <div className="casino-cashier-methods casino-crypto-coins" data-casino-crypto-coins="">
        {CRYPTO_DEPOSIT_COINS.map((row) => {
          const selected = coin === row.id;
          return (
            <button
              key={row.id}
              type="button"
              className={selected ? "casino-cashier-method is-selected" : "casino-cashier-method"}
              data-casino-crypto-coin={row.id}
              data-casino-crypto-selected={selected ? "true" : "false"}
              aria-pressed={selected}
              onClick={() => void choose(row.id)}
            >
              <span className="casino-cashier-method-icon" aria-hidden>
                {methodIcon(row.id)}
              </span>
              <span className="casino-cashier-method-copy">
                <strong>{row.title}</strong>
                <span>{selected ? "Выбрано" : "Выбрать"}</span>
              </span>
              {selected ? <Check className="casino-crypto-check" size={18} aria-hidden /> : null}
            </button>
          );
        })}
      </div>
      {loading ? <p className="casino-muted">Готовим адрес {chosen?.title ?? ""}…</p> : null}
      {error ? <p className="casino-muted" data-casino-crypto-error="">{error}</p> : null}
      {address && chosen ? (
        <div className="casino-crypto-pay" data-casino-crypto-pay="">
          <p className="casino-crypto-chosen">Выбрано: {chosen.title}</p>
          <p className="casino-muted">Адрес для перевода {chosen.title}</p>
          <p className="casino-mono casino-crypto-address" data-casino-crypto-address="">{address.address}</p>
          <button type="button" className="casino-btn casino-btn-ghost" onClick={() => void copyAddress()}>
            {copied ? "Скопировано" : "Скопировать адрес"}
          </button>
          {minLabel ? <p className="casino-crypto-min">Минимум пополнения — {minLabel} ₽</p> : null}
          <p className="casino-muted">{address.hint || "Зачислим после 1 подтверждения по курсу продажи"}</p>
          {rateLabel ? (
            <p className="casino-muted">Курс продажи 1 {chosen.title} сейчас около {rateLabel} ₽</p>
          ) : null}
          {visible.length ? (
            <ul className="casino-crypto-deposits">
              {visible.map((row) => (
                <li key={`${row.coin}:${row.txid}`}>
                  <span className="casino-mono">{row.amount_crypto} {row.coin.toUpperCase()}</span>
                  {" · "}
                  {row.status === "credited"
                    ? `Зачислено ${row.amount_rub ?? ""} ₽`
                    : "Меньше минимума, на баланс не зачислено"}
                </li>
              ))}
            </ul>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}

function PromoDepositBlock() {
  const [code, setCode] = useState("");
  const [status, setStatus] = useState("");
  const [submitting, setSubmitting] = useState(false);

  async function onActivate() {
    const value = code.trim().toUpperCase();
    if (!value) {
      setStatus("Введите промокод");
      return;
    }
    setSubmitting(true);
    setStatus("");
    try {
      const res = await fetch("/api/auth/promo/activate", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        credentials: "include",
        body: JSON.stringify({ promo_code: value }),
      });
      const payload = (await res.json().catch(() => null)) as { detail?: string; message?: string; bonus_rub?: number; bonus?: number } | null;
      if (!res.ok) {
        const message = payload?.detail || payload?.message || "Промокод не подошёл";
        setStatus(message);
        toast.error(message);
        return;
      }
      const credited = Number(payload?.bonus_rub ?? payload?.bonus);
      const message = Number.isFinite(credited) && credited > 0
        ? `Промокод применён: +${credited} ₽`
        : "Промокод применён";
      setStatus(message);
      toast.success(message);
      setCode("");
      window.dispatchEvent(new Event(CASINO_BALANCE_EVENT));
    } catch {
      setStatus("Не удалось проверить промокод");
      toast.error("Не удалось проверить промокод");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="casino-promo-deposit" data-casino-promo-deposit="">
      <p className="casino-promo-deposit-title">Промокод</p>
      <p className="casino-muted">Баланс FocusBet пополнится сразу после проверки кода.</p>
      <label className="casino-field">
        Промокод
        <input
          className="casino-mono"
          value={code}
          onChange={(event) => {
            setCode(event.target.value.toUpperCase());
            setStatus("");
          }}
          placeholder="FOCUS-2026"
          maxLength={32}
          autoComplete="off"
          spellCheck={false}
        />
      </label>
      {status ? <p className="casino-muted" data-casino-promo-status="">{status}</p> : null}
      <button
        type="button"
        className="casino-btn casino-wallet-submit"
        disabled={submitting || !code.trim()}
        onClick={() => void onActivate()}
      >
        {submitting ? "Проверка…" : "Активировать промокод"}
      </button>
    </div>
  );
}

function methodIcon(id: CashierMethodId) {
  if (id === "sbp") return <Landmark size={22} />;
  if (id === "card") return <CreditCard size={22} />;
  if (id === "btc") return <Bitcoin size={22} />;
  if (id === "ltc") return <Coins size={22} />;
  if (id === "trx") return <Hexagon size={22} />;
  return <Wallet size={22} />;
}
