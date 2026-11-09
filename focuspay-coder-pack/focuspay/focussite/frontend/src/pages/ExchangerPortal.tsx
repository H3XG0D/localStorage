import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, type ChangeEvent, type FormEvent, type HTMLAttributes, type ReactNode } from "react";
import {
  AlertTriangle,
  ArrowRight,
  Check,
  CheckCircle2,
  ChevronDown,
  CircleDollarSign,
  Clock3,
  Copy,
  Eye,
  EyeOff,
  FileCheck2,
  History,
  KeyRound,
  Landmark,
  Loader2,
  LockKeyhole,
  LogOut,
  MessageCircle,
  RefreshCw,
  Settings,
  ShieldCheck,
  Trash2,
  Upload,
  UserRound,
  Users,
  Wallet,
  XCircle,
} from "lucide-react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { toast } from "sonner";
import { AuthShell } from "@/components/AuthShell";
import { ExchangerChatPanel } from "@/components/ExchangerChatPanel";
import { PublicHeader } from "@/components/PublicHeader";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { ApiError, clearToken, getToken, setToken } from "@/lib/api";
import {
  buildMarkupFormulaText,
  buildTelegramPaymentText,
  copyText,
  cryptoToRub,
  dealStep,
  exampleAtAmount,
  formatCabinetMoney,
  inputLabelForMode,
  modeDescription,
  normalizeBillFields,
  normalizeHistoryItem,
  readDisplayCurrency,
  shopRateFromRapira,
  withdrawFeeUsd,
  writeDisplayCurrency,
  minPayoutGrossUsd,
  rubToCryptoAmount,
  type CabinetDisplayCurrency,
  type CabinetMoneyUnit,
} from "@/lib/exchangerDeal";
import { isLocalDev } from "@/lib/isLocalDev";
import { ExchangerHmacGuide } from "@/components/ExchangerHmacGuide";
import {
  exchangerAccounts,
  exchangerActiveDeals,
  exchangerApiKey,
  exchangerCancelDeal,
  exchangerChangePassword,
  exchangerConfirmPaid,
  exchangerCreateClerk,
  exchangerCreateDeal,
  exchangerCreatePayout,
  exchangerRubCardPayout,
  exchangerDeal,
  exchangerDealPreview,
  exchangerDashboard,
  exchangerHistory,
  exchangerLogin,
  exchangerLogin2FA,
  exchangerPayoutBalance,
  exchangerPayoutPreview,
  exchangerPayouts,
  exchangerRates,
  exchangerReki,
  exchangerResetAccountPassword,
  exchangerTotpConfirm,
  exchangerTotpDisable,
  exchangerTotpSetup,
  exchangerUpdateAccount,
  exchangerUploadReceipt,
  type ExchangerAccount,
  type ExchangerApiKey,
  type ExchangerCredentials,
  type ExchangerDashboard,
  type ExchangerRatesSnapshot,
  type ExchangerRekiSection,
  type ExchangerRekiSnapshot,
  type PortalRecord,
} from "@/lib/portals";
import { type CryptoId } from "@/lib/public";
import { cn, formatCrypto, formatDate, formatMoney } from "@/lib/utils";

type PortalTab = "overview" | "reki" | "payouts" | "history" | "chat" | "api" | "settings";
type DealChangeOpts = { close?: boolean; dealId?: number };
type HelpPref = "open" | "hidden" | "gone";
type HelpPrefs = Partial<Record<PortalTab, HelpPref>>;

const DEAL_STEPS = ["Реквизит", "PDF-чек", "Проверка"] as const;
const SHORTAGE_TEXT = "На балансе не хватает. Напишите старшему — пусть пополнит.";
const EXAMPLE_RUB = 1000;
const HELP_LS = "focuspay_exchanger_help_v1";
const RATE_COINS: CryptoId[] = ["usdt", "btc", "trx", "ltc"];
const SHELL = "portal-fluid";

const PAGE_HELP: Record<PortalTab, { title: string; steps: Array<{ n: string; title: string; text: string }> }> = {
  overview: {
    title: "Как это работает",
    steps: [
      { n: "1", title: "Укажите сумму", text: "Рубли или крипта, например 1.5243 LTC. СБП или карта. Что именно вы вводите — сумма клиента или сумма на баланс — зависит от вашей наценки." },
      { n: "2", title: "Получите реквизит", text: "Скопируйте банк, телефон или карту и отправьте клиенту. Сумму не округляйте." },
      { n: "3", title: "Клиент платит", text: "Клиент перевёл — загружаете PDF-чек. После проверки либо деньги на балансе (вывод потом сами), либо сразу заявка оператору на крипту." },
    ],
  },
  reki: {
    title: "Что здесь видно",
    steps: [
      { n: "1", title: "Свободные суммы", text: "Коридоры сумм, которые сейчас проходят по СБП и карте. Номеров реквизитов здесь нет — их выдаёт сделка." },
      { n: "2", title: "Подберите сумму", text: "Если нужной суммы нет в списке, возьмите ближайшую из свободного окна — реквизит выдастся сразу." },
      { n: "3", title: "Свежесть", text: "Данные обновляются раз в пару минут. Если помечено «устарело» — подождите следующего обновления." },
    ],
  },
  payouts: {
    title: "Как вывести",
    steps: [
      { n: "1", title: "Свой кошелёк", text: "Сумма в $, монета и адрес кошелька. Смотрите, сколько придёт «на руки» после комиссии." },
      { n: "2", title: "Одна заявка", text: "Пока одна заявка в работе, вторую не создадим. Дождитесь выплаты или отказа." },
      { n: "3", title: "Вывод ₽", text: "На карту или СБП комиссия 0%, курс — Рапира USDT, без вашей наценки. ФИО и банк — как в банке. Если баланса мало — напишите старшему, пусть пополнит." },
    ],
  },
  history: {
    title: "Что в истории",
    steps: [
      { n: "1", title: "Сделки и выводы", text: "Всё в одном списке: что оплатили клиенты и что вы вывели." },
      { n: "2", title: "Сделка", text: "Сколько заплатил клиент и сколько легло на баланс." },
      { n: "3", title: "Вывод", text: "Сколько сняли с баланса и сколько ушло на руки после комиссии." },
    ],
  },
  chat: {
    title: "Как писать оператору",
    steps: [
      { n: "1", title: "Сообщение здесь", text: "Пишите здесь. Оператор видит чат в очереди и отвечает в это же окно." },
      { n: "2", title: "Номер сделки", text: "Сразу напишите номер сделки или вывода — так быстрее найдут." },
      { n: "3", title: "Чек и видео", text: "Если PDF не прошёл, оператор напишет, что ещё нужно — обычно видео экрана." },
    ],
  },
  api: {
    title: "Как подключить API",
    steps: [
      { n: "1", title: "Ключ", text: "Ключ и секрет выдаёт администратор FocusPay. Секрет виден один раз. Ниже инструкция для программиста — можно скопировать или скачать." },
      { n: "2", title: "Реквизит клиенту", text: "POST /deals — клиенту показываете bill и сумму из client_pays_rub, как пришла, без своего округления." },
      { n: "3", title: "Чек", text: "Клиент оплатил: сначала POST …/paid, потом публичный URL PDF. Когда зачислим — придёт callback, либо смотрите статус." },
      { n: "4", title: "Отмена", text: "Клиент не заплатил — POST /deals/{id}/cancel с телом {}. Пока awaiting_receipt и чек не отправлен. Иначе 400." },
      { n: "5", title: "Статистика", text: "Пришлите client_stat со сделкой или POST /deals/{id}/client-stat. Без неё /check uuid покажет нового клиента. Fingerprint — id покупателя у вас." },
    ],
  },
  settings: {
    title: "Что здесь можно",
    steps: [
      { n: "1", title: "Пароль", text: "После первого входа сразу смените выданный пароль на свой." },
      { n: "2", title: "Второй фактор", text: "При каждом входе — код из приложения. Если пароль утечёт, без телефона не зайдут." },
      { n: "3", title: "Сотрудники", text: "Логины сотрудникам: реквизиты и чеки можно, выводы — нет." },
      { n: "4", title: "Валюта", text: "Рубли или доллар — это только как смотреть цифры, курс Рапира USDT. Сами сделки от этого не меняются." },
    ],
  },
};

type DisplayMoneyCtx = {
  currency: CabinetDisplayCurrency;
  usdtRub: number;
  rateOk: boolean;
  setCurrency: (next: CabinetDisplayCurrency) => void;
  money: (amount: unknown, from: CabinetMoneyUnit) => string;
};

const DisplayMoneyContext = createContext<DisplayMoneyCtx | null>(null);

function useDisplayMoney(): DisplayMoneyCtx {
  const ctx = useContext(DisplayMoneyContext);
  if (!ctx) {
    return {
      currency: "rub",
      usdtRub: 0,
      rateOk: false,
      setCurrency: () => undefined,
      money: (amount, from) => formatCabinetMoney(num(amount), from, "rub", 0),
    };
  }
  return ctx;
}

function readHelpPrefs(): HelpPrefs {
  try {
    const raw = JSON.parse(window.localStorage.getItem(HELP_LS) || "{}") as HelpPrefs;
    return raw && typeof raw === "object" && !Array.isArray(raw) ? raw : {};
  } catch {
    return {};
  }
}

function fmtRate(value: number, coin: string) {
  const digits = coin === "btc" ? 0 : 2;
  return value.toLocaleString("ru-RU", { minimumFractionDigits: digits, maximumFractionDigits: digits });
}

function Head({ className, ...props }: HTMLAttributes<HTMLDivElement>) {
  return <CardHeader className={cn("gap-1 p-3 pb-1.5", className)} {...props} />;
}

function Body({ className, ...props }: HTMLAttributes<HTMLDivElement>) {
  return <CardContent className={cn("px-3 pb-3 pt-0", className)} {...props} />;
}

function num(value: unknown) {
  const result = Number(value ?? 0);
  return Number.isFinite(result) ? result : 0;
}

function text(value: unknown, fallback = "—") {
  return value == null || String(value).trim() === "" ? fallback : String(value);
}

function record(value: unknown): PortalRecord {
  return value && typeof value === "object" && !Array.isArray(value) ? value as PortalRecord : {};
}

function crypto(value: unknown) {
  return text(value, "usdt").toUpperCase();
}

function useCountdown(expiresAt: string | null): string | null {
  const [, tick] = useState(0);
  useEffect(() => {
    const timer = window.setInterval(() => tick((n) => n + 1), 1000);
    return () => window.clearInterval(timer);
  }, []);
  if (!expiresAt) return null;
  const diff = new Date(expiresAt).getTime() - Date.now();
  if (!Number.isFinite(diff)) return null;
  if (diff <= 0) return "00:00";
  const total = Math.floor(diff / 1000);
  const h = Math.floor(total / 3600);
  const m = Math.floor((total % 3600) / 60);
  const s = total % 60;
  const pad = (n: number) => String(n).padStart(2, "0");
  return h > 0 ? `${pad(h)}:${pad(m)}:${pad(s)}` : `${pad(m)}:${pad(s)}`;
}

function countdownExpires(status: unknown, expiresAt: unknown) {
  if (!["awaiting_receipt", "pending"].includes(String(status))) return null;
  const raw = String(expiresAt || "").trim();
  return raw || null;
}

function DealCountdown({ status, expiresAt, className }: { status: unknown; expiresAt: unknown; className?: string }) {
  const countdown = useCountdown(countdownExpires(status, expiresAt));
  if (!countdown) return null;
  return (
    <span className={cn("inline-flex items-center gap-1 font-mono tabular-nums", countdown === "00:00" ? "text-destructive" : "text-muted-foreground", className)}>
      <Clock3 className="size-3.5" />
      {countdown}
    </span>
  );
}

function statusLabel(value: unknown) {
  const labels: Record<string, string> = {
    awaiting_receipt: "Ожидает оплаты",
    pending: "Проверяется",
    confirmed: "Зачислено",
    cancelled: "Отменено",
    paid: "Выплачено",
    rejected: "Отклонено",
  };
  return labels[String(value)] ?? text(value);
}

