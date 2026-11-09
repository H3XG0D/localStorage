/** Client-only casino wallet rules until deposit/withdraw APIs are wired. */

export const CARD_STEP_RUB = 250;
export const CARD_MIN_WITHDRAW_RUB = 20000;

export function formatRubGroup(value: number): string {
  return String(Math.round(value)).replace(/\B(?=(\d{3})+(?!\d))/g, " ");
}
export const CARD_WITHDRAW_FEE_RUB = 100;
export const DEPOSIT_CHIPS_RUB = [250, 500, 1000, 2500] as const;
export const WITHDRAW_CHIPS_RUB = [20000, 30000, 50000] as const;

export type WalletCrypto = "btc" | "ltc" | "trx" | "usdt";
export type WithdrawMethod = "card" | "crypto";
export type DepositPayMethod = "card" | "sbp";

export const WALLET_CRYPTOS: readonly WalletCrypto[] = ["btc", "ltc", "trx", "usdt"];
export const USDT_NETWORKS = ["TRC20", "ERC20", "BEP20"] as const;
export const BTC_WITHDRAW_FEE_USD = 2.5;
export const LTC_WITHDRAW_FEE_USD = 2.5;
export const TRX_WITHDRAW_FEE_USD = 2.5;
export const USDT_NETWORK_FEE_USD = 4;

export function parseRubAmount(raw: string): number | null {
  const n = Number(String(raw).replace(/\s/g, "").replace(",", "."));
  if (!Number.isFinite(n)) return null;
  return Math.round(n * 100) / 100;
}

export function isMultipleOfCardStep(amountRub: number): boolean {
  if (!Number.isFinite(amountRub) || amountRub <= 0) return false;
  const kopecks = Math.round(amountRub * 100);
  return kopecks % (CARD_STEP_RUB * 100) === 0;
}

export function amountStepError(amountRub: number | null): string | null {
  if (amountRub == null || amountRub <= 0) return "Укажите сумму";
  if (!isMultipleOfCardStep(amountRub)) return `Сумма должна быть кратна ${CARD_STEP_RUB} ₽`;
  return null;
}

export function withdrawNetworkFeeRub(
  method: WithdrawMethod,
  crypto: WalletCrypto | null,
  usdtRub: number | null,
): { feeRub: number | null; feeUsd: number | null } {
  if (method === "card") {
    const feeUsd =
      usdtRub != null && usdtRub > 0
        ? Math.round((CARD_WITHDRAW_FEE_RUB / usdtRub) * 100) / 100
        : null;
    return { feeRub: CARD_WITHDRAW_FEE_RUB, feeUsd };
  }
  if (crypto === "btc" || crypto === "ltc" || crypto === "trx") {
    const feeUsd =
      crypto === "btc" ? BTC_WITHDRAW_FEE_USD : crypto === "ltc" ? LTC_WITHDRAW_FEE_USD : TRX_WITHDRAW_FEE_USD;
    if (usdtRub != null && usdtRub > 0) {
      return { feeRub: Math.round(feeUsd * usdtRub * 100) / 100, feeUsd };
    }
    return { feeRub: null, feeUsd };
  }
  if (crypto === "usdt") {
    if (usdtRub != null && usdtRub > 0) {
      return { feeRub: Math.round(USDT_NETWORK_FEE_USD * usdtRub * 100) / 100, feeUsd: USDT_NETWORK_FEE_USD };
    }
    return { feeRub: null, feeUsd: USDT_NETWORK_FEE_USD };
  }
  return { feeRub: 0, feeUsd: null };
}

export function payoutAmountRub(amountRub: number, feeRub: number | null): number | null {
  if (feeRub == null || !Number.isFinite(amountRub) || !Number.isFinite(feeRub)) return null;
  return Math.round((amountRub - feeRub) * 100) / 100;
}

