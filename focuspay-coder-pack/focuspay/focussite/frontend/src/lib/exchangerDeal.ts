export type MarkupMode = "on_deal" | "on_turnover";

export interface BillField {
  label: string;
  value: string;
}

const PHONE_RE = /^[\d+\s()-]{10,}$/;

function looksLikePhone(value: string): boolean {
  const digits = value.replace(/\D/g, "");
  return digits.length >= 10 && PHONE_RE.test(value.trim());
}

function formatPhone(value: string): string {
  const digits = value.replace(/\D/g, "");
  if (digits.length === 11 && digits.startsWith("7")) {
    return `+7 ${digits.slice(1, 4)} ${digits.slice(4, 7)} ${digits.slice(7, 9)} ${digits.slice(9)}`;
  }
  if (digits.length === 10) {
    return `+7 ${digits.slice(0, 3)} ${digits.slice(3, 6)} ${digits.slice(6, 8)} ${digits.slice(8)}`;
  }
  return value.trim();
}

function asBill(bill: unknown): Record<string, string> {
  if (!bill || typeof bill !== "object" || Array.isArray(bill)) return {};
  const out: Record<string, string> = {};
  for (const [key, value] of Object.entries(bill as Record<string, unknown>)) {
    if (value == null || value === "") continue;
    out[key] = typeof value === "object" ? JSON.stringify(value) : String(value);
  }
  return out;
}

export function normalizeBillFields(bill: unknown, subToken: string | null | undefined): BillField[] {
  const raw = asBill(bill);
  const sub = (subToken || "SBPRUB").toUpperCase();
  const bank = (raw.bank || raw.bankName || "").trim();
  const fio = (raw.fio || raw.holderName || "").trim();
  const reciver = (raw.reciver || raw.receiver || raw.card || raw.phone || "").trim();
  const fields: BillField[] = [];

  if (bank) fields.push({ label: "Банк", value: bank });

  if (sub === "SBPRUB") {
    const phoneRaw = looksLikePhone(fio) ? fio : looksLikePhone(reciver) ? reciver : "";
    const nameRaw = phoneRaw === fio ? reciver : phoneRaw === reciver ? fio : fio || reciver;
    if (phoneRaw) fields.push({ label: "Телефон СБП", value: formatPhone(phoneRaw) });
    if (nameRaw && nameRaw !== phoneRaw) fields.push({ label: "Получатель", value: nameRaw });
    else if (!phoneRaw && reciver) fields.push({ label: "Реквизит", value: reciver });
    else if (!phoneRaw && fio) fields.push({ label: "Реквизит", value: fio });
  } else {
    if (reciver) fields.push({ label: "Номер карты", value: reciver });
    if (fio) fields.push({ label: "ФИО", value: fio });
  }
  return fields;
}

export const CLIENT_PAY_MINUTES = 20;

export const BANNED_PAY_WARNING =
  "Не оплачивайте с МТС Банка и Уралсиба — такие переводы не принимаем.";

export function buildTelegramPaymentText(input: {
  client_pays_rub: number;
  sub_token?: string | null;
  payment?: { bill?: unknown; fiat_amount?: number };
  deal_id?: string | number | null;
}): string {
  const amount = input.payment?.fiat_amount ?? input.client_pays_rub;
  const method = String(input.sub_token || "SBPRUB").toUpperCase() === "CARDRUB" ? "Карта" : "СБП";
  const labeled = Object.fromEntries(
    normalizeBillFields(input.payment?.bill, input.sub_token).map((field) => [field.label, field.value]),
  );
  const requisite = labeled["Номер карты"] || labeled["Телефон СБП"] || labeled["Реквизит"] || "";
  const bank = labeled["Банк"] || "";
  const holder = labeled["ФИО"] || labeled["Получатель"] || "";
  const lines = ["⚡ Реквизит выдан", "", `⛔ ${BANNED_PAY_WARNING}`, ""];
  if (input.deal_id != null && String(input.deal_id).trim() !== "") {
    lines.push(`▸ Заявка: #${input.deal_id}`);
  }
  lines.push(`▸ Сумма: ${amount.toLocaleString("ru-RU")} ₽`);
  if (requisite) lines.push(`▸ Реквизит: ${requisite}`);
  if (bank) lines.push(`▸ Банк: ${bank}`);
  if (holder) lines.push(`▸ Получатель: ${holder}`);
  lines.push(`▸ Способ: ${method}`);
  lines.push(`▸ Срок оплаты: ${CLIENT_PAY_MINUTES} минут`);
  lines.push("", "📌 Переведите ровно эту сумму, одним платежом.");
  if (method === "СБП") lines.push("По СБП — только на указанный банк.");
  lines.push(
    "",
    "Чек лучше сразу PDF, сразу после перевода.",
    `Если деньги ушли, а чек пришёл позже ${CLIENT_PAY_MINUTES} минут — оплату не подтвердим, средства могут пропасть.`,
    "Если по чеку будут вопросы — попросим видео экрана. Без него заявку закроем.",
  );
  return lines.join("\n");
}

