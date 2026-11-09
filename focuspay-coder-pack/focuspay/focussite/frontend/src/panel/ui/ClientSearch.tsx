// Debounced client autocomplete. Type → suggestions appear → pick one.
// Backend accepts Telegram ID or @username (min 1 char).
import { useEffect, useRef, useState } from "react";
import { Loader2, Search } from "lucide-react";
import { lookupOrder, searchUsers, type OrderRow } from "@/panel/lib/operatorApi";
import { Input, cx } from "@/panel/ui/primitives";

export type ClientHit = Record<string, unknown> & { user_id?: number; id?: number; username?: string; first_name?: string };

export function ClientSearch({
  onPick,
  onOrderPick,
  placeholder = "Telegram ID или @username",
  autoFocus,
  lookupOrders = false,
}: {
  onPick: (u: ClientHit) => void;
  onOrderPick?: (order: OrderRow) => void;
  placeholder?: string;
  autoFocus?: boolean;
  lookupOrders?: boolean;
}) {
  const [q, setQ] = useState("");
  const [hits, setHits] = useState<ClientHit[]>([]);
  const [orderHit, setOrderHit] = useState<OrderRow | null>(null);
  const [loading, setLoading] = useState(false);
  const [open, setOpen] = useState(false);
  const [activeIndex, setActiveIndex] = useState(0);
  const boxRef = useRef<HTMLDivElement>(null);

  // debounce
  useEffect(() => {
    const term = q.trim();
    if (term.length < 1) {
      setHits([]);
      setOrderHit(null);
      setOpen(false);
      return;
    }
    let alive = true;
    const normalizedOrder = term.replace(/^#/, "").trim();
    const orderOnly = lookupOrders && (/^#/.test(term) || /^OP/i.test(normalizedOrder));
    const maybeOrder = lookupOrders && normalizedOrder.length >= 4 && (orderOnly || /^\d{8}$/.test(normalizedOrder));
    const searchClient = !orderOnly;
    setLoading(true);
    setHits([]);
    setOrderHit(null);
    setOpen(false);
    const t = window.setTimeout(() => {
      const clientTask = searchClient ? searchUsers(term, 10) : Promise.resolve({ users: [] });
      const orderTask = maybeOrder ? lookupOrder(normalizedOrder) : Promise.resolve(null);
      Promise.allSettled([clientTask, orderTask]).then(([clientResult, orderResult]) => {
        if (!alive) return;
        const users = clientResult.status === "fulfilled" ? (clientResult.value.users as ClientHit[]) || [] : [];
        const order = orderResult.status === "fulfilled" && orderResult.value ? orderResult.value.order : null;
        setHits(users);
        setOrderHit(order as OrderRow | null);
        setActiveIndex(0);
        setOpen(users.length > 0 || !!order);
      }).finally(() => alive && setLoading(false));
    }, 300);
    return () => {
      alive = false;
      window.clearTimeout(t);
    };
  }, [q, lookupOrders]);

  // close on outside click
  useEffect(() => {
    function onDoc(e: MouseEvent) {
      if (boxRef.current && !boxRef.current.contains(e.target as Node)) setOpen(false);
    }
    document.addEventListener("mousedown", onDoc);
    return () => document.removeEventListener("mousedown", onDoc);
  }, []);

  const totalHits = hits.length + (orderHit ? 1 : 0);

  function choose(index: number) {
    if (index < hits.length) {
      onPick(hits[index]);
    } else if (orderHit && onOrderPick) {
      onOrderPick(orderHit);
    } else {
      return;
    }
    setOpen(false);
    setQ("");
    setHits([]);
    setOrderHit(null);
  }

  return (
    <div ref={boxRef} className="relative">
      <div className="relative">
        <Search className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-[var(--text-muted)]" />
        <Input
          value={q}
          onChange={(e) => setQ(e.target.value)}
          onFocus={() => totalHits > 0 && setOpen(true)}
          onKeyDown={(e) => {
            if (e.key === "Escape") {
              setOpen(false);
            } else if (e.key === "ArrowDown" && totalHits > 0) {
              e.preventDefault();
              setActiveIndex((i) => (i + 1) % totalHits);
            } else if (e.key === "ArrowUp" && totalHits > 0) {
              e.preventDefault();
              setActiveIndex((i) => (i - 1 + totalHits) % totalHits);
            } else if (e.key === "Enter" && open && totalHits > 0) {
              e.preventDefault();
              choose(activeIndex);
            }
          }}
          placeholder={placeholder}
          autoFocus={autoFocus}
          className="pl-9"
        />
        {loading && <Loader2 className="absolute right-3 top-1/2 size-4 -translate-y-1/2 animate-spin text-[var(--text-muted)]" />}
      </div>
      {open && totalHits > 0 && (
        <div className="absolute z-20 mt-1 max-h-72 w-full overflow-y-auto rounded-[var(--radius)] border border-[var(--border-strong)] bg-[var(--bg-surface)] shadow-[var(--shadow-lg)]">
          {hits.map((u) => {
            const id = u.user_id ?? u.id;
            const index = hits.indexOf(u);
            return (
              <button
                key={String(id)}
                onClick={() => choose(index)}
                className={cx("flex w-full items-center gap-3 px-3 py-2.5 text-left transition-colors hover:bg-[var(--bg-elevated)]", activeIndex === index && "bg-[var(--bg-elevated)]")}
              >
                <div className="flex size-8 shrink-0 items-center justify-center rounded-full bg-[var(--bg-overlay)] text-[11px] font-bold text-[var(--text-secondary)]">
                  {String(u.first_name || u.username || id || "?").slice(0, 2).toUpperCase()}
                </div>
                <div className="min-w-0">
                  <div className="truncate text-[13px]">{u.first_name || (u.username ? `@${u.username}` : `ID ${id}`)}</div>
                  <div className="truncate text-[11px] text-[var(--text-muted)]">ID {String(id)}{u.username ? ` · @${u.username}` : ""}</div>
                </div>
              </button>
            );
          })}
          {orderHit && onOrderPick && (
            <button
              key={`order-${orderHit.order_id}`}
              onClick={() => choose(hits.length)}
              className={cx("flex w-full items-center gap-3 border-t border-[var(--border)] px-3 py-2.5 text-left transition-colors hover:bg-[var(--bg-elevated)]", activeIndex === hits.length && "bg-[var(--bg-elevated)]")}
            >
              <div className="flex size-8 shrink-0 items-center justify-center rounded-full bg-[var(--blue-bg)] text-[11px] font-bold text-[var(--blue)]">#</div>
              <div className="min-w-0">
                <div className="truncate font-mono text-[13px]">#{orderHit.order_id}</div>
                <div className="truncate text-[11px] text-[var(--text-muted)]">
                  {orderHit.direction === "buy" ? "Покупка" : "Продажа"} {String(orderHit.crypto ?? "").toUpperCase()} · {String(orderHit.status_label ?? orderHit.status ?? "")}
                </div>
              </div>
            </button>
          )}
        </div>
      )}
    </div>
  );
}
