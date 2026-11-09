import { useCallback, useEffect, useState } from "react";
import { AlertCircle, Calendar, TrendingUp } from "lucide-react";
import { toast } from "sonner";
import { PanelApiError } from "@/panel/lib/panelApi";
import {
  getRecurringExpenses,
  getUpcomingExpenses,
  getRoiAnalysis,
  createRecurringExpense,
  patchRecurringExpense,
  deleteRecurringExpense,
  billRecurringExpense,
  getExpenses,
  type Dict,
} from "@/panel/lib/adminApi";
import {
  Badge,
  Button,
  Card,
  Field,
  Input,
  Modal,
  PageHeader,
  Select,
  Table,
  Kpi,
  cx,
  type BadgeTone,
  type Column,
} from "@/panel/ui/primitives";

function money(v: unknown) {
  return new Intl.NumberFormat("ru-RU", { maximumFractionDigits: 0 }).format(Number(v ?? 0));
}

function daysDiff(from: string, to: string): number {
  const d1 = new Date(from);
  const d2 = new Date(to);
  return Math.ceil((d2.getTime() - d1.getTime()) / (1000 * 60 * 60 * 24));
}

const TABS = [
  { key: "subscriptions", label: "Подписки" },
  { key: "manual", label: "Разовые расходы" },
  { key: "roi", label: "ROI-анализ" },
] as const;

const CATEGORIES = [
  { key: "subscription", label: "Подписки на сервисы" },
  { key: "salary", label: "Зарплаты" },
  { key: "marketing", label: "Маркетинг" },
  { key: "other", label: "Прочее" },
] as const;

const BILLING_CYCLES = [
  { key: "weekly", label: "Еженедельно" },
  { key: "biweekly", label: "Раз в 2 недели" },
  { key: "monthly", label: "Ежемесячно" },
  { key: "quarterly", label: "Ежеквартально" },
  { key: "annual", label: "Ежегодно" },
] as const;

type Tab = (typeof TABS)[number]["key"];

function catTone(c: unknown): BadgeTone {
  return c === "subscription" ? "blue" : c === "salary" ? "purple" : c === "marketing" ? "orange" : "yellow";
}
function catLabel(c: unknown): string {
  const found = CATEGORIES.find((x) => x.key === c);
  return found ? found.label : String(c ?? "—");
}
function cycleLabel(c: unknown): string {
  const found = BILLING_CYCLES.find((x) => x.key === c);
  return found ? found.label : String(c ?? "—");
}

