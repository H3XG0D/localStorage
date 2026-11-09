import { useCallback, useEffect, useState, type ReactNode } from "react";
import { Link } from "react-router-dom";
import {
  CalendarDays,
  CheckCircle2,
  CircleDollarSign,
  Clock3,
  Gift,
  History,
  LockKeyhole,
  Play,
  RefreshCw,
  RotateCcw,
  ShieldCheck,
  Ticket,
  Trophy,
  UserRound,
  Users,
  WalletCards,
  XCircle,
  type LucideIcon,
} from "lucide-react";
import { toast } from "sonner";
import { PanelApiError } from "@/panel/lib/panelApi";
import {
  getRaffle,
  getRaffleCampaigns,
  createRaffle,
  getRaffleParticipant,
  getRaffleParticipants,
  getRafflePartners,
  patchRafflePrizes,
  patchRaffleShowSettings,
  patchRaffleSchedule,
  patchRaffleText,
  raffleAction,
  raffleBlockParticipant,
  raffleBlockPartner,
  raffleUnblockParticipant,
  raffleUnblockPartner,
  type Dict,
} from "@/panel/lib/adminApi";
import { Badge, Button, Card, Field, Input, Kpi, Modal, PageHeader, Table, cx, type BadgeTone, type Column } from "@/panel/ui/primitives";

type Action = "draw" | "activate" | "close" | "start-new-without-draw" | "start-next" | "pay-balance" | "start-show";
type Tab = "participants" | "partners";

const ACTIONS: {
  key: Action;
  label: string;
  description: string;
  confirm: string;
  icon: LucideIcon;
  variant: "primary" | "secondary";
}[] = [
  { key: "activate", label: "Открыть набор", description: "Начать начислять билеты", confirm: "Открыть набор билетов для участников?", icon: Play, variant: "primary" },
  { key: "close", label: "Закрыть набор", description: "Остановить начисление билетов", confirm: "Закрыть набор билетов? Новые билеты больше не будут начисляться.", icon: LockKeyhole, variant: "secondary" },
  { key: "start-show", label: "Запустить шоу", description: "Уведомить и крутить места с 1-го", confirm: "Запустить живой розыгрыш? Набор закроется, места пойдут по очереди, призы начислятся сразу.", icon: Trophy, variant: "primary" },
  { key: "start-next", label: "Следующий цикл", description: "Новый набор, прошлый в истории", confirm: "Начать следующий цикл? Прошедший розыгрыш останется в истории, даты и призы нового можно задать сразу.", icon: RotateCcw, variant: "primary" },
  { key: "start-new-without-draw", label: "Новая кампания", description: "Сорвать набор без розыгрыша", confirm: "Начать новую кампанию без розыгрыша текущей? Победителей не будет.", icon: RotateCcw, variant: "secondary" },
  { key: "pay-balance", label: "Догнать балансы", description: "Старые pending-призы на баланс", confirm: "Выплатить оставшиеся pending-призы на балансы?", icon: WalletCards, variant: "secondary" },
];

const numberFormat = new Intl.NumberFormat("ru-RU", { maximumFractionDigits: 0 });
const moneyFormat = new Intl.NumberFormat("ru-RU", { maximumFractionDigits: 2 });

function displayNumber(value: unknown) {
  if (value === null || value === undefined || value === "") return "—";
  const n = Number(value);
  return Number.isFinite(n) ? numberFormat.format(n) : "—";
}

function money(value: unknown) {
  if (value === null || value === undefined || value === "") return "—";
  const n = Number(value);
  return Number.isFinite(n) ? moneyFormat.format(n) : "—";
}

function dateTime(value: unknown) {
  if (!value) return "—";
  const d = new Date(String(value));
  return Number.isNaN(d.getTime()) ? String(value) : d.toLocaleString("ru-RU", { dateStyle: "medium", timeStyle: "short" });
}

function statusTone(status: unknown): BadgeTone {
  if (status === "active") return "green";
  if (status === "drawn" || status === "drawing") return "blue";
  if (status === "closed") return "yellow";
  return "default";
}

function phaseTone(value: unknown): BadgeTone {
  if (value === "green") return "green";
  if (value === "blue") return "blue";
  if (value === "amber") return "yellow";
  return "default";
}

function statusLabel(status: unknown) {
  if (status === "active") return "Набор билетов идёт";
  if (status === "closed") return "Набор закрыт";
  if (status === "drawing") return "Идёт живой розыгрыш";
  if (status === "drawn") return "Розыгрыш проведён";
  return "Черновик";
}

function blockLabel(row: Dict) {
  if (row.accrual_blocked) return "Заблокирован";
  if (row.referral_accrual_blocked) return "Рефералы заблокированы";
  return "Активен";
}

function blockTone(row: Dict): BadgeTone {
  if (row.accrual_blocked) return "red";
  if (row.referral_accrual_blocked) return "yellow";
  return "green";
}

function formatCountdown(ms: number): string {
  const total = Math.max(0, Math.floor(ms / 1000));
  const d = Math.floor(total / 86400);
  const h = String(Math.floor((total % 86400) / 3600)).padStart(2, "0");
  const m = String(Math.floor((total % 3600) / 60)).padStart(2, "0");
  const s = String(total % 60).padStart(2, "0");
  return d > 0 ? `${d} дн. ${h}:${m}:${s}` : `${h}:${m}:${s}`;
}

function KindTabs() {
  const [kind, setKind] = useState<"monthly" | "weekly">("monthly");
  const [items, setItems] = useState<Dict[]>([]);
  const [now, setNow] = useState(() => Date.now());

  useEffect(() => {
    getRaffleCampaigns()
      .then((r) => setItems(Array.isArray(r.campaigns) ? r.campaigns : []))
      .catch(() => {});
  }, []);

  useEffect(() => {
    const timer = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(timer);
  }, []);

  const upcoming = items
    .filter((row) => String(row.kind ?? "monthly") === kind)
    .map((row) => ({ row, at: new Date(String(row.draw_at ?? "")).getTime() }))
    .filter((x) => Number.isFinite(x.at) && x.at > now)
    .sort((a, b) => a.at - b.at)[0];

  return (
    <div>
      <div className="flex w-fit max-w-full gap-1 overflow-x-auto rounded-[var(--radius)] border border-[var(--border)] bg-[var(--bg-surface)] p-1">
        {(["monthly", "weekly"] as const).map((k) => (
          <button
            key={k}
            type="button"
            onClick={() => setKind(k)}
            className={cx("inline-flex shrink-0 items-center gap-2 rounded-[var(--radius-sm)] px-3 py-2 text-[13px] font-medium transition-colors", kind === k ? "bg-[var(--bg-elevated)] text-[var(--text-primary)]" : "text-[var(--text-secondary)] hover:text-[var(--text-primary)]")}
          >
            {kindLabel(k)}
          </button>
        ))}
      </div>
      <div className="mt-2 flex items-center gap-2 text-[13px] text-[var(--text-secondary)]">
        <Clock3 className="size-4 text-[var(--blue)]" />
        {upcoming ? (
          <span>До следующего {kind === "monthly" ? "месячного" : "недельного"} розыгрыша: <span className="font-mono font-semibold text-[var(--text-primary)]">{formatCountdown(upcoming.at - now)}</span> <span className="text-[var(--text-muted)]">· {dateTime(upcoming.row.draw_at)} МСК</span></span>
        ) : (
          <span>Нет запланированного {kind === "monthly" ? "месячного" : "недельного"} розыгрыша — создайте его ниже.</span>
        )}
      </div>
    </div>
  );
}