function statusVariant(value: unknown): "default" | "secondary" | "outline" | "muted" | "positive" | "warning" | "destructive" {
  const status = String(value);
  if (status === "confirmed" || status === "paid") return "positive";
  if (status === "pending" || status === "awaiting_receipt") return "warning";
  if (status === "cancelled" || status === "rejected") return "destructive";
  return "muted";
}

function errorMessage(error: unknown, fallback: string) {
  return error instanceof ApiError ? error.message : fallback;
}

async function loadHistoryQuiet(limit: number): Promise<{ items: PortalRecord[]; total: number }> {
  try {
    const result = await exchangerHistory({ limit });
    return {
      items: (result.items ?? []).map((item) => normalizeHistoryItem(record(item))),
      total: num(result.total),
    };
  } catch {
    return { items: [], total: 0 };
  }
}

function resolveMarkup(data: ExchangerDashboard | null, preview?: PortalRecord | null) {
  const pct = data?.markup_pct != null ? num(data.markup_pct) : preview?.markup_pct != null ? num(preview.markup_pct) : null;
  const mode = text(data?.markup_mode, text(preview?.markup_mode, "on_deal"));
  const hint = text(data?.markup_hint, modeDescription(mode));
  return { pct, mode, hint };
}

function dealActionLabel(deal: PortalRecord) {
  if (deal.can_upload_receipt || deal.paid_confirmed_at) return "Загрузить чек";
  return "Открыть реквизит";
}

export function ExchangerLoginPage() {
  const navigate = useNavigate();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [pending, setPending] = useState(false);
  const [preAuth, setPreAuth] = useState<string | null>(null);
  const [code, setCode] = useState("");

  useEffect(() => {
    if (getToken("exchanger") || isLocalDev()) navigate("/exchanger", { replace: true });
  }, [navigate]);

  async function submit(e: FormEvent) {
    e.preventDefault();
    setPending(true);
    try {
      const result = await exchangerLogin(username, password);
      if (result.requires_2fa && result.pre_auth_token) {
        setPreAuth(result.pre_auth_token);
        toast.info("Код из приложения, шесть цифр.");
        return;
      }
      if (result.access_token) {
        setToken("exchanger", result.access_token);
        navigate("/exchanger", { replace: true });
      }
    } catch (error) {
      toast.error(errorMessage(error, "Не удалось войти"));
    } finally {
      setPending(false);
    }
  }

  async function submit2FA(e: FormEvent) {
    e.preventDefault();
    if (!preAuth) return;
    setPending(true);
    try {
      const result = await exchangerLogin2FA(preAuth, code.trim());
      if (result.access_token) {
        setToken("exchanger", result.access_token);
        navigate("/exchanger", { replace: true });
      }
    } catch (error) {
      toast.error(errorMessage(error, "Неверный код"));
    } finally {
      setPending(false);
    }
  }

  if (preAuth) {
    return (
      <AuthShell hideSiteLink title="Подтверждение входа" subtitle="Откройте приложение с кодами и введите шесть цифр.">
        <form onSubmit={submit2FA} className="flex flex-col gap-5">
          <div className="flex flex-col gap-2">
            <Label htmlFor="exchanger-2fa">Код 2FA</Label>
            <div className="relative">
              <ShieldCheck className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-muted-foreground" />
              <Input id="exchanger-2fa" inputMode="numeric" value={code} onChange={(e) => setCode(e.target.value)} placeholder="000000" className="pl-10 font-mono tracking-[0.3em]" maxLength={8} autoFocus />
            </div>
          </div>
          <Button type="submit" size="lg" className="w-full" disabled={pending}>
            {pending ? "Проверяем…" : "Подтвердить"}
          </Button>
        </form>
      </AuthShell>
    );
  }

  return (
    <AuthShell hideSiteLink title="Вход в кабинет" subtitle="Берёте реквизит, отдаёте клиенту, после проверки деньги на балансе — потом вывод на свой кошелёк.">
      <form onSubmit={submit} className="flex flex-col gap-5">
        <div className="flex flex-col gap-2">
          <Label htmlFor="exchanger-login">Логин</Label>
          <div className="relative">
            <UserRound className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-muted-foreground" />
            <Input id="exchanger-login" autoComplete="username" value={username} onChange={(e) => setUsername(e.target.value)} className="pl-10" required />
          </div>
        </div>
        <div className="flex flex-col gap-2">
          <Label htmlFor="exchanger-password">Пароль</Label>
          <div className="relative">
            <LockKeyhole className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-muted-foreground" />
            <Input id="exchanger-password" type="password" autoComplete="current-password" value={password} onChange={(e) => setPassword(e.target.value)} className="pl-10" required />
          </div>
        </div>
        <Button type="submit" size="lg" className="w-full" disabled={pending}>
          {pending ? "Проверяем…" : "Войти"}
          {!pending && <ArrowRight data-icon="inline-end" />}
        </Button>
      </form>
    </AuthShell>
  );
}

export function ExchangerDashboardPage() {
  const navigate = useNavigate();
  const [params, setParams] = useSearchParams();
  const [data, setData] = useState<ExchangerDashboard | null>(null);
  const [loading, setLoading] = useState(true);
  const [selectedDeal, setSelectedDeal] = useState<PortalRecord | null>(null);
  const [dealsNonce, setDealsNonce] = useState(0);
  const [chatDraft, setChatDraft] = useState("");
  const tabParam = params.get("tab");
  const tab: PortalTab =
    tabParam === "reki" || tabParam === "payouts" || tabParam === "history" || tabParam === "chat" || tabParam === "api" || tabParam === "settings"
      ? tabParam
      : "overview";
  const [rates, setRates] = useState<ExchangerRatesSnapshot | null>(null);
  const [helpPrefs, setHelpPrefs] = useState<HelpPrefs>({});
  const [currency, setCurrencyState] = useState<CabinetDisplayCurrency>(() => readDisplayCurrency());
  const usdtRub = num(rates?.rates?.usdt?.market);
  const moneyCtx = useMemo<DisplayMoneyCtx>(() => ({
    currency,
    usdtRub,
    rateOk: usdtRub > 0,
    setCurrency: (next) => {
      writeDisplayCurrency(next);
      setCurrencyState(next);
    },
    money: (amount, from) => formatCabinetMoney(num(amount), from, currency, usdtRub),
  }), [currency, usdtRub]);

  const setTab = (next: PortalTab) => {
    setParams(next === "overview" ? {} : { tab: next }, { replace: true });
  };

  const loadDashboard = useCallback(async () => {
    try {
      setData(await exchangerDashboard());
    } catch (error) {
      if (error instanceof ApiError && error.status === 401) {
        clearToken("exchanger");
        if (!isLocalDev()) navigate("/exchanger/login", { replace: true });
      } else {
        toast.error(errorMessage(error, "Не удалось загрузить кабинет"));
      }
    } finally {
      setLoading(false);
    }
  }, [navigate]);

  useEffect(() => {
    if (!getToken("exchanger") && !isLocalDev()) {
      navigate("/exchanger/login", { replace: true });
      return;
    }
    void loadDashboard();
  }, [loadDashboard, navigate]);

  useEffect(() => {
    setHelpPrefs(readHelpPrefs());
    exchangerRates().then(setRates).catch(() => undefined);
  }, []);

  function setHelp(page: PortalTab, pref: HelpPref) {
    const next = { ...helpPrefs, [page]: pref };
    window.localStorage.setItem(HELP_LS, JSON.stringify(next));
    setHelpPrefs(next);
  }

  function restoreHelp() {
    const next: HelpPrefs = { overview: "open", payouts: "open", history: "open", chat: "open", api: "open", settings: "open" };
    window.localStorage.setItem(HELP_LS, JSON.stringify(next));
    setHelpPrefs(next);
  }

  const openDeal = useCallback(async (id: number) => {
    try {
      setSelectedDeal(await exchangerDeal(id));
    } catch (error) {
      toast.error(errorMessage(error, "Не удалось открыть сделку"));
    }
  }, []);

  const onDealCreated = useCallback(async (deal: PortalRecord) => {
    const id = num(deal.id);
    setDealsNonce((value) => value + 1);
    if (id) {
      try {
        setSelectedDeal(await exchangerDeal(id));
      } catch {
        setSelectedDeal(deal);
      }
    } else {
      setSelectedDeal(deal);
    }
    await loadDashboard();
  }, [loadDashboard]);

  const onDealChanged = useCallback(async (opts?: DealChangeOpts) => {
    setDealsNonce((value) => value + 1);
    await loadDashboard();
    if (opts?.close) {
      setSelectedDeal(null);
      return;
    }
    const id = opts?.dealId;
    if (!id) return;
    try {
      setSelectedDeal(await exchangerDeal(id));
    } catch {
      setSelectedDeal(null);
    }
  }, [loadDashboard]);

  function logout() {
    clearToken("exchanger");
    navigate("/exchanger/login", { replace: true });
  }

  const markup = resolveMarkup(data);
  const ratesSlot = <RapiraRatesStrip rates={rates} pct={markup.pct} mode={markup.mode} />;

  if (loading) {
    return (
      <DisplayMoneyContext.Provider value={moneyCtx}>
      <div className="min-h-dvh bg-background">
        <PublicHeader fluid compactBrand afterBrand={ratesSlot} hidePublicLinks homeTo="/exchanger" />
        <div className="flex justify-center py-16"><Loader2 className="size-6 animate-spin text-muted-foreground" /></div>
      </div>
      </DisplayMoneyContext.Provider>
    );
  }

  if (!data) {
    return (
      <DisplayMoneyContext.Provider value={moneyCtx}>
      <div className="min-h-dvh bg-background">
        <PublicHeader fluid compactBrand afterBrand={ratesSlot} hidePublicLinks homeTo="/exchanger" />
        <main className={SHELL}>
          {isLocalDev() && <PortalTabs tab={tab} onChange={setTab} isOwner />}
          <Card className="mt-6">
            <Body className="flex flex-col items-center gap-3 py-12 text-center text-sm text-muted-foreground">
              <p>Кабинет не загрузился. Обновите страницу.</p>
              <Button
                type="button"
                variant="outline"
                size="sm"
                onClick={() => {
                  setLoading(true);
                  void loadDashboard();
                }}
              >
                <RefreshCw className="size-4" /> Ещё раз
              </Button>
            </Body>
          </Card>
        </main>
      </div>
      </DisplayMoneyContext.Provider>
    );
  }

  const isOwner = data.is_owner !== false;

  return (
    <DisplayMoneyContext.Provider value={moneyCtx}>
    <div className={cn("min-h-dvh bg-background", tab === "chat" && "flex flex-col")}>
      <PublicHeader fluid compactBrand afterBrand={ratesSlot} hidePublicLinks homeTo="/exchanger" />
      <main className={cn(SHELL, "md:gap-5", tab === "chat" ? "flex min-h-0 flex-1 flex-col pb-1 md:flex-row md:items-stretch" : "md:flex md:items-start")}>
        <aside className="mb-3 flex flex-col gap-3 md:sticky md:top-[2.75rem] md:mb-0 md:w-52 md:shrink-0">
          <div className="flex items-start justify-between gap-2 md:block">
            <div className="min-w-0">
              <h1 className="portal-title truncate">{text(data.name, "Магазин")}</h1>
              <p className="mt-0.5 truncate text-xs text-muted-foreground">
                {text(data.username)}{isOwner ? "" : " · сотрудник"}
              </p>
            </div>
            <Button className="md:hidden" variant="ghost" size="icon" aria-label="Выйти" title="Выйти" onClick={logout}><LogOut className="size-4" /></Button>
          </div>
          <PortalTabs tab={tab} onChange={setTab} isOwner={isOwner} />
          <Button className="hidden justify-start md:inline-flex" variant="ghost" size="sm" onClick={logout}>
            <LogOut className="size-4" /> Выйти
          </Button>
        </aside>

        <div className={cn("min-w-0 flex-1", tab === "chat" && "flex min-h-0 flex-col")}>
        {tab === "overview" && (
          <OverviewPanel
            data={data}
            markup={markup}
            rates={rates}
            isOwner={isOwner}
            helpPrefs={helpPrefs}
            onHelp={setHelp}
            reloadToken={dealsNonce}
            onRefresh={loadDashboard}
            onOpenTab={setTab}
            onOpenDeal={(id) => void openDeal(id)}
            onDealCreated={onDealCreated}
          />
        )}
        {tab === "reki" && <RekiPanel helpPrefs={helpPrefs} onHelp={setHelp} />}
        {tab === "payouts" && isOwner && <PayoutsPanel onDashboardChanged={loadDashboard} helpPrefs={helpPrefs} onHelp={setHelp} />}
        {tab === "history" && <HistoryPanel helpPrefs={helpPrefs} onHelp={setHelp} />}
        {tab === "chat" && <ExchangerChatPanel helpPrefs={helpPrefs} onHelp={setHelp} draft={chatDraft} />}
        {tab === "api" && <ApiPanel isOwner={isOwner} helpPrefs={helpPrefs} onHelp={setHelp} />}
        {tab === "settings" && (
          <SettingsPanel
            data={data}
            isOwner={isOwner}
            helpPrefs={helpPrefs}
            onHelp={setHelp}
            onRestoreHelp={restoreHelp}
            onRefresh={loadDashboard}
          />
        )}
        </div>
        {selectedDeal && (
          <DealOverlay
            deal={selectedDeal}
            onClose={() => setSelectedDeal(null)}
            onChanged={onDealChanged}
            onMessageOperator={(id) => {
              setChatDraft(`#${id} `);
              setSelectedDeal(null);
              setTab("chat");
            }}
          />
        )}
      </main>
    </div>
    </DisplayMoneyContext.Provider>
  );
}

