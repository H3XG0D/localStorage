import { useEffect, useRef, useState } from "react";
import { Bot, ImagePlus, ListTodo, Maximize2, Minimize2, Plus, Send, Sparkles, ThumbsUp, X } from "lucide-react";
import { Link, useLocation } from "react-router-dom";
import { toast } from "sonner";
import { PanelApiError } from "@/panel/lib/panelApi";
import {
  aiCreateSession,
  aiCreateTask,
  aiGetMessages,
  aiGrantConsent,
  aiListSessions,
  aiMarkUseful,
  aiPrivacy,
  aiSendMessage,
  aiStatus,
  type AiMessage,
  type AiSession,
} from "@/panel/lib/operatorApi";
import { Badge, Button, cx } from "@/panel/ui/primitives";

const OPEN_EVENT = "focuspay-ops-ai-open";
const STORAGE_KEY = "focuspay_ops_ai_open";

const PAGE_HINTS: Record<string, string> = {
  "/ops": "Дашборд: сводка смен/заявок",
  "/ops/orders": "Очередь и список заявок",
  "/ops/external": "Внештатные обмены HMAC: очередь, статистика клиента, видео, продление",
  "/ops/create": "Ручное создание заявки",
  "/ops/chat": "Чаты с клиентами",
  "/ops/payroll": "Зарплата оператора",
  "/ops/promo": "Промокоды и скидки",
  "/ops/dev-requests": "Inbox: очередь задач разработчикам, не баг-экран",
  "/ops/shifts": "Смены операторов",
  "/ops/reviews": "Модерация отзывов",
  "/ops/broadcast": "Рассылка",
  "/ops/profile": "Профиль оператора",
};

function buildUiContext(pathname: string, search: string) {
  const params = new URLSearchParams(search);
  const order = (params.get("order") || params.get("order_id") || "").trim();
  const clientMatch = pathname.match(/^\/ops\/clients?\/(-?\d+)/);
  const basePath = pathname.replace(/\/$/, "") || "/ops";
  const hint =
    PAGE_HINTS[basePath] ||
    (clientMatch ? "Карточка клиента" : basePath.startsWith("/ops/orders") ? "Заявки" : undefined);
  return {
    path: pathname,
    search: search || undefined,
    title: typeof document !== "undefined" ? document.title : undefined,
    hint,
    order_id: order || undefined,
    client_id: clientMatch ? Number(clientMatch[1]) : undefined,
  };
}

export function openOpsAi(prefill?: string) {
  window.dispatchEvent(new CustomEvent(OPEN_EVENT, { detail: { prefill } }));
}

