import { useEffect, useState } from "react";
import { CheckCircle2, History, Loader2 } from "lucide-react";
import { toast } from "sonner";
import { PanelApiError } from "@/panel/lib/panelApi";
import {
  confirmDeployEvent,
  getChangelog,
  type ChangelogDay,
  type DeployEvent,
} from "@/panel/lib/operatorApi";
import { Badge, Button, Card, Field, Input, PageHeader, type BadgeTone } from "@/panel/ui/primitives";

const statusTone: Record<string, BadgeTone> = {
  pending: "yellow",
  success: "blue",
  confirmed: "green",
  failed: "red",
  unknown: "orange",
};

function todayUtc(): string {
  return new Date().toISOString().slice(0, 10);
}

export function OperatorChangelog() {
  const [day, setDay] = useState(todayUtc());
  const [days, setDays] = useState<ChangelogDay[]>([]);
  const [items, setItems] = useState<DeployEvent[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [busyId, setBusyId] = useState<number | null>(null);

  async function load(selectedDay: string) {
    setLoading(true);
    setError(null);
    try {
      const r = await getChangelog({ day: selectedDay || undefined });
      setDays(r.days || []);
      setItems(r.items || []);
    } catch (e) {
      setError(e instanceof PanelApiError ? e.message : "Не удалось загрузить changelog");
      setItems([]);
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    void load(day);
  }, [day]);

  async function confirm(id: number) {
    setBusyId(id);
    try {
      await confirmDeployEvent(id, "Проверено на production");
      toast.success(`Выкат #${id} подтверждён, уведомление отправлено`);
      await load(day);
    } catch (e) {
      toast.error(e instanceof PanelApiError ? e.message : "Ошибка подтверждения");
    } finally {
      setBusyId(null);
    }
  }

  return (
    <>
      <PageHeader
        title="Changelog"
        subtitle="По дням: что выкатили, какие сектора затронуты и что изменилось для людей."
      />

      <Card className="mb-4 flex flex-wrap items-end gap-3">
        <Field label="День (UTC)">
          <Input type="date" value={day} onChange={(e) => setDay(e.target.value)} className="w-auto" />
        </Field>
        <div className="flex flex-wrap gap-1.5 pb-0.5">
          {days.slice(0, 8).map((d) => (
            <button
              key={d.date}
              type="button"
              onClick={() => setDay(d.date)}
              className={
                d.date === day
                  ? "rounded-[var(--radius)] border border-[var(--accent)] bg-[var(--accent)]/15 px-2 py-1 text-[11px] text-[var(--text-primary)]"
                  : "rounded-[var(--radius)] border border-[var(--border-strong)] px-2 py-1 text-[11px] text-[var(--text-secondary)] hover:bg-[var(--bg-elevated)]"
              }
            >
              {d.date} · {d.count}
            </button>
          ))}
        </div>
      </Card>

      {loading ? (
        <Card className="flex items-center gap-2 text-[13px] text-[var(--text-secondary)]">
          <Loader2 className="size-4 animate-spin" /> Загрузка…
        </Card>
      ) : error ? (
        <Card className="text-[13px] text-[var(--red)]">{error}</Card>
      ) : items.length === 0 ? (
        <Card className="flex items-center gap-2 text-[13px] text-[var(--text-secondary)]">
          <History className="size-4" /> За этот день записей пока нет.
        </Card>
      ) : (
        <div className="space-y-3">
          {items.map((ev) => (
            <Card key={ev.id} className="space-y-3">
              <div className="flex flex-wrap items-start justify-between gap-2">
                <div>
                  <div className="text-[14px] font-semibold text-[var(--text-primary)]">
                    #{ev.id} {ev.title || "Изменение"}
                  </div>
                  <div className="mt-1 text-[11px] text-[var(--text-muted)]">
                    {ev.created_at ? String(ev.created_at).replace("T", " ").slice(0, 19) : "—"} UTC
                    {ev.commit_sha ? ` · ${String(ev.commit_sha).slice(0, 8)}` : ""}
                    {ev.actor ? ` · ${ev.actor}` : ""}
                  </div>
                </div>
                <Badge tone={statusTone[String(ev.status)] || "default"}>{String(ev.status)}</Badge>
              </div>

              {(ev.sectors || []).length > 0 && (
                <div className="flex flex-wrap gap-1.5">
                  {(ev.sectors || []).map((s) => (
                    <Badge key={s} tone="blue">
                      {s}
                    </Badge>
                  ))}
                </div>
              )}

              {ev.plain_explanation ? (
                <div>
                  <div className="mb-1 text-[11px] font-semibold uppercase tracking-wide text-[var(--text-muted)]">
                    Простыми словами
                  </div>
                  <p className="text-[13px] leading-relaxed text-[var(--text-primary)] whitespace-pre-wrap">
                    {ev.plain_explanation}
                  </p>
                </div>
              ) : null}

              {ev.user_impact ? (
                <div>
                  <div className="mb-1 text-[11px] font-semibold uppercase tracking-wide text-[var(--text-muted)]">
                    Влияние на пользователя
                  </div>
                  <p className="text-[13px] text-[var(--text-secondary)] whitespace-pre-wrap">{ev.user_impact}</p>
                </div>
              ) : null}

              {ev.technical_summary ? (
                <div>
                  <div className="mb-1 text-[11px] font-semibold uppercase tracking-wide text-[var(--text-muted)]">
                    Технически
                  </div>
                  <p className="font-mono text-[12px] text-[var(--text-secondary)] whitespace-pre-wrap">
                    {ev.technical_summary}
                  </p>
                </div>
              ) : null}

              {ev.status === "success" && ev.environment === "production" ? (
                <Button
                  size="sm"
                  variant="primary"
                  disabled={busyId === ev.id}
                  onClick={() => confirm(ev.id)}
                >
                  <CheckCircle2 className="size-3.5" />
                  Подтвердить на production
                </Button>
              ) : null}
              {ev.status === "confirmed" ? (
                <div className="text-[12px] text-[var(--green)]">
                  Подтверждено{ev.confirmed_at ? ` · ${String(ev.confirmed_at).slice(0, 19)}` : ""}
                  {ev.notify_sent_at ? " · операторы уведомлены" : ""}
                </div>
              ) : null}
            </Card>
          ))}
        </div>
      )}
    </>
  );
}
