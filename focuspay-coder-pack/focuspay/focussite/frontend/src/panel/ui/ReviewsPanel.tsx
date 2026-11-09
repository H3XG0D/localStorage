// Shared reviews moderation (admin + operator share the same routes/shape).
import { useCallback, useEffect, useState } from "react";
import { toast } from "sonner";
import { panelApi, PanelApiError, type PanelScope } from "@/panel/lib/panelApi";
import { REVIEW_TODAY_LABEL, isReviewFromCalendarToday } from "@/panel/lib/reviewToday";
import { Badge, Button, Card, PageHeader, cx, type BadgeTone } from "@/panel/ui/primitives";

interface Review {
  id: number;
  user_id?: number;
  username?: string;
  review_text?: string;
  status?: string;
  has_photo?: boolean;
  has_photo_preview?: boolean;
  created_at?: string;
  [k: string]: unknown;
}

const STATUS: { key: string; label: string }[] = [
  { key: "pending", label: "На модерации" },
  { key: "published", label: "Опубликованы" },
  { key: "rejected", label: "Отклонены" },
];
const tone = (s?: string): BadgeTone => (s === "published" ? "green" : s === "rejected" ? "red" : "yellow");

export function ReviewsPanel({ scope }: { scope: PanelScope }) {
  const [status, setStatus] = useState("pending");
  const [rows, setRows] = useState<Review[]>([]);
  const [loading, setLoading] = useState(true);

  const load = useCallback(() => {
    setLoading(true);
    panelApi<{ items?: Review[]; reviews?: Review[] }>(`/${scope}/reviews`, { scope, query: { status, page: 1, limit: 50 } })
      .then((r) => setRows(r.items ?? r.reviews ?? []))
      .catch((e) => toast.error(e instanceof PanelApiError ? e.message : "Ошибка"))
      .finally(() => setLoading(false));
  }, [scope, status]);

  useEffect(() => load(), [load]);

  async function act(id: number, action: "publish" | "reject", body: Record<string, unknown>) {
    try {
      await panelApi(`/${scope}/reviews/${id}/${action}`, { scope, method: "POST", body });
      toast.success(action === "publish" ? "Опубликовано" : "Отклонено");
      load();
    } catch (e) {
      toast.error(e instanceof PanelApiError ? e.message : "Ошибка");
    }
  }

  return (
    <>
      <PageHeader title="Отзывы" subtitle="Модерация клиентских отзывов" />
      <div className="flex w-fit gap-1 rounded-[var(--radius)] border border-[var(--border)] bg-[var(--bg-surface)] p-1">
        {STATUS.map((s) => (
          <button
            key={s.key}
            onClick={() => setStatus(s.key)}
            className={cx(
              "rounded-[var(--radius-sm)] px-3 py-1.5 text-[13px] font-medium transition-colors",
              status === s.key ? "bg-[var(--bg-elevated)] text-[var(--text-primary)]" : "text-[var(--text-secondary)] hover:text-[var(--text-primary)]",
            )}
          >
            {s.label}
          </button>
        ))}
      </div>

      {loading ? (
        <Card>Загрузка…</Card>
      ) : rows.length === 0 ? (
        <Card>Нет отзывов.</Card>
      ) : (
        <div className="grid grid-cols-2 gap-3 max-md:grid-cols-1">
          {rows.map((r) => (
            <Card key={r.id}>
              <div className="mb-2 flex items-center justify-between gap-2">
                <span className="text-[13px] font-medium">{r.username || `ID ${r.user_id ?? "—"}`}</span>
                <span className="flex items-center gap-1">
                  <Badge tone={r.product === "vpn" ? "blue" : "default"}>{r.product === "vpn" ? "VPN" : "Обмен"}</Badge>
                  <Badge tone={tone(r.status)}>{STATUS.find((s) => s.key === r.status)?.label || r.status}</Badge>
                </span>
              </div>
              {r.product === "vpn" ? (
                <p className="mb-2 text-[12px] text-[var(--text-muted)]">
                  Бонус раз в 7 дней: {Number(r.bonus_text_rub ?? 25)} ₽ текст, {Number(r.bonus_photo_rub ?? 50)} ₽ со скрином.
                </p>
              ) : null}
              {isReviewFromCalendarToday(r.created_at) && (
                <p className="mb-2 text-[12px] text-[var(--text-muted)]">{REVIEW_TODAY_LABEL}</p>
              )}
              <p className="whitespace-pre-line text-[13px] text-[var(--text-secondary)]">{r.review_text || "—"}</p>
              {(r.has_photo_preview ?? r.has_photo) && (
                <a
                  href={`/api/${scope}/reviews/${r.id}/photo`}
                  target="_blank"
                  rel="noreferrer"
                  className="mt-2 inline-block text-[12px] text-[var(--blue)] hover:underline"
                >
                  Скриншот →
                </a>
              )}
              {r.status === "pending" && (
                <div className="mt-3 flex flex-wrap gap-2">
                  <Button size="sm" variant="primary" onClick={() => act(r.id, "publish", { bonus: "none" })}>
                    Опубликовать
                  </Button>
                  <Button size="sm" variant="secondary" onClick={() => act(r.id, "publish", { bonus: "text" })}>
                    +{Number(r.bonus_text_rub ?? 50)} ₽
                  </Button>
                  <Button size="sm" variant="secondary" onClick={() => act(r.id, "publish", { bonus: "photo" })}>
                    +{Number(r.bonus_photo_rub ?? 100)} ₽
                  </Button>
                  <Button size="sm" variant="danger" onClick={() => act(r.id, "reject", { reason: "" })}>
                    Отклонить
                  </Button>
                </div>
              )}
            </Card>
          ))}
        </div>
      )}
    </>
  );
}