export function AdminRecurringExpenses() {
  const [tab, setTab] = useState<Tab>("subscriptions");
  const [rows, setRows] = useState<Dict[]>([]);
  const [manualRows, setManualRows] = useState<Dict[]>([]);
  const [roiData, setRoiData] = useState<Dict[]>([]);
  const [upcoming, setUpcoming] = useState<Dict[]>([]);
  const [loading, setLoading] = useState(true);
  const [createOpen, setCreateOpen] = useState(false);
  const [edit, setEdit] = useState<Dict | null>(null);

  const load = useCallback(() => {
    setLoading(true);
    Promise.all([
      getRecurringExpenses(undefined, true, 200),
      getUpcomingExpenses(7),
      getRoiAnalysis(30),
      getExpenses(undefined, 200),
    ])
      .then(([rec, upc, roi, man]) => {
        setRows(Array.isArray(rec) ? rec : ((rec.expenses ?? []) as Dict[]));
        setUpcoming(Array.isArray(upc) ? upc : ((upc.expenses ?? []) as Dict[]));
        setRoiData(Array.isArray(roi) ? roi : ((roi.expenses ?? []) as Dict[]));
        setManualRows(Array.isArray(man) ? man : ((man.expenses ?? []) as Dict[]));
      })
      .catch((e) => toast.error(e instanceof PanelApiError ? e.message : "Ошибка загрузки"))
      .finally(() => setLoading(false));
  }, []);

  useEffect(() => load(), [load]);

  async function del(id: unknown) {
    if (id == null) return;
    if (!window.confirm("Деактивировать эту подписку?")) return;
    try {
      await deleteRecurringExpense(Number(id));
      toast.success("Подписка деактивирована");
      load();
    } catch (e) {
      toast.error(e instanceof PanelApiError ? e.message : "Ошибка");
    }
  }

  async function billNow(id: unknown) {
    if (id == null) return;
    if (!window.confirm("Создать платёж по этой подписке сейчас?")) return;
    try {
      await billRecurringExpense(Number(id));
      toast.success("Платёж создан");
      load();
    } catch (e) {
      toast.error(e instanceof PanelApiError ? e.message : "Ошибка");
    }
  }

  // KPI расчёты
  const monthlyTotal = rows.reduce((sum, r) => {
    const amount = Number(r.amount_rub ?? 0);
    const cycle = String(r.billing_cycle);
    if (cycle === "monthly") return sum + amount;
    if (cycle === "quarterly") return sum + amount / 3;
    if (cycle === "annual") return sum + amount / 12;
    if (cycle === "weekly") return sum + amount * 4.33;
    if (cycle === "biweekly") return sum + amount * 2.16;
    return sum;
  }, 0);

  const upcoming7d = upcoming.reduce((sum, r) => sum + Number(r.amount_rub ?? 0), 0);
  const count7d = upcoming.length;

  const avgROI = roiData.length > 0 
    ? roiData.reduce((sum, r) => sum + Number(r.roi_percent ?? 0), 0) / roiData.length 
    : 0;

  const profitableCount = roiData.filter((r) => Number(r.roi_percent ?? 0) > 20).length;
  const unprofitableCount = roiData.filter((r) => {
    const roi = r.roi_percent;
    return roi != null && Number(roi) < 20;
  }).length;

  const lifetimeTotal = rows.reduce((sum, r) => sum + Number(r.amount_rub ?? 0), 0);

  const cols: Column<Dict>[] = [
    { key: "title", label: "Название", render: (r) => String(r.title ?? "—") },
    { 
      key: "category", 
      label: "Категория", 
      width: "150px", 
      render: (r) => <Badge tone={catTone(r.category)}>{catLabel(r.category)}</Badge> 
    },
    { 
      key: "amount_rub", 
      label: "Сумма ₽", 
      width: "120px", 
      align: "right", 
      render: (r) => <span className="font-mono tabular-nums">{money(r.amount_rub)} ₽</span> 
    },
    { 
      key: "billing_cycle", 
      label: "Цикл", 
      width: "140px", 
      render: (r) => <Badge tone="default">{cycleLabel(r.billing_cycle)}</Badge> 
    },
    {
      key: "next_billing_date",
      label: "Следующая оплата",
      width: "160px",
      render: (r) => {
        const date = String(r.next_billing_date ?? "—");
        const today = new Date().toISOString().slice(0, 10);
        const days = daysDiff(today, date);
        const tone = days < 3 ? "red" : days < 7 ? "yellow" : "default";
        return (
          <Badge tone={tone}>
            {date} ({days} дн)
          </Badge>
        );
      },
    },
    {
      key: "roi_percent",
      label: "ROI %",
      width: "100px",
      align: "right",
      render: (r) => {
        if (r.roi_percent == null) return "—";
        const roi = Number(r.roi_percent);
        const tone = roi > 50 ? "green" : roi > 20 ? "yellow" : "red";
        return <Badge tone={tone}>{roi.toFixed(1)}%</Badge>;
      },
    },
    {
      key: "status",
      label: "Статус",
      width: "130px",
      render: (r) => {
        if (!r.is_active) return <Badge tone="default">Архив</Badge>;
        const roi = r.roi_percent != null ? Number(r.roi_percent) : null;
        if (roi !== null && roi > 50) return <Badge tone="green">Прибыльно</Badge>;
        if (roi !== null && roi > 20) return <Badge tone="yellow">Окупается</Badge>;
        if (roi !== null && roi < 20) return <Badge tone="red">Проверить</Badge>;
        return <Badge tone="blue">Отслеживается</Badge>;
      },
    },
    {
      key: "actions",
      label: "",
      width: "220px",
      render: (r) => (
        <div className="flex gap-1.5">
          <Button size="sm" variant="secondary" onClick={(e) => { e.stopPropagation(); setEdit(r); }}>
            Правка
          </Button>
          <Button size="sm" variant="ghost" onClick={(e) => { e.stopPropagation(); billNow(r.id); }}>
            Оплатить
          </Button>
          <Button size="sm" variant="danger" onClick={(e) => { e.stopPropagation(); del(r.id); }}>
            Архив
          </Button>
        </div>
      ),
    },
  ];

  const manualCols: Column<Dict>[] = [
    { key: "expense_date", label: "Дата", width: "120px", render: (r) => String(r.expense_date ?? "—") },
    { key: "category", label: "Категория", width: "150px", render: (r) => <Badge tone={catTone(r.category)}>{catLabel(r.category)}</Badge> },
    { key: "title", label: "Название", render: (r) => String(r.title ?? "—") },
    { key: "amount_rub", label: "Сумма ₽", width: "120px", align: "right", render: (r) => <span className="font-mono tabular-nums">{money(r.amount_rub)} ₽</span> },
    { key: "comment", label: "Комментарий", render: (r) => String(r.comment ?? "—") },
  ];

  return (
    <>
      <PageHeader
        title="Управление расходами"
        subtitle="Подписки, зарплаты, маркетинг и ROI-трекинг"
        actions={
          <Button variant="primary" onClick={() => setCreateOpen(true)}>
            + Добавить подписку
          </Button>
        }
      />

      {/* Верхние KPI */}
      <div className="grid grid-cols-6 gap-4 max-lg:grid-cols-3 max-md:grid-cols-2">
        <Kpi label="Ежемесячно" value={`${money(monthlyTotal)} ₽`} hint="активные подписки" />
        <Kpi label="Ближайшие 7 дней" value={`${money(upcoming7d)} ₽`} hint={`${count7d} платежей`} />
        <Kpi 
          label="ROI средний" 
          value={avgROI > 0 ? `${avgROI.toFixed(1)}%` : "—"} 
          trend={avgROI > 20 ? avgROI : undefined}
        />
        <Kpi label="Прибыльных" value={`${profitableCount}/${roiData.length}`} hint="ROI > 20%" />
        <Kpi label="Убыточных" value={String(unprofitableCount)} hint="требуют проверки" />
        <Kpi label="Всего расходов" value={`${money(lifetimeTotal)} ₽`} hint="сумма активных" />
      </div>

      {/* Предстоящие платежи (если есть) */}
      {upcoming.length > 0 && (
        <Card>
          <div className="flex items-start gap-3">
            <AlertCircle className="text-[var(--yellow)]" size={20} />
            <div className="flex-1">
              <div className="font-semibold">Предстоящие платежи (7 дней)</div>
              <div className="mt-2 flex flex-col gap-2">
                {upcoming.slice(0, 5).map((exp) => (
                  <div key={String(exp.id)} className="flex items-center justify-between text-[12px]">
                    <span>{String(exp.title)}</span>
                    <span className="font-mono text-[var(--text-muted)]">
                      {String(exp.next_billing_date)} — {money(exp.amount_rub)} ₽
                    </span>
                  </div>
                ))}
              </div>
            </div>
          </div>
        </Card>
      )}

      {/* Табы */}
      <div className="flex w-fit gap-1 rounded-[var(--radius)] border border-[var(--border)] bg-[var(--bg-surface)] p-1">
        {TABS.map((t) => (
          <button
            key={t.key}
            onClick={() => setTab(t.key)}
            className={cx(
              "rounded-[var(--radius-sm)] px-3 py-1.5 text-[13px] font-medium transition-colors",
              tab === t.key ? "bg-[var(--bg-elevated)] text-[var(--text-primary)]" : "text-[var(--text-secondary)] hover:text-[var(--text-primary)]",
            )}
          >
            {t.label}
          </button>
        ))}
      </div>

      {/* Контент */}
      {tab === "subscriptions" && (
        <Card>
          <Table columns={cols} rows={rows} empty={loading ? "Загрузка…" : "Нет подписок"} onRowClick={(r) => setEdit(r)} />
        </Card>
      )}

      {tab === "manual" && (
        <Card>
          <div className="mb-3 text-[13px] text-[var(--text-muted)]">
            Разовые расходы (ручные) из системы manual_expenses
          </div>
          <Table columns={manualCols} rows={manualRows} empty={loading ? "Загрузка…" : "Нет расходов"} />
        </Card>
      )}

      {tab === "roi" && (
        <Card>
          <div className="mb-4 flex items-center gap-2">
            <TrendingUp size={18} className="text-[var(--text-secondary)]" />
            <div>
              <div className="text-[14px] font-semibold">Рекомендации по продлению</div>
              <div className="text-[11px] text-[var(--text-muted)]">
                На основе ROI за последние 30 дней · порог окупаемости 20%
              </div>
            </div>
          </div>

          {roiData.length > 0 ? (
            <div className="flex flex-col gap-4">
              {roiData.map((item) => (
                <div key={String(item.id)} className="rounded-[var(--radius)] border border-[var(--border)] p-4">
                  <div className="flex items-start justify-between">
                    <div>
                      <div className="font-semibold">{String(item.title)}</div>
                      <div className="text-[12px] text-[var(--text-muted)]">{String(item.category_label)}</div>
                    </div>
                    <Badge tone={item.recommendation === "continue" ? "green" : "red"}>
                      {item.recommendation === "continue" ? "✓ Продлевать" : "⚠ Проверить"}
                    </Badge>
                  </div>

                  <div className="mt-3 grid grid-cols-4 gap-3 text-[12px] max-md:grid-cols-2">
                    <div>
                      <div className="text-[var(--text-muted)]">Расход</div>
                      <div className="font-mono">{money(item.amount_rub)} ₽</div>
                    </div>
                    <div>
                      <div className="text-[var(--text-muted)]">Возврат</div>
                      <div className="font-mono">{money(item.actual_return_rub)} ₽</div>
                    </div>
                    <div>
                      <div className="text-[var(--text-muted)]">ROI</div>
                      <div
                        className={cx(
                          "font-mono",
                          Number(item.roi_percent ?? 0) > 20 ? "text-[var(--green)]" : "text-[var(--red)]",
                        )}
                      >
                        {item.roi_percent != null ? `${Number(item.roi_percent).toFixed(1)}%` : "—"}
                      </div>
                    </div>
                    <div>
                      <div className="text-[var(--text-muted)]">След. платёж</div>
                      <div className="font-mono">{String(item.next_billing_date ?? "—")}</div>
                    </div>
                  </div>

                  {item.linked_partner_id != null && (
                    <div className="mt-2 text-[11px] text-[var(--text-muted)]">
                      Связано: партнёр #{String(item.linked_partner_id)}
                    </div>
                  )}

                  {item.recommendation === "review" && (
                    <div className="mt-2 rounded bg-[var(--red-bg)] p-2 text-[11px]">
                      ⚠ ROI ниже порога 20%. Рекомендуется пересмотреть целесообразность расхода.
                    </div>
                  )}
                </div>
              ))}
            </div>
          ) : (
            <div className="py-8 text-center text-[13px] text-[var(--text-muted)]">Нет данных для анализа</div>
          )}
        </Card>
      )}

      {createOpen && <ExpenseFormModal onClose={() => setCreateOpen(false)} onDone={() => { setCreateOpen(false); load(); }} />}
      {edit && <ExpenseFormModal initial={edit} onClose={() => setEdit(null)} onDone={() => { setEdit(null); load(); }} />}
    </>
  );
}

