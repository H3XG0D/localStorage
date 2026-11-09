import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { motion } from "framer-motion";
import {
  AlertTriangle,
  CheckCircle2,
  Clock3,
  Copy,
  FileUp,
  Loader2,
  MessageSquare,
  ShieldCheck,
  XCircle,
} from "lucide-react";
import { useParams } from "react-router-dom";
import { toast } from "sonner";
import { PublicHeader } from "@/components/PublicHeader";
import { WalletConfirmCard } from "@/components/WalletConfirmNotice";
import { ReviewBonusCard } from "@/components/ReviewBonusCard";
import { OrderChat } from "@/components/OrderChat";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { ApiError } from "@/lib/api";
import {
  ACTIVE_STATUSES,
  STATUS_LABEL,
  cancelOrder,
  confirmPaid,
  confirmPayoutReceipt,
  getOrder,
  parseCryptoSymbol,
  uploadReceipt,
  type Order as OrderT,
} from "@/lib/orders";
import { useSession } from "@/lib/session";
import { useLiveEvents } from "@/lib/useLiveEvents";
import { normalizeBillFields } from "@/lib/exchangerDeal";
import { formatCrypto, formatMoney } from "@/lib/utils";

const POLL_MS = 8000;
const POLL_SLOW_MS = 30000; // live SSE connected → status poll is just a safety net

function useCountdown(expiresAt: string | null): string | null {
  const [, tick] = useState(0);
  useEffect(() => {
    const t = window.setInterval(() => tick((n) => n + 1), 1000);
    return () => window.clearInterval(t);
  }, []);
  if (!expiresAt) return null;
  const diff = new Date(expiresAt).getTime() - Date.now();
  if (diff <= 0) return "00:00";
  const total = Math.floor(diff / 1000);
  const h = Math.floor(total / 3600);
  const m = Math.floor((total % 3600) / 60);
  const s = total % 60;
  const pad = (n: number) => String(n).padStart(2, "0");
  return h > 0 ? `${pad(h)}:${pad(m)}:${pad(s)}` : `${pad(m)}:${pad(s)}`;
}

function statusTone(status: string): "muted" | "positive" | "warning" | "destructive" {
  if (["COMPLETED", "PAID"].includes(status)) return "positive";
  if (["FAILED", "CANCELED", "EXPIRED", "DISPUTE"].includes(status)) return "destructive";
  if (["AWAITING_CHECK", "PENDING", "OPERATOR_PENDING"].includes(status)) return "warning";
  return "muted";
}

function CopyRow({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-center justify-between gap-3 rounded-lg border border-border bg-muted/30 p-3">
      <div className="min-w-0">
        <p className="text-xs text-muted-foreground">{label}</p>
        <p className="truncate font-mono text-sm">{value}</p>
      </div>
      <Button
        variant="ghost"
        size="icon"
        aria-label="Скопировать"
        onClick={() =>
          navigator.clipboard?.writeText(value).then(
            () => toast.success("Скопировано"),
            () => toast.error("Не удалось скопировать"),
          )
        }
      >
        <Copy className="size-4" />
      </Button>
    </div>
  );
}

