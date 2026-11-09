import { useCallback, useEffect, useRef, useState, type ClipboardEvent, type DragEvent, type FormEvent, type KeyboardEvent } from "react";
import {
  Eye,
  EyeOff,
  FileAudio,
  FileText,
  FileVideo,
  Loader2,
  MessageCircle,
  Paperclip,
  Send,
  Trash2,
  X,
} from "lucide-react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { ApiError } from "@/lib/api";
import {
  exchangerChat,
  exchangerSendChat,
  exchangerSendChatFile,
  exchangerSendChatImage,
  type PortalRecord,
} from "@/lib/portals";
import { cn } from "@/lib/utils";

type HelpPref = "open" | "hidden" | "gone";

const POLL_MS = 5000;
const MAX_BODY = 2000;
const MAX_IMAGE_BYTES = 5 * 1024 * 1024;
const MAX_VIDEO_BYTES = 50 * 1024 * 1024;
const MAX_DOCUMENT_BYTES = 20 * 1024 * 1024;
const MAX_AUDIO_BYTES = 10 * 1024 * 1024;

const IMAGE_MIMES = new Set(["image/jpeg", "image/jpg", "image/png", "image/webp", "image/gif"]);
const VIDEO_MIMES = new Set(["video/mp4", "video/webm", "video/quicktime", "video/x-msvideo"]);
const AUDIO_MIMES = new Set(["audio/ogg", "audio/mpeg", "audio/mp4", "audio/x-m4a", "audio/webm"]);
const DOCUMENT_MIMES = new Set([
  "application/pdf",
  "application/msword",
  "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
]);
const IMAGE_EXTS = new Set([".jpg", ".jpeg", ".png", ".webp", ".gif"]);
const VIDEO_EXTS = new Set([".mp4", ".webm", ".mov", ".avi"]);
const AUDIO_EXTS = new Set([".ogg", ".mp3", ".m4a", ".mpeg"]);
const DOCUMENT_EXTS = new Set([".pdf", ".doc", ".docx"]);

const FILE_ACCEPT = [
  "image/jpeg",
  "image/png",
  "image/webp",
  "image/gif",
  "video/mp4",
  "video/webm",
  "video/quicktime",
  ".pdf",
  ".doc",
  ".docx",
  ".mp3",
  ".m4a",
  ".ogg",
  ".mov",
  ".avi",
].join(",");

const ERR_IMAGE = "Допустимы только JPG, PNG, WEBP, GIF (макс. 5 МБ)";
const ERR_VIDEO = "Допустимы MP4, WEBM, MOV (макс. 50 МБ)";
const ERR_DOCUMENT = "Допустимы PDF, DOC, DOCX, изображения (макс. 20 МБ)";
const ERR_AUDIO = "Допустимы OGG, MP3, M4A (макс. 10 МБ)";
const ERR_TYPE = "Неподдерживаемый тип файла";

type QueueItem = {
  id: string;
  file: File;
  kind: "image" | "file";
  previewUrl?: string;
};

function fileExt(name: string) {
  const i = name.lastIndexOf(".");
  return i >= 0 ? name.slice(i).toLowerCase() : "";
}

function classifyChatFile(file: File): { ok: true; kind: "image" | "file" } | { ok: false; error: string } {
  const mime = (file.type || "").split(";")[0].trim().toLowerCase();
  const ext = fileExt(file.name);
  const isImage = IMAGE_MIMES.has(mime) || IMAGE_EXTS.has(ext);
  const isVideo = VIDEO_MIMES.has(mime) || VIDEO_EXTS.has(ext);
  const isAudio = AUDIO_MIMES.has(mime) || AUDIO_EXTS.has(ext);
  const isDocument = DOCUMENT_MIMES.has(mime) || DOCUMENT_EXTS.has(ext);

  if (isImage) {
    if (file.size > MAX_IMAGE_BYTES) return { ok: false, error: ERR_IMAGE };
    return { ok: true, kind: "image" };
  }
  if (isVideo) {
    if (file.size > MAX_VIDEO_BYTES) return { ok: false, error: ERR_VIDEO };
    return { ok: true, kind: "file" };
  }
  if (isAudio) {
    if (file.size > MAX_AUDIO_BYTES) return { ok: false, error: ERR_AUDIO };
    return { ok: true, kind: "file" };
  }
  if (isDocument) {
    if (file.size > MAX_DOCUMENT_BYTES) return { ok: false, error: ERR_DOCUMENT };
    return { ok: true, kind: "file" };
  }
  return { ok: false, error: ERR_TYPE };
}

