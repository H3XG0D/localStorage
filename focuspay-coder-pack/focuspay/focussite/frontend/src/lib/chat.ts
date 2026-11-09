// Buyer↔operator chat (public scope). Polling-based; auth via bearer or the
// X-Guest-Session header (both handled by the shared api() client).
import { api } from "@/lib/api";

export type SenderRole = "buyer" | "admin" | "operator" | "system" | string;
export type MessageType = "text" | "image" | "video" | "document" | "audio";

export interface ChatMessage {
  id: number;
  sender_role: SenderRole;
  message_type: MessageType;
  body: string;
  attachment_id: string | null;
  attachment_filename: string | null;
  created_at: string | null;
  image_url?: string;
  video_url?: string;
  file_url?: string;
  audio_url?: string;
}

export interface ChatThread {
  id: number;
  order_id: string | null;
  source: string;
  last_message_at: string | null;
  created_at: string | null;
}

export interface Conversation {
  thread: ChatThread | null;
  messages: ChatMessage[];
  has_more_older: boolean;
  oldest_id: number | null;
}

export function getConversation(opts: { order_id?: string; after_id?: number; before_id?: number; limit?: number } = {}) {
  return api<Conversation>("/public/chat", {
    method: "GET",
    query: { order_id: opts.order_id, after_id: opts.after_id, before_id: opts.before_id, limit: opts.limit ?? 100 },
  });
}

export function sendMessage(body: string, order_id?: string) {
  return api<{ message: ChatMessage }>("/public/chat/messages", { method: "POST", body: { body, order_id } });
}

export function sendImage(file: File, order_id?: string, caption?: string) {
  const form = new FormData();
  form.append("file", file);
  if (caption) form.append("caption", caption);
  if (order_id) form.append("order_id", order_id);
  return api<{ message: ChatMessage }>("/public/chat/messages/image", { method: "POST", body: form });
}

export function sendFile(file: File, order_id?: string) {
  const form = new FormData();
  form.append("file", file);
  if (order_id) form.append("order_id", order_id);
  return api<{ message: ChatMessage }>("/public/chat/messages/file", { method: "POST", body: form });
}
