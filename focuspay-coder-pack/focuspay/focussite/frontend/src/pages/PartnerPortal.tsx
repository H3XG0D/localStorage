import { useEffect, useRef, useState, type FormEvent, type ReactNode } from "react";
import { ArrowRight, Copy, Eye, EyeOff, Loader2, LockKeyhole, LogOut, ShieldCheck, UserRound } from "lucide-react";
import { useNavigate } from "react-router-dom";
import { toast } from "sonner";
import { AuthShell } from "@/components/AuthShell";
import { PublicHeader } from "@/components/PublicHeader";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { ApiError, clearToken, getToken, setToken } from "@/lib/api";
import { CARD_WITHDRAW_PROMISE } from "@/lib/cardWithdrawCopy";
import { isLocalDev } from "@/lib/isLocalDev";
import {
  partnerDashboard,
  partnerLedger,
  partnerLogin,
  partnerLogin2FA,
  partnerOrders,
  partnerUsers,
  partnerWithdraw,
  partnerWithdrawals,
  type PartnerDashboard,
  type PartnerLedgerEntry,
  type PartnerOrderRow,
  type PartnerUserRow,
  type PartnerWithdrawal,
} from "@/lib/portals";
import { formatDate, formatMoney } from "@/lib/utils";

export function PartnerLoginPage() {
  const navigate = useNavigate();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [pending, setPending] = useState(false);
  const [preAuth, setPreAuth] = useState<string | null>(null);
  const [code, setCode] = useState("");

  useEffect(() => {
    if (getToken("partner") || isLocalDev()) navigate("/partner", { replace: true });
  }, [navigate]);

  async function submit(e: FormEvent) {
    e.preventDefault();
    setPending(true);
    try {
      const r = await partnerLogin(username, password);
      if (r.requires_2fa && r.pre_auth_token) {
        setPreAuth(r.pre_auth_token);
        toast.info("Введите код 2FA");
        return;
      }
      if (r.access_token) {
        setToken("partner", r.access_token);
        navigate("/partner", { replace: true });
      }
    } catch (e) {
      toast.error(e instanceof ApiError ? e.message : "Не удалось войти");
    } finally {
      setPending(false);
    }
  }

  async function submit2FA(e: FormEvent) {
    e.preventDefault();
    if (!preAuth) return;
    setPending(true);
    try {
      const r = await partnerLogin2FA(preAuth, code.trim());
      if (r.access_token) {
        setToken("partner", r.access_token);
        navigate("/partner", { replace: true });
      }
    } catch (e) {
      toast.error(e instanceof ApiError ? e.message : "Неверный код");
    } finally {
      setPending(false);
    }
  }

  if (preAuth) {
    return (
      <AuthShell title="Подтверждение входа" subtitle="Введите код из приложения-аутентификатора.">
        <form onSubmit={submit2FA} className="flex flex-col gap-5">
          <div className="flex flex-col gap-2">
            <Label htmlFor="code">Код 2FA</Label>
            <div className="relative">
              <ShieldCheck className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-muted-foreground" />
              <Input id="code" inputMode="numeric" value={code} onChange={(e) => setCode(e.target.value)} placeholder="000000" className="pl-10 font-mono tracking-[0.3em]" maxLength={8} autoFocus />
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
    <AuthShell title="Кабинет партнёра" subtitle="Войдите, чтобы видеть статистику и выводить вознаграждение.">
      <form onSubmit={submit} className="flex flex-col gap-5">
        <div className="flex flex-col gap-2">
          <Label htmlFor="u">Логин</Label>
          <div className="relative">
            <UserRound className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-muted-foreground" />
            <Input id="u" value={username} onChange={(e) => setUsername(e.target.value)} className="pl-10" required />
          </div>
        </div>
        <div className="flex flex-col gap-2">
          <Label htmlFor="p">Пароль</Label>
          <div className="relative">
            <LockKeyhole className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-muted-foreground" />
            <Input id="p" type="password" value={password} onChange={(e) => setPassword(e.target.value)} className="pl-10" required />
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

type PrivateKey = "summary" | "ledger" | "users" | "orders" | "withdrawals";

export function PartnerDashboardPage() {
  const navigate = useNavigate();
  const [data, setData] = useState<PartnerDashboard | null>(null);
  const [ledger, setLedger] = useState<ListState<PartnerLedgerEntry> | null>(null);
  const [users, setUsers] = useState<ListState<PartnerUserRow> | null>(null);
  const [orders, setOrders] = useState<ListState<PartnerOrderRow> | null>(null);
  const [withdrawals, setWithdrawals] = useState<ListState<PartnerWithdrawal> | null>(null);
  const [withdrawMeta, setWithdrawMeta] = useState<{
    available: number;
    minimum: number;
    pending: boolean;
  } | null>(null);
  const [loading, setLoading] = useState(true);
  const [open, setOpen] = useState<Record<PrivateKey, boolean>>({
    summary: false,
    ledger: false,
    users: false,
    orders: false,
    withdrawals: false,
  });
  const loaded = useRef<Record<Exclude<PrivateKey, "summary">, boolean>>({
    ledger: false,
    users: false,
    orders: false,
    withdrawals: false,
  });

  useEffect(() => {
    if (!getToken("partner") && !isLocalDev()) {
      navigate("/partner/login", { replace: true });
      return;
    }
    partnerDashboard()
      .then(setData)
      .catch((e) => {
        if (e instanceof ApiError && e.status === 401) {
          clearToken("partner");
          if (!isLocalDev()) navigate("/partner/login", { replace: true });
        }
      })
      .finally(() => setLoading(false));
  }, [navigate]);

  function reveal(key: PrivateKey) {
    const willOpen = !open[key];
    setOpen({ summary: false, ledger: false, users: false, orders: false, withdrawals: false, [key]: willOpen });
    if (!willOpen || key === "summary" || loaded.current[key]) return;
    loaded.current[key] = true;
    const request = key === "ledger"
      ? partnerLedger(30).then((row) => setLedger({ status: "ready", rows: row.entries ?? [] }))
      : key === "users"
        ? partnerUsers(20).then((row) => setUsers({ status: "ready", rows: row.users ?? [] }))
        : key === "orders"
          ? partnerOrders(20).then((row) => setOrders({ status: "ready", rows: row.orders ?? [] }))
          : Promise.all([partnerLedger(1), partnerWithdrawals()]).then(([meta, history]) => {
              setWithdrawMeta({
                available: meta.available_rub,
                minimum: meta.min_withdraw_card_rub,
                pending: meta.has_pending_withdrawal,
              });
              setWithdrawals({ status: "ready", rows: history.withdrawals ?? [] });
            });
    request.catch(() => {
      loaded.current[key] = false;
      if (key === "ledger") setLedger({ status: "error" });
      if (key === "users") setUsers({ status: "error" });
      if (key === "orders") setOrders({ status: "error" });
      if (key === "withdrawals") setWithdrawals({ status: "error" });
    });
  }

  async function refreshWithdrawals() {
    const [meta, history, dashboard] = await Promise.all([partnerLedger(1), partnerWithdrawals(), partnerDashboard()]);
    setWithdrawMeta({
      available: meta.available_rub,
      minimum: meta.min_withdraw_card_rub,
      pending: meta.has_pending_withdrawal,
    });
    setWithdrawals({ status: "ready", rows: history.withdrawals ?? [] });
    setData(dashboard);
  }

  function logout() {
    clearToken("partner");
    navigate("/partner/login", { replace: true });
  }

  function copy(t: string) {
    navigator.clipboard?.writeText(t).then(() => toast.success("Скопировано"), () => toast.error("Ошибка"));
  }

  return (
    <div className="min-h-screen bg-background">
      <PublicHeader />
      <main className="mx-auto max-w-4xl px-4 py-8 sm:px-6 lg:px-8">
        {loading ? (
          <div className="flex justify-center py-24"><Loader2 className="size-6 animate-spin text-muted-foreground" /></div>
        ) : !data ? (
          <Card><CardContent className="py-12 text-center text-sm text-muted-foreground">Нет данных.</CardContent></Card>
        ) : (
          <div className="space-y-6">
            <div className="flex items-center justify-between">
              <div>
                <h1 className="text-2xl font-bold tracking-tight">{data.campaign.name || "Партнёрский кабинет"}</h1>
                <p className="mt-1 font-mono text-sm text-muted-foreground">Код кампании: {data.campaign.code}</p>
                {tierCaption(data.tier) && (
                  <p className="mt-1 text-sm text-muted-foreground">{tierCaption(data.tier)}</p>
                )}
              </div>
              <Button variant="ghost" size="icon" aria-label="Выйти" onClick={logout}><LogOut className="size-4" /></Button>
            </div>

            <Card>
              <CardHeader>
                <CardTitle>Реферальная ссылка</CardTitle>
                <CardDescription>{data.commission_basis_label}</CardDescription>
              </CardHeader>
              <CardContent className="space-y-2">
                <div className="flex gap-2">
                  <Input readOnly value={data.referral_web_link} className="font-mono text-xs" />
                  <Button variant="outline" size="icon" onClick={() => copy(data.referral_web_link)}><Copy className="size-4" /></Button>
                </div>
                <div className="flex gap-2">
                  <Input readOnly value={data.referral_link} className="font-mono text-xs" />
                  <Button variant="outline" size="icon" onClick={() => copy(data.referral_link)}><Copy className="size-4" /></Button>
                </div>
              </CardContent>
            </Card>

            <PrivateSection
              title="Сводка"
              hint="Числа по балансу, обороту и клиентам скрыты."
              open={open.summary}
              onToggle={() => reveal("summary")}
            >
              <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
                <Stat label="Привлечено" value={String(data.attracted_users)} />
                <Stat label="Оплачено заявок" value={String(data.paid_orders_count)} />
                <Stat label="Баланс, ₽" value={formatMoney(data.balance_rub)} mono />
                <Stat label="Доступно, ₽" value={formatMoney(data.available_rub)} mono />
              </div>
              <div className="mt-4 grid grid-cols-2 gap-3 sm:grid-cols-4">
                <MiniStat label="Оборот, ₽" value={data.paid_fiat_sum} />
                <MiniStat label="Начислено за период" value={data.period_accrued} />
                <MiniStat label="Выплачено" value={data.period_paid_out} />
                <MiniStat label="К выводу в обработке" value={data.pending_withdraw_rub} />
              </div>
            </PrivateSection>

            <PrivateSection
              title="Выплаты"
              hint="Создание заявки и история выводов."
              open={open.withdrawals}
              onToggle={() => reveal("withdrawals")}
            >
              <WithdrawalSection state={withdrawals} meta={withdrawMeta} onCreated={refreshWithdrawals} />
            </PrivateSection>

            <PrivateSection
              title="Начисления"
              hint="Суммы по сделкам скрыты, пока не откроете."
              open={open.ledger}
              onToggle={() => reveal("ledger")}
            >
              <LedgerList state={ledger} />
            </PrivateSection>

            <PrivateSection
              title="Клиенты"
              hint="Имена и логины скрыты, пока не откроете."
              open={open.users}
              onToggle={() => reveal("users")}
            >
              <UserList state={users} />
            </PrivateSection>

            <PrivateSection
              title="Заявки рефералов"
              hint="Номера и суммы заявок скрыты, пока не откроете."
              open={open.orders}
              onToggle={() => reveal("orders")}
            >
              <OrderList state={orders} />
            </PrivateSection>
          </div>
        )}
      </main>
    </div>
  );
}

function PrivateSection({
  title,
  hint,
  open,
  onToggle,
  children,
}: {
  title: string;
  hint: string;
  open: boolean;
  onToggle: () => void;
  children: ReactNode;
}) {
  return (
    <Card>
      <CardHeader className="flex-row items-start justify-between gap-3 space-y-0">
        <div className="min-w-0">
          <CardTitle>{title}</CardTitle>
          {!open && <CardDescription className="mt-1.5">{hint}</CardDescription>}
        </div>
        <Button type="button" variant="outline" size="sm" className="shrink-0" onClick={onToggle} aria-expanded={open}>
          {open ? <EyeOff className="size-4" /> : <Eye className="size-4" />}
          {open ? "Скрыть" : "Показать"}
        </Button>
      </CardHeader>
      {open ? <CardContent>{children}</CardContent> : null}
    </Card>
  );
}

function Stat({ label, value, mono }: { label: string; value: string; mono?: boolean }) {
  return (
    <div className="rounded-xl border border-border bg-card p-4">
      <p className="text-xs text-muted-foreground">{label}</p>
      <p className={`mt-1 text-2xl font-semibold tracking-tight ${mono ? "font-mono" : ""}`}>{value}</p>
    </div>
  );
}
function MiniStat({ label, value }: { label: string; value: number }) {
  return (
    <div className="rounded-lg border border-border bg-muted/30 p-3">
      <p className="text-[10px] uppercase tracking-wide text-muted-foreground">{label}</p>
      <p className="mt-0.5 font-mono text-sm font-medium">{formatMoney(value)} ₽</p>
    </div>
  );
}

type ListState<T> = { status: "ready"; rows: T[] } | { status: "error" };

function visibleLedgerNote(note?: string | null): string | null {
  const text = note?.trim();
  if (!text) return null;
  if (/от прибыли/i.test(text) || /\(tier\)/i.test(text)) return null;
  return text;
}

function tierCaption(tier: PartnerDashboard["tier"]): string | null {
  const pct = asNumber(tier.effective_percent);
  if (pct == null) return null;
  if (tier.tier_fixed || tier.at_max_tier) return `Ставка ${pct}%`;
  const next = asNumber(tier.next_tier_percent);
  const done = asNumber(tier.progress_current);
  const total = asNumber(tier.progress_total);
  if (next == null || done == null || total == null) return `Ставка ${pct}%`;
  return `Ставка ${pct}% · до ${next}%: ${done}/${total} реф.`;
}

function asNumber(value: unknown): number | null {
  if (typeof value === "boolean" || value == null || value === "") return null;
  const n = Number(value);
  return Number.isFinite(n) ? n : null;
}

function formatRub2(value: number) {
  return new Intl.NumberFormat("ru-RU", { minimumFractionDigits: 2, maximumFractionDigits: 2 }).format(value);
}

const LEDGER_LABEL: Record<string, string> = {
  accrual: "Начисление",
  payout: "Выплата",
  adjustment: "Корректировка",
  spend: "Списание",
};

const ORDER_STATUS: Record<string, string> = {
  PAID: "Оплачена",
  COMPLETED: "Завершена",
  CREATED: "Создана",
  AWAITING_CHECK: "На проверке",
  PENDING: "В работе",
  OPERATOR_PENDING: "У оператора",
  FAILED: "Ошибка",
  CANCELED: "Отменена",
  EXPIRED: "Истекла",
  DISPUTE: "Спор",
};

function LedgerList({ state }: { state: ListState<PartnerLedgerEntry> | null }) {
  if (!state || state.status === "error") {
    return <p className="text-sm text-muted-foreground">{state ? "Не удалось загрузить начисления." : "Загрузка…"}</p>;
  }
  const rows = state.rows.filter((row) => row.type !== "hold");
  if (rows.length === 0) return <p className="text-sm text-muted-foreground">Начислений пока нет.</p>;
  return (
    <div className="divide-y divide-border">
      {rows.map((row) => {
        const note = visibleLedgerNote(row.note);
        return (
          <div key={row.id} className="py-3">
            <div className="flex items-baseline justify-between gap-3">
              <p className="text-sm">{LEDGER_LABEL[row.type] || row.type}</p>
              <p className="font-mono text-sm">{formatRub2(row.amount_rub)} ₽</p>
            </div>
            <p className="mt-1 text-xs text-muted-foreground">
              {formatDate(row.created_at)}
              {row.order_id ? ` · ${row.order_id}` : ""}
            </p>
            {note ? <p className="mt-1 text-sm text-muted-foreground">{note}</p> : null}
          </div>
        );
      })}
    </div>
  );
}

function UserList({ state }: { state: ListState<PartnerUserRow> | null }) {
  if (!state || state.status === "error") {
    return <p className="text-sm text-muted-foreground">{state ? "Не удалось загрузить клиентов." : "Загрузка…"}</p>;
  }
  if (state.rows.length === 0) return <p className="text-sm text-muted-foreground">Клиентов пока нет.</p>;
  return (
    <div className="divide-y divide-border">
      {state.rows.map((row) => (
        <div key={row.user_id} className="flex items-baseline justify-between gap-3 py-3">
          <div className="min-w-0">
            <p className="truncate text-sm">{row.username ? `@${row.username}` : row.first_name || String(row.user_id)}</p>
            <p className="text-xs text-muted-foreground">{formatDate(row.assigned_at)}</p>
          </div>
          <p className="shrink-0 text-sm text-muted-foreground">{row.paid_orders} оплачено · {row.total_orders} заявок</p>
        </div>
      ))}
    </div>
  );
}

function OrderList({ state }: { state: ListState<PartnerOrderRow> | null }) {
  if (!state || state.status === "error") {
    return <p className="text-sm text-muted-foreground">{state ? "Не удалось загрузить заявки." : "Загрузка…"}</p>;
  }
  if (state.rows.length === 0) return <p className="text-sm text-muted-foreground">Заявок пока нет.</p>;
  return (
    <div className="divide-y divide-border">
      {state.rows.map((row) => (
        <div key={row.order_id} className="flex items-baseline justify-between gap-3 py-3">
          <div className="min-w-0">
            <p className="truncate font-mono text-sm">{row.order_id}</p>
            <p className="text-xs text-muted-foreground">
              {row.direction === "buy" ? "Покупка" : "Продажа"} {String(row.crypto || "").toUpperCase()} · {formatDate(row.created_at)}
            </p>
          </div>
          <div className="shrink-0 text-right">
            <p className="font-mono text-sm">{formatMoney(row.fiat_amount)} ₽</p>
            <p className="text-xs text-muted-foreground">{ORDER_STATUS[row.status] || row.status}</p>
          </div>
        </div>
      ))}
    </div>
  );
}

const WITHDRAWAL_STATUS: Record<string, string> = {
  pending: "В обработке",
  awaiting: "В ожидании",
  processing: "На выплате",
  paid: "Выплачено",
  approved: "Выплачено",
  rejected: "Отклонено",
  canceled: "Отменено",
};

function WithdrawalSection({
  state,
  meta,
  onCreated,
}: {
  state: ListState<PartnerWithdrawal> | null;
  meta: { available: number; minimum: number; pending: boolean } | null;
  onCreated: () => Promise<void>;
}) {
  const [amount, setAmount] = useState("");
  const [method, setMethod] = useState<"card" | "crypto">("card");
  const [crypto, setCrypto] = useState("usdt");
  const [network, setNetwork] = useState("trc20");
  const [requisites, setRequisites] = useState("");
  const [submitting, setSubmitting] = useState(false);

  async function submit(e: FormEvent) {
    e.preventDefault();
    const value = Number(amount.replace(",", "."));
    if (!Number.isFinite(value) || value <= 0) {
      toast.error("Укажите корректную сумму");
      return;
    }
    setSubmitting(true);
    try {
      await partnerWithdraw({
        amount_rub: value,
        method,
        requisites: requisites.trim(),
        crypto: method === "crypto" ? crypto : null,
        network: method === "crypto" && crypto === "usdt" ? network : null,
      });
      toast.success("Заявка на вывод создана");
      setAmount("");
      setRequisites("");
      await onCreated();
    } catch (error) {
      toast.error(error instanceof ApiError ? error.message : "Не удалось создать заявку");
    } finally {
      setSubmitting(false);
    }
  }

  if (!state || !meta || state.status === "error") {
    return <p className="text-sm text-muted-foreground">{state?.status === "error" ? "Не удалось загрузить выплаты." : "Загрузка…"}</p>;
  }

  return (
    <div className="space-y-6">
      <div>
        <div className="mb-4 flex flex-wrap items-baseline justify-between gap-2">
          <p className="text-sm font-medium">Новая заявка</p>
          <p className="text-sm text-muted-foreground">Доступно: <span className="font-mono text-foreground">{formatMoney(meta.available)} ₽</span></p>
        </div>
        {meta.pending ? (
          <p className="rounded-lg border border-border bg-muted/30 p-3 text-sm text-muted-foreground">
            Предыдущая заявка ещё обрабатывается. Новую можно создать после её завершения.
          </p>
        ) : (
          <form onSubmit={submit} className="grid gap-4 sm:grid-cols-2">
            <div className="space-y-2">
              <Label htmlFor="withdraw-amount">Сумма, ₽</Label>
              <Input id="withdraw-amount" inputMode="decimal" value={amount} onChange={(e) => setAmount(e.target.value)} placeholder={method === "card" ? `От ${formatMoney(meta.minimum)}` : "0"} required />
              {method === "card" && (
                <p className="text-xs text-muted-foreground">
                  Минимум {formatMoney(meta.minimum)} ₽. {CARD_WITHDRAW_PROMISE}
                </p>
              )}
            </div>
            <div className="space-y-2">
              <Label htmlFor="withdraw-method">Способ</Label>
              <select id="withdraw-method" value={method} onChange={(e) => setMethod(e.target.value as "card" | "crypto")} className="flex h-10 w-full rounded-md border border-input bg-background px-3 py-2 text-sm">
                <option value="card">Карта / СБП</option>
                <option value="crypto">Криптовалюта</option>
              </select>
            </div>
            {method === "crypto" && (
              <>
                <div className="space-y-2">
                  <Label htmlFor="withdraw-crypto">Монета</Label>
                  <select id="withdraw-crypto" value={crypto} onChange={(e) => setCrypto(e.target.value)} className="flex h-10 w-full rounded-md border border-input bg-background px-3 py-2 text-sm">
                    <option value="usdt">USDT</option>
                    <option value="trx">TRX</option>
                    <option value="ltc">LTC</option>
                    <option value="btc">BTC</option>
                  </select>
                </div>
                {crypto === "usdt" && (
                  <div className="space-y-2">
                    <Label htmlFor="withdraw-network">Сеть</Label>
                    <select id="withdraw-network" value={network} onChange={(e) => setNetwork(e.target.value)} className="flex h-10 w-full rounded-md border border-input bg-background px-3 py-2 text-sm">
                      <option value="trc20">TRC20</option>
                      <option value="erc20">ERC20</option>
                    </select>
                  </div>
                )}
              </>
            )}
            <div className="space-y-2 sm:col-span-2">
              <Label htmlFor="withdraw-requisites">{method === "card" ? "Номер карты или телефон СБП" : "Адрес кошелька"}</Label>
              <Input id="withdraw-requisites" value={requisites} onChange={(e) => setRequisites(e.target.value)} minLength={5} maxLength={500} required />
            </div>
            <div className="sm:col-span-2">
              <Button type="submit" disabled={submitting || meta.available <= 0}>
                {submitting && <Loader2 className="size-4 animate-spin" />}
                {submitting ? "Отправляем…" : "Создать заявку"}
              </Button>
            </div>
          </form>
        )}
      </div>

      <div>
        <p className="mb-2 text-sm font-medium">История выводов</p>
        {state.rows.length === 0 ? (
          <p className="text-sm text-muted-foreground">Выводов пока нет.</p>
        ) : (
          <div className="divide-y divide-border">
            {state.rows.map((row) => {
              const status = row.phase || row.status;
              const methodLabel = row.method === "card"
                ? "Карта / СБП"
                : `${String(row.crypto || "Крипта").toUpperCase()}${row.network ? ` · ${String(row.network).toUpperCase()}` : ""}`;
              return (
                <div key={`${row.id}-${row.created_at || ""}`} className="py-3">
                  <div className="flex items-baseline justify-between gap-3">
                    <div className="min-w-0">
                      <p className="truncate text-sm">{methodLabel} · №{row.id}</p>
                      <p className="mt-1 text-xs text-muted-foreground">{formatDate(row.created_at)}</p>
                    </div>
                    <div className="shrink-0 text-right">
                      <p className="font-mono text-sm">{formatMoney(row.amount_rub)} ₽</p>
                      <p className="text-xs text-muted-foreground">{row.status_label || WITHDRAWAL_STATUS[status] || status}</p>
                    </div>
                  </div>
                  {(row.reject_reason || row.status_hint) && <p className="mt-2 text-xs text-muted-foreground">{row.reject_reason || row.status_hint}</p>}
                  {row.network_fee_rub != null && (
                    <p className="mt-2 text-xs text-muted-foreground">
                      Комиссия: {formatMoney(row.network_fee_rub)} ₽
                      {row.payout_amount_rub != null ? ` · к получению: ${formatMoney(row.payout_amount_rub)} ₽` : ""}
                    </p>
                  )}
                  {row.payout_tx_hash && <p className="mt-2 break-all font-mono text-xs text-muted-foreground">Tx: {row.payout_tx_hash}</p>}
                </div>
              );
            })}
          </div>
        )}
      </div>
    </div>
  );
}
