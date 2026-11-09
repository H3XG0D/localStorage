import { useEffect, useState } from "react";
import { Link, useLocation } from "react-router-dom";
import { toast } from "sonner";
import { ApiError } from "@/lib/api";
import {
  getActiveOrder,
  submitWalletConfirm,
  type PayoutSent,
  type WalletConfirm,
} from "@/lib/orders";
import { useSession } from "@/lib/session";

function rub(value: number | null | undefined): string {
  if (value == null || Number.isNaN(Number(value))) return "";
  return `${Math.round(Number(value)).toLocaleString("ru-RU")} ₽`;
}

function coinAmount(value: number | null | undefined): string {
  if (value == null || Number.isNaN(Number(value))) return "";
  return Number(value).toFixed(8).replace(/0+$/, "").replace(/\.$/, "");
}

const DETAIL: Record<string, string> = {
  order_not_found: "Заявка не найдена",
  not_buy: "Это не покупка",
  wrong_status: "Заявка ещё не на выплате",
  unsupported_coin: "Для этой монеты подтверждение не нужно",
  not_waiting: "Подтверждение уже не требуется",
  bad_action: "Не удалось выполнить действие",
};

function rememberPaid(orderId: string) {
  const key = `fp-payout-sent:${orderId}`;
  try {
    if (window.sessionStorage.getItem(key)) return;
    window.sessionStorage.setItem(key, "1");
  } catch {
    return;
  }
  toast.success("Выплачено", { description: `Заявка #${orderId}` });
}

function paidDismissed(orderId: string): boolean {
  try {
    return window.sessionStorage.getItem(`fp-payout-sent-hide:${orderId}`) === "1";
  } catch {
    return false;
  }
}

export function PayoutSentCard({
  sent,
  onDismiss,
}: {
  sent: PayoutSent;
  onDismiss: () => void;
}) {
  const amount = [coinAmount(sent.crypto_amount), sent.coin].filter(Boolean).join(" ");

  useEffect(() => {
    rememberPaid(sent.order_id);
  }, [sent.order_id]);

  return (
    <section className="rounded-2xl border border-border bg-card p-4 text-card-foreground shadow-lg" aria-live="assertive">
      <p className="text-xs font-semibold uppercase tracking-[.14em] text-muted-foreground">Заявка #{sent.order_id}</p>
      <h2 className="mt-1 text-base font-semibold">Выплачено</h2>
      {amount ? <p className="mt-1 font-mono text-sm">{amount}</p> : null}
      {sent.address ? <p className="mt-2 break-all font-mono text-xs text-muted-foreground">{sent.address}</p> : null}
      <div className="mt-3 flex flex-col gap-2">
        {sent.explorer_url ? (
          <a
            href={sent.explorer_url}
            target="_blank"
            rel="noreferrer"
            className="flex h-11 items-center justify-center rounded-xl border border-border text-sm font-semibold"
          >
            Открыть транзакцию
          </a>
        ) : null}
        <button
          type="button"
          onClick={onDismiss}
          className="h-11 rounded-xl bg-primary text-sm font-semibold text-primary-foreground"
        >
          Понятно
        </button>
      </div>
    </section>
  );
}

function rememberAsk(orderId: string) {
  const key = `fp-wallet-ask:${orderId}`;
  try {
    if (window.sessionStorage.getItem(key)) return;
    window.sessionStorage.setItem(key, "1");
  } catch {
    return;
  }
  toast("Уточните кошелёк перед отправкой", {
    description: `Заявка #${orderId}`,
  });
}

