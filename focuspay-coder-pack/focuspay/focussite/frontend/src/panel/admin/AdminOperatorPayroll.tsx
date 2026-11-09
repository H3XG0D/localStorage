import { useCallback, useEffect, useState } from "react";
import { toast } from "sonner";
import { PanelApiError } from "@/panel/lib/panelApi";
import {
  getPayrollPoolBalance,
  getPayoutRequests,
  payoutRequestPaid,
  payoutRequestReject,
  type Dict,
} from "@/panel/lib/adminApi";
import { Badge, Button, Card, Field, Input, Kpi, Modal, PageHeader, Table, cx, type BadgeTone, type Column } from "@/panel/ui/primitives";

function money(v: unknown) {
  return new Intl.NumberFormat("ru-RU", { maximumFractionDigits: 0 }).format(Number(v ?? 0));
}

const TABS = [
  { key: "pending", label: "В обработке" },
  { key: "paid", label: "Выплачено" },
  { key: "rejected", label: "Отклонено" },
  { key: "canceled", label: "Отменено" },
] as const;

type Status = (typeof TABS)[number]["key"];

function statusTone(s: unknown): BadgeTone {
  return s === "paid" ? "green" : s === "pending" ? "yellow" : s === "rejected" ? "red" : "default";
}

export function AdminOperatorPayroll() {
  const [tab, setTab] = useState<Status>("pending");
  const [balance, setBalance] = useState<Dict | null>(null);
  const [rows, setRows] = useState<Dict[]>([]);
  const [loading, setLoading] = useState(true);
  const [action, setAction] = useState<{ row: Dict; kind: "paid" | "reject" } | null>(null);

  const load = useCallback(() => {
    setLoading(true);
    Promise.allSettled([getPayrollPoolBalance(), getPayoutRequests(tab, 50)]).then(([b, r]) => {
      if (b.status === "fulfilled") setBalance(b.value);
      if (r.status === "fulfilled") setRows((r.value.requests ?? []) as Dict[]);
      else toast.error(r.reason instanceof PanelApiError ? r.reason.message : "Ошибка");
      setLoading(false);
    });
  }, [tab]);

  useEffect(() => load(), [load]);

  const cols: Column<Dict>[] = [
    { key: "operator_name", label: "Оператор", render: (r) => String(r.operator_name ?? "—") },
    { key: "amount_rub", label: "Сумма ₽", width: "120px", align: "right", render: (r) => <span className="font-mono tabular-nums">{money(r.amount_rub)}</span> },
    { key: "requisites", label: "Реквизиты", render: (r) => String(r.requisites ?? "—") },
    { key: "status", label: "Статус", width: "130px", render: (r) => <Badge tone={statusTone(r.status)}>{String(r.status ?? "—")}</Badge> },
    { key: "created_at", label: "Создано", width: "160px", render: (r) => String(r.created_at ?? "—") },
    {
      key: "actions",
      label: "",
      width: "190px",
      render: (r) =>
        r.status === "pending" ? (
          <div className="flex gap-2">
            <Button size="sm" variant="primary" onClick={(e) => { e.stopPropagation(); setAction({ row: r, kind: "paid" }); }}>
              Выплатить
            </Button>
            <Button size="sm" variant="danger" onClick={(e) => { e.stopPropagation(); setAction({ row: r, kind: "reject" }); }}>
              Отклонить
            </Button>
          </div>
        ) : null,
    },
  ];

  return (
    <>
      <PageHeader title="Выплаты операторам" subtitle="Пул выплат и заявки операторов" />

      <div className="grid grid-cols-3 gap-4 max-[520px]:grid-cols-1">
        <Kpi label="Доступно в пуле, ₽" value={money(balance?.pool_balance ?? balance?.available_rub ?? balance?.balance_rub)} />
        <Kpi label="К выплате, ₽" value={money(balance?.pending_rub ?? balance?.pending_payouts_rub)} />
        <Kpi label="Выплачено, ₽" value={money(balance?.paid_rub ?? balance?.total_paid_rub)} />
      </div>

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
        <Table columns={cols} rows={rows} empty={loading ? "Загрузка…" : "Нет заявок"} />
      </Card>

      {action && (
        <PayoutActionModal
          row={action.row}
          kind={action.kind}
          onClose={() => setAction(null)}
          onDone={() => { setAction(null); load(); }}
        />
      )}
    </>
  );
}

function PayoutActionModal({ row, kind, onClose, onDone }: { row: Dict; kind: "paid" | "reject"; onClose: () => void; onDone: () => void }) {
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);

  async function submit() {
    setBusy(true);
    try {
      const id = Number(row.id ?? row.request_id);
      if (kind === "paid") await payoutRequestPaid(id, note.trim() || undefined);
      else await payoutRequestReject(id, note.trim() || undefined);
      toast.success(kind === "paid" ? "Выплачено" : "Отклонено");
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
      title={kind === "paid" ? "Подтвердить выплату" : "Отклонить заявку"}
      onClose={onClose}
      footer={
        <>
          <Button variant="ghost" onClick={onClose}>Отмена</Button>
          <Button variant={kind === "paid" ? "primary" : "danger"} disabled={busy} onClick={submit}>
            {kind === "paid" ? "Выплатить" : "Отклонить"}
          </Button>
        </>
      }
    >
      <div className="flex flex-col gap-3">
        <div className="text-[13px] text-[var(--text-secondary)]">
          {String(row.operator_name ?? "")} · <span className="font-mono">{money(row.amount_rub)} ₽</span>
        </div>
        <Field label="Заметка (необязательно)">
          <Input value={note} onChange={(e) => setNote(e.target.value)} />
        </Field>
      </div>
    </Modal>
  );
}
