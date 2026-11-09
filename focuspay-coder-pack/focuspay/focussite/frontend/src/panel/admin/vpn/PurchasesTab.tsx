import { useCallback, useEffect, useState } from "react";
import { getVpnPurchases, type Dict } from "@/panel/lib/adminApi";
import { Badge, Button, Card, Input, Select, Table, type Column } from "@/panel/ui/primitives";
import { moneyRub, num } from "@/panel/admin/analytics/format";
import { PURCHASE_STATUS, purchaseTitle, when } from "@/panel/admin/vpn/format";

const PAGE = 50;

export function PurchasesTab({ onOpenUser }: { onOpenUser: (telegramId: string) => void }) {
  const [status, setStatus] = useState("");
  const [kind, setKind] = useState("");
  const [tg, setTg] = useState("");
  const [offset, setOffset] = useState(0);
  const [data, setData] = useState<{ total: number; items: Dict[] } | null>(null);
  const [error, setError] = useState("");

  const load = useCallback(() => {
    setError("");
    getVpnPurchases({ status: status || undefined, kind: kind || undefined, telegram_id: tg || undefined, offset })
      .then(setData)
      .catch((e: Error) => setError(e.message));
  }, [status, kind, tg, offset]);
  useEffect(load, [load]);

  const columns: Column<Dict>[] = [
    { key: "created_at", label: "Создано", render: (r) => <span className="text-[var(--text-secondary)]">{when(r.created_at)}</span> },
    {
      key: "telegram_id",
      label: "Telegram",
      render: (r) => (
        <button type="button" className="font-mono text-[var(--blue)] hover:underline" onClick={() => onOpenUser(String(r.telegram_id))}>
          {String(r.telegram_id)}
        </button>
      ),
    },
    {
      key: "plan_code",
      label: "Тариф",
      render: (r) =>
        r.kind === "trial" ? <Badge tone="purple">триал</Badge> : <span>{purchaseTitle(r)}</span>,
    },
    { key: "days", label: "Дней", align: "right", render: (r) => num(r.days) },
    { key: "price_rub", label: "Сумма", align: "right", render: (r) => <span className="font-mono">{moneyRub(r.price_rub, true)}</span> },
    {
      key: "status",
      label: "Статус",
      render: (r) => {
        const s = PURCHASE_STATUS[String(r.status)] || { label: String(r.status), tone: "default" as const };
        return (
          <span title={r.error ? String(r.error) : undefined}>
            <Badge tone={s.tone}>{s.label}</Badge>
          </span>
        );
      },
    },
    { key: "cp_ends_at", label: "Доступ до", render: (r) => when(r.cp_ends_at) },
  ];

  return (
    <Card className="space-y-4">
      <div className="flex flex-wrap gap-2">
        <Select className="w-auto" value={status} onChange={(e) => { setOffset(0); setStatus(e.target.value); }}>
          <option value="">все статусы</option>
          {Object.entries(PURCHASE_STATUS).map(([k, v]) => (
            <option key={k} value={k}>{v.label}</option>
          ))}
        </Select>
        <Select className="w-auto" value={kind} onChange={(e) => { setOffset(0); setKind(e.target.value); }}>
          <option value="">все виды</option>
          <option value="paid">подписки</option>
          <option value="device">устройства</option>
          <option value="trial">триалы</option>
        </Select>
        <Input
          className="w-44"
          placeholder="Поиск по Telegram ID"
          inputMode="numeric"
          value={tg}
          onChange={(e) => { setOffset(0); setTg(e.target.value.replace(/\D/g, "")); }}
        />
      </div>
      {error ? <p className="text-[13px] text-[var(--red)]">{error}</p> : null}
      <Table columns={columns} rows={data?.items || []} empty={data ? "Ничего не найдено" : "Загрузка…"} />
      {data && data.total > PAGE ? (
        <div className="flex items-center gap-3 text-[12.5px] text-[var(--text-secondary)]">
          <Button size="sm" disabled={offset === 0} onClick={() => setOffset(Math.max(0, offset - PAGE))}>←</Button>
          <span>{offset + 1}–{Math.min(offset + PAGE, data.total)} из {data.total}</span>
          <Button size="sm" disabled={offset + PAGE >= data.total} onClick={() => setOffset(offset + PAGE)}>→</Button>
        </div>
      ) : null}
    </Card>
  );
}