export function AdminFocusLucky() {
  const [raffle, setRaffle] = useState<Dict | null>(null);
  const [tab, setTab] = useState<Tab>("participants");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [busyAction, setBusyAction] = useState<Action | null>(null);
  const [selectedParticipant, setSelectedParticipant] = useState<number | null>(null);

  const load = useCallback((quiet = false) => {
    if (!quiet) {
      setLoading(true);
      setError(null);
    }
    getRaffle()
      .then(setRaffle)
      .catch((e) => {
        const message = e instanceof PanelApiError ? e.message : "Не удалось загрузить кампанию";
        if (!quiet) {
          setError(message);
          toast.error(message);
        }
      })
      .finally(() => {
        if (!quiet) setLoading(false);
      });
  }, []);

  useEffect(() => load(), [load]);

  useEffect(() => {
    if (String((raffle?.campaign as Dict | undefined)?.status ?? raffle?.status ?? "") !== "drawing") return;
    const timer = window.setInterval(() => load(true), 2000);
    return () => window.clearInterval(timer);
  }, [load, raffle]);

  async function runAction(action: Action, confirm: string) {
    if (!window.confirm(confirm)) return;
    setBusyAction(action);
    try {
      await raffleAction(action);
      toast.success("Состояние FocusLucky обновлено");
      load();
    } catch (e) {
      toast.error(e instanceof PanelApiError ? e.message : "Не удалось выполнить действие");
    } finally {
      setBusyAction(null);
    }
  }

  const campaign = (raffle?.campaign ?? {}) as Dict;
  const status = String(campaign.status ?? raffle?.status ?? "draft");
  const phaseLabel = String(raffle?.phase_label ?? statusLabel(status));
  const pendingBalance = Number(raffle?.winners_pending_balance ?? 0);
  const winnersPaid = Number(raffle?.winners_paid_count ?? 0);
  const issuedTickets = Number(raffle?.total_tickets_issued ?? Number(raffle?.tickets_own_total ?? 0) + Number(raffle?.tickets_referral_total ?? 0));
  const canUse = (action: Action) => {
    if (action === "activate") return status === "draft" || status === "closed";
    if (action === "close") return status === "active";
    if (action === "start-show") return (status === "active" || status === "closed") && issuedTickets > 0;
    if (action === "start-next") return status === "drawn";
    if (action === "start-new-without-draw") return status === "closed" && winnersPaid === 0;
    return pendingBalance > 0;
  };

  return (
    <>
      <PageHeader
        title="FocusLucky"
        subtitle={phaseLabel}
        actions={<Button size="sm" variant="secondary" onClick={() => load()} disabled={loading} title="Обновить данные" aria-label="Обновить данные"><RefreshCw className={cx("size-4", loading && "animate-spin")} /> Обновить</Button>}
      />

      {error && <Card className="border-[var(--red)]/30 bg-[var(--red-bg)]"><div className="flex items-center gap-2 text-[12px] text-[var(--red)]"><XCircle className="size-4 shrink-0" />{error}</div></Card>}
      <KindTabs />
      {loading && !raffle ? (
        <Card><div className="flex items-center gap-2 text-[13px] text-[var(--text-muted)]"><RefreshCw className="size-4 animate-spin" />Загрузка состояния кампании…</div></Card>
      ) : raffle ? (
        <>
          <CampaignStatus campaign={campaign} raffle={raffle} status={status} phaseLabel={phaseLabel} onDone={load} onStartNext={() => runAction("start-next", ACTIONS.find((a) => a.key === "start-next")!.confirm)} startNextBusy={busyAction === "start-next"} />

          <CreateRaffleCard onDone={load} />

          <div className="grid grid-cols-4 gap-4 max-xl:grid-cols-2 max-[520px]:grid-cols-1">
            <Kpi label="Участников" value={displayNumber(raffle.participants)} hint="Участники текущей кампании" />
            <Kpi label="Билетов в пуле" value={displayNumber(raffle.pool_total)} hint="Активные билеты в розыгрыше" />
            <Kpi label="Билетов выдано" value={displayNumber(issuedTickets)} hint={`Свои ${displayNumber(raffle.tickets_own_total)} · реферальные ${displayNumber(raffle.tickets_referral_total)}`} />
            <Kpi label="Призовой фонд" value={`${money(raffle.prize_pool_rub)} ₽`} hint={`${displayNumber((raffle.winners as Dict[] | undefined)?.length ?? 0)} победителей`} />
          </div>

          <ActionCenter status={status} pendingBalance={pendingBalance} busyAction={busyAction} canUse={canUse} onAction={runAction} />

          <div className="grid grid-cols-1 gap-4 xl:grid-cols-[minmax(0,1.4fr)_minmax(320px,1fr)]">
            <CampaignActivity raffle={raffle} campaign={campaign} />
            <div className="flex flex-col gap-4">
              <PrizePlan raffle={raffle} onDone={load} onStartNext={() => runAction("start-next", ACTIONS.find((a) => a.key === "start-next")!.confirm)} startNextBusy={busyAction === "start-next"} />
              <ShowSettings raffle={raffle} onDone={load} />
            </div>
          </div>

          <div className="flex w-fit max-w-full gap-1 overflow-x-auto rounded-[var(--radius)] border border-[var(--border)] bg-[var(--bg-surface)] p-1">
            <button type="button" onClick={() => setTab("participants")} className={cx("inline-flex shrink-0 items-center gap-2 rounded-[var(--radius-sm)] px-3 py-2 text-[13px] font-medium transition-colors", tab === "participants" ? "bg-[var(--bg-elevated)] text-[var(--text-primary)]" : "text-[var(--text-secondary)] hover:text-[var(--text-primary)]")}><Users className="size-4" />Участники</button>
            <button type="button" onClick={() => setTab("partners")} className={cx("inline-flex shrink-0 items-center gap-2 rounded-[var(--radius-sm)] px-3 py-2 text-[13px] font-medium transition-colors", tab === "partners" ? "bg-[var(--bg-elevated)] text-[var(--text-primary)]" : "text-[var(--text-secondary)] hover:text-[var(--text-primary)]")}><UserRound className="size-4" />Партнёры</button>
          </div>

          {tab === "participants" ? <ParticipantsTable onSelect={setSelectedParticipant} /> : <PartnersTable />}

          <div className="grid grid-cols-2 gap-4 max-[900px]:grid-cols-1">
            <WinnersCard raffle={raffle} />
            <AccrualsCard raffle={raffle} />
          </div>

          <HistoryCard key={`${String(campaign.id)}-${String(campaign.draw_at)}-${String(campaign.prize_pool_rub)}`} currentId={campaign.id} />

          <TextsCard raffle={raffle} onDone={load} />
          {selectedParticipant !== null && <ParticipantDetail userId={selectedParticipant} onClose={() => setSelectedParticipant(null)} />}
        </>
      ) : null}
    </>
  );
}

function toMskDatetimeLocal(value: unknown): string {
  if (!value) return "";
  const d = new Date(String(value));
  if (Number.isNaN(d.getTime())) return "";
  const parts = new Intl.DateTimeFormat("sv-SE", {
    timeZone: "Europe/Moscow",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  }).formatToParts(d);
  const get = (type: string) => parts.find((part) => part.type === type)?.value ?? "";
  const hour = get("hour") === "24" ? "00" : get("hour");
  return `${get("year")}-${get("month")}-${get("day")}T${hour}:${get("minute")}`;
}