function fmtRub(n: number) {
  return n.toLocaleString("ru-RU", { maximumFractionDigits: 0 });
}

export function inputLabelForMode(
  mode: string | null | undefined,
  opts?: { unit?: "rub" | "crypto"; coin?: string },
): string {
  if (opts?.unit === "crypto") {
    const ticker = String(opts.coin || "usdt").toUpperCase();
    return mode === "on_turnover" ? `Сумма оплаты клиента, ${ticker}` : `Сумма на баланс, ${ticker}`;
  }
  return mode === "on_turnover" ? "Сумма оплаты клиента, ₽" : "Сумма на баланс, ₽";
}

export function cryptoToRub(amountCrypto: number, marketRub: number): number {
  if (!(amountCrypto > 0) || !(marketRub > 0)) return 0;
  return Math.round(amountCrypto * marketRub * 100) / 100;
}

export function rubToCryptoAmount(amountRub: number, marketRub: number): number {
  if (!(amountRub > 0) || !(marketRub > 0)) return 0;
  return Number((amountRub / marketRub).toFixed(8));
}

export function modeDescription(mode: string | null | undefined): string {
  if (mode === "on_turnover") {
    return "Вводите то, что платит клиент. Ваш процент снимаем с этой суммы, на баланс приходит остаток.";
  }
  return "Вводите то, что хотите на баланс. Клиенту сверху добавится ваш процент.";
}

export const WITHDRAW_FEE_USD: Record<string, number> = {
  usdt: 3,
  btc: 2,
  ltc: 2,
  trx: 2,
};

export function withdrawFeeUsd(crypto: string | null | undefined, fees?: Record<string, unknown> | null): number {
  const coin = String(crypto || "usdt").toLowerCase();
  const fromApi = fees && fees[coin] != null ? Number(fees[coin]) : NaN;
  if (fromApi > 0) return fromApi;
  return WITHDRAW_FEE_USD[coin] ?? WITHDRAW_FEE_USD.usdt;
}

export function minPayoutGrossUsd(crypto: string | null | undefined, fees?: Record<string, unknown> | null): number {
  return Math.round((withdrawFeeUsd(crypto, fees) + 0.01) * 100) / 100;
}

export function shopRateFromRapira(rapira: number, pct: number, mode: string | null | undefined): number {
  const p = Number(pct) || 0;
  if (!(rapira > 0)) return 0;
  if (mode === "on_turnover") return rapira / (1 - p / 100);
  return rapira * (1 + p / 100);
}

export function exampleAtAmount(
  amountRub: number,
  pct: number,
  mode: string | null | undefined,
  rapiraUsdt: number,
) {
  const calc = buildMarkupFormulaText(amountRub, pct, mode);
  const usdt = rapiraUsdt > 0 ? Math.round((calc.baseRub / rapiraUsdt) * 100) / 100 : 0;
  return {
    ...calc,
    usdt,
    rapiraUsdt,
    shopUsdt: shopRateFromRapira(rapiraUsdt, pct, mode),
  };
}