function formatBytes(n: number) {
  if (n < 1024) return `${n} Б`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} КБ`;
  return `${(n / (1024 * 1024)).toFixed(1)} МБ`;
}

function errorMessage(error: unknown, fallback: string) {
  return error instanceof ApiError ? error.message : fallback;
}

function text(value: unknown, fallback = "—") {
  return value == null || String(value).trim() === "" ? fallback : String(value);
}

function dayKey(iso: string) {
  if (!iso) return "";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "";
  return `${d.getFullYear()}-${d.getMonth()}-${d.getDate()}`;
}

function formatChatMessageTime(iso: string | null | undefined): string {
  if (!iso) return "";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "";
  const now = new Date();
  const sameDay = d.getFullYear() === now.getFullYear() && d.getMonth() === now.getMonth() && d.getDate() === now.getDate();
  if (sameDay) return d.toLocaleTimeString("ru-RU", { hour: "2-digit", minute: "2-digit" });
  if (d.getFullYear() === now.getFullYear()) {
    return d.toLocaleString("ru-RU", { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" });
  }
  return d.toLocaleString("ru-RU", { day: "2-digit", month: "2-digit", year: "numeric", hour: "2-digit", minute: "2-digit" });
}

function dayLabel(iso: string) {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "";
  const now = new Date();
  const start = (value: Date) => new Date(value.getFullYear(), value.getMonth(), value.getDate()).getTime();
  const diff = start(now) - start(d);
  if (diff === 0) return "Сегодня";
  if (diff === 86400000) return "Вчера";
  return d.toLocaleDateString("ru-RU", { day: "numeric", month: "long" });
}

function collectFiles(from: FileList | File[] | DataTransferItemList | undefined | null): File[] {
  if (!from) return [];
  if (from instanceof FileList || Array.isArray(from)) return Array.from(from);
  const files: File[] = [];
  for (const item of Array.from(from)) {
    if (item.kind === "file") {
      const file = item.getAsFile();
      if (file) files.push(file);
    }
  }
  return files;
}

function revokePreview(item: QueueItem) {
  if (item.previewUrl) URL.revokeObjectURL(item.previewUrl);
}

export function ExchangerChatPanel({
  helpPrefs,
  onHelp,
  draft,
}: {
  helpPrefs: { chat?: HelpPref };
  onHelp: (page: "chat", pref: HelpPref) => void;
  draft?: string;
}) {
  const help = helpPrefs.chat ?? "hidden";
  const [messages, setMessages] = useState<PortalRecord[]>([]);
  const [body, setBody] = useState("");
  const [queue, setQueue] = useState<QueueItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [sending, setSending] = useState(false);
  const [uploadProgress, setUploadProgress] = useState<{ current: number; total: number } | null>(null);
  const [dragging, setDragging] = useState(false);
  const scrollRef = useRef<HTMLDivElement>(null);
  const fileInput = useRef<HTMLInputElement>(null);
  const textRef = useRef<HTMLTextAreaElement>(null);
  const dragDepth = useRef(0);
  const queueRef = useRef(queue);
  queueRef.current = queue;

  const load = useCallback(async () => {
    try {
      const result = await exchangerChat({ limit: 100 });
      setMessages(result.messages ?? []);
    } catch (error) {
      if (!(error instanceof ApiError && error.status === 401)) toast.error(errorMessage(error, "Не удалось загрузить чат"));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
    const timer = window.setInterval(() => void load(), POLL_MS);
    return () => window.clearInterval(timer);
  }, [load]);

  useEffect(() => {
    if (draft) setBody(draft);
  }, [draft]);

  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: "smooth" });
  }, [messages]);

  useEffect(() => {
    const el = textRef.current;
    if (!el) return;
    el.style.height = "0px";
    el.style.height = `${Math.min(Math.max(el.scrollHeight, 40), 120)}px`;
  }, [body]);

  useEffect(() => {
    return () => {
      queueRef.current.forEach(revokePreview);
    };
  }, []);

  function addFiles(files: File[]) {
    if (!files.length) return;
    const next: QueueItem[] = [];
    for (const file of files) {
      const classified = classifyChatFile(file);
      if (!classified.ok) {
        toast.error(`${file.name}: ${classified.error}`);
        continue;
      }
      next.push({
        id: `${Date.now()}-${Math.random().toString(16).slice(2)}`,
        file,
        kind: classified.kind,
        previewUrl: classified.kind === "image" ? URL.createObjectURL(file) : undefined,
      });
    }
    if (next.length) setQueue((items) => [...items, ...next]);
  }

  function removeQueued(id: string) {
    setQueue((items) => {
      const item = items.find((entry) => entry.id === id);
      if (item) revokePreview(item);
      return items.filter((entry) => entry.id !== id);
    });
  }

  async function submit() {
    if (sending) return;
    const caption = body.trim();
    if (!caption && queue.length === 0) return;
    setSending(true);
    const pending = [...queue];
    let captionUsed = false;
    try {
      if (pending.length === 0) {
        const result = await exchangerSendChat(caption);
        setMessages((items) => [...items, result.message]);
        setBody("");
        return;
      }
      for (let i = 0; i < pending.length; i++) {
        setUploadProgress({ current: i + 1, total: pending.length });
        const item = pending[i];
        const cap = !captionUsed && caption ? caption : undefined;
        const result =
          item.kind === "image" ? await exchangerSendChatImage(item.file, cap) : await exchangerSendChatFile(item.file, cap);
        setMessages((items) => [...items, result.message]);
        if (cap) {
          captionUsed = true;
          setBody("");
        }
        revokePreview(item);
        setQueue((items) => items.filter((entry) => entry.id !== item.id));
      }
      setBody("");
      setQueue([]);
    } catch (error) {
      toast.error(errorMessage(error, pending.length ? "Не удалось загрузить файл" : "Не удалось отправить сообщение"));
    } finally {
      setSending(false);
      setUploadProgress(null);
    }
  }

  function onSubmit(e: FormEvent) {
    e.preventDefault();
    void submit();
  }

  function onComposerKey(e: KeyboardEvent<HTMLTextAreaElement>) {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      void submit();
    }
  }

  function onPaste(e: ClipboardEvent<HTMLDivElement>) {
    const fromItems = collectFiles(e.clipboardData?.items);
    const fromList = collectFiles(e.clipboardData?.files);
    const files = fromList.length ? fromList : fromItems;
    if (!files.length) return;
    e.preventDefault();
    addFiles(files);
  }

  function onDragEnter(e: DragEvent<HTMLDivElement>) {
    if (![...e.dataTransfer.types].includes("Files")) return;
    e.preventDefault();
    dragDepth.current += 1;
    setDragging(true);
  }

  function onDragLeave(e: DragEvent<HTMLDivElement>) {
    if (![...e.dataTransfer.types].includes("Files") && dragDepth.current === 0) return;
    e.preventDefault();
    dragDepth.current = Math.max(0, dragDepth.current - 1);
    if (dragDepth.current === 0) setDragging(false);
  }

  function onDragOver(e: DragEvent<HTMLDivElement>) {
    if (![...e.dataTransfer.types].includes("Files")) return;
    e.preventDefault();
    e.dataTransfer.dropEffect = "copy";
  }

  function onDrop(e: DragEvent<HTMLDivElement>) {
    e.preventDefault();
    dragDepth.current = 0;
    setDragging(false);
    addFiles(collectFiles(e.dataTransfer.files));
  }

  const canSend = !sending && (Boolean(body.trim()) || queue.length > 0);

  return (
    <div className="mx-auto flex min-h-0 w-full max-w-3xl flex-1 flex-col gap-2 pt-1 md:pt-0">
      <ChatHelp pref={help} onChange={(pref) => onHelp("chat", pref)} />
      <div
        className="relative flex min-h-0 flex-1 flex-col overflow-hidden rounded-xl border border-border bg-card"
        onPaste={onPaste}
        onDragEnter={onDragEnter}
        onDragLeave={onDragLeave}
        onDragOver={onDragOver}
        onDrop={onDrop}
      >
        {dragging && (
          <div className="pointer-events-none absolute inset-0 z-10 flex items-center justify-center rounded-xl border-2 border-dashed border-foreground/40 bg-background/85">
            <p className="text-sm font-medium">Отпустите файлы</p>
          </div>
        )}
        <div className="shrink-0 border-b border-border px-4 py-3">
          <div className="flex items-center gap-2">
            <MessageCircle className="size-5" />
            <p className="text-sm font-semibold">Чат с оператором</p>
          </div>
          <p className="mt-1 text-xs text-muted-foreground">Номер сделки, чек, видео или PDF — перетащите сюда или вставьте Ctrl+V.</p>
        </div>
        <div ref={scrollRef} className="scrollbar-thin min-h-0 flex-1 space-y-2 overflow-y-auto overscroll-contain p-4">
          {loading ? (
            <Loader2 className="mx-auto mt-8 size-5 animate-spin text-muted-foreground" />
          ) : messages.length === 0 ? (
            <div className="flex h-full min-h-[12rem] flex-col items-center justify-center gap-2 px-6 text-center">
              <Paperclip className="size-8 text-muted-foreground/40" />
              <p className="text-sm text-muted-foreground">Пока тихо. Перетащите чек, видео или PDF — или напишите оператору.</p>
            </div>
          ) : (
            <MessageList messages={messages} />
          )}
        </div>
        <form onSubmit={onSubmit} className="shrink-0 border-t border-border p-3">
          {queue.length > 0 && (
            <div className="mb-2 flex gap-2 overflow-x-auto pb-1">
              {queue.map((item) => (
                <div key={item.id} className="flex min-w-[10rem] max-w-[14rem] items-center gap-2 rounded-lg border border-border bg-muted/40 px-2 py-1.5">
                  {item.previewUrl ? (
                    <img src={item.previewUrl} alt="" className="size-10 shrink-0 rounded object-cover" />
                  ) : (
                    <FileIcon name={item.file.name} className="size-4 shrink-0 text-muted-foreground" />
                  )}
                  <div className="min-w-0 flex-1">
                    <p className="truncate text-xs font-medium">{item.file.name}</p>
                    <p className="text-[10px] text-muted-foreground">{formatBytes(item.file.size)}</p>
                  </div>
                  <button
                    type="button"
                    className="rounded p-0.5 text-muted-foreground hover:bg-muted hover:text-foreground disabled:opacity-50"
                    aria-label="Убрать файл"
                    disabled={sending}
                    onClick={() => removeQueued(item.id)}
                  >
                    <X className="size-3.5" />
                  </button>
                </div>
              ))}
            </div>
          )}
          <div className="flex items-end gap-2">
            <input
              ref={fileInput}
              type="file"
              accept={FILE_ACCEPT}
              multiple
              className="hidden"
              tabIndex={-1}
              onChange={(e) => {
                addFiles(collectFiles(e.target.files));
                e.target.value = "";
              }}
            />
            <Button
              type="button"
              variant="ghost"
              size="icon"
              className="shrink-0"
              aria-label="Прикрепить файл"
              title="Прикрепить файл"
              disabled={sending}
              onClick={() => fileInput.current?.click()}
            >
              <Paperclip className="size-4" />
            </Button>
            <textarea
              ref={textRef}
              value={body}
              onChange={(e) => setBody(e.target.value)}
              onKeyDown={onComposerKey}
              placeholder="напишите оператору"
              maxLength={MAX_BODY}
              rows={1}
              disabled={sending}
              className="max-h-[120px] min-h-[40px] flex-1 resize-none rounded-lg border border-input bg-background px-3 py-2 text-sm outline-none placeholder:text-muted-foreground focus-visible:ring-2 focus-visible:ring-ring disabled:cursor-not-allowed disabled:opacity-50"
            />
            <Button type="submit" size="icon" className="shrink-0" disabled={!canSend} aria-label="Отправить сообщение" title="Отправить сообщение">
              {sending ? <Loader2 className="size-4 animate-spin" /> : <Send className="size-4" />}
            </Button>
          </div>
          {uploadProgress && (
            <p className="mt-2 text-[11px] text-muted-foreground">
              Отправляется {uploadProgress.current}/{uploadProgress.total}
            </p>
          )}
        </form>
      </div>
    </div>
  );
}

function ChatHelp({ pref, onChange }: { pref: HelpPref; onChange: (pref: HelpPref) => void }) {
  if (pref === "gone") return null;
  if (pref === "hidden") {
    return (
      <button
        type="button"
        onClick={() => onChange("open")}
        className="flex w-full shrink-0 items-center justify-between rounded-lg border border-dashed border-border px-3 py-1.5 text-left text-xs text-muted-foreground hover:text-foreground"
      >
        <span>Инструкция скрыта</span>
        <span className="inline-flex items-center gap-1 font-medium">
          <Eye className="size-3.5" /> Показать
        </span>
      </button>
    );
  }
  return (
    <div className="flex shrink-0 items-start justify-between gap-2 rounded-lg border border-border bg-muted/30 px-3 py-2">
      <p className="text-xs text-muted-foreground">
        Пишите здесь. Сразу номер сделки — так быстрее найдут. Чек, видео и PDF можно перетащить в окно или вставить Ctrl+V.
      </p>
      <div className="flex shrink-0 gap-1">
        <Button type="button" variant="ghost" size="sm" onClick={() => onChange("hidden")}>
          <EyeOff className="size-3.5" /> Скрыть
        </Button>
        <Button type="button" variant="ghost" size="sm" onClick={() => onChange("gone")}>
          <Trash2 className="size-3.5" /> Убрать
        </Button>
      </div>
    </div>
  );
}

function MessageList({ messages }: { messages: PortalRecord[] }) {
  const blocks: Array<{ id: string; day?: string; message: PortalRecord }> = [];
  let lastDay = "";
  for (const message of messages) {
    const created = String(message.created_at || "");
    const key = dayKey(created);
    const day = key && key !== lastDay ? dayLabel(created) : "";
    if (key) lastDay = key;
    blocks.push({ id: String(message.id), day: day || undefined, message });
  }
  return (
    <>
      {blocks.map((block) => (
        <div key={block.id}>
          {block.day ? (
            <div className="flex justify-center py-1">
              <span className="rounded-full bg-muted px-2.5 py-0.5 text-[11px] text-muted-foreground">{block.day}</span>
            </div>
          ) : null}
          <ChatMessage message={block.message} />
        </div>
      ))}
    </>
  );
}

function FileIcon({ name, className }: { name: string; className?: string }) {
  const ext = fileExt(name);
  if (VIDEO_EXTS.has(ext)) return <FileVideo className={className} />;
  if (AUDIO_EXTS.has(ext)) return <FileAudio className={className} />;
  return <FileText className={className} />;
}

function ChatMessage({ message }: { message: PortalRecord }) {
  const fromExchanger = message.sender_role === "exchanger";
  const imageUrl = typeof message.image_url === "string" ? message.image_url : "";
  const videoUrl = typeof message.video_url === "string" ? message.video_url : "";
  const fileUrl = typeof message.file_url === "string" ? message.file_url : "";
  const audioUrl = typeof message.audio_url === "string" ? message.audio_url : "";
  const bodyText = String(message.body || "").trim();
  const filename = text(message.attachment_filename, "Файл");
  const hasMedia = Boolean(imageUrl || videoUrl || fileUrl || audioUrl);
  return (
    <div className={`flex ${fromExchanger ? "justify-end" : "justify-start"}`}>
      <div
        className={cn(
          "max-w-[85%] rounded-2xl px-3 py-2 text-sm",
          fromExchanger ? "rounded-br-md bg-foreground text-background" : "rounded-bl-md bg-muted text-foreground",
        )}
      >
        {imageUrl && (
          <a href={imageUrl} target="_blank" rel="noreferrer" className="block">
            <img src={imageUrl} alt="" className="mb-1 max-h-64 max-w-full rounded-xl object-contain" />
          </a>
        )}
        {videoUrl && <video src={videoUrl} controls className="mb-1 max-h-64 w-full rounded-xl" preload="metadata" />}
        {fileUrl && (
          <a
            href={fileUrl}
            target="_blank"
            rel="noreferrer"
            className={cn(
              "mb-1 flex items-center gap-2 rounded-lg border px-2.5 py-2",
              fromExchanger ? "border-background/20 bg-background/10" : "border-border bg-background/50",
            )}
          >
            <FileText className="size-4 shrink-0" />
            <span className="min-w-0">
              <span className="block truncate text-xs font-medium">{filename}</span>
              <span className={cn("block text-[10px]", fromExchanger ? "text-background/60" : "text-muted-foreground")}>Открыть</span>
            </span>
          </a>
        )}
        {audioUrl && <audio src={audioUrl} controls className="mb-1 w-full" />}
        {bodyText ? <p className="whitespace-pre-wrap break-words">{bodyText}</p> : !hasMedia ? <p>Вложение</p> : null}
        <p className={cn("mt-1 text-right text-[10px] leading-none", fromExchanger ? "text-background/60" : "text-muted-foreground")}>
          {formatChatMessageTime(typeof message.created_at === "string" ? message.created_at : null)}
        </p>
      </div>
    </div>
  );
}