function ExpenseFormModal({ initial, onClose, onDone }: { initial?: Dict; onClose: () => void; onDone: () => void }) {
  const editing = initial != null;
  const [category, setCategory] = useState<string>(String(initial?.category ?? "subscription"));
  const [amount, setAmount] = useState(initial?.amount_rub == null ? "" : String(initial.amount_rub));
  const [title, setTitle] = useState(String(initial?.title ?? ""));
  const [billingCycle, setBillingCycle] = useState<string>(String(initial?.billing_cycle ?? "monthly"));
  const [nextBilling, setNextBilling] = useState(() => {
    if (initial?.next_billing_date) return String(initial.next_billing_date).slice(0, 10);
    const future = new Date();
    future.setDate(future.getDate() + 30);
    return future.toISOString().slice(0, 10);
  });
  const [expectedReturn, setExpectedReturn] = useState(initial?.expected_return_rub == null ? "" : String(initial.expected_return_rub));
  const [comment, setComment] = useState(String(initial?.comment ?? ""));
  const [busy, setBusy] = useState(false);

  async function submit() {
    if (Number(amount) <= 0) {
      toast.error("Укажите сумму");
      return;
    }
    if (title.trim().length === 0) {
      toast.error("Укажите название");
      return;
    }
    setBusy(true);
    try {
      if (editing) {
        await patchRecurringExpense(Number(initial.id), {
          amount_rub: Number(amount),
          title: title.trim(),
          billing_cycle: billingCycle,
          next_billing_date: nextBilling || undefined,
          expected_return_rub: expectedReturn ? Number(expectedReturn) : undefined,
          comment: comment.trim() || undefined,
        });
        toast.success("Подписка обновлена");
      } else {
        await createRecurringExpense({
          category,
          amount_rub: Number(amount),
          title: title.trim(),
          billing_cycle: billingCycle,
          next_billing_date: nextBilling || undefined,
          expected_return_rub: expectedReturn ? Number(expectedReturn) : undefined,
          comment: comment.trim() || undefined,
        });
        toast.success("Подписка создана");
      }
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
      title={editing ? "Изменить подписку" : "Новая подписка"}
      onClose={onClose}
      footer={
        <>
          <Button variant="ghost" onClick={onClose}>
            Отмена
          </Button>
          <Button variant="primary" disabled={busy} onClick={submit}>
            {editing ? "Сохранить" : "Создать"}
          </Button>
        </>
      }
    >
      <div className="flex flex-col gap-3">
        <Field label="Название">
          <Input value={title} onChange={(e) => setTitle(e.target.value)} />
        </Field>

        <Field label="Категория">
          <Select value={category} disabled={editing} onChange={(e) => setCategory(e.target.value)}>
            {CATEGORIES.map((c) => (
              <option key={c.key} value={c.key}>
                {c.label}
              </option>
            ))}
          </Select>
        </Field>

        <Field label="Сумма, ₽">
          <Input inputMode="decimal" value={amount} onChange={(e) => setAmount(e.target.value)} className="font-mono" />
        </Field>

        <Field label="Цикл оплаты">
          <Select value={billingCycle} onChange={(e) => setBillingCycle(e.target.value)}>
            {BILLING_CYCLES.map((c) => (
              <option key={c.key} value={c.key}>
                {c.label}
              </option>
            ))}
          </Select>
        </Field>

        <Field label="Следующая оплата">
          <Input type="date" value={nextBilling} onChange={(e) => setNextBilling(e.target.value)} className="font-mono" />
        </Field>

        <Field label="Ожидаемый возврат, ₽ (для ROI)">
          <Input
            inputMode="decimal"
            value={expectedReturn}
            onChange={(e) => setExpectedReturn(e.target.value)}
            className="font-mono"
          />
          <div className="text-[11px] text-[var(--text-muted)]">Оставьте пустым для ручного отслеживания</div>
        </Field>

        <Field label="Комментарий">
          <Input value={comment} onChange={(e) => setComment(e.target.value)} />
        </Field>
      </div>
    </Modal>
  );
}
