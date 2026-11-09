import { useCallback, useEffect, useState } from "react";
import { BadgePercent, Gift, Plus, Trash2 } from "lucide-react";
import { toast } from "sonner";
import { panelApi, PanelApiError } from "@/panel/lib/panelApi";
import { Badge, Button, Card, Field, Input, Kpi, Modal, PageHeader, Table, cx, type BadgeTone, type Column } from "@/panel/ui/primitives";

interface Promo {
  id: number;
  code?: string;
  name?: string;
  kind?: string;
  campaign_kind?: string;
  status?: string;
  client_fixed_bonus_rub?: number;
  amount_rub?: number;
  bonus_rub?: number;
  min_order_rub?: number;
  max_activations?: number;
  activations?: number;
  activations_used?: number;
  is_active?: boolean;
  [k: string]: unknown;
}

type PromoGiftKind = "fixed_rub" | "exchange_discount";

const op = <T,>(path: string, opts: Omit<Parameters<typeof panelApi>[1], "scope"> = {}) => panelApi<T>(`/operator${path}`, { ...opts, scope: "operator" });
const tone = (s?: string): BadgeTone => (s === "active" ? "green" : s === "exhausted" ? "orange" : s === "disabled" ? "red" : s === "held" ? "yellow" : "default");

function formatRub(value: unknown) {
  return `${new Intl.NumberFormat("ru-RU").format(Number(value) || 0)} ₽`;
}

function promoValue(row: Promo) {
  return Number(row.client_fixed_bonus_rub ?? row.amount_rub ?? row.bonus_rub ?? 0);
}

function activationCount(row: Promo) {
  return Number(row.activations_used ?? row.activations ?? 0);
}

function statusValue(row: Promo) {
  return String(row.status || (row.is_active === false ? "disabled" : "active"));
}

function statusLabel(status: string) {
  return status === "active" ? "Активна" : status === "exhausted" ? "Лимит исчерпан" : status === "disabled" ? "Выключена" : status === "held" ? "В заказе" : status === "used" ? "Использована" : status === "released" ? "Снята" : status;
}

function formatDate(value: unknown) {
  if (!value) return "—";
  const date = new Date(String(value));
  return Number.isNaN(date.getTime()) ? "—" : date.toLocaleDateString("ru-RU", { day: "2-digit", month: "2-digit", year: "2-digit" });
}

function promoKind(row: Promo) {
  return String(row.campaign_kind ?? row.kind ?? "fixed_rub");
}

function promoKindLabel(kind: string) {
  if (kind === "exchange_discount") return "Скидка на обмен";
  if (kind === "fixed_rub") return "На баланс";
  return kind || "—";
}

function promoKindTone(kind: string): BadgeTone {
  return kind === "exchange_discount" ? "purple" : kind === "fixed_rub" ? "blue" : "default";
}

