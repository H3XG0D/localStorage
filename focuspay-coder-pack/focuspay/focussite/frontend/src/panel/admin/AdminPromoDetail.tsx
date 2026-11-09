import { useEffect, useState } from "react";
import { Link, Navigate, useNavigate, useParams } from "react-router-dom";
import { ArrowLeft } from "lucide-react";
import { toast } from "sonner";
import { PanelApiError } from "@/panel/lib/panelApi";
import { getPromo, type Dict } from "@/panel/lib/adminApi";
import { Badge, Button, Card, Kpi, PageHeader, Table, type Column } from "@/panel/ui/primitives";

function money(v: unknown, digits = 0) {
  return new Intl.NumberFormat("ru-RU", { maximumFractionDigits: digits }).format(Number(v ?? 0));
}
function dt(v: unknown) {
  if (!v) return "—";
  const d = new Date(String(v));
  return Number.isNaN(d.getTime()) ? "—" : d.toLocaleString("ru-RU");
}
function isPartnerPromo(promo: Dict, partner: Dict | null) {
  return String(promo.campaign_kind ?? "") === "partner" || Boolean(partner?.username || promo.partner_username);
}
function isDiscountPromo(promo: Dict) {
  return String(promo.campaign_kind ?? "") === "exchange_discount";
}
function userLabel(row: Dict) {
  if (row.username) return `@${String(row.username)}`;
  if (row.first_name) return String(row.first_name);
  return `ID ${row.user_id ?? "—"}`;
}
function statusLabel(promo: Dict, used: number, maxAct: number) {
  if (promo.status === "exhausted" || (maxAct > 0 && used >= maxAct)) return "исчерпан";
  if (promo.is_active === false || promo.status === "disabled") return "выключен";
  return "активен";
}

export function AdminPromoDetail() {
  const { id } = useParams();
  const navigate = useNavigate();
  const pid = Number(id);
  const [payload, setPayload] = useState<Dict | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    if (!Number.isFinite(pid)) return;
    setLoading(true);
    getPromo(pid)
      .then(setPayload)
      .catch((e) => {
        setPayload(null);
        toast.error(e instanceof PanelApiError ? e.message : "Промокод не найден");
      })
      .finally(() => setLoading(false));
  }, [pid]);

  if (!loading && payload) {
    const promo = (payload.promo ?? {}) as Dict;
    const partner = (payload.partner ?? null) as Dict | null;
    if (isPartnerPromo(promo, partner) && Number.isFinite(pid)) {
      return <Navigate to={`/x8/partners/${pid}`} replace />;
    }
  }

  const promo = ((payload?.promo ?? {}) as Dict);
  const metrics = ((payload?.metrics ?? {}) as Dict);
  const entries = Array.isArray(payload?.gift_entries) ? (payload.gift_entries as Dict[]) : [];
  const used = Number(metrics.activations_used ?? promo.activations_used ?? entries.length);
  const maxAct = Number(metrics.activations_max ?? promo.max_activations ?? 5);
  const status = statusLabel(promo, used, maxAct);
  const issued = (promo.issued_by_operator ?? null) as Dict | null;
  const discount = isDiscountPromo(promo);
  const minOrder = Number(promo.min_order_rub ?? 0);

  const cols: Column<Dict>[] = [
    { key: "entered_at", label: "Дата", width: "180px", render: (r) => dt(r.entered_at ?? r.redeemed_at) },
    { key: "user", label: "Пользователь", render: (r) => (
      <Link to={`/x8/users?user=${r.user_id}`} className="text-[var(--accent)] hover:underline" onClick={(e) => e.stopPropagation()}>
        {userLabel(r)}
      </Link>
    ) },
    { key: "user_id", label: "Telegram ID", width: "140px", render: (r) => <span className="font-mono">{String(r.user_id ?? "—")}</span> },
    { key: "amount_rub", label: discount ? "Купон ₽" : "На баланс ₽", width: "120px", align: "right", render: (r) => <span className="font-mono">{discount ? "" : "+"}{money(r.amount_rub, 2)} ₽</span> },
  ];

  return (
    <>
      <PageHeader
        title={String(promo.code || `Промо ${id}`)}
        subtitle={String(promo.name || (discount ? "Скидка на обмен" : "Промокод на баланс"))}
        actions={
          <Button variant="ghost" onClick={() => navigate("/x8/promo")}>
            <ArrowLeft className="size-4" /> К списку
          </Button>
        }
      />

      {loading || !payload ? (
        <Card>{loading ? "Загрузка…" : "Нет данных"}</Card>
      ) : (
        <>
          <p className="text-[13px] text-[var(--text-secondary)]">
            {discount
              ? <>Активация через <code className="font-mono">/gift {String(promo.code)}</code> или в кабинете даёт купон на покупку, не зачисление на баланс.{minOrder > 0 ? ` Купон действует от ${money(minOrder)} ₽.` : ""}</>
              : <>Активация через <code className="font-mono">/gift {String(promo.code)}</code> или в кабинете зачисляет сумму на баланс.</>}
            {" "}Лимит: {maxAct} активаций.
            {issued
              ? ` Выдал: @${String(issued.username || issued.display_name || issued.id)}.`
              : " Выдал: админ."}
          </p>

          <div className="grid grid-cols-3 gap-4 max-md:grid-cols-1">
            <Kpi label={discount ? "Скидка на обмен, ₽" : "На баланс, ₽"} value={money(promo.client_fixed_bonus_rub)} />
            <Kpi label="Активации" value={`${used} / ${maxAct}`} />
            <Kpi label="Статус" value={<Badge tone={status === "активен" ? "green" : status === "исчерпан" ? "yellow" : "red"}>{status}</Badge>} />
          </div>

          {promo.author_telegram_id ? (
            <div className="grid grid-cols-3 gap-4 max-md:grid-cols-1">
              <Kpi label="Автор" value={String(promo.author_telegram_id)} hint={promo.issued_for === "first_video" ? "Первое видео" : "Код автора"} />
              <Kpi label="Приходы" value={String(metrics.attracted_users ?? 0)} hint="Перешли по ссылке или закрепились за кодом" />
              <Kpi label="Обмены со скидкой" value={String(metrics.discount_orders_count ?? 0)} hint={`${money(metrics.discount_fiat_sum)} ₽`} />
            </div>
          ) : null}

          <Card>
            <div className="mb-3 text-[13.5px] font-semibold">Кто активировал · {entries.length}</div>
            <Table columns={cols} rows={entries} empty="Пока никто не активировал" />
          </Card>
        </>
      )}
    </>
  );
}