export function withdrawSubmitError(opts: {
  amountRub: number | null;
  method: WithdrawMethod;
  crypto: WalletCrypto | null;
  usdtRub: number | null;
  requisites: string;
  availableRub?: number | null;
  remainingFiatOutRub?: number | null;
}): string | null {
  const step = amountStepError(opts.amountRub);
  if (step) return step;
  const amount = opts.amountRub as number;
  if (opts.method === "card" && amount < CARD_MIN_WITHDRAW_RUB) {
    return `Минимум для карты: ${formatRubGroup(CARD_MIN_WITHDRAW_RUB)} ₽`;
  }
  const fee = withdrawNetworkFeeRub(opts.method, opts.crypto, opts.usdtRub);
  const payout = payoutAmountRub(amount, fee.feeRub);
  if (fee.feeRub != null && (payout == null || payout <= 0)) {
    return `Сумма слишком мала: комиссия ${fee.feeRub.toFixed(2)} ₽`;
  }
  if (opts.availableRub != null && Number.isFinite(opts.availableRub) && amount > opts.availableRub + 0.01) {
    return `Недостаточно средств. Доступно: ${opts.availableRub.toFixed(2)} ₽`;
  }
  if (opts.method === "crypto" && cryptoWithdrawBlocked(opts.remainingFiatOutRub)) {
    return cryptoWithdrawBlockedMessage(Number(opts.remainingFiatOutRub));
  }
  if (opts.requisites.trim().length < 5) {
    return opts.method === "card" ? "Укажите номер карты" : "Укажите адрес кошелька";
  }
  if (opts.method === "crypto" && !opts.crypto) return "Укажите криптовалюту";
  return null;
}

export type PayoutRailSnapshot = {
  fiat_deposited_rub?: string | number;
  card_withdrawn_rub?: string | number;
  remaining_rub?: string | number;
  crypto_allowed?: boolean;
};

export function payoutRailRemaining(rail: PayoutRailSnapshot | null | undefined): number {
  if (rail?.crypto_allowed === true) return 0;
  const n = Number(rail?.remaining_rub ?? 0);
  if (!Number.isFinite(n) || n <= 0.01) return 0;
  return Math.round(n * 100) / 100;
}

export function cryptoWithdrawBlocked(remainingRub: number | null | undefined): boolean {
  return Number(remainingRub) > 0.01;
}

export function cryptoWithdrawBlockedMessage(remainingRub: number): string {
  return `Сначала выведите ${remainingRub.toFixed(2)} ₽ на карту`;
}

export function stubDepositRequisites(method: DepositPayMethod, amountRub: number): {
  methodLabel: string;
  lines: Array<{ label: string; value: string }>;
} {
  const sum = `${new Intl.NumberFormat("ru-RU", { maximumFractionDigits: 0 }).format(amountRub)} ₽`;
  if (method === "sbp") {
    return {
      methodLabel: "СБП",
      lines: [
        { label: "Телефон", value: "+7 900 123-45-67" },
        { label: "Получатель", value: "Иванов И. И." },
        { label: "Банк", value: "Т-Банк" },
        { label: "Сумма", value: sum },
      ],
    };
  }
  return {
    methodLabel: "Карта",
    lines: [
      { label: "Карта", value: "2200 7001 2345 6789" },
      { label: "Получатель", value: "ИВАНОВ ИВАН ИВАНОВИЧ" },
      { label: "Банк", value: "Т-Банк" },
      { label: "Сумма", value: sum },
    ],
  };
}

/** Playable wallet: pending withdrawals already reserved, wagering lock still spendable. */
export function spendableBalanceRub(row: {
  available_rub?: number | string | null;
  balance_rub?: number | string | null;
} | null | undefined): number {
  const available = Number(row?.available_rub);
  if (Number.isFinite(available) && available >= 0) return Math.round(available * 100) / 100;
  const balance = Number(row?.balance_rub);
  if (Number.isFinite(balance) && balance >= 0) return Math.round(balance * 100) / 100;
  return 0;
}

export function availableAfterWagering(availableRub: number, lockedRub: number): number {
  const available = Number(availableRub);
  const locked = Number(lockedRub);
  if (!Number.isFinite(available)) return 0;
  const lock = Number.isFinite(locked) && locked > 0 ? locked : 0;
  return Math.max(0, Math.round((available - lock) * 100) / 100);
}

export type WithdrawalPhase = "awaiting" | "processing" | "paid" | "rejected" | "canceled";

export const WITHDRAWAL_PHASE_COPY: Record<WithdrawalPhase, { label: string; hint: string }> = {
  awaiting: { label: "В ожидании", hint: "Заявка в очереди. Можно отменить." },
  processing: {
    label: "На выплате",
    hint: "Передана на выплату. Обычно зачисляем в течение 3 часов. Отменить нельзя.",
  },
  paid: { label: "Выплачено", hint: "" },
  rejected: { label: "Отклонено", hint: "Деньги на балансе." },
  canceled: { label: "Отменена", hint: "" },
};

