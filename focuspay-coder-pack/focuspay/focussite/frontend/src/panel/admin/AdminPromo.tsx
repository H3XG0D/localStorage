import { useCallback, useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { toast } from "sonner";
import { PanelApiError } from "@/panel/lib/panelApi";
import { createExchangeDiscount, createFixedRubPromo, deletePromo, getPromos, patchPromo, quickPartner, type Dict } from "@/panel/lib/adminApi";
import { Badge, Button, Card, Field, Input, Modal, PageHeader, Table, cx, type BadgeTone, type Column } from "@/panel/ui/primitives";

type PromoGiftKind = "fixed_rub" | "exchange_discount";

function pct(v: unknown) {
  return v == null ? "—" : `${Number(v)}%`;
}
const kindTone = (k?: string): BadgeTone => (k === "fixed_rub" ? "blue" : k === "exchange_discount" ? "purple" : "default");
function kindLabel(k?: string) {
  if (k === "fixed_rub") return "На баланс";
  if (k === "exchange_discount") return "Скидка на обмен";
  if (k === "partner") return "Партнёр";
  return k || "—";
}
function activationsUsed(row: Dict) {
  return Number(row.activations_used ?? row.activations ?? 0);
}

function promoHref(row: Dict) {
  const kind = String(row.campaign_kind ?? row.kind ?? "");
  if (kind === "partner" || row.partner_username) return `/x8/partners/${row.id}`;
  return `/x8/promo/${row.id}`;
}

export function AdminPromo() {
  const navigate = useNavigate();
  const [rows, setRows] = useState<Dict[]>([]);
  const [loading, setLoading] = useState(true);
  const [createOpen, setCreateOpen] = useState(false);
  const [partnerOpen, setPartnerOpen] = useState(false);
  const [search, setSearch] = useState("");

  const load = useCallback(() => {
    setLoading(true);
    getPromos()
      .then((r) => setRows(Array.isArray(r) ? r : (r.promos || [])))
      .catch((e) => toast.error(e instanceof PanelApiError ? e.message : "Ошибка"))
      .finally(() => setLoading(false));
  }, []);

  useEffect(() => load(), [load]);

  const q = search.trim().toLowerCase();
  const filtered = q
    ? rows.filter((r) =>
        [r.code, r.name, r.campaign_kind, r.author_telegram_id, kindLabel(String(r.campaign_kind ?? r.kind ?? ""))].some((v) => String(v ?? "").toLowerCase().includes(q)),
      )
    : rows;

  async function toggle(id: number, next: boolean) {
    try {
      await patchPromo(id, { is_active: next });
      toast.success(next ? "Включено" : "Выключено");
      load();
    } catch (e) {
      toast.error(e instanceof PanelApiError ? e.message : "Ошибка");
    }
  }

  async function del(id: number) {
    if (!window.confirm("Удалить промокод?")) return;
    try {
      await deletePromo(id);
      toast.success("Удалено");
      load();
    } catch (e) {
      toast.error(e instanceof PanelApiError ? e.message : "Ошибка");
    }
  }

  const cols: Column<Dict>[] = [
    { key: "code", label: "Код", render: (r) => <span className="font-mono">{String(r.code || `#${r.id}`)}</span> },
    { key: "name", label: "Название", render: (r) => String(r.name || "—") },
    { key: "bonus", label: "Бонус", width: "120px", align: "right", render: (r) => (Number(r.client_fixed_bonus_rub) > 0 ? `${Number(r.client_fixed_bonus_rub)} ₽` : pct(r.bonus_percent)) },
    { key: "kind", label: "Тип", width: "160px", render: (r) => <Badge tone={kindTone(String(r.campaign_kind ?? r.kind))}>{kindLabel(String(r.campaign_kind ?? r.kind))}</Badge> },
    { key: "is_active", label: "Статус", width: "110px", render: (r) => <Badge tone={r.is_active ? "green" : "red"}>{r.is_active ? "активен" : "выключен"}</Badge> },
    { key: "activations", label: "Активации", width: "110px", align: "right", render: (r) => `${activationsUsed(r)} / ${r.max_activations ?? "∞"}` },
    {
      key: "arrivals",
      label: "Приходы",
      width: "100px",
      align: "right",
      render: (r) => (r.author_telegram_id ? String(r.arrivals ?? 0) : "—"),
    },
    {
      key: "actions",
      label: "",
      width: "160px",
      render: (r) => (
        <div className="flex gap-1.5">
          <Button size="sm" variant="secondary" onClick={(e) => { e.stopPropagation(); toggle(Number(r.id), !r.is_active); }}>
            {r.is_active ? "Выкл" : "Вкл"}
          </Button>
          <Button size="sm" variant="danger" onClick={(e) => { e.stopPropagation(); del(Number(r.id)); }}>
            Удалить
          </Button>
        </div>
      ),
    },
  ];

  return (
    <>
      <PageHeader
        title="Промокоды"
        subtitle="Скидка на обмен, зачисление на баланс и быстрые партнёры"
        actions={
          <>
            <Button variant="secondary" onClick={() => setPartnerOpen(true)}>Быстрый партнёр</Button>
            <Button variant="primary" onClick={() => setCreateOpen(true)}>+ Создать промо</Button>
          </>
        }
      />
      <Card>
        <div className="mb-3">
          <Input value={search} onChange={(e) => setSearch(e.target.value)} placeholder="Поиск по коду, названию или типу…" />
        </div>
        <Table columns={cols} rows={filtered} empty={loading ? "Загрузка…" : "Ничего не найдено"} onRowClick={(r) => navigate(promoHref(r))} />
        {!loading && <div className="mt-2 text-[11px] text-[var(--text-muted)]">Показано {filtered.length} из {rows.length}</div>}
      </Card>

      {createOpen && <CreateModal onClose={() => setCreateOpen(false)} onDone={() => { setCreateOpen(false); load(); }} />}
      {partnerOpen && <PartnerModal onClose={() => setPartnerOpen(false)} onDone={() => { setPartnerOpen(false); load(); }} />}
    </>
  );
}

function CreateModal({ onClose, onDone }: { onClose: () => void; onDone: () => void }) {
  const [giftKind, setGiftKind] = useState<PromoGiftKind>("fixed_rub");
  const [bonus, setBonus] = useState("");
  const [name, setName] = useState("");
  const [maxAct, setMaxAct] = useState("");
  const [minOrder, setMinOrder] = useState("");
  const [busy, setBusy] = useState(false);
  const isDiscount = giftKind === "exchange_discount";

  async function submit() {
    if (Number(bonus) <= 0) return toast.error("Укажите бонус");
    setBusy(true);
    try {
      const body = {
        client_fixed_bonus_rub: Number(bonus),
        name: name.trim() || undefined,
        max_activations: maxAct === "" ? undefined : Number(maxAct),
        ...(isDiscount ? { min_order_rub: Number(minOrder || 0) } : {}),
      };
      if (isDiscount) await createExchangeDiscount(body);
      else await createFixedRubPromo(body);
      toast.success(isDiscount ? "Создан промокод на скидку" : "Создан промокод на баланс");
      onDone();
    } catch (e) {
      toast.error(e instanceof PanelApiError ? e.message : "Ошибка");
    } finally {
      setBusy(false);
    }
  }

  return (
    <Modal
      open
      title="Новый промокод"
      onClose={onClose}
      footer={
        <>
          <Button variant="ghost" onClick={onClose}>Отмена</Button>
          <Button variant="primary" disabled={busy} onClick={submit}>Создать</Button>
        </>
      }
    >
      <div className="flex flex-col gap-3">
        <div className="flex flex-col gap-1.5">
          <span className="text-[11px] font-semibold uppercase tracking-wide text-[var(--text-muted)]">Тип</span>
          <div className="flex w-fit gap-1 rounded-[var(--radius)] border border-[var(--border)] bg-[var(--bg-elevated)] p-1" role="radiogroup" aria-label="Тип промокода">
            {([
              { key: "fixed_rub", label: "На баланс" },
              { key: "exchange_discount", label: "Скидка на обмен" },
            ] as const).map((opt) => (
              <button
                key={opt.key}
                type="button"
                role="radio"
                aria-checked={giftKind === opt.key}
                onClick={() => setGiftKind(opt.key)}
                className={cx(
                  "rounded-[var(--radius-sm)] px-3 py-1.5 text-[13px] font-medium transition-colors",
                  giftKind === opt.key ? "bg-[var(--bg-surface)] text-[var(--text-primary)] shadow-[var(--shadow)]" : "text-[var(--text-secondary)] hover:text-[var(--text-primary)]",
                )}
              >
                {opt.label}
              </button>
            ))}
          </div>
          <span className="text-[11px] leading-snug text-[var(--text-muted)]">
            {isDiscount ? "Клиент активирует код и получает купон на покупку. На баланс не зачисляется." : "Клиент активирует код — сумма сразу на баланс."}
          </span>
        </div>
        <Field label="Бонус клиенту, ₽">
          <Input inputMode="decimal" value={bonus} onChange={(e) => setBonus(e.target.value)} className="font-mono" />
        </Field>
        <Field label="Название (необязательно)">
          <Input value={name} onChange={(e) => setName(e.target.value)} />
        </Field>
        <Field label="Макс. активаций">
          <Input inputMode="numeric" value={maxAct} onChange={(e) => setMaxAct(e.target.value)} className="font-mono" />
        </Field>
        {isDiscount && (
          <Field label="Мин. сумма заказа, ₽" hint="Купон сработает только на покупке от этой суммы. Например 3000.">
            <Input inputMode="decimal" value={minOrder} onChange={(e) => setMinOrder(e.target.value)} className="font-mono" placeholder="Без минимума" />
          </Field>
        )}
      </div>
    </Modal>
  );
}

function PartnerModal({ onClose, onDone }: { onClose: () => void; onDone: () => void }) {
  const [username, setUsername] = useState("");
  const [commission, setCommission] = useState("");
  const [busy, setBusy] = useState(false);

  async function submit() {
    if (!username.trim()) return toast.error("Укажите username");
    setBusy(true);
    try {
      await quickPartner({
        partner_username: username.trim(),
        partner_commission_percent: commission === "" ? undefined : Number(commission),
      });
      toast.success("Партнёр создан");
      onDone();
    } catch (e) {
      toast.error(e instanceof PanelApiError ? e.message : "Ошибка");
    } finally {
      setBusy(false);
    }
  }

  return (
    <Modal
      open
      title="Быстрый партнёр"
      onClose={onClose}
      footer={
        <>
          <Button variant="ghost" onClick={onClose}>Отмена</Button>
          <Button variant="primary" disabled={busy} onClick={submit}>Создать</Button>
        </>
      }
    >
      <div className="flex flex-col gap-3">
        <Field label="Username партнёра">
          <Input value={username} onChange={(e) => setUsername(e.target.value)} className="font-mono" />
        </Field>
        <Field label="Комиссия партнёра, %">
          <Input inputMode="decimal" value={commission} onChange={(e) => setCommission(e.target.value)} className="font-mono" />
        </Field>
      </div>
    </Modal>
  );
}
