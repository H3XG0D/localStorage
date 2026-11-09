import { AlertTriangle } from "lucide-react";
import { Card } from "@/panel/ui/primitives";
import type { AnalyticsBundle, SliceKey } from "@/panel/lib/useAnalyticsData";

const SLICE_LABEL: Record<SliceKey, string> = {
  owner: "Метрики владельца",
  live: "Живой кошелёк и операторы",
  liab: "Обязательства",
  stats: "Статистика заявок",
  finance: "Финансовый отчёт",
  promo: "Промо-кампании",
  cohorts: "Когорты и retention",
  prevCohorts: "Когорты предыдущего окна",
  misses: "Пропуски",
  traffic: "Трафик заявок",
  partners: "Партнёры",
  external: "Внештат",
  orders: "Заявки",
  prevOrders: "Заявки предыдущего окна",
  casino: "Казино",
};

const FINANCE_FORBIDDEN = "Нет права finance.analytics — денежные показатели скрыты, а не равны нулю.";

function issueMessage(slice: SliceKey, err: { message: string; status: number }) {
  const isFinanceSlice = slice === "finance" || slice === "owner";
  const isPermissionDenial =
    err.status === 403 && /finance\.analytics|недостаточно прав/i.test(err.message);
  return isFinanceSlice && isPermissionDenial ? FINANCE_FORBIDDEN : err.message;
}

/**
 * Failed slices must be visible: without this banner a 403 renders as a page
 * full of zeros that looks like real data.
 */
export function DataIssues({ data, slices }: { data: AnalyticsBundle; slices: SliceKey[] }) {
  const rows = slices
    .map((slice) => ({ slice, err: data.errors[slice] }))
    .filter((row): row is { slice: SliceKey; err: { message: string; status: number } } => Boolean(row.err));
  if (!rows.length) return null;
  return (
    <Card className="border-[var(--red)]/30">
      <div className="mb-2 flex items-center gap-2">
        <AlertTriangle className="size-4 text-[var(--red)]" />
        <span className="text-[13px] font-semibold text-[var(--red)]">Часть данных не загрузилась — это не нули</span>
      </div>
      <div className="flex flex-col gap-1 text-[12px] text-[var(--text-secondary)]">
        {rows.map(({ slice, err }) => (
          <div key={slice}>
            <span className="font-medium text-[var(--text-primary)]">{SLICE_LABEL[slice]}</span>:{" "}
            {issueMessage(slice, err)}
          </div>
        ))}
      </div>
    </Card>
  );
}
