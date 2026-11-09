export interface ChatMessageContentModel {
  id: number;
  sender_role: "buyer" | "admin" | "exchanger" | string;
  message_type?: "text" | "image" | "video" | "document" | "audio" | "sticker" | string;
  body: string;
  attachment_id?: string | null;
  attachment_filename?: string | null;
  image_url?: string;
  admin_image_url?: string;
  video_url?: string;
  file_url?: string;
  audio_url?: string;
  sticker_url?: string;
  sticker_emoji?: string | null;
  created_at?: string | null;
}

function mediaUrl(message: ChatMessageContentModel): string | undefined {
  return (
    message.image_url ||
    message.admin_image_url ||
    message.video_url ||
    message.file_url ||
    message.audio_url ||
    message.sticker_url
  );
}

export function ChatMessageContent({
  message,
}: {
  message: ChatMessageContentModel;
  variant?: "buyer" | "admin";
}) {
  const msgType = message.message_type || "text";
  const url = mediaUrl(message);
  const isImage = msgType === "image" && message.attachment_id && url;
  const isVideo = msgType === "video" && message.attachment_id && url;
  const isDocument = msgType === "document" && message.attachment_id && url;
  const isAudio = msgType === "audio" && message.attachment_id && url;
  const isSticker = msgType === "sticker";
  const stickerUrl = msgType === "sticker" && url ? url : undefined;

  return (
    <>
      {stickerUrl && (
        <img
          src={stickerUrl}
          alt={message.sticker_emoji || "Стикер"}
          className="max-w-[160px] max-h-[160px] object-contain"
          loading="lazy"
        />
      )}
      {isSticker && !stickerUrl && message.body ? (
        <span className="text-5xl leading-none">{message.body}</span>
      ) : null}
      {isImage && url && (
        <a href={url} target="_blank" rel="noreferrer" className="block">
          <img
            src={url}
            alt="Фото"
            className="max-w-full max-h-48 rounded-lg object-contain bg-black/20"
            loading="lazy"
          />
        </a>
      )}
      {isVideo && url && (
        <video
          src={url}
          controls
          className="max-w-full max-h-48 rounded-lg bg-black/20"
          preload="metadata"
        />
      )}
      {isDocument && url && (
        <a
          href={url}
          target="_blank"
          rel="noreferrer"
          className="inline-flex items-center gap-2 text-cyan-300 hover:text-cyan-200 underline break-all"
        >
          <span>📄</span>
          <span>{message.attachment_filename || "Скачать файл"}</span>
        </a>
      )}
      {isAudio && url && (
        <audio src={url} controls className="max-w-full" preload="metadata" />
      )}
      {message.body ? (
        <p
          className={
            isImage || isVideo || isDocument || isAudio || isSticker
              ? "mt-1.5 whitespace-pre-wrap break-words"
              : "whitespace-pre-wrap break-words"
          }
        >
          {message.body.split(/(https:\/\/t\.me\/[^\s]+)/g).map((part, i) =>
            part.startsWith("https://t.me/") ? (
              <a
                key={i}
                href={part}
                target="_blank"
                rel="noreferrer"
                className="underline text-cyan-300 hover:text-cyan-200"
              >
                {part.replace("https://t.me/", "@")}
              </a>
            ) : (
              <span key={i}>{part}</span>
            ),
          )}
        </p>
      ) : null}
      {!isImage && !isVideo && !isDocument && !isAudio && !isSticker && !message.body ? (
        <span className="text-gray-500">…</span>
      ) : null}
    </>
  );
}
