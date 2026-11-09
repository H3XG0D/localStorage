import { useCallback, useEffect, useState, type ReactNode } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import {
  AlertCircle,
  ArrowLeft,
  CheckCircle2,
  CircleDashed,
  Loader2,
  RefreshCw,
  Shield,
  Sticker,
  Wand2,
} from "lucide-react";
import { toast } from "sonner";
import { PanelApiError } from "@/panel/lib/panelApi";
import {
  stickerAiApprove,
  stickerAiAssetUrl,
  stickerAiCreateTask,
  stickerAiEdit,
  stickerAiGenerate,
  stickerAiGetTask,
  stickerAiHealth,
  stickerAiListTasks,
  stickerAiPublish,
  stickerAiReject,
  stickerAiSubmitReview,
  type StickerAiHealth,
  type StickerAiTask,
} from "@/panel/lib/adminApi";
import { getPanelToken } from "@/panel/lib/panelApi";
import { panelMe } from "@/panel/lib/panelAuth";
import { Badge, Button, Card, Field, Input, PageHeader, type BadgeTone } from "@/panel/ui/primitives";

const STATUS_RU: Record<string, string> = {
  draft: "Черновик",
  generating: "Генерация",
  editing: "Редактирование",
  review: "На проверке",
  approved: "Одобрено",
  rejected: "Отклонено",
  publishing: "Публикация",
  published: "Опубликовано",
  quarantined: "Карантин",
};

const STATUS_TONE: Record<string, BadgeTone> = {
  draft: "default",
  generating: "blue",
  editing: "blue",
  review: "yellow",
  approved: "green",
  rejected: "red",
  publishing: "purple",
  published: "green",
  quarantined: "orange",
};

const REASON_RU: Record<string, string> = {
  flag_disabled: "Раздел выключен флагом на сервере (STICKER_AI_ENABLED)",
  mutations_closed: "Создание и публикация закрыты (STICKER_AI_MUTATIONS_ENABLED=false)",
  provider_not_ready: "Провайдер изображений не готов",
  provider_null: "Провайдер не подключён (null)",
};

const STEPS = [
  { n: 1, title: "Идея", text: "Опишите тему стикера в фирменном стиле FocusPay." },
  { n: 2, title: "Генерация", text: "Система создаёт варианты (mock или воркер)." },
  { n: 3, title: "Проверка и approve", text: "Ручная модерация обязательна — без неё публикация запрещена." },
  { n: 4, title: "Публикация", text: "После одобрения — публикация в Telegram-набор (на lab — mock)." },
] as const;

function statusLabel(status: unknown): string {
  const key = String(status ?? "");
  return STATUS_RU[key] ?? (key || "Неизвестно");
}

function statusTone(status: unknown): BadgeTone {
  return STATUS_TONE[String(status ?? "")] || "default";
}

function providerLabel(provider: unknown): string {
  const key = String(provider ?? "").toLowerCase();
  if (!key || key === "null") return "Не подключён";
  if (key === "offline_mock" || key === "offline" || key === "mock") return "Тестовый (офлайн)";
  if (key === "lelouch" || key === "openai" || key === "openai_images") return "Lelouch";
  if (key === "http" || key === "http_worker" || key === "worker") return "Внешний воркер";
  return key;
}

