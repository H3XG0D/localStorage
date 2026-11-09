import { useEffect, useState } from "react";
import { toast } from "sonner";
import { PanelApiError } from "@/panel/lib/panelApi";
import { getShifts, type ShiftRow } from "@/panel/lib/operatorApi";
import { Badge, Card, PageHeader, Table, type Column } from "@/panel/ui/primitives";

function dt(v: unknown) {
  return v ? new Date(String(v)).toLocaleString("ru-RU", { day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" }) : "—";
}

function money(v: unknown) {
  return v == null ? "—" : new Intl.NumberFormat("ru-RU", { maximumFractionDigits: 0 }).format(Number(v));
}

export function OperatorShifts() {
  const [rows, setRows] = useState<ShiftRow[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    getShifts()
      .then((r) => setRows(r.shifts || []))
      .catch((e) => toast.error(e instanceof PanelApiError ? e.message : "Ошибка"))
      .finally(() => setLoading(false));
  }, []);

  const cols: Column<ShiftRow>[] = [
    { key: "started_at", label: "Начало", render: (r) => <span className="font-mono">{dt(r.started_at)}</span> },
    { key: "ended_at", label: "Конец", render: (r) => (r.ended_at ? <span className="font-mono">{dt(r.ended_at)}</span> : <Badge tone="green">Активна</Badge>) },
    { key: "orders_count", label: "Заявок", align: "right", render: (r) => String(r.orders_count ?? "—") },
    { key: "fiat_total", label: "Оборот ₽", align: "right", render: (r) => <span className="font-mono">{money(r.fiat_total)}</span> },
    { key: "earnings_rub", label: "Заработано ₽", align: "right", render: (r) => <span className="font-mono font-semibold text-[var(--green)]">{money(r.earnings_rub)}</span> },
    { key: "note", label: "Заметка", render: (r) => r.note || "—" },
  ];

  return (
    <>
      <PageHeader title="Смены" subtitle="История ваших смен" />
      <Card>
        <Table columns={cols} rows={rows} empty={loading ? "Загрузка…" : "Смен пока нет"} />
      </Card>
    </>
  );
}