function mskLocalToIso(local: string): string {
  const trimmed = local.trim();
  if (!trimmed) return "";
  return trimmed.length === 16 ? `${trimmed}:00+03:00` : `${trimmed}+03:00`;
}

function ProfileLink({ userId, children }: { userId?: number | null; children: ReactNode }) {
  if (userId == null || !Number.isFinite(userId) || userId <= 0) return <>{children}</>;
  return (
    <Link
      to={`/x8/users?user=${userId}`}
      className="min-w-0 truncate text-[var(--accent)] hover:underline"
      onClick={(e) => e.stopPropagation()}
    >
      {children}
    </Link>
  );
}

function personLabel(row: Dict) {
  if (row.username) return `@${String(row.username).replace(/^@/, "")}`;
  return `ID ${row.user_id ?? "—"}`;
}

function kindLabel(kind: unknown) {
  return String(kind ?? "monthly") === "weekly" ? "Недельный" : "Месячный";
}

function kindTone(kind: unknown): BadgeTone {
  return String(kind ?? "monthly") === "weekly" ? "yellow" : "blue";
}

function monthKeyOf(row: Dict): string {
  const raw = String(row.month_key ?? "").slice(0, 7);
  if (/^\d{4}-\d{2}$/.test(raw)) return raw;
  const d = new Date(String(row.draw_at ?? ""));
  if (!Number.isNaN(d.getTime())) {
    const parts = new Intl.DateTimeFormat("sv-SE", { timeZone: "Europe/Moscow", year: "numeric", month: "2-digit" }).format(d);
    if (/^\d{4}-\d{2}$/.test(parts)) return parts;
  }
  return "без месяца";
}

function CreateRaffleCard({ onDone }: { onDone: () => void }) {
  const [kind, setKind] = useState<"weekly" | "monthly">("weekly");
  const [drawLocal, setDrawLocal] = useState("");
  const [busy, setBusy] = useState(false);

  async function create() {
    if (!drawLocal.trim()) {
      toast.error("Укажите дату и время розыгрыша (МСК)");
      return;
    }
    setBusy(true);
    try {
      await createRaffle({ kind, draw_at: mskLocalToIso(drawLocal) });
      toast.success(`${kindLabel(kind)} розыгрыш запланирован`);
      setDrawLocal("");
      onDone();
    } catch (e) {
      toast.error(e instanceof PanelApiError ? e.message : "Не удалось создать розыгрыш");
    } finally {
      setBusy(false);
    }
  }

  return (
    <Card>
      <div className="mb-3 flex items-start justify-between gap-3">
        <div>
          <div className="flex items-center gap-2 text-[13.5px] font-semibold"><CalendarDays className="size-4 text-[var(--green)]" />Новый розыгрыш</div>
          <div className="mt-1 text-[11px] text-[var(--text-muted)]">Настройки (призы, шоу, тексты) общие. В один день два розыгрыша нельзя — минимум 24 часа между ними.</div>
        </div>
      </div>
      <div className="flex flex-wrap items-end gap-3">
        <div className="flex w-fit gap-1 rounded-[var(--radius)] border border-[var(--border)] bg-[var(--bg-surface)] p-1">
          {(["monthly", "weekly"] as const).map((k) => (
            <button key={k} type="button" onClick={() => setKind(k)} className={cx("rounded-[var(--radius-sm)] px-3 py-1.5 text-[13px] font-medium transition-colors", kind === k ? "bg-[var(--bg-elevated)] text-[var(--text-primary)]" : "text-[var(--text-secondary)] hover:text-[var(--text-primary)]")}>{kindLabel(k)}</button>
          ))}
        </div>
        <Field label="Дата и время розыгрыша (МСК)">
          <Input type="datetime-local" value={drawLocal} disabled={busy} onChange={(e) => setDrawLocal(e.target.value)} className="h-9 w-[220px] font-mono" />
        </Field>
        <Button size="sm" variant="primary" disabled={busy} onClick={() => void create()}>{busy ? "Создание…" : "Запланировать"}</Button>
      </div>
    </Card>
  );
}

function CampaignStatus({ campaign, raffle, status, phaseLabel, onDone, onStartNext, startNextBusy }: { campaign: Dict; raffle: Dict; status: string; phaseLabel: string; onDone: () => void; onStartNext: () => void; startNextBusy: boolean }) {
  const progress = Math.max(0, Math.min(100, Number(raffle.campaign_progress_pct ?? 0)));
  const locked = Boolean(raffle.draw_at_locked) || status === "drawing" || status === "drawn";
  const [startLocal, setStartLocal] = useState("");
  const [drawLocal, setDrawLocal] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    setStartLocal(toMskDatetimeLocal(campaign.starts_at));
    setDrawLocal(toMskDatetimeLocal(campaign.draw_at));
  }, [campaign.starts_at, campaign.draw_at]);

  async function saveSchedule() {
    const starts = mskLocalToIso(startLocal);
    const draw = mskLocalToIso(drawLocal);
    if (!starts || !draw) {
      toast.error("Укажите начало набора и время розыгрыша");
      return;
    }
    setBusy(true);
    try {
      await patchRaffleSchedule({ starts_at: starts, draw_at: draw });
      toast.success("Расписание сохранено");
      onDone();
    } catch (e) {
      toast.error(e instanceof PanelApiError ? e.message : "Не удалось сохранить расписание");
    } finally {
      setBusy(false);
    }
  }

  return (
    <Card className="border-[var(--border-strong)]">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            <span className="text-[14px] font-semibold">Текущая кампания</span>
            <Badge tone={statusTone(status)}>{statusLabel(status)}</Badge>
            {!!raffle.accrual_open && <Badge tone="blue">Начисление открыто</Badge>}
          </div>
          <p className="mt-1 max-w-2xl text-[12px] text-[var(--text-muted)]">{phaseLabel}. Набор — билеты за обмены. Розыгрыш — старт шоу в указанное время (или «Запустить шоу» раньше).</p>
        </div>
        <div className="text-right text-[11px] text-[var(--text-muted)]">
          <div>ID кампании <span className="font-mono text-[var(--text-secondary)]">#{String(campaign.id ?? "—")}</span></div>
          <div className="mt-1">Следующий билет <span className="font-mono text-[var(--text-secondary)]">#{displayNumber(raffle.next_ticket_no)}</span></div>
        </div>
      </div>
      {locked ? (
        <div className="mt-4 rounded-[var(--radius)] border border-[var(--border)] bg-[var(--bg-elevated)] px-3 py-2.5 text-[12px] text-[var(--text-secondary)]">
          Даты и призы этого цикла зафиксированы.
          {status === "drawn" ? " Чтобы задать новые — начните следующий цикл." : " Дождитесь конца шоу."}
          {status === "drawn" ? (
            <Button size="sm" variant="primary" className="ml-3" disabled={startNextBusy} onClick={onStartNext}>{startNextBusy ? "…" : "Следующий цикл"}</Button>
          ) : null}
        </div>
      ) : null}
      <div className="mt-5 grid grid-cols-3 gap-3 border-t border-[var(--border)] pt-4 text-[12px] max-[620px]:grid-cols-1">
        {locked ? (
          <Meta icon={CalendarDays} label="Период набора" value={`${dateTime(campaign.starts_at)} — ${dateTime(campaign.draw_at)}`} />
        ) : (
          <div className="min-w-0">
            <div className="mb-1 flex items-center gap-1.5 text-[11px] text-[var(--text-muted)]"><CalendarDays className="size-3.5" />Начало набора (МСК)</div>
            <Input type="datetime-local" value={startLocal} disabled={busy} onChange={(e) => setStartLocal(e.target.value)} className="h-8 w-[210px] font-mono" />
          </div>
        )}
        <div className="min-w-0">
          <div className="mb-1 flex items-center gap-1.5 text-[11px] text-[var(--text-muted)]"><Clock3 className="size-3.5" />Время розыгрыша (МСК)</div>
          {locked ? (
            <div className="font-medium">{dateTime(campaign.draw_at)}</div>
          ) : (
            <div className="flex flex-wrap items-center gap-2">
              <Input type="datetime-local" value={drawLocal} disabled={busy} onChange={(e) => setDrawLocal(e.target.value)} className="h-8 w-[210px] font-mono" />
              <Button size="sm" variant="primary" disabled={busy} onClick={() => void saveSchedule()}>{busy ? "…" : "Сохранить"}</Button>
            </div>
          )}
        </div>
        <Meta icon={ShieldCheck} label="Заблокировано" value={`${displayNumber(raffle.accrual_blocked_count)} участников`} />
      </div>
      <div className="mt-4">
        <div className="mb-1.5 flex items-center justify-between text-[11px] text-[var(--text-muted)]"><span>Прогресс к розыгрышу</span><span className="font-mono text-[var(--text-secondary)]">{progress}%</span></div>
        <div className="h-2 overflow-hidden rounded-full bg-[var(--bg-overlay)]"><div className="h-full rounded-full bg-[var(--blue)] transition-[width] duration-300" style={{ width: `${progress}%` }} /></div>
        <div className="mt-1.5 text-[11px] text-[var(--text-muted)]">{Number(raffle.days_until_draw ?? 0) > 0 ? `До розыгрыша ${displayNumber(raffle.days_until_draw)} дн.` : "Дата розыгрыша наступила или не задана"}</div>
      </div>
    </Card>
  );
}