export function withdrawalPhase(row: {
  phase?: string | null;
  status?: string | null;
  operator_id?: number | null;
} | null | undefined): WithdrawalPhase {
  const phase = String(row?.phase ?? "").trim();
  if (phase === "awaiting" || phase === "processing" || phase === "paid" || phase === "rejected" || phase === "canceled") {
    return phase;
  }
  const status = String(row?.status ?? "").trim().toLowerCase();
  if (status === "pending") return row?.operator_id != null ? "processing" : "awaiting";
  if (status === "paid" || status === "rejected" || status === "canceled") return status;
  return "awaiting";
}

export function isActiveWithdrawal(row: { phase?: string | null; status?: string | null } | null | undefined): boolean {
  const phase = withdrawalPhase(row);
  return phase === "awaiting" || phase === "processing";
}

export function withdrawalCancellable(row: {
  cancellable?: boolean;
  phase?: string | null;
  status?: string | null;
} | null | undefined): boolean {
  if (row?.cancellable === true) return true;
  if (row?.cancellable === false) return false;
  return withdrawalPhase(row) === "awaiting";
}

export function withdrawalStatusLabel(row: { status_label?: string | null; phase?: string | null; status?: string | null } | null | undefined): string {
  const label = String(row?.status_label ?? "").trim();
  if (label) return label;
  return WITHDRAWAL_PHASE_COPY[withdrawalPhase(row)].label;
}

export function withdrawalStatusHint(row: { status_hint?: string | null; phase?: string | null; status?: string | null } | null | undefined): string {
  const hint = String(row?.status_hint ?? "").trim();
  if (hint) return hint;
  return WITHDRAWAL_PHASE_COPY[withdrawalPhase(row)].hint;
}

export type WalletHistoryTab = "deposit" | "withdraw" | "games";
export type WalletStatusTone = "pending" | "success" | "fail" | "neutral";
export type LedgerKind = "deposit" | "game" | "other";

export type WalletLedgerLike = {
  type?: string | null;
  note?: string | null;
  order_id?: string | number | null;
  amount_rub?: string | number | null;
  created_at?: string | null;
};

const GAME_LEDGER_NOTE =
  /^(casino win\b|casino v2\b|focuslucky\b|fixed room\b|jackpot\b)/i;

export function withdrawalStatusTone(phase: WithdrawalPhase): WalletStatusTone {
  if (phase === "awaiting" || phase === "processing") return "pending";
  if (phase === "paid") return "success";
  return "fail";
}

export function gameResultTone(result: string | null | undefined): WalletStatusTone {
  const value = String(result ?? "").trim().toLowerCase();
  if (value === "win") return "success";
  if (value === "loss" || value === "refund") return "fail";
  return "neutral";
}

export function isCasinoGameLedgerNote(note: string | null | undefined): boolean {
  return GAME_LEDGER_NOTE.test(String(note ?? "").trim());
}

export function isCasinoDepositLedgerNote(
  note: string | null | undefined,
  orderId?: string | number | null,
): boolean {
  const text = String(note ?? "").trim();
  const oid = String(orderId ?? "");
  if (/^casino deposit\b/i.test(text)) return true;
  if (/deposit/i.test(oid) && !isCasinoGameLedgerNote(text)) return true;
  return false;
}

export function ledgerKind(entry: WalletLedgerLike | null | undefined): LedgerKind {
  const note = String(entry?.note ?? "");
  const type = String(entry?.type ?? "").trim().toLowerCase();
  const amount = Number(entry?.amount_rub ?? 0);
  if (isCasinoGameLedgerNote(note)) return "game";
  if (isCasinoDepositLedgerNote(note, entry?.order_id)) return "deposit";
  if (type === "accrual") return "deposit";
  if (type === "adjustment" && Number.isFinite(amount) && amount > 0 && /^промокод/i.test(note)) {
    return "deposit";
  }
  return "other";
}

export function isDepositLedgerEntry(entry: WalletLedgerLike | null | undefined): boolean {
  return ledgerKind(entry) === "deposit";
}

