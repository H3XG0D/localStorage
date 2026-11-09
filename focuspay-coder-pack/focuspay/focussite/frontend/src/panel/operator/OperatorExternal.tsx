import { useCallback, useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { toast } from "sonner";
import { PanelApiError } from "@/panel/lib/panelApi";
import { CopyField } from "@/panel/ui/CopyField";
import { useAuthedPoll } from "@/panel/lib/useAuthedPoll";
import {
  cancelExternalDeal,
  confirmExternalDeal,
  extendExternalDeal,
  externalDealReceiptUrl,
  getExternalDeal,
  getMe,
  listExternalDeals,
  requestExternalDealVideo,
  type ExternalDealRow,
  type OperatorMe,
} from "@/panel/lib/operatorApi";
import { orderStatusTone, statusLabel } from "@/panel/lib/orderStatus";
import { Badge, Button, Card, PageHeader, cx } from "@/panel/ui/primitives";

type Filter = "open" | "confirmed" | "cancelled" | "all";

function money(v: unknown) {
  return new Intl.NumberFormat("ru-RU", { maximumFractionDigits: 2 }).format(Number(v ?? 0));
}

function asRecord(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" ? (value as Record<string, unknown>) : {};
}

function dealStatus(deal: ExternalDealRow): string {
  return String(deal.order_status || deal.status || "—");
}

function billLines(deal: ExternalDealRow): Array<{ label: string; value: string }> {
  const bill = asRecord(deal.bill);
  const payment = asRecord(deal.payment);
  const nested = asRecord(payment.bill);
  const src = Object.keys(bill).length ? bill : nested;
  const out: Array<{ label: string; value: string }> = [];
  const bank = String(src.bank || src.bankName || "").trim();
  const reciver = String(src.reciver || src.receiver || src.phone || src.card || "").trim();
  const fio = String(src.fio || src.holderName || "").trim();
  if (bank) out.push({ label: "Банк", value: bank });
  if (reciver) out.push({ label: "Реквизит", value: reciver });
  if (fio) out.push({ label: "ФИО", value: fio });
  return out;
}

function Mini({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <div className="text-[11px] text-[var(--text-muted)]">{label}</div>
      <div className="text-[13px] text-[var(--text-primary)]">{value}</div>
    </div>
  );
}

function StatBlock({ deal }: { deal: ExternalDealRow }) {
  const stat = asRecord(deal.client_stat || deal.check);
  const paid = Number(stat.paid_orders ?? 0);
  const total = Number(stat.total_orders ?? 0);
  const buyPaid = Number(stat.buy_paid ?? paid);
  const buyFailed = Number(stat.buy_failed ?? 0);
  const conv = stat.conversion_pct;
  const turnover = money(stat.turnover_rub);
  const hasStat = Boolean(deal.client_stat) || paid > 0 || total > 0 || buyFailed > 0;
  const convText =
    conv == null || conv === ""
      ? buyPaid + buyFailed <= 0
        ? "нет данных (первая заявка)"
        : `${buyPaid}/${buyPaid + buyFailed}`
      : `${conv}% (${buyPaid}/${buyPaid + buyFailed})`;
  return (
    <div className="rounded-[var(--radius)] bg-[var(--bg-elevated)] p-3 text-[13px]">
      <div className="mb-2 text-[11px] font-semibold uppercase tracking-wide text-[var(--text-muted)]">
        Статистика клиента
      </div>
      {!hasStat ? (
        <p className="text-[var(--text-muted)]">Магазин ещё не прислал сводку — как новый клиент.</p>
      ) : null}
      <div className="grid grid-cols-2 gap-2">
        <Mini label="Оплачено" value={String(paid)} />
        <Mini label="Конверсия BUY" value={convText} />
        <Mini label="Заявок всего" value={`${total || buyPaid + buyFailed} · отмен ${buyFailed}`} />
        <Mini label="Объём" value={`${turnover} ₽`} />
      </div>
    </div>
  );
}

export function OperatorExternal() {
  const [openDeals, setOpenDeals] = useState<ExternalDealRow[]>([]);
  const [closedDeals, setClosedDeals] = useState<ExternalDealRow[]>([]);
  const [filter, setFilter] = useState<Filter>("open");
  const [selId, setSelId] = useState<number | null>(null);
  const [detail, setDetail] = useState<ExternalDealRow | null>(null);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [lastUpdated, setLastUpdated] = useState<number | null>(null);
  const [me, setMe] = useState<OperatorMe | null>(null);
  const [shiftLoaded, setShiftLoaded] = useState(false);
  const [busy, setBusy] = useState(false);

  const load = useCallback(() => {
    setRefreshing(true);
    Promise.allSettled([
      listExternalDeals("open"),
      listExternalDeals("all"),
      getMe(),
    ]).then(([openRes, allRes, meRes]) => {
      if (openRes.status === "fulfilled") setOpenDeals(openRes.value.deals ?? []);
      else toast.error(openRes.reason instanceof PanelApiError ? openRes.reason.message : "Ошибка загрузки внештата");
      if (allRes.status === "fulfilled") setClosedDeals(allRes.value.deals ?? []);
      if (meRes.status === "fulfilled") setMe(meRes.value);
      setLastUpdated(Date.now());
      setShiftLoaded(true);
    }).finally(() => {
      setLoading(false);
      setRefreshing(false);
    });
  }, []);

  useAuthedPoll("operator", load, 8000, [load]);

  const list = useMemo(() => {
    if (filter === "open") return openDeals;
    const all = closedDeals.length ? closedDeals : openDeals;
    if (filter === "all") return all;
    if (filter === "confirmed") return all.filter((d) => String(d.status) === "confirmed");
    return all.filter((d) => ["cancelled", "canceled"].includes(String(d.status)));
  }, [closedDeals, filter, openDeals]);

  useEffect(() => {
    if (selId && list.some((d) => d.id === selId)) return;
    if (list.length) setSelId(list[0].id);
    else setSelId(null);
  }, [list, selId]);

  useEffect(() => {
    if (selId == null) {
      setDetail(null);
      return;
    }
    getExternalDeal(selId)
      .then(setDetail)
      .catch(() => {
        const fallback = list.find((d) => d.id === selId) ?? null;
        setDetail(fallback);
      });
  }, [selId, list]);

  const shiftOpen = !!me?.active_shift;
  const shiftLocked = shiftLoaded && !shiftOpen;
  const selected = detail && detail.id === selId ? detail : list.find((d) => d.id === selId) ?? null;

  async function run(fn: () => Promise<unknown>, ok: string) {
    setBusy(true);
    try {
      await fn();
      toast.success(ok);
      load();
      if (selId != null) {
        const next = await getExternalDeal(selId);
        setDetail(next);
      }
    } catch (e) {
      toast.error(e instanceof PanelApiError ? e.message : "Ошибка операции");
    } finally {
      setBusy(false);
    }
  }

  const actionDisabled = busy || !shiftOpen;
  const openStatus = selected ? String(selected.status) : "";
  const canAct = openStatus === "awaiting_receipt" || openStatus === "pending";

  return (
    <>
      <PageHeader
        title="Внештатные обмены"
        subtitle={`Открытых ${openDeals.length}`}
        actions={
          <div className="flex items-center gap-2">
            <span className="text-[11px] text-[var(--text-muted)]">
              {refreshing ? "Обновление…" : lastUpdated ? `Обновлено ${new Date(lastUpdated).toLocaleTimeString("ru-RU", { hour: "2-digit", minute: "2-digit" })}` : "—"}
            </span>
            <Button size="sm" variant="ghost" onClick={load} disabled={refreshing} aria-label="Обновить">↻</Button>
          </div>
        }
      />

      {shiftLocked && (
        <div className="rounded-[var(--radius-lg)] border border-[var(--yellow)]/30 bg-[var(--yellow-bg)] px-4 py-3 text-[13px] text-[var(--yellow)]">
          Смена не открыта. Сделки видны, действия — после открытия смены.
        </div>
      )}

      <div className="grid grid-cols-[minmax(0,1fr)_420px] gap-4 max-lg:grid-cols-1">
        <Card className="p-0">
          <div className="grid grid-cols-4 gap-1 border-b border-[var(--border)] p-2" role="tablist">
            {(
              [
                ["open", "Открытые", openDeals.length],
                ["confirmed", "Подтверждены", closedDeals.filter((d) => d.status === "confirmed").length],
                ["cancelled", "Отмены", closedDeals.filter((d) => ["cancelled", "canceled"].includes(String(d.status))).length],
                ["all", "Все", closedDeals.length || openDeals.length],
              ] as const
            ).map(([id, title, count]) => (
              <button
                key={id}
                type="button"
                role="tab"
                aria-selected={filter === id}
                onClick={() => setFilter(id)}
                className={cx(
                  "rounded-[var(--radius)] px-2 py-2 text-left text-[12px] font-semibold",
                  filter === id ? "bg-[var(--bg-elevated)] text-[var(--text-primary)]" : "text-[var(--text-muted)]",
                )}
              >
                {title} <span className="text-[var(--text-muted)]">{count}</span>
              </button>
            ))}
          </div>
          <div className="max-h-[calc(100dvh-220px)] overflow-y-auto">
            {list.length === 0 ? (
              <p className="p-8 text-center text-[13px] text-[var(--text-muted)]">
                {loading ? "Загрузка…" : "Нет сделок"}
              </p>
            ) : (
              list.map((deal) => (
                <button
                  key={deal.id}
                  type="button"
                  onClick={() => setSelId(deal.id)}
                  className={cx(
                    "flex w-full items-center justify-between gap-3 border-b border-[var(--border)] px-4 py-3 text-left",
                    selId === deal.id ? "bg-[var(--bg-elevated)]" : "hover:bg-[var(--bg-elevated)]/50",
                  )}
                >
                  <div>
                    <div className="font-mono text-[13px] font-semibold">#{deal.id}</div>
                    <div className="text-[12px] text-[var(--text-muted)]">{String(deal.exchanger_name || "магазин")}</div>
                  </div>
                  <div className="text-right">
                    <div className="font-mono text-[13px]">{money(deal.client_pays_rub)} ₽</div>
                    <Badge tone={orderStatusTone(dealStatus(deal))}>{statusLabel(dealStatus(deal))}</Badge>
                  </div>
                </button>
              ))
            )}
          </div>
        </Card>

        <div>
          {!selected ? (
            <Card className="p-6 text-[13px] text-[var(--text-muted)]">Выберите сделку</Card>
          ) : (
            <Card className="flex flex-col gap-4">
              <div className="flex items-center justify-between">
                <span className="font-mono text-[15px] font-semibold">#{selected.id}</span>
                <Badge tone={orderStatusTone(dealStatus(selected))}>{statusLabel(dealStatus(selected))}</Badge>
              </div>
              <div className="grid grid-cols-2 gap-2 text-[13px]">
                <Mini label="Магазин" value={String(selected.exchanger_name || "—")} />
                <Mini label="Актив" value={String(selected.crypto || "usdt").toUpperCase()} />
                <Mini label="Клиент платит" value={`${money(selected.client_pays_rub)} ₽`} />
                <Mini label="Payfast" value={String(selected.merchant_order_id || `EXT-${selected.id}`)} />
                <Mini
                  label="Окно до"
                  value={
                    selected.expires_at
                      ? new Date(String(selected.expires_at)).toLocaleString("ru-RU", {
                          day: "2-digit",
                          month: "2-digit",
                          hour: "2-digit",
                          minute: "2-digit",
                        })
                      : "—"
                  }
                />
                <Mini label="Fingerprint" value={String(selected.fingerprint || "—")} />
              </div>
              {billLines(selected).length > 0 && (
                <div className="flex flex-col gap-2">
                  {billLines(selected).map((row) => (
                    <CopyField key={row.label} label={row.label} value={row.value} />
                  ))}
                </div>
              )}
              <StatBlock deal={selected} />
              {selected.has_receipt && (
                <a
                  href={externalDealReceiptUrl(selected.id)}
                  target="_blank"
                  rel="noreferrer"
                  className="text-[13px] text-[var(--blue)] underline-offset-4 hover:underline"
                >
                  Открыть чек →
                </a>
              )}
              <div className="flex flex-col gap-2 border-t border-[var(--border)] pt-4">
                {canAct && (
                  <>
                    <Button
                      variant="secondary"
                      disabled={actionDisabled}
                      onClick={() => run(() => requestExternalDealVideo(selected.id), "Запрошено видео")}
                    >
                      Запросить видео
                    </Button>
                    <Button
                      variant="secondary"
                      disabled={actionDisabled}
                      onClick={() => run(() => extendExternalDeal(selected.id, 20), "Окно оплаты продлено на 20 мин")}
                    >
                      Продлить 20 мин
                    </Button>
                    <Button
                      variant="primary"
                      disabled={actionDisabled}
                      onClick={() => run(() => confirmExternalDeal(selected.id), "Сделка подтверждена")}
                    >
                      Подтвердить
                    </Button>
                    <Button
                      variant="danger"
                      disabled={actionDisabled}
                      onClick={() => run(() => cancelExternalDeal(selected.id), "Сделка отменена")}
                    >
                      Отменить
                    </Button>
                  </>
                )}
                <Link to="/ops/chat" className="text-[13px] text-[var(--blue)] underline-offset-4 hover:underline">
                  Чат внештатника →
                </Link>
              </div>
            </Card>
          )}
        </div>
      </div>
    </>
  );
}