function ActionCenter({ status, pendingBalance, busyAction, canUse, onAction }: { status: string; pendingBalance: number; busyAction: Action | null; canUse: (action: Action) => boolean; onAction: (action: Action, confirm: string) => void }) {
  const next = status === "active" ? "Задайте время — шоу стартует само, либо запустите вручную" : status === "closed" ? "Дождитесь времени или запустите шоу вручную" : status === "drawing" ? "Места крутятся сами, призы уже на балансе" : status === "drawn" ? "Начните следующий цикл — даты и призы нового можно задать сразу" : "Активируйте кампанию, чтобы началось начисление билетов";
  return (
    <Card>
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div><div className="flex items-center gap-2 text-[13.5px] font-semibold"><CircleDollarSign className="size-4 text-[var(--blue)]" />Управление кампанией</div><div className="mt-1 text-[12px] text-[var(--text-muted)]">Следующий шаг: {next}.</div></div>
        {pendingBalance > 0 && <Badge tone="yellow">К выплате на баланс: {money(pendingBalance)} ₽</Badge>}
      </div>
      <div className="mt-4 grid grid-cols-2 gap-2 xl:grid-cols-3">
        {ACTIONS.map((action) => {
          const Icon = action.icon;
          const enabled = canUse(action.key);
          return (
            <Button key={action.key} variant={action.variant} disabled={!enabled || busyAction !== null} onClick={() => onAction(action.key, action.confirm)} title={enabled ? action.description : "Сейчас недоступно"} className="h-auto min-h-11 justify-start whitespace-normal px-3 py-2 text-left">
              {busyAction === action.key ? <RefreshCw className="size-4 shrink-0 animate-spin" /> : <Icon className="size-4 shrink-0" />}
              <span className="min-w-0"><span className="block text-[12px] leading-tight">{action.label}</span><span className="mt-0.5 block text-[10px] font-normal opacity-70">{action.description}</span></span>
            </Button>
          );
        })}
      </div>
    </Card>
  );
}

function CampaignActivity({ raffle, campaign }: { raffle: Dict; campaign: Dict }) {
  return (
    <Card>
      <div className="mb-3 flex items-start justify-between gap-3"><div><div className="flex items-center gap-2 text-[13.5px] font-semibold"><Ticket className="size-4 text-[var(--blue)]" />Из чего складывается пул</div><div className="mt-1 text-[11px] text-[var(--text-muted)]">Разделение собственных и реферальных билетов.</div></div><Badge tone="blue">{displayNumber(raffle.pool_total)} активных</Badge></div>
      <div className="grid grid-cols-2 gap-3">
        <MetricLine label="За свои обмены" value={displayNumber(raffle.tickets_own_total)} color="var(--blue)" />
        <MetricLine label="За рефералов" value={displayNumber(raffle.tickets_referral_total)} color="var(--purple)" />
      </div>
      <div className="mt-4 grid grid-cols-2 gap-3 border-t border-[var(--border)] pt-3 text-[12px]">
        <Meta icon= {CircleDollarSign} label="Объём своих обменов" value={`${money(raffle.own_volume_total_rub)} ₽`} />
        <Meta icon={Users} label="Объём рефералов" value={`${money(raffle.referral_volume_total_rub)} ₽`} />
      </div>
      <div className="mt-4 rounded-[var(--radius)] bg-[var(--bg-elevated)] p-3 text-[11px] text-[var(--text-muted)]">Кампания <span className="font-mono text-[var(--text-secondary)]">{String(campaign.code ?? campaign.name ?? `#${campaign.id ?? "—"}`)}</span>. Билеты начисляются автоматически после успешных обменов, пока набор открыт.</div>
    </Card>
  );
}

function MetricLine({ label, value, color }: { label: string; value: string; color: string }) {
  return <div className="rounded-[var(--radius)] bg-[var(--bg-elevated)] p-3"><div className="flex items-center gap-2 text-[11px] text-[var(--text-muted)]"><span className="size-2 rounded-full" style={{ backgroundColor: color }} />{label}</div><div className="mt-1 font-mono text-lg font-semibold tabular-nums">{value}</div></div>;
}