export function depositLedgerTitle(entry: WalletLedgerLike | null | undefined): string {
  const note = String(entry?.note ?? "").trim();
  const orderId = String(entry?.order_id ?? "");
  if (isCasinoDepositLedgerNote(note, orderId)) return "Пополнение";
  if (orderId.startsWith("clb:") || /level bonus/i.test(note)) return "Бонус уровня";
  if (/кешбек|cashback/i.test(note)) return "Кешбэк";
  if (/^промокод/i.test(note)) return note;
  if (note) return note.length > 64 ? `${note.slice(0, 61)}…` : note;
  return "Зачисление";
}

/** Stat tiles: never flash a fake 0 before the first ledger/withdrawals response. */
export function walletCountLabel(ready: boolean, count: number): string {
  if (!ready) return "—";
  const n = Number(count);
  return String(Number.isFinite(n) && n >= 0 ? n : 0);
}

export function unpackLedgerEntries(payload: unknown): WalletLedgerLike[] {
  if (Array.isArray(payload)) return payload as WalletLedgerLike[];
  if (payload && typeof payload === "object") {
    const rec = payload as { entries?: unknown; items?: unknown };
    if (Array.isArray(rec.entries)) return rec.entries as WalletLedgerLike[];
    if (Array.isArray(rec.items)) return rec.items as WalletLedgerLike[];
  }
  return [];
}

export function withdrawalsForHistoryTab<T extends { phase?: string | null; status?: string | null }>(
  rows: T[] | null | undefined,
): T[] {
  const active: T[] = [];
  const rest: T[] = [];
  for (const row of rows ?? []) {
    if (isActiveWithdrawal(row)) active.push(row);
    else rest.push(row);
  }
  return [...active, ...rest];
}

export function shortRequisites(method: string | null | undefined, requisites: string | null | undefined): string {
  const raw = String(requisites ?? "").replace(/\s/g, "");
  if (!raw) return "";
  if (String(method ?? "") === "card" && raw.length >= 4) return `•••• ${raw.slice(-4)}`;
  if (raw.length > 12) return `${raw.slice(0, 6)}…${raw.slice(-4)}`;
  return raw;
}

export const CASINO_PENDING_MAX = 5;
export const CASINO_CREATE_INTERVAL_MS = 5 * 60 * 1000;
export const CASINO_PENDING_MAX_MSG = "Можно держать не больше 5 заявок на вывод одновременно";

export function latestWithdrawalCreatedAtMs(
  rows: { created_at?: string | null }[] | null | undefined,
): number | null {
  let latest = 0;
  for (const row of rows ?? []) {
    const ms = Date.parse(String(row?.created_at ?? ""));
    if (Number.isFinite(ms) && ms > latest) latest = ms;
  }
  return latest > 0 ? latest : null;
}

export function casinoCreateWaitMessage(lastCreatedAtMs: number | null, nowMs = Date.now()): string | null {
  if (lastCreatedAtMs == null || !Number.isFinite(lastCreatedAtMs)) return null;
  const remaining = lastCreatedAtMs + CASINO_CREATE_INTERVAL_MS - nowMs;
  if (remaining <= 0) return null;
  const minutes = Math.max(1, Math.ceil(remaining / 60_000));
  return `Следующую заявку можно создать через ${minutes} мин.`;
}

export function casinoCreateBlockReason(opts: {
  activeCount: number;
  lastCreatedAtMs?: number | null;
  nowMs?: number;
}): string | null {
  if (opts.activeCount >= CASINO_PENDING_MAX) return CASINO_PENDING_MAX_MSG;
  return casinoCreateWaitMessage(opts.lastCreatedAtMs ?? null, opts.nowMs ?? Date.now());
}

export type CashierTab = "deposit" | "withdraw";
export type CashierMethodId = "sbp" | "card" | "btc" | "ltc" | "trx" | "usdt_trc20" | "usdt_erc20" | "usdt_bep20";

export type CashierMethod = {
  id: CashierMethodId;
  title: string;
  subtitle: string;
};

export const CASHIER_DEPOSIT_METHODS: readonly CashierMethod[] = [
  { id: "sbp", title: "СБП", subtitle: `от ${CARD_STEP_RUB} ₽` },
  { id: "card", title: "Карта", subtitle: `от ${CARD_STEP_RUB} ₽` },
  { id: "usdt_trc20", title: "USDT TRC20", subtitle: "перевод на адрес" },
  { id: "usdt_erc20", title: "USDT ERC20", subtitle: "перевод на адрес" },
  { id: "usdt_bep20", title: "USDT BEP20", subtitle: "перевод на адрес" },
  { id: "btc", title: "Bitcoin", subtitle: "перевод на адрес" },
  { id: "ltc", title: "Litecoin", subtitle: "перевод на адрес" },
];