function formatUpdatedAt(value: unknown): string {
  const raw = String(value ?? "");
  if (!raw) return "—";
  const d = new Date(raw);
  if (Number.isNaN(d.getTime())) return raw;
  return d.toLocaleString("ru-RU", {
    day: "2-digit",
    month: "short",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

function describeLoadError(e: unknown): string {
  if (!(e instanceof PanelApiError)) return "Не удалось загрузить раздел стикеров";
  if (e.status === 404) return "Раздел ещё не подключён на сервере. Нужен выкат бэкенда брендовых стикеров.";
  if (e.status === 503) {
    const d = String(e.message || "");
    if (d.includes("mutations")) return "Управление закрыто: включите лабораторные мутации на сервере.";
    return "Генерация стикеров выключена на сервере или мутации закрыты.";
  }
  if (e.status === 401) return "Сессия истекла — войдите снова.";
  if (e.status === 403) return "Недостаточно прав для этого действия.";
  if (e.status === 409) return "Нельзя выполнить шаг: проверьте статус задачи (нужен approve перед публикацией).";
  return e.message || "Ошибка загрузки";
}

type LoadPhase = "idle" | "loading" | "ready" | "error";

export function AdminStickerAi() {
  const { taskId } = useParams<{ taskId?: string }>();
  const navigate = useNavigate();
  const [health, setHealth] = useState<StickerAiHealth | null>(null);
  const [tasks, setTasks] = useState<StickerAiTask[]>([]);
  const [selected, setSelected] = useState<StickerAiTask | null>(null);
  const [perms, setPerms] = useState<string[]>([]);
  const [isAdmin, setIsAdmin] = useState(false);
  const [phase, setPhase] = useState<LoadPhase>("loading");
  const [banner, setBanner] = useState<string | null>(null);
  const [detailError, setDetailError] = useState<string | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const [busy, setBusy] = useState(false);
  const [idea, setIdea] = useState("");
  const [rejectReason, setRejectReason] = useState("");
  const [pickedKey, setPickedKey] = useState<string | null>(null);
  const [editPrompt, setEditPrompt] = useState("");

  const load = useCallback(async () => {
    setPhase("loading");
    setBanner(null);
    try {
      try {
        const me = await panelMe("admin");
        setPerms(Array.isArray(me.permissions) ? me.permissions.map(String) : []);
        setIsAdmin(me.is_admin === true || me.rbac_role === "ADMIN");
      } catch {
        /* права опциональны для карточки статуса */
      }

      const h = await stickerAiHealth();
      setHealth(h);
      if (!h.enabled) {
        setTasks([]);
        setBanner(
          "Режим наблюдения: раздел выключен. Создание и публикация недоступны до серверного включения.",
        );
        setPhase("ready");
        return;
      }
      try {
        const r = await stickerAiListTasks("all");
        setTasks(r.tasks || []);
        if (!h.mutations) {
          setBanner(
            "Список задач доступен, но управление закрыто (mutations=false). Нужны флаги и готовый провайдер.",
          );
        }
        setPhase("ready");
      } catch (e) {
        setTasks([]);
        setBanner(describeLoadError(e));
        setPhase("ready");
      }
    } catch (e) {
      setHealth(null);
      setTasks([]);
      setBanner(describeLoadError(e));
      setPhase("error");
    }
  }, []);

  useEffect(() => {
    load().catch(() => {});
  }, [load]);

  useEffect(() => {
    if (!taskId) {
      setSelected(null);
      setDetailError(null);
      setPickedKey(null);
      return;
    }
    let cancelled = false;
    setDetailLoading(true);
    setDetailError(null);
    stickerAiGetTask(taskId)
      .then((t) => {
        if (!cancelled) setSelected(t);
      })
      .catch((e) => {
        if (!cancelled) {
          setSelected(null);
          setDetailError(describeLoadError(e));
        }
      })
      .finally(() => {
        if (!cancelled) setDetailLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [taskId]);

  const stickerPerms = (health?.my_permissions?.length ? health.my_permissions : perms).filter((p) =>
    String(p).startsWith("sticker."),
  );
  const canView =
    isAdmin ||
    stickerPerms.includes("sticker.view_own") ||
    stickerPerms.includes("sticker.view_any") ||
    stickerPerms.includes("sticker.create");
  const canCreate = isAdmin || stickerPerms.includes("sticker.create");
  const canEdit = isAdmin || stickerPerms.includes("sticker.edit_own");
  const canSubmit = isAdmin || stickerPerms.includes("sticker.submit_review");
  const canModerate = isAdmin || stickerPerms.includes("sticker.moderate");
  const canPublish = isAdmin || stickerPerms.includes("sticker.publish");

  const loading = phase === "loading";
  const enabled = health?.enabled === true;
  const mutationsOpen = health?.mutations === true;
  const reasons = (health?.observation_reasons || []).map((r) => REASON_RU[r] || r);

  async function runAction(label: string, fn: () => Promise<StickerAiTask>) {
    setBusy(true);
    try {
      const t = await fn();
      setSelected(t);
      toast.success(label);
      await load();
      if (t.id) navigate(`/x8/sticker-ai/tasks/${encodeURIComponent(String(t.id))}`);
    } catch (e) {
      toast.error(describeLoadError(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="space-y-5">
      <PageHeader
        title="Брендовые стикеры"
        subtitle="Управляемое создание и модерация фирменных Telegram-стикеров FocusPay. Отделён от AI-задач. Без approve публикация невозможна."
        actions={
          <Button
            type="button"
            variant="secondary"
            size="sm"
            onClick={() => load()}
            disabled={loading}
            aria-label="Обновить данные раздела"
          >
            <RefreshCw className={`mr-1.5 h-3.5 w-3.5 ${loading ? "animate-spin" : ""}`} aria-hidden />
            Обновить
          </Button>
        }
      />

      <Card className="space-y-3 border-[var(--border-strong)] bg-[var(--bg-elevated)]/40">
        <div className="flex items-start gap-3">
          <div className="mt-0.5 flex h-9 w-9 shrink-0 items-center justify-center rounded-[var(--radius)] border border-[var(--border)] bg-[var(--bg-surface)]">
            <Sticker className="h-4 w-4 text-[var(--text-secondary)]" aria-hidden />
          </div>
          <div className="min-w-0 space-y-1.5">
            <h2 className="text-[14px] font-semibold text-[var(--text-primary)]">Зачем этот раздел</h2>
            <p className="text-[13px] leading-relaxed text-[var(--text-secondary)]">
              Здесь готовятся брендовые стикеры для чатов и новостей. Итог — одобренный набор в стиле FocusPay.
              Ops AI только консультирует и не включает генерацию сам.
            </p>
          </div>
        </div>
      </Card>

      <Card className="space-y-4">
        <div>
          <h2 className="text-[14px] font-semibold text-[var(--text-primary)]">Как это работает</h2>
          <p className="mt-0.5 text-[12.5px] text-[var(--text-muted)]">
            Идея → генерация → проверка → approve оператора → публикация
          </p>
        </div>
        <ol className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
          {STEPS.map((step) => (
            <li
              key={step.n}
              className="rounded-[var(--radius)] border border-[var(--border)] bg-[var(--bg-surface)] p-3"
            >
              <div className="mb-1.5 flex items-center gap-2">
                <span className="flex h-5 w-5 items-center justify-center rounded-full bg-[var(--bg-elevated)] text-[11px] font-semibold text-[var(--text-secondary)]">
                  {step.n}
                </span>
                <span className="text-[13px] font-medium text-[var(--text-primary)]">{step.title}</span>
              </div>
              <p className="text-[12px] leading-relaxed text-[var(--text-muted)]">{step.text}</p>
            </li>
          ))}
        </ol>
        <div className="rounded-[var(--radius)] border border-dashed border-[var(--border)] px-3 py-2.5 text-[12.5px] text-[var(--text-secondary)]">
          <span className="font-medium text-[var(--text-primary)]">Первый шаг сейчас:</span>{" "}
          {!enabled
            ? "обновите статус и дождитесь включения раздела на сервере."
            : !mutationsOpen
              ? "просмотрите причины режима наблюдения ниже. Создание пока закрыто."
              : canCreate
                ? "создайте задачу с идеей стикера в форме ниже."
                : "у вас нет права sticker.create — обратитесь к администратору."}
        </div>
      </Card>

      {banner && (
        <div
          role="status"
          className="flex items-start gap-2 rounded-[var(--radius)] border border-[var(--yellow)]/30 bg-[var(--yellow-bg)] px-3 py-2.5 text-[12.5px] leading-relaxed text-[var(--yellow)]"
        >
          <AlertCircle className="mt-0.5 h-4 w-4 shrink-0" aria-hidden />
          <span>{banner}</span>
        </div>
      )}

      <Card className="space-y-3" aria-busy={loading} aria-label="Состояние платформы стикеров">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <div className="flex items-center gap-2">
            <Shield className="h-4 w-4 text-[var(--text-secondary)]" aria-hidden />
            <h2 className="text-[14px] font-semibold text-[var(--text-primary)]">Состояние и права</h2>
          </div>
          {loading && (
            <span className="inline-flex items-center gap-1.5 text-[12px] text-[var(--text-muted)]">
              <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden />
              Загрузка…
            </span>
          )}
        </div>

        {phase === "error" && !health ? (
          <div className="flex flex-col items-start gap-3 py-2" role="alert">
            <p className="text-[13px] text-[var(--text-secondary)]">
              Не удалось получить статус. Проверьте соединение или права и нажмите «Обновить».
            </p>
            <Button type="button" variant="secondary" size="sm" onClick={() => load()}>
              Повторить
            </Button>
          </div>
        ) : health ? (
          <>
            <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
              <StatusCell
                label="Раздел"
                value={
                  <Badge tone={health.enabled ? "green" : "yellow"}>
                    {health.enabled ? "Включён" : "Выключен"}
                  </Badge>
                }
              />
              <StatusCell
                label="Управление"
                value={
                  <Badge tone={mutationsOpen ? "green" : "default"}>
                    {mutationsOpen ? "Открыто" : "Только просмотр"}
                  </Badge>
                }
                hint={mutationsOpen ? "Можно создавать и модерировать" : "Мутации закрыты флагом"}
              />
              <StatusCell
                label="Провайдер"
                value={<span className="text-[var(--text-primary)]">{providerLabel(health.provider)}</span>}
                hint={
                  health.provider_ready
                    ? `Готов${health.image_model ? ` · ${String(health.image_model)}` : ""}`
                    : "Не готов"
                }
              />
              <StatusCell
                label="Изоляция от AI-задач"
                value={
                  <Badge tone={health.ops_ai_isolated ? "green" : "red"}>
                    {health.ops_ai_isolated ? "Да" : "Нет"}
                  </Badge>
                }
              />
            </div>
            {reasons.length > 0 && (
              <div className="rounded-[var(--radius)] border border-[var(--border)] bg-[var(--bg-surface)] px-3 py-2.5">
                <div className="text-[11.5px] uppercase tracking-wide text-[var(--text-muted)]">
                  Почему режим наблюдения
                </div>
                <ul className="mt-1.5 list-disc space-y-1 pl-4 text-[12.5px] text-[var(--text-secondary)]">
                  {reasons.map((r) => (
                    <li key={r}>{r}</li>
                  ))}
                </ul>
              </div>
            )}
            <div className="text-[12px] text-[var(--text-muted)]">
              Ваши права sticker.*:{" "}
              {stickerPerms.length ? stickerPerms.join(", ") : "нет (или не загружены)"}
              {" · "}
              Секреты в ответе API: {health.secrets_exposed ? "обнаружены!" : "не передаются"}
            </div>
          </>
        ) : (
          <p className="text-[13px] text-[var(--text-muted)]">
            {loading ? "Загрузка статуса…" : "Нет данных со сервера"}
          </p>
        )}
      </Card>

      {mutationsOpen && canCreate && (
        <Card className="space-y-3" aria-label="Создание задачи стикера">
          <h2 className="text-[14px] font-semibold text-[var(--text-primary)]">Создать задачу</h2>
          <Field label="Идея стикера">
            <Input
              value={idea}
              onChange={(e) => setIdea(e.target.value)}
              placeholder="Например: приветственный F на космическом фоне"
              maxLength={1000}
              aria-label="Текст идеи стикера"
            />
          </Field>
          <Button
            type="button"
            size="sm"
            disabled={busy || !idea.trim()}
            onClick={() =>
              runAction("Задача создана", () =>
                stickerAiCreateTask({
                  idea: idea.trim(),
                  n_variants: 2,
                  idempotency_key: `ui-${Date.now()}`,
                }),
              )
            }
          >
            Создать
          </Button>
        </Card>
      )}

      {taskId && (
        <Card className="space-y-3" aria-label="Карточка задачи стикера">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <h2 className="text-[14px] font-semibold text-[var(--text-primary)]">Задача стикера</h2>
            <Link
              to="/x8/sticker-ai"
              className="inline-flex items-center gap-1.5 text-[12.5px] text-[var(--text-secondary)] hover:text-[var(--text-primary)]"
            >
              <ArrowLeft className="h-3.5 w-3.5" aria-hidden />
              К списку задач
            </Link>
          </div>
          {detailLoading ? (
            <div className="flex items-center gap-2 py-4 text-[13px] text-[var(--text-muted)]">
              <Loader2 className="h-4 w-4 animate-spin" aria-hidden />
              Загрузка задачи…
            </div>
          ) : detailError ? (
            <div role="alert" className="space-y-2 py-2">
              <p className="text-[13px] text-[var(--red)]">{detailError}</p>
            </div>
          ) : selected ? (
            <>
              <div className="grid gap-3 text-[13px] sm:grid-cols-2">
                <DetailRow label="Идентификатор" value={<span className="font-mono">{String(selected.id)}</span>} />
                <DetailRow
                  label="Статус"
                  value={<Badge tone={statusTone(selected.status)}>{statusLabel(selected.status)}</Badge>}
                />
                <DetailRow
                  label="Идея"
                  value={String(selected.idea_redacted || "—")}
                  className="sm:col-span-2"
                />
                <DetailRow label="Владелец" value={selected.owner_id != null ? String(selected.owner_id) : "—"} />
                <DetailRow label="Обновлено" value={formatUpdatedAt(selected.updated_at)} />
                <DetailRow
                  label="Вариантов"
                  value={String((selected.variants || []).length)}
                />
              </div>
              <VariantGallery
                taskId={String(selected.id)}
                variants={selected.variants || []}
                pickedKey={pickedKey}
                onPick={setPickedKey}
              />
              {mutationsOpen && (
                <div className="flex flex-wrap gap-2 border-t border-[var(--border)] pt-3">
                  {canEdit && String(selected.status) === "draft" && (
                    <Button
                      type="button"
                      size="sm"
                      variant="secondary"
                      disabled={busy}
                      onClick={() =>
                        runAction("Генерация запущена", () => stickerAiGenerate(String(selected.id)))
                      }
                    >
                      {(selected.variants || []).length ? "Сгенерировать ещё" : "Сгенерировать"}
                    </Button>
                  )}
                  {canEdit && String(selected.status) === "draft" && pickedKey && (
                    <div className="flex w-full flex-wrap items-center gap-2">
                      <Input
                        value={editPrompt}
                        onChange={(e) => setEditPrompt(e.target.value)}
                        placeholder="Правка выбранного варианта, например: крупнее буква F"
                        aria-label="Текст правки выбранного стикера"
                      />
                      <Button
                        type="button"
                        size="sm"
                        disabled={busy || !editPrompt.trim()}
                        onClick={() =>
                          runAction("Вариант обновлён", () =>
                            stickerAiEdit(String(selected.id), {
                              source_asset_key: pickedKey,
                              prompt: editPrompt.trim(),
                            }),
                          )
                        }
                      >
                        Править выбранный
                      </Button>
                    </div>
                  )}
                  {canSubmit && String(selected.status) === "draft" && (selected.variants || []).length > 0 && (
                    <Button
                      type="button"
                      size="sm"
                      variant="secondary"
                      disabled={busy}
                      onClick={() =>
                        runAction("Отправлено на проверку", () => stickerAiSubmitReview(String(selected.id)))
                      }
                    >
                      На проверку
                    </Button>
                  )}
                  {canModerate && String(selected.status) === "review" && (
                    <>
                      <Button
                        type="button"
                        size="sm"
                        disabled={busy}
                        onClick={() => runAction("Одобрено", () => stickerAiApprove(String(selected.id)))}
                      >
                        Одобрить
                      </Button>
                      <div className="flex flex-wrap items-center gap-2">
                        <Input
                          value={rejectReason}
                          onChange={(e) => setRejectReason(e.target.value)}
                          placeholder="Причина отклонения"
                          className="max-w-[220px]"
                          aria-label="Причина отклонения"
                        />
                        <Button
                          type="button"
                          size="sm"
                          variant="danger"
                          disabled={busy}
                          onClick={() =>
                            runAction("Отклонено", () =>
                              stickerAiReject(String(selected.id), rejectReason),
                            )
                          }
                        >
                          Отклонить
                        </Button>
                      </div>
                    </>
                  )}
                  {canPublish && String(selected.status) === "approved" && (
                    <Button
                      type="button"
                      size="sm"
                      disabled={busy}
                      onClick={() =>
                        runAction("Опубликовано (mock)", () => stickerAiPublish(String(selected.id)))
                      }
                    >
                      Опубликовать
                    </Button>
                  )}
                  {String(selected.status) !== "approved" && String(selected.status) !== "published" && (
                    <p className="w-full text-[12px] text-[var(--text-muted)]">
                      Публикация без одобрения недоступна — сначала статус «Одобрено».
                    </p>
                  )}
                </div>
              )}
            </>
          ) : (
            <p className="text-[13px] text-[var(--text-muted)]">Задача не найдена.</p>
          )}
        </Card>
      )}

      <Card className="space-y-3" aria-label="Очередь задач стикеров">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <h2 className="text-[14px] font-semibold text-[var(--text-primary)]">Очередь задач</h2>
            <p className="mt-0.5 text-[12.5px] text-[var(--text-muted)]">
              Изолированная очередь sticker_ai.* · хранилище с префиксом sticker_ai
            </p>
          </div>
          {!canView && !banner && stickerPerms.length > 0 && (
            <Badge tone="red">Нет прав на просмотр</Badge>
          )}
        </div>

        {loading && tasks.length === 0 ? (
          <div className="flex items-center gap-2 py-8 text-[13px] text-[var(--text-muted)]" aria-live="polite">
            <Loader2 className="h-4 w-4 animate-spin" aria-hidden />
            Загрузка очереди…
          </div>
        ) : !enabled ? (
          <EmptyState
            icon={<CircleDashed className="h-5 w-5" aria-hidden />}
            title="Очередь пока пуста"
            text="Раздел выключен. Когда включат флаги и провайдер, здесь появятся задачи."
          />
        ) : tasks.length === 0 ? (
          <EmptyState
            icon={<Wand2 className="h-5 w-5" aria-hidden />}
            title="Пока нет задач"
            text={
              mutationsOpen
                ? "Создайте первую идею стикера формой выше."
                : "Управление закрыто. После включения мутаций задачи появятся здесь."
            }
          />
        ) : (
          <ul className="divide-y divide-[var(--border)]" role="list">
            {tasks.map((t) => {
              const id = String(t.id);
              const active = taskId === id;
              return (
                <li key={id}>
                  <Link
                    to={`/x8/sticker-ai/tasks/${encodeURIComponent(id)}`}
                    className={`flex items-center justify-between gap-3 py-3 text-[13px] transition-colors hover:bg-[var(--bg-elevated)]/50 ${
                      active ? "bg-[var(--bg-elevated)]/60" : ""
                    }`}
                    aria-current={active ? "page" : undefined}
                    aria-label={`Задача ${id}, статус ${statusLabel(t.status)}`}
                  >
                    <div className="min-w-0 flex-1 px-1">
                      <div className="truncate font-medium text-[var(--text-primary)]">
                        {String(t.idea_redacted || "Без описания")}
                      </div>
                      <div className="mt-0.5 flex flex-wrap items-center gap-x-2 gap-y-0.5 text-[12px] text-[var(--text-muted)]">
                        <span className="font-mono">{id}</span>
                        <span aria-hidden>·</span>
                        <span>{formatUpdatedAt(t.updated_at)}</span>
                      </div>
                    </div>
                    <Badge tone={statusTone(t.status)}>{statusLabel(t.status)}</Badge>
                  </Link>
                </li>
              );
            })}
          </ul>
        )}

        {enabled && tasks.length > 0 && (
          <p className="flex items-center gap-1.5 text-[12px] text-[var(--text-muted)]">
            <CheckCircle2 className="h-3.5 w-3.5 text-[var(--green)]" aria-hidden />
            Показано задач: {tasks.length}
          </p>
        )}
      </Card>
    </div>
  );
}

function StatusCell({
  label,
  value,
  hint,
}: {
  label: string;
  value: ReactNode;
  hint?: string;
}) {
  return (
    <div className="rounded-[var(--radius)] border border-[var(--border)] bg-[var(--bg-surface)] px-3 py-2.5">
      <div className="text-[11.5px] uppercase tracking-wide text-[var(--text-muted)]">{label}</div>
      <div className="mt-1.5">{value}</div>
      {hint && <div className="mt-1 text-[11.5px] text-[var(--text-muted)]">{hint}</div>}
    </div>
  );
}

function DetailRow({
  label,
  value,
  className = "",
}: {
  label: string;
  value: ReactNode;
  className?: string;
}) {
  return (
    <div className={className}>
      <div className="text-[11.5px] uppercase tracking-wide text-[var(--text-muted)]">{label}</div>
      <div className="mt-1 text-[var(--text-secondary)]">{value}</div>
    </div>
  );
}

function EmptyState({
  icon,
  title,
  text,
}: {
  icon: ReactNode;
  title: string;
  text: string;
}) {
  return (
    <div className="flex flex-col items-center gap-2 px-4 py-10 text-center" role="status">
      <div className="flex h-10 w-10 items-center justify-center rounded-full border border-[var(--border)] bg-[var(--bg-elevated)] text-[var(--text-muted)]">
        {icon}
      </div>
      <p className="text-[13.5px] font-medium text-[var(--text-primary)]">{title}</p>
      <p className="max-w-md text-[12.5px] leading-relaxed text-[var(--text-muted)]">{text}</p>
    </div>
  );
}

function variantKey(v: Record<string, unknown>, index: number): string {
  return String(v.asset_key || v.key || `var-${index}`);
}

function VariantGallery({
  taskId,
  variants,
  pickedKey,
  onPick,
}: {
  taskId: string;
  variants: Array<Record<string, unknown>>;
  pickedKey: string | null;
  onPick: (key: string) => void;
}) {
  useEffect(() => {
    if (!variants.length) return;
    const keys = variants.map((v, i) => variantKey(v, i));
    if (!pickedKey || !keys.includes(pickedKey)) onPick(keys[0]);
  }, [variants, pickedKey, onPick]);

  if (!variants.length) {
    return (
      <p className="rounded-[var(--radius)] border border-dashed border-[var(--border)] px-3 py-4 text-[12.5px] text-[var(--text-muted)]">
        Пока нет картинок. Нажмите «Сгенерировать» — превью появятся здесь.
      </p>
    );
  }

  return (
    <div className="space-y-2">
      <div className="text-[11.5px] uppercase tracking-wide text-[var(--text-muted)]">Превью стикеров</div>
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-4">
        {variants.map((v, i) => {
          const key = variantKey(v, i);
          const active = pickedKey === key;
          return (
            <button
              key={key}
              type="button"
              onClick={() => onPick(key)}
              className={`rounded-[var(--radius)] border p-2 text-left transition-colors ${
                active
                  ? "border-[var(--text-primary)] bg-[var(--bg-elevated)]"
                  : "border-[var(--border)] hover:border-[var(--border-strong)]"
              }`}
              aria-pressed={active}
              aria-label={`Вариант ${i + 1}${active ? ", выбран" : ""}`}
            >
              <StickerThumb taskId={taskId} assetKey={key} />
              <div className="mt-1.5 flex items-center justify-between gap-2 text-[11.5px] text-[var(--text-muted)]">
                <span>Вариант {i + 1}</span>
                {active && <span className="text-[var(--text-primary)]">выбран</span>}
              </div>
            </button>
          );
        })}
      </div>
      {pickedKey && (
        <div className="flex flex-wrap gap-2">
          <Button
            type="button"
            size="sm"
            variant="secondary"
            onClick={() => downloadSticker(taskId, pickedKey)}
          >
            Скачать выбранный
          </Button>
        </div>
      )}
    </div>
  );
}

function StickerThumb({ taskId, assetKey }: { taskId: string; assetKey: string }) {
  const [src, setSrc] = useState<string | null>(null);
  const [err, setErr] = useState(false);

  useEffect(() => {
    let cancelled = false;
    let objectUrl: string | null = null;
    setSrc(null);
    setErr(false);
    const token = getPanelToken("admin");
    fetch(stickerAiAssetUrl(taskId, assetKey), {
      credentials: "include",
      headers: token ? { Authorization: `Bearer ${token}` } : {},
    })
      .then((r) => {
        if (!r.ok) throw new Error(String(r.status));
        return r.blob();
      })
      .then((blob) => {
        if (cancelled) return;
        objectUrl = URL.createObjectURL(blob);
        setSrc(objectUrl);
      })
      .catch(() => {
        if (!cancelled) setErr(true);
      });
    return () => {
      cancelled = true;
      if (objectUrl) URL.revokeObjectURL(objectUrl);
    };
  }, [taskId, assetKey]);

  if (err) {
    return (
      <div className="flex aspect-square items-center justify-center rounded bg-[var(--bg-elevated)] text-center text-[11px] text-[var(--text-muted)]">
        Файл недоступен
        <br />
        сгенерируйте снова
      </div>
    );
  }
  if (!src) {
    return (
      <div className="flex aspect-square items-center justify-center rounded bg-[var(--bg-elevated)] text-[var(--text-muted)]">
        <Loader2 className="h-5 w-5 animate-spin" aria-hidden />
      </div>
    );
  }
  return (
    <img
      src={src}
      alt="Превью стикера"
      className="aspect-square w-full rounded object-contain bg-[var(--bg-elevated)]"
    />
  );
}

async function downloadSticker(taskId: string, assetKey: string) {
  try {
    const token = getPanelToken("admin");
    const res = await fetch(stickerAiAssetUrl(taskId, assetKey), {
      credentials: "include",
      headers: token ? { Authorization: `Bearer ${token}` } : {},
    });
    if (!res.ok) throw new Error();
    const blob = await res.blob();
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = assetKey.split("/").pop() || "sticker.png";
    a.click();
    URL.revokeObjectURL(url);
  } catch {
    toast.error("Не удалось скачать стикер");
  }
}