export function OperatorPromo() {
  const [tab, setTab] = useState<"promos" | "discounts">("promos");
  const [rows, setRows] = useState<Promo[]>([]);
  const [loading, setLoading] = useState(true);
  const [createOpen, setCreateOpen] = useState(false);

  const load = useCallback(() => {
    setLoading(true);
    const path = tab === "promos" ? "/promos" : "/discounts";
    op<{ promos?: Promo[]; discounts?: Promo[]; grants?: Promo[] } | Promo[]>(path, { query: { mine_only: tab === "promos" ? true : undefined } })
      .then((r) => setRows(Array.isArray(r) ? r : (r.promos || r.discounts || r.grants || [])))
      .catch((e) => toast.error(e instanceof PanelApiError ? e.message : "Ошибка"))
      .finally(() => setLoading(false));
  }, [tab]);

  useEffect(() => load(), [load]);

  const activeCount = rows.filter((row) => statusValue(row) === "active").length;
  const activations = rows.reduce((sum, row) => sum + activationCount(row), 0);
  const bonusTotal = rows.reduce((sum, row) => sum + promoValue(row), 0);

  const cols: Column<Promo>[] = tab === "promos"
    ? [
        {
          key: "code",
          label: "Промо",
          render: (r) => (
            <div className="min-w-[150px]">
              <div className="font-mono font-semibold text-[var(--text-primary)]">{r.code || `#${r.id}`}</div>
              <div className="mt-0.5 truncate text-[11px] text-[var(--text-muted)]">{r.name || "Без названия"}</div>
            </div>
          ),
        },
        {
          key: "bonus",
          label: "Вознаграждение",
          render: (r) => (
            <div>
              <div className="font-mono font-semibold tabular-nums">{formatRub(promoValue(r))}</div>
              <div className="mt-0.5 text-[11px] text-[var(--text-muted)]">{Number(r.min_order_rub) > 0 ? `от ${formatRub(r.min_order_rub)}` : "Без минимума"}</div>
            </div>
          ),
        },
        {
          key: "kind",
          label: "Тип",
          width: "150px",
          render: (r) => {
            const kind = promoKind(r);
            return <Badge tone={promoKindTone(kind)}>{promoKindLabel(kind)}</Badge>;
          },
        },
        {
          key: "act",
          label: "Использование",
          width: "135px",
          render: (r) => (
            <div>
              <div className="font-mono tabular-nums">{activationCount(r)} / {r.max_activations ?? "∞"}</div>
              <div className="mt-1 h-1 w-20 overflow-hidden rounded-full bg-[var(--bg-overlay)]">
                <div
                  className="h-full rounded-full bg-[var(--blue)]"
                  style={{ width: `${Math.min(100, Number(r.max_activations) > 0 ? (activationCount(r) / Number(r.max_activations)) * 100 : 0)}%` }}
                />
              </div>
            </div>
          ),
        },
        {
          key: "status",
          label: "Статус",
          width: "145px",
          render: (r) => {
            const status = statusValue(r);
            return <Badge tone={tone(status)}>{statusLabel(status)}</Badge>;
          },
        },
        {
          key: "del",
          label: "",
          width: "54px",
          align: "right",
          render: (r) => <DeleteButton id={r.id} label={r.code || `промо #${r.id}`} onDelete={del} />,
        },
      ]
    : [
        {
          key: "client",
          label: "Клиент",
          render: (r) => (
            <div className="min-w-[150px]">
              <div className="font-medium">{String(r.user_label || r.username || `ID ${r.user_id ?? r.id}`)}</div>
              <div className="mt-0.5 truncate text-[11px] text-[var(--text-muted)]">{String(r.label || "Персональная скидка")}</div>
            </div>
          ),
        },
        {
          key: "amount",
          label: "Сумма скидки",
          render: (r) => (
            <div>
              <div className="font-mono font-semibold tabular-nums">{formatRub(r.amount_rub)}</div>
              <div className="mt-0.5 text-[11px] text-[var(--text-muted)]">{Number(r.min_order_rub) > 0 ? `от ${formatRub(r.min_order_rub)}` : "Без минимума"}</div>
            </div>
          ),
        },
        { key: "issued", label: "Выдана", width: "110px", render: (r) => <span className="text-[11px] text-[var(--text-muted)]">{formatDate(r.created_at)}</span> },
        { key: "status", label: "Статус", width: "135px", render: (r) => <Badge tone={tone(String(r.status || "active"))}>{statusLabel(String(r.status || "active"))}</Badge> },
        {
          key: "del",
          label: "",
          width: "54px",
          align: "right",
          render: (r) => <DeleteButton id={r.id} label={`скидку #${r.id}`} onDelete={del} />,
        },
      ];

  async function del(id: number) {
    try {
      await op(`/${tab}/${id}`, { method: "DELETE" });
      toast.success("Удалено");
      load();
    } catch (e) {
      toast.error(e instanceof PanelApiError ? e.message : "Ошибка");
    }
  }

  return (
    <>
      <PageHeader
        title="Промо и скидки"
        subtitle="Управление бонусами для клиентов"
        actions={
          <Button variant="primary" onClick={() => setCreateOpen(true)}>
            <Plus className="size-3.5" /> Создать
          </Button>
        }
      />

      <div className="grid gap-3 sm:grid-cols-3">
        <Kpi label={tab === "promos" ? "Кампании" : "Выдано скидок"} value={rows.length} hint={tab === "promos" ? "Промокоды оператора" : "Персональные предложения"} />
        <Kpi label="Активные" value={activeCount} hint="Доступны клиентам" />
        <Kpi label={tab === "promos" ? "Активации" : "Объём скидок"} value={tab === "promos" ? activations : formatRub(bonusTotal)} hint={tab === "promos" ? `Сумма бонусов ${formatRub(bonusTotal)}` : "По текущему списку"} />
      </div>

      <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <div className="flex w-fit gap-1 rounded-[var(--radius)] border border-[var(--border)] bg-[var(--bg-surface)] p-1" role="tablist" aria-label="Тип бонуса">
          {(["promos", "discounts"] as const).map((t) => (
            <button
              key={t}
              type="button"
              role="tab"
              aria-selected={tab === t}
              onClick={() => setTab(t)}
              className={cx(
                "inline-flex items-center gap-2 rounded-[var(--radius-sm)] px-3 py-1.5 text-[13px] font-medium transition-colors",
                tab === t ? "bg-[var(--bg-elevated)] text-[var(--text-primary)] shadow-[var(--shadow)]" : "text-[var(--text-secondary)] hover:text-[var(--text-primary)]",
              )}
            >
              {t === "promos" ? <Gift className="size-3.5" /> : <BadgePercent className="size-3.5" />}
              {t === "promos" ? "Промокоды" : "Скидки"}
              {tab === t && <span className="rounded-full bg-[var(--bg-overlay)] px-1.5 py-0.5 text-[10px] text-[var(--text-muted)]">{rows.length}</span>}
            </button>
          ))}
        </div>
        <span className="text-[11.5px] text-[var(--text-muted)]">{tab === "promos" ? "Код: скидка на обмен или на баланс" : "Персональная скидка клиенту"}</span>
      </div>

      <Card className="overflow-hidden p-0">
        <div className="flex flex-wrap items-center justify-between gap-3 border-b border-[var(--border)] p-5 sm:p-6">
          <div className="flex items-center gap-3">
            <span className="flex size-9 items-center justify-center rounded-[var(--radius)] bg-[var(--blue-bg)] text-[var(--blue)]">
              {tab === "promos" ? <Gift className="size-4" /> : <BadgePercent className="size-4" />}
            </span>
            <div>
              <div className="text-[13.5px] font-semibold">{tab === "promos" ? "Промокоды" : "Скидки"}</div>
              <div className="mt-0.5 text-[11.5px] text-[var(--text-muted)]">{loading ? "Обновляем данные…" : `${rows.length} ${pluralize(rows.length, "запись", "записи", "записей")}`}</div>
            </div>
          </div>
          <Badge tone={activeCount ? "green" : "default"}>{activeCount ? `${activeCount} активно` : "Нет активных"}</Badge>
        </div>
        <Table columns={cols} rows={rows} empty={loading ? "Загрузка…" : "Здесь пока ничего нет"} />
      </Card>

      {createOpen && <CreatePromoModal kind={tab} onClose={() => setCreateOpen(false)} onDone={() => { setCreateOpen(false); load(); }} />}
    </>
  );
}

