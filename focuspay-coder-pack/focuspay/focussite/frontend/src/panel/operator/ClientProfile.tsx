import { useCallback, useEffect, useState } from "react";
import { useNavigate, useParams, useSearchParams } from "react-router-dom";
import { toast } from "sonner";
import { ArrowLeft } from "lucide-react";
import { PanelApiError } from "@/panel/lib/panelApi";
import { adjustUserBalance, banUser, closeClientHold, getUser, getUserCasinoHistory, getUserCasinoProfile, unbanUser } from "@/panel/lib/operatorApi";
import { panelMe } from "@/panel/lib/panelAuth";
import type { CasinoClientProfile } from "@/panel/lib/casinoClientProfile";
import { orderStatusTone, statusLabel } from "@/panel/lib/orderStatus";
import { ClientCasinoTab } from "@/panel/ui/ClientCasinoTab";
import { Badge, Button, Card, Field, Input, Kpi, PageHeader, Table, Tabs, cx, type Column } from "@/panel/ui/primitives";

function money(v: unknown) {
  return new Intl.NumberFormat("ru-RU", { maximumFractionDigits: 0 }).format(Number(v ?? 0));
}
function money2(v: unknown) {
  return new Intl.NumberFormat("ru-RU", { maximumFractionDigits: 2 }).format(Number(v ?? 0));
}
function parseAmount(raw: string): number {
  const t = String(raw ?? "").trim().replace(/\s+/g, "").replace(/,/g, ".");
  if (!t) return NaN;
  const n = Number(t);
  return Number.isFinite(n) ? n : NaN;
}
function dt(v: unknown) {
  return v ? new Date(String(v)).toLocaleString("ru-RU", { day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" }) : "—";
}
type Dict = Record<string, unknown>;

function telegramOpenHref(userId: unknown, username?: unknown): string | null {
  const id = Number(userId);
  if (Number.isInteger(id) && id < 0) return null;
  const uname = String(username ?? "").trim().replace(/^@/, "");
  if (uname) return `https://t.me/${encodeURIComponent(uname)}`;
  if (Number.isInteger(id) && id > 0) return `tg://user?id=${id}`;
  return null;
}

export function ClientProfile() {
  const { userId: paramId } = useParams();
  const [searchParams] = useSearchParams();
  const userId = (paramId || searchParams.get("uid") || "").trim();
  const navigate = useNavigate();
  const [p, setP] = useState<Dict | null>(null);
  const [loading, setLoading] = useState(true);
  const [banReason, setBanReason] = useState("");
  const [busy, setBusy] = useState(false);
  const [canCasino, setCanCasino] = useState(false);
  const [canAdjustBalance, setCanAdjustBalance] = useState(false);
  const [permKnown, setPermKnown] = useState(false);
  const [balAmount, setBalAmount] = useState("");
  const [balReason, setBalReason] = useState("");
  const wantCasino = searchParams.get("tab") === "casino";
  const tab = wantCasino && (canCasino || !permKnown) ? "casino" : "exchange";
  const [casino, setCasino] = useState<CasinoClientProfile | null>(null);
  const [casinoLoading, setCasinoLoading] = useState(false);
  const [casinoError, setCasinoError] = useState<string | null>(null);
  const [casinoTried, setCasinoTried] = useState(false);
  const [casinoMore, setCasinoMore] = useState(false);

  const load = useCallback(() => {
    if (!userId) {
      setP(null);
      setLoading(false);
      return;
    }
    setLoading(true);
    getUser(userId)
      .then((d) => setP(d as Dict))
      .catch((e) => toast.error(e instanceof PanelApiError ? e.message : "Клиент не найден"))
      .finally(() => setLoading(false));
  }, [userId]);

  useEffect(() => load(), [load]);

  useEffect(() => {
    let cancelled = false;
    panelMe("operator")
      .then((me) => {
        if (!cancelled) {
          const perms = Array.isArray(me.permissions) ? me.permissions.map(String) : [];
          const flag = (me as unknown as { can_adjust_balance?: unknown }).can_adjust_balance;
          const grades = (me as unknown as { role_grades?: unknown }).role_grades;
          const isSenior =
            !!grades &&
            typeof grades === "object" &&
            Object.values(grades as Record<string, unknown>).some(
              (g) => String(g ?? "").trim().toLowerCase() === "senior",
            );
          setCanCasino(perms.includes("casino.payout"));
          // Источник истины — бэк /operator/me.can_adjust_balance (finance.payout ИЛИ senior).
          // orders.history права НЕ даёт — кнопки для него скрываем.
          setCanAdjustBalance(
            typeof flag === "boolean" ? flag : perms.includes("finance.payout") || isSenior,
          );
          setPermKnown(true);
        }
      })
      .catch(() => {
        if (!cancelled) {
          setCanCasino(false);
          setPermKnown(true);
        }
      });
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    if (!permKnown || canCasino || !wantCasino) return;
    const next = new URLSearchParams(searchParams);
    next.delete("tab");
    const search = next.toString();
    navigate({ search: search ? `?${search}` : "" }, { replace: true });
  }, [permKnown, canCasino, wantCasino, searchParams, navigate]);

  function setTab(id: string) {
    const next = new URLSearchParams(searchParams);
    if (id === "casino" && canCasino) next.set("tab", "casino");
    else next.delete("tab");
    const search = next.toString();
    navigate({ search: search ? `?${search}` : "" }, { replace: true });
  }

  useEffect(() => {
    setCasino(null);
    setCasinoTried(false);
    setCasinoError(null);
  }, [userId]);

  useEffect(() => {
    if (!canCasino || tab !== "casino" || !userId || casinoTried) return;
    setCasinoTried(true);
    setCasinoLoading(true);
    setCasinoError(null);
    getUserCasinoProfile(userId)
      .then((payload) => setCasino(payload))
      .catch((e) => {
        if (e instanceof PanelApiError && e.status === 404) {
          setCasino(null);
          setCasinoError(null);
          return;
        }
        setCasinoError(e instanceof PanelApiError ? e.message : "Не удалось загрузить казино");
      })
      .finally(() => setCasinoLoading(false));
  }, [canCasino, tab, userId, casinoTried]);

  const identity = (p?.identity ?? {}) as Dict;
  const summary = (p?.summary ?? {}) as Dict;
  const balances = (p?.balances ?? {}) as Dict;
  const referral = (p?.referral ?? {}) as Dict;
  const lastDeal = (p?.last_deal ?? null) as Dict | null;
  const activeOrder = (p?.active_order ?? null) as Dict | null;
  const promo = (p?.promo ?? null) as Dict | null;
  const reviews = (p?.reviews ?? []) as Dict[];
  const orders = (p?.recent_orders ?? []) as Dict[];
  const banned = !!identity.is_banned;
  const referrer = (referral.referrer ?? identity.invited_by ?? null) as Dict | null;

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

  async function loadMoreCasino() {
    if (!userId || !casino?.history_next_before) return;
    setCasinoMore(true);
    try {
      const page = await getUserCasinoHistory(userId, { before: String(casino.history_next_before) });
      setCasino((prev) => {
        if (!prev) return prev;
        return {
          ...prev,
          recent_games: [...(prev.recent_games ?? []), ...(page.items ?? [])],
          history_next_before: page.next_before ?? null,
        };
      });
    } catch (e) {
      toast.error(e instanceof PanelApiError ? e.message : "Не удалось догрузить историю");
    } finally {
      setCasinoMore(false);
    }
  }

  const cols: Column<Dict>[] = [
    { key: "order_id", label: "#", render: (r) => <span className="font-mono">{String(r.order_id ?? "—")}</span> },
    { key: "direction", label: "Тип", width: "80px", render: (r) => (r.direction === "buy" ? "Покупка" : "Продажа") },
    { key: "crypto", label: "Актив", width: "80px", render: (r) => String(r.crypto ?? "—").toUpperCase() },
    { key: "fiat_amount", label: "₽", width: "100px", align: "right", render: (r) => <span className="font-mono">{money(r.fiat_amount)}</span> },
    { key: "status", label: "Статус", width: "130px", render: (r) => <Badge tone={orderStatusTone(String(r.status))}>{String(r.status_label ?? statusLabel(String(r.status)))}</Badge> },
    { key: "created_at", label: "Дата", width: "130px", render: (r) => dt(r.created_at) },
  ];

  const uid = identity.user_id ?? userId;
  const tgHref = telegramOpenHref(uid, identity.username);
  const tabItems = canCasino
    ? [
        { id: "exchange", label: "Обменник" },
        { id: "casino", label: "Казино" },
      ]
    : [{ id: "exchange", label: "Обменник" }];

  return (
    <>
      <PageHeader
        title="Профиль клиента"
        actions={
          <Button variant="ghost" onClick={() => navigate(-1)}>
            <ArrowLeft className="size-4" /> Назад
          </Button>
        }
      />

      {loading ? (
        <Card>Загрузка…</Card>
      ) : !p ? (
        <Card>Клиент не найден.</Card>
      ) : (
        <>
          <Card>
            <div className="flex items-center gap-4">
              {identity.avatar_url ? (
                <img src={String(identity.avatar_url)} alt="" className="size-16 rounded-full object-cover" />
              ) : (
                <div className="flex size-16 items-center justify-center rounded-full bg-[var(--bg-overlay)] text-lg font-bold text-[var(--text-secondary)]">
                  {String(identity.first_name || identity.username || uid || "?").slice(0, 2).toUpperCase()}
                </div>
              )}
              <div className="min-w-0 flex-1">
                <div className="flex items-center gap-2">
                  <span className="text-[16px] font-bold">{String(identity.first_name || identity.username || `ID ${uid}`)}</span>
                  {banned && <Badge tone="red">Заблокирован</Badge>}
                </div>
                <div className="mt-0.5 text-[12.5px] text-[var(--text-muted)]">
                  <span className="font-mono">ID {String(uid)}</span>
                  {identity.username ? ` · @${identity.username}` : ""}
                  {tgHref ? (
                    <>
                      {" · "}
                      <a href={tgHref} className="text-[var(--text-primary)] underline-offset-2 hover:underline">
                        Telegram
                      </a>
                    </>
                  ) : null}
                </div>
                <div className="mt-0.5 text-[11px] text-[var(--text-muted)]">
                  В боте с {dt(identity.first_seen_at)}
                  {identity.last_seen_at ? ` · был ${dt(identity.last_seen_at)}` : ""}
                </div>
              </div>
            </div>
          </Card>

          <div data-client-profile-tabs="">
            <Tabs value={tab} onChange={setTab} items={tabItems} />
          </div>

          {tab === "exchange" ? (
            <div className="flex flex-col gap-4" data-client-tab="exchange">
              <div className="grid grid-cols-4 gap-4 max-lg:grid-cols-2 max-[520px]:grid-cols-1">
                <Kpi label="Заявок всего" value={String(summary.total_orders ?? 0)} />
                <Kpi label="Оплачено" value={String(summary.paid_orders ?? 0)} />
                <Kpi label="Оборот, ₽" value={money(summary.turnover_rub)} />
                <Kpi label="Баланс, ₽" value={money(balances.balance_rub)} />
              </div>

              <div className="grid grid-cols-4 gap-4 max-lg:grid-cols-2 max-[520px]:grid-cols-1" data-client-exchange-summary>
                <Kpi label="Завершено" value={String(summary.completed_orders ?? 0)} />
                <Kpi label="Отменено" value={String(summary.canceled_orders ?? 0)} />
                <Kpi label="Покупки / продажи" value={`${summary.buy_paid ?? 0} / ${summary.sell_paid ?? 0}`} />
                <Kpi label="Конверсия" value={summary.conversion_pct == null ? "—" : `${summary.conversion_pct}%`} />
              </div>

              <Card data-client-exchange-balances>
                <div className="mb-2 text-[13.5px] font-semibold">Балансы</div>
                <div className="grid grid-cols-2 gap-3 text-[13px] sm:grid-cols-4">
                  <div>
                    <div className="text-[11px] text-[var(--text-muted)]">Доступно</div>
                    <div className="font-mono">{money2(balances.available_rub)} ₽</div>
                  </div>
                  <div>
                    <div className="text-[11px] text-[var(--text-muted)]">Кэшбэк</div>
                    <div className="font-mono">{money2(balances.cashback_rub)} ₽ · {String(balances.cashback_percent ?? 0)}%</div>
                  </div>
                  <div>
                    <div className="text-[11px] text-[var(--text-muted)]">Реферальные</div>
                    <div className="font-mono">{money2(balances.referral_rub)} ₽</div>
                  </div>
                  <div>
                    <div className="text-[11px] text-[var(--text-muted)]">Сэкономлено</div>
                    <div className="font-mono">{money2(balances.saved_rub)} ₽</div>
                  </div>
                </div>
                {canAdjustBalance ? (
                  <div className="mt-3 flex flex-col gap-2 border-t border-[var(--border)] pt-3">
                    <div className="text-[12px] text-[var(--text-muted)]">Начислить или списать единый баланс ₽. Нужна открытая смена.</div>
                    <div className="grid grid-cols-2 gap-2 max-sm:grid-cols-1">
                      <Field label="Сумма, ₽">
                        <Input
                          inputMode="decimal"
                          value={balAmount}
                          onChange={(e) => setBalAmount(e.target.value)}
                          placeholder="1000"
                          className="font-mono"
                        />
                      </Field>
                      <Field label="Причина">
                        <Input
                          value={balReason}
                          onChange={(e) => setBalReason(e.target.value)}
                          placeholder="Минимум 3 символа"
                        />
                      </Field>
                    </div>
                    <div className="flex flex-wrap gap-2">
                      <Button
                        size="sm"
                        variant="primary"
                        disabled={busy || !(parseAmount(balAmount) > 0) || balReason.trim().length < 3}
                        onClick={() => {
                          const amt = parseAmount(balAmount);
                          void run(async () => {
                            await adjustUserBalance(userId, Math.round(amt * 100) / 100, balReason.trim());
                            setBalAmount("");
                            setBalReason("");
                          }, "Баланс начислен");
                        }}
                      >
                        Начислить
                      </Button>
                      <Button
                        size="sm"
                        variant="danger"
                        disabled={busy || !(parseAmount(balAmount) > 0) || balReason.trim().length < 3}
                        onClick={() => {
                          const amt = parseAmount(balAmount);
                          if (!window.confirm(`Списать ${amt} ₽?`)) return;
                          void run(async () => {
                            await adjustUserBalance(userId, -(Math.round(amt * 100) / 100), balReason.trim());
                            setBalAmount("");
                            setBalReason("");
                          }, "Баланс списан");
                        }}
                      >
                        Списать
                      </Button>
                    </div>
                  </div>
                ) : null}
              </Card>

              {activeOrder && activeOrder.order_id != null && (
                <Card data-client-exchange-active>
                  <div className="mb-2 text-[13.5px] font-semibold">Активная заявка</div>
                  <div className="flex flex-wrap items-center gap-x-6 gap-y-2 text-[13px]">
                    <span className="font-mono">#{String(activeOrder.order_id)}</span>
                    <span>{activeOrder.direction === "buy" ? "Покупка" : "Продажа"} {String(activeOrder.crypto ?? "").toUpperCase()}</span>
                    <span className="font-mono">{money(activeOrder.fiat_amount)} ₽</span>
                    <Badge tone={orderStatusTone(String(activeOrder.status))}>{statusLabel(String(activeOrder.status))}</Badge>
                    <Button
                      size="sm"
                      variant="danger"
                      disabled={busy}
                      onClick={() => {
                        if (!window.confirm(`Закрыть #${String(activeOrder.order_id)}? Клиент сможет начать новый обмен.`)) return;
                        void run(() => closeClientHold(String(activeOrder.order_id)), "Заявка закрыта");
                      }}
                    >
                      Закрыть
                    </Button>
                  </div>
                </Card>
              )}

              {lastDeal && (
                <Card>
                  <div className="mb-2 text-[13.5px] font-semibold">Последняя заявка</div>
                  <div className="flex flex-wrap items-center gap-x-6 gap-y-1 text-[13px]">
                    <span className="font-mono">#{String(lastDeal.order_id ?? "—")}</span>
                    <span>{lastDeal.direction === "buy" ? "Покупка" : "Продажа"} {String(lastDeal.crypto ?? "").toUpperCase()}</span>
                    <span className="font-mono">{money(lastDeal.fiat_amount)} ₽</span>
                    <Badge tone={orderStatusTone(String(lastDeal.status))}>{statusLabel(String(lastDeal.status))}</Badge>
                    <span className="text-[var(--text-muted)]">{dt(lastDeal.created_at)}</span>
                  </div>
                </Card>
              )}

              <Card data-client-exchange-referral>
                <div className="mb-2 text-[13.5px] font-semibold">Реферальная программа</div>
                <div className="grid grid-cols-2 gap-3 text-[13px] sm:grid-cols-4">
                  <div>
                    <div className="text-[11px] text-[var(--text-muted)]">Привёл</div>
                    <div>{String(referral.referred_count ?? 0)}</div>
                  </div>
                  <div>
                    <div className="text-[11px] text-[var(--text-muted)]">Оплаченных у рефов</div>
                    <div>{String(referral.paid_orders_count ?? 0)}</div>
                  </div>
                  <div>
                    <div className="text-[11px] text-[var(--text-muted)]">Баланс реф., ₽</div>
                    <div className="font-mono">{money2(referral.referral_balance_rub)}</div>
                  </div>
                  <div>
                    <div className="text-[11px] text-[var(--text-muted)]">Начислено, ₽</div>
                    <div className="font-mono">{money2(referral.total_accrual_rub)}</div>
                  </div>
                </div>
                <div className="mt-2 text-[12.5px] text-[var(--text-muted)]">
                  Кто пригласил:{" "}
                  {referrer && typeof referrer === "object" && referrer.user_id != null
                    ? `${referrer.username ? `@${String(referrer.username)}` : `ID ${String(referrer.user_id)}`}`
                    : "—"}
                </div>
                {promo ? (
                  <div className="mt-1 text-[12.5px] text-[var(--text-muted)]">Промокод: {String(promo.promo_code ?? "—")}</div>
                ) : null}
              </Card>

              <Card>
                <div className="mb-3 text-[13.5px] font-semibold">История заявок</div>
                <Table columns={cols} rows={orders} empty="Заявок нет" />
              </Card>

              <Card data-client-exchange-reviews>
                <div className="mb-3 text-[13.5px] font-semibold">Отзывы</div>
                {reviews.length === 0 ? (
                  <p className="text-[13px] text-[var(--text-muted)]">Отзывов нет</p>
                ) : (
                  <ul className="m-0 list-none space-y-2 p-0 text-[12.5px]">
                    {reviews.map((r) => (
                      <li key={String(r.id)} className="rounded-[var(--radius)] bg-[var(--bg-elevated)] p-2">
                        <div className="flex justify-between gap-2">
                          <Badge tone={r.status === "published" ? "green" : r.status === "rejected" ? "red" : "yellow"}>
                            {String(r.status ?? "—")}
                          </Badge>
                          <span className="text-[var(--text-muted)]">{dt(r.created_at)}</span>
                        </div>
                        {r.bonus_rub != null ? <div className="mt-1 font-mono text-[12px]">{money2(r.bonus_rub)} ₽</div> : null}
                        {r.review_text ? <div className="mt-1 text-[var(--text-secondary)]">{String(r.review_text)}</div> : null}
                      </li>
                    ))}
                  </ul>
                )}
              </Card>
            </div>
          ) : (
            <div data-client-tab="casino">
              <ClientCasinoTab
                data={casino}
                scope="operator"
                loading={casinoLoading || (wantCasino && !permKnown)}
                error={casinoError}
                onLoadMore={loadMoreCasino}
                loadingMore={casinoMore}
              />
            </div>
          )}

          <Card>
            <div className="mb-3 text-[13.5px] font-semibold">Модерация</div>
            {banned ? (
              <div className="flex flex-col gap-2">
                {identity.ban_reason ? <p className="text-[13px] text-[var(--text-muted)]">Причина: {String(identity.ban_reason)}</p> : null}
                <Button variant="secondary" disabled={busy} onClick={() => run(() => unbanUser(uid as number), "Разбанен")} className={cx("w-fit")}>
                  Разбанить
                </Button>
              </div>
            ) : (
              <div className="flex flex-col gap-2 sm:max-w-md">
                <Field label="Причина блокировки">
                  <Input value={banReason} onChange={(e) => setBanReason(e.target.value)} />
                </Field>
                <div className="flex gap-2">
                  <Button variant="danger" disabled={busy} onClick={() => run(() => banUser(uid as number, banReason, "hard"), "Заблокирован (hard)")}>
                    Бан (hard)
                  </Button>
                  <Button variant="secondary" disabled={busy} onClick={() => run(() => banUser(uid as number, banReason, "soft"), "Заблокирован (soft)")}>
                    Бан (soft)
                  </Button>
                </div>
              </div>
            )}
          </Card>
        </>
      )}
    </>
  );
}