function RapiraRatesStrip({
  rates,
  pct,
  mode,
}: {
  rates: ExchangerRatesSnapshot | null;
  pct: number | null;
  mode: string;
}) {
  return (
    <div className="flex min-w-0 flex-1 items-center gap-0.5 overflow-x-auto [scrollbar-width:none] [&::-webkit-scrollbar]:hidden">
      <span className="shrink-0 pr-2 text-[10px] font-bold uppercase tracking-wide text-muted-foreground">
        Рапира{pct != null ? ` +${pct}%` : ""}
      </span>
      {RATE_COINS.map((coin) => {
        const rapira = num(rates?.rates?.[coin]?.market);
        const shop = pct != null && rapira > 0 ? shopRateFromRapira(rapira, pct, mode) : 0;
        return (
          <div key={coin} className="shrink-0 border-l border-border px-2">
            <p className="text-[10px] font-semibold leading-none tracking-wide text-muted-foreground">{coin.toUpperCase()}</p>
            <p className="mt-0.5 flex items-center gap-1 font-mono text-xs font-semibold tabular-nums leading-none">
              <span>{rapira > 0 ? fmtRate(rapira, coin) : "—"}</span>
              {pct != null && shop > 0 && (
                <>
                  <ArrowRight className="size-2.5 shrink-0 opacity-70" strokeWidth={2.5} aria-hidden />
                  <span>{fmtRate(shop, coin)}</span>
                </>
              )}
            </p>
          </div>
        );
      })}
    </div>
  );
}

function PageHelp({
  page,
  prefs,
  onChange,
}: {
  page: PortalTab;
  prefs: HelpPrefs;
  onChange: (page: PortalTab, pref: HelpPref) => void;
}) {
  const state = prefs[page] ?? (page === "api" ? "open" : "hidden");
  const copy = PAGE_HELP[page];
  if (state === "gone") return null;
  if (state === "hidden") {
    return (
      <button
        type="button"
        onClick={() => onChange(page, "open")}
        className="flex w-full items-center justify-between rounded-lg border border-dashed border-border px-3 py-2 text-left text-sm text-muted-foreground hover:text-foreground"
      >
        <span>Инструкция скрыта</span>
        <span className="inline-flex items-center gap-1 font-medium"><Eye className="size-4" /> Показать</span>
      </button>
    );
  }
  return (
    <Card>
      <Head className="flex-row items-start justify-between space-y-0 gap-3">
        <div>
          <CardTitle>{copy.title}</CardTitle>
        </div>
        <div className="flex shrink-0 gap-1">
          <Button type="button" variant="ghost" size="sm" onClick={() => onChange(page, "hidden")}>
            <EyeOff className="size-4" /> Скрыть
          </Button>
          <Button type="button" variant="ghost" size="sm" onClick={() => onChange(page, "gone")}>
            <Trash2 className="size-4" /> Убрать
          </Button>
        </div>
      </Head>
      <Body className="grid gap-2 sm:grid-cols-3">
        {copy.steps.map((step) => (
          <div key={step.n} className="rounded-md border border-border bg-muted/30 px-2.5 py-2">
            <p className="text-sm font-medium">{step.n}. {step.title}</p>
            <p className="mt-0.5 text-xs text-muted-foreground">{step.text}</p>
          </div>
        ))}
      </Body>
    </Card>
  );
}

function PortalTabs({ tab, onChange, isOwner }: { tab: PortalTab; onChange: (tab: PortalTab) => void; isOwner: boolean }) {
  const items: Array<{ id: PortalTab; label: string; icon: typeof CircleDollarSign }> = [
    { id: "overview", label: "Обзор", icon: CircleDollarSign },
    { id: "reki", label: "Активные реквизиты", icon: Landmark },
    ...(isOwner ? [{ id: "payouts" as PortalTab, label: "Выводы", icon: Wallet }] : []),
    { id: "history", label: "История", icon: History },
    { id: "chat", label: "Чат", icon: MessageCircle },
    { id: "api", label: "API", icon: KeyRound },
    { id: "settings", label: "Настройки", icon: Settings },
  ];
  return (
    <nav
      className="flex gap-1 overflow-x-auto border-b border-border md:flex-col md:overflow-visible md:border-b-0"
      aria-label="Разделы кабинета"
    >
      {items.map(({ id, label, icon: Icon }) => (
        <button
          key={id}
          type="button"
          onClick={() => onChange(id)}
          className={`flex shrink-0 items-center gap-1.5 px-3 py-2 text-sm font-medium transition-colors md:rounded-md md:px-2.5 md:py-1.5 ${
            tab === id
              ? "border-b-2 border-foreground text-foreground md:border-b-0 md:bg-muted"
              : "border-b-2 border-transparent text-muted-foreground hover:text-foreground md:border-b-0 md:hover:bg-muted/50"
          }`}
          aria-current={tab === id ? "page" : undefined}
        >
          <Icon className="size-4" /> {label}
        </button>
      ))}
    </nav>
  );
}

function OverviewPanel({
  data,
  markup,
  rates,
  isOwner,
  helpPrefs,
  onHelp,
  reloadToken,
  onRefresh,
  onOpenTab,
  onOpenDeal,
  onDealCreated,
}: {
  data: ExchangerDashboard;
  markup: { pct: number | null; mode: string; hint: string };
  rates: ExchangerRatesSnapshot | null;
  isOwner: boolean;
  helpPrefs: HelpPrefs;
  onHelp: (page: PortalTab, pref: HelpPref) => void;
  reloadToken: number;
  onRefresh: () => Promise<void>;
  onOpenTab: (tab: PortalTab) => void;
  onOpenDeal: (id: number) => void;
  onDealCreated: (deal: PortalRecord) => Promise<void>;
}) {
  const [fallback, setFallback] = useState<{ pct: number; mode: string } | null>(null);
  const [statsOpen, setStatsOpen] = useState(false);

  useEffect(() => {
    if (markup.pct != null) return;
    let cancelled = false;
    exchangerDealPreview(10000)
      .then((preview) => {
        if (cancelled || preview.markup_pct == null) return;
        setFallback({ pct: num(preview.markup_pct), mode: text(preview.markup_mode, "on_deal") });
      })
      .catch(() => undefined);
    return () => {
      cancelled = true;
    };
  }, [markup.pct]);

  const pct = markup.pct ?? fallback?.pct ?? null;
  const mode = markup.pct != null ? markup.mode : fallback?.mode ?? markup.mode;
  const hint = markup.pct != null ? markup.hint : modeDescription(mode);
  const { money, rateOk } = useDisplayMoney();
  const rapiraUsdt = num(rates?.rates?.usdt?.market);
  const example = pct != null ? exampleAtAmount(EXAMPLE_RUB, pct, mode, rapiraUsdt) : null;
  const shopUsdt = pct != null && rapiraUsdt > 0 ? shopRateFromRapira(rapiraUsdt, pct, mode) : 0;

  return (
    <div className="space-y-4 pt-1 md:pt-0">
      <PageHelp page="overview" prefs={helpPrefs} onChange={onHelp} />

      <div className="portal-overview-grid">
      <Card>
        <Head>
          <CardTitle className="text-lg">Ваши условия</CardTitle>
        </Head>
        <Body className="space-y-4">
          <p className="text-lg font-semibold md:text-xl">
            Ваша наценка: {pct != null ? `${pct}%` : "—"}
            <span className="ml-2 text-sm font-normal text-muted-foreground md:text-base">
              {mode === "on_turnover" ? "с суммы клиента" : "сверху к оплате"}
            </span>
          </p>
          <p className="text-sm text-muted-foreground md:text-base">{hint}</p>
          {example && (
            <div className="rounded-md border border-border bg-muted/30 px-3 py-3 text-sm md:text-base">
              <p className="font-medium">Пример на {money(EXAMPLE_RUB, "rub")}</p>
              {mode === "on_turnover" ? (
                <p className="mt-1 text-muted-foreground">
                  Клиент платит <b className="text-foreground">{money(example.clientPaysRub, "rub")}</b>.
                  Наценка {pct}% = {money(example.markupRub, "rub")}.
                  На баланс <b className="text-foreground">{money(example.baseRub, "rub")}</b>
                  {rapiraUsdt > 0 ? ` · ${formatCrypto(example.usdt)} USDT` : ""}.
                </p>
              ) : (
                <p className="mt-1 text-muted-foreground">
                  На баланс <b className="text-foreground">{money(example.baseRub, "rub")}</b>.
                  Клиент платит <b className="text-foreground">{money(example.clientPaysRub, "rub")}</b> (+{pct}%).
                  {rapiraUsdt > 0 ? ` · ${formatCrypto(example.usdt)} USDT.` : ""}
                </p>
              )}
              {rapiraUsdt > 0 && (
                <p className="mt-1 font-mono text-sm">
                  Рапира USDT {fmtRate(rapiraUsdt, "usdt")} ₽ → ваш курс (Рапира +{pct}%) {fmtRate(shopUsdt, "usdt")} ₽
                </p>
              )}
            </div>
          )}
          {!rateOk && (
            <p className="text-sm text-muted-foreground">Рапира сейчас не отвечает. Показываем суммы как есть, без перевода.</p>
          )}
          <div className="grid gap-2 sm:grid-cols-3">
            {isOwner && <MiniStat label="Комиссия вывода" value={`USDT ${money(3, "usd")} · BTC/LTC/TRX ${money(2, "usd")}`} />}
            {isOwner && <MiniStat label="Минимум к выводу" value={money(data.payout_threshold_usd, "usd")} />}
            <MiniStat label="Доступно" value={money(data.available_usd, "usd")} />
          </div>
          {isOwner ? (
            <div className="flex flex-wrap gap-2">
              <Button onClick={() => onOpenTab("payouts")}>Выплата на свой кошелёк <ArrowRight className="size-4" /></Button>
              <Button variant="outline" onClick={() => onOpenTab("payouts")}>Вывод ₽</Button>
              <Button variant="outline" onClick={() => onOpenTab("api")}><KeyRound className="size-4" /> API реквизитов</Button>
            </div>
          ) : (
            <div className="space-y-2">
              <p className="text-sm text-muted-foreground">С этого логина вывести нельзя. Баланс видно.</p>
              <Button variant="outline" onClick={() => onOpenTab("api")}><KeyRound className="size-4" /> Как подключить API</Button>
            </div>
          )}
        </Body>
      </Card>

      <DealCreator rates={rates} markupPct={pct} markupMode={mode} onCreated={onDealCreated} />
      </div>

      {data.has_pending_payout && (
        <Card className="border-amber-500/40">
          <Body className="flex items-start gap-3 py-3 text-sm">
            <RefreshCw className="mt-0.5 size-4 text-amber-600" />
            <div>
              <p className="font-medium">Вывод уже обрабатывается</p>
              <p className="mt-1 text-muted-foreground">Сейчас в работе {money(data.pending_payout_gross_usd, "usd")}. Дождитесь окончания — новую заявку пока не примем.</p>
            </div>
          </Body>
        </Card>
      )}

      <ActiveDealsCard reloadToken={reloadToken} onOpenDeal={onOpenDeal} />

      <OverviewHistory onOpenHistory={() => onOpenTab("history")} />

      <Card>
        <button type="button" className="flex w-full items-center justify-between px-3 py-2.5 text-left" onClick={() => setStatsOpen((value) => !value)}>
          <div>
            <p className="font-medium">Оборот и статистика</p>
            <p className="text-sm text-muted-foreground">Баланс {money(data.balance_usd, "usd")} · сделок {data.deal_count}</p>
          </div>
          <ChevronDown className={`size-4 text-muted-foreground transition-transform ${statsOpen ? "rotate-180" : ""}`} />
        </button>
        {statsOpen && (
          <Body className="grid grid-cols-2 gap-3 border-t border-border pt-4 sm:grid-cols-4">
            <MiniStat label="Оборот (база)" value={money(data.turnover_base_rub, "rub")} />
            <MiniStat label="Оборот клиента" value={money(data.turnover_client_rub, "rub")} />
            <MiniStat label="Начислено" value={money(data.total_credited_usd, "usd")} />
            <MiniStat label="Выплачено" value={money(data.total_paid_out_usd, "usd")} />
          </Body>
        )}
      </Card>

      <div className="flex justify-end"><Button variant="ghost" size="sm" onClick={() => void onRefresh()}><RefreshCw className="size-4" /> Обновить данные</Button></div>
    </div>
  );
}

