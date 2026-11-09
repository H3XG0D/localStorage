import { useCallback, useState } from "react";
import { useNavigate } from "react-router-dom";
import { toast } from "sonner";
import { PanelApiError } from "@/panel/lib/panelApi";
import { useAuthedPoll } from "@/panel/lib/useAuthedPoll";
import { getQueue, type QueueSummary } from "@/panel/lib/operatorApi";
import { Badge, Card, PageHeader, Table, type Column } from "@/panel/ui/primitives";
import { orderStatusTone, statusLabel } from "@/panel/lib/orderStatus";
import type { OrderRow } from "@/panel/lib/operatorApi";

function fmtMoney(v: unknown) {
  return new Intl.NumberFormat("ru-RU", { maximumFractionDigits: 0 }).format(Number(v ?? 0));
}

export function OperatorQueue() {
  const [data, setData] = useState<QueueSummary | null>(null);
  const [loading, setLoading] = useState(true);
  const navigate = useNavigate();

  const load = useCallback(() => {
    getQueue()
      .then(setData)
      .catch((e) => toast.error(e instanceof PanelApiError ? e.message : "Ошибка"))
      .finally(() => setLoading(false));
  }, []);

  useAuthedPoll("operator", load, 8000, [load]);

  const cols: Column<OrderRow>[] = [
    { key: "order_id", label: "#", width: "120px", render: (r) => <span className="font-mono">{r.order_id}</span> },
    { key: "buyer", label: "Клиент", render: (r) => r.buyer_first_name || r.buyer_username || `ID ${r.user_id ?? "—"}` },
    { key: "direction", label: "Тип", width: "80px", render: (r) => (r.direction === "buy" ? "Покупка" : "Продажа") },
    { key: "crypto", label: "Актив", width: "90px", render: (r) => <span className="font-mono">{String(r.crypto).toUpperCase()}</span> },
    { key: "fiat_amount", label: "Сумма ₽", width: "110px", align: "right", render: (r) => <span className="font-mono">{fmtMoney(r.fiat_amount)}</span> },
    { key: "status", label: "Статус", width: "130px", render: (r) => <Badge tone={orderStatusTone(r.status)}>{r.status_label || statusLabel(r.status)}</Badge> },
    { key: "operator_name", label: "Оператор", width: "120px", render: (r) => r.operator_name || "—" },
  ];

  return (
    <>
      <PageHeader title="Очередь" subtitle="Входящие заявки и работа в процессе" />

      <div className="grid grid-cols-5 gap-3 max-lg:grid-cols-2 max-[520px]:grid-cols-1">
        <QueueChip label="В очереди" value={data?.queue_count} />
        <QueueChip label="Готовы к приёму" value={data?.ready_to_accept_count} />
        <QueueChip label="Ждут чек" value={data?.awaiting_receipt_count} />
        <QueueChip label="Держат клиента" value={data?.client_hold_count} />
        <QueueChip label="Выводы" value={data?.withdrawal_incoming_count} />
      </div>

      <Card>
        <div className="mb-3 text-[13.5px] font-semibold">В работе · {data?.in_progress_count ?? 0}</div>
        <Table
          columns={cols}
          rows={data?.in_progress_orders ?? []}
          empty={loading ? "Загрузка…" : "Нет заявок в работе"}
          onRowClick={(r) => navigate(`/ops/orders?order=${encodeURIComponent(r.order_id)}`)}
        />
      </Card>
    </>
  );
}

function QueueChip({ label, value }: { label: string; value: number | undefined }) {
  return (
    <div className="rounded-[var(--radius-lg)] border border-[var(--border)] bg-[var(--bg-surface)] p-4">
      <div className="text-[12px] text-[var(--text-muted)]">{label}</div>
      <div className="mt-1 font-mono text-2xl font-extrabold tabular-nums">{value ?? "—"}</div>
    </div>
  );
}
