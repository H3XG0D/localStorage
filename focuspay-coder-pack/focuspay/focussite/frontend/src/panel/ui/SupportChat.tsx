import { useCallback, useEffect, useRef, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { toast } from "sonner";
import { getPanelToken, type PanelScope } from "@/panel/lib/panelApi";
import {
  addMyStickerSet,
  chatEventsUrl,
  createQuickReply,
  deleteQuickReply,
  getStickerSets,
  getThread,
  listMyStickerSets,
  listQuickReplies,
  listThreads,
  removeMyStickerSet,
  sendThreadFile,
  sendThreadMessage,
  sendThreadSticker,
  unreadBySource,
  updateQuickReply,
  type ChatMessage,
  type MyStickerSetRow,
  type QuickReplyTemplate,
  type StickerSetInfo,
} from "@/panel/lib/chatApi";
import { FOCUS_OPERATOR_NAME } from "@/panel/lib/focusOperator";
import {
  isSoundMuted,
  playNotificationSound,
  setSoundMuted,
} from "@/panel/lib/notificationSound";
import { BuyerAvatar } from "@/panel/ui/BuyerAvatar";
import { FocusOperatorChatBubble } from "@/panel/ui/FocusOperatorChatBubble";

interface BuyerSnapshot {
  user_id?: number;
  username?: string | null;
  first_name?: string | null;
  display_name: string;
  avatar_url?: string | null;
  guest?: boolean;
  session_hint?: string | null;
  total_orders?: number;
  paid_orders?: number;
  turnover_rub?: number;
  active_order_id?: string | null;
  active_order_status?: string | null;
  in_bot?: boolean;
}

interface ExchangerSnapshot {
  exchanger_id: number;
  name: string;
  display_name: string;
  username?: string | null;
  active_deal_id?: number | null;
  active_deal_ids?: number[];
  active_deal_count?: number;
}

function formatActiveDealsLabel(ex?: ExchangerSnapshot | null): string | null {
  if (!ex) return null;
  const ids = ex.active_deal_ids ?? (ex.active_deal_id ? [ex.active_deal_id] : []);
  if (ids.length === 0) return null;
  if (ids.length === 1) return `Активная #${ids[0]}`;
  return `Активных: ${ex.active_deal_count ?? ids.length} (#${ids.join(", #")})`;
}

interface Thread {
  id: number;
  order_id?: string;
  telegram_user_id?: number;
  source?: string;
  admin_unread: number;
  needs_reply?: boolean;
  last_message_at?: string;
  last_body?: string;
  last_sender?: string;
  message_count?: number;
  buyer?: BuyerSnapshot;
  exchanger?: ExchangerSnapshot;
}

interface BuyerProfile {
  identity: {
    user_id: number;
    username?: string;
    first_name?: string;
    avatar_url?: string;
    first_seen_at?: string;
    last_seen_at?: string;
  };
  summary: {
    paid_orders: number;
    turnover_rub: number;
    total_orders: number;
    canceled_orders?: number;
  };
  balances?: {
    balance_rub: number;
    use_cashback_on_next: boolean;
  };
  active_order?: {
    order_id: string;
    status: string;
    status_label?: string;
    fiat_amount: number;
    crypto: string;
  } | null;
  last_deal?: {
    order_id: string;
    status: string;
    fiat_amount: number;
    created_at: string;
  } | null;
}

type SourceFilter = "all" | "web" | "telegram" | "exchanger";

function sourceFilterKey(scope: PanelScope) {
  return scope === "admin" ? "admin_chat_source_filter" : "ops_chat_source_filter";
}

function clientProfilePath(scope: PanelScope, userId: number) {
  return scope === "admin" ? `/x8/users?user=${userId}` : `/ops/client/${userId}`;
}

function orderPath(scope: PanelScope, orderId: string) {
  return scope === "admin" ? `/x8/orders?order=${orderId}` : `/ops/orders?order=${orderId}`;
}

function threadOpenError(e: unknown): string {
  const status = e && typeof e === "object" && "status" in e ? Number((e as { status: number }).status) : 0;
  if (status === 401 || status === 403) return "Нет доступа к чату";
  if (status === 404) return "Чат не найден";
  if (status === 429 || status === 503) {
    return "Слишком много запросов. Подождите пару секунд и повторите.";
  }
  if (e instanceof Error && e.message.trim()) return e.message;
  return "Не удалось открыть чат";
}

function mergeMessages(prev: ChatMessage[], incoming: ChatMessage[]) {
  const ids = new Set(prev.map((m) => m.id));
  return [...prev, ...incoming.filter((m) => !ids.has(m.id))].sort((a, b) => a.id - b.id);
}

function isNearBottom(el: HTMLDivElement) {
  return el.scrollHeight - el.scrollTop - el.clientHeight < 80;
}

function sourceBadge(source?: string): { label: string; className: string } {
  if (source === "exchanger") {
    return { label: "Внештат", className: "bg-orange-500/20 text-orange-300" };
  }
  if (source === "telegram") {
    return { label: "TG", className: "bg-sky-500/20 text-sky-300" };
  }
  if (source === "both") {
    return { label: "Сайт+TG", className: "bg-violet-500/20 text-violet-300" };
  }
  return { label: "Сайт", className: "bg-emerald-500/20 text-emerald-300" };
}

function rub(n: number) {
  return n.toLocaleString("ru-RU", { maximumFractionDigits: 0 }) + " ₽";
}

function requestBrowserNotifyPermission(): void {
  if (typeof Notification === "undefined") return;
  if (Notification.permission === "default") {
    void Notification.requestPermission();
  }
}

function showBrowserNotification(preview: string, name: string): void {
  if (typeof Notification === "undefined") return;
  if (Notification.permission !== "granted") return;
  if (!document.hidden) return;
  try {
    new Notification(`Новое сообщение — ${name}`, {
      body: preview || "Чат поддержки",
    });
  } catch {
    /* ignore */
  }
}

function ThreadListItem({
  thread: t,
  selected,
  onSelect,
}: {
  thread: Thread;
  selected: boolean;
  onSelect: () => void;
}) {
  const b = t.buyer;
  const ex = t.exchanger;
  const badge = sourceBadge(t.source);
  const name =
    ex?.display_name ||
    b?.display_name ||
    (t.telegram_user_id ? `ID ${t.telegram_user_id}` : `Чат #${t.id}`);

  return (
    <button
      type="button"
      onClick={onSelect}
      className={`w-full text-left px-3 py-3 hover:bg-white/5 transition-colors ${
        selected ? "bg-white/10" : ""
      }`}
    >
      <div className="flex gap-3">
        <BuyerAvatar
          avatarUrl={b?.avatar_url}
          name={ex?.name ?? b?.first_name}
          username={ex?.username ?? b?.username}
          userId={b?.user_id ?? t.telegram_user_id}
          size="md"
        />
        <div className="min-w-0 flex-1">
          <div className="flex items-start justify-between gap-2">
            <div className="min-w-0">
              <p className="text-sm font-medium text-white truncate">{name}</p>
              {(ex?.username || b?.username) && (
                <p className="text-xs text-gray-500 truncate">
                  @{(ex?.username || b?.username || "").replace(/^@/, "")}
                </p>
              )}
              {b?.guest && b.session_hint && (
                <p className="text-xs text-gray-600">сессия …{b.session_hint}</p>
              )}
            </div>
            <div className="flex flex-col items-end gap-1 shrink-0">
              {t.needs_reply && (
                <span className="bg-red-500 text-white text-xs px-1.5 rounded-full">
                  !
                </span>
              )}
              <span className={`text-[10px] px-1.5 py-0.5 rounded ${badge.className}`}>
                {badge.label}
              </span>
            </div>
          </div>
          {b && !b.guest && !ex && (
            <p className="text-[11px] text-gray-500 mt-1">
              {b.paid_orders ?? 0} оплач. · {rub(b.turnover_rub ?? 0)}
              {(t.message_count ?? 0) > 0 && (
                <span className="text-gray-600"> · {t.message_count} сообщ.</span>
              )}
            </p>
          )}
          {(formatActiveDealsLabel(ex) || b?.active_order_id) && (
            <p className="text-[11px] text-amber-400/90 mt-0.5 truncate">
              {formatActiveDealsLabel(ex) ?? `Активная #${b?.active_order_id}`}
            </p>
          )}
          {t.last_body && (
            <p className="text-xs text-gray-500 truncate mt-1">{t.last_body}</p>
          )}
        </div>
      </div>
    </button>
  );
}

function ExchangerStatsPanel({ thread }: { thread: Thread }) {
  const ex = thread.exchanger;
  if (!ex) return null;

  return (
    <div className="px-4 py-3 border-b border-white/10 bg-white/[0.02] space-y-2">
      <div className="flex items-start gap-3 flex-wrap">
        <BuyerAvatar name={ex.name} username={ex.username} size="md" />
        <div className="min-w-0 flex-1">
          <p className="font-semibold text-white">{ex.display_name}</p>
          {ex.username && (
            <p className="text-xs text-gray-500">@{ex.username.replace(/^@/, "")}</p>
          )}
          <div className="flex flex-wrap gap-2 mt-1.5">
            <span className={`text-[10px] px-2 py-0.5 rounded ${sourceBadge(thread.source).className}`}>
              {sourceBadge(thread.source).label}
            </span>
            {thread.message_count != null && (
              <span className="text-[10px] text-gray-500">
                {thread.message_count} сообщ. в истории
              </span>
            )}
          </div>
        </div>
      </div>
      {formatActiveDealsLabel(ex) && (
        <p className="text-xs text-amber-400">{formatActiveDealsLabel(ex)}</p>
      )}
    </div>
  );
}

function BuyerStatsPanel({
  thread,
  profile,
  scope,
}: {
  thread: Thread;
  profile: BuyerProfile | null;
  scope: PanelScope;
}) {
  const b = thread.buyer;
  if (!b && !profile) return null;

  const identity = profile?.identity;
  const summary = profile?.summary;
  const name =
    identity?.first_name ||
    (identity?.username ? `@${identity.username}` : null) ||
    b?.display_name ||
    "Клиент";

  return (
    <div className="px-4 py-3 border-b border-white/10 bg-white/[0.02] space-y-3">
      <div className="flex items-start gap-3 flex-wrap">
        <BuyerAvatar
          avatarUrl={identity?.avatar_url ?? b?.avatar_url}
          name={identity?.first_name ?? b?.first_name}
          username={identity?.username ?? b?.username}
          userId={identity?.user_id ?? b?.user_id ?? thread.telegram_user_id}
          size="md"
        />
        <div className="min-w-0 flex-1">
          <p className="font-semibold text-white">{name}</p>
          {identity?.user_id && (
            <p className="text-xs text-gray-500">Telegram ID {identity.user_id}</p>
          )}
          <div className="flex flex-wrap gap-2 mt-1.5">
            <span className={`text-[10px] px-2 py-0.5 rounded ${sourceBadge(thread.source).className}`}>
              {sourceBadge(thread.source).label}
            </span>
            {thread.message_count != null && (
              <span className="text-[10px] text-gray-500">
                {thread.message_count} сообщ. в истории
              </span>
            )}
          </div>
        </div>
        {thread.telegram_user_id && (
          <Link
            to={clientProfilePath(scope, thread.telegram_user_id)}
            className="text-xs text-cyan-400 hover:underline shrink-0"
          >
            Полный профиль →
          </Link>
        )}
      </div>

      {profile && (
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-2 text-center">
          <div className="rounded-lg bg-black/30 px-2 py-2">
            <p className="text-lg font-semibold text-white">{summary?.paid_orders ?? 0}</p>
            <p className="text-[10px] text-gray-500 uppercase">Оплачено</p>
          </div>
          <div className="rounded-lg bg-black/30 px-2 py-2">
            <p className="text-lg font-semibold text-white">{rub(summary?.turnover_rub ?? 0)}</p>
            <p className="text-[10px] text-gray-500 uppercase">Оборот</p>
          </div>
          <div className="rounded-lg bg-black/30 px-2 py-2">
            <p className="text-lg font-semibold text-white">{summary?.total_orders ?? 0}</p>
            <p className="text-[10px] text-gray-500 uppercase">Заявок</p>
          </div>
          <div className="rounded-lg bg-black/30 px-2 py-2">
            <p className="text-lg font-semibold text-amber-400">
              {rub(profile.balances?.balance_rub ?? 0)}
            </p>
            <p className="text-[10px] text-gray-500 uppercase">Баланс</p>
          </div>
        </div>
      )}

      {profile?.active_order && (
        <div className="text-xs rounded-lg border border-amber-500/30 bg-amber-500/10 px-3 py-2 flex flex-wrap items-center justify-between gap-2">
          <span>
            Активная заявка{" "}
            <Link
              to={orderPath(scope, profile.active_order.order_id)}
              className="text-amber-300 hover:underline font-mono"
            >
              #{profile.active_order.order_id}
            </Link>
            {" · "}
            {profile.active_order.status_label || profile.active_order.status}
            {" · "}
            {rub(profile.active_order.fiat_amount)}
          </span>
        </div>
      )}

      {thread.order_id && (
        <Link
          to={orderPath(scope, thread.order_id)}
          className="text-xs text-amber-400 hover:underline inline-block"
        >
          Заявка в чате: #{thread.order_id}
        </Link>
      )}
    </div>
  );
}

export function SupportChat({ scope }: { scope: PanelScope }) {
  const token = getPanelToken(scope);
  const allowPersonalStickers = scope === "operator";
  const allowPersonalTemplates = scope === "operator";
  const [searchParams, setSearchParams] = useSearchParams();
  const targetThreadId = searchParams.get("thread");
  const targetUserId = searchParams.get("user");
  const [threads, setThreads] = useState<Thread[]>([]);
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [pendingUserId, setPendingUserId] = useState<number | null>(null);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [threadMeta, setThreadMeta] = useState<Thread | null>(null);
  const [threadLoading, setThreadLoading] = useState(false);
  const [threadError, setThreadError] = useState<string | null>(null);
  const [buyerProfile, setBuyerProfile] = useState<BuyerProfile | null>(null);
  const [text, setText] = useState("");
  const [unreadOnly, setUnreadOnly] = useState(false);
  const [sending, setSending] = useState(false);
  const [soundMuted, setSoundMutedState] = useState(isSoundMuted);
  const [sourceFilter, setSourceFilter] = useState<SourceFilter>(() => {
    const saved = sessionStorage.getItem(sourceFilterKey(scope));
    return saved === "web" || saved === "telegram" || saved === "exchanger" ? saved : "all";
  });
  const [sourceUnread, setSourceUnread] = useState({
    all: 0,
    web: 0,
    telegram: 0,
    exchanger: 0,
  });
  const [hasMoreOlder, setHasMoreOlder] = useState(false);
  const [loadingOlder, setLoadingOlder] = useState(false);
  const bottomRef = useRef<HTMLDivElement>(null);
  const messagesScrollRef = useRef<HTMLDivElement>(null);
  const oldestIdRef = useRef(0);
  const lastMessageIdRef = useRef(0);
  const [stickerSets, setStickerSets] = useState<StickerSetInfo[]>([]);
  const [myStickerSets, setMyStickerSets] = useState<MyStickerSetRow[]>([]);
  const [newStickerSetName, setNewStickerSetName] = useState("");
  const [stickerOpen, setStickerOpen] = useState(false);
  const [stickerManage, setStickerManage] = useState(false);
  const [activeStickerSet, setActiveStickerSet] = useState(0);
  const [quickGlobal, setQuickGlobal] = useState<QuickReplyTemplate[]>([]);
  const [quickPersonal, setQuickPersonal] = useState<QuickReplyTemplate[]>([]);
  const [quickManageOpen, setQuickManageOpen] = useState(false);
  const [qrTitle, setQrTitle] = useState("");
  const [qrBody, setQrBody] = useState("");
  const [qrTrigger, setQrTrigger] = useState("");
  const [qrEditId, setQrEditId] = useState<number | null>(null);
  const fileRef = useRef<HTMLInputElement>(null);
  const selectedIdRef = useRef<number | null>(null);
  const threadsRef = useRef<Thread[]>([]);

  useEffect(() => {
    selectedIdRef.current = selectedId;
  }, [selectedId]);

  useEffect(() => {
    threadsRef.current = threads;
  }, [threads]);

  const loadSourceUnread = useCallback(async () => {
    if (!token) return;
    try {
      const data = await unreadBySource(scope);
      setSourceUnread({
        all: data.all ?? 0,
        web: data.web ?? 0,
        telegram: data.telegram ?? 0,
        exchanger: data.exchanger ?? 0,
      });
    } catch {
      /* */
    }
  }, [token, scope]);

  const loadThreads = useCallback(async () => {
    if (!token) return;
    try {
      const data = await listThreads(scope, {
        limit: 200,
        unread_only: unreadOnly,
        source: sourceFilter === "all" ? undefined : sourceFilter,
      });
      setThreads((data.threads || []) as Thread[]);
    } catch {
      toast.error("Не удалось загрузить список чатов");
    }
  }, [token, unreadOnly, sourceFilter, scope]);

  const selectThread = useCallback(
    (id: number) => {
      if (!Number.isFinite(id) || id <= 0) return;
      setSelectedId(id);
      setPendingUserId(null);
      setThreadError(null);
      setThreadMeta(null);
      setMessages([]);
      const next = new URLSearchParams(searchParams);
      next.set("thread", String(id));
      next.delete("user");
      setSearchParams(next, { replace: true });
      // На узком экране панель диалога под списком — прокрутим к ней.
      requestAnimationFrame(() => {
        document.getElementById("support-chat-thread-pane")?.scrollIntoView({
          behavior: "smooth",
          block: "nearest",
        });
      });
    },
    [searchParams, setSearchParams],
  );

  useEffect(() => {
    loadSourceUnread();
    const t = setInterval(() => {
      if (!getPanelToken(scope)) return;
      loadSourceUnread();
    }, 15000);
    return () => clearInterval(t);
  }, [loadSourceUnread]);

  const loadThread = useCallback(
    async (id: number, opts?: { beforeId?: number; scrollToBottom?: boolean }) => {
      if (!token) return;
      const isInitial = !opts?.beforeId;
      if (isInitial) {
        setThreadLoading(true);
        setThreadError(null);
      }
      try {
        const data = await getThread(scope, id, {
          before_id: opts?.beforeId,
        });
        const incoming: ChatMessage[] = data.messages || [];
        if (selectedIdRef.current !== id) return;

        if (opts?.beforeId) {
          const el = messagesScrollRef.current;
          const prevHeight = el?.scrollHeight ?? 0;
          setMessages((prev) => mergeMessages(incoming, prev));
          if (incoming.length) {
            oldestIdRef.current = data.oldest_id ?? incoming[0].id;
          }
          setHasMoreOlder(Boolean(data.has_more_older));
          requestAnimationFrame(() => {
            if (el) el.scrollTop = el.scrollHeight - prevHeight;
          });
        } else {
          setMessages(incoming);
          setHasMoreOlder(Boolean(data.has_more_older));
          if (incoming.length) {
            oldestIdRef.current = data.oldest_id ?? incoming[0].id;
            lastMessageIdRef.current = incoming[incoming.length - 1].id;
          } else {
            oldestIdRef.current = 0;
            lastMessageIdRef.current = 0;
          }
          const meta = (data.thread || null) as Thread | null;
          if (!meta) {
            setThreadMeta(null);
            setThreadError("Чат недоступен");
            toast.error("Чат недоступен");
          } else {
            setThreadMeta(meta);
            setThreadError(null);
          }
          setBuyerProfile((data.buyer_profile as unknown as BuyerProfile) ?? null);
          setThreads((prev) =>
            prev.map((t) => (t.id === id ? { ...t, admin_unread: 0 } : t)),
          );
          void loadSourceUnread();
          if (opts?.scrollToBottom !== false) {
            requestAnimationFrame(() => {
              const el = messagesScrollRef.current;
              if (el) el.scrollTop = el.scrollHeight;
            });
          }
        }
      } catch (e) {
        if (selectedIdRef.current !== id) return;
        if (isInitial) {
          setThreadMeta(null);
          setBuyerProfile(null);
          setMessages([]);
          const msg = threadOpenError(e);
          setThreadError(msg);
          toast.error(msg);
        }
      } finally {
        if (isInitial && selectedIdRef.current === id) setThreadLoading(false);
      }
    },
    [token, loadSourceUnread, scope],
  );

  const pollThread = useCallback(
    async (id: number) => {
      if (!token) return;
      const el = messagesScrollRef.current;
      const atBottom = el ? isNearBottom(el) : true;
      const lastId = lastMessageIdRef.current;
      if (!lastId) return;
      try {
        const data = await getThread(scope, id, { after_id: lastId });
        if (selectedIdRef.current !== id) return;
        const incoming: ChatMessage[] = data.messages || [];
        if (incoming.length) {
          lastMessageIdRef.current = incoming[incoming.length - 1].id;
          setMessages((prev) => mergeMessages(prev, incoming));
          if (atBottom) {
            requestAnimationFrame(() => {
              const scrollEl = messagesScrollRef.current;
              if (scrollEl) scrollEl.scrollTop = scrollEl.scrollHeight;
            });
          }
        }
      } catch {
        /* */
      }
    },
    [token, scope],
  );

  const setFilter = (f: SourceFilter) => {
    setSourceFilter(f);
    sessionStorage.setItem(sourceFilterKey(scope), f);
  };

  useEffect(() => {
    loadThreads();
    const t = setInterval(() => {
      if (!getPanelToken(scope)) return;
      loadThreads();
    }, 30000);
    return () => clearInterval(t);
  }, [loadThreads]);

  useEffect(() => {
    if (!targetThreadId) return;
    const tid = Number.parseInt(targetThreadId, 10);
    if (!Number.isFinite(tid) || tid <= 0) return;
    if (selectedId !== tid) {
      setSelectedId(tid);
      setPendingUserId(null);
      setThreadError(null);
    }
    const found = threads.find((t) => t.id === tid);
    if (!found) return;
    if (found.source === "exchanger" && sourceFilter !== "exchanger") {
      setFilter("exchanger");
    } else if (found.source === "telegram" && sourceFilter !== "telegram") {
      setFilter("telegram");
    } else if ((found.source === "web" || found.source === "both") && sourceFilter === "exchanger") {
      setFilter(found.source === "both" ? "telegram" : "web");
    }
  }, [targetThreadId, threads, selectedId, sourceFilter]);

  useEffect(() => {
    if (!targetUserId) return;
    const uid = Number.parseInt(targetUserId, 10);
    if (!Number.isFinite(uid) || uid <= 0) return;
    const found = threads.find((t) => t.telegram_user_id === uid);
    if (found) {
      selectThread(found.id);
      return;
    }
    setPendingUserId(uid);
  }, [targetUserId, threads, selectThread]);

  const loadThreadRef = useRef(loadThread);
  const pollThreadRef = useRef(pollThread);
  loadThreadRef.current = loadThread;
  pollThreadRef.current = pollThread;

  useEffect(() => {
    if (!selectedId) return;
    const id = selectedId;
    setHasMoreOlder(false);
    oldestIdRef.current = 0;
    lastMessageIdRef.current = 0;
    void loadThreadRef.current(id, { scrollToBottom: true });
    const t = setInterval(() => {
      if (!getPanelToken(scope)) return;
      void pollThreadRef.current(id);
    }, 20000);
    return () => clearInterval(t);
  }, [selectedId, scope]);

  useEffect(() => {
    if (!token) return;
    const es = new EventSource(chatEventsUrl(scope));

    es.onmessage = (ev) => {
      try {
        const data = JSON.parse(ev.data) as {
          type?: string;
          thread_id?: number;
          preview?: string;
        };
        if (data.type !== "new_message") return;
        playNotificationSound();
        const th = threadsRef.current.find((x) => x.id === data.thread_id);
        const name =
          th?.exchanger?.display_name || th?.buyer?.display_name || FOCUS_OPERATOR_NAME;
        if (data.thread_id) {
          showBrowserNotification(data.preview || "", name);
        }
        void loadThreads();
        void loadSourceUnread();
        const cur = selectedIdRef.current;
        if (cur && data.thread_id === cur) {
          void pollThread(cur);
        }
      } catch {
        /* */
      }
    };

    return () => es.close();
  }, [token, loadThreads, loadSourceUnread, pollThread, scope]);

  const loadOlder = useCallback(async () => {
    if (!selectedId || !hasMoreOlder || loadingOlder || !oldestIdRef.current) return;
    setLoadingOlder(true);
    try {
      await loadThread(selectedId, { beforeId: oldestIdRef.current });
    } finally {
      setLoadingOlder(false);
    }
  }, [selectedId, hasMoreOlder, loadingOlder, loadThread]);

  const handleMessagesScroll = () => {
    const el = messagesScrollRef.current;
    if (!el || loadingOlder) return;
    if (el.scrollTop < 80) void loadOlder();
  };

  const send = async () => {
    if (!selectedId || !text.trim() || sending || !token) return;
    setSending(true);
    try {
      await sendThreadMessage(scope, selectedId, text.trim());
      setText("");
      await loadThread(selectedId);
    } catch {
      toast.error("Не удалось отправить сообщение");
    } finally {
      setSending(false);
    }
  };

  const sendFile = async (file: File) => {
    if (!selectedId || sending || !token) return;
    setSending(true);
    try {
      await sendThreadFile(scope, selectedId, file, text.trim() || undefined);
      setText("");
      await loadThread(selectedId, { scrollToBottom: true });
    } catch {
      toast.error("Не удалось отправить файл");
    } finally {
      setSending(false);
      if (fileRef.current) fileRef.current.value = "";
    }
  };

  const loadStickerSets = useCallback(async () => {
    if (!token) return;
    try {
      const setsData = await getStickerSets(scope);
      setStickerSets(setsData.sets || []);
      if (allowPersonalStickers) {
        const myData = await listMyStickerSets();
        setMyStickerSets(myData.items || []);
      } else {
        setMyStickerSets([]);
      }
      setActiveStickerSet(0);
    } catch {
      setStickerSets([]);
      setMyStickerSets([]);
    }
  }, [token, scope, allowPersonalStickers]);

  const loadQuickReplies = useCallback(async () => {
    if (!token) return;
    try {
      const data = await listQuickReplies(scope);
      if ("global" in data && "personal" in data) {
        setQuickGlobal(data.global || []);
        setQuickPersonal(data.personal || []);
        return;
      }
      if ("items" in data) {
        setQuickGlobal(data.items || []);
        setQuickPersonal([]);
      }
    } catch {
      setQuickGlobal([]);
      setQuickPersonal([]);
    }
  }, [token, scope]);

  useEffect(() => {
    void loadQuickReplies();
  }, [loadQuickReplies]);

  const addStickerSet = async () => {
    const name = newStickerSetName.trim();
    if (!name) return;
    try {
      await addMyStickerSet(name);
      setNewStickerSetName("");
      setStickerManage(false);
      await loadStickerSets();
      toast.success("Набор добавлен");
    } catch {
      toast.error("Не удалось добавить набор (проверьте имя и доступ бота)");
    }
  };

  const removeStickerSet = async (rowId: number) => {
    try {
      await removeMyStickerSet(rowId);
      await loadStickerSets();
      toast.success("Набор удалён");
    } catch {
      toast.error("Не удалось удалить набор");
    }
  };

  const applyQuickReply = (body: string, sendNow: boolean) => {
    if (sendNow && selectedId && !sending) {
      void (async () => {
        setSending(true);
        try {
          await sendThreadMessage(scope, selectedId, body);
          await loadThread(selectedId, { scrollToBottom: true });
        } catch {
          toast.error("Не удалось отправить");
        } finally {
          setSending(false);
        }
      })();
      return;
    }
    setText((prev) => (prev ? `${prev}\n${body}` : body));
  };

  const resetQrForm = () => {
    setQrEditId(null);
    setQrTitle("");
    setQrBody("");
    setQrTrigger("");
  };

  const saveQuickReply = async () => {
    if (!qrTitle.trim() || !qrBody.trim()) {
      toast.error("Заполните название и текст");
      return;
    }
    try {
      if (qrEditId) {
        await updateQuickReply(scope, qrEditId, {
          title: qrTitle.trim(),
          body: qrBody.trim(),
          trigger_phrase: qrTrigger.trim() || null,
        });
        toast.success("Шаблон обновлён");
      } else {
        await createQuickReply(scope, {
          title: qrTitle.trim(),
          body: qrBody.trim(),
          trigger_phrase: qrTrigger.trim() || undefined,
        });
        toast.success("Шаблон добавлен");
      }
      resetQrForm();
      await loadQuickReplies();
    } catch {
      toast.error("Не удалось сохранить шаблон");
    }
  };

  const editQuickReply = (item: QuickReplyTemplate) => {
    setQrEditId(item.id);
    setQrTitle(item.title);
    setQrBody(item.body);
    setQrTrigger(item.trigger_phrase || "");
    setQuickManageOpen(true);
  };

  const removeQuickReply = async (id: number) => {
    try {
      await deleteQuickReply(scope, id);
      if (qrEditId === id) resetQrForm();
      await loadQuickReplies();
      toast.success("Удалено");
    } catch {
      toast.error("Не удалось удалить");
    }
  };

  const sendSticker = async (fileId: string) => {
    if (!selectedId || sending || !token) return;
    setSending(true);
    try {
      await sendThreadSticker(scope, selectedId, fileId);
      setStickerOpen(false);
      await loadThread(selectedId, { scrollToBottom: true });
    } catch {
      toast.error("Не удалось отправить стикер");
    } finally {
      setSending(false);
    }
  };

  const toggleSound = () => {
    const next = !soundMuted;
    setSoundMuted(next);
    setSoundMutedState(next);
    requestBrowserNotifyPermission();
  };

  const managedReplies = allowPersonalTemplates ? quickPersonal : quickGlobal;
  const templatesLabel = allowPersonalTemplates ? "⚡ Мои шаблоны" : "⚡ Общие шаблоны";

  return (
    <div className="w-full max-w-none flex flex-col h-[calc(100vh-10.5rem)] min-h-[480px]">
      <div className="flex items-center justify-between mb-3 flex-wrap gap-3 shrink-0">
        <div>
          <h1 className="text-xl font-semibold text-white">
            {scope === "admin" ? "Чаты поддержки" : `Чат — ${FOCUS_OPERATOR_NAME}`}
          </h1>
          <p className="text-sm text-gray-500 mt-1">
            Один диалог на клиента · сайт, Telegram и внештат
          </p>
        </div>
        <div className="flex items-center gap-4 flex-wrap">
          <button
            type="button"
            onClick={toggleSound}
            className="text-sm text-gray-400 hover:text-white transition-colors"
          >
            {soundMuted ? "🔕 Звук выкл." : "🔔 Звук вкл."}
          </button>
          <label className="flex items-center gap-2 text-sm text-gray-400">
            <input
              type="checkbox"
              checked={unreadOnly}
              onChange={(e) => setUnreadOnly(e.target.checked)}
            />
            Только непрочитанные
          </label>
        </div>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-12 gap-4 flex-1 min-h-0">
        <div className="rounded-xl border border-white/10 bg-[var(--bg-surface)] p-0 overflow-hidden lg:col-span-4 flex flex-col h-full min-h-0">
          <div className="px-3 py-2 border-b border-white/10 shrink-0 space-y-2">
            <div className="flex gap-1">
              {(["all", "web", "telegram", "exchanger"] as const).map((f) => {
                const count = sourceUnread[f];
                const label =
                  f === "all"
                    ? "Все"
                    : f === "web"
                      ? "Сайт"
                      : f === "telegram"
                        ? "Telegram"
                        : "Внештат";
                return (
                  <button
                    key={f}
                    type="button"
                    onClick={() => setFilter(f)}
                    className={`relative flex-1 text-[11px] py-1 rounded transition-colors ${
                      sourceFilter === f
                        ? "bg-white/15 text-white"
                        : "text-gray-500 hover:text-gray-300"
                    }`}
                  >
                    {label}
                    {count > 0 && (
                      <span className="absolute -top-1 -right-0.5 min-w-[14px] h-[14px] px-0.5 flex items-center justify-center bg-red-500 text-white text-[9px] font-bold rounded-full">
                        {count > 99 ? "99+" : count}
                      </span>
                    )}
                  </button>
                );
              })}
            </div>
            <p className="text-xs text-gray-500">Клиенты ({threads.length})</p>
          </div>
          <div className="flex-1 min-h-0 overflow-y-auto divide-y divide-white/5">
            {threads.length === 0 && (
              <p className="p-4 text-sm text-gray-500">Пока нет сообщений</p>
            )}
            {threads.map((t) => (
              <ThreadListItem
                key={t.id}
                thread={t}
                selected={selectedId === t.id}
                onSelect={() => selectThread(t.id)}
              />
            ))}
          </div>
        </div>

        <div
          id="support-chat-thread-pane"
          className="rounded-xl border border-white/10 bg-[var(--bg-surface)] p-0 flex flex-col lg:col-span-8 h-full min-h-0 overflow-hidden"
        >
          {!selectedId ? (
            pendingUserId ? (
              <div className="m-auto max-w-md p-6 text-center space-y-3">
                <p className="text-gray-300 text-sm">
                  Клиент <code className="text-accent-300">{pendingUserId}</code> ещё не писал в чат
                  поддержки.
                </p>
                <p className="text-gray-500 text-xs">
                  Если у клиента есть @username — откройте профиль в Telegram. Иначе напишите через
                  чат на сайте или дождитесь сообщения от клиента @focus_operator.
                </p>
                <Link
                  to={clientProfilePath(scope, pendingUserId)}
                  className="rounded-lg bg-white text-black px-4 py-2 text-sm font-medium inline-block"
                >
                  Открыть профиль в кабинете
                </Link>
              </div>
            ) : (
              <p className="m-auto text-gray-500 text-sm">Выберите клиента слева</p>
            )
          ) : threadLoading && !threadMeta ? (
            <p className="m-auto text-gray-500 text-sm">Открываем чат…</p>
          ) : threadError && !threadMeta ? (
            <div className="m-auto max-w-sm p-6 text-center space-y-3">
              <p className="text-sm text-red-300">{threadError}</p>
              <button
                type="button"
                className="rounded-lg bg-white text-black px-4 py-2 text-sm font-medium"
                onClick={() => void loadThread(selectedId, { scrollToBottom: true })}
              >
                Повторить
              </button>
            </div>
          ) : !threadMeta ? (
            <p className="m-auto text-gray-500 text-sm">Открываем чат…</p>
          ) : (
            <>
              <div className="shrink-0 max-h-[22%] overflow-y-auto">
                {threadMeta?.source === "exchanger" ? (
                  <ExchangerStatsPanel thread={threadMeta} />
                ) : (
                  <BuyerStatsPanel thread={threadMeta} profile={buyerProfile} scope={scope} />
                )}
              </div>
              <div
                ref={messagesScrollRef}
                onScroll={handleMessagesScroll}
                className="flex-1 min-h-0 overflow-y-auto px-4 py-3 space-y-2"
              >
                {loadingOlder && (
                  <p className="text-center text-xs text-gray-500 py-1">Загрузка…</p>
                )}
                {messages.map((m) => (
                  <FocusOperatorChatBubble
                    key={m.id}
                    message={m}
                    variant="admin"
                    align={m.sender_role === "admin" ? "end" : "start"}
                    peer={
                      m.sender_role === "admin"
                        ? null
                        : threadMeta?.source === "exchanger"
                          ? {
                              name: threadMeta.exchanger?.name,
                              username: threadMeta.exchanger?.username,
                            }
                          : {
                              avatarUrl:
                                buyerProfile?.identity?.avatar_url ?? threadMeta?.buyer?.avatar_url,
                              name:
                                buyerProfile?.identity?.first_name ??
                                threadMeta?.buyer?.first_name ??
                                threadMeta?.buyer?.display_name,
                              username:
                                buyerProfile?.identity?.username ?? threadMeta?.buyer?.username,
                              userId:
                                buyerProfile?.identity?.user_id ??
                                threadMeta?.buyer?.user_id ??
                                threadMeta?.telegram_user_id,
                            }
                    }
                  />
                ))}
                <div ref={bottomRef} />
              </div>
              <div className="p-3 border-t border-white/10 flex flex-col gap-2 shrink-0 relative">
                {(quickGlobal.length > 0 || quickPersonal.length > 0 || quickManageOpen) ? (
                  <div className="flex flex-wrap gap-1 items-center max-h-20 overflow-y-auto">
                    {quickGlobal.map((q) => (
                      <button
                        key={`g-${q.id}`}
                        type="button"
                        title={q.body}
                        disabled={sending}
                        onClick={(e) => applyQuickReply(q.body, e.shiftKey)}
                        className="text-[11px] px-2 py-1 rounded-full border border-cyan-500/30 text-cyan-200 hover:bg-cyan-500/10"
                      >
                        {q.title}
                      </button>
                    ))}
                    {quickPersonal.map((q) => (
                      <button
                        key={`p-${q.id}`}
                        type="button"
                        title={q.body}
                        disabled={sending}
                        onClick={(e) => applyQuickReply(q.body, e.shiftKey)}
                        className="text-[11px] px-2 py-1 rounded-full border border-white/15 text-gray-200 hover:bg-white/10"
                      >
                        {q.title}
                      </button>
                    ))}
                    <button
                      type="button"
                      className="text-[11px] px-2 py-1 rounded-full border border-white/10 text-gray-400 hover:bg-white/5"
                      onClick={() => {
                        setQuickManageOpen((v) => !v);
                        if (quickManageOpen) resetQrForm();
                      }}
                    >
                      {templatesLabel}
                    </button>
                    {scope === "operator" && (
                      <Link
                        to="/ops/templates"
                        className="text-[11px] px-2 py-1 rounded-full border border-white/10 text-gray-400 hover:bg-white/5"
                      >
                        Общие шаблоны
                      </Link>
                    )}
                  </div>
                ) : (
                  <div className="flex flex-wrap gap-1 items-center">
                    <button
                      type="button"
                      className="self-start text-[11px] px-2 py-1 rounded-full border border-white/10 text-gray-400 hover:bg-white/5"
                      onClick={() => setQuickManageOpen(true)}
                    >
                      ⚡ Быстрые ответы
                    </button>
                    {scope === "operator" && (
                      <Link
                        to="/ops/templates"
                        className="text-[11px] px-2 py-1 rounded-full border border-white/10 text-gray-400 hover:bg-white/5"
                      >
                        Общие шаблоны
                      </Link>
                    )}
                  </div>
                )}
                {quickManageOpen && (
                  <div className="rounded-lg border border-white/10 bg-[var(--bg-elevated)] p-3 space-y-2 text-sm">
                    <p className="text-[11px] text-gray-500">
                      Shift+клик по chip — сразу отправить. Триггер — автоответ клиенту (раз в 30 мин).
                    </p>
                    <div className="grid gap-2 sm:grid-cols-3">
                      <input
                        className="rounded border border-white/10 bg-black/20 px-2 py-1 text-white text-xs"
                        placeholder="Название chip"
                        value={qrTitle}
                        onChange={(e) => setQrTitle(e.target.value)}
                      />
                      <input
                        className="rounded border border-white/10 bg-black/20 px-2 py-1 text-white text-xs sm:col-span-2"
                        placeholder="Текст ответа"
                        value={qrBody}
                        onChange={(e) => setQrBody(e.target.value)}
                      />
                      <input
                        className="rounded border border-white/10 bg-black/20 px-2 py-1 text-white text-xs sm:col-span-2"
                        placeholder="Триггер (необяз.)"
                        value={qrTrigger}
                        onChange={(e) => setQrTrigger(e.target.value)}
                      />
                      <div className="flex gap-1">
                        <button
                          type="button"
                          className="rounded bg-white text-black px-2 py-1 text-xs"
                          onClick={() => void saveQuickReply()}
                        >
                          {qrEditId ? "Сохранить" : "Добавить"}
                        </button>
                        {qrEditId && (
                          <button type="button" className="text-xs text-gray-400 px-2" onClick={resetQrForm}>
                            Отмена
                          </button>
                        )}
                      </div>
                    </div>
                    {managedReplies.length > 0 && (
                      <ul className="space-y-1 max-h-32 overflow-y-auto">
                        {managedReplies.map((q) => (
                          <li key={q.id} className="flex items-center gap-2 text-xs">
                            <span className="flex-1 truncate">{q.title}</span>
                            <button type="button" className="text-cyan-300" onClick={() => editQuickReply(q)}>
                              ✎
                            </button>
                            <button type="button" className="text-red-400" onClick={() => void removeQuickReply(q.id)}>
                              ×
                            </button>
                          </li>
                        ))}
                      </ul>
                    )}
                  </div>
                )}
                {stickerOpen && (
                  <div className="rounded-lg border border-white/10 bg-[var(--bg-elevated)] p-2 max-h-56 overflow-hidden flex flex-col">
                    {stickerManage && allowPersonalStickers ? (
                      <div className="space-y-2 text-sm">
                        <p className="text-[11px] text-gray-500">Имя набора как в Telegram, без @</p>
                        <div className="flex gap-2">
                          <input
                            className="flex-1 rounded border border-white/10 bg-black/20 px-2 py-1 text-white text-xs"
                            placeholder="MyStickerSet_by_Bot"
                            value={newStickerSetName}
                            onChange={(e) => setNewStickerSetName(e.target.value)}
                          />
                          <button
                            type="button"
                            className="rounded bg-white text-black px-2 text-xs"
                            onClick={() => void addStickerSet()}
                          >
                            Добавить
                          </button>
                        </div>
                        <ul className="max-h-24 overflow-y-auto space-y-1">
                          {myStickerSets.map((s) => (
                            <li key={s.id} className="flex items-center gap-2 text-xs">
                              <span className="flex-1 truncate">{s.title || s.set_name}</span>
                              <button type="button" className="text-red-400" onClick={() => void removeStickerSet(s.id)}>
                                ×
                              </button>
                            </li>
                          ))}
                        </ul>
                        <button type="button" className="text-xs text-gray-400" onClick={() => setStickerManage(false)}>
                          ← К стикерам
                        </button>
                      </div>
                    ) : stickerSets.length > 0 ? (
                      <>
                        <div className="flex gap-1 overflow-x-auto pb-2 shrink-0 items-center">
                          {stickerSets.map((set, idx) => (
                            <button
                              key={set.name}
                              type="button"
                              onClick={() => setActiveStickerSet(idx)}
                              className={`text-[11px] px-2 py-1 rounded whitespace-nowrap ${
                                activeStickerSet === idx ? "bg-white/15 text-white" : "text-gray-500"
                              }`}
                            >
                              {set.title || set.name}
                            </button>
                          ))}
                          {allowPersonalStickers && (
                          <button
                            type="button"
                            className="text-[11px] px-2 py-1 rounded text-gray-400 hover:bg-white/5 ml-auto"
                            onClick={() => setStickerManage(true)}
                          >
                            + Мои наборы
                          </button>
                          )}
                        </div>
                        <div className="grid grid-cols-6 gap-1 overflow-y-auto">
                          {(stickerSets[activeStickerSet]?.stickers || []).map((st) => (
                            <button
                              key={st.file_id}
                              type="button"
                              disabled={sending}
                              title={st.emoji || ""}
                              onClick={() => void sendSticker(st.file_id)}
                              className="text-2xl p-1 rounded hover:bg-white/10"
                            >
                              {st.emoji || "🎭"}
                            </button>
                          ))}
                        </div>
                      </>
                    ) : (
                      <div className="text-xs text-gray-500 space-y-2">
                        <p>
                          {allowPersonalStickers
                            ? "Нет наборов. Добавьте свой или попросите админа настроить общие."
                            : "Нет общих наборов стикеров."}
                        </p>
                        {allowPersonalStickers && (
                        <button
                          type="button"
                          className="rounded border border-white/10 px-2 py-1"
                          onClick={() => setStickerManage(true)}
                        >
                          + Добавить набор
                        </button>
                        )}
                      </div>
                    )}
                  </div>
                )}
                <div className="flex gap-2 items-end">
                <input
                  ref={fileRef}
                  type="file"
                  accept="image/*,video/*,.pdf,.doc,.docx,audio/*"
                  className="hidden"
                  onChange={(e) => {
                    const f = e.target.files?.[0];
                    if (f) sendFile(f);
                  }}
                />
                <button
                  type="button"
                  className="rounded-lg border border-white/10 px-3 py-2 shrink-0 text-sm hover:bg-white/5"
                  disabled={sending}
                  title="Стикеры"
                  onClick={() => {
                    const next = !stickerOpen;
                    setStickerOpen(next);
                    if (next) void loadStickerSets();
                  }}
                >
                  🎭
                </button>
                <button
                  type="button"
                  className="rounded-lg border border-white/10 px-3 py-2 shrink-0 hover:bg-white/5"
                  disabled={sending}
                  title="Отправить файл"
                  onClick={() => fileRef.current?.click()}
                >
                  📎
                </button>
                <textarea
                  className="flex-1 min-h-[44px] text-sm resize-none rounded-lg border border-white/10 bg-black/20 px-3 py-2 text-white"
                  rows={2}
                  placeholder="Ответ или подпись к файлу..."
                  value={text}
                  onChange={(e) => setText(e.target.value)}
                />
                <button
                  type="button"
                  className="rounded-lg bg-white text-black px-4 py-2 self-end shrink-0 font-medium disabled:opacity-50"
                  disabled={sending || !text.trim()}
                  onClick={send}
                >
                  Отправить
                </button>
                </div>
              </div>
            </>
          )}
        </div>
      </div>
    </div>
  );
}