function ActiveDealsCard({ reloadToken, onOpenDeal }: { reloadToken: number; onOpenDeal: (id: number) => void }) {
  const [deals, setDeals] = useState<PortalRecord[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    setLoading(true);
    exchangerActiveDeals().then((result) => setDeals(result.deals ?? [])).catch(() => undefined).finally(() => setLoading(false));
  }, [reloadToken]);

  if (!loading && deals.length === 0) return null;

  return (
    <Card>
      <Head>
        <CardTitle>Активные сделки</CardTitle>
      </Head>
      <Body>
        {loading ? <Loader2 className="size-5 animate-spin text-muted-foreground" /> : (
          <div className="divide-y divide-border">
            {deals.map((deal) => (
              <DealRow key={String(deal.id)} deal={deal} action={dealActionLabel(deal)} onClick={() => onOpenDeal(num(deal.id))} />
            ))}
          </div>
        )}
      </Body>
    </Card>
  );
}

function OverviewHistory({ onOpenHistory }: { onOpenHistory: () => void }) {
  const [items, setItems] = useState<PortalRecord[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    loadHistoryQuiet(8).then((result) => {
      setItems(result.items);
      setTotal(result.total);
    }).finally(() => setLoading(false));
  }, []);

  if (!loading && items.length === 0) return null;

  return (
    <Card>
      <Head className="flex-row items-center justify-between space-y-0">
        <CardTitle>Последние операции{total ? ` · ${total}` : ""}</CardTitle>
        <Button variant="ghost" size="sm" onClick={onOpenHistory}>История <ArrowRight className="size-4" /></Button>
      </Head>
      <Body>
        {loading ? <Loader2 className="size-5 animate-spin text-muted-foreground" /> : (
          <div className="divide-y divide-border">{items.map((item) => <HistoryRow key={`${String(item.kind)}-${String(item.id)}`} item={item} />)}</div>
        )}
      </Body>
    </Card>
  );
}

function DealCreator({
  rates,
  markupPct,
  markupMode,
  onCreated,
}: {
  rates: ExchangerRatesSnapshot | null;
  markupPct?: number | null;
  markupMode?: string | null;
  onCreated: (deal: PortalRecord) => Promise<void>;
}) {
  const [amount, setAmount] = useState("");
  const [unit, setUnit] = useState<"rub" | "crypto">("rub");
  const [coin, setCoin] = useState("usdt");
  const [subToken, setSubToken] = useState("SBPRUB");
  const [note, setNote] = useState("");
  const [clientIsNew, setClientIsNew] = useState(true);
  const [settlement, setSettlement] = useState<"balance" | "crypto">("balance");
  const [wallet, setWallet] = useState("");
  const [preview, setPreview] = useState<PortalRecord | null>(null);
  const [previewLoading, setPreviewLoading] = useState(false);
  const [busy, setBusy] = useState(false);
  const { money } = useDisplayMoney();

  const amountNum = num(amount);
  const coinRate = num(rates?.rates?.[coin as CryptoId]?.market);
  const amountRub =
    unit === "crypto"
      ? cryptoToRub(amountNum, coinRate) || num(preview?.input_rub)
      : amountNum;
  const mode = text(preview?.markup_mode, markupMode || "on_deal");
  const pct = preview?.markup_pct != null ? num(preview.markup_pct) : markupPct ?? null;
  const localFormula = amountRub > 0 && pct != null ? buildMarkupFormulaText(amountRub, pct, mode) : null;

  useEffect(() => {
    if (amountNum <= 0) {
      setPreview(null);
      setPreviewLoading(false);
      return;
    }
    setPreviewLoading(true);
    const timer = window.setTimeout(() => {
      const req =
        unit === "crypto"
          ? exchangerDealPreview({ amount_crypto: amountNum, crypto: coin })
          : exchangerDealPreview({ amount_rub: amountNum });
      req.then(setPreview).catch(() => setPreview(null)).finally(() => setPreviewLoading(false));
    }, 400);
    return () => window.clearTimeout(timer);
  }, [amountNum, unit, coin]);

  function switchUnit(next: "rub" | "crypto") {
    if (next === unit) return;
    if (amountNum > 0 && coinRate > 0) {
      setAmount(next === "crypto" ? String(rubToCryptoAmount(amountNum, coinRate)) : String(cryptoToRub(amountNum, coinRate)));
    }
    setUnit(next);
  }

  async function submit(e: FormEvent) {
    e.preventDefault();
    if (amountNum <= 0) return toast.error(unit === "crypto" ? `Укажите сумму в ${crypto(coin)}` : "Укажите сумму в рублях");
    if (settlement === "crypto" && wallet.trim().length < 8) return toast.error("Вставьте адрес кошелька — без него сразу в крипте не создадим.");
    setBusy(true);
    try {
      const created = await exchangerCreateDeal({
        ...(unit === "crypto" ? { amount_crypto: amountNum } : { amount_rub: amountNum }),
        crypto: coin,
        sub_token: subToken,
        note: note.trim() || undefined,
        client_is_new: clientIsNew,
        payout_on_credit: settlement === "crypto",
        payout_wallet: settlement === "crypto" ? wallet.trim() : undefined,
      });
      toast.success("Реквизит готов — отправьте клиенту.");
      setAmount("");
      setNote("");
      setWallet("");
      setPreview(null);
      await onCreated(created);
    } catch (error) {
      toast.error(errorMessage(error, "Не удалось получить реквизиты"));
    } finally {
      setBusy(false);
    }
  }

  const inputLabel = unit === "crypto" ? inputLabelForMode(mode, { unit: "crypto", coin }) : text(preview?.input_label, inputLabelForMode(mode));
  const formulaText = text(preview?.formula_text, localFormula?.formulaText ?? "");
  const fees = record(preview?.withdraw_fees);
  const feeUsd = withdrawFeeUsd(coin, fees);
  const principal = num(preview?.principal_usdt);
  const netUsd = settlement === "crypto" && principal > 0 ? Math.max(0, Math.round((principal - feeUsd) * 100) / 100) : principal;
  const feeTooHigh = settlement === "crypto" && principal > 0 && principal <= feeUsd;
  const approxRub = unit === "crypto" && amountNum > 0 ? amountRub || num(preview?.input_rub) : 0;
  const rateShown = coinRate > 0 ? coinRate : num(preview?.crypto_rate_rub);

  return (
    <Card className="portal-card">
      <Head>
        <CardTitle className="text-lg">Получить реквизиты</CardTitle>
      </Head>
      <Body>
        <form onSubmit={submit} className="portal-form-grid">
          <Field label={inputLabel}>
            <div className="flex gap-2">
              <Input
                type="number"
                min={unit === "crypto" ? "0" : "1"}
                step={unit === "crypto" ? "any" : "0.01"}
                value={amount}
                onChange={(e) => setAmount(e.target.value)}
                placeholder={unit === "crypto" ? "1.5243" : "например 50000"}
                className="h-11 flex-1 text-base"
              />
              <div className="flex h-11 shrink-0 rounded-lg border border-input p-0.5">
                <button
                  type="button"
                  onClick={() => switchUnit("rub")}
                  className={cn("min-w-10 rounded-md px-2.5 text-sm font-medium", unit === "rub" ? "bg-foreground text-background" : "text-muted-foreground hover:bg-muted/40")}
                >
                  ₽
                </button>
                <button
                  type="button"
                  onClick={() => switchUnit("crypto")}
                  className={cn("min-w-10 rounded-md px-2.5 text-sm font-medium", unit === "crypto" ? "bg-foreground text-background" : "text-muted-foreground hover:bg-muted/40")}
                >
                  {crypto(coin)}
                </button>
              </div>
            </div>
            {unit === "crypto" && amountNum > 0 && (
              <p className="text-sm text-muted-foreground">
                {approxRub > 0
                  ? `≈ ${money(approxRub, "rub")}${rateShown > 0 ? ` · курс ${crypto(coin)} ${fmtRate(rateShown, coin)} ₽` : ""}`
                  : previewLoading
                    ? "Считаем по Рапире…"
                    : "Рапира не ответила. Введите сумму в рублях"}
              </p>
            )}
          </Field>
          <Field label="Криптовалюта">
            <select value={coin} onChange={(e) => setCoin(e.target.value)} className={selectClass}>
              <option value="usdt">USDT</option>
              <option value="btc">BTC</option>
              <option value="trx">TRX</option>
              <option value="ltc">LTC</option>
            </select>
          </Field>
          <Field label="Способ оплаты клиента">
            <select value={subToken} onChange={(e) => setSubToken(e.target.value)} className={selectClass}>
              <option value="SBPRUB">СБП</option>
              <option value="CARDRUB">Карта</option>
            </select>
          </Field>
          <div className="flex items-end">
            <Button type="submit" className="h-11 w-full text-base" disabled={busy || amountNum <= 0}>
              {busy ? <Loader2 className="size-4 animate-spin" /> : <ArrowRight className="size-4" />} Получить реквизиты
            </Button>
          </div>
          <div className="grid gap-2 [grid-column:1/-1] sm:grid-cols-2">
            <button
              type="button"
              onClick={() => setSettlement("balance")}
              className={cn("rounded-lg border px-3 py-3 text-left transition-colors", settlement === "balance" ? "border-foreground bg-muted/40" : "border-border hover:bg-muted/20")}
            >
              <p className="font-medium">На баланс</p>
              <p className="mt-1 text-xs text-muted-foreground">Комиссии вывода нет. Когда накопите — выведете сами.</p>
            </button>
            <button
              type="button"
              onClick={() => setSettlement("crypto")}
              className={cn("rounded-lg border px-3 py-3 text-left transition-colors", settlement === "crypto" ? "border-foreground bg-muted/40" : "border-border hover:bg-muted/20")}
            >
              <p className="font-medium">Сразу в крипте</p>
              <p className="mt-1 text-xs text-muted-foreground">Чек пройдёт проверку — оператор отправит на кошелёк. Комиссия {money(feeUsd, "usd")}.</p>
            </button>
          </div>
          {settlement === "crypto" && (
            <div className="[grid-column:1/-1]">
              <Field label={`Кошелёк ${crypto(coin)}`}>
                <Input value={wallet} onChange={(e) => setWallet(e.target.value)} placeholder="куда отправить после зачисления" className="font-mono" />
              </Field>
            </div>
          )}
          <div className="[grid-column:1/-1]"><Field label="Комментарий (необязательно)"><textarea value={note} onChange={(e) => setNote(e.target.value)} rows={2} className={textareaClass} placeholder="имя клиента или своя пометка" /></Field></div>
          <label className="flex items-center gap-2 text-sm text-muted-foreground [grid-column:1/-1]">
            <input type="checkbox" checked={clientIsNew} onChange={(e) => setClientIsNew(e.target.checked)} className="size-4 accent-foreground" /> Этот клиент у нас первый раз
          </label>
        </form>
        {(preview || localFormula) && (
          <div className="mt-4 grid gap-3 rounded-lg border border-border bg-muted/30 p-3 text-sm sm:grid-cols-2 lg:grid-cols-4 md:text-base">
            <PreviewValue label="Клиент заплатит" value={money(preview?.client_pays_rub ?? localFormula?.clientPaysRub, "rub")} />
            <PreviewValue label={settlement === "crypto" ? "На руки после комиссии" : "На баланс"} value={settlement === "crypto" ? money(netUsd, "usd") : `${formatCrypto(principal)} ${crypto(coin)}`} />
            <PreviewValue label={settlement === "crypto" ? "Комиссия вывода" : "Наценка"} value={settlement === "crypto" ? `${money(feeUsd, "usd")} · ${crypto(coin)}` : (pct != null ? `${pct}% · ${money(preview?.markup_rub ?? localFormula?.markupRub, "rub")}` : "—")} />
            <PreviewValue label={previewLoading ? "Считаем…" : "Формула"} value={formulaText || "—"} />
          </div>
        )}
        {feeTooHigh && <p className="mt-3 text-sm text-amber-700">На зачисление не хватает даже комиссии {money(feeUsd, "usd")}. После проверки деньги останутся на балансе, на кошелёк не уйдут.</p>}
      </Body>
    </Card>
  );
}

