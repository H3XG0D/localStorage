// Buyer↔operator chat panel. Prefers the live SSE stream to react instantly to
// operator replies; falls back to polling (and keeps a slow safety-net poll even
// while live). Supports text, image and file messages.
import { useCallback, useEffect, useRef, useState } from "react";
import { ImagePlus, Loader2, Paperclip, Send } from "lucide-react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { ApiError } from "@/lib/api";
import { getConversation, sendFile, sendImage, sendMessage, type ChatMessage } from "@/lib/chat";
import { useLiveEvents } from "@/lib/useLiveEvents";
import { cn } from "@/lib/utils";

const POLL_FAST_MS = 5000; // no live stream → poll briskly
const POLL_SLOW_MS = 20000; // live stream connected → just a safety net

function playPing() {
  try {
    const Ctor =
      window.AudioContext ||
      (window as unknown as { webkitAudioContext?: typeof AudioContext }).webkitAudioContext;
    if (!Ctor) return;
    const ctx = new Ctor();
    const osc = ctx.createOscillator();
    const gain = ctx.createGain();
    osc.connect(gain);
    gain.connect(ctx.destination);
    osc.frequency.value = 880;
    gain.gain.setValueAtTime(0.12, ctx.currentTime);
    osc.start();
    osc.stop(ctx.currentTime + 0.25);
    osc.onended = () => void ctx.close();
  } catch {
    /* ignore */
  }
}