export function WalletConfirmCard({
  orderId,
  confirm,
  cryptoAmount,
  fiatAmount,
  onResolved,
}: {
  orderId: string;
  confirm: WalletConfirm;
  cryptoAmount?: number | null;
  fiatAmount?: number | null;
  onResolved?: () => void;
}) {
  const [other, setOther] = useState(confirm.status === "awaiting_address");
  const [address, setAddress] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const amount = [coinAmount(cryptoAmount), rub(fiatAmount)].filter(Boolean).join(" · ");

  useEffect(() => {
    setOther(confirm.status === "awaiting_address");
  }, [confirm.status, confirm.address]);

  useEffect(() => {
    rememberAsk(orderId);
  }, [orderId]);

  async function send(action: "confirm" | "replace") {
    setBusy(true);
    setError("");
    try {
      const result = await submitWalletConfirm(orderId, action, action === "replace" ? address : undefined);
      toast.success(result.detail || "Отправляем на этот адрес");
      onResolved?.();
    } catch (err) {
      const raw = err instanceof ApiError ? err.message : "";
      setError(DETAIL[raw] || raw || "Не удалось подтвердить кошелёк");
    } finally {
      setBusy(false);
    }
  }

  return (
    <section
      className="rounded-2xl border border-border bg-card p-4 text-card-foreground shadow-lg"
      aria-live="assertive"
    >
      <p className="text-xs font-semibold uppercase tracking-[.14em] text-muted-foreground">Перед отправкой</p>
      <h2 className="mt-1 text-base font-semibold">Уточните кошелёк</h2>
      <p className="mt-1 text-sm text-muted-foreground">
        Заявка #{orderId}
        {confirm.coin ? ` · ${confirm.coin}` : ""}
        {amount ? ` · ${amount}` : ""}
      </p>
      <p className="mt-3 break-all font-mono text-sm">{confirm.address}</p>
      <p className="mt-3 text-sm">Кошелёк актуален или нужна выплата на другой?</p>
      {error ? <p className="mt-2 text-sm text-destructive">{error}</p> : null}
      {other ? (
        <div className="mt-3 flex flex-col gap-2">
          <label className="text-xs text-muted-foreground" htmlFor={`wallet-next-${orderId}`}>
            Новый адрес
          </label>
          <input
            id={`wallet-next-${orderId}`}
            value={address}
            autoComplete="off"
            spellCheck={false}
            disabled={busy}
            placeholder="Адрес кошелька"
            onChange={(event) => setAddress(event.target.value)}
            className="h-11 w-full rounded-xl border border-input bg-background px-3 font-mono text-sm outline-none"
          />
          <button
            type="button"
            disabled={busy || !address.trim()}
            onClick={() => void send("replace")}
            className="h-11 rounded-xl bg-primary text-sm font-semibold text-primary-foreground disabled:opacity-50"
          >
            {busy ? "Проверяем…" : "Проверить и отправить"}
          </button>
          <button
            type="button"
            disabled={busy}
            onClick={() => {
              setOther(false);
              setError("");
            }}
            className="h-10 text-sm text-muted-foreground"
          >
            Назад
          </button>
        </div>
      ) : (
        <div className="mt-3 flex flex-col gap-2">
          <button
            type="button"
            disabled={busy}
            onClick={() => void send("confirm")}
            className="h-11 rounded-xl bg-primary text-sm font-semibold text-primary-foreground disabled:opacity-50"
          >
            {busy ? "Отправляем…" : "Кошелёк актуален"}
          </button>
          <button
            type="button"
            disabled={busy}
            onClick={() => {
              setOther(true);
              setError("");
            }}
            className="h-11 rounded-xl border border-border text-sm font-semibold"
          >
            На другой
          </button>
        </div>
      )}
    </section>
  );
}

function onOrderPage(pathname: string, surface: "site" | "miniapp" | "casino"): boolean {
  if (surface === "casino") return false;
  if (surface === "miniapp") return pathname === "/order" || pathname.startsWith("/order/");
  return pathname.startsWith("/exchange/order/");
}

export function WalletConfirmGate({ surface }: { surface: "site" | "miniapp" | "casino" }) {
  const { isAuthed, loading } = useSession();
  const location = useLocation();
  const [orderId, setOrderId] = useState("");
  const [confirm, setConfirm] = useState<WalletConfirm | null>(null);
  const [cryptoAmount, setCryptoAmount] = useState<number | null>(null);
  const [fiatAmount, setFiatAmount] = useState<number | null>(null);
  const [stamp, setStamp] = useState(0);
  const [sent, setSent] = useState<PayoutSent | null>(null);
  const hidden = onOrderPage(location.pathname, surface);

  useEffect(() => {
    if (loading || !isAuthed) return;
    let alive = true;
    const load = () => {
      getActiveOrder()
        .then((page) => {
          if (!alive) return;
          const next = page.active && page.order?.wallet_confirm ? page.order : null;
          setOrderId(next?.order_id || "");
          setConfirm(next?.wallet_confirm || null);
          setCryptoAmount(next?.crypto_amount ?? null);
          setFiatAmount(next?.fiat_amount ?? null);
          const paid = page.payout_sent;
          setSent(paid && paid.order_id && !paidDismissed(paid.order_id) ? paid : null);
        })
        .catch(() => {
          if (!alive) return;
          setConfirm(null);
        });
    };
    load();
    const id = window.setInterval(load, 5000);
    return () => {
      alive = false;
      window.clearInterval(id);
    };
  }, [loading, isAuthed, stamp]);

  const showConfirm = Boolean(confirm && orderId && !hidden);
  const showSent = Boolean(sent);
  if (!showConfirm && !showSent) return null;

  const top = surface === "site"
    ? "4.5rem"
    : "calc(8px + env(safe-area-inset-top, 0px))";

  return (
    <div className="pointer-events-none fixed inset-x-0 z-[60] flex flex-col gap-3 px-3" style={{ top }}>
      <div className="pointer-events-auto mx-auto flex w-full max-w-md flex-col gap-3">
        {showSent && sent ? (
          <PayoutSentCard
            sent={sent}
            onDismiss={() => {
              try {
                window.sessionStorage.setItem(`fp-payout-sent-hide:${sent.order_id}`, "1");
              } catch {
                /* ignore */
              }
              setSent(null);
            }}
          />
        ) : null}
        {showConfirm && confirm ? (
          <>
            <WalletConfirmCard
              orderId={orderId}
              confirm={confirm}
              cryptoAmount={cryptoAmount}
              fiatAmount={fiatAmount}
              onResolved={() => setStamp((value) => value + 1)}
            />
            {surface === "miniapp" ? (
              <Link to="/order" className="block text-center text-xs font-medium text-muted-foreground">
                Открыть заявку
              </Link>
            ) : (
              <a
                href={`/exchange/order/${orderId}`}
                className="block text-center text-xs font-medium text-muted-foreground"
              >
                Открыть заявку
              </a>
            )}
          </>
        ) : null}
      </div>
    </div>
  );
}