function DealOverlay({
  deal,
  onClose,
  onChanged,
  onMessageOperator,
}: {
  deal: PortalRecord;
  onClose: () => void;
  onChanged: (opts?: DealChangeOpts) => Promise<void>;
  onMessageOperator: (id: number) => void;
}) {
  const [busy, setBusy] = useState<"confirm" | "cancel" | "receipt" | null>(null);
  const [copiedAll, setCopiedAll] = useState(false);
  const payment = record(deal.payment);
  const fields = normalizeBillFields(payment.bill, text(deal.sub_token, "SBPRUB"));
  const step = dealStep(deal);
  const canConfirm = Boolean(deal.can_confirm_paid) || (deal.status === "awaiting_receipt" && !deal.paid_confirmed_at);
  const canUpload = Boolean(deal.can_upload_receipt) || (deal.status === "awaiting_receipt" && Boolean(deal.paid_confirmed_at));
  const canCancel = Boolean(deal.can_cancel) || (deal.status === "awaiting_receipt" && !deal.receipt_submitted_at);
  const countdown = useCountdown(countdownExpires(deal.status, deal.expires_at));
  const { money, currency, rateOk } = useDisplayMoney();
  const payText =
    String(deal.payment_text || "").trim() ||
    buildTelegramPaymentText({
      client_pays_rub: num(deal.client_pays_rub),
      sub_token: text(deal.sub_token, "SBPRUB"),
      payment: { bill: payment.bill, fiat_amount: num(payment.fiat_amount) || undefined },
      deal_id: text(deal.id),
    });

  useEffect(() => {
    const previous = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    function onKey(event: KeyboardEvent) {
      if (event.key === "Escape") onClose();
    }
    window.addEventListener("keydown", onKey);
    return () => {
      document.body.style.overflow = previous;
      window.removeEventListener("keydown", onKey);
    };
  }, [onClose]);

  async function confirmPaid() {
    setBusy("confirm");
    try {
      await exchangerConfirmPaid(num(deal.id));
      toast.success("Отметили оплату. Теперь загрузите PDF-чек из банка.");
      await onChanged({ dealId: num(deal.id) });
    } catch (error) {
      toast.error(errorMessage(error, "Не удалось подтвердить оплату"));
    } finally {
      setBusy(null);
    }
  }

  async function cancel() {
    if (!window.confirm("Отменить сделку? Реквизит больше нельзя будет оплатить.")) return;
    setBusy("cancel");
    try {
      await exchangerCancelDeal(num(deal.id));
      toast.success("Сделка отменена");
      await onChanged({ close: true, dealId: num(deal.id) });
    } catch (error) {
      toast.error(errorMessage(error, "Не удалось отменить сделку"));
    } finally {
      setBusy(null);
    }
  }

  async function upload(event: ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0];
    event.target.value = "";
    if (!file) return;
    if (!file.name.toLowerCase().endsWith(".pdf")) return toast.error("Нужен файл .pdf из банка, не фото.");
    if (file.size > 10 * 1024 * 1024) return toast.error("Файл больше 10 МБ — сожмите или выгрузите заново.");
    setBusy("receipt");
    try {
      await exchangerUploadReceipt(num(deal.id), file);
      toast.success("Чек ушёл на проверку");
      await onChanged({ dealId: num(deal.id) });
    } catch (error) {
      toast.error(errorMessage(error, "Не удалось отправить чек"));
    } finally {
      setBusy(null);
    }
  }

  async function copyAll() {
    if (await copyText(payText)) {
      setCopiedAll(true);
      window.setTimeout(() => setCopiedAll(false), 2000);
    }
  }

  return (
    <div
      className="fixed inset-0 z-50 flex items-start justify-center overflow-y-auto bg-black/60 p-4 sm:items-center"
      role="dialog"
      aria-modal="true"
      aria-labelledby="exchanger-deal-title"
      onClick={onClose}
    >
      <div className="w-full max-w-lg py-6" onClick={(event) => event.stopPropagation()}>
        <Card className="border-foreground/20 shadow-xl">
          <Head className="flex-row items-start justify-between space-y-0">
            <div>
              <p className="text-xs uppercase tracking-[.16em] text-muted-foreground">Оплата заявки</p>
              <CardTitle id="exchanger-deal-title">Сделка #{text(deal.id)}</CardTitle>
              <CardDescription>{formatDate(text(deal.created_at, ""))} · {crypto(deal.crypto)}</CardDescription>
            </div>
            <div className="flex items-center gap-2">
              {countdown && (
                <span className={cn("inline-flex items-center gap-1 font-mono text-sm tabular-nums", countdown === "00:00" ? "text-destructive" : "text-muted-foreground")}>
                  <Clock3 className="size-4" />
                  {countdown}
                </span>
              )}
              <Button type="button" variant="ghost" size="icon" aria-label="Закрыть" title="Закрыть без отмены заявки" onClick={onClose}>
                <XCircle className="size-5" />
              </Button>
            </div>
          </Head>
          <Body className="space-y-3">
            {deal.status !== "cancelled" && (
              <div className="flex gap-1">
                {DEAL_STEPS.map((label, index) => {
                  const n = index + 1;
                  const active = step >= n;
                  const current = step === n;
                  return (
                    <div key={label} className="flex-1 text-center">
                      <div className={`mb-1.5 h-1 rounded-full ${active ? (current ? "bg-foreground" : "bg-foreground/40") : "bg-border"}`} />
                      <span className={`text-[10px] ${current ? "text-foreground" : "text-muted-foreground"}`}>{label}</span>
                    </div>
                  );
                })}
              </div>
            )}
            <div className="flex flex-wrap items-center gap-2">
              <Badge variant={statusVariant(deal.status)}>{statusLabel(deal.status)}</Badge>
              {Boolean(deal.payout_on_credit) && <Badge variant="secondary">{deal.payout_id ? "Выплата запрошена" : "Сразу в крипте"}</Badge>}
            </div>
            <CopyField label="Сумма к оплате" value={`${formatMoney(num(deal.client_pays_rub))} ₽`} />
            {currency === "usd" && rateOk && (
              <p className="text-sm text-muted-foreground">≈ {money(deal.client_pays_rub, "rub")}</p>
            )}
            <p className="text-sm text-muted-foreground">
              На баланс <b className="text-foreground">{money(deal.principal_usdt, "usd")}</b>
              {` · ${formatCrypto(num(deal.principal_usdt))} ${crypto(deal.crypto)}`}
              {deal.markup_pct != null ? ` · наценка ${num(deal.markup_pct)}%` : ""}
            </p>
            {Boolean(deal.payout_on_credit) && (
              <div className="rounded-lg border border-border bg-muted/30 p-3 text-sm">
                <p className="mb-2 font-medium">Выплата после зачисления</p>
                <p className="text-muted-foreground">
                  Комиссия {money(deal.payout_fee_usd ?? withdrawFeeUsd(text(deal.crypto)), "usd")} · {crypto(deal.crypto)}.
                  Оператор увидит заявку на выплату, когда чек пройдёт проверку.
                </p>
                {String(deal.payout_wallet || "").trim() ? (
                  <div className="mt-2"><CopyField label="Кошелёк" value={String(deal.payout_wallet).trim()} /></div>
                ) : null}
                {deal.payout_id ? <p className="mt-2 text-muted-foreground">Заявка на вывод #{text(deal.payout_id)}</p> : null}
              </div>
            )}
            {Boolean(deal.formula_text) && (
              <p className="rounded-lg border border-border bg-muted/30 px-3 py-2 text-sm text-muted-foreground">{text(deal.formula_text)}</p>
            )}
            <div className="rounded-lg border border-border bg-muted/30 p-3">
              <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
                <div className="flex items-center gap-2 font-medium"><Wallet className="size-4" /> Реквизиты оплаты</div>
                {fields.length > 0 && (
                  <Button type="button" variant="outline" size="sm" onClick={() => void copyAll()}>
                    {copiedAll ? <Check className="size-3.5" /> : <Copy className="size-3.5" />}
                    {copiedAll ? "Скопировано" : "Копировать всё"}
                  </Button>
                )}
              </div>
              {fields.length === 0 ? (
                <p className="text-sm text-muted-foreground">Реквизит появится, как только заявка создастся.</p>
              ) : (
                fields.map((field) => <CopyField key={field.label} label={field.label} value={field.value} />)
              )}
              {Boolean(payment.pay_link) && (
                <p className="mt-3 text-sm"><a className="underline" href={String(payment.pay_link)} target="_blank" rel="noreferrer">Открыть ссылку на оплату</a></p>
              )}
              {fields.length > 0 && (
                <>
                  <div className="mt-3 flex items-start gap-2 rounded-lg border border-destructive/30 bg-destructive/5 p-3 text-sm leading-6">
                    <AlertTriangle className="mt-0.5 size-4 shrink-0 text-destructive" />
                    <p>
                      <span className="font-medium">Не оплачивайте с МТС Банка и Уралсиба</span>
                      {" — такие переводы не принимаем."}
                    </p>
                  </div>
                  <p className="mt-2 text-xs text-muted-foreground">Переведите ровно эту сумму, одним платежом, за 20 минут. Чек лучше сразу PDF.</p>
                </>
              )}
            </div>
            <div className="grid gap-2 text-sm sm:grid-cols-2">
              <InfoRow label="Способ" value={text(deal.sub_token) === "CARDRUB" ? "Карта" : "СБП"} />
              <InfoRow label="Сделка" value={`#${text(deal.id)}`} />
            </div>
            <div className="flex flex-wrap gap-2 border-t border-border pt-3">
              {canConfirm && (
                <Button type="button" onClick={() => void confirmPaid()} disabled={busy !== null}>
                  <CheckCircle2 className="size-4" /> {busy === "confirm" ? "Сохраняем…" : "Я оплатил"}
                </Button>
              )}
              {canUpload && (
                <label className="inline-flex h-10 cursor-pointer items-center justify-center gap-2 rounded-lg border border-input bg-background px-4 py-2 text-sm font-medium transition-colors hover:bg-muted has-[:disabled]:pointer-events-none has-[:disabled]:opacity-50">
                  <Upload className="size-4" /> {busy === "receipt" ? "Отправляем…" : "Загрузить PDF-чек"}
                  <input type="file" accept="application/pdf,.pdf" className="sr-only" disabled={busy !== null} onChange={(event) => void upload(event)} />
                </label>
              )}
              <Button type="button" variant="outline" onClick={() => onMessageOperator(num(deal.id))}>
                <MessageCircle className="size-4" /> Написать оператору #{text(deal.id)}
              </Button>
              {canCancel && (
                <Button type="button" variant="destructive" onClick={() => void cancel()} disabled={busy !== null}>
                  <XCircle className="size-4" /> Отменить
                </Button>
              )}
            </div>
            {Boolean(deal.needs_operator_video) && (
              <div className="rounded-lg border border-amber-500/40 bg-amber-500/10 p-3 text-sm">
                Чек не приняли — нужно видео экрана оплаты. Напишите оператору и укажите номер сделки.
              </div>
            )}
          </Body>
        </Card>
      </div>
    </div>
  );
}