export function buildMarkupFormulaText(
  inputRub: number,
  pct: number,
  mode: string | null | undefined,
): { formulaText: string; baseRub: number; clientPaysRub: number; markupRub: number } {
  const p = Number(pct) || 0;
  if (mode === "on_turnover") {
    const clientPaysRub = Math.round(inputRub * 100) / 100;
    const baseRub = Math.round(inputRub * (1 - p / 100) * 100) / 100;
    return {
      baseRub,
      clientPaysRub,
      markupRub: Math.round((clientPaysRub - baseRub) * 100) / 100,
      formulaText: `${fmtRub(inputRub)} − ${p}% = ${fmtRub(baseRub)} ₽ на баланс. К оплате: ${fmtRub(clientPaysRub)} ₽`,
    };
  }
  const baseRub = Math.round(inputRub * 100) / 100;
  const clientPaysRub = Math.round(inputRub * (1 + p / 100) * 100) / 100;
  return {
    baseRub,
    clientPaysRub,
    markupRub: Math.round((clientPaysRub - baseRub) * 100) / 100,
    formulaText: `${fmtRub(inputRub)} + ${p}% = ${fmtRub(clientPaysRub)} ₽ к оплате. На баланс: ${fmtRub(baseRub)} ₽`,
  };
}

export function dealStep(deal: {
  status?: unknown;
  can_upload_receipt?: unknown;
  requires_receipt?: unknown;
  paid_confirmed_at?: unknown;
  receipt_submitted_at?: unknown;
}): number {
  const status = String(deal.status ?? "");
  if (status === "pending" || status === "confirmed") return 3;
  if (deal.can_upload_receipt || deal.requires_receipt || deal.paid_confirmed_at || deal.receipt_submitted_at) return 2;
  return 1;
}

export async function copyText(value: string): Promise<boolean> {
  try {
    await navigator.clipboard.writeText(value);
    return true;
  } catch {
    return false;
  }
}

export type CabinetMoneyUnit = "rub" | "usd";
export type CabinetDisplayCurrency = "rub" | "usd";
export const DISPLAY_CURRENCY_LS = "focuspay_exchanger_display_currency";

export function parseDisplayCurrency(raw: unknown): CabinetDisplayCurrency {
  return raw === "usd" ? "usd" : "rub";
}

export function readDisplayCurrency(): CabinetDisplayCurrency {
  try {
    return parseDisplayCurrency(window.localStorage.getItem(DISPLAY_CURRENCY_LS));
  } catch {
    return "rub";
  }
}

export function writeDisplayCurrency(currency: CabinetDisplayCurrency): void {
  window.localStorage.setItem(DISPLAY_CURRENCY_LS, currency);
}

function formatUsdAmount(value: number): string {
  return `$${new Intl.NumberFormat("ru-RU", { maximumFractionDigits: 2 }).format(value)}`;
}

function formatRubAmount(value: number): string {
  return `${new Intl.NumberFormat("ru-RU", { maximumFractionDigits: 0 }).format(value)} ₽`;
}

export function convertCabinetAmount(
  amount: number,
  from: CabinetMoneyUnit,
  currency: CabinetDisplayCurrency,
  usdtRub: number,
): { value: number; unit: CabinetMoneyUnit; converted: boolean } {
  const src = Number.isFinite(amount) ? amount : 0;
  if (from === currency) return { value: src, unit: from, converted: true };
  if (!(usdtRub > 0)) return { value: src, unit: from, converted: false };
  if (from === "rub") return { value: src / usdtRub, unit: "usd", converted: true };
  return { value: src * usdtRub, unit: "rub", converted: true };
}

export function formatCabinetMoney(
  amount: number,
  from: CabinetMoneyUnit,
  currency: CabinetDisplayCurrency,
  usdtRub: number,
): string {
  const { value, unit } = convertCabinetAmount(amount, from, currency, usdtRub);
  return unit === "usd" ? formatUsdAmount(value) : formatRubAmount(value);
}

export function normalizeHistoryItem(item: Record<string, unknown>): Record<string, unknown> {
  const kind =
    item.kind === "payout" || item.kind === "deal"
      ? item.kind
      : item.gross_usd != null && item.client_pays_rub == null && item.amount_rub == null
        ? "payout"
        : "deal";
  return {
    ...item,
    kind,
    at: item.at ?? item.created_at ?? null,
    amount_rub: item.amount_rub ?? item.client_pays_rub ?? null,
    amount_usd: item.amount_usd ?? item.principal_usdt ?? item.total_credit_usdt ?? null,
  };
}
