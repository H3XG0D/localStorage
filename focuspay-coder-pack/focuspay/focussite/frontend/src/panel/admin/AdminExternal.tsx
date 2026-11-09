import { useCallback, useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { ChevronRight, Copy, KeyRound } from "lucide-react";
import { toast } from "sonner";
import { ExchangerHmacGuide } from "@/components/ExchangerHmacGuide";
import { PanelApiError } from "@/panel/lib/panelApi";
import {
  completePayout,
  createExchanger,
  getExchangerApiKey,
  getExternalExchangers,
  getExternalSummary,
  getPendingPayouts,
  issueExchangerApiKey,
  patchExchanger,
  rejectPayout,
  resetExchangerPassword,
  revokeExchangerApiKey,
  type Dict,
} from "@/panel/lib/adminApi";
import { Badge, Button, Card, Field, Input, Kpi, Modal, PageHeader, Select, Table, cx, type Column } from "@/panel/ui/primitives";

function money(v: unknown, digits = 2) {
  return new Intl.NumberFormat("ru-RU", { maximumFractionDigits: digits }).format(Number(v ?? 0));
}
function asRows(r: unknown, ...keys: string[]): Dict[] {
  if (Array.isArray(r)) return r as Dict[];
  if (r && typeof r === "object") {
    const rec = r as Dict;
    for (const key of keys) {
      const val = rec[key];
      if (Array.isArray(val)) return val as Dict[];
    }
  }
  return [];
}
function markupLabel(row: Dict) {
  const pct = row.effective_markup_pct ?? row.markup_pct;
  if (pct == null || pct === "") return "—";
  const mode = String(row.effective_markup_mode ?? row.markup_mode ?? "on_deal");
  const modeLabel = mode === "on_turnover" ? "с оборота" : "к базе";
  return `${pct}% · ${modeLabel}`;
}

export async function reissueExchangerCredentials(exchangerId: number): Promise<Dict | null> {
  if (!window.confirm("Старый пароль сразу перестанет работать. Выдать новый случайный и показать данные входа?")) {
    return null;
  }
  return resetExchangerPassword(exchangerId);
}

function accountUsername(row: Dict) {
  const value = row.account_username ?? row.username;
  return value ? String(value) : "";
}

export function AdminExternal() {
  const navigate = useNavigate();
  const [tab, setTab] = useState<"exchangers" | "payouts">("exchangers");
  const [exchangers, setExchangers] = useState<Dict[]>([]);
  const [summary, setSummary] = useState<Dict | null>(null);
  const [payouts, setPayouts] = useState<Dict[]>([]);
  const [credentials, setCredentials] = useState<Dict | null>(null);
  const [createOpen, setCreateOpen] = useState(false);
  const [search, setSearch] = useState("");
  const [status, setStatus] = useState<"all" | "active" | "off">("all");

  const load = useCallback(() => {
    getExternalSummary().then(setSummary).catch(() => undefined);
    getExternalExchangers(true)
      .then((r) => setExchangers(Array.isArray(r) ? r : (r.exchangers as Dict[]) || []))
      .catch((e) => toast.error(e instanceof PanelApiError ? e.message : "Ошибка"));
    getPendingPayouts()
      .then((r) => setPayouts(asRows(r, "items", "payouts")))
      .catch(() => undefined);
  }, []);

  useEffect(() => load(), [load]);

  const visible = useMemo(() => {
    const q = search.trim().toLowerCase();
    return exchangers.filter((row) => {
      if (status === "active" && !row.is_active) return false;
      if (status === "off" && row.is_active) return false;
      if (!q) return true;
      return `${row.name ?? ""} ${row.contact ?? ""} ${accountUsername(row)}`.toLowerCase().includes(q);
    });
  }, [exchangers, search, status]);

  async function reissue(row: Dict) {
    try {
      const issued = await reissueExchangerCredentials(Number(row.id));
      if (!issued) return;
      setCredentials(issued);
      toast.success("Новые данные готовы — сохраните и передайте");
    } catch (e) {
      toast.error(e instanceof PanelApiError ? e.message : "Не удалось перевыдать доступ");
    }
  }

  const exCols: Column<Dict>[] = [
    {
      key: "name",
      label: "Название",
      render: (r) => (
        <div>
          <div>{String(r.name ?? "—")}</div>
          {accountUsername(r) ? (
            <div className="mt-0.5 font-mono text-[11px] text-[var(--text-muted)]">{accountUsername(r)}</div>
          ) : (
            <div className="mt-0.5 text-[11px] text-[var(--text-muted)]">нет логина</div>
          )}
        </div>
      ),
    },
    { key: "markup", label: "Наценка", width: "150px", render: (r) => <span className="font-mono text-[12.5px]">{markupLabel(r)}</span> },
    { key: "balance_usd", label: "Баланс $", width: "110px", align: "right", render: (r) => <span className="font-mono">{money(r.balance_usd)}</span> },
    {
      key: "deals",
      label: "Сделки",
      width: "120px",
      align: "right",
      render: (r) => (
        <span className="font-mono">
          {String(r.deals_confirmed ?? r.deal_count ?? 0)}
          <span className="text-[var(--text-muted)]"> / {String(r.deals_cancelled ?? 0)}</span>
        </span>
      ),
    },
    { key: "conversion_pct", label: "Конверсия", width: "110px", align: "right", render: (r) => (r.conversion_pct != null ? `${r.conversion_pct}%` : "—") },
    {
      key: "is_active",
      label: "Статус",
      width: "170px",
      render: (r) => (
        <div className="flex items-center gap-2" onClick={(e) => e.stopPropagation()}>
          <Badge tone={r.is_active ? "green" : "red"}>{r.is_active ? "Активен" : "Выкл"}</Badge>
          {r.is_trusted_client ? <Badge tone="blue">дов.</Badge> : null}
          <Button
            size="sm"
            variant={r.is_active ? "danger" : "primary"}
            onClick={() =>
              act(
                () => patchExchanger(Number(r.id), { is_active: !r.is_active }),
                r.is_active ? "Внештатник отключён" : "Внештатник включён",
              )
            }
          >
            {r.is_active ? "Отключить" : "Включить"}
          </Button>
        </div>
      ),
    },
    {
      key: "access",
      label: "Доступ",
      width: "140px",
      render: (r) => (
        <div onClick={(e) => e.stopPropagation()}>
          {r.has_account ? (
            <Button size="sm" onClick={() => void reissue(r)}>
              <KeyRound size={14} /> Перевыдать
            </Button>
          ) : (
            <Button size="sm" onClick={() => navigate(`/x8/external/${r.id}?tab=access`)}>
              Выдать
            </Button>
          )}
        </div>
      ),
    },
    {
      key: "_open",
      label: "",
      width: "36px",
      align: "right",
      render: () => <ChevronRight className="ml-auto size-4 text-[var(--text-muted)]" />,
    },
  ];

  const poCols: Column<Dict>[] = [
    { key: "exchanger_name", label: "Обменщик", render: (r) => String(r.exchanger_name ?? r.name ?? "—") },
    { key: "gross_usd", label: "Сумма $", width: "110px", align: "right", render: (r) => <span className="font-mono">{money(r.gross_usd)}</span> },
    { key: "fee_usd", label: "Комиссия $", width: "110px", align: "right", render: (r) => <span className="font-mono">{money(r.fee_usd)}</span> },
    { key: "status", label: "Статус", width: "100px", render: (r) => <Badge tone="yellow">{String(r.status ?? "pending")}</Badge> },
    {
      key: "act",
      label: "",
      width: "170px",
      render: (r) => (
        <div className="flex gap-1">
          <Button size="sm" variant="primary" onClick={() => act(() => completePayout(Number(r.id), {}), "Выплата завершена")}>
            Завершить
          </Button>
          <Button size="sm" variant="danger" onClick={() => act(() => rejectPayout(Number(r.id)), "Отклонено")}>
            Откл
          </Button>
        </div>
      ),
    },
  ];

  async function act(fn: () => Promise<unknown>, ok: string) {
    try {
      await fn();
      toast.success(ok);
      load();
    } catch (e) {
      toast.error(e instanceof PanelApiError ? e.message : "Ошибка");
    }
  }

  return (
    <>
      <PageHeader
        title="Внешние обмены"
        subtitle="Внештатные обменщики · клик по строке открывает карточку, «Перевыдать» даёт новый пароль"
        actions={
          <Button variant="primary" onClick={() => setCreateOpen(true)}>
            + Обменщик
          </Button>
        }
      />

      <div className="grid grid-cols-4 gap-4 max-lg:grid-cols-2 max-[520px]:grid-cols-1">
        <Kpi label="Обменщиков" value={String(summary?.active_count ?? summary?.exchangers_count ?? exchangers.filter((r) => r.is_active).length)} hint={`всего ${summary?.total_count ?? exchangers.length}`} />
        <Kpi label="Оборот ₽" value={money(summary?.total_turnover_base_rub ?? summary?.turnover_usd, 0)} hint={`клиент ${money(summary?.total_turnover_client_rub, 0)} ₽`} />
        <Kpi label="Долг обменщикам $" value={money(summary?.total_balance_usd ?? summary?.liabilities_usd)} />
        <Kpi label="Прибыль дома $" value={money(summary?.house_profit_usd)} hint={`${summary?.total_deals ?? 0} сделок`} />
        <Kpi label="Выплат в ожидании" value={String(payouts.length)} />
      </div>

      <div className="flex w-fit gap-1 rounded-[var(--radius)] border border-[var(--border)] bg-[var(--bg-surface)] p-1">
        {(["exchangers", "payouts"] as const).map((t) => (
          <button
            key={t}
            onClick={() => setTab(t)}
            className={cx(
              "rounded-[var(--radius-sm)] px-3 py-1.5 text-[13px] font-medium transition-colors",
              tab === t ? "bg-[var(--bg-elevated)] text-[var(--text-primary)]" : "text-[var(--text-secondary)] hover:text-[var(--text-primary)]",
            )}
          >
            {t === "exchangers" ? "Обменщики" : `Выплаты (${payouts.length})`}
          </button>
        ))}
      </div>

      <Card>
        {tab === "exchangers" ? (
          <>
            <div className="mb-4 flex flex-wrap items-end justify-between gap-3">
              <div className="text-[13.5px] font-semibold">Список · {visible.length}</div>
              <div className="flex flex-wrap items-end gap-2">
                <Field label="Статус">
                  <Select value={status} onChange={(e) => setStatus(e.target.value as "all" | "active" | "off")}>
                    <option value="all">Все</option>
                    <option value="active">Активные</option>
                    <option value="off">Выключенные</option>
                  </Select>
                </Field>
                <Field label="Поиск">
                  <Input value={search} onChange={(e) => setSearch(e.target.value)} placeholder="Имя / контакт / логин" className="w-[220px]" />
                </Field>
              </div>
            </div>
            <Table columns={exCols} rows={visible} empty="Нет обменщиков" onRowClick={(r) => navigate(`/x8/external/${r.id}`)} />
          </>
        ) : (
          <Table columns={poCols} rows={payouts} empty="Нет выплат в ожидании" />
        )}
      </Card>

      {createOpen && (
        <CreateExchangerModal
          onClose={() => setCreateOpen(false)}
          onDone={(created) => {
            setCreateOpen(false);
            load();
            if (created.password) setCredentials(created);
          }}
        />
      )}
      {credentials && <CredentialsModal credentials={credentials} onClose={() => setCredentials(null)} />}
    </>
  );
}

function CreateExchangerModal({ onClose, onDone }: { onClose: () => void; onDone: (created: Dict) => void }) {
  const [name, setName] = useState("");
  const [markupPct, setMarkupPct] = useState("20");
  const [markupMode, setMarkupMode] = useState<"on_deal" | "on_turnover">("on_deal");
  const [contact, setContact] = useState("");
  const [cabinetUsername, setCabinetUsername] = useState("");
  const [busy, setBusy] = useState(false);

  async function submit() {
    if (!name.trim()) return toast.error("Укажите название");
    setBusy(true);
    try {
      const created = await createExchanger({
        name: name.trim(),
        markup_pct: Number(markupPct),
        markup_mode: markupMode,
        contact: contact || undefined,
        cabinet_username: cabinetUsername.trim() || undefined,
      });
      toast.success("Обменщик создан");
      onDone(created);
    } catch (e) {
      toast.error(e instanceof PanelApiError ? e.message : "Ошибка");
    } finally {
      setBusy(false);
    }
  }

  return (
    <Modal
      open
      title="Новый обменщик"
      onClose={onClose}
      footer={
        <>
          <Button variant="ghost" onClick={onClose}>Отмена</Button>
          <Button variant="primary" disabled={busy} onClick={submit}>Создать</Button>
        </>
      }
    >
      <div className="flex flex-col gap-3">
        <Field label="Название">
          <Input value={name} onChange={(e) => setName(e.target.value)} />
        </Field>
        <div className="grid grid-cols-2 gap-3">
          <Field label="Наценка %">
            <Input value={markupPct} onChange={(e) => setMarkupPct(e.target.value)} className="font-mono" />
          </Field>
          <Field label="Режим">
            <Select value={markupMode} onChange={(e) => setMarkupMode(e.target.value as "on_deal" | "on_turnover")}>
              <option value="on_deal">К базе (сверху)</option>
              <option value="on_turnover">С оборота (вычитается)</option>
            </Select>
          </Field>
        </div>
        <Field label="Контакт (необязательно)">
          <Input value={contact} onChange={(e) => setContact(e.target.value)} />
        </Field>
        <Field label="Логин кабинета (необязательно)">
          <Input value={cabinetUsername} onChange={(e) => setCabinetUsername(e.target.value)} placeholder="Оставьте пустым, чтобы выдать позже" className="font-mono" />
        </Field>
      </div>
    </Modal>
  );
}

export function CredentialsModal({ credentials, onClose }: { credentials: Dict; onClose: () => void }) {
  const username = String(credentials.username ?? "");
  const password = String(credentials.password ?? "");
  const loginUrl = String(credentials.login_url ?? `${window.location.origin}/exchanger/login`);

  async function copy(value: string, label: string) {
    try {
      await navigator.clipboard.writeText(value);
      toast.success(`${label} скопирован`);
    } catch {
      toast.error("Не удалось скопировать");
    }
  }

  return (
    <Modal
      open
      title="Новые данные входа"
      onClose={onClose}
      footer={<Button variant="primary" onClick={onClose}>Готово</Button>}
    >
      <div className="flex flex-col gap-3">
        <div className="rounded-[var(--radius)] border border-yellow-500/30 bg-yellow-500/10 p-3 text-[13px] text-[var(--text-secondary)]">
          Пароль показывается сейчас. Сохраните его и передайте сотруднику защищённым способом.
        </div>
        <CredentialRow label="Логин" value={username} onCopy={() => copy(username, "Логин")} />
        <CredentialRow label="Пароль" value={password} onCopy={() => copy(password, "Пароль")} />
        <CredentialRow label="Ссылка входа" value={loginUrl} onCopy={() => copy(loginUrl, "Ссылка")} />
      </div>
    </Modal>
  );
}

function CredentialRow({ label, value, onCopy }: { label: string; value: string; onCopy: () => void }) {
  return (
    <div className="flex items-end gap-2">
      <Field label={label}>
        <Input value={value} readOnly className="font-mono" />
      </Field>
      <Button size="sm" variant="ghost" aria-label={`Скопировать: ${label}`} title={`Скопировать ${label}`} onClick={onCopy}>
        <Copy size={15} />
      </Button>
    </div>
  );
}

export function ExchangerApiBlock({ exchangerId }: { exchangerId: number }) {
  const [key, setKey] = useState<Dict | null>(null);
  const [secret, setSecret] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const result = await getExchangerApiKey(exchangerId);
      setKey(result.key && typeof result.key === "object" ? result.key : null);
    } catch (e) {
      toast.error(e instanceof PanelApiError ? e.message : "Не удалось загрузить API");
    } finally {
      setLoading(false);
    }
  }, [exchangerId]);

  useEffect(() => {
    void load();
  }, [load]);

  async function copy(value: string, label: string) {
    try {
      await navigator.clipboard.writeText(value);
      toast.success(`${label} скопирован`);
    } catch {
      toast.error("Не удалось скопировать");
    }
  }

  async function issue() {
    if (key?.is_active && !window.confirm("Старый ключ сразу перестанет работать. Выпустить новый?")) return;
    setBusy(true);
    try {
      const issued = await issueExchangerApiKey(exchangerId);
      setKey(issued);
      setSecret(typeof issued.secret === "string" ? issued.secret : null);
      toast.success("Ключ выпущен. Секрет показывается один раз.");
    } catch (e) {
      toast.error(e instanceof PanelApiError ? e.message : "Не удалось выпустить ключ");
    } finally {
      setBusy(false);
    }
  }

  async function revoke() {
    if (!window.confirm("Отозвать ключ? Магазин больше не сможет запрашивать реквизиты.")) return;
    setBusy(true);
    try {
      await revokeExchangerApiKey(exchangerId);
      setSecret(null);
      toast.success("Ключ отозван");
      await load();
    } catch (e) {
      toast.error(e instanceof PanelApiError ? e.message : "Не удалось отозвать ключ");
    } finally {
      setBusy(false);
    }
  }

  const apiKey = typeof key?.api_key === "string" ? key.api_key : "";

  return (
    <div className="rounded-[var(--radius)] border border-[var(--border)] p-3">
      <div className="mb-2 flex items-center gap-2 text-[12px] font-semibold uppercase tracking-wide text-[var(--text-muted)]">
        <KeyRound size={14} /> API реквизитов
      </div>
      <p className="mb-3 text-[13px] text-[var(--text-secondary)]">
        Магазин сам показывает клиенту реквизит. Ключ выпускаете только здесь: внештатник в кабинете выпустить его не может. Секрет покажите один раз.
      </p>
      {loading ? (
        <div className="text-[12px] text-[var(--text-muted)]">Загрузка ключа…</div>
      ) : (
        <>
          {key?.is_active ? (
            <div className="mb-2 flex items-end gap-2">
              <Field label="API key">
                <Input value={apiKey} readOnly className="font-mono text-[12px]" />
              </Field>
              <Button size="sm" variant="ghost" onClick={() => void copy(apiKey, "API key")}>
                <Copy size={14} />
              </Button>
            </div>
          ) : (
            <p className="mb-2 text-[13px] text-[var(--text-muted)]">Ключей нет — выпустите пару для этого магазина.</p>
          )}
          {secret && (
            <div className="mb-2 rounded-[var(--radius)] border border-yellow-500/30 bg-yellow-500/10 p-2">
              <div className="mb-1 text-[12px] text-[var(--text-secondary)]">Секрет виден один раз. Передайте хозяину магазина.</div>
              <div className="flex items-end gap-2">
                <Field label="Secret">
                  <Input value={secret} readOnly className="font-mono text-[12px]" />
                </Field>
                <Button size="sm" variant="ghost" onClick={() => void copy(secret, "Секрет")}>
                  <Copy size={14} />
                </Button>
              </div>
            </div>
          )}
          <div className="mb-3 flex flex-wrap gap-1">
            <Button size="sm" variant="primary" disabled={busy} onClick={() => void issue()}>
              {key?.is_active ? "Новый ключ" : "Выпустить ключ"}
            </Button>
            {Boolean(key?.is_active) && (
              <Button size="sm" variant="danger" disabled={busy} onClick={() => void revoke()}>
                Отозвать
              </Button>
            )}
          </div>
        </>
      )}
      <ExchangerHmacGuide apiKey={apiKey || null} tone="panel" />
    </div>
  );
}