function PrizePlan({ raffle, onDone, onStartNext, startNextBusy }: { raffle: Dict; onDone: () => void; onStartNext: () => void; startNextBusy: boolean }) {
  const locked = Boolean(raffle.prizes_locked);
  const source = (raffle.prize_places ?? []) as Dict[];
  const [rows, setRows] = useState<{ place: number; prize_rub: string }[]>([]);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    setRows(source.map((prize, index) => ({
      place: Number(prize.place ?? index + 1),
      prize_rub: String(prize.prize_rub ?? ""),
    })));
  }, [raffle]);

  const pool = rows.reduce((sum, row) => sum + (Number(row.prize_rub) || 0), 0);

  async function save() {
    setBusy(true);
    try {
      await patchRafflePrizes(rows.map((row) => ({ prize_rub: Number(row.prize_rub) })));
      toast.success("Призы сохранены");
      onDone();
    } catch (e) {
      toast.error(e instanceof PanelApiError ? e.message : "Не удалось сохранить призы");
    } finally {
      setBusy(false);
    }
  }

  return (
    <Card>
      <div className="mb-3 flex items-start justify-between gap-3">
        <div>
          <div className="flex items-center gap-2 text-[13.5px] font-semibold"><Gift className="size-4 text-[var(--yellow)]" />Призы</div>
          <div className="mt-1 text-[11px] text-[var(--text-muted)]">{locked ? "Во время и после шоу состав мест только смотрим." : "Места 1…N, сразу на баланс. Добавляйте и убирайте строки."}</div>
        </div>
        <span className="font-mono text-[13px]">{money(pool || raffle.prize_pool_rub)} ₽</span>
      </div>
      {locked && String((raffle.campaign as Dict | undefined)?.status ?? raffle.status ?? "") === "drawn" ? (
        <div className="mb-3 text-[12px] text-[var(--text-secondary)]">
          Чтобы добавить или убрать места —{" "}
          <button type="button" className="text-[var(--accent)] hover:underline" disabled={startNextBusy} onClick={onStartNext}>начните следующий цикл</button>.
        </div>
      ) : null}
      <div className="flex flex-col gap-1.5">
        {rows.map((row, index) => (
          <div key={`place-${index}`} className="flex items-center gap-2 rounded-[var(--radius)] bg-[var(--bg-elevated)] px-3 py-2 text-[12px]">
            <span className="w-6 font-mono text-[var(--text-muted)]">{index + 1}.</span>
            <Input
              type="number"
              min="1"
              step="1"
              value={row.prize_rub}
              disabled={locked || busy}
              onChange={(e) => setRows((current) => current.map((item, i) => (i === index ? { ...item, prize_rub: e.target.value } : item)))}
              className="h-8 w-[140px] font-mono"
            />
            <span className="text-[var(--text-muted)]">₽ на баланс</span>
            <Button size="sm" variant="ghost" disabled={locked || busy || rows.length <= 1} onClick={() => setRows((current) => current.filter((_, i) => i !== index))} className="ml-auto">Убрать</Button>
          </div>
        ))}
      </div>
      {locked ? null : (
        <div className="mt-3 flex flex-wrap gap-2">
          <Button size="sm" variant="secondary" disabled={busy || rows.length >= 20} onClick={() => setRows((current) => [...current, { place: current.length + 1, prize_rub: "500" }])}>Добавить место</Button>
          <Button size="sm" variant="primary" disabled={busy} onClick={() => void save()}>{busy ? "Сохранение…" : "Сохранить призы"}</Button>
        </div>
      )}
    </Card>
  );
}

function ShowSettings({ raffle, onDone }: { raffle: Dict; onDone: () => void }) {
  const locked = Boolean(raffle.show_settings_locked);
  const [intervalSec, setIntervalSec] = useState("30");
  const [preShow, setPreShow] = useState("30");
  const [busy, setBusy] = useState(false);
  const campaign = (raffle.campaign ?? {}) as Dict;
  const drawing = String(campaign.status ?? raffle.status ?? "") === "drawing";
  const schedule = Array.isArray(raffle.notify_schedule) ? (raffle.notify_schedule as Dict[]) : [
    { minutes: 360, label: "за 6 часов" },
    { minutes: 180, label: "за 3 часа" },
    { minutes: 60, label: "за 1 час" },
    { minutes: 10, label: "за 10 минут" },
  ];

  useEffect(() => {
    setIntervalSec(String(raffle.spin_interval_seconds ?? campaign.spin_interval_seconds ?? 30));
    setPreShow(String(raffle.pre_show_seconds ?? campaign.pre_show_seconds ?? 30));
  }, [raffle, campaign.spin_interval_seconds, campaign.pre_show_seconds]);

  async function save() {
    setBusy(true);
    try {
      await patchRaffleShowSettings({
        spin_interval_seconds: Number(intervalSec),
        pre_show_seconds: Number(preShow),
      });
      toast.success("Настройки шоу сохранены");
      onDone();
    } catch (e) {
      toast.error(e instanceof PanelApiError ? e.message : "Не удалось сохранить настройки шоу");
    } finally {
      setBusy(false);
    }
  }

  return (
    <Card>
      <div className="mb-3 flex items-start justify-between gap-3">
        <div>
          <div className="flex items-center gap-2 text-[13.5px] font-semibold"><Clock3 className="size-4 text-[var(--blue)]" />Шоу</div>
          <div className="mt-1 text-[11px] text-[var(--text-muted)]">Одна лента, места с 1-го. Игроки смотрят {String(raffle.watch_path ?? "/casino/play/raffle")}.</div>
        </div>
        {drawing ? <Badge tone="blue">крутится</Badge> : null}
      </div>
      {drawing ? (
        <div className="mb-3 grid grid-cols-2 gap-2 text-[12px]">
          <Meta icon={Trophy} label="Текущее место" value={String(raffle.current_place ?? campaign.current_place ?? "—")} />
          <Meta icon={Clock3} label="Следующий спин" value={dateTime(raffle.next_spin_at ?? campaign.next_spin_at)} />
        </div>
      ) : null}
      <div className="grid grid-cols-1 gap-3">
        <Field label="Интервал между местами (сек, 12–120)"><Input type="number" min="12" max="120" value={intervalSec} disabled={locked || busy} onChange={(e) => setIntervalSec(e.target.value)} /></Field>
        <Field label="Пауза до 1-го места (сек, 5–300)"><Input type="number" min="5" max="300" value={preShow} disabled={locked || busy} onChange={(e) => setPreShow(e.target.value)} /></Field>
      </div>
      <div className="mt-3 rounded-[var(--radius)] bg-[var(--bg-elevated)] p-3 text-[11px] text-[var(--text-muted)]">
        Напоминания всем в боте: {schedule.map((row) => String(row.label ?? `за ${row.minutes} мин`)).join(", ")}.
      </div>
      {locked ? null : <div className="mt-3"><Button size="sm" variant="primary" disabled={busy} onClick={() => void save()}>{busy ? "Сохранение…" : "Сохранить шоу"}</Button></div>}
    </Card>
  );
}

