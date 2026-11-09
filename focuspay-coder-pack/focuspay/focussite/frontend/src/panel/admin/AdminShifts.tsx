import { useCallback, useEffect, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { toast } from "sonner";
import { PanelApiError } from "@/panel/lib/panelApi";
import { closeOperatorShift, getOperatorShifts, type Dict } from "@/panel/lib/adminApi";
import { Badge, Button, Card, Field, Input, Kpi, PageHeader, Select, cx } from "@/panel/ui/primitives";

function money(v: unknown) {
  return new Intl.NumberFormat("ru-RU", { maximumFractionDigits: 2 }).format(Number(v ?? 0));
}
function dt(v: unknown) {
  if (!v) return "—";
  const d = new Date(String(v));
  return Number.isNaN(d.getTime()) ? String(v) : d.toLocaleString("ru-RU");
}
function moneyOrDash(v: unknown) {
  return v == null ? "—" : money(v);
}
function asOrders(row: Dict): Dict[] {
  return Array.isArray(row.orders) ? (row.orders as Dict[]) : [];
}
function buyerLabel(o: Dict) {
  const un = o.buyer_username ? (String(o.buyer_username).startsWith("@") ? String(o.buyer_username) : `@${o.buyer_username}`) : "";
  return un || String(o.buyer_first_name || o.user_id || "—");
}

export function AdminShifts() {
  const [params, setParams] = useSearchParams();
  const opFilter = params.get("operator_id") || "";
  const [rows, setRows] = useState<Dict[]>([]);
  const [loading, setLoading] = useState(true);
  const [busyId, setBusyId] = useState<number | null>(null);
  const [canViewFinance, setCanViewFinance] = useState(true);
  const [search, setSearch] = useState("");
  const [status, setStatus] = useState("all");
  const [page, setPage] = useState(1);
  const [openId, setOpenId] = useState<number | null>(null);

  const PAGE_SIZE = 20;

  const load = useCallback(() => {
    setLoading(true);
    const q: Dict = { limit: 200 };
    if (opFilter) q.operator_id = Number(opFilter);
    getOperatorShifts(q)
      .then((r) => {
        if (Array.isArray(r)) {
          setRows(r);
          return;
        }
        setRows(r.shifts || []);
        setCanViewFinance(r.can_view_finance !== false);
      })
      .catch((e) => toast.error(e instanceof PanelApiError ? e.message : "Ошибка"))
      .finally(() => setLoading(false));
  }, [opFilter]);

  useEffect(() => load(), [load]);

  const filteredRows = rows.filter((row) => {
    const haystack = `${row.operator_display_name ?? ""} ${row.operator_username ?? ""} ${row.operator_id ?? ""}`.toLowerCase();
    const matchesSearch = !search.trim() || haystack.includes(search.trim().toLowerCase());
    const matchesStatus = status === "all" || (status === "active" ? !row.ended_at : !!row.ended_at);
    return matchesSearch && matchesStatus;
  });
  const pages = Math.max(1, Math.ceil(filteredRows.length / PAGE_SIZE));
  const visibleRows = filteredRows.slice((page - 1) * PAGE_SIZE, page * PAGE_SIZE);

  async function close(operatorId: number) {
    setBusyId(operatorId);
    try {
      await closeOperatorShift(operatorId);
      toast.success("Смена закрыта");
      load();
    } catch (e) {
      toast.error(e instanceof PanelApiError ? e.message : "Ошибка");
    } finally {
      setBusyId(null);
    }
  }

  const totalOrders = rows.reduce((sum, r) => sum + Number(r.orders_count ?? 0), 0);
  const totalTurnover = rows.reduce((sum, r) => sum + Number(r.fiat_total ?? 0), 0);
  const totalProfit = rows.reduce((sum, r) => sum + Number(r.profit_rub ?? 0), 0);
  const colCount = 7 + (canViewFinance ? 1 : 0);

  return (
    <>
      <PageHeader title="Смены операторов" subtitle="История и активные смены. Клик по строке — заявки смены." />
      <div className={`grid gap-4 ${canViewFinance ? "grid-cols-3" : "grid-cols-2"} max-[640px]:grid-cols-1`}>
        <Kpi label="Заявок за период" value={String(totalOrders)} />
        <Kpi label="Оборот за период, ₽" value={money(totalTurnover)} />
        {canViewFinance && <Kpi label="Плюс по сделкам за период, ₽" value={money(totalProfit)} hint="После кешбэка и рефералок; общие расходы — в аналитике" />}
      </div>
      <Card>
        <div className="mb-4 grid grid-cols-2 gap-3 md:grid-cols-3">
          <Field label="Поиск оператора"><Input value={search} onChange={(e) => { setSearch(e.target.value); setPage(1); }} placeholder="Имя / логин / ID" /></Field>
          <Field label="Статус"><Select value={status} onChange={(e) => { setStatus(e.target.value); setPage(1); }}><option value="all">Все смены</option><option value="active">Активные</option><option value="closed">Закрытые</option></Select></Field>
          <div className="flex items-end gap-2 text-[12px] text-[var(--text-muted)]">
            <span>Показано {filteredRows.length} из загруженных {rows.length}</span>
            {opFilter && (
              <Button size="sm" variant="ghost" onClick={() => { params.delete("operator_id"); setParams(params, { replace: true }); setPage(1); }}>
                Сбросить фильтр #{opFilter}
              </Button>
            )}
          </div>
        </div>
        <div className="overflow-x-auto">
          <table className="w-full border-collapse text-[13px]">
            <thead>
              <tr className="border-b border-[var(--border)] text-left text-[var(--text-muted)]">
                <th className="px-3 py-2 font-medium">Оператор</th>
                <th className="px-3 py-2 font-medium">Начало</th>
                <th className="px-3 py-2 font-medium">Окончание</th>
                <th className="px-3 py-2 text-right font-medium">USDT выдано</th>
                <th className="px-3 py-2 text-right font-medium">Заявок</th>
                <th className="px-3 py-2 text-right font-medium">Оборот ₽</th>
                {canViewFinance && <th className="px-3 py-2 text-right font-medium">Плюс по сделкам ₽</th>}
                <th className="px-3 py-2 font-medium" />
              </tr>
            </thead>
            <tbody>
              {loading && visibleRows.length === 0 ? (
                <tr><td colSpan={colCount} className="px-3 py-8 text-center text-[var(--text-muted)]">Загрузка…</td></tr>
              ) : visibleRows.length === 0 ? (
                <tr><td colSpan={colCount} className="px-3 py-8 text-center text-[var(--text-muted)]">Пусто</td></tr>
              ) : visibleRows.map((r) => {
                const sid = Number(r.id);
                const open = openId === sid;
                const orders = asOrders(r);
                return (
                  <ShiftRow
                    key={sid}
                    row={r}
                    open={open}
                    orders={orders}
                    canViewFinance={canViewFinance}
                    colCount={colCount}
                    busy={busyId === Number(r.operator_id)}
                    onToggle={() => setOpenId(open ? null : sid)}
                    onCloseShift={() => close(Number(r.operator_id))}
                  />
                );
              })}
            </tbody>
          </table>
        </div>
        <div className="mt-4 flex items-center justify-between text-[12px] text-[var(--text-muted)]">
          <span>Стр. {page}/{pages}</span>
          <div className="flex items-center gap-2">
            <Button size="sm" variant="secondary" disabled={page <= 1} onClick={() => setPage((p) => Math.max(1, p - 1))}>Назад</Button>
            <Button size="sm" variant="secondary" disabled={page >= pages} onClick={() => setPage((p) => Math.min(pages, p + 1))}>Вперёд</Button>
          </div>
        </div>
      </Card>
    </>
  );
}

function ShiftRow({
  row,
  open,
  orders,
  canViewFinance,
  colCount,
  busy,
  onToggle,
  onCloseShift,
}: {
  row: Dict;
  open: boolean;
  orders: Dict[];
  canViewFinance: boolean;
  colCount: number;
  busy: boolean;
  onToggle: () => void;
  onCloseShift: () => void;
}) {
  return (
    <>
      <tr className="cursor-pointer border-b border-[var(--border)] hover:bg-[var(--bg-elevated)]" onClick={onToggle}>
        <td className="px-3 py-2.5">
          <Link
            to={`/x8/operators/${row.operator_id}`}
            className="text-[var(--accent)] hover:underline"
            onClick={(e) => e.stopPropagation()}
          >
            {String(row.operator_display_name || row.operator_username || `#${row.operator_id ?? ""}`)}
          </Link>
          {orders.length > 0 && <span className="ml-1 text-[var(--text-muted)]">{open ? "▾" : "▸"}</span>}
        </td>
        <td className="px-3 py-2.5">{dt(row.started_at)}</td>
        <td className="px-3 py-2.5">{row.ended_at ? dt(row.ended_at) : <Badge tone="green">Активна</Badge>}</td>
        <td className="px-3 py-2.5 text-right font-mono">{money(row.usdt_issued)}</td>
        <td className="px-3 py-2.5 text-right">{String(row.orders_count ?? "—")}</td>
        <td className="px-3 py-2.5 text-right font-mono">{moneyOrDash(row.fiat_total)}</td>
        {canViewFinance && (
          <td className="px-3 py-2.5 text-right font-mono" title="После кешбэка и рефералок, до общих расходов">{moneyOrDash(row.profit_rub)}</td>
        )}
        <td className="px-3 py-2.5">
          {row.ended_at ? null : (
            <Button size="sm" variant="danger" disabled={busy} onClick={(e) => { e.stopPropagation(); onCloseShift(); }}>
              Закрыть
            </Button>
          )}
        </td>
      </tr>
      {open && (
        <tr className="bg-[var(--bg-elevated)]">
          <td colSpan={colCount} className="px-3 py-3">
            {orders.length === 0 ? (
              <p className="text-[12px] text-[var(--text-muted)]">Выплат за смену нет</p>
            ) : (
              <table className="w-full text-[12px]">
                <thead>
                  <tr className="text-[var(--text-muted)]">
                    <th className="py-1 pr-3 text-left font-medium">Заявка</th>
                    <th className="py-1 pr-3 text-left font-medium">Клиент</th>
                    <th className="py-1 pr-3 text-left font-medium">Тип</th>
                    <th className="py-1 pr-3 text-right font-medium">₽</th>
                    <th className="py-1 text-left font-medium">Закрыта</th>
                  </tr>
                </thead>
                <tbody>
                  {orders.map((o) => (
                    <tr key={String(o.order_id)} className="border-t border-[var(--border)]">
                      <td className="py-1 pr-3 font-mono">
                        <Link to={`/x8/orders`} className={cx("hover:underline")} onClick={(e) => e.stopPropagation()}>{String(o.order_id)}</Link>
                      </td>
                      <td className="py-1 pr-3">{buyerLabel(o)}</td>
                      <td className="py-1 pr-3">{o.direction === "buy" ? "Покупка" : "Продажа"} {String(o.crypto ?? "").toUpperCase()}</td>
                      <td className="py-1 pr-3 text-right font-mono">{money(o.fiat_amount)}</td>
                      <td className="py-1">{dt(o.completed_at)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </td>
        </tr>
      )}
    </>
  );
}