export const CASHIER_WITHDRAW_METHODS: readonly CashierMethod[] = [
  { id: "card", title: "На карту", subtitle: `от ${formatRubGroup(CARD_MIN_WITHDRAW_RUB)} ₽ · комиссия ${CARD_WITHDRAW_FEE_RUB} ₽` },
  { id: "usdt_trc20", title: "USDT TRC20", subtitle: "комиссия $4" },
  { id: "usdt_erc20", title: "USDT ERC20", subtitle: "комиссия $4" },
  { id: "usdt_bep20", title: "USDT BEP20", subtitle: "комиссия $4" },
  { id: "btc", title: "Bitcoin", subtitle: `комиссия $${BTC_WITHDRAW_FEE_USD.toFixed(2)}` },
  { id: "ltc", title: "Litecoin", subtitle: `комиссия $${LTC_WITHDRAW_FEE_USD.toFixed(2)}` },
  { id: "trx", title: "Tron", subtitle: `комиссия $${TRX_WITHDRAW_FEE_USD.toFixed(2)}` },
];

export function cashierWithdrawFeeSubtitle(id: CashierMethodId, feeLabel: string): string {
  if (isFiatCashierMethod(id)) return `от ${formatRubGroup(CARD_MIN_WITHDRAW_RUB)} ₽ · комиссия ${feeLabel}`;
  return `комиссия ${feeLabel}`;
}

export function isFiatCashierMethod(id: CashierMethodId): boolean {
  return id === "sbp" || id === "card";
}

export function cashierAmountError(id: CashierMethodId, amountRub: number | null): string | null {
  if (isFiatCashierMethod(id)) return amountStepError(amountRub);
  if (amountRub == null || amountRub <= 0) return "Укажите сумму";
  return null;
}

export function cashierWithdrawSpec(id: CashierMethodId): {
  method: WithdrawMethod;
  crypto: WalletCrypto | null;
  network: (typeof USDT_NETWORKS)[number] | null;
} {
  if (id === "card" || id === "sbp") return { method: "card", crypto: null, network: null };
  if (id === "btc") return { method: "crypto", crypto: "btc", network: null };
  if (id === "ltc") return { method: "crypto", crypto: "ltc", network: null };
  if (id === "trx") return { method: "crypto", crypto: "trx", network: null };
  const network = id === "usdt_erc20" ? "ERC20" : id === "usdt_bep20" ? "BEP20" : "TRC20";
  return { method: "crypto", crypto: "usdt", network };
}

export function isCryptoCashierWithdraw(id: CashierMethodId): boolean {
  return cashierWithdrawSpec(id).method === "crypto";
}

export function stubCashierDepositRequisites(
  methodId: CashierMethodId,
  amountRub: number,
): { methodLabel: string; lines: Array<{ label: string; value: string }> } {
  if (methodId === "sbp" || methodId === "card") return stubDepositRequisites(methodId, amountRub);
  const sum = `${new Intl.NumberFormat("ru-RU", { maximumFractionDigits: 0 }).format(amountRub)} ₽`;
  if (methodId === "btc") {
    return {
      methodLabel: "Bitcoin",
      lines: [
        { label: "Сеть", value: "Bitcoin" },
        { label: "Адрес", value: "bc1qfocuspaydemo0000000000000000000wl" },
        { label: "Сумма", value: sum },
      ],
    };
  }
  if (methodId === "ltc") {
    return {
      methodLabel: "Litecoin",
      lines: [
        { label: "Сеть", value: "Litecoin" },
        { label: "Адрес", value: "ltc1qfocuspaydemo000000000000000000c0" },
        { label: "Сумма", value: sum },
      ],
    };
  }
  const network = methodId === "usdt_erc20" ? "ERC20" : methodId === "usdt_bep20" ? "BEP20" : "TRC20";
  return {
    methodLabel: `USDT ${network}`,
    lines: [
      { label: "Сеть", value: network },
      { label: "Адрес", value: network === "TRC20" ? "TFocusPayDemo11111111111111111111" : "0xFocusPayDemo000000000000000000000001" },
      { label: "Сумма", value: sum },
    ],
  };
}