function ParticipantsTable({ onSelect }: { onSelect: (userId: number) => void }) {
  const [rows, setRows] = useState<Dict[]>([]);
  const [loading, setLoading] = useState(true);
  const [search, setSearch] = useState("");
  const [page, setPage] = useState(1);
  const [total, setTotal] = useState(0);
  const [busyId, setBusyId] = useState<number | null>(null);
  const LIMIT = 20;

  const load = useCallback(() => {
    setLoading(true);
    getRaffleParticipants({ page, limit: LIMIT, q: search.trim() || undefined })
      .then((r) => { setRows(Array.isArray(r) ? r : ((r.items as Dict[]) || [])); setTotal(Number(r.total ?? 0)); })
      .catch((e) => toast.error(e instanceof PanelApiError ? e.message : "Не удалось загрузить участников"))
      .finally(() => setLoading(false));
  }, [page, search]);

  useEffect(() => load(), [load]);

  async function toggleBlock(row: Dict) {
    const userId = Number(row.user_id);
    if (!userId) return;
    setBusyId(userId);
    try {
      if (row.accrual_blocked || row.referral_accrual_blocked) await raffleUnblockParticipant(userId);
      else await raffleBlockParticipant(userId, "all");
      toast.success(row.accrual_blocked || row.referral_accrual_blocked ? "Участник разблокирован" : "Участник заблокирован");
      load();
    } catch (e) {
      toast.error(e instanceof PanelApiError ? e.message : "Не удалось изменить блокировку");
    } finally {
      setBusyId(null);
    }
  }

  const cols: Column<Dict>[] = [
    { key: "rank", label: "#", width: "55px", align: "right", render: (r) => <span className="font-mono text-[var(--text-muted)]">{displayNumber(r.rank)}</span> },
    { key: "username", label: "Участник", render: (r) => <div><div><ProfileLink userId={Number(r.user_id) || null}>{r.username ? `@${String(r.username).replace(/^@/, "")}` : "Без username"}</ProfileLink></div><div className="font-mono text-[10px] text-[var(--text-muted)]">{String(r.user_id ?? "—")}</div></div> },
    { key: "tickets_total", label: "Билеты", width: "90px", align: "right", render: (r) => <span className="font-mono">{displayNumber(r.tickets_total)}</span> },
    { key: "tickets_referral", label: "Реф.", width: "80px", align: "right", render: (r) => <span className="font-mono">{displayNumber(r.tickets_referral)}</span> },
    { key: "win_chance_label", label: "Шанс", width: "80px", align: "right", render: (r) => String(r.win_chance_label ?? "0%") },
    { key: "block", label: "Статус", width: "190px", render: (r) => <div className="flex items-center justify-between gap-2"><Badge tone={blockTone(r)}>{blockLabel(r)}</Badge><Button size="sm" variant={r.accrual_blocked || r.referral_accrual_blocked ? "secondary" : "danger"} disabled={busyId === Number(r.user_id)} onClick={(e) => { e.stopPropagation(); toggleBlock(r); }}>{r.accrual_blocked || r.referral_accrual_blocked ? "Разблокировать" : "Блокировать"}</Button></div> },
  ];

  return (
    <Card>
      <div className="mb-4 flex flex-wrap items-end justify-between gap-3"><div><div className="flex items-center gap-2 text-[13.5px] font-semibold"><Users className="size-4" />Участники · {total}</div><div className="mt-1 text-[11px] text-[var(--text-muted)]">Нажмите на строку, чтобы посмотреть номера билетов и объёмы.</div></div><Field label="Поиск"><Input value={search} onChange={(e) => { setSearch(e.target.value); setPage(1); }} placeholder="ID / username" className="w-[220px]" /></Field></div>
      <div className="hidden md:block"><Table columns={cols} rows={rows} empty={loading ? "Загрузка…" : "Участников нет"} onRowClick={(row) => onSelect(Number(row.user_id))} /></div>
      <div className="flex flex-col gap-2 md:hidden">{loading ? <EmptyState text="Загрузка…" /> : rows.length ? rows.map((row) => <ParticipantMobileRow key={String(row.user_id)} row={row} busy={busyId === Number(row.user_id)} onSelect={() => onSelect(Number(row.user_id))} onToggle={() => toggleBlock(row)} />) : <EmptyState text="Участников нет" />}</div>
      <RafflePager page={page} total={total} limit={LIMIT} onPage={setPage} />
    </Card>
  );
}

function ParticipantMobileRow({ row, busy, onSelect, onToggle }: { row: Dict; busy: boolean; onSelect: () => void; onToggle: () => void }) {
  const blocked = Boolean(row.accrual_blocked || row.referral_accrual_blocked);
  return <div role="button" tabIndex={0} onClick={onSelect} onKeyDown={(e) => { if (e.key === "Enter") onSelect(); }} className="rounded-[var(--radius)] border border-[var(--border)] bg-[var(--bg-elevated)] p-3"><div className="flex items-start justify-between gap-3"><div><div className="font-medium"><ProfileLink userId={Number(row.user_id) || null}>{row.username ? `@${String(row.username).replace(/^@/, "")}` : "Без username"}</ProfileLink></div><div className="font-mono text-[10px] text-[var(--text-muted)]">{String(row.user_id ?? "—")}</div></div><Badge tone={blockTone(row)}>{blockLabel(row)}</Badge></div><div className="mt-3 grid grid-cols-3 gap-2 text-[11px]"><MetricValue label="Билеты" value={displayNumber(row.tickets_total)} /><MetricValue label="Реф." value={displayNumber(row.tickets_referral)} /><MetricValue label="Шанс" value={String(row.win_chance_label ?? "0%")} /></div><Button size="sm" variant={blocked ? "secondary" : "danger"} disabled={busy} onClick={(e) => { e.stopPropagation(); onToggle(); }} className="mt-3 w-full">{blocked ? "Разблокировать" : "Блокировать"}</Button></div>;
}

function PartnersTable() {
  const [rows, setRows] = useState<Dict[]>([]);
  const [loading, setLoading] = useState(true);
  const [search, setSearch] = useState("");
  const [page, setPage] = useState(1);
  const [total, setTotal] = useState(0);
  const [busyId, setBusyId] = useState<number | null>(null);
  const LIMIT = 30;

  const load = useCallback(() => {
    setLoading(true);
    getRafflePartners({ page, limit: LIMIT, q: search.trim() || undefined })
      .then((r) => { setRows(Array.isArray(r) ? r : ((r.items as Dict[]) || [])); setTotal(Number(r.total ?? 0)); })
      .catch((e) => toast.error(e instanceof PanelApiError ? e.message : "Не удалось загрузить партнёров"))
      .finally(() => setLoading(false));
  }, [page, search]);

  useEffect(() => load(), [load]);

  async function toggleBlock(row: Dict) {
    const userId = Number(row.telegram_user_id);
    if (!userId) return;
    setBusyId(userId);
    try {
      if (row.accrual_blocked || row.referral_accrual_blocked) await raffleUnblockPartner(userId);
      else await raffleBlockPartner(userId);
      toast.success(row.accrual_blocked || row.referral_accrual_blocked ? "Партнёр разблокирован" : "Реферальные начисления заблокированы");
      load();
    } catch (e) {
      toast.error(e instanceof PanelApiError ? e.message : "Не удалось изменить блокировку");
    } finally {
      setBusyId(null);
    }
  }

  const cols: Column<Dict>[] = [
    { key: "partner", label: "Партнёр", render: (r) => <div><div>{String(r.display_name ?? r.partner_login ?? r.tg_username ?? "Без имени")}</div><div className="font-mono text-[10px] text-[var(--text-muted)]">{r.telegram_user_id ? `TG ${r.telegram_user_id}` : "Telegram не привязан"}</div></div> },
    { key: "promo_code", label: "Код", render: (r) => <span className="font-mono">{String(r.promo_code ?? "—")}</span> },
    { key: "tickets_total", label: "Билеты", width: "90px", align: "right", render: (r) => displayNumber(r.tickets_total) },
    { key: "tickets_referral", label: "Реф.", width: "80px", align: "right", render: (r) => displayNumber(r.tickets_referral) },
    { key: "invited", label: "Приглашено", width: "110px", align: "right", render: (r) => displayNumber(r.uref_invited_count ?? r.promo_attributed_count) },
    { key: "status", label: "Статус", width: "210px", render: (r) => <div className="flex items-center justify-between gap-2"><Badge tone={r.referral_accrual_blocked ? "red" : "green"}>{r.referral_accrual_blocked ? "Рефералы заблокированы" : "Активен"}</Badge>{r.telegram_user_id ? <Button size="sm" variant={r.referral_accrual_blocked ? "secondary" : "danger"} disabled={busyId === Number(r.telegram_user_id)} onClick={() => toggleBlock(r)}>{r.referral_accrual_blocked ? "Разблокировать" : "Блокировать"}</Button> : <span className="text-[11px] text-[var(--text-muted)]">Нет Telegram</span>}</div> },
  ];

  return (
    <Card>
      <div className="mb-4 flex flex-wrap items-end justify-between gap-3"><div><div className="flex items-center gap-2 text-[13.5px] font-semibold"><UserRound className="size-4" />Партнёры · {total}</div><div className="mt-1 text-[11px] text-[var(--text-muted)]">Состояние реферальных начислений и вклад в пул билетов.</div></div><Field label="Поиск"><Input value={search} onChange={(e) => { setSearch(e.target.value); setPage(1); }} placeholder="ID / код / username" className="w-[220px]" /></Field></div>
      <Table columns={cols} rows={rows} empty={loading ? "Загрузка…" : "Партнёров нет"} />
      <RafflePager page={page} total={total} limit={LIMIT} onPage={setPage} />
    </Card>
  );
}