export function OrderChat({ orderId }: { orderId: string }) {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [text, setText] = useState("");
  const [sending, setSending] = useState(false);
  const lastId = useRef(0);
  const initialLoaded = useRef(false);
  const rootRef = useRef<HTMLDivElement>(null);
  const scrollRef = useRef<HTMLDivElement>(null);
  const imageInput = useRef<HTMLInputElement>(null);
  const fileInput = useRef<HTMLInputElement>(null);

  function notifyOperatorReply(incoming: ChatMessage[]) {
    const fresh = incoming.filter((m) => m.sender_role !== "buyer");
    if (!fresh.length) return;
    playPing();
    const preview = fresh[fresh.length - 1].body?.slice(0, 120) || "Новое сообщение";
    toast.info(`Оператор: ${preview}`, {
      description: "Оператор написал вам в чат",
      action: {
        label: "Открыть чат",
        onClick: () => rootRef.current?.scrollIntoView({ behavior: "smooth", block: "center" }),
      },
    });
    rootRef.current?.scrollIntoView({ behavior: "smooth", block: "center" });
  }

  function mergeMessages(incoming: ChatMessage[], notify = false) {
    if (!incoming.length) return;
    if (notify && initialLoaded.current) {
      const unseen = incoming.filter((m) => m.id > lastId.current && m.sender_role !== "buyer");
      if (unseen.length) notifyOperatorReply(unseen);
    }
    setMessages((prev) => {
      const seen = new Set(prev.map((m) => m.id));
      const merged = [...prev, ...incoming.filter((m) => !seen.has(m.id))];
      merged.sort((a, b) => a.id - b.id);
      return merged;
    });
    lastId.current = Math.max(lastId.current, ...incoming.map((m) => m.id));
  }

  const fetchNew = useCallback(() => {
    getConversation({ order_id: orderId, after_id: lastId.current })
      .then((c) => mergeMessages(c.messages, true))
      .catch(() => undefined);
  }, [orderId]);

  // Live stream: pull new messages the instant the server signals a chat event.
  const { live } = useLiveEvents(orderId, (e) => {
    if (e.type === "chat" || e.type === "event") fetchNew();
  });

  useEffect(() => {
    let alive = true;
    // initial full load
    getConversation({ order_id: orderId })
      .then((c) => {
        if (!alive) return;
        setMessages(c.messages);
        if (c.messages.length) lastId.current = Math.max(...c.messages.map((m) => m.id));
        initialLoaded.current = true;
      })
      .catch(() => undefined);
    const t = window.setInterval(() => alive && fetchNew(), live ? POLL_SLOW_MS : POLL_FAST_MS);
    return () => {
      alive = false;
      window.clearInterval(t);
    };
  }, [orderId, live, fetchNew]);

  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: "smooth" });
  }, [messages]);

  async function submit() {
    const value = text.trim();
    if (!value || sending) return;
    setSending(true);
    try {
      const { message } = await sendMessage(value, orderId);
      mergeMessages([message]);
      setText("");
    } catch (e) {
      toast.error(e instanceof ApiError ? e.message : "Не удалось отправить");
    } finally {
      setSending(false);
    }
  }

  async function upload(file: File, kind: "image" | "file") {
    setSending(true);
    try {
      const { message } = kind === "image" ? await sendImage(file, orderId) : await sendFile(file, orderId);
      mergeMessages([message]);
    } catch (e) {
      toast.error(e instanceof ApiError ? e.message : "Не удалось загрузить файл");
    } finally {
      setSending(false);
    }
  }

  return (
    <div ref={rootRef} className="flex h-[420px] flex-col rounded-xl border border-border bg-card">
      <div className="border-b border-border px-4 py-3">
        <p className="text-sm font-semibold">Чат с оператором</p>
        <p className="text-xs text-muted-foreground">Оператор ответит в этом окне</p>
      </div>

      <div ref={scrollRef} className="scrollbar-thin flex-1 space-y-2 overflow-y-auto p-4">
        {messages.length === 0 && (
          <p className="py-8 text-center text-xs text-muted-foreground">Пока сообщений нет. Напишите оператору.</p>
        )}
        {messages.map((m) => {
          const mine = m.sender_role === "buyer";
          return (
            <div key={m.id} className={cn("flex", mine ? "justify-end" : "justify-start")}>
              <div
                className={cn(
                  "max-w-[80%] rounded-2xl px-3 py-2 text-sm",
                  mine ? "bg-primary text-primary-foreground" : "bg-muted text-foreground",
                )}
              >
                {m.image_url && (
                  <a href={m.image_url} target="_blank" rel="noreferrer">
                    <img src={m.image_url} alt="" className="mb-1 max-h-48 rounded-lg" />
                  </a>
                )}
                {m.video_url && (
                  <video src={m.video_url} controls className="mb-1 max-h-48 rounded-lg" />
                )}
                {m.file_url && (
                  <a href={m.file_url} target="_blank" rel="noreferrer" className="mb-1 flex items-center gap-1 underline">
                    <Paperclip className="size-3" />
                    {m.attachment_filename || "Файл"}
                  </a>
                )}
                {m.body && (
                  <p className="whitespace-pre-line break-words">
                    {m.body.split(/(https?:\/\/[^\s]+)/g).map((part, i) =>
                      /^https?:\/\//.test(part) ? (
                        <a
                          key={i}
                          href={part}
                          target="_blank"
                          rel="noreferrer"
                          className={cn("underline", mine ? "text-primary-foreground" : "text-foreground")}
                        >
                          {part}
                        </a>
                      ) : (
                        <span key={i}>{part}</span>
                      ),
                    )}
                  </p>
                )}
                {m.created_at && (
                  <p className={cn("mt-1 text-[10px]", mine ? "text-primary-foreground/60" : "text-muted-foreground")}>
                    {new Intl.DateTimeFormat("ru-RU", { hour: "2-digit", minute: "2-digit" }).format(new Date(m.created_at))}
                  </p>
                )}
              </div>
            </div>
          );
        })}
      </div>

      <div className="flex items-center gap-2 border-t border-border p-3">
        <input
          ref={imageInput}
          type="file"
          accept="image/*"
          className="hidden"
          onChange={(e) => e.target.files?.[0] && upload(e.target.files[0], "image")}
        />
        <input
          ref={fileInput}
          type="file"
          className="hidden"
          onChange={(e) => e.target.files?.[0] && upload(e.target.files[0], "file")}
        />
        <Button variant="ghost" size="icon" onClick={() => imageInput.current?.click()} aria-label="Фото" disabled={sending}>
          <ImagePlus className="size-4" />
        </Button>
        <Button variant="ghost" size="icon" onClick={() => fileInput.current?.click()} aria-label="Файл" disabled={sending}>
          <Paperclip className="size-4" />
        </Button>
        <Input
          value={text}
          onChange={(e) => setText(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && !e.shiftKey && (e.preventDefault(), submit())}
          placeholder="Сообщение…"
        />
        <Button size="icon" onClick={submit} disabled={sending || !text.trim()} aria-label="Отправить">
          {sending ? <Loader2 className="size-4 animate-spin" /> : <Send className="size-4" />}
        </Button>
      </div>
    </div>
  );
}