export function Order() {
  const { orderId } = useParams();
  const { isAuthed } = useSession();
  const [order, setOrder] = useState<OrderT | null>(null);
  const [loading, setLoading] = useState(true);
  const [notFound, setNotFound] = useState(false);
  const [busy, setBusy] = useState(false);
  const [showChat, setShowChat] = useState(false);
  const receiptInput = useRef<HTMLInputElement>(null);
  const requisitesCountdown = useCountdown(order?.expires_at ?? null);
  const merchantCountdown = useCountdown(order?.merchant_expires_at ?? null);

  const isBuy = order?.direction === "buy";
  const isOperator = order?.payment?.type === "operator";
  const isDeposit = order?.payment?.type === "deposit" && Boolean(order?.deposit_wallet);
  const active = order ? ACTIVE_STATUSES.includes(order.status) : false;
  const receiptRequestedAfterRecheck = order?.required_receipt_type === 3;
  const requisitesClosed = Boolean(order?.requisites_closed) || Boolean(
    order?.merchant_expires_at && requisitesCountdown === "00:00" && !receiptRequestedAfterRecheck,
  );
  const payfastBillFields = useMemo(
    () => normalizeBillFields(order?.payment?.type === "buy" ? order.payment.bill : null, order?.sub_token),
    [order?.payment, order?.sub_token],
  );
  const crypto = useMemo(() => (order ? parseCryptoSymbol(order.crypto) : { base: "" }), [order]);

  const load = useCallback(() => {
    if (!orderId) return;
    getOrder(orderId)
      .then((o) => {
        setOrder(o);
        setLoading(false);
      })
      .catch((e) => {
        setLoading(false);
        if (e instanceof ApiError && e.status === 404) setNotFound(true);
      });
  }, [orderId]);

  // Live status: refetch the moment the server signals a status change.
  const { live } = useLiveEvents(orderId, (e) => {
    if (e.type === "status" || e.type === "event") load();
  });

  useEffect(() => {
    if (!orderId) return;
    let alive = true;
    const tick = () => alive && load();
    tick();
    const t = window.setInterval(tick, live ? POLL_SLOW_MS : POLL_MS);
    return () => {
      alive = false;
      window.clearInterval(t);
    };
  }, [orderId, live, load]);

  async function onConfirmPaid() {
    if (!orderId) return;
    setBusy(true);
    try {
      await confirmPaid(orderId);
      toast.success("Отмечено как оплачено");
      const o = await getOrder(orderId);
      setOrder(o);
    } catch (e) {
      toast.error(e instanceof ApiError ? e.message : "Не удалось подтвердить");
    } finally {
      setBusy(false);
    }
  }

  async function onCancel() {
    if (!orderId) return;
    setBusy(true);
    try {
      await cancelOrder(orderId);
      toast.info("Заявка отменена");
      const o = await getOrder(orderId);
      setOrder(o);
    } catch (e) {
      toast.error(e instanceof ApiError ? e.message : "Не удалось отменить");
    } finally {
      setBusy(false);
    }
  }

  async function onReceipt(file: File) {
    if (!orderId) return;
    setBusy(true);
    try {
      await uploadReceipt(orderId, file);
      toast.success("Чек загружен");
      const o = await getOrder(orderId);
      setOrder(o);
    } catch (e) {
      toast.error(e instanceof ApiError ? e.message : "Не удалось загрузить чек");
    } finally {
      setBusy(false);
    }
  }

  const receiptAccept = order?.required_receipt_type === 3 ? "video/*" : "application/pdf";
  const receiptHint = order?.required_receipt_type === 3 ? "видео (MP4, MOV, WebM…)" : "PDF-файл";

  return (
    <div className="min-h-screen bg-background">
      <PublicHeader back={{ to: "/exchange", label: "Новый обмен" }} />
      <main className="mx-auto max-w-3xl px-4 py-10 sm:px-6 sm:py-14 lg:px-8">
        {loading ? (
          <div className="flex justify-center py-24">
            <Loader2 className="size-6 animate-spin text-muted-foreground" />
          </div>
        ) : notFound || !order ? (
          <Card>
            <CardHeader>
              <CardTitle>Заявка не найдена</CardTitle>
              <CardDescription>Проверьте ссылку или создайте новую заявку.</CardDescription>
            </CardHeader>
            <CardContent>
              <Button asChild>
                <a href="/exchange">Создать заявку</a>
              </Button>
            </CardContent>
          </Card>
        ) : (
          <motion.div initial={{ opacity: 0, y: 16 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.4 }} className="space-y-4">
            {order.wallet_confirm ? (
              <WalletConfirmCard
                orderId={order.order_id}
                confirm={order.wallet_confirm}
                cryptoAmount={order.crypto_amount}
                fiatAmount={order.fiat_amount}
                onResolved={load}
              />
            ) : null}
            {/* header */}
            <div className="flex flex-wrap items-center justify-between gap-3">
              <div>
                <p className="text-xs uppercase tracking-[.16em] text-muted-foreground">Заявка</p>
                <h1 className="font-mono text-2xl font-bold tracking-tight">#{order.order_id}</h1>
              </div>
              <Badge variant={statusTone(order.status)}>{order.status_label || STATUS_LABEL[order.status] || order.status}</Badge>
            </div>

            {/* summary */}
            <Card>
              <CardContent className="grid gap-4 p-5 sm:grid-cols-3">
                <div>
                  <p className="text-xs text-muted-foreground">Направление</p>
                  <p className="font-medium">{isBuy ? "Покупка" : "Продажа"} {crypto.base}{crypto.network ? ` · ${crypto.network}` : ""}</p>
                </div>
                <div>
                  <p className="text-xs text-muted-foreground">{receiptRequestedAfterRecheck ? "Проверка" : "Сумма"}</p>
                  <p className="font-mono font-medium">
                    {receiptRequestedAfterRecheck ? "Видео подтверждения" : `${formatMoney(order.fiat_amount)} ₽`}
                  </p>
                </div>
                <div>
                  <p className="text-xs text-muted-foreground">Криптовалюта</p>
                  <p className="font-mono font-medium">{formatCrypto(order.crypto_amount)} {crypto.base}</p>
                </div>
              </CardContent>
            </Card>

            {/* operator (sell / fallback) */}
            {isOperator && (
              <Card>
                <CardHeader>
                  <div className="flex items-center gap-2">
                    <ShieldCheck className="size-5" />
                    <CardTitle>Заявка у оператора</CardTitle>
                  </div>
                </CardHeader>
                <CardContent>
                  <p className="text-sm leading-6 text-muted-foreground">
                    {order.payment?.type === "operator" && order.payment.message
                      ? order.payment.message
                      : order.operator_message ||
                        `Напишите оператору с номером #${order.order_id} — он выдаст реквизиты и завершит обмен.`}
                  </p>
                </CardContent>
              </Card>
            )}

            {/* sell: постоянный адрес приёма крипты */}
            {isDeposit && active && !order.crypto_confirmed && !order.payout_receipt_available && (
              <Card>
                <CardHeader>
                  <CardTitle>Отправьте крипту</CardTitle>
                  <CardDescription>
                    {order.payment?.type === "deposit" && order.payment.message
                      ? order.payment.message
                      : "Переведите точную сумму на адрес ниже, затем нажмите «Я оплатил»."}
                  </CardDescription>
                </CardHeader>
                <CardContent className="space-y-3">
                  <CopyRow label={`Адрес для ${crypto.base}`} value={order.deposit_wallet ?? ""} />
                  <CopyRow label="Сумма к отправке" value={`${formatCrypto(order.crypto_amount)} ${crypto.base}`} />
                  <CopyRow label="Ваши реквизиты для рублей" value={order.requisites} />

                  {order.status === "OPERATOR_PENDING" || order.status === "CREATED" ? (
                    <Button className="w-full" onClick={onConfirmPaid} disabled={busy}>
                      {busy ? <Loader2 className="size-4 animate-spin" data-icon="inline-start" /> : <CheckCircle2 data-icon="inline-start" />}
                      Я оплатил
                    </Button>
                  ) : (
                    <p className="text-sm text-muted-foreground">
                      {order.crypto_confirmed
                        ? "Приход крипты подтверждён — рубли уйдут на ваши реквизиты."
                        : "Ждём подтверждения прихода крипты — после этого оператор отправит рубли."}
                    </p>
                  )}
                </CardContent>
              </Card>
            )}

            {/* buy payment details */}
            {isBuy && !isOperator && active && (
              <Card>
                {receiptRequestedAfterRecheck ? (
                  <>
                    <CardHeader>
                      <CardTitle>Требуется видео подтверждения</CardTitle>
                      <CardDescription>
                        Платёж уже передан на проверку. Запишите видео подтверждения и прикрепите его к заявке.
                      </CardDescription>
                    </CardHeader>
                    <CardContent className="space-y-3">
                      {order.status === "AWAITING_CHECK" ? (
                        <div className="space-y-2">
                          <input
                            ref={receiptInput}
                            type="file"
                            accept={receiptAccept}
                            className="hidden"
                            onChange={(e) => e.target.files?.[0] && onReceipt(e.target.files[0])}
                          />
                          <Button className="w-full" onClick={() => receiptInput.current?.click()} disabled={busy}>
                            {busy ? <Loader2 className="size-4 animate-spin" data-icon="inline-start" /> : <FileUp data-icon="inline-start" />}
                            Загрузить видео ({receiptHint})
                          </Button>
                          <p className="text-center text-xs text-muted-foreground">
                            Прикрепите видео подтверждения: {receiptHint}.
                          </p>
                        </div>
                      ) : (
                        <p className="text-sm text-muted-foreground">Видео отправлено и ожидает проверки.</p>
                      )}
                    </CardContent>
                  </>
                ) : (
                  <>
                    <CardHeader>
                      <div className="flex items-center justify-between gap-3">
                        <CardTitle>{requisitesClosed ? "Реквизиты закрыты" : "Оплата заявки"}</CardTitle>
                        {(requisitesClosed ? merchantCountdown : requisitesCountdown) && (
                          <span className="inline-flex items-center gap-1 font-mono text-sm text-muted-foreground">
                            <Clock3 className="size-4" />
                            {requisitesClosed ? merchantCountdown : requisitesCountdown}
                          </span>
                        )}
                      </div>
                      <CardDescription>
                        {requisitesClosed
                          ? merchantCountdown === "00:00"
                            ? "Время оплаты истекло."
                            : "Если вы уже сделали перевод, обратитесь к оператору до окончания срока PayFast."
                          : order.payment?.type === "buy" && order.payment.rail === "requisite"
                            ? "Оплатите точную сумму на карту ниже, затем нажмите «Я оплатил» и приложите чек."
                            : "Оплатите точную сумму по реквизитам ниже."}
                      </CardDescription>
                    </CardHeader>
                    <CardContent className="space-y-3">
                      {requisitesClosed ? (
                        <div className="rounded-lg border border-destructive/30 bg-destructive/5 p-4 text-sm leading-6">
                          <p className="font-medium">Реквизиты закрыты.</p>
                          {merchantCountdown !== "00:00" ? (
                            <p className="mt-1 text-muted-foreground">
                              Если вы уже сделали перевод, у вас есть ещё {merchantCountdown}, чтобы написать оператору. Иначе деньги могут быть утеряны.
                            </p>
                          ) : (
                            <p className="mt-1 text-muted-foreground">Напишите оператору для уточнения статуса перевода.</p>
                          )}
                        </div>
                      ) : (
                        <>
                          <CopyRow label="Сумма к оплате" value={`${formatMoney(order.fiat_amount)} ₽`} />
                          {payfastBillFields.map((field) => (
                            <CopyRow key={`${field.label}:${field.value}`} label={field.label} value={field.value} />
                          ))}
                          {order.deposit_wallet && <CopyRow label="Реквизиты для оплаты" value={order.deposit_wallet} />}
                          <CopyRow label="Ваш кошелёк для зачисления" value={order.requisites} />

                          <div className="flex items-start gap-2 rounded-lg border border-destructive/30 bg-destructive/5 p-3 text-sm leading-6">
                            <AlertTriangle className="mt-0.5 size-4 shrink-0 text-destructive" />
                            <p>
                              <span className="font-medium">Не оплачивайте с МТС Банка и Уралсиба</span>
                              {" — такие переводы не принимаем."}
                            </p>
                          </div>

                          {order.status === "CREATED" && (
                            <Button className="w-full" onClick={onConfirmPaid} disabled={busy}>
                              {busy ? <Loader2 className="size-4 animate-spin" data-icon="inline-start" /> : <CheckCircle2 data-icon="inline-start" />}
                              Я оплатил
                            </Button>
                          )}

                          {order.status === "AWAITING_CHECK" && (
                            <div className="space-y-2">
                              <input
                                ref={receiptInput}
                                type="file"
                                accept={receiptAccept}
                                className="hidden"
                                onChange={(e) => e.target.files?.[0] && onReceipt(e.target.files[0])}
                              />
                              <Button className="w-full" onClick={() => receiptInput.current?.click()} disabled={busy}>
                                {busy ? <Loader2 className="size-4 animate-spin" data-icon="inline-start" /> : <FileUp data-icon="inline-start" />}
                                Загрузить чек ({receiptHint})
                              </Button>
                              <p className="text-center text-xs text-muted-foreground">Прикрепите подтверждение оплаты — {receiptHint}.</p>
                            </div>
                          )}
                        </>
                      )}
                    </CardContent>
                  </>
                )}
              </Card>
            )}

            {isDeposit && active && order.crypto_confirmed && !order.payout_receipt_available && (
              <Card>
                <CardHeader>
                  <CardTitle>Ждём выплату</CardTitle>
                  <CardDescription>
                    Приход крипты подтверждён. Рубли уйдут на ваши реквизиты — здесь появится чек.
                  </CardDescription>
                </CardHeader>
              </Card>
            )}

            {/* terminal / payout receipt */}
            {(order.payout_receipt_available || ["COMPLETED", "PAID"].includes(order.status)) && (
              <Card>
                <CardContent className="flex flex-wrap items-center gap-3 p-5">
                  <CheckCircle2 className="size-6 text-foreground" />
                  <div className="flex-1">
                    <p className="font-medium">
                      {order.status === "PAID" || order.payout_receipt_confirmed
                        ? "Выплачено"
                        : "Выплата отправлена"}
                    </p>
                    <p className="text-sm text-muted-foreground">
                      {order.status === "PAID" || order.payout_receipt_confirmed
                        ? isBuy
                          ? "Крипта ушла на указанный кошелёк."
                          : "Средства отправлены по указанным реквизитам."
                        : "Проверьте чек и подтвердите, когда деньги придут."}
                    </p>
                  </div>
                  {isBuy && order.payout_explorer_url && (
                    <Button variant="outline" asChild>
                      <a href={order.payout_explorer_url} target="_blank" rel="noreferrer">
                        Открыть транзакцию
                      </a>
                    </Button>
                  )}
                  {order.payout_receipt_available && (
                    <div className="flex flex-wrap items-center gap-2">
                      <Button variant="outline" asChild>
                        <a href={`/api/public/orders/${order.order_id}/payout-receipt`} target="_blank" rel="noreferrer">
                          <FileUp data-icon="inline-start" />
                          Чек о выплате
                        </a>
                      </Button>
                      {order.payout_receipt_confirmed ? (
                        <p className="text-sm text-muted-foreground">Получение подтверждено</p>
                      ) : (
                        <Button
                          disabled={busy}
                          onClick={async () => {
                            if (!orderId) return;
                            setBusy(true);
                            try {
                              await confirmPayoutReceipt(orderId);
                              toast.success("Получение подтверждено");
                              const o = await getOrder(orderId);
                              setOrder(o);
                            } catch (e) {
                              toast.error(e instanceof ApiError ? e.message : "Не удалось подтвердить");
                            } finally {
                              setBusy(false);
                            }
                          }}
                        >
                          Подтвердить получение
                        </Button>
                      )}
                    </div>
                  )}
                </CardContent>
              </Card>
            )}
            {["FAILED", "EXPIRED"].includes(order.status) && (
              <Card>
                <CardContent className="flex items-center gap-3 p-5">
                  <AlertTriangle className="size-6 text-destructive" />
                  <div>
                    <p className="font-medium">Заявка {STATUS_LABEL[order.status]?.toLowerCase()}</p>
                    <p className="text-sm text-muted-foreground">Создайте новую заявку или свяжитесь с оператором.</p>
                  </div>
                </CardContent>
              </Card>
            )}

            {isAuthed && isBuy && ["PAID", "COMPLETED"].includes(order.status) && <ReviewBonusCard />}

            {/* actions */}
            <div className="flex flex-wrap gap-3">
              <Button variant="outline" onClick={() => setShowChat((v) => !v)}>
                <MessageSquare data-icon="inline-start" />
                {showChat ? "Скрыть чат" : "Открыть чат с оператором"}
              </Button>
              {active && !requisitesClosed && !receiptRequestedAfterRecheck && (
                <Button variant="ghost" onClick={onCancel} disabled={busy} className="text-destructive hover:text-destructive">
                  <XCircle data-icon="inline-start" />
                  Отменить заявку
                </Button>
              )}
            </div>

            {showChat && <OrderChat orderId={order.order_id} />}
          </motion.div>
        )}
      </main>
    </div>
  );
}