function ParticipantDetail({ userId, onClose }: { userId: number; onClose: () => void }) {
  const [data, setData] = useState<Dict | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => { getRaffleParticipant(userId).then(setData).catch((e) => setError(e instanceof PanelApiError ? e.message : "Не удалось загрузить участника")); }, [userId]);
  return <Modal open title={`Участник #${userId}`} onClose={onClose} footer={<div className="flex gap-2"><Link to={`/x8/users?user=${userId}`} className="inline-flex h-9 items-center rounded-[var(--radius)] px-3 text-[13px] text-[var(--accent)] hover:underline">Открыть профиль</Link><Button variant="ghost" onClick={onClose}>Закрыть</Button></div>}>
    {error ? <div className="text-[12px] text-[var(--red)]">{error}</div> : !data ? <div className="text-[12px] text-[var(--text-muted)]">Загрузка…</div> : <div className="grid grid-cols-2 gap-3 text-[13px]">{[
      ["Username", data.username ? `@${String(data.username).replace(/^@/, "")}` : "—"],
      ["Всего билетов", displayNumber(data.tickets_total)],
      ["За свои обмены", displayNumber(data.tickets_own)],
      ["За рефералов", displayNumber(data.tickets_referral)],
      ["Шанс", String(data.win_chance_label ?? "0%")],
      ["Номера билетов", String(data.ticket_numbers ?? "—")],
      ["Объём своих обменов", `${money(data.own_volume_rub)} ₽`],
      ["Объём рефералов", `${money(data.referral_volume_rub)} ₽`],
    ].map(([label, value]) => <div key={String(label)} className="rounded-[var(--radius)] bg-[var(--bg-elevated)] p-2.5"><div className="text-[10px] uppercase tracking-wide text-[var(--text-muted)]">{label}</div><div className="mt-0.5 break-words text-[13px]">{value}</div></div>)}</div>}
  </Modal>;
}

function WinnersCard({ raffle }: { raffle: Dict }) {
  const winners = (raffle.winners ?? []) as Dict[];
  return <Card><div className="mb-3 flex items-start justify-between gap-3"><div><div className="flex items-center gap-2 text-[13.5px] font-semibold"><Trophy className="size-4 text-[var(--yellow)]" />Победители</div><div className="mt-1 text-[11px] text-[var(--text-muted)]">Появляются по мере спина. Имя ведёт в профиль. «Начислено» — уже на балансе.</div></div>{winners.length > 0 && <Badge tone="blue">{winners.length} мест</Badge>}</div>{winners.length ? <div className="flex flex-col gap-1.5">{winners.map((winner, index) => <div key={`${String(winner.place ?? index)}-${String(winner.user_id)}`} className="flex items-center justify-between gap-3 rounded-[var(--radius)] bg-[var(--bg-elevated)] px-3 py-2 text-[12px]"><span className="flex min-w-0 items-center gap-2"><span className="w-5 font-mono text-[var(--text-muted)]">{String(winner.place ?? index + 1)}.</span><ProfileLink userId={Number(winner.user_id) || null}>{personLabel(winner)}</ProfileLink></span><span className="flex shrink-0 items-center gap-2"><span className="font-mono">{money(winner.prize_rub)} ₽</span><Badge tone={winner.payout_status === "paid" ? "green" : "yellow"}>{winner.payout_status === "paid" ? "начислено" : String(winner.payout_status ?? "pending")}</Badge></span></div>)}</div> : <EmptyState icon={Trophy} text="Розыгрыш ещё не начался" />}</Card>;
}

function AccrualsCard({ raffle }: { raffle: Dict }) {
  const rows = (raffle.recent_accruals ?? []) as Dict[];
  return <Card><div className="mb-3 flex items-start justify-between gap-3"><div><div className="flex items-center gap-2 text-[13.5px] font-semibold"><Ticket className="size-4 text-[var(--blue)]" />Последние начисления</div><div className="mt-1 text-[11px] text-[var(--text-muted)]">Последние выданные номера билетов.</div></div>{rows.length > 0 && <Badge tone="default">{rows.length} записей</Badge>}</div>{rows.length ? <div className="flex flex-col gap-1.5">{rows.slice(0, 8).map((row, index) => <div key={`${String(row.order_id)}-${index}`} className="flex items-center justify-between gap-3 rounded-[var(--radius)] bg-[var(--bg-elevated)] px-3 py-2 text-[12px]"><ProfileLink userId={Number(row.user_id) || null}>{personLabel(row)}</ProfileLink><span className="shrink-0 text-[var(--text-muted)]">{String(row.kind_label ?? row.kind ?? "—")}</span><span className="shrink-0 font-mono">{String(row.ticket_label ?? `+${row.ticket_count ?? 0}`)}</span></div>)}</div> : <EmptyState icon={Ticket} text="Начислений пока нет" />}</Card>;
}

