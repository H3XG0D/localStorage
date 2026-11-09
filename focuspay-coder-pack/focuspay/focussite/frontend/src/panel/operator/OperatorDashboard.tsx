import { useCallback, useState } from "react";
import { Link } from "react-router-dom";
import { toast } from "sonner";
import { PanelApiError } from "@/panel/lib/panelApi";
import { useAuthedPoll } from "@/panel/lib/useAuthedPoll";
import { confirmHotWalletSwap, endShift, getMe, getOperatorHotWallet, getOrders, getQueue, previewHotWalletSwap, startShift, type HotWalletSwapPreview, type HotWalletView, type OperatorMe, type QueueSummary, type OrderRow, type ShiftBalance } from "@/panel/lib/operatorApi";
import { CopyField } from "@/panel/ui/CopyField";
import { Badge, Button, Card, Field, Input, Kpi, Modal, PageHeader, Select } from "@/panel/ui/primitives";

function fmtMoney(v: number | undefined) {
  return new Intl.NumberFormat("ru-RU", { maximumFractionDigits: 0 }).format(Number(v ?? 0));
}

function fmtMoney2(v: number | undefined) {
  return new Intl.NumberFormat("ru-RU", { minimumFractionDigits: 2, maximumFractionDigits: 2 }).format(Number(v ?? 0));
}

function fmtCoin(v: unknown) {
  const n = Number(v ?? 0);
  if (!Number.isFinite(n)) return "0";
  return n.toLocaleString("ru-RU", { maximumFractionDigits: 8 });
}

const SHIFT_COINS = ["usdt", "btc", "trx", "ltc"] as const;

function roleLabel(role: string) {
  return role === "finance" ? "Финансы" : "Клиент";
}

function gradeLabel(grade: unknown) {
  return grade === "trainee" ? "стажёр" : grade === "senior" ? "старший" : "новичок";
}

function shiftValue(me: OperatorMe | null, key: string) {
  return (me?.current_shift as Record<string, unknown> | null | undefined)?.[key];
}

