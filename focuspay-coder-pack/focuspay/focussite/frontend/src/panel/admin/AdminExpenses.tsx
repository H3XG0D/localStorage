import { useCallback, useEffect, useState } from "react";
import { toast } from "sonner";
import { PanelApiError } from "@/panel/lib/panelApi";
import { getExpenses, createExpense, patchExpense, deleteExpense, type Dict } from "@/panel/lib/adminApi";
import { Badge, Button, Card, Field, Input, Modal, PageHeader, Select, Table, cx, type BadgeTone, type Column } from "@/panel/ui/primitives";

function money(v: unknown) {
  return new Intl.NumberFormat("ru-RU", { maximumFractionDigits: 0 }).format(Number(v ?? 0));
}

const TABS = [
  { key: "all", label: "Все" },
  { key: "mandatory", label: "Обязательные" },
  { key: "work", label: "Рабочие" },
  { key: "unexpected", label: "Непредвиденные" },
] as const;

const CATEGORIES = [
  { key: "mandatory", label: "Обязательные" },
  { key: "work", label: "Рабочие" },
  { key: "unexpected", label: "Непредвиденные" },
] as const;

type Tab = (typeof TABS)[number]["key"];

function catTone(c: unknown): BadgeTone {
  return c === "mandatory" ? "red" : c === "work" ? "blue" : c === "unexpected" ? "orange" : "default";
}
function catLabel(c: unknown): string {
  const found = CATEGORIES.find((x) => x.key === c);
  return found ? found.label : String(c ?? "—");
}

export function AdminExpenses() {
  const [tab, setTab] = useState<Tab>("all");
  const [rows, setRows] = useState<Dict[]>([]);
  const [loading, setLoading] = useState(true);
  const [createOpen, setCreateOpen] = useState(false);
  const [edit, setEdit] = useState<Dict | null>(null);

  const load = useCallback(() => {
    setLoading(true);
    getExpenses(tab === "all" ? undefined : tab, 200)
      .then((r) => setRows(Array.isArray(r) ? r : ((r.expenses ?? []) as Dict[])))
      .catch((e) => toast.error(e instanceof PanelApiError ? e.message : "Ошибка"))
      .finally(() => setLoading(false));
  }, [tab]);

  useEffect(() => load(), [load]);

  async function del(id: unknown) {
    if (id == null) return;
    try {
      await deleteExpense(Number(id));
      toast.success("Удалено");
      load();
    } catch (e) {
      toast.error(e instanceof PanelApiError ? e.message : "Ошибка");
    }
  }

  const cols: Column<Dict>[] = [
    { key: "expense_date", label: "Дата", width: "120px", render: (r) => String(r.expense_date ?? "—") },
    { key: "category", label: "Категория", width: "150px", render: (r) => <Badge tone={catTone(r.category)}>{catLabel(r.category)}</Badge> },
    { key: "title", label: "Название", render: (r) => String(r.title ?? "—") },
    { key: "amount_rub", label: "Сумма ₽", width: "120px", align: "right", render: (r) => <span className="font-mono tabular-nums">{money(r.amount_rub)} ₽</span> },
    { key: "comment", label: "Комментарий", render: (r) => String(r.comment ?? "—") },
    {
      key: "actions",
      label: "",
      width: "170px",
      render: (r) => (
        <div className="flex gap-1.5">
          <Button size="sm" variant="secondary" onClick={(e) => { e.stopPropagation(); setEdit(r); }}>
            Изменить
          </Button>
          <Button size="sm" variant="danger" onClick={(e) => { e.stopPropagation(); del(r.id ?? r.expense_id); }}>
            Удалить
          </Button>
        </div>
      ),
    },
  ];

  return (
    <>
      <PageHeader
        title="Расходы"
        subtitle="Ручной учёт расходов"
        actions={
          <Button variant="primary" onClick={() => setCreateOpen(true)}>
            + Добавить расход
          </Button>
        }
      />

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

      <Card>
        <Table columns={cols} rows={rows} empty={loading ? "Загрузка…" : "Нет расходов"} onRowClick={(r) => setEdit(r)} />
      </Card>

      {createOpen && <ExpenseFormModal onClose={() => setCreateOpen(false)} onDone={() => { setCreateOpen(false); load(); }} />}
      {edit && <ExpenseFormModal initial={edit} onClose={() => setEdit(null)} onDone={() => { setEdit(null); load(); }} />}
    </>
  );
}

function ExpenseFormModal({ initial, onClose, onDone }: { initial?: Dict; onClose: () => void; onDone: () => void }) {
  const editing = initial != null;
  const [category, setCategory] = useState<string>(String(initial?.category ?? "mandatory"));
  const [amount, setAmount] = useState(initial?.amount_rub == null ? "" : String(initial.amount_rub));
  const [title, setTitle] = useState(String(initial?.title ?? initial?.operation_type ?? ""));
  const [comment, setComment] = useState(String(initial?.comment ?? ""));
  const [date, setDate] = useState(() => String(initial?.expense_date ?? new Date().toISOString().slice(0, 10)).slice(0, 10));
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
        await patchExpense(Number(initial.id ?? initial.expense_id), {
          amount_rub: Number(amount),
          title: title.trim(),
          comment: comment.trim() || "",
          expense_date: date || undefined,
        });
        toast.success("Расход обновлён");
      } else {
        await createExpense({
          category,
          amount_rub: Number(amount),
          title: title.trim(),
          comment: comment.trim() || undefined,
          expense_date: date || undefined,
        });
        toast.success("Расход добавлен");
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
      title={editing ? "Изменить расход" : "Новый расход"}
      onClose={onClose}
      footer={
        <>
          <Button variant="ghost" onClick={onClose}>Отмена</Button>
          <Button variant="primary" disabled={busy} onClick={submit}>{editing ? "Сохранить" : "Добавить"}</Button>
        </>
      }
    >
      <div className="flex flex-col gap-3">
        <Field label="Категория">
          <Select value={category} disabled={editing} onChange={(e) => setCategory(e.target.value)}>
            {CATEGORIES.map((c) => (
              <option key={c.key} value={c.key}>{c.label}</option>
            ))}
          </Select>
        </Field>
        <Field label="Сумма, ₽">
          <Input inputMode="decimal" value={amount} onChange={(e) => setAmount(e.target.value)} className="font-mono" />
        </Field>
        <Field label="Название">
          <Input value={title} onChange={(e) => setTitle(e.target.value)} />
        </Field>
        <Field label="Комментарий">
          <Input value={comment} onChange={(e) => setComment(e.target.value)} />
        </Field>
        <Field label="Дата">
          <Input type="date" value={date} onChange={(e) => setDate(e.target.value)} className="font-mono" />
        </Field>
      </div>
    </Modal>
  );
}