function HistoryCard({ currentId }: { currentId: unknown }) {
  const [items, setItems] = useState<Dict[]>([]);
  const [openId, setOpenId] = useState<number | null>(null);
  const [loading, setLoading] = useState(true);

  const load = useCallback(() => {
    setLoading(true);
    getRaffleCampaigns()
      .then((r) => setItems(Array.isArray(r.campaigns) ? r.campaigns : []))
      .catch((e) => toast.error(e instanceof PanelApiError ? e.message : "Не удалось загрузить историю"))
      .finally(() => setLoading(false));
  }, []);

  useEffect(() => { load(); }, [load, currentId]);

  const [kindTab, setKindTab] = useState<"all" | "monthly" | "weekly">("all");
  const [monthSel, setMonthSel] = useState<string>("all");
  const months = [...new Set(items.map(monthKeyOf))].sort().reverse();
  const visible = items.filter((row) => {
    if (kindTab !== "all" && String(row.kind ?? "monthly") !== kindTab) return false;
    if (monthSel !== "all" && monthKeyOf(row) !== monthSel) return false;
    return true;
  });

  return (
    <Card>
      <div className="mb-3 flex flex-wrap items-start justify-between gap-3">
        <div>
          <div className="flex items-center gap-2 text-[13.5px] font-semibold"><History className="size-4 text-[var(--blue)]" />История розыгрышей</div>
          <div className="mt-1 text-[11px] text-[var(--text-muted)]">Прошлые циклы. Нажмите строку, чтобы увидеть победителей.</div>
        </div>
        <Badge tone="default">{visible.length}/{items.length}</Badge>
      </div>
      <div className="mb-3 flex flex-wrap items-center gap-2">
        <div className="flex w-fit gap-1 rounded-[var(--radius)] border border-[var(--border)] bg-[var(--bg-surface)] p-1">
          {(["all", "monthly", "weekly"] as const).map((k) => (
            <button key={k} type="button" onClick={() => setKindTab(k)} className={cx("rounded-[var(--radius-sm)] px-3 py-1.5 text-[12px] font-medium transition-colors", kindTab === k ? "bg-[var(--bg-elevated)] text-[var(--text-primary)]" : "text-[var(--text-secondary)] hover:text-[var(--text-primary)]")}>{k === "all" ? "Все" : kindLabel(k)}</button>
          ))}
        </div>
        <select value={monthSel} onChange={(e) => setMonthSel(e.target.value)} className="h-8 rounded-[var(--radius)] border border-[var(--border-strong)] bg-[var(--bg-elevated)] px-2 text-[12px] text-[var(--text-primary)]">
          <option value="all">Все месяцы</option>
          {months.map((m) => <option key={m} value={m}>{m}</option>)}
        </select>
      </div>
      {loading ? <EmptyState text="Загрузка…" /> : visible.length === 0 ? <EmptyState icon={History} text="Кампаний пока нет" /> : (
        <div className="flex flex-col gap-1.5">
          {visible.map((row) => {
            const id = Number(row.campaign_id);
            const open = openId === id;
            const winners = (row.winners ?? []) as Dict[];
            return (
              <div key={id} className="rounded-[var(--radius)] bg-[var(--bg-elevated)]">
                <button type="button" className="flex w-full items-center justify-between gap-3 px-3 py-2 text-left text-[12px]" onClick={() => setOpenId(open ? null : id)}>
                  <span className="min-w-0">
                    <span className="font-medium">{String(row.month_label || row.title || `Кампания #${id}`)}</span>
                    <Badge tone={kindTone(row.kind)} className="ml-2">{kindLabel(row.kind)}</Badge>
                    {row.is_current ? <Badge tone="blue" className="ml-2">текущая</Badge> : null}
                    <span className="mt-0.5 block text-[11px] text-[var(--text-muted)]">{statusLabel(row.status)} · {dateTime(row.draw_at)} · {money(row.prize_pool_rub)} ₽ · {displayNumber(row.ticket_count)} билетов</span>
                  </span>
                  <span className="shrink-0 font-mono text-[var(--text-muted)]">{displayNumber(row.winner_count)} мест</span>
                </button>
                {open ? (
                  winners.length ? (
                    <div className="flex flex-col gap-1 border-t border-[var(--border)] px-3 py-2">
                      {winners.map((winner, index) => (
                        <div key={`${id}-${String(winner.place ?? index)}`} className="flex items-center justify-between gap-3 text-[12px]">
                          <span className="flex min-w-0 items-center gap-2">
                            <span className="w-5 font-mono text-[var(--text-muted)]">{String(winner.place ?? index + 1)}.</span>
                            <ProfileLink userId={Number(winner.user_id) || null}>{personLabel(winner)}</ProfileLink>
                          </span>
                          <span className="flex shrink-0 items-center gap-2">
                            <span className="font-mono">{money(winner.prize_rub)} ₽</span>
                            <Badge tone={winner.payout_status === "paid" ? "green" : "yellow"}>{winner.payout_status === "paid" ? "начислено" : String(winner.payout_status ?? "pending")}</Badge>
                          </span>
                        </div>
                      ))}
                    </div>
                  ) : <div className="border-t border-[var(--border)] px-3 py-2 text-[11px] text-[var(--text-muted)]">Победителей нет</div>
                ) : null}
              </div>
            );
          })}
        </div>
      )}
    </Card>
  );
}

function TextsCard({ raffle, onDone }: { raffle: Dict; onDone: () => void }) {
  const [info, setInfo] = useState("");
  const [how, setHow] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => { const campaign = (raffle.campaign ?? {}) as Dict; setInfo(String(raffle.resolved_info_text ?? campaign.info_text ?? "")); setHow(String(raffle.resolved_how_to_text ?? campaign.how_to_text ?? "")); }, [raffle]);

  async function save() {
    setBusy(true);
    try { await patchRaffleText({ info_text: info, how_to_text: how }); toast.success("Тексты сохранены"); onDone(); } catch (e) { toast.error(e instanceof PanelApiError ? e.message : "Не удалось сохранить тексты"); } finally { setBusy(false); }
  }

  const textareaClass = "w-full rounded-[var(--radius)] border border-[var(--border-strong)] bg-[var(--bg-elevated)] px-3 py-2 text-[13px] text-[var(--text-primary)] placeholder:text-[var(--text-muted)] outline-none focus:border-[var(--text-muted)]";
  return <Card><div className="mb-3 flex items-start justify-between gap-3"><div><div className="flex items-center gap-2 text-[13.5px] font-semibold"><CheckCircle2 className="size-4 text-[var(--green)]" />Тексты для участников</div><div className="mt-1 text-[11px] text-[var(--text-muted)]">Эти тексты показываются в боте и объясняют правила FocusLucky.</div></div><Button variant="primary" size="sm" disabled={busy} onClick={save}>{busy ? "Сохранение…" : "Сохранить тексты"}</Button></div><div className="grid grid-cols-2 gap-4 max-[700px]:grid-cols-1"><Field label="Коротко о билетах"><textarea rows={5} value={info} onChange={(e) => setInfo(e.target.value)} className={textareaClass} /></Field><Field label="Как участвовать"><textarea rows={5} value={how} onChange={(e) => setHow(e.target.value)} className={textareaClass} /></Field></div></Card>;
}

function Meta({ icon: Icon, label, value }: { icon: LucideIcon; label: string; value: string }) {
  return <div className="flex min-w-0 items-start gap-2"><Icon className="mt-0.5 size-4 shrink-0 text-[var(--text-muted)]" /><div className="min-w-0"><div className="text-[10px] uppercase tracking-wide text-[var(--text-muted)]">{label}</div><div className="mt-0.5 truncate text-[12px] text-[var(--text-secondary)]">{value}</div></div></div>;
}

function MetricValue({ label, value }: { label: string; value: string }) {
  return <div><div className="text-[10px] uppercase tracking-wide text-[var(--text-muted)]">{label}</div><div className="mt-0.5 font-mono text-[13px]">{value}</div></div>;
}

function EmptyState({ text, icon: Icon }: { text: string; icon?: LucideIcon }) {
  return <div className="flex items-center justify-center gap-2 py-8 text-center text-[12px] text-[var(--text-muted)]">{Icon && <Icon className="size-4" />}{text}</div>;
}

function RafflePager({ page, total, limit, onPage }: { page: number; total: number; limit: number; onPage: (page: number) => void }) {
  const pages = Math.max(1, Math.ceil(total / limit));
  return <div className="mt-4 flex items-center justify-between text-[12px] text-[var(--text-muted)]"><span>Стр. {page}/{pages}</span><div className="flex items-center gap-2"><Button size="sm" variant="secondary" disabled={page <= 1} onClick={() => onPage(Math.max(1, page - 1))}>Назад</Button><Button size="sm" variant="secondary" disabled={page >= pages} onClick={() => onPage(Math.min(pages, page + 1))}>Вперёд</Button></div></div>;
}