function PayoutsPanel({
  onDashboardChanged,
  helpPrefs,
  onHelp,
}: {
  onDashboardChanged: () => Promise<void>;
  helpPrefs: HelpPrefs;
  onHelp: (page: PortalTab, pref: HelpPref) => void;
}) {
  const [balance, setBalance] = useState<PortalRecord | null>(null);
  const [items, setItems] = useState<PortalRecord[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [reload, setReload] = useState(0);
  const [usdtRub, setUsdtRub] = useState(0);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [balanceResult, payoutsResult] = await Promise.all([exchangerPayoutBalance(), exchangerPayouts({ limit: 20 })]);
      setBalance(balanceResult);
      setItems(payoutsResult.items ?? []);
      setTotal(num(payoutsResult.total));
    } catch (error) {
      toast.error(errorMessage(error, "Не удалось загрузить выводы"));
    } finally {
      setLoading(false);
    }
  }, []);
  useEffect(() => { void load(); }, [load, reload]);
  useEffect(() => {
    exchangerRates()
      .then((result) => setUsdtRub(num(result.rates?.usdt?.market)))
      .catch(() => undefined);
  }, []);

  async function created() {
    setReload((value) => value + 1);
    await onDashboardChanged();
  }

  return (
    <div className="space-y-3 pt-1 md:pt-0">
      <PageHelp page="payouts" prefs={helpPrefs} onChange={onHelp} />
      <PayoutForm balance={balance} onCreated={created} />
      <RubCardPayoutForm availableUsd={num(balance?.available_usd)} usdtRub={usdtRub} pending={num(balance?.pending_payout_gross_usd) > 0} onCreated={created} />
      {loading ? <div className="flex justify-center py-8"><Loader2 className="size-5 animate-spin text-muted-foreground" /></div> : (
        <Card>
          <Head><CardTitle>Заявки на вывод</CardTitle><CardDescription>{total} операций за всё время</CardDescription></Head>
          <Body>{items.length === 0 ? <EmptyState label="Заявок на вывод ещё нет." /> : <div className="space-y-2">{items.map((item) => <PayoutRow key={String(item.id)} item={item} />)}</div>}</Body>
        </Card>
      )}
      <div className="flex justify-end"><Button variant="ghost" size="sm" onClick={() => setReload((value) => value + 1)}><RefreshCw className="size-4" /> Обновить</Button></div>
    </div>
  );
}

function PayoutForm({ balance, onCreated }: { balance: PortalRecord | null; onCreated: () => Promise<void> }) {
  const { money } = useDisplayMoney();
  const [gross, setGross] = useState("");
  const [coin, setCoin] = useState("usdt");
  const [wallet, setWallet] = useState("");
  const [preview, setPreview] = useState<PortalRecord | null>(null);
  const [busy, setBusy] = useState(false);
  const pending = num(balance?.pending_payout_gross_usd) > 0;
  const available = num(balance?.available_usd);
  const fees = record(balance?.withdraw_fees);
  const fee = withdrawFeeUsd(coin, fees);
  const min = num(balance?.payout_threshold_usd) > 0 && coin === "usdt" ? num(balance?.payout_threshold_usd) : minPayoutGrossUsd(coin, fees);
  const grossNum = num(gross);
  const localNet = Math.max(0, Math.round((grossNum - fee) * 100) / 100);
  const short = grossNum > 0 && grossNum > available;

  useEffect(() => {
    if (grossNum <= 0) {
      setPreview(null);
      return;
    }
    const timer = window.setTimeout(() => {
      exchangerPayoutPreview(grossNum, coin).then(setPreview).catch(() => setPreview(null));
    }, 400);
    return () => window.clearTimeout(timer);
  }, [grossNum, coin]);

  async function submit(e: FormEvent) {
    e.preventDefault();
    if (short) return;
    if (grossNum <= 0 || wallet.trim().length < 8) return toast.error("Проверьте сумму и адрес — без адреса вывод не отправим.");
    setBusy(true);
    try {
      await exchangerCreatePayout({ gross_usd: grossNum, crypto: coin, wallet: wallet.trim() });
      toast.success("Заявку на вывод приняли.");
      setGross("");
      setWallet("");
      setPreview(null);
      await onCreated();
    } catch (error) {
      toast.error(errorMessage(error, "Не удалось создать вывод"));
    } finally {
      setBusy(false);
    }
  }

  return (
    <Card id="exchanger-payout">
      <Head>
        <CardTitle>Выплата на свой кошелёк</CardTitle>
      </Head>
      <Body>
        <div className="mb-3 grid grid-cols-2 gap-2 sm:grid-cols-4">
          <MiniStat label="Доступно" value={money(available, "usd")} />
          <MiniStat label="Комиссия" value={money(fee, "usd")} />
          <MiniStat label="Минимум" value={money(min, "usd")} />
          <MiniStat label="На руки" value={money(preview?.net_usd ?? (grossNum > 0 ? localNet : 0), "usd")} />
        </div>
        <form onSubmit={submit} className="grid gap-4 lg:grid-cols-[1fr_1fr_2fr_auto] lg:items-end">
          <Field label="Списать, $"><Input type="number" min="0.01" step="0.01" value={gross} disabled={pending} onChange={(e) => setGross(e.target.value)} placeholder="100" /></Field>
          <Field label="Монета">
            <select value={coin} disabled={pending} onChange={(e) => setCoin(e.target.value)} className={selectClass}>
              <option value="usdt">USDT</option>
              <option value="btc">BTC</option>
              <option value="trx">TRX</option>
              <option value="ltc">LTC</option>
            </select>
          </Field>
          <Field label="Ваш кошелёк"><Input value={wallet} disabled={pending} onChange={(e) => setWallet(e.target.value)} placeholder="Адрес для выплаты" className="font-mono" /></Field>
          <Button type="submit" disabled={busy || pending || short}>{busy ? <Loader2 className="size-4 animate-spin" /> : <ArrowRight className="size-4" />} Вывести</Button>
        </form>
        {pending && <p className="mt-3 text-sm text-amber-600">Предыдущий вывод ещё в работе. Новый пока не создадим.</p>}
        {short && <p className="mt-3 text-sm text-amber-700">{SHORTAGE_TEXT}</p>}
        {preview && (
          <div className="mt-4 grid gap-2 rounded-lg border border-border bg-muted/30 p-3 text-sm sm:grid-cols-4">
            <PreviewValue label="Списывается" value={money(preview.gross_usd, "usd")} />
            <PreviewValue label="Комиссия" value={money(preview.fee_usd, "usd")} />
            <PreviewValue label="На руки" value={money(preview.net_usd, "usd")} />
            <PreviewValue label="К выплате" value={`${formatCrypto(num(preview.crypto_amount))} ${crypto(preview.crypto)}`} />
          </div>
        )}
      </Body>
    </Card>
  );
}

function RubCardPayoutForm({
  availableUsd,
  usdtRub,
  pending,
  onCreated,
}: {
  availableUsd: number;
  usdtRub: number;
  pending: boolean;
  onCreated: () => Promise<void>;
}) {
  const { money } = useDisplayMoney();
  const [amount, setAmount] = useState("");
  const [method, setMethod] = useState<"sbp" | "c2c">("sbp");
  const [phone, setPhone] = useState("");
  const [card, setCard] = useState("");
  const [recipient, setRecipient] = useState("");
  const [bank, setBank] = useState("");
  const [busy, setBusy] = useState(false);
  const amountRub = num(amount);
  const neededUsd = usdtRub > 0 ? amountRub / usdtRub : 0;
  const short = amountRub > 0 && (availableUsd <= 0 || (usdtRub > 0 && neededUsd > availableUsd));

  async function submit(e: FormEvent) {
    e.preventDefault();
    if (short) return;
    if (amountRub <= 0) return toast.error("Укажите сумму в ₽");
    if (recipient.trim().length < 3) return toast.error("Укажите ФИО получателя");
    if (bank.trim().length < 2) return toast.error("Укажите банк получателя");
    if (method === "sbp" && phone.trim().length < 10) return toast.error("Укажите телефон СБП");
    if (method === "c2c" && card.trim().length < 16) return toast.error("Укажите номер карты");
    setBusy(true);
    try {
      await exchangerRubCardPayout({
        amount_rub: amountRub,
        pay_method: method,
        phone: method === "sbp" ? phone.trim() : undefined,
        card_number: method === "c2c" ? card.trim() : undefined,
        recipient_name: recipient.trim(),
        bank: bank.trim(),
      });
      toast.success("Заявку на вывод в рублях приняли.");
      setAmount("");
      setPhone("");
      setCard("");
      setRecipient("");
      setBank("");
      await onCreated();
    } catch (error) {
      toast.error(errorMessage(error, "Не удалось отправить вывод ₽"));
    } finally {
      setBusy(false);
    }
  }

  return (
    <Card>
      <Head>
        <CardTitle>Вывод ₽ на карту / СБП</CardTitle>
        <CardDescription>
          Комиссия 0%. Курс — Рапира USDT{usdtRub > 0 ? ` ${fmtRate(usdtRub, "usdt")} ₽` : ""}. С баланса спишем {neededUsd > 0 ? money(neededUsd, "usd") : "сумму"} по этому курсу, вашу наценку сюда не добавляем.
        </CardDescription>
      </Head>
      <Body>
        <form onSubmit={submit} className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3 lg:items-end">
          <Field label="Сумма, ₽"><Input type="number" min="1" step="1" value={amount} disabled={pending} onChange={(e) => setAmount(e.target.value)} placeholder="15000" /></Field>
          <Field label="Способ">
            <select value={method} disabled={pending} onChange={(e) => setMethod(e.target.value as "sbp" | "c2c")} className={selectClass}>
              <option value="sbp">СБП</option>
              <option value="c2c">Карта</option>
            </select>
          </Field>
          {method === "sbp" ? (
            <Field label="Ваш телефон СБП"><Input value={phone} disabled={pending} onChange={(e) => setPhone(e.target.value)} placeholder="+7900…" /></Field>
          ) : (
            <Field label="Ваша карта"><Input value={card} disabled={pending} onChange={(e) => setCard(e.target.value)} placeholder="2200…" className="font-mono" /></Field>
          )}
          <Field label="Получатель"><Input value={recipient} disabled={pending} onChange={(e) => setRecipient(e.target.value)} placeholder="Иванов Иван Иванович" /></Field>
          <Field label="Банк получателя"><Input value={bank} disabled={pending} onChange={(e) => setBank(e.target.value)} placeholder="Сбер, Т-Банк…" /></Field>
          <Button type="submit" disabled={busy || pending || short}>{busy ? <Loader2 className="size-4 animate-spin" /> : <ArrowRight className="size-4" />} Вывести ₽</Button>
        </form>
        {short && <p className="mt-3 text-sm text-amber-700">{SHORTAGE_TEXT}</p>}
      </Body>
    </Card>
  );
}

const REKI_REFRESH_MS = 60_000;