export function OperatorDashboard() {
  const [me, setMe] = useState<OperatorMe | null>(null);
  const [hot, setHot] = useState<HotWalletView | null>(null);
  const [queue, setQueue] = useState<QueueSummary | null>(null);
  const [myOrders, setMyOrders] = useState<OrderRow[]>([]);
  const [myWithdrawals, setMyWithdrawals] = useState<Record<string, unknown>[]>([]);
  const [loading, setLoading] = useState(true);
  const [lastUpdated, setLastUpdated] = useState<number | null>(null);
  const [busy, setBusy] = useState(false);
  const [shiftModal, setShiftModal] = useState<null | "start" | "end">(null);
  const [bal, setBal] = useState<Record<string, string>>({ usdt: "", btc: "", trx: "", ltc: "" });
  const [note, setNote] = useState("");

  const load = useCallback(() => {
    setLoading(true);
    Promise.allSettled([getMe(), getQueue(), getOrders(20, 0)]).then(async ([meResult, queueResult, ordersResult]) => {
      if (meResult.status === "fulfilled") {
        setMe(meResult.value);
        const senior = meResult.value.operator?.role_grades?.finance === "senior";
        if (meResult.value.active_shift && senior) {
          try {
            setHot(await getOperatorHotWallet());
          } catch {
            setHot(null);
          }
        } else {
          setHot(null);
        }
      } else {
        setHot(null);
        toast.error(meResult.reason instanceof PanelApiError ? meResult.reason.message : "Ошибка загрузки смены");
      }
      if (queueResult.status === "fulfilled") setQueue(queueResult.value);
      else toast.error(queueResult.reason instanceof PanelApiError ? queueResult.reason.message : "Ошибка загрузки очереди");
      if (ordersResult.status === "fulfilled") {
        const mineId = meResult.status === "fulfilled" ? meResult.value.operator?.id : undefined;
        const open = ordersResult.value.orders ?? [];
        setMyOrders(
          open.filter(
            (order) =>
              Boolean(order.assigned_to_me) ||
              (mineId != null && Number(order.operator_id) === mineId),
          ),
        );
        setMyWithdrawals(ordersResult.value.withdrawals ?? []);
      } else {
        toast.error(ordersResult.reason instanceof PanelApiError ? ordersResult.reason.message : "Ошибка загрузки активных задач");
      }
      setLastUpdated(Date.now());
    }).finally(() => setLoading(false));
  }, []);

  useAuthedPoll("operator", load, 15000, [load]);

  const onShift = !!me?.active_shift;
  const showHot = onShift && me?.operator?.role_grades?.finance === "senior" && hot != null;
  const earnings = Number(shiftValue(me, "earnings_rub") ?? 0);
  const hourlyApplies = shiftValue(me, "hourly_applies") === true;
  const hourlyForecast = hourlyApplies ? Number(shiftValue(me, "hourly_forecast_rub") ?? 0) : 0;
  const dealEarnings = hourlyApplies
    ? Number(shiftValue(me, "deal_earnings_rub") ?? Math.max(0, earnings - hourlyForecast))
    : earnings;
  const earningsText = hourlyApplies ? fmtMoney2(earnings) : fmtMoney(earnings);
  const ordersKpi = onShift
    ? String(shiftValue(me, "orders_count") ?? 0)
    : String(me?.today?.orders_count ?? 0);
  const turnoverKpi = fmtMoney(
    Number(onShift ? (shiftValue(me, "fiat_total") ?? 0) : (me?.today?.fiat_total ?? 0)),
  );
  const activeTasks = [
    ...myOrders.map((order) => ({
      key: `order-${order.order_id}`,
      href: `/ops/orders?order=${encodeURIComponent(order.order_id)}`,
      title: `#${order.order_id}`,
      subtitle: `${order.direction === "buy" ? "Покупка" : "Продажа"} ${String(order.crypto).toUpperCase()}`,
      status: order.status_label || order.status,
    })),
    ...myWithdrawals.map((withdrawal) => ({
      key: `withdrawal-${String(withdrawal.id)}`,
      href: "/ops/orders",
      title: `Вывод #${String(withdrawal.id)}`,
      subtitle: `${String(withdrawal.method ?? "").toLowerCase() === "crypto" ? String(withdrawal.crypto ?? "crypto").toUpperCase() : "Карта"}`,
      status: "В работе",
    })),
  ];

  function openShiftModal(kind: "start" | "end") {
    setBal({ usdt: "", btc: "", trx: "", ltc: "" });
    setNote("");
    setShiftModal(kind);
  }

  async function submitShift() {
    const balances: ShiftBalance[] = SHIFT_COINS.map((c) => ({ crypto: c, amount: Number(bal[c] || 0) }));
    setBusy(true);
    try {
      if (shiftModal === "end") {
        await endShift(note, balances);
        toast.success("Смена закрыта");
      } else {
        await startShift(balances);
        toast.success("Смена открыта");
      }
      setShiftModal(null);
      load();
    } catch (e) {
      toast.error(e instanceof PanelApiError ? e.message : "Не удалось изменить смену");
    } finally {
      setBusy(false);
    }
  }

  const today = new Date().toLocaleDateString("ru-RU", { day: "numeric", month: "long" });

  return (
    <>
      <PageHeader
        title="Дашборд"
        subtitle={`Смена и заявки на ${today}`}
        actions={
          <>
            <span className="text-[11px] text-[var(--text-muted)]" aria-live="polite">
              {lastUpdated ? `Обновлено ${new Date(lastUpdated).toLocaleTimeString("ru-RU", { hour: "2-digit", minute: "2-digit" })}` : "Обновление…"}
            </span>
            <Badge tone={onShift ? "green" : "default"}>{onShift ? "На смене" : "Не на смене"}</Badge>
            <Button variant={onShift ? "danger" : "primary"} onClick={() => openShiftModal(onShift ? "end" : "start")} disabled={busy || loading}>
              {onShift ? "Закрыть смену" : "Открыть смену"}
            </Button>
            <Button variant="secondary" disabled={busy || loading || !onShift} onClick={() => (window.location.href = "/ops/create")}>
              + Заявка
            </Button>
          </>
        }
      />

      <div className="grid grid-cols-6 gap-4 max-xl:grid-cols-3 max-lg:grid-cols-2 max-[520px]:grid-cols-1">
        <Kpi label="Новые обмены" value={queue?.exchange_incoming_count ?? 0} />
        <Kpi label="Новые выводы" value={queue?.withdrawal_incoming_count ?? 0} />
        <Kpi label="В работе у меня" value={me?.active_work_count ?? "—"} />
        <Kpi label={onShift ? "Заявок за смену" : "Заявок сегодня"} value={ordersKpi} />
        <Kpi label={onShift ? "Оборот за смену, ₽" : "Оборот сегодня, ₽"} value={turnoverKpi} />
        <Kpi
          label="Заработано за смену, ₽"
          value={onShift ? earningsText : "—"}
          hint={
            onShift
              ? hourlyApplies
                ? `заявки ${fmtMoney2(dealEarnings)} · часы ${fmtMoney2(hourlyForecast)}`
                : "Начисление оператора"
              : "Откройте смену для начисления"
          }
        />
      </div>

      {showHot && hot ? (
        <HotWalletCard
          data={hot}
          onSent={() => {
            getOperatorHotWallet().then(setHot).catch(() => setHot(null));
          }}
        />
      ) : null}

      <div className="grid grid-cols-[1fr_320px] gap-4 max-[1100px]:grid-cols-1">
        <Card>
          <div className="mb-3 flex items-center justify-between">
            <div>
              <div className="text-[13.5px] font-semibold">Мои активные задачи</div>
              <div className="mt-0.5 text-[11px] text-[var(--text-muted)]">Заявки и выводы, взятые в работу</div>
            </div>
            <Link to="/ops/orders" className="text-[12px] text-[var(--text-muted)] hover:text-[var(--text-primary)]">Открыть очередь →</Link>
          </div>
          {activeTasks.length > 0 ? (
            <div className="flex flex-col gap-2">
              {activeTasks.slice(0, 3).map((task) => (
                <Link key={task.key} to={task.href} className="flex items-center justify-between gap-3 rounded-[var(--radius)] bg-[var(--bg-elevated)] p-3 hover:bg-[var(--bg-overlay)]">
                  <div className="min-w-0">
                    <div className="font-mono text-[13px] font-semibold">{task.title}</div>
                    <div className="truncate text-[12px] text-[var(--text-muted)]">{task.subtitle}</div>
                  </div>
                  <Badge tone="yellow">{task.status}</Badge>
                </Link>
              ))}
            </div>
          ) : (
            <p className="py-5 text-center text-[13px] text-[var(--text-muted)]">
              {(queue?.ready_to_accept_count ?? me?.queue_count ?? 0) > 0
                ? `Новых задач: обмены ${queue?.exchange_incoming_count ?? 0} · выводы ${queue?.withdrawal_incoming_count ?? 0}`
                : "Активных задач нет."}
            </p>
          )}
        </Card>

        {/* current shift summary */}
        <Card>
          <div className="mb-3 flex items-center justify-between">
            <span className="text-[13.5px] font-semibold">Баланс смены</span>
            <Link to="/ops/orders" className="text-[12px] text-[var(--text-muted)] hover:text-[var(--text-primary)]">
              Открыть заявки →
            </Link>
          </div>
          {onShift ? (
            <>
            <div className="mb-3 rounded-[var(--radius)] bg-[var(--green-bg)] p-3">
              <div className="text-[10px] uppercase tracking-wide text-[var(--green)]">Заработано за смену</div>
              <div className="mt-1 font-mono text-xl font-bold text-[var(--green)]">{earningsText} ₽</div>
              {hourlyApplies ? (
                <div className="mt-1 text-[11px] leading-snug text-[var(--green)]">
                  Часы {fmtMoney2(hourlyForecast)} ₽ из общего фонда. В баланс сядут при закрытии смены.
                </div>
              ) : null}
            </div>
            <div className="grid grid-cols-3 gap-2 text-[13px]">
              <ShiftStat label="Начало" value={me?.active_shift?.started_at ? new Date(me.active_shift.started_at).toLocaleTimeString("ru-RU", { hour: "2-digit", minute: "2-digit" }) : "—"} />
              <ShiftStat label="Заявок" value={String(shiftValue(me, "orders_count") ?? 0)} />
              <ShiftStat label="Оборот ₽" value={fmtMoney(Number(shiftValue(me, "fiat_total") ?? 0))} />
              {/* Остатки криптокошельков, введённые при открытии смены — без прибыли/финансов */}
              {(me?.shift_balances ?? []).map((b, i) => (
                <ShiftStat
                  key={`${String(b.crypto ?? "coin")}-${i}`}
                  label={String(b.crypto ?? "").toUpperCase()}
                  value={fmtCoin(b.balance_end ?? b.balance_start ?? b.amount)}
                />
              ))}
            </div>
            </>
          ) : (
            <p className="py-6 text-center text-[13px] text-[var(--text-muted)]">Откройте смену, чтобы принимать заявки.</p>
          )}
        </Card>

        {/* team on shift */}
        <Card>
          <div className="mb-3 text-[13.5px] font-semibold">Команда на смене · {me?.on_shift_count ?? 0}</div>
          <div className="flex flex-col gap-2">
            {(me?.team_on_shift ?? []).length === 0 ? (
              <p className="text-[12.5px] text-[var(--text-muted)]">Никого нет на смене.</p>
            ) : (
              me?.team_on_shift.map((t) => (
                <div key={t.id} className="flex items-center gap-2.5">
                  <span className="size-2 rounded-full bg-[var(--green)] shadow-[0_0_0_3px_var(--green-bg)]" />
                  <div className="min-w-0 flex-1">
                    <div className="truncate text-[13px]">{t.display_name || t.username}</div>
                    <div className="truncate text-[11px] text-[var(--blue)]">
                      {(t.operator_roles ?? ["client"]).map((role) => `${roleLabel(role)} · ${gradeLabel(t.role_grades?.[role])}`).join(" · ")}
                    </div>
                    <div className="text-[11px] text-[var(--text-muted)]">
                      В работе: {Number(t.workload ?? 0)} · обмены {Number(t.orders_in_progress ?? 0)} · выводы {Number(t.withdrawals_in_progress ?? 0)}
                    </div>
                  </div>
                </div>
              ))
            )}
          </div>
        </Card>
      </div>

      {shiftModal && (
        <Modal
          open
          title={shiftModal === "start" ? "Открытие смены" : "Закрытие смены"}
          onClose={() => setShiftModal(null)}
          footer={
            <>
              <Button variant="ghost" onClick={() => setShiftModal(null)}>
                Отмена
              </Button>
              <Button variant={shiftModal === "end" ? "danger" : "primary"} disabled={busy} onClick={submitShift}>
                {shiftModal === "start" ? "Открыть смену" : "Закрыть смену"}
              </Button>
            </>
          }
        >
          <div className="flex flex-col gap-3">
            <p className="text-[12.5px] text-[var(--text-muted)]">Укажите остатки по криптокошелькам на {shiftModal === "start" ? "начало" : "конец"} смены (0 допустимо).</p>
            <div className="grid grid-cols-2 gap-3">
              {SHIFT_COINS.map((c) => (
                <Field key={c} label={c.toUpperCase()}>
                  <Input inputMode="decimal" value={bal[c]} onChange={(e) => setBal((b) => ({ ...b, [c]: e.target.value }))} placeholder="0" className="font-mono" />
                </Field>
              ))}
            </div>
            {shiftModal === "end" && (
              <Field label="Заметка (необязательно)">
                <Input value={note} onChange={(e) => setNote(e.target.value)} />
              </Field>
            )}
          </div>
        </Modal>
      )}
    </>
  );
}