function DeleteButton({ id, label, onDelete }: { id: number; label: string; onDelete: (id: number) => void }) {
  return (
    <Button size="sm" variant="danger" aria-label={`Удалить ${label}`} title="Удалить" onClick={(e) => { e.stopPropagation(); onDelete(id); }}>
      <Trash2 className="size-3.5" />
    </Button>
  );
}

function pluralize(value: number, one: string, few: string, many: string) {
  const mod10 = value % 10;
  const mod100 = value % 100;
  if (mod10 === 1 && mod100 !== 11) return one;
  if (mod10 >= 2 && mod10 <= 4 && (mod100 < 10 || mod100 >= 20)) return few;
  return many;
}

function CreatePromoModal({ kind, onClose, onDone }: { kind: "promos" | "discounts"; onClose: () => void; onDone: () => void }) {
  const [giftKind, setGiftKind] = useState<PromoGiftKind>("fixed_rub");
  const [bonus, setBonus] = useState("");
  const [minOrder, setMinOrder] = useState("");
  const [maxAct, setMaxAct] = useState("5");
  const [name, setName] = useState("");
  const [recipient, setRecipient] = useState("");
  const [busy, setBusy] = useState(false);
  const isCode = kind === "promos";
  const isDiscountCode = isCode && giftKind === "exchange_discount";
  const showMinOrder = !isCode || isDiscountCode;

  async function submit() {
    if (Number(bonus) <= 0) return toast.error("Укажите бонус");
    if (kind === "discounts" && !recipient.trim()) return toast.error("Укажите Telegram клиента");
    setBusy(true);
    try {
      if (isCode) {
        const body = {
          client_fixed_bonus_rub: Number(bonus),
          max_activations: Number(maxAct || 1),
          name: name.trim() || undefined,
          ...(isDiscountCode ? { min_order_rub: Number(minOrder || 0) } : {}),
        };
        await op(isDiscountCode ? "/promos/exchange-discount" : "/promos", { method: "POST", body });
      } else {
        await op("/discounts/grant", { method: "POST", body: { amount_rub: Number(bonus), min_order_rub: Number(minOrder || 0), recipients: [recipient.trim()], name: name.trim() || undefined } });
      }
      toast.success(isCode ? (isDiscountCode ? "Создан промокод на скидку" : "Создан промокод на баланс") : "Создано");
      onDone();
    } catch (e) {
      toast.error(e instanceof PanelApiError ? e.message : "Ошибка");
    } finally {
      setBusy(false);
    }
  }

  return (
    <Modal
      open
      title={kind === "promos" ? "Новый промокод" : "Новая скидка"}
      onClose={onClose}
      footer={
        <>
          <Button variant="ghost" onClick={onClose}>Отмена</Button>
          <Button variant="primary" disabled={busy} onClick={submit}><Plus className="size-3.5" /> Создать</Button>
        </>
      }
    >
      <div className="mb-5 flex items-start gap-3 rounded-[var(--radius)] border border-[var(--blue)]/25 bg-[var(--blue-bg)] p-3.5">
        <span className="flex size-8 shrink-0 items-center justify-center rounded-[var(--radius-sm)] bg-[var(--blue)]/15 text-[var(--blue)]">
          {kind === "promos" ? <Gift className="size-4" /> : <BadgePercent className="size-4" />}
        </span>
        <div>
          <div className="text-[12.5px] font-semibold">{kind === "promos" ? (isDiscountCode ? "Скидка на обмен по коду" : "Бонус на баланс по коду") : "Персональная скидка"}</div>
          <div className="mt-0.5 text-[11.5px] text-[var(--text-secondary)]">
            {kind === "promos"
              ? (isDiscountCode ? "Клиент активирует код и получает купон на покупку. На баланс не зачисляется." : "Клиент активирует код — сумма сразу на баланс.")
              : "Заполните сумму и условия, чтобы выдать предложение клиентам."}
          </div>
        </div>
      </div>
      {isCode && (
        <div className="mb-3 flex flex-col gap-1.5">
          <span className="text-[11px] font-semibold uppercase tracking-wide text-[var(--text-muted)]">Тип</span>
          <div className="flex w-fit gap-1 rounded-[var(--radius)] border border-[var(--border)] bg-[var(--bg-elevated)] p-1" role="radiogroup" aria-label="Тип промокода">
            {([
              { key: "fixed_rub", label: "На баланс" },
              { key: "exchange_discount", label: "Скидка на обмен" },
            ] as const).map((opt) => (
              <button
                key={opt.key}
                type="button"
                role="radio"
                aria-checked={giftKind === opt.key}
                onClick={() => setGiftKind(opt.key)}
                className={cx(
                  "rounded-[var(--radius-sm)] px-3 py-1.5 text-[13px] font-medium transition-colors",
                  giftKind === opt.key ? "bg-[var(--bg-surface)] text-[var(--text-primary)] shadow-[var(--shadow)]" : "text-[var(--text-secondary)] hover:text-[var(--text-primary)]",
                )}
              >
                {opt.label}
              </button>
            ))}
          </div>
          <span className="text-[11px] leading-snug text-[var(--text-muted)]">
            {isDiscountCode ? "Купон действует на покупке от указанной суммы." : "Без минимума заказа — сразу на баланс."}
          </span>
        </div>
      )}
      <div className="grid gap-3 sm:grid-cols-2">
        <Field label="Бонус клиенту, ₽">
          <Input autoFocus inputMode="decimal" value={bonus} onChange={(e) => setBonus(e.target.value)} className="font-mono" placeholder="500" />
        </Field>
        {kind === "discounts" && (
          <Field label="Telegram клиента">
            <Input value={recipient} onChange={(e) => setRecipient(e.target.value)} placeholder="ID или @username" />
          </Field>
        )}
        {showMinOrder && (
          <Field label="Мин. сумма заказа, ₽">
            <Input inputMode="decimal" value={minOrder} onChange={(e) => setMinOrder(e.target.value)} className="font-mono" placeholder="Без минимума" />
          </Field>
        )}
        {kind === "promos" && (
          <Field label="Макс. активаций">
            <Input inputMode="numeric" value={maxAct} onChange={(e) => setMaxAct(e.target.value)} className="font-mono" />
          </Field>
        )}
        <Field label="Название (необязательно)">
          <Input value={name} onChange={(e) => setName(e.target.value)} placeholder="Например, Стартовый бонус" />
        </Field>
      </div>
    </Modal>
  );
}