function RekiPanel({ helpPrefs, onHelp }: { helpPrefs: HelpPrefs; onHelp: (page: PortalTab, pref: HelpPref) => void }) {
  const [snapshot, setSnapshot] = useState<ExchangerRekiSnapshot | null>(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);

  const load = useCallback(async (quiet = false) => {
    if (!quiet) setBusy(true);
    try {
      setSnapshot(await exchangerReki());
    } catch (error) {
      if (!quiet) toast.error(errorMessage(error, "Не удалось загрузить наличие"));
    } finally {
      setLoading(false);
      if (!quiet) setBusy(false);
    }
  }, []);

  useEffect(() => {
    void load(true);
    const timer = window.setInterval(() => void load(true), REKI_REFRESH_MS);
    return () => window.clearInterval(timer);
  }, [load]);

  const sections = snapshot?.sections ?? [];
  const stale = Boolean(snapshot?.stale);
  const hasBands = sections.some((section) => section.bands.length > 0);

  return (
    <div className="space-y-3 pt-1 md:pt-0">
      <PageHelp page="reki" prefs={helpPrefs} onChange={onHelp} />
      {loading ? (
        <div className="flex justify-center py-8"><Loader2 className="size-5 animate-spin text-muted-foreground" /></div>
      ) : !hasBands ? (
        <Card>
          <Head><CardTitle>Активные реквизиты</CardTitle><CardDescription>Какие суммы сейчас проходят.</CardDescription></Head>
          <Body><EmptyState label={stale ? "Данные устарели. Обновятся через пару минут." : "Свободных реквизитов сейчас нет."} /></Body>
        </Card>
      ) : (
        <div className="grid gap-3 md:grid-cols-2">
          {sections.map((section) => <RekiSectionCard key={section.sub_token} section={section} stale={stale} />)}
        </div>
      )}
      <div className="flex items-center justify-between gap-3">
        <p className="text-xs text-muted-foreground">
          {snapshot?.snapshot_at ? `Данные на ${formatDate(snapshot.snapshot_at)}` : "Данных пока нет"}
          {stale && " · устарело"}
        </p>
        <Button variant="ghost" size="sm" disabled={busy} onClick={() => void load()}>
          {busy ? <Loader2 className="size-4 animate-spin" /> : <RefreshCw className="size-4" />} Обновить
        </Button>
      </div>
    </div>
  );
}

function RekiSectionCard({ section, stale }: { section: ExchangerRekiSection; stale: boolean }) {
  const bands = section.bands;
  return (
    <Card className={cn(stale && "opacity-70")}>
      <Head>
        <div className="flex items-center justify-between gap-2">
          <CardTitle>{text(section.title, section.sub_token)}</CardTitle>
          {stale && <Badge variant="outline">устарело</Badge>}
        </div>
        <CardDescription>Активных {section.count} · свободно {formatMoney(section.total_rub)} ₽</CardDescription>
      </Head>
      <Body>
        {bands.length === 0 ? (
          <EmptyState label="Свободных сумм нет." />
        ) : (
          <div className="divide-y divide-border">
            {bands.map((band, index) => (
              <div key={`${band.min_rub}-${band.max_rub}-${index}`} className="flex items-center justify-between gap-3 py-2 first:pt-0 last:pb-0">
                <span className="font-mono text-sm tabular-nums">{formatMoney(band.min_rub)} – {formatMoney(band.max_rub)} ₽</span>
                <span className="font-mono text-sm tabular-nums text-muted-foreground">{formatMoney(band.available_rub)} ₽</span>
              </div>
            ))}
          </div>
        )}
      </Body>
    </Card>
  );
}

function HistoryPanel({ helpPrefs, onHelp }: { helpPrefs: HelpPrefs; onHelp: (page: PortalTab, pref: HelpPref) => void }) {
  const [items, setItems] = useState<PortalRecord[]>([]);
  const [loading, setLoading] = useState(true);
  useEffect(() => {
    loadHistoryQuiet(10).then((result) => {
      setItems(result.items);
    }).finally(() => setLoading(false));
  }, []);
  return (
    <div className="space-y-3 pt-1 md:pt-0">
      <PageHelp page="history" prefs={helpPrefs} onChange={onHelp} />
      <Card>
        <Head><CardTitle>История операций</CardTitle><CardDescription>Последние 10 записей — сделки и выводы.</CardDescription></Head>
        <Body>
          {loading ? <div className="flex justify-center py-8"><Loader2 className="size-5 animate-spin text-muted-foreground" /></div> : items.length === 0 ? <EmptyState label="Пока пусто — появятся сделки и выводы." /> : <div className="divide-y divide-border">{items.map((item) => <HistoryRow key={`${String(item.kind)}-${String(item.id)}`} item={item} />)}</div>}
        </Body>
      </Card>
    </div>
  );
}

function SettingsPanel({
  data,
  isOwner,
  helpPrefs,
  onHelp,
  onRestoreHelp,
  onRefresh,
}: {
  data: ExchangerDashboard;
  isOwner: boolean;
  helpPrefs: HelpPrefs;
  onHelp: (page: PortalTab, pref: HelpPref) => void;
  onRestoreHelp: () => void;
  onRefresh: () => Promise<void>;
}) {
  return (
    <div className="space-y-3 pt-1 md:pt-0">
      <PageHelp page="settings" prefs={helpPrefs} onChange={onHelp} />
      <DisplayCurrencyCard />
      <PasswordCard />
      <TwoFactorCard enabled={Boolean(data.totp_enabled)} onChanged={onRefresh} />
      <Card>
        <Head>
          <CardTitle>Инструкции</CardTitle>
          <CardDescription>Те самые подсказки сверху на вкладках.</CardDescription>
        </Head>
        <Body>
          <Button variant="outline" size="sm" onClick={onRestoreHelp}><Eye className="size-4" /> Вернуть инструкции</Button>
        </Body>
      </Card>
      {isOwner && <ClerksCard />}
    </div>
  );
}

function DisplayCurrencyCard() {
  const { currency, setCurrency, usdtRub, rateOk } = useDisplayMoney();
  return (
    <Card>
      <Head>
        <CardTitle>Валюта сумм</CardTitle>
        <CardDescription>Меняется только картинка на экране. Клиент по-прежнему платит в рублях, крипту выводите в долларах.</CardDescription>
      </Head>
      <Body className="space-y-3">
        <div className="flex gap-2">
          <Button type="button" variant={currency === "rub" ? "default" : "outline"} onClick={() => setCurrency("rub")}>
            Рубли
          </Button>
          <Button type="button" variant={currency === "usd" ? "default" : "outline"} onClick={() => setCurrency("usd")}>
            <CircleDollarSign className="size-4" /> Доллар
          </Button>
        </div>
        {usdtRub > 0 ? (
          <p className="text-sm text-muted-foreground">Курс Рапира USDT {fmtRate(usdtRub, "usdt")} ₽</p>
        ) : (
          !rateOk && <p className="text-sm text-muted-foreground">Рапира сейчас не отвечает. Показываем суммы как есть, без перевода.</p>
        )}
      </Body>
    </Card>
  );
}

function PasswordCard() {
  const [current, setCurrent] = useState("");
  const [next, setNext] = useState("");
  const [repeat, setRepeat] = useState("");
  const [busy, setBusy] = useState(false);

  async function submit(e: FormEvent) {
    e.preventDefault();
    if (next.length < 6) return toast.error("Новый пароль — минимум 6 символов");
    if (next !== repeat) return toast.error("Пароли не совпадают");
    setBusy(true);
    try {
      await exchangerChangePassword(current, next);
      toast.success("Пароль изменён");
      setCurrent("");
      setNext("");
      setRepeat("");
    } catch (error) {
      toast.error(errorMessage(error, "Не удалось изменить пароль"));
    } finally {
      setBusy(false);
    }
  }

  return (
    <Card>
      <Head>
        <CardTitle>Пароль</CardTitle>
        <CardDescription>Выданный пароль лучше сразу сменить на свой.</CardDescription>
      </Head>
      <Body>
        <form onSubmit={submit} className="grid gap-3 sm:grid-cols-3">
          <Field label="Текущий пароль"><Input type="password" value={current} onChange={(e) => setCurrent(e.target.value)} autoComplete="current-password" required /></Field>
          <Field label="Новый пароль"><Input type="password" value={next} onChange={(e) => setNext(e.target.value)} autoComplete="new-password" required /></Field>
          <Field label="Повторите новый пароль"><Input type="password" value={repeat} onChange={(e) => setRepeat(e.target.value)} autoComplete="new-password" required /></Field>
          <div className="sm:col-span-3">
            <Button type="submit" disabled={busy}>{busy ? <Loader2 className="size-4 animate-spin" /> : <KeyRound className="size-4" />} Сохранить</Button>
          </div>
        </form>
      </Body>
    </Card>
  );
}

function TwoFactorCard({ enabled, onChanged }: { enabled: boolean; onChanged: () => Promise<void> }) {
  const [secret, setSecret] = useState<string | null>(null);
  const [code, setCode] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);

  async function start() {
    setBusy(true);
    try {
      const result = await exchangerTotpSetup();
      setSecret(result.secret);
      setCode("");
    } catch (error) {
      toast.error(errorMessage(error, "Не удалось включить 2FA"));
    } finally {
      setBusy(false);
    }
  }

  async function confirm(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    try {
      await exchangerTotpConfirm(code.trim());
      toast.success("2FA включена");
      setSecret(null);
      setCode("");
      await onChanged();
    } catch (error) {
      toast.error(errorMessage(error, "Неверный код"));
    } finally {
      setBusy(false);
    }
  }

  async function disable(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    try {
      await exchangerTotpDisable(password, code.trim());
      toast.success("2FA отключена");
      setPassword("");
      setCode("");
      await onChanged();
    } catch (error) {
      toast.error(errorMessage(error, "Не удалось отключить 2FA"));
    } finally {
      setBusy(false);
    }
  }

  return (
    <Card>
      <Head className="flex-row items-start justify-between space-y-0 gap-3">
        <div>
          <CardTitle>Вход по коду (2FA)</CardTitle>
          <CardDescription>Каждый вход — код из приложения, не из СМС.</CardDescription>
        </div>
        <Badge variant={enabled ? "positive" : "muted"}>{enabled ? "Включена" : "Выключена"}</Badge>
      </Head>
      <Body className="space-y-3">
        {enabled ? (
          <form onSubmit={disable} className="grid gap-3 sm:grid-cols-3">
            <Field label="Текущий пароль"><Input type="password" value={password} onChange={(e) => setPassword(e.target.value)} autoComplete="current-password" required /></Field>
            <Field label="Код из приложения"><Input inputMode="numeric" value={code} onChange={(e) => setCode(e.target.value)} placeholder="000000" className="font-mono" maxLength={8} required /></Field>
            <div className="flex items-end">
              <Button type="submit" variant="destructive" disabled={busy}>Отключить</Button>
            </div>
          </form>
        ) : secret ? (
          <>
            <div className="rounded-lg border border-border bg-muted/30 p-3">
              <p className="text-sm text-muted-foreground">Добавьте ключ в приложение (Google Authenticator или похожее) и введите код оттуда.</p>
              <CopyField label="Секретный ключ" value={secret} />
            </div>
            <form onSubmit={confirm} className="flex flex-wrap items-end gap-3">
              <Field label="Код из приложения"><Input inputMode="numeric" value={code} onChange={(e) => setCode(e.target.value)} placeholder="000000" className="font-mono" maxLength={8} required /></Field>
              <Button type="submit" disabled={busy}><ShieldCheck className="size-4" /> Включить</Button>
              <Button type="button" variant="ghost" onClick={() => setSecret(null)}>Отмена</Button>
            </form>
          </>
        ) : (
          <Button variant="outline" disabled={busy} onClick={() => void start()}>
            {busy ? <Loader2 className="size-4 animate-spin" /> : <ShieldCheck className="size-4" />} Включить 2FA
          </Button>
        )}
      </Body>
    </Card>
  );
}

function HmacConnectGuide({ apiKey }: { apiKey?: string | null }) {
  return <ExchangerHmacGuide apiKey={apiKey} tone="site" />;
}

function ApiPanel({
  isOwner,
  helpPrefs,
  onHelp,
}: {
  isOwner: boolean;
  helpPrefs: HelpPrefs;
  onHelp: (page: PortalTab, pref: HelpPref) => void;
}) {
  return (
    <div className="space-y-3 pt-1 md:pt-0">
      <PageHelp page="api" prefs={helpPrefs} onChange={onHelp} />
      <ApiKeysCard canManage={isOwner} />
    </div>
  );
}

