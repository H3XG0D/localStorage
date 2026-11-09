// Shared broadcast composer + job list (admin + operator share routes).
import { useCallback, useEffect, useRef, useState, type ReactNode } from "react";
import { BellRing, CalendarClock, CheckCheck, CircleAlert, Clock3, Copy, Eye, MessageCircle, Pencil, Repeat, Send, Sparkles, UsersRound, XCircle, type LucideIcon } from "lucide-react";
import { toast } from "sonner";
import {
  ALL_WEEKDAYS,
  applyAiDraft,
  BROADCAST_AI_PROFILE_DEFAULT,
  BROADCAST_STICKER_MODE_DEFAULT,
  buildCreateJobBody,
  buildCreateScheduleBody,
  buildPatchJobBody,
  destinationTitle,
  normalizeDestination,
  catalogIsEmpty,
  defaultMoscowSlotLocal,
  isoToMoscowDateTimeLocal,
  moscowDateTimeLocalToIso,
  parseStickerCatalog,
  plannedPreviewStickers,
  stickerDraftFromRow,
  stickerPreviewUrl,
  toggleWeekday,
  WEEKDAY_OPTIONS,
  weekdayLabels,
  type AiDraftResult,
  type BroadcastDestination,
  type BroadcastSendMode,
  type BroadcastSticker,
} from "@/panel/lib/adminBroadcast";
import { broadcastPlainPreview, PREMIUM_EMOJI, plainEmojiLeft, premiumInsert, toEditorText, toTelegramText, upgradePremiumEmoji } from "@/panel/lib/premiumEmoji";
import { getPanelToken, panelApi, PanelApiError, type PanelScope } from "@/panel/lib/panelApi";
import { Badge, Button, Card, Field, Input, Modal, PageHeader, Select, Table, type BadgeTone, type Column } from "@/panel/ui/primitives";

interface Segment { id?: string; key?: string; label?: string; count?: number; [k: string]: unknown }
interface Job {
  id: number;
  segment?: string;
  segment_label?: string;
  destination?: string;
  destination_label?: string;
  status?: string;
  message_text?: string;
  sent_count?: number;
  total_count?: number;
  failed_count?: number;
  created_at?: string;
  scheduled_at?: string | null;
  started_at?: string | null;
  finished_at?: string | null;
  error_summary?: string | null;
  sticker_status?: string;
  sender_label?: string;
  sticker_ids?: string[];
  sticker_mode?: string;
  stickers?: BroadcastSticker[];
  [k: string]: unknown;
}

interface Schedule {
  id: number;
  segment?: string;
  segment_label?: string;
  destination?: string;
  destination_label?: string;
  message_text?: string;
  time_local?: string;
  days_of_week?: number[];
  enabled?: boolean;
  sender_label?: string;
  sticker_ids?: string[];
  sticker_mode?: string;
  [k: string]: unknown;
}

function segmentKey(segment: Segment) {
  return segment.key || segment.id || "all";
}

function whereLabel(row: { destination?: string; segment_label?: string; segment?: string }) {
  if (normalizeDestination(row.destination) === "news") return destinationTitle("news");
  return row.segment_label || row.segment || destinationTitle("bot");
}

function jobTone(job: Job): BadgeTone {
  const status = String(job.status || "");
  if (status === "done") return "green";
  if (status === "failed") return "red";
  if (status === "cancelled") return "default";
  if (status === "running") return "yellow";
  if (status === "draft") return "blue";
  if (status === "pending" && isFutureSlot(job.scheduled_at)) return "blue";
  return "yellow";
}

function isFutureSlot(value?: string | null) {
  if (!value) return false;
  const date = new Date(value);
  return !Number.isNaN(date.getTime()) && date.getTime() > Date.now() + 15_000;
}

function jobStatusLabel(job: Job) {
  const status = String(job.status || "");
  if (status === "done") return "Завершена";
  if (status === "failed") return "Ошибка";
  if (status === "cancelled") return "Отменена";
  if (status === "running") return "Выполняется";
  if (status === "draft") return "Черновик";
  if (status === "pending" && isFutureSlot(job.scheduled_at)) return "Запланирована";
  return "В очереди";
}

function isQueuedJob(job: Job) {
  return ["draft", "pending", "running"].includes(String(job.status));
}

function canPatchJob(job: Job) {
  return String(job.status) === "pending" && !job.started_at;
}