const SWAP_CHECK_LABELS: Record<string, string> = {
  signer: "Кошелёк на связи",
  live: "Боевой режим",
  node: "Нода",
  balance: "Баланс",
  limit_per_payout: "Лимит на отправку",
  limit_operator_day: "Лимит оператора за день",
  limit_wallet_day: "Лимит кошелька за день",
};

const FEE_CURRENCIES = ["usdt", "btc", "ltc", "trx", "rub"] as const;

function HotWalletCard({ data, onSent }: { data: HotWalletView; onSent: () => void }) {
  const coins = Array.isArray(data.coins) ? data.coins : [];
  const tone = data.available !== true ? "default" : data.below_floor ? "yellow" : "green";
  const status = data.available !== true ? "Нет данных" : data.below_floor ? "Ниже порога" : "В норме";
  const [sendCoin, setSendCoin] = useState<"btc" | "ltc">("ltc");
  const [dest, setDest] = useState("");
  const [sendAmount, setSendAmount] = useState("");
  const [feeAmount, setFeeAmount] = useState("");
  const [feeCrypto, setFeeCrypto] = useState<(typeof FEE_CURRENCIES)[number]>("usdt");
  const [busy, setBusy] = useState(false);
  const [preview, setPreview] = useState<HotWalletSwapPreview | null>(null);
  const [totp, setTotp] = useState("");
  const [lastTx, setLastTx] = useState("");

  const swapBody = {
    coin: sendCoin,
    address: dest.trim(),
    crypto_amount: sendAmount.trim().replace(",", "."),
    fee_crypto: feeCrypto,
    fee_amount: feeAmount.trim().replace(",", "."),
  };
  const canPreview = Boolean(swapBody.address && swapBody.crypto_amount && swapBody.fee_amount);

  function closePreview() {
    setPreview(null);
    setTotp("");
  }

  async function runPreview() {
    setBusy(true);
    try {
      const next = await previewHotWalletSwap(swapBody);
      setTotp("");
      setPreview(next);
    } catch (e) {
      toast.error(e instanceof PanelApiError ? e.message : "Не удалось проверить отправку");
    } finally {
      setBusy(false);
    }
  }

  async function runSend() {
    const token = preview?.preview_token;
    if (!token || preview?.ok !== true) return;
    setBusy(true);
    try {
      const sent = await confirmHotWalletSwap({ ...swapBody, preview_token: token, totp_code: totp.trim() });
      const feeRub = fmtMoney(Number(sent.fee_amount_rub ?? preview.fee_amount_rub ?? 0));
      setLastTx(sent.txid);
      closePreview();
      setDest("");
      setSendAmount("");
      setFeeAmount("");
      toast.success(`Отправлено. tx ${sent.txid}. Комиссия свапа ${feeRub} ₽`);
      onSent();
    } catch (e) {
      toast.error(e instanceof PanelApiError ? e.message : "Отправка не прошла");
    } finally {
      setBusy(false);
    }
  }

  return (
    <Card>
      <div className="mb-3 flex items-center justify-between gap-2">
        <div>
          <div className="text-[13.5px] font-semibold">Горячий кошелёк</div>
          <div className="mt-0.5 text-[11px] text-[var(--text-muted)]">BTC и LTC проекта · пополнить по адресу</div>
        </div>
        <Badge tone={tone}>{status}</Badge>
      </div>
      {data.floor_phrase ? <p className="mb-3 text-[12.5px] text-[var(--text-secondary)]">{String(data.floor_phrase)}</p> : null}
      <div className="grid grid-cols-2 gap-3 max-[720px]:grid-cols-1">
        {coins.map((coin) => {
          const name = String(coin.coin ?? "").toUpperCase();
          const address = coin.deposit_address ? String(coin.deposit_address) : "";
          return (
            <div key={name || "coin"} className="flex flex-col gap-2 rounded-[var(--radius)] border border-[var(--border)] p-3">
              <div className="flex items-baseline justify-between gap-2">
                <span className="text-sm font-semibold">{name}</span>
                <span className="text-[12px] text-[var(--text-secondary)]">{String(coin.hours_phrase ?? "")}</span>
              </div>
              <div className="font-mono text-xl font-bold tabular-nums">{fmtCoin(coin.spendable)}</div>
              <div className="text-[12px] text-[var(--text-muted)]">≈ {fmtMoney(Number(coin.value_rub ?? 0))} ₽</div>
              {Number(coin.unconfirmed ?? 0) > 0 ? (
                <div className="text-[12px] text-[var(--yellow)]">
                  ещё {fmtCoin(coin.unconfirmed)} {name} ждёт подтверждения
                </div>
              ) : null}
              {address ? (
                <>
                  <CopyField label="Адрес пополнения" value={address} />
                  <div className="text-[12px] text-[var(--text-muted)]">
                    Свободный адрес. Старые тоже принимают, баланс общий.
                  </div>
                </>
              ) : (
                <div className="text-[12px] text-[var(--text-muted)]">Адрес пополнения появится, когда кошелёк будет на связи</div>
              )}
            </div>
          );
        })}
      </div>
      <div className="mt-4 border-t border-[var(--border)] pt-4">
        <div className="mb-3">
          <div className="text-[13.5px] font-semibold">Отправка на размен</div>
          <p className="mt-0.5 text-[12px] text-[var(--text-muted)]">
            Адрес той же монеты. Комиссия свапа записывается в расходы после отправки.
          </p>
        </div>
        <div className="grid grid-cols-2 gap-3 max-[720px]:grid-cols-1">
          <Field label="Монета">
            <Select value={sendCoin} onChange={(e) => setSendCoin(e.target.value === "btc" ? "btc" : "ltc")}>
              <option value="ltc">LTC</option>
              <option value="btc">BTC</option>
            </Select>
          </Field>
          <Field label="Сумма">
            <Input inputMode="decimal" value={sendAmount} onChange={(e) => setSendAmount(e.target.value)} placeholder="0" className="font-mono" />
          </Field>
          <Field label="Адрес получателя" hint="LTC на LTC-адрес, BTC на BTC-адрес">
            <Input value={dest} onChange={(e) => setDest(e.target.value)} placeholder={sendCoin === "btc" ? "bc1…" : "ltc1…"} className="font-mono" />
          </Field>
          <div className="grid grid-cols-[1fr_120px] gap-2">
            <Field label="Комиссия свапа">
              <Input inputMode="decimal" value={feeAmount} onChange={(e) => setFeeAmount(e.target.value)} placeholder="0" className="font-mono" />
            </Field>
            <Field label="Валюта">
              <Select value={feeCrypto} onChange={(e) => setFeeCrypto(e.target.value as (typeof FEE_CURRENCIES)[number])}>
                {FEE_CURRENCIES.map((cur) => (
                  <option key={cur} value={cur}>{cur.toUpperCase()}</option>
                ))}
              </Select>
            </Field>
          </div>
        </div>
        <div className="mt-3 flex flex-wrap items-center gap-3">
          <Button variant="primary" disabled={busy || !canPreview} onClick={() => void runPreview()}>
            Проверить
          </Button>
          {lastTx ? <span className="font-mono text-[12px] text-[var(--text-secondary)]">tx {lastTx}</span> : null}
        </div>
      </div>
      <Modal
        open={preview != null}
        title="Подтверждение отправки"
        onClose={closePreview}
        footer={
          <>
            <Button variant="ghost" onClick={closePreview} disabled={busy}>Закрыть</Button>
            {preview?.ok && preview.preview_token ? (
              <Button variant="primary" disabled={busy || totp.trim().length < 6} onClick={() => void runSend()}>
                Отправить
              </Button>
            ) : null}
          </>
        }
      >
        {preview ? (
          <div className="flex flex-col gap-3">
            <div className="grid grid-cols-2 gap-3">
              <ShiftStat label="Отправка" value={`${fmtCoin(preview.crypto_amount)} ${String(preview.coin ?? "").toUpperCase()}`} />
              <ShiftStat label="В рублях" value={`${fmtMoney(Number(preview.amount_rub ?? 0))} ₽`} />
              <ShiftStat label="Комиссия" value={`${fmtCoin(preview.fee_amount)} ${String(preview.fee_crypto ?? "").toUpperCase()}`} />
              <ShiftStat label="Комиссия, ₽" value={`${fmtMoney(Number(preview.fee_amount_rub ?? 0))} ₽`} />
            </div>
            <div className="break-all font-mono text-[12px] text-[var(--text-secondary)]">{String(preview.address ?? dest)}</div>
            <ul className="flex flex-col gap-1.5">
              {(preview.checks ?? []).map((check) => (
                <li key={check.key} className="flex items-baseline justify-between gap-3 text-[12.5px]">
                  <span className={check.ok ? "text-[var(--text-secondary)]" : "text-[var(--red)]"}>
                    {SWAP_CHECK_LABELS[check.key] ?? check.key}
                  </span>
                  <span className="text-right text-[var(--text-muted)]">{check.ok ? "ок" : check.detail || "не прошла"}</span>
                </li>
              ))}
            </ul>
            {preview.ok && preview.preview_token ? (
              <Field label="Код 2FA" hint="Окно действует 2 минуты">
                <Input inputMode="numeric" autoComplete="one-time-code" value={totp} onChange={(e) => setTotp(e.target.value)} placeholder="000000" className="font-mono" />
              </Field>
            ) : (
              <p className="text-[12.5px] text-[var(--text-secondary)]">Отправка закрыта, пока проверки не пройдут.</p>
            )}
          </div>
        ) : null}
      </Modal>
    </Card>
  );
}

function ShiftStat({ label, value }: { label: string; value: string }) {
  return (
    <div className="min-w-0 rounded-[var(--radius)] bg-[var(--bg-elevated)] p-2.5">
      <div className="text-[10px] uppercase tracking-wide text-[var(--text-muted)]">{label}</div>
      <div className="mt-1 font-mono text-[14px] font-semibold tabular-nums">{value}</div>
    </div>
  );
}