export function OperatorAiWidget() {
  const location = useLocation();
  const [open, setOpen] = useState(() => {
    try {
      return sessionStorage.getItem(STORAGE_KEY) === "1";
    } catch {
      return false;
    }
  });
  const [expanded, setExpanded] = useState(false);
  const [sessions, setSessions] = useState<AiSession[]>([]);
  const [sessionId, setSessionId] = useState<number | null>(null);
  const [messages, setMessages] = useState<AiMessage[]>([]);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const [configured, setConfigured] = useState(true);
  const [booted, setBooted] = useState(false);
  const [needsConsent, setNeedsConsent] = useState(false);
  const [consentBusy, setConsentBusy] = useState(false);
  const [pendingFiles, setPendingFiles] = useState<File[]>([]);
  const [lastTaskId, setLastTaskId] = useState<number | null>(null);
  const bottomRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);
  const fileRef = useRef<HTMLInputElement>(null);

  const screenLabel =
    PAGE_HINTS[location.pathname.replace(/\/$/, "") || "/ops"] ||
    (location.pathname.startsWith("/ops/client")
      ? `Клиент ${location.pathname.split("/").pop()}`
      : location.pathname);

  function setOpenPersist(v: boolean) {
    setOpen(v);
    try {
      sessionStorage.setItem(STORAGE_KEY, v ? "1" : "0");
    } catch {
      /* ignore */
    }
  }

  useEffect(() => {
    const onOpen = (ev: Event) => {
      const detail = (ev as CustomEvent<{ prefill?: string }>).detail;
      setOpenPersist(true);
      if (detail?.prefill) setInput(detail.prefill);
      window.setTimeout(() => inputRef.current?.focus(), 50);
    };
    window.addEventListener(OPEN_EVENT, onOpen);
    return () => window.removeEventListener(OPEN_EVENT, onOpen);
  }, []);

  useEffect(() => {
    if (!open || booted) return;
    let cancelled = false;
    (async () => {
      try {
        const s = await aiStatus();
        if (!cancelled) setConfigured(!!s.configured);
      } catch {
        /* ignore */
      }
      try {
        const priv = await aiPrivacy();
        if (!cancelled) setNeedsConsent(!priv.has_valid_consent);
      } catch {
        /* ignore */
      }
      try {
        const r = await aiListSessions();
        if (cancelled) return;
        const list = r.sessions || [];
        setSessions(list);
        if (list[0]) {
          setSessionId(list[0].id);
        } else {
          const created = await aiCreateSession("Чат");
          if (cancelled) return;
          setSessionId(created.id);
          setSessions([created]);
        }
        setBooted(true);
      } catch (e) {
        if (!cancelled) {
          toast.error(e instanceof PanelApiError ? e.message : "Не удалось загрузить AI");
        }
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [open, booted]);

  async function grantConsent() {
    setConsentBusy(true);
    try {
      await aiGrantConsent(["llm"], "ops_ui");
      setNeedsConsent(false);
      toast.success("Согласие Ops AI сохранено");
    } catch (e) {
      toast.error(e instanceof PanelApiError ? e.message : "Не удалось сохранить согласие");
    } finally {
      setConsentBusy(false);
    }
  }

  useEffect(() => {
    if (!sessionId || !open) return;
    aiGetMessages(sessionId)
      .then((r) => setMessages(r.messages || []))
      .catch(() => setMessages([]));
  }, [sessionId, open]);

  useEffect(() => {
    if (open) bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, busy, open]);

  async function refreshSessions() {
    const r = await aiListSessions();
    setSessions(r.sessions || []);
    return r.sessions || [];
  }

  async function ensureSession(): Promise<number> {
    if (sessionId) return sessionId;
    const s = await aiCreateSession("Чат");
    setSessionId(s.id);
    await refreshSessions();
    return s.id;
  }

  async function onSend() {
    const text = input.trim();
    if ((!text && !pendingFiles.length) || busy) return;
    setBusy(true);
    setInput("");
    const files = pendingFiles.slice(0, 3);
    setPendingFiles([]);
    try {
      const sid = await ensureSession();
      const r = await aiSendMessage(
        sid,
        text || "Смотри скриншот — что не так?",
        buildUiContext(location.pathname, location.search),
        files.length ? files : undefined,
      );
      setMessages((prev) => [...prev, r.user, r.assistant]);
      if (r.escalated_task?.id) {
        setLastTaskId(r.escalated_task.id);
        toast.success(`Задача #${r.escalated_task.id} → /x8/ai-tasks`);
      }
      await refreshSessions();
    } catch (e) {
      const msg = e instanceof PanelApiError ? e.message : "Ошибка AI";
      if (e instanceof PanelApiError && e.status === 403 && /соглас/i.test(msg)) {
        setNeedsConsent(true);
      }
      toast.error(msg);
      setInput(text);
      setPendingFiles(files);
    } finally {
      setBusy(false);
    }
  }

  function addFiles(list: FileList | File[] | null) {
    if (!list) return;
    const next = [...pendingFiles];
    for (const f of Array.from(list)) {
      if (!f.type.startsWith("image/")) continue;
      if (f.size > 4 * 1024 * 1024) {
        toast.error(`${f.name}: больше 4 МБ`);
        continue;
      }
      if (next.length >= 3) {
        toast.error("Максимум 3 фото");
        break;
      }
      next.push(f);
    }
    setPendingFiles(next);
  }

  async function onNewChat() {
    try {
      const s = await aiCreateSession("Чат");
      setSessionId(s.id);
      setMessages([]);
      await refreshSessions();
    } catch (e) {
      toast.error(e instanceof PanelApiError ? e.message : "Ошибка");
    }
  }

  async function makeTaskFrom(msg: AiMessage) {
    const request =
      messages
        .filter((m) => m.role === "user")
        .slice(-3)
        .map((m) => m.content)
        .join("\n\n") || msg.content;
    setBusy(true);
    try {
      const task = await aiCreateTask({
        request_text: request,
        source_session_id: sessionId ?? undefined,
        source_message_id: msg.id,
        ui_context: buildUiContext(location.pathname, location.search),
      });
      toast.success(`Задача #${task.id} отправлена разработчикам`);
    } catch (e) {
      toast.error(e instanceof PanelApiError ? e.message : "Не удалось создать задачу");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="pointer-events-none fixed bottom-4 right-4 z-[60] flex flex-col items-end gap-3 md:bottom-5 md:right-5">
      {open && (
        <div
          className={cx(
            "pointer-events-auto flex w-[min(100vw-1.5rem,400px)] flex-col overflow-hidden rounded-[var(--radius-lg)] border border-[var(--border-strong)] bg-[var(--bg-surface)] shadow-[0_12px_40px_rgba(0,0,0,0.35)]",
            expanded ? "h-[min(92vh,720px)] w-[min(100vw-1.5rem,520px)]" : "h-[min(70vh,560px)]",
          )}
          role="dialog"
          aria-label="AI-помощник FocusPay"
        >
          <div className="flex items-center gap-2 border-b border-[var(--border)] px-3 py-2.5">
            <Bot className="size-4 shrink-0 text-[var(--accent)]" />
            <div className="min-w-0 flex-1">
              <div className="truncate text-[13px] font-semibold text-[var(--text-primary)]">AI-помощник</div>
              <div className="truncate text-[11px] text-[var(--text-muted)]" title={location.pathname + location.search}>
                {configured ? `Видит экран: ${screenLabel}` : "Offline / без ключа"}
              </div>
            </div>
            <button
              type="button"
              className="rounded p-1.5 text-[var(--text-muted)] hover:bg-[var(--bg-elevated)] hover:text-[var(--text-primary)]"
              title={expanded ? "Свернуть" : "Крупнее"}
              onClick={() => setExpanded((v) => !v)}
            >
              {expanded ? <Minimize2 className="size-3.5" /> : <Maximize2 className="size-3.5" />}
            </button>
            <button
              type="button"
              className="rounded p-1.5 text-[var(--text-muted)] hover:bg-[var(--bg-elevated)] hover:text-[var(--text-primary)]"
              title="Новый чат"
              onClick={onNewChat}
            >
              <Plus className="size-3.5" />
            </button>
            <Link
              to="/ops/dev-requests"
              className="rounded p-1.5 text-[var(--text-muted)] hover:bg-[var(--bg-elevated)] hover:text-[var(--text-primary)]"
              title="Мои задачи AI"
            >
              <ListTodo className="size-3.5" />
            </Link>
            <button
              type="button"
              className="rounded p-1.5 text-[var(--text-muted)] hover:bg-[var(--bg-elevated)] hover:text-[var(--text-primary)]"
              title="Закрыть"
              onClick={() => setOpenPersist(false)}
            >
              <X className="size-3.5" />
            </button>
          </div>

          {sessions.length > 1 && (
            <div className="flex gap-1 overflow-x-auto border-b border-[var(--border)] px-2 py-1.5">
              {sessions.slice(0, 8).map((s) => (
                <button
                  key={s.id}
                  type="button"
                  onClick={() => setSessionId(s.id)}
                  className={cx(
                    "shrink-0 rounded-full px-2.5 py-1 text-[11px]",
                    sessionId === s.id
                      ? "bg-[var(--accent)]/20 text-[var(--text-primary)]"
                      : "text-[var(--text-muted)] hover:bg-[var(--bg-elevated)]",
                  )}
                >
                  {(s.title || `#${s.id}`).slice(0, 18)}
                </button>
              ))}
            </div>
          )}

          {needsConsent && (
            <div className="border-b border-[var(--border)] bg-[var(--bg-elevated)] px-3 py-2.5">
              <p className="m-0 text-[12px] leading-relaxed text-[var(--text-secondary)]">
                Нужно согласие на обработку данных Ops AI (чат уходит в LLM). Без него ответы блокируются.
              </p>
              <Button size="sm" className="mt-2" disabled={consentBusy} onClick={grantConsent}>
                {consentBusy ? "Сохраняю…" : "Разрешить"}
              </Button>
            </div>
          )}

          <div className="flex-1 space-y-2.5 overflow-auto px-3 py-3">
            {!messages.length && (
              <div className="flex flex-col items-center gap-2 py-10 text-center text-[var(--text-muted)]">
                <Bot className="size-7 opacity-45" />
                <p className="m-0 text-[12.5px] leading-relaxed">
                  Спросите про курсы, смены, чеки, freeze…
                  <br />
                  Можно не уходить со страницы.
                </p>
              </div>
            )}
            {messages.map((m) => (
              <div key={m.id} className={cx("flex", m.role === "user" ? "justify-end" : "justify-start")}>
                <div
                  className={cx(
                    "max-w-[92%] rounded-[var(--radius)] px-3 py-2 text-[12.5px] leading-relaxed whitespace-pre-wrap",
                    m.role === "user"
                      ? "bg-[var(--accent)] text-[var(--text-inverse)]"
                      : "border border-[var(--border)] bg-[var(--bg-elevated)] text-[var(--text-primary)]",
                  )}
                >
                  {m.content}
                  {m.role === "assistant" && (
                    <div className="mt-2 flex flex-wrap gap-1 border-t border-[var(--border)]/50 pt-2">
                      {(m.sources_json || []).slice(0, 3).map((s, i) => (
                        <Badge key={i} tone="blue">
                          {s.path || s.title || "src"}
                        </Badge>
                      ))}
                      <Button
                        size="sm"
                        variant="ghost"
                        disabled={busy}
                        onClick={() =>
                          aiMarkUseful(sessionId!, m.id)
                            .then(() => toast.success("Отмечено"))
                            .catch((e) => toast.error(e instanceof PanelApiError ? e.message : "Ошибка"))
                        }
                      >
                        <ThumbsUp className="size-3" />
                      </Button>
                      <Button size="sm" variant="secondary" disabled={busy} onClick={() => makeTaskFrom(m)}>
                        <Sparkles className="size-3" /> Задача
                      </Button>
                    </div>
                  )}
                </div>
              </div>
            ))}
            {busy && <div className="text-[11px] text-[var(--text-muted)]">Думаю…</div>}
            {lastTaskId && (
              <div className="text-[11px] text-[var(--accent)]">Последняя эскалация: задача #{lastTaskId} → админка</div>
            )}
            <div ref={bottomRef} />
          </div>

          <div className="border-t border-[var(--border)] p-2.5">
            {!!pendingFiles.length && (
              <div className="mb-2 flex flex-wrap gap-2">
                {pendingFiles.map((f, i) => (
                  <div key={`${f.name}-${i}`} className="relative">
                    <img
                      src={URL.createObjectURL(f)}
                      alt=""
                      className="h-14 w-14 rounded object-cover border border-[var(--border)]"
                    />
                    <button
                      type="button"
                      className="absolute -right-1 -top-1 rounded-full bg-[var(--bg-surface)] p-0.5 text-[var(--text-muted)]"
                      onClick={() => setPendingFiles((prev) => prev.filter((_, j) => j !== i))}
                    >
                      <X className="size-3" />
                    </button>
                  </div>
                ))}
              </div>
            )}
            <div className="flex gap-2">
              <input
                ref={fileRef}
                type="file"
                accept="image/*"
                multiple
                className="hidden"
                onChange={(e) => {
                  addFiles(e.target.files);
                  e.target.value = "";
                }}
              />
              <button
                type="button"
                className="self-end rounded-[var(--radius)] border border-[var(--border-strong)] p-2 text-[var(--text-muted)] hover:bg-[var(--bg-elevated)] hover:text-[var(--text-primary)]"
                title="Прикрепить скрин"
                onClick={() => fileRef.current?.click()}
              >
                <ImagePlus className="size-4" />
              </button>
              <textarea
                ref={inputRef}
                value={input}
                onChange={(e) => setInput(e.target.value)}
                onPaste={(e) => {
                  const items = e.clipboardData?.files;
                  if (items?.length) {
                    const imgs = Array.from(items).filter((f) => f.type.startsWith("image/"));
                    if (imgs.length) {
                      e.preventDefault();
                      addFiles(imgs);
                    }
                  }
                }}
                onKeyDown={(e) => {
                  if (e.key === "Enter" && !e.shiftKey) {
                    e.preventDefault();
                    onSend();
                  }
                }}
                rows={2}
                placeholder="Вопрос, скрин или /grill-me"
                className="min-h-[40px] flex-1 resize-none rounded-[var(--radius)] border border-[var(--border-strong)] bg-[var(--bg-elevated)] px-2.5 py-2 text-[12.5px] text-[var(--text-primary)] outline-none focus:border-[var(--text-muted)]"
              />
              <Button
                variant="primary"
                disabled={busy || (!input.trim() && !pendingFiles.length)}
                onClick={onSend}
                className="self-end"
              >
                <Send className="size-3.5" />
              </Button>
            </div>
          </div>
        </div>
      )}

      <button
        type="button"
        className={cx(
          "pointer-events-auto flex size-12 items-center justify-center rounded-full border border-[var(--border-strong)] bg-[var(--accent)] text-[var(--text-inverse)] shadow-[0_8px_24px_rgba(0,0,0,0.35)] transition hover:bg-[var(--accent-hover)] active:scale-[0.96]",
          open && "ring-2 ring-[var(--accent)]/40",
        )}
        title={open ? "Скрыть AI" : "AI-помощник"}
        aria-label={open ? "Скрыть AI-помощник" : "Открыть AI-помощник"}
        onClick={() => {
          const next = !open;
          setOpenPersist(next);
          if (next) window.setTimeout(() => inputRef.current?.focus(), 50);
        }}
      >
        {open ? <X className="size-5" /> : <Bot className="size-5" />}
      </button>
    </div>
  );
}