function formatDate(value?: string | null) {
  if (!value) return "—";
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? "—" : date.toLocaleString("ru-RU", { day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" });
}

function jobPreviewSticker(job: Job, catalog: BroadcastSticker[]): BroadcastSticker | undefined {
  const fromJob = Array.isArray(job.stickers) ? job.stickers : [];
  for (const item of fromJob) {
    const id = String(item.id || "").trim();
    if (!id) continue;
    const fromCatalog = catalog.find((row) => row.id === id);
    return {
      id,
      label: item.label || fromCatalog?.label || id,
      emoji: item.emoji || fromCatalog?.emoji || "",
      preview_url: item.preview_url || fromCatalog?.preview_url || "",
    };
  }
  const sid = String((job.sticker_ids || [])[0] || "").trim();
  if (!sid) return undefined;
  return catalog.find((item) => item.id === sid) || { id: sid, preview_url: "" };
}

export function BroadcastPanel({ scope }: { scope: PanelScope }) {
  const [segments, setSegments] = useState<Segment[]>([]);
  const [segment, setSegment] = useState("all");
  const [destination, setDestination] = useState<BroadcastDestination>("bot");
  const [text, setText] = useState("");
  const [jobs, setJobs] = useState<Job[]>([]);
  const [busy, setBusy] = useState(false);
  const [count, setCount] = useState<number | null>(null);
  const [autoPick, setAutoPick] = useState(false);
  const [selectedStickerIds, setSelectedStickerIds] = useState<string[]>([]);
  const [catalog, setCatalog] = useState<BroadcastSticker[]>([]);
  const [catalogEmpty, setCatalogEmpty] = useState(false);
  const [previewStickers, setPreviewStickers] = useState<BroadcastSticker[]>([]);
  const [aiBusy, setAiBusy] = useState(false);
  const [aiDraft, setAiDraft] = useState<AiDraftResult | null>(null);
  const [aiError, setAiError] = useState<string | null>(null);
  const [mode, setMode] = useState<BroadcastSendMode>("now");
  const [onceLocal, setOnceLocal] = useState(defaultMoscowSlotLocal);
  const [repeatTime, setRepeatTime] = useState("10:00");
  const [repeatDays, setRepeatDays] = useState<number[]>(ALL_WEEKDAYS);
  const [schedules, setSchedules] = useState<Schedule[]>([]);
  const [editSlot, setEditSlot] = useState<Record<number, string>>({});
  const [editingJobId, setEditingJobId] = useState<number | null>(null);
  const [editingScheduleId, setEditingScheduleId] = useState<number | null>(null);
  const [previewJob, setPreviewJob] = useState<Job | null>(null);
  const [previewEdit, setPreviewEdit] = useState(false);
  const [previewText, setPreviewText] = useState("");
  const [previewSegment, setPreviewSegment] = useState("all");
  const [previewDestination, setPreviewDestination] = useState<BroadcastDestination>("bot");
  const [previewBusy, setPreviewBusy] = useState(false);
  const [previewCount, setPreviewCount] = useState<number | null>(null);
  const textRef = useRef<HTMLTextAreaElement>(null);
  const previewRef = useRef<HTMLTextAreaElement>(null);
  const caretRef = useRef<{ el: "main" | "preview"; pos: number } | null>(null);

  const p = useCallback(
    <T,>(path: string, opts: Omit<Parameters<typeof panelApi>[1], "scope"> = {}) => panelApi<T>(`/${scope}${path}`, { ...opts, scope }),
    [scope],
  );

  const loadJobs = useCallback(() => {
    p<{ jobs?: Job[] } | Job[]>("/broadcast/jobs", { query: { limit: 50 } })
      .then((r) => setJobs(Array.isArray(r) ? r : r.jobs || []))
      .catch(() => undefined);
  }, [p]);

  const loadSchedules = useCallback(() => {
    p<{ schedules?: Schedule[] } | Schedule[]>("/broadcast/schedules", { query: { limit: 50 } })
      .then((r) => setSchedules(Array.isArray(r) ? r : r.schedules || []))
      .catch(() => undefined);
  }, [p]);

  useEffect(() => {
    p<{ segments?: Segment[] } | Segment[]>("/broadcast/segments")
      .then((r) => setSegments(Array.isArray(r) ? r : r.segments || []))
      .catch(() => undefined);
    loadJobs();
    loadSchedules();
  }, [p, loadJobs, loadSchedules]);

  useEffect(() => {
    setCatalog([]);
    setCatalogEmpty(true);
  }, []);

  useEffect(() => {
    if (destination === "news") {
      setCount(1);
      return;
    }
    p<{ count?: number }>("/broadcast/preview", { method: "POST", body: { segment, destination } })
      .then((r) => setCount(r.count ?? null))
      .catch(() => setCount(null));
  }, [p, segment, destination]);

  useEffect(() => {
    if (!previewJob) {
      setPreviewCount(null);
      return;
    }
    if (previewDestination === "news") {
      setPreviewCount(1);
      return;
    }
    p<{ count?: number }>("/broadcast/preview", { method: "POST", body: { segment: previewSegment, destination: previewDestination } })
      .then((r) => setPreviewCount(r.count ?? null))
      .catch(() => setPreviewCount(null));
  }, [p, previewJob, previewSegment, previewDestination]);

  useEffect(() => {
    setPreviewStickers([]);
  }, []);

  const selectedSegment = segments.find((item) => segmentKey(item) === segment);
  const segmentLabel = destination === "news"
    ? "Новости FocusPay"
    : selectedSegment?.label || (segment === "all" ? "Все в боте" : segment);
  const previewSegmentMeta = segments.find((item) => segmentKey(item) === previewSegment);
  const previewSegmentLabel = previewDestination === "news"
    ? "Новости FocusPay"
    : previewSegmentMeta?.label || previewJob?.segment_label || previewSegment || "—";
  const hasMessage = text.trim().length > 0;
  const editingDraft = Boolean(editingJobId && jobs.some((job) => job.id === editingJobId && String(job.status) === "draft"));
  const queuedJobs = jobs.filter(isQueuedJob);
  const historyJobs = jobs.filter((job) => !isQueuedJob(job));
  const hasActiveJob = jobs.some((job) => ["pending", "running"].includes(String(job.status)));
  const previewSticker = previewStickers[0];

  useEffect(() => {
    const pending = caretRef.current;
    if (!pending) return;
    const el = pending.el === "main" ? textRef.current : previewRef.current;
    caretRef.current = null;
    if (!el) return;
    el.focus();
    el.setSelectionRange(pending.pos, pending.pos);
  }, [text, previewText]);

  function insertPremium(el: "main" | "preview", chunk: string) {
    const current = el === "main" ? text : previewText;
    const node = el === "main" ? textRef.current : previewRef.current;
    const start = node?.selectionStart ?? current.length;
    const end = node?.selectionEnd ?? current.length;
    const next = (current.slice(0, start) + chunk + current.slice(end)).slice(0, 4096);
    caretRef.current = { el, pos: Math.min(start + chunk.length, next.length) };
    if (el === "main") setText(next);
    else setPreviewText(next);
  }

  useEffect(() => {
    if (!hasActiveJob) return;
    // Broadcast progress is persisted by the API; poll only while a job is active.
    const timer = window.setInterval(loadJobs, 2000);
    return () => window.clearInterval(timer);
  }, [hasActiveJob, loadJobs]);

  function applyStickerDraft(_row: { sticker_ids?: unknown; sticker_mode?: unknown }) {
    setSelectedStickerIds([]);
    setAutoPick(false);
  }

  function liftDraft(job: Job) {
    setDestination(normalizeDestination(job.destination));
    setSegment(String(job.segment || "all"));
    setText(toEditorText(String(job.message_text || "")));
    applyStickerDraft(job);
    setAiDraft(null);
    setAiError(null);
    setEditingScheduleId(null);
    setEditingJobId(job.id);
    setMode("now");
    toast.success(`Черновик #${job.id} наверху. Выберите, куда отправить.`);
    window.setTimeout(() => document.getElementById("broadcast-composer")?.scrollIntoView({ behavior: "smooth", block: "start" }), 0);
  }

  function reuseJob(job: Job, edit: boolean) {
    setDestination(normalizeDestination(job.destination));
    setSegment(String(job.segment || "all"));
    setText(toEditorText(String(job.message_text || "")));
    applyStickerDraft(job);
    setAiDraft(null);
    setAiError(null);
    setEditingScheduleId(null);
    if (edit && String(job.status) === "pending") {
      setEditingJobId(job.id);
      if (isFutureSlot(job.scheduled_at)) {
        setMode("once");
        setOnceLocal(isoToMoscowDateTimeLocal(job.scheduled_at) || defaultMoscowSlotLocal());
      } else {
        setMode("now");
      }
      toast.success(`Правка #${job.id}. Не уйдёт, пока не сохраните.`);
    } else {
      setEditingJobId(null);
      setMode("now");
      toast.success(`Черновик из #${job.id}. Проверьте текст — повтор не уходит сам.`);
    }
    window.setTimeout(() => document.getElementById("broadcast-composer")?.scrollIntoView({ behavior: "smooth", block: "start" }), 0);
  }

  function openJobViewer(job: Job, edit = false) {
    setPreviewJob(job);
    setPreviewText(toEditorText(String(job.message_text || "")));
    setPreviewSegment(String(job.segment || "all"));
    setPreviewDestination(normalizeDestination(job.destination));
    setPreviewEdit(edit);
  }

  function closeJobViewer() {
    setPreviewJob(null);
    setPreviewEdit(false);
    setPreviewBusy(false);
  }

  async function saveJobViewer() {
    if (!previewJob) return;
    const nextText = previewText.trim();
    if (!nextText) return toast.error("Введите текст");
    setPreviewBusy(true);
    try {
      if (canPatchJob(previewJob)) {
        const body = buildPatchJobBody({
          segment: previewSegment,
          destination: previewDestination,
          text: toTelegramText(nextText),
          selectedStickerIds: [],
          autoPick: false,
        });
        await p(`/broadcast/jobs/${previewJob.id}`, { method: "PATCH", body });
        toast.success("Сохранено");
        closeJobViewer();
        loadJobs();
        return;
      }
      setDestination(previewDestination);
      setSegment(previewSegment);
      setText(toEditorText(nextText));
      applyStickerDraft(previewJob);
      setAiDraft(null);
      setAiError(null);
      setEditingJobId(null);
      setEditingScheduleId(null);
      setMode("now");
      closeJobViewer();
      toast.success("Сохранено в форму. В Telegram не уйдёт, пока не запустите.");
      window.setTimeout(() => document.getElementById("broadcast-composer")?.scrollIntoView({ behavior: "smooth", block: "start" }), 0);
    } catch (e) {
      toast.error(e instanceof PanelApiError ? e.message : "Ошибка");
    } finally {
      setPreviewBusy(false);
    }
  }

  function reuseSchedule(row: Schedule, edit: boolean) {
    setDestination(normalizeDestination(row.destination));
    setSegment(String(row.segment || "all"));
    setText(toEditorText(String(row.message_text || "")));
    applyStickerDraft(row);
    setAiDraft(null);
    setAiError(null);
    setRepeatTime(row.time_local || "10:00");
    setRepeatDays((row.days_of_week || []).length ? row.days_of_week || ALL_WEEKDAYS : ALL_WEEKDAYS);
    setEditingJobId(null);
    if (edit) {
      setEditingScheduleId(row.id);
      setMode("repeat");
      toast.success(`Правка повтора #${row.id}. Сохраните шаблон, без лишней отправки.`);
    } else {
      setEditingScheduleId(null);
      setMode("now");
      toast.success(`Черновик из повтора #${row.id}. Проверьте текст перед запуском.`);
    }
    window.setTimeout(() => document.getElementById("broadcast-composer")?.scrollIntoView({ behavior: "smooth", block: "start" }), 0);
  }

  function clearEditing() {
    setEditingJobId(null);
    setEditingScheduleId(null);
  }

  async function improveText() {
    if (!hasMessage) return toast.error("Введите текст");
    setAiBusy(true);
    setAiError(null);
    try {
      const draft = await p<AiDraftResult>("/broadcast/ai-draft", {
        method: "POST",
        body: {
          text: text.trim(),
          ai_enabled: true,
          ai_provider_profile: BROADCAST_AI_PROFILE_DEFAULT,
        },
      });
      setAiDraft(draft);
      if (draft.error || !draft.improved_text) {
        setAiError(draft.error || "Не удалось улучшить текст");
      }
    } catch (e) {
      setAiDraft(null);
      setAiError(e instanceof PanelApiError ? e.message : "AI недоступен");
    } finally {
      setAiBusy(false);
    }
  }

  function confirmAiDraft() {
    if (!aiDraft) return;
    const next = applyAiDraft(aiDraft, { text, selectedStickerIds, autoPick });
    if (!next) return toast.error(aiDraft.error || "Нечего применять");
    setText(toEditorText(next.text));
    setSelectedStickerIds([]);
    setAutoPick(false);
    setAiDraft(null);
    setAiError(null);
    toast.success("Черновик применён. Проверьте текст перед запуском.");
  }

  async function send() {
    if (!hasMessage) return toast.error("Введите текст");
    if (mode === "once" && !onceLocal.trim()) return toast.error("Укажите дату и время");
    setBusy(true);
    try {
      const scheduledAt = mode === "once" ? moscowDateTimeLocalToIso(onceLocal) : undefined;
      const editing = editingJobId ? jobs.find((job) => job.id === editingJobId) : undefined;
      if (editing && String(editing.status) === "draft" && mode !== "repeat") {
        await p(`/broadcast/jobs/${editing.id}`, {
          method: "PATCH",
          body: buildPatchJobBody({
            segment,
            destination,
            text: toTelegramText(text),
            selectedStickerIds: [],
            autoPick: false,
            scheduledAt: mode === "once" ? scheduledAt || null : null,
          }),
        });
        await p(`/broadcast/jobs/${editing.id}/launch`, { method: "POST" });
        toast.success(mode === "once" ? "Черновик запланирован" : "Черновик поставлен в очередь");
      } else if (editingJobId && mode !== "repeat") {
        const body = buildPatchJobBody({
          segment,
          destination,
          text: toTelegramText(text),
          selectedStickerIds: [],
          autoPick: false,
          scheduledAt: mode === "once" ? scheduledAt || null : null,
        });
        await p(`/broadcast/jobs/${editingJobId}`, { method: "PATCH", body });
        toast.success("Рассылка обновлена");
      } else {
        const body = buildCreateJobBody({ segment, destination, text: toTelegramText(text), selectedStickerIds: [], autoPick: false, scheduledAt });
        await p("/broadcast/jobs", { method: "POST", body });
        toast.success(mode === "once" ? "Рассылка запланирована" : "Рассылка поставлена в очередь");
      }
      setText("");
      setAiDraft(null);
      setAiError(null);
      clearEditing();
      setSelectedStickerIds([]);
      setAutoPick(false);
      loadJobs();
    } catch (e) {
      toast.error(e instanceof PanelApiError ? e.message : "Ошибка");
    } finally {
      setBusy(false);
    }
  }

  async function cancel(id: number) {
    try {
      await p(`/broadcast/jobs/${id}/cancel`, { method: "POST" });
      toast.success("Отменено");
      loadJobs();
    } catch (e) {
      toast.error(e instanceof PanelApiError ? e.message : "Ошибка");
    }
  }

  async function saveRepeat() {
    if (!hasMessage) return toast.error("Введите текст");
    if (!repeatTime.trim()) return toast.error("Укажите время повтора");
    setBusy(true);
    try {
      const body = buildCreateScheduleBody({
        segment,
        destination,
        text: toTelegramText(text),
        selectedStickerIds: [],
        autoPick: false,
        timeLocal: repeatTime,
        daysOfWeek: repeatDays,
      });
      if (editingScheduleId) {
        await p(`/broadcast/schedules/${editingScheduleId}`, { method: "PATCH", body });
        toast.success("Повтор обновлён");
      } else {
        await p("/broadcast/schedules", { method: "POST", body });
        toast.success("Повтор сохранён");
      }
      setText("");
      setAiDraft(null);
      setAiError(null);
      clearEditing();
      loadSchedules();
    } catch (e) {
      toast.error(e instanceof PanelApiError ? e.message : "Ошибка");
    } finally {
      setBusy(false);
    }
  }

  async function patchQueued(id: number, body: Record<string, unknown>) {
    try {
      await p(`/broadcast/jobs/${id}`, { method: "PATCH", body });
      toast.success("Обновлено");
      loadJobs();
    } catch (e) {
      toast.error(e instanceof PanelApiError ? e.message : "Ошибка");
    }
  }

  async function toggleSchedule(row: Schedule, enabled: boolean) {
    try {
      await p(`/broadcast/schedules/${row.id}`, { method: "PATCH", body: { enabled } });
      loadSchedules();
    } catch (e) {
      toast.error(e instanceof PanelApiError ? e.message : "Ошибка");
    }
  }

  async function removeSchedule(id: number) {
    try {
      await p(`/broadcast/schedules/${id}`, { method: "DELETE" });
      toast.success("Повтор удалён");
      loadSchedules();
    } catch (e) {
      toast.error(e instanceof PanelApiError ? e.message : "Ошибка");
    }
  }

  const cols: Column<Job>[] = [
    { key: "id", label: "#", width: "60px", render: (r) => <span className="font-mono text-[var(--text-muted)]">{r.id}</span> },
    {
      key: "segment",
      label: "Куда",
      render: (r) => (
        <button type="button" className="block max-w-[320px] text-left" onClick={(e) => { e.stopPropagation(); openJobViewer(r); }}>
          <div className="font-medium text-[var(--blue)] hover:underline">{whereLabel(r)}</div>
          {r.message_text && <div className="mt-0.5 truncate text-[11px] text-[var(--text-muted)]">{broadcastPlainPreview(r.message_text)}</div>}
        </button>
      ),
    },
    {
      key: "progress",
      label: "Доставка",
      width: "145px",
      render: (r) => {
        const sent = Number(r.sent_count ?? 0);
        const total = Number(r.total_count ?? 0);
        const progress = total > 0 ? Math.min(100, (sent / total) * 100) : 0;
        return (
          <div className="min-w-[100px]">
            <div className="font-mono tabular-nums">{sent} / {total || "—"}</div>
            <div className="mt-1 h-1 w-20 overflow-hidden rounded-full bg-[var(--bg-overlay)]">
              <div className="h-full rounded-full bg-[var(--green)]" style={{ width: `${progress}%` }} />
            </div>
            {Number(r.failed_count) > 0 && <div className="mt-1 text-[10px] text-[var(--red)]">Ошибок: {r.failed_count}</div>}
          </div>
        );
      },
    },
    { key: "status", label: "Статус", width: "130px", render: (r) => <Badge tone={jobTone(r)}>{jobStatusLabel(r)}</Badge> },
    { key: "created_at", label: "Слот", width: "105px", render: (r) => <span className="text-[11px] text-[var(--text-muted)]">{formatDate(r.scheduled_at || r.created_at)}</span> },
  ];

  return (
    <>
      <PageHeader
        title="Рассылка"
        subtitle="Сейчас, отложенный слот или повтор по дням. Время — Москва (UTC+3)."
        actions={<Badge tone="blue"><BellRing className="mr-1 size-3.5" /> {scope === "operator" ? "Операторская" : "Администраторская"}</Badge>}
      />

      <div className="grid items-start gap-4 xl:grid-cols-[minmax(0,1fr)_360px]">
        <div id="broadcast-composer">
        <Card className="overflow-hidden p-0">
          <div className="flex flex-wrap items-center justify-between gap-3 border-b border-[var(--border)] p-5 sm:p-6">
            <div className="flex items-center gap-3">
              <span className="flex size-9 items-center justify-center rounded-[var(--radius)] bg-[var(--blue-bg)] text-[var(--blue)]"><Send className="size-4" /></span>
              <div>
                <div className="text-[13.5px] font-semibold">
                  {editingDraft ? `Черновик #${editingJobId}` : editingJobId ? `Правка #${editingJobId}` : editingScheduleId ? `Правка повтора #${editingScheduleId}` : "Новое сообщение"}
                </div>
                <div className="mt-0.5 text-[11.5px] text-[var(--text-muted)]">
                  {editingDraft ? "Выберите, куда отправить, и запустите" : editingJobId || editingScheduleId ? "Сохраните изменения — повторная отправка сама не уйдёт" : "Соберите текст и выберите, когда отправить"}
                </div>
              </div>
            </div>
            <div className="flex items-center gap-2">
              {(editingJobId || editingScheduleId) && (
                <Button size="sm" variant="ghost" onClick={clearEditing}>Сбросить правку</Button>
              )}
              <Badge tone={hasMessage ? "green" : "default"}>{hasMessage ? `${text.length} / 4096` : "Черновик"}</Badge>
            </div>
          </div>
          <div className="space-y-5 p-5 sm:p-6">
            <div className="space-y-3">
              <div className="text-[12px] font-semibold">Куда отправить</div>
              <div className="flex flex-wrap gap-2">
                {([
                  ["bot", "В бота"],
                  ["news", "В новости"],
                ] as const).map(([id, label]) => (
                  <Button key={id} size="sm" variant={destination === id ? "primary" : "secondary"} onClick={() => setDestination(id)}>
                    {id === "news" ? <MessageCircle className="size-3.5" /> : <Send className="size-3.5" />}
                    {label}
                  </Button>
                ))}
              </div>
            </div>
            <div className={`grid gap-4 ${destination === "bot" ? "md:grid-cols-[minmax(0,1fr)_190px]" : ""}`}>
              {destination === "bot" ? (
                <Field label="Сегмент">
                  <Select value={segment} onChange={(e) => setSegment(e.target.value)} aria-label="Сегмент">
                    {(segments.length ? segments : [{ id: "all", label: "Все в боте" }]).map((s) => {
                      const key = segmentKey(s);
                      return (
                        <option key={key} value={key}>
                          {s.label || key}
                          {s.count != null ? ` (${s.count})` : ""}
                        </option>
                      );
                    })}
                  </Select>
                </Field>
              ) : (
                <div className="text-[12.5px] leading-5 text-[var(--text-muted)]">Один пост в канал «FocusPay новости проекта».</div>
              )}
              <div className="flex items-end">
                <div className="flex w-full items-center gap-2 rounded-[var(--radius)] border border-[var(--border)] bg-[var(--bg-elevated)] px-3 py-2 text-[12px]">
                  <UsersRound className="size-4 shrink-0 text-[var(--blue)]" />
                  <div className="min-w-0">
                    <div className="truncate font-medium">
                      {destination === "news" ? "1 пост в новости FocusPay" : count == null ? "Считаем…" : `${count} получателей`}
                    </div>
                    {destination === "bot" && <div className="truncate text-[10.5px] text-[var(--text-muted)]">{segmentLabel}</div>}
                  </div>
                </div>
              </div>
            </div>
            <div className="space-y-3 rounded-[var(--radius)] border border-[var(--border)] bg-[var(--bg-elevated)] p-4">
              <div className="text-[12px] font-semibold">Когда отправить</div>
              <div className="flex flex-wrap gap-2">
                {([
                  ["now", "Сейчас"],
                  ["once", "Один раз"],
                  ["repeat", "Повтор"],
                ] as const).map(([id, label]) => (
                  <Button key={id} size="sm" variant={mode === id ? "primary" : "secondary"} onClick={() => setMode(id)}>
                    {id === "once" ? <CalendarClock className="size-3.5" /> : id === "repeat" ? <Repeat className="size-3.5" /> : <Send className="size-3.5" />}
                    {label}
                  </Button>
                ))}
              </div>
              {mode === "once" && (
                <Field label="Дата и время (Москва)">
                  <Input type="datetime-local" value={onceLocal} onChange={(e) => setOnceLocal(e.target.value)} />
                </Field>
              )}
              {mode === "repeat" && (
                <div className="grid gap-3 sm:grid-cols-[140px_minmax(0,1fr)]">
                  <Field label="Время (Москва)">
                    <Input type="time" value={repeatTime} onChange={(e) => setRepeatTime(e.target.value)} />
                  </Field>
                  <Field label="Дни недели">
                    <div className="flex flex-wrap gap-1.5">
                      {WEEKDAY_OPTIONS.map((day) => {
                        const active = repeatDays.includes(day.id);
                        return (
                          <button
                            key={day.id}
                            type="button"
                            onClick={() => setRepeatDays((current) => toggleWeekday(current, day.id))}
                            className={`h-8 min-w-8 rounded-[var(--radius)] border px-2 text-[12px] ${active ? "border-[var(--blue)] bg-[var(--blue-bg)] text-[var(--blue)]" : "border-[var(--border)] text-[var(--text-muted)]"}`}
                          >
                            {day.label}
                          </button>
                        );
                      })}
                    </div>
                  </Field>
                </div>
              )}
            </div>
            <Field label="Текст сообщения">
              <textarea
                ref={textRef}
                value={text}
                onChange={(e) => setText(e.target.value)}
                rows={8}
                maxLength={4096}
                aria-label="Текст сообщения для Telegram"
                placeholder="Напишите сообщение для клиентов…"
                className="min-h-[190px] w-full resize-y rounded-[var(--radius)] border border-[var(--border-strong)] bg-[var(--bg-elevated)] p-3.5 text-[13px] leading-6 text-[var(--text-primary)] placeholder:text-[var(--text-muted)] outline-none transition-colors focus:border-[var(--blue)]"
              />
              <div className="mt-1.5 flex items-center justify-between gap-3 text-[10.5px] text-[var(--text-muted)]">
                <span className="inline-flex items-center gap-1.5"><CircleAlert className="size-3.5" /> Жирный через &lt;b&gt;. Смайлы с клавиатуры в Telegram плоские.</span>
                <span className={text.length >= 3900 ? "text-[var(--yellow)]" : ""}>{text.length} / 4096</span>
              </div>
              <PremiumEmojiBar onInsert={(chunk) => insertPremium("main", chunk)} />
              <div className="mt-3 flex flex-wrap items-center gap-2">
                <Button size="sm" disabled={aiBusy || !hasMessage} onClick={improveText}>
                  <Sparkles className="size-3.5" /> {aiBusy ? "Улучшаем…" : "Улучшить текст"}
                </Button>
                <span className="text-[11px] text-[var(--text-muted)]">Черновик не уходит в рассылку, пока не нажмёте «Применить».</span>
              </div>
              {aiError && <div className="mt-2 text-[12px] text-[var(--red)]">{aiError}</div>}
              {aiDraft?.improved_text && !aiDraft.error && (
                <div className="mt-3 space-y-2 rounded-[var(--radius)] border border-[var(--border)] bg-[var(--bg-base)] p-3">
                  <div className="text-[11px] font-semibold uppercase tracking-wide text-[var(--text-muted)]">Результат AI</div>
                  <div className="whitespace-pre-wrap text-[12.5px] leading-5">{renderTelegramText(aiDraft.improved_text)}</div>
                  <div className="flex gap-2">
                    <Button size="sm" variant="primary" onClick={confirmAiDraft}>Применить</Button>
                    <Button size="sm" variant="ghost" onClick={() => { setAiDraft(null); setAiError(null); }}>Отклонить</Button>
                  </div>
                </div>
              )}
            </Field>
            <div className="flex flex-wrap items-center justify-between gap-3 border-t border-[var(--border)] pt-4">
              <span className="text-[11.5px] text-[var(--text-muted)]">
                {destination === "news"
                  ? (mode === "repeat" ? "Шаблон будет публиковаться в новости в выбранные дни." : "Один пост в группу новостей FocusPay.")
                  : (mode === "repeat" ? "Шаблон будет уходить в выбранные дни." : "Получатели увидят это сообщение от FocusPay.")}
              </span>
              {mode === "repeat" ? (
                <Button variant="primary" disabled={busy || !hasMessage} onClick={saveRepeat}>
                  <Repeat className="size-3.5" /> {busy ? "Сохраняем…" : editingScheduleId ? "Сохранить правку" : "Сохранить повтор"}
                </Button>
              ) : (
                <Button variant="primary" disabled={busy || !hasMessage} onClick={send}>
                  <Send className="size-3.5" /> {busy ? "Сохраняем…" : editingDraft ? (mode === "once" ? "Запланировать" : "Запустить рассылку") : editingJobId ? "Сохранить правку" : mode === "once" ? "Запланировать" : "Запустить рассылку"}
                </Button>
              )}
            </div>
          </div>
        </Card>
        </div>

        <TelegramPreview
          scope={scope}
          text={text}
          segmentLabel={segmentLabel}
          count={destination === "news" ? 1 : count}
          countLabel={destination === "news" ? "Постов" : "Получателей"}
          metaLabel={destination === "news" ? "Куда" : "Сегмент"}
          peerLabel={destination === "news" ? "новости" : "бот"}
        />
      </div>

      <Card className="overflow-hidden p-0">
        <div className="flex flex-wrap items-center justify-between gap-3 border-b border-[var(--border)] p-5 sm:p-6">
          <div className="flex items-center gap-3">
            <span className="flex size-9 items-center justify-center rounded-[var(--radius)] bg-[var(--blue-bg)] text-[var(--blue)]"><CalendarClock className="size-4" /></span>
            <div>
              <div className="text-[13.5px] font-semibold">Очередь</div>
              <div className="mt-0.5 text-[11.5px] text-[var(--text-muted)]">Запланированные и ожидающие отправки</div>
            </div>
          </div>
          <Badge tone={queuedJobs.length ? "yellow" : "default"}>{queuedJobs.length ? `${queuedJobs.length} в очереди` : "Пусто"}</Badge>
        </div>
        <div className="divide-y divide-[var(--border)]">
          {queuedJobs.length === 0 && (
            <div className="px-5 py-8 text-center text-[13px] text-[var(--text-muted)]">Очередь пуста</div>
          )}
          {queuedJobs.map((job) => {
            const slotValue = editSlot[job.id] ?? (isoToMoscowDateTimeLocal(job.scheduled_at) || defaultMoscowSlotLocal());
            return (
              <div key={job.id} className="flex flex-wrap items-center gap-3 px-5 py-3 sm:px-6">
                <div className="min-w-0 flex-1">
                  <button type="button" className="block w-full min-w-0 text-left" onClick={() => String(job.status) === "draft" ? liftDraft(job) : openJobViewer(job)}>
                    <div className="flex flex-wrap items-center gap-2">
                      <span className="font-mono text-[11px] text-[var(--text-muted)]">#{job.id}</span>
                      <Badge tone={jobTone(job)}>{jobStatusLabel(job)}</Badge>
                      <span className="text-[12px] font-medium text-[var(--blue)] hover:underline">{whereLabel(job)}</span>
                    </div>
                    {job.message_text && <div className="mt-1 max-w-[520px] truncate text-[12px] text-[var(--text-muted)]">{broadcastPlainPreview(job.message_text)}</div>}
                  </button>
                </div>
                {String(job.status) === "draft" && (
                  <Button size="sm" variant="primary" onClick={() => liftDraft(job)}>В форму</Button>
                )}
                {String(job.status) === "pending" && (
                  <div className="flex flex-wrap items-center gap-2">
                    <Input
                      type="datetime-local"
                      className="w-[190px]"
                      value={slotValue}
                      onChange={(e) => setEditSlot((current) => ({ ...current, [job.id]: e.target.value }))}
                    />
                    <Button size="sm" onClick={() => patchQueued(job.id, { scheduled_at: moscowDateTimeLocalToIso(slotValue) })}>Слот</Button>
                    <Button size="sm" onClick={() => patchQueued(job.id, { scheduled_at: null })}>Сразу</Button>
                    <Button size="sm" onClick={() => openJobViewer(job, true)}><Pencil className="size-3.5" /> Изменить</Button>
                    <Button size="sm" onClick={() => reuseJob(job, false)}><Copy className="size-3.5" /> Повторить</Button>
                  </div>
                )}
                {String(job.status) === "running" && (
                  <Button size="sm" onClick={() => reuseJob(job, false)}><Copy className="size-3.5" /> Повторить</Button>
                )}
                {["draft", "pending", "running"].includes(String(job.status)) && (
                  <Button size="sm" variant="danger" onClick={() => cancel(job.id)}><XCircle className="size-3.5" /> Отмена</Button>
                )}
              </div>
            );
          })}
        </div>
      </Card>

      <Card className="overflow-hidden p-0">
        <div className="flex flex-wrap items-center justify-between gap-3 border-b border-[var(--border)] p-5 sm:p-6">
          <div className="flex items-center gap-3">
            <span className="flex size-9 items-center justify-center rounded-[var(--radius)] bg-[var(--bg-elevated)] text-[var(--text-secondary)]"><Repeat className="size-4" /></span>
            <div>
              <div className="text-[13.5px] font-semibold">Повторы</div>
              <div className="mt-0.5 text-[11.5px] text-[var(--text-muted)]">Ежедневные шаблоны, время Москвы</div>
            </div>
          </div>
          <Badge>{schedules.length} шаблонов</Badge>
        </div>
        <div className="divide-y divide-[var(--border)]">
          {schedules.length === 0 && (
            <div className="px-5 py-8 text-center text-[13px] text-[var(--text-muted)]">Повторов пока нет</div>
          )}
          {schedules.map((row) => (
            <div key={row.id} className="flex flex-wrap items-center gap-3 px-5 py-3 sm:px-6">
              <div className="min-w-0 flex-1">
                <div className="flex flex-wrap items-center gap-2">
                  <Badge tone={row.enabled ? "green" : "default"}>{row.enabled ? "Вкл" : "Выкл"}</Badge>
                  <span className="font-mono text-[12px]">{row.time_local || "—"}</span>
                  <span className="text-[12px] text-[var(--text-muted)]">{weekdayLabels(row.days_of_week || [])}</span>
                  <span className="text-[12px] font-medium">{whereLabel(row)}</span>
                </div>
                {row.message_text && <div className="mt-1 max-w-[520px] truncate text-[12px] text-[var(--text-muted)]">{broadcastPlainPreview(row.message_text)}</div>}
              </div>
              <Button size="sm" onClick={() => reuseSchedule(row, false)}><Copy className="size-3.5" /> Повторить</Button>
              <Button size="sm" onClick={() => reuseSchedule(row, true)}><Pencil className="size-3.5" /> Изменить</Button>
              <Button size="sm" onClick={() => toggleSchedule(row, !row.enabled)}>{row.enabled ? "Выключить" : "Включить"}</Button>
              <Button size="sm" variant="danger" onClick={() => removeSchedule(row.id)}>Удалить</Button>
            </div>
          ))}
        </div>
      </Card>

      <Card className="overflow-hidden p-0">
        <div className="flex flex-wrap items-center justify-between gap-3 border-b border-[var(--border)] p-5 sm:p-6">
          <div className="flex items-center gap-3">
            <span className="flex size-9 items-center justify-center rounded-[var(--radius)] bg-[var(--bg-elevated)] text-[var(--text-secondary)]"><Clock3 className="size-4" /></span>
            <div>
              <div className="text-[13.5px] font-semibold">История рассылок</div>
              <div className="mt-0.5 text-[11.5px] text-[var(--text-muted)]">Нажмите на строку, чтобы открыть и изменить</div>
            </div>
          </div>
          <Badge tone={hasActiveJob ? "yellow" : "default"}>{hasActiveJob ? "Обновляется" : `${jobs.length} задач`}</Badge>
        </div>
        <Table columns={cols} rows={historyJobs} empty="Истории пока нет" onRowClick={(row) => openJobViewer(row)} />
      </Card>

      <Modal
        open={!!previewJob}
        title={previewJob ? `Рассылка #${previewJob.id}` : "Рассылка"}
        size="lg"
        onClose={closeJobViewer}
        footer={previewJob ? (
          previewEdit ? (
            <>
              <Button onClick={() => { setPreviewText(toEditorText(String(previewJob.message_text || ""))); setPreviewSegment(String(previewJob.segment || "all")); setPreviewDestination(normalizeDestination(previewJob.destination)); setPreviewEdit(false); }}>Отмена</Button>
              <Button variant="primary" disabled={previewBusy || !previewText.trim()} onClick={saveJobViewer}>
                {previewBusy ? "Сохраняем…" : "Сохранить"}
              </Button>
            </>
          ) : (
            <>
              <Button onClick={closeJobViewer}>Закрыть</Button>
              <Button variant="primary" onClick={() => setPreviewEdit(true)}>
                <Pencil className="size-3.5" /> Изменить
              </Button>
            </>
          )
        ) : undefined}
      >
        {previewJob && (
          <div className="space-y-4">
            <div className="flex flex-wrap items-center gap-2">
              <Badge tone={jobTone(previewJob)}>{jobStatusLabel(previewJob)}</Badge>
              <span className="text-[12px] text-[var(--text-muted)]">{previewSegmentLabel}</span>
              <span className="text-[12px] text-[var(--text-muted)]">{formatDate(previewJob.finished_at || previewJob.scheduled_at || previewJob.created_at)}</span>
            </div>
            {previewJob.error_summary && (
              <div className="rounded-[var(--radius)] border border-[var(--red)]/30 bg-[var(--red-bg)] px-3 py-2 text-[12px] text-[var(--red)]">{previewJob.error_summary}</div>
            )}
            {previewEdit && (
              <div className="space-y-3">
                <div className="space-y-2">
                  <div className="text-[12px] font-semibold">Куда отправить</div>
                  <div className="flex flex-wrap gap-2">
                    {([
                      ["bot", "В бота"],
                      ["news", "В новости"],
                    ] as const).map(([id, label]) => (
                      <Button key={id} size="sm" variant={previewDestination === id ? "primary" : "secondary"} onClick={() => setPreviewDestination(id)}>
                        {label}
                      </Button>
                    ))}
                  </div>
                </div>
                {previewDestination === "bot" && (
                <Field label="Сегмент">
                  <Select value={previewSegment} onChange={(e) => setPreviewSegment(e.target.value)} aria-label="Сегмент">
                    {(segments.length ? segments : [{ id: "all", label: "Все в боте" }]).map((s) => {
                      const key = segmentKey(s);
                      return (
                        <option key={key} value={key}>
                          {s.label || key}
                          {s.count != null ? ` (${s.count})` : ""}
                        </option>
                      );
                    })}
                  </Select>
                </Field>
                )}
                <Field label="Текст сообщения">
                  <textarea
                    ref={previewRef}
                    value={previewText}
                    onChange={(e) => setPreviewText(e.target.value)}
                    rows={8}
                    maxLength={4096}
                    aria-label="Текст рассылки"
                    className="min-h-[160px] w-full resize-y rounded-[var(--radius)] border border-[var(--border-strong)] bg-[var(--bg-elevated)] p-3.5 text-[13px] leading-6 text-[var(--text-primary)] outline-none transition-colors focus:border-[var(--blue)]"
                  />
                  <div className="mt-1.5 text-[10.5px] text-[var(--text-muted)]">{previewText.length} / 4096</div>
                  <PremiumEmojiBar onInsert={(chunk) => insertPremium("preview", chunk)} />
                </Field>
                {!canPatchJob(previewJob) && (
                  <div className="text-[12px] text-[var(--text-muted)]">Уже отправленное в Telegram сообщение не изменится. Сохранение откроет копию в форме сверху.</div>
                )}
              </div>
            )}
            <TelegramPreview
              scope={scope}
              text={previewEdit ? previewText : String(previewJob.message_text || "")}
              segmentLabel={previewSegmentLabel}
              countLabel={previewDestination === "news" ? "Постов" : canPatchJob(previewJob) || previewEdit ? "Получателей" : "Доставка"}
              count={previewDestination === "news" && (canPatchJob(previewJob) || previewEdit) ? 1 : canPatchJob(previewJob) || previewEdit ? previewCount : `${Number(previewJob.sent_count ?? 0)} / ${Number(previewJob.total_count ?? 0) || "—"}`}
              metaLabel={previewDestination === "news" ? "Куда" : "Сегмент"}
              peerLabel={previewDestination === "news" ? "новости" : "бот"}
              live={previewEdit}
              timeLabel={previewEdit ? "сейчас" : formatDate(previewJob.finished_at || previewJob.started_at || previewJob.created_at)}
            />
          </div>
        )}
      </Modal>
    </>
  );
}

function PremiumEmojiBar({ onInsert }: { onInsert: (chunk: string) => void }) {
  return (
    <div className="mt-3 space-y-2">
      <div className="text-[11px] leading-4 text-[var(--text-muted)]">
        Премиум-эмодзи Telegram. В чате это стикеры пака бота, не смайлы с клавиатуры.
      </div>
      <div className="flex flex-wrap gap-1.5">
        {PREMIUM_EMOJI.map((item) => (
          <button
            key={item.key}
            type="button"
            title={item.label}
            aria-label={item.label}
            onClick={() => onInsert(premiumInsert(item))}
            className="inline-flex h-8 min-w-8 items-center justify-center rounded-[var(--radius)] border border-[var(--border)] bg-[var(--bg-base)] px-1.5 text-[15px] leading-none transition-colors hover:border-[var(--blue)]"
          >
            {item.fallback}
          </button>
        ))}
      </div>
    </div>
  );
}

function TelegramPreview({
  scope,
  text,
  segmentLabel,
  count,
  sticker: _ignoredSticker,
  live = true,
  timeLabel = "сейчас",
  countLabel = "Получателей",
  metaLabel = "Сегмент",
  peerLabel = "бот",
}: {
  scope: PanelScope;
  text: string;
  segmentLabel: string;
  count: number | string | null;
  sticker?: BroadcastSticker;
  live?: boolean;
  timeLabel?: string;
  countLabel?: string;
  metaLabel?: string;
  peerLabel?: string;
}) {
  const [blobSrc, setBlobSrc] = useState("");
  const telegramText = upgradePremiumEmoji(text);
  const leftoverEmoji = plainEmojiLeft(telegramText);
  const sticker = undefined as BroadcastSticker | undefined;
  const previewPath = sticker ? stickerPreviewUrl(scope, sticker.id, sticker.preview_url) : "";
  useEffect(() => {
    if (!previewPath) {
      setBlobSrc("");
      return;
    }
    let revoked = false;
    let objectUrl = "";
    const token = getPanelToken(scope);
    const headers = new Headers();
    if (token) headers.set("Authorization", `Bearer ${token}`);
    fetch(previewPath, { headers, credentials: "include" })
      .then((res) => (res.ok ? res.blob() : null))
      .then((blob) => {
        if (!blob || revoked) return;
        objectUrl = URL.createObjectURL(blob);
        setBlobSrc(objectUrl);
      })
      .catch(() => undefined);
    return () => {
      revoked = true;
      if (objectUrl) URL.revokeObjectURL(objectUrl);
    };
  }, [previewPath, scope]);
  const previewSrc = blobSrc;
  return (
    <Card className="overflow-hidden p-0">
      <div className="flex items-center justify-between gap-3 border-b border-[var(--border)] p-5 sm:p-6">
        <div className="flex items-center gap-3">
          <span className="flex size-9 items-center justify-center rounded-[var(--radius)] bg-[var(--blue-bg)] text-[var(--blue)]"><Eye className="size-4" /></span>
          <div>
            <div className="text-[13.5px] font-semibold">Предпросмотр Telegram</div>
            <div className="mt-0.5 text-[11.5px] text-[var(--text-muted)]">Как сообщение увидит клиент</div>
          </div>
        </div>
        <Badge tone={live ? "blue" : "default"}>{live ? "LIVE" : "АРХИВ"}</Badge>
      </div>
      <div className="bg-[var(--bg-elevated)] p-4 sm:p-5">
        <div className="mx-auto max-w-[320px] overflow-hidden rounded-[var(--radius-lg)] border border-[var(--border-strong)] bg-[var(--bg-base)] shadow-[var(--shadow)]">
          <div className="flex items-center gap-2.5 border-b border-[var(--border)] bg-[var(--bg-surface)] px-3.5 py-3">
            <span className="flex size-8 items-center justify-center rounded-full bg-[var(--blue)] text-[var(--text-inverse)]"><MessageCircle className="size-4" /></span>
            <div className="min-w-0">
              <div className="text-[12px] font-semibold">FocusPay <span className="text-[var(--blue)]">✓</span></div>
              <div className="text-[10px] text-[var(--text-muted)]">{peerLabel}</div>
            </div>
          </div>
          <div className="min-h-[220px] space-y-2 bg-[var(--bg-overlay)] p-3">
            {sticker && previewSrc && (
              <div className="ml-auto max-w-[92%] rounded-[var(--radius-lg)] bg-[var(--bg-surface)] p-2 shadow-[var(--shadow)]">
                <img src={previewSrc} alt={sticker.emoji || sticker.label || "Стикер"} className="mx-auto size-20 object-contain" />
              </div>
            )}
            <div className="ml-auto max-w-[92%] rounded-[var(--radius-lg)] rounded-br-[var(--radius-sm)] bg-[var(--blue-bg)] px-3 py-2.5 text-[12.5px] leading-5 text-[var(--text-primary)] shadow-[var(--shadow)]">
              <div className="break-words whitespace-pre-wrap">{renderTelegramText(telegramText)}</div>
              <div className="mt-1 flex items-center justify-end gap-1 text-[10px] text-[var(--blue)]"><span>{timeLabel}</span><CheckCheck className="size-3.5" /></div>
            </div>
          </div>
        </div>
        {leftoverEmoji.length > 0 && (
          <div className="mx-auto mt-3 max-w-[320px] text-[11px] leading-4 text-[var(--yellow)]">
            В Telegram останутся обычными: {leftoverEmoji.join(" ")}. Это смайлы с клавиатуры — замените их кнопками премиум-пака.
          </div>
        )}
      </div>
      <div className="grid grid-cols-2 gap-px border-t border-[var(--border)] bg-[var(--border)]">
        <PreviewMeta icon={UsersRound} label={metaLabel} value={segmentLabel} />
        <PreviewMeta icon={UsersRound} label={countLabel} value={count == null ? "—" : String(count)} />
      </div>
    </Card>
  );
}

function PreviewMeta({ icon: Icon, label, value }: { icon: LucideIcon; label: string; value: string }) {
  return (
    <div className="min-w-0 bg-[var(--bg-surface)] px-3.5 py-3">
      <div className="flex items-center gap-1.5 text-[10px] font-semibold uppercase tracking-wide text-[var(--text-muted)]"><Icon className="size-3" /> {label}</div>
      <div className="mt-1 truncate font-mono text-[12px] text-[var(--text-primary)]">{value}</div>
    </div>
  );
}

function renderTelegramText(value: string): ReactNode {
  if (!value.trim()) return <span className="text-[var(--text-muted)]">Текст сообщения появится здесь</span>;
  if (typeof DOMParser === "undefined") return value;
  const body = new DOMParser().parseFromString(value, "text/html").body;
  return Array.from(body.childNodes).map((node, index) => renderTelegramNode(node, index));
}

function renderTelegramNode(node: ChildNode, key: number): ReactNode {
  if (node.nodeType === Node.TEXT_NODE) return node.textContent;
  if (node.nodeType !== Node.ELEMENT_NODE) return null;
  const element = node as HTMLElement;
  const children = Array.from(element.childNodes).map((child, index) => renderTelegramNode(child, index));
  switch (element.tagName.toLowerCase()) {
    case "script":
    case "style":
    case "iframe":
    case "object":
    case "embed":
    case "link":
    case "meta":
    case "form":
    case "input": return null;
    case "br": return <br key={key} />;
    case "p":
    case "div":
    case "li":
    case "h1":
    case "h2":
    case "h3":
    case "h4":
    case "h5":
    case "h6": return <span key={key}>{children}<br /></span>;
    case "b":
    case "strong": return <strong key={key}>{children}</strong>;
    case "i":
    case "em": return <em key={key}>{children}</em>;
    case "u": return <u key={key}>{children}</u>;
    case "s":
    case "strike":
    case "del": return <s key={key}>{children}</s>;
    case "code": return <code key={key} className="rounded bg-[var(--bg-overlay)] px-1 py-0.5 font-mono text-[11px]">{children}</code>;
    case "blockquote": return <blockquote key={key} className="border-l-2 border-[var(--blue)] pl-2 text-[var(--text-secondary)]">{children}</blockquote>;
    case "a": {
      const href = element.getAttribute("href") || "";
      return /^https?:\/\//i.test(href) ? <a key={key} href={href} target="_blank" rel="noreferrer" className="text-[var(--blue)] underline">{children}</a> : <span key={key}>{children}</span>;
    }
    case "tg-emoji":
      return (
        <span key={key} title="Премиум-эмодзи Telegram" className="mx-px inline-flex h-5 min-w-5 items-center justify-center rounded-full bg-[var(--bg-surface)] px-0.5 align-middle text-[13px] leading-none">
          {children}
        </span>
      );
    default: return <span key={key}>{children}</span>;
  }
}