function ApiKeysCard({ canManage }: { canManage: boolean }) {
  const [key, setKey] = useState<ExchangerApiKey | null>(null);
  const [loading, setLoading] = useState(canManage);

  const load = useCallback(async () => {
    if (!canManage) {
      setLoading(false);
      return;
    }
    setLoading(true);
    try {
      const result = await exchangerApiKey();
      setKey(result.key);
    } catch (error) {
      toast.error(errorMessage(error, "Не удалось загрузить API-ключи"));
    } finally {
      setLoading(false);
    }
  }, [canManage]);

  useEffect(() => { void load(); }, [load]);

  return (
    <Card>
      <Head>
        <CardTitle>API реквизитов</CardTitle>
        <CardDescription>
          Ключ выдаёт администратор FocusPay. Здесь — публичный ключ и схема подписи. Секрет показывают один раз при выдаче.
        </CardDescription>
      </Head>
      <Body className="space-y-3">
        {!canManage && (
          <p className="text-sm text-muted-foreground">Ключ выдаёт администратор площадки. Когда пара будет у вас — схема подключения ниже.</p>
        )}
        {canManage && (loading ? <Loader2 className="size-5 animate-spin text-muted-foreground" /> : (
          key?.is_active ? (
            <div className="space-y-2">
              <CopyField label="API key" value={key.api_key} />
              <p className="text-sm text-muted-foreground">Секрет скрыт. Если его нет — напишите администратору площадки.</p>
            </div>
          ) : (
            <p className="text-sm text-muted-foreground">Ключа пока нет. Его выдаёт администратор площадки — напишите ему, если нужен API.</p>
          )
        ))}
        <HmacConnectGuide apiKey={key?.api_key} />
      </Body>
    </Card>
  );
}

function ClerksCard() {
  const [items, setItems] = useState<ExchangerAccount[]>([]);
  const [currentId, setCurrentId] = useState(0);
  const [loading, setLoading] = useState(true);
  const [username, setUsername] = useState("");
  const [label, setLabel] = useState("");
  const [busy, setBusy] = useState(false);
  const [issued, setIssued] = useState<ExchangerCredentials | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const result = await exchangerAccounts();
      setItems(result.items ?? []);
      setCurrentId(num(result.current_account_id));
    } catch (error) {
      toast.error(errorMessage(error, "Не удалось загрузить логины"));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { void load(); }, [load]);

  async function create(e: FormEvent) {
    e.preventDefault();
    if (username.trim().length < 3) return toast.error("Логин — минимум 3 символа");
    setBusy(true);
    try {
      const result = await exchangerCreateClerk({ username: username.trim(), label: label.trim() || undefined });
      setIssued(result.credentials);
      setUsername("");
      setLabel("");
      toast.success("Логин сотрудника создан");
      await load();
    } catch (error) {
      toast.error(errorMessage(error, "Не удалось создать логин"));
    } finally {
      setBusy(false);
    }
  }

  async function resetPassword(id: number) {
    setBusy(true);
    try {
      setIssued(await exchangerResetAccountPassword(id));
      toast.success("Новый пароль готов");
    } catch (error) {
      toast.error(errorMessage(error, "Не удалось сбросить пароль"));
    } finally {
      setBusy(false);
    }
  }

  async function toggleActive(account: ExchangerAccount) {
    setBusy(true);
    try {
      await exchangerUpdateAccount(account.id, { is_active: !account.is_active });
      await load();
    } catch (error) {
      toast.error(errorMessage(error, "Не удалось изменить доступ"));
    } finally {
      setBusy(false);
    }
  }

  return (
    <Card>
      <Head>
        <div className="flex items-center gap-2"><Users className="size-5" /><CardTitle>Логины магазина</CardTitle></div>
        <CardDescription>Сотрудник может брать реквизит и грузить чеки. Выводы и настройки магазина — только у вас.</CardDescription>
      </Head>
      <Body className="space-y-3">
        {issued && (
          <div className="rounded-lg border border-amber-500/40 bg-amber-500/10 p-3">
            <p className="text-sm font-medium">Пароль больше не покажем. Скопируйте и отдайте сотруднику сейчас.</p>
            <CopyField label="Логин" value={text(issued.username)} />
            <CopyField label="Пароль" value={text(issued.password)} />
            <Button variant="ghost" size="sm" className="mt-2" onClick={() => setIssued(null)}>Скрыть</Button>
          </div>
        )}
        {loading ? (
          <Loader2 className="size-5 animate-spin text-muted-foreground" />
        ) : (
          <div className="divide-y divide-border">
            {items.map((account) => (
              <div key={account.id} className="flex flex-wrap items-center justify-between gap-2 py-2">
                <div className="min-w-0">
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="font-mono text-sm">{account.username}</span>
                    <Badge variant={account.is_owner ? "default" : "secondary"}>{account.is_owner ? "Владелец" : "Сотрудник"}</Badge>
                    {!account.is_active && <Badge variant="destructive">Отключён</Badge>}
                    {account.id === currentId && <Badge variant="outline">Вы</Badge>}
                  </div>
                  {Boolean(account.label) && <p className="mt-1 text-xs text-muted-foreground">{text(account.label)}</p>}
                </div>
                {!account.is_owner && (
                  <div className="flex shrink-0 gap-1">
                    <Button variant="outline" size="sm" disabled={busy} onClick={() => void resetPassword(account.id)}>
                      <KeyRound className="size-3.5" /> Новый пароль
                    </Button>
                    <Button variant="ghost" size="sm" disabled={busy} onClick={() => void toggleActive(account)}>
                      {account.is_active ? "Отключить" : "Включить"}
                    </Button>
                  </div>
                )}
              </div>
            ))}
          </div>
        )}
        <form onSubmit={create} className="flex flex-wrap items-end gap-3 border-t border-border pt-3">
          <Field label="Логин сотрудника"><Input value={username} onChange={(e) => setUsername(e.target.value)} placeholder="например, kassa_night" className="font-mono" /></Field>
          <Field label="Пометка (необязательно)"><Input value={label} onChange={(e) => setLabel(e.target.value)} placeholder="Ночная смена" /></Field>
          <Button type="submit" disabled={busy || username.trim().length < 3}>
            {busy ? <Loader2 className="size-4 animate-spin" /> : <ArrowRight className="size-4" />} Выдать логин
          </Button>
        </form>
      </Body>
    </Card>
  );
}

function DealRow({ deal, onClick, action }: { deal: PortalRecord; onClick?: () => void; action?: string }) {
  const { money } = useDisplayMoney();
  return (
    <button type="button" onClick={onClick} className={`flex w-full items-center justify-between gap-3 py-2 text-left ${onClick ? "cursor-pointer hover:bg-muted/40" : "cursor-default"}`}>
      <div className="min-w-0">
        <div className="flex flex-wrap items-center gap-2"><span className="font-medium">#{text(deal.id)}</span><Badge variant={statusVariant(deal.status)}>{statusLabel(deal.status)}</Badge><DealCountdown status={deal.status} expiresAt={deal.expires_at} className="text-xs" /></div>
        <p className="mt-1 truncate text-xs text-muted-foreground">{formatDate(text(deal.created_at, ""))} · {crypto(deal.crypto)} · {text(deal.sub_token) === "CARDRUB" ? "Карта" : "СБП"}{deal.payout_on_credit ? " · сразу в крипте" : ""}{action ? ` · ${action}` : ""}</p>
      </div>
      <div className="shrink-0 text-right">
        <p className="font-mono text-sm">{money(deal.client_pays_rub, "rub")}</p>
        <p className="text-xs text-muted-foreground">{formatCrypto(num(deal.principal_usdt))} {crypto(deal.crypto)}</p>
      </div>
    </button>
  );
}

function PayoutRow({ item }: { item: PortalRecord }) {
  const { money } = useDisplayMoney();
  return (
    <div className="flex flex-col gap-2 border-b border-border py-3 last:border-b-0 sm:flex-row sm:items-center sm:justify-between">
      <div>
        <div className="flex items-center gap-2"><span className="font-medium">Вывод #{text(item.id)}</span><Badge variant={statusVariant(item.status)}>{statusLabel(item.status)}</Badge></div>
        <p className="mt-1 text-xs text-muted-foreground">{formatDate(text(item.created_at, ""))} · {crypto(item.crypto)}</p>
      </div>
      <div className="text-left sm:text-right">
        <p className="font-mono">{money(item.net_usd, "usd")} · {formatCrypto(num(item.crypto_amount))} {crypto(item.crypto)}</p>
        <p className="text-xs text-muted-foreground">Списано {money(item.gross_usd, "usd")} · комиссия {money(item.fee_usd, "usd")}</p>
      </div>
    </div>
  );
}

function HistoryRow({ item }: { item: PortalRecord }) {
  const isPayout = item.kind === "payout";
  const { money } = useDisplayMoney();
  return (
    <div className="flex flex-col gap-2 py-2 sm:flex-row sm:items-center sm:justify-between">
      <div>
        <div className="flex flex-wrap items-center gap-2">
          <span className="font-medium">{isPayout ? `Вывод #${text(item.id)}` : `Сделка #${text(item.id)}`}</span>
          <Badge variant={statusVariant(item.status)}>{statusLabel(item.status)}</Badge>
          {!isPayout && <DealCountdown status={item.status} expiresAt={item.expires_at} className="text-xs" />}
        </div>
        <p className="mt-1 text-xs text-muted-foreground">{formatDate(text(item.at ?? item.created_at, ""))} · {crypto(item.crypto)}</p>
      </div>
      <div className="text-left sm:text-right">
        <p className="font-mono">{isPayout ? `−${money(item.gross_usd, "usd")}` : money(item.amount_rub ?? item.client_pays_rub, "rub")}</p>
        <p className="text-xs text-muted-foreground">{isPayout ? `На руки ${money(item.net_usd, "usd")}` : `Начислено ${money(item.amount_usd, "usd")}`}</p>
      </div>
    </div>
  );
}

function CopyField({ label, value }: { label: string; value: string }) {
  const [copied, setCopied] = useState(false);
  async function copy() {
    if (await copyText(value)) {
      setCopied(true);
      window.setTimeout(() => setCopied(false), 2000);
    }
  }
  return (
    <div className="flex items-start justify-between gap-3 border-b border-border/60 py-2 last:border-0">
      <div className="min-w-0">
        <p className="text-xs text-muted-foreground">{label}</p>
        <p className="mt-0.5 break-all font-mono text-sm">{value}</p>
      </div>
      <Button type="button" variant="outline" size="sm" onClick={() => void copy()}>
        {copied ? <Check className="size-3.5" /> : <Copy className="size-3.5" />}
        {copied ? "Скопировано" : "Копировать"}
      </Button>
    </div>
  );
}

function InfoRow({ label, value }: { label: string; value: ReactNode }) {
  return <div className="flex min-w-0 justify-between gap-3 border-b border-border/60 pb-2 last:border-0"><span className="capitalize text-muted-foreground">{label}</span><span className="min-w-0 break-all text-right">{value}</span></div>;
}

function PreviewValue({ label, value }: { label: string; value: string }) {
  return <div className="min-w-0"><p className="text-xs text-muted-foreground">{label}</p><p className="mt-1 truncate font-mono text-sm font-medium md:text-base" title={value}>{value}</p></div>;
}

function MiniStat({ label, value }: { label: string; value: string }) {
  return <div className="rounded-md border border-border bg-muted/30 px-3 py-2.5"><p className="text-[11px] uppercase tracking-wide text-muted-foreground md:text-xs">{label}</p><p className="mt-0.5 font-mono text-base font-medium">{value}</p></div>;
}

function Field({ label, children }: { label: string; children: ReactNode }) {
  return <div className="flex min-w-0 flex-col gap-2"><Label>{label}</Label>{children}</div>;
}

function EmptyState({ label }: { label: string }) {
  return <div className="flex flex-col items-center gap-2 py-6 text-center text-sm text-muted-foreground"><FileCheck2 className="size-5" />{label}</div>;
}

const selectClass = "flex h-11 w-full rounded-lg border border-input bg-background px-3 py-2 text-base outline-none focus-visible:ring-2 focus-visible:ring-ring";
const textareaClass = "w-full resize-y rounded-lg border border-input bg-background px-3 py-2 text-base outline-none placeholder:text-muted-foreground focus-visible:ring-2 focus-visible:ring-ring";
