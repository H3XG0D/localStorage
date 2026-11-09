import { useCallback, useEffect, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { ArrowLeft } from "lucide-react";
import { toast } from "sonner";
import { PanelApiError } from "@/panel/lib/panelApi";
import {
  getPartnerWithdrawals,
  getPartners,
  getPromo,
  partnerPayout,
  partnerWithdrawalPaid,
  partnerWithdrawalReject,
  patchPartner,
  resetPartnerPassword,
  type Dict,
} from "@/panel/lib/adminApi";
import { orderStatusTone, statusLabel } from "@/panel/lib/orderStatus";
import { Badge, Button, Card, Field, Input, Kpi, PageHeader, Table, cx, type Column } from "@/panel/ui/primitives";

function money(v: unknown, digits = 0) {
  return new Intl.NumberFormat("ru-RU", { maximumFractionDigits: digits }).format(Number(v ?? 0));
}
function pct(v: unknown) {
  return v == null || v === "" ? "—" : `${Number(v)}%`;
}
function dt(v: unknown) {
  if (!v) return "—";
  const d = new Date(String(v));
  return Number.isNaN(d.getTime()) ? "—" : d.toLocaleString("ru-RU");
}
async function copyText(value: string, ok = "Скопировано") {
  try {
    await navigator.clipboard.writeText(value);
    toast.success(ok);
  } catch {
    toast.error("Не удалось скопировать");
  }
}

export function AdminPartnerDetail() {
  const { id } = useParams();
  const navigate = useNavigate();
  const pid = Number(id);
  const [payload, setPayload] = useState<Dict | null>(null);
  const [withdrawals, setWithdrawals] = useState<Dict[]>([]);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [editPct, setEditPct] = useState("");
  const [editAd, setEditAd] = useState("");
  const [editing, setEditing] = useState(false);
  const [payoutAmount, setPayoutAmount] = useState("");
  const [payoutNote, setPayoutNote] = useState("");
  const [wdTx, setWdTx] = useState<Record<string, string>>({});
  const [listRow, setListRow] = useState<Dict | null>(null);
  const [resetInfo, setResetInfo] = useState<Dict | null>(null);

  const load = useCallback(() => {
    if (!Number.isFinite(pid)) return;
    setLoading(true);
    Promise.all([
      getPromo(pid),
      getPartnerWithdrawals(pid).catch(() => ({ withdrawals: [] as Dict[] })),
      getPartners().catch(() => ({ partners: [] as Dict[] })),
    ])
      .then(([detail, wd, listed]) => {
        setPayload(detail);
        const promo = (detail.promo as Dict) || {};
        setEditPct(String(promo.partner_commission_percent ?? ""));
        setEditAd(String((detail.metrics as Dict | undefined)?.ad_spend_rub ?? promo.ad_spend_rub ?? "0"));
        setWithdrawals(Array.isArray(wd) ? wd : ((wd as Dict).withdrawals as Dict[]) || []);
        const partners = Array.isArray(listed) ? listed : ((listed as Dict).partners as Dict[]) || [];
        setListRow(partners.find((p) => Number(p.id) === pid) ?? null);
      })
      .catch((e) => toast.error(e instanceof PanelApiError ? e.message : "Партнёр не найден"))
      .finally(() => setLoading(false));
  }, [pid]);

  useEffect(() => load(), [load]);

  const promo = (payload?.promo ?? {}) as Dict;
  const partner = (payload?.partner ?? {}) as Dict;
  const metrics = (payload?.metrics ?? {}) as Dict;
  const users = (payload?.users ?? []) as Dict[];
  const orders = (payload?.orders ?? []) as Dict[];
  const ledger = (payload?.ledger ?? []) as Dict[];
  const gifts = (payload?.gift_entries ?? []) as Dict[];
  const webLink = String(promo.referral_web_link ?? "");
  const tgLink = String(promo.referral_link ?? "");
  const everyN = Number(listRow?.tier_every_n ?? 0);
  const refsUntil = Number(listRow?.refs_until_next_tier ?? 0);
  const progressDone = everyN > 0 ? Math.max(0, everyN - refsUntil) : 0;
  const progressPct = everyN > 0 ? Math.min(100, Math.round((progressDone / everyN) * 100)) : 0;
  const active = promo.is_active !== false && partner.is_active !== false;
  const effectivePct = listRow?.effective_percent ?? promo.partner_commission_percent;
  const nextTier = listRow?.next_tier_percent;
  const atMax = !!listRow?.at_max_tier;

  async function run(fn: () => Promise<unknown>, ok: string) {
    setBusy(true);
    try {
      await fn();
      toast.success(ok);
      load();
    } catch (e) {
      toast.error(e instanceof PanelApiError ? e.message : "Ошибка");
    } finally {
      setBusy(false);
    }
  }

  const userCols: Column<Dict>[] = [
    { key: "user_id", label: "ID", width: "110px", render: (r) => (
      <Link to={`/x8/users?user=${r.user_id}`} className="font-mono text-[var(--accent)] hover:underline" onClick={(e) => e.stopPropagation()}>
        {String(r.user_id ?? "—")}
      </Link>
    ) },
    { key: "username", label: "Юзернейм", render: (r) => (r.username ? `@${String(r.username)}` : String(r.first_name || "—")) },
    { key: "assigned_at", label: "Привязан", width: "160px", render: (r) => dt(r.assigned_at ?? r.entered_at) },
  ];
  const orderCols: Column<Dict>[] = [
    { key: "order_id", label: "#", render: (r) => <span className="font-mono">{String(r.order_id ?? "—")}</span> },
    { key: "direction", label: "Тип", width: "90px", render: (r) => (r.direction === "buy" ? "Покупка" : "Продажа") },
    { key: "fiat_amount", label: "₽", width: "110px", align: "right", render: (r) => <span className="font-mono">{money(r.fiat_amount)}</span> },
    { key: "status", label: "Статус", width: "140px", render: (r) => <Badge tone={orderStatusTone(String(r.status))}>{String(r.status_label ?? statusLabel(String(r.status)))}</Badge> },
    { key: "created_at", label: "Дата", width: "150px", render: (r) => dt(r.created_at) },
  ];
  const ledgerCols: Column<Dict>[] = [
    { key: "created_at", label: "Дата", width: "150px", render: (r) => dt(r.created_at) },
    { key: "type", label: "Тип", width: "110px", render: (r) => String(r.type ?? "—") },
    { key: "amount_rub", label: "₽", width: "110px", align: "right", render: (r) => <span className="font-mono">{money(r.amount_rub, 2)}</span> },
    { key: "order_id", label: "Заявка", render: (r) => String(r.order_id ?? "—") },
    { key: "note", label: "Заметка", render: (r) => String(r.note ?? "—") },
  ];

  return (
    <>
      <PageHeader
        title={String(promo.name || partner.display_name || promo.code || `Партнёр ${id}`)}
        subtitle={partner.username ? `Логин ${String(partner.username)}` : undefined}
        actions={
          <Button variant="ghost" onClick={() => navigate("/x8/partners")}>
            <ArrowLeft className="size-4" /> К списку
          </Button>
        }
      />

      {loading || !payload ? (
        <Card>{loading ? "Загрузка…" : "Нет данных"}</Card>
      ) : (
        <>
          <div className="grid grid-cols-4 gap-4 max-lg:grid-cols-2 max-[520px]:grid-cols-1">
            <Kpi label="Приведено" value={String(metrics.attracted_users ?? 0)} hint={`${metrics.paid_orders_count ?? 0} с оплатой`} />
            <Kpi label="Начислено, ₽" value={money(metrics.total_accrued, 2)} />
            <Kpi label="На балансе, ₽" value={money(metrics.partner_balance_rub ?? promo.balance_rub, 2)} />
            <Kpi label="Выплачено, ₽" value={money(metrics.total_paid_out, 2)} hint={`оборот ${money(metrics.paid_fiat_sum)} ₽`} />
            <Kpi label="Прибыль net, ₽" value={money(metrics.service_profit_net_rub, 2)} hint={`gross ${money(metrics.service_profit_gross_rub, 2)} ₽`} />
            <Kpi label="Эффект. %" value={pct(effectivePct)} />
            <Kpi label="Реклама, ₽" value={money(metrics.ad_spend_rub, 2)} />
            <Kpi label="Чистыми, ₽" value={money(metrics.net_after_ad_spend, 2)} />
          </div>

          {!atMax && everyN > 0 && (
            <Card>
              <div className="mb-2 flex justify-between text-[12.5px] text-[var(--text-secondary)]">
                <span>Прогресс до {pct(nextTier)}: {progressDone}/{everyN}</span>
                <span>ещё {refsUntil} реф.</span>
              </div>
              <div className="h-2 overflow-hidden rounded-full bg-[var(--bg-elevated)]">
                <div className="h-full bg-[var(--accent)]" style={{ width: `${progressPct}%` }} />
              </div>
            </Card>
          )}

          <Card>
            <div className="mb-3 text-[13.5px] font-semibold">Управление</div>
            <div className="mb-3 flex flex-wrap items-center gap-2">
              <Badge tone={active ? "green" : "red"}>{active ? "активен" : "выключен"}</Badge>
              <Button size="sm" variant="secondary" disabled={busy} onClick={() => run(() => patchPartner(pid, { is_active: !promo.is_active }), promo.is_active ? "Отключён" : "Включён")}>
                {promo.is_active ? "Отключить" : "Включить"}
              </Button>
              <Button size="sm" variant="secondary" disabled={busy} onClick={() => setEditing((v) => !v)}>
                {editing ? "Скрыть правку" : "Процент и реклама"}
              </Button>
              <Button
                size="sm"
                variant="secondary"
                disabled={busy}
                onClick={() =>
                  run(async () => {
                    const r = await resetPartnerPassword(pid);
                    setResetInfo(r);
                  }, "Пароль сброшен")
                }
              >
                Сбросить пароль
              </Button>
            </div>
            {resetInfo && (
              <div className="mb-3 rounded-[var(--radius)] border border-yellow-500/30 bg-yellow-500/10 p-3 text-[13px]">
                Логин <span className="font-mono">{String(resetInfo.username ?? "—")}</span>
                {" · "}пароль <span className="font-mono">{String(resetInfo.password ?? "—")}</span>
                <Button size="sm" variant="ghost" className="ml-2" onClick={() => copyText(`${resetInfo.username}\n${resetInfo.password}`, "Логин и пароль")}>
                  Копировать
                </Button>
              </div>
            )}
            {editing && (
              <div className="mb-4 grid max-w-md grid-cols-2 gap-3">
                <Field label="% от прибыли">
                  <Input inputMode="decimal" value={editPct} onChange={(e) => setEditPct(e.target.value)} className="font-mono" />
                </Field>
                <Field label="Реклама, ₽">
                  <Input inputMode="decimal" value={editAd} onChange={(e) => setEditAd(e.target.value)} className="font-mono" />
                </Field>
                <div className="col-span-2">
                  <Button
                    variant="primary"
                    disabled={busy}
                    onClick={() =>
                      run(
                        () => patchPartner(pid, {
                          partner_commission_percent: editPct === "" ? undefined : Number(editPct),
                          ad_spend_rub: editAd === "" ? undefined : Number(editAd),
                        }),
                        "Сохранено",
                      )
                    }
                  >
                    Сохранить
                  </Button>
                </div>
              </div>
            )}
            <div className="grid gap-3 md:grid-cols-2">
              <CopyRow label="Сайт" value={webLink} />
              <CopyRow label="Telegram" value={tgLink} />
            </div>
          </Card>

          <Card>
            <div className="mb-3 text-[13.5px] font-semibold">Ручная выплата</div>
            <div className="grid max-w-lg grid-cols-2 gap-3">
              <Field label="Сумма, ₽">
                <Input inputMode="decimal" value={payoutAmount} onChange={(e) => setPayoutAmount(e.target.value)} className="font-mono" />
              </Field>
              <Field label="Заметка">
                <Input value={payoutNote} onChange={(e) => setPayoutNote(e.target.value)} />
              </Field>
            </div>
            <div className="mt-3">
              <Button
                variant="primary"
                disabled={busy || Number(payoutAmount) <= 0}
                onClick={() =>
                  run(async () => {
                    await partnerPayout(pid, Number(payoutAmount), payoutNote.trim() || undefined);
                    setPayoutAmount("");
                    setPayoutNote("");
                  }, "Выплата проведена")
                }
              >
                Выплатить
              </Button>
            </div>
          </Card>

          <Card>
            <div className="mb-3 text-[13.5px] font-semibold">Заявки на вывод</div>
            {withdrawals.length === 0 ? (
              <p className="text-[12.5px] text-[var(--text-muted)]">Нет заявок.</p>
            ) : (
              <div className="flex flex-col gap-3">
                {withdrawals.map((w, i) => {
                  const wid = Number(w.id);
                  const source = String(w.source ?? "partner");
                  const pending = w.status === "pending" || w.status == null;
                  const key = `${source}-${wid || i}`;
                  const crypto = w.method === "crypto";
                  return (
                    <div key={key} className="rounded-[var(--radius)] bg-[var(--bg-elevated)] p-3 text-[13px]">
                      <div className="flex flex-wrap items-center justify-between gap-2">
                        <div className="flex flex-wrap items-center gap-2">
                          <span className="font-mono">{money(w.amount_rub, 2)} ₽</span>
                          <Badge tone={w.status === "paid" ? "green" : w.status === "rejected" ? "red" : "yellow"}>{String(w.status ?? "pending")}</Badge>
                          {source === "unified" && <Badge tone="blue">кабинет / бот</Badge>}
                        </div>
                        <span className="text-[12px] text-[var(--text-muted)]">{dt(w.created_at)}</span>
                      </div>
                      <div className="mt-2 text-[var(--text-secondary)]">
                        {w.method === "card" ? "Карта / СБП" : `Крипта ${String(w.crypto ?? "").toUpperCase()} ${String(w.network ?? "").toUpperCase()}`.trim()}
                      </div>
                      {w.requisites != null && w.requisites !== "" && (
                        <code className="mt-2 block break-all rounded bg-[var(--bg-surface)] p-2 text-[12px]">{String(w.requisites)}</code>
                      )}
                      {w.payout_tx_hash ? <div className="mt-1 font-mono text-[12px]">tx {String(w.payout_tx_hash)}</div> : null}
                      {pending && (
                        <div className="mt-3 flex flex-wrap items-end gap-2">
                          {crypto && (
                            <Field label="Tx hash">
                              <Input
                                value={wdTx[key] ?? ""}
                                onChange={(e) => setWdTx((prev) => ({ ...prev, [key]: e.target.value }))}
                                className="w-[220px] font-mono"
                              />
                            </Field>
                          )}
                          <Button
                            size="sm"
                            variant="primary"
                            disabled={busy}
                            onClick={() =>
                              run(
                                () => partnerWithdrawalPaid(wid, source, crypto ? (wdTx[key] || undefined) : undefined),
                                "Отмечено оплаченным",
                              )
                            }
                          >
                            Выплачено
                          </Button>
                          <Button size="sm" variant="danger" disabled={busy} onClick={() => run(() => partnerWithdrawalReject(wid, source), "Отклонено")}>
                            Отклонить
                          </Button>
                        </div>
                      )}
                    </div>
                  );
                })}
              </div>
            )}
          </Card>

          <Card>
            <div className="mb-3 text-[13.5px] font-semibold">Приведённые клиенты · {users.length}</div>
            <Table columns={userCols} rows={users} empty="Нет клиентов" />
          </Card>

          <Card>
            <div className="mb-3 text-[13.5px] font-semibold">Заявки рефералов · {orders.length}</div>
            <Table columns={orderCols} rows={orders} empty="Нет заявок" />
          </Card>

          <Card>
            <div className="mb-3 text-[13.5px] font-semibold">История баланса</div>
            <Table columns={ledgerCols} rows={ledger} empty="Пусто" />
          </Card>

          {gifts.length > 0 && (
            <Card>
              <div className="mb-3 text-[13.5px] font-semibold">Активации промо</div>
              <ul className="m-0 list-none space-y-1 p-0 text-[13px]">
                {gifts.map((g, i) => (
                  <li key={Number(g.user_id) || i} className="flex justify-between gap-2">
                    <span>{g.username ? `@${String(g.username)}` : String(g.user_id)}</span>
                    <span className="font-mono">{money(g.amount_rub, 2)} ₽ · {dt(g.entered_at ?? g.redeemed_at)}</span>
                  </li>
                ))}
              </ul>
            </Card>
          )}
        </>
      )}
    </>
  );
}

function CopyRow({ label, value }: { label: string; value: string }) {
  if (!value) return null;
  return (
    <div className={cx("flex flex-col gap-1.5")}>
      <span className="text-[11px] font-semibold uppercase tracking-wide text-[var(--text-muted)]">{label}</span>
      <div className="flex gap-2">
        <code className="min-w-0 flex-1 break-all rounded-[var(--radius)] bg-[var(--bg-elevated)] px-3 py-2 text-[12px]">{value}</code>
        <Button size="sm" variant="secondary" onClick={() => copyText(value, label)}>Копировать</Button>
      </div>
    </div>
  );
}
