// Panel support chat (admin + operator share the same thread model).
// Live SSE uses HttpOnly panel cookie (same-origin EventSource). No JWT in URL.
import { panelApi, type PanelScope } from "@/panel/lib/panelApi";

export interface ChatThread {
  id: number;
  order_id?: string | null;
  source?: string;
  admin_unread?: number;
  last_body?: string | null;
  last_sender?: string | null;
  needs_reply?: boolean;
  last_message_at?: string | null;
  telegram_user_id?: number | null;
  message_count?: number;
  buyer?: {
    user_id?: number;
    username?: string | null;
    first_name?: string | null;
    display_name?: string | null;
    avatar_url?: string | null;
    guest?: boolean;
    session_hint?: string | null;
    total_orders?: number;
    paid_orders?: number;
    turnover_rub?: number;
    active_order_id?: string | null;
    [k: string]: unknown;
  } | null;
  exchanger?: Record<string, unknown> | null;
  buyer_profile?: Record<string, unknown> | null;
  [k: string]: unknown;
}

export interface ChatMessage {
  id: number;
  sender_role: string;
  message_type: string;
  body: string;
  attachment_id?: string | null;
  attachment_filename?: string | null;
  created_at?: string | null;
  image_url?: string;
  admin_image_url?: string;
  video_url?: string;
  file_url?: string;
  audio_url?: string;
  sticker_url?: string;
  sticker_emoji?: string | null;
  sticker_file_id?: string | null;
  [k: string]: unknown;
}

export interface StickerSetInfo {
  name: string;
  title: string;
  stickers: { file_id: string; emoji?: string; file_unique_id?: string }[];
}

export interface MyStickerSetRow {
  id: number;
  operator_id: number;
  set_name: string;
  title?: string | null;
  created_at?: string | null;
}

export interface QuickReplyTemplate {
  id: number;
  operator_id?: number | null;
  scope?: "global" | "personal";
  title: string;
  body: string;
  trigger_phrase?: string | null;
  sort_order: number;
  is_active?: boolean;
  is_system?: boolean;
  version?: number;
  created_by_operator_id?: number | null;
  created_at?: string | null;
  updated_at?: string | null;
}

const base = (scope: PanelScope) => `/${scope}`;

export const listThreads = (
  scope: PanelScope,
  opts: { unread_only?: boolean; source?: string; limit?: number; offset?: number } = {},
) => panelApi<{ threads: ChatThread[]; total?: number; [k: string]: unknown }>(`${base(scope)}/chat/threads`, { scope, query: opts });

export const getThread = (
  scope: PanelScope,
  threadId: number,
  opts: { after_id?: number; before_id?: number; limit?: number } = {},
) =>
  panelApi<{
    thread: ChatThread;
    messages: ChatMessage[];
    buyer_profile?: Record<string, unknown>;
    has_more_older?: boolean;
    oldest_id?: number;
    [k: string]: unknown;
  }>(`${base(scope)}/chat/threads/${threadId}`, { scope, query: opts });

export const sendThreadMessage = (scope: PanelScope, threadId: number, body: string) =>
  panelApi<{ message: ChatMessage }>(`${base(scope)}/chat/threads/${threadId}/messages`, { scope, method: "POST", body: { body } });

export function sendThreadImage(scope: PanelScope, threadId: number, file: File, caption?: string) {
  const f = new FormData();
  f.append("file", file);
  if (caption) f.append("caption", caption);
  return panelApi<{ message: ChatMessage }>(`${base(scope)}/chat/threads/${threadId}/messages/image`, { scope, method: "POST", body: f });
}

export function sendThreadFile(scope: PanelScope, threadId: number, file: File, caption?: string) {
  const f = new FormData();
  f.append("file", file);
  if (caption) f.append("caption", caption);
  return panelApi<{ message: ChatMessage }>(`${base(scope)}/chat/threads/${threadId}/messages/file`, { scope, method: "POST", body: f });
}

export const sendThreadSticker = (scope: PanelScope, threadId: number, file_id: string) =>
  panelApi<{ message: ChatMessage }>(`${base(scope)}/chat/threads/${threadId}/messages/sticker`, {
    scope,
    method: "POST",
    body: { file_id },
  });

export const unreadCount = (scope: PanelScope) => panelApi<{ count: number }>(`${base(scope)}/chat/unread-count`, { scope });

export const initiateChat = (scope: PanelScope, order_id: string, body: string) =>
  panelApi<{ thread: ChatThread; message: ChatMessage }>(`${base(scope)}/chat/initiate`, { scope, method: "POST", body: { order_id, body } });

export const unreadBySource = (scope: PanelScope) =>
  panelApi<{ all: number; web: number; telegram: number; exchanger: number }>(`${base(scope)}/chat/unread-by-source`, { scope });

export const getStickerSets = (scope: PanelScope) =>
  panelApi<{ sets: StickerSetInfo[] }>(`${base(scope)}/chat/sticker-sets`, { scope });

export const listMyStickerSets = () =>
  panelApi<{ items: MyStickerSetRow[] }>("/operator/chat/my-sticker-sets", { scope: "operator" });

export const addMyStickerSet = (set_name: string) =>
  panelApi<{ item: MyStickerSetRow }>("/operator/chat/my-sticker-sets", {
    scope: "operator",
    method: "POST",
    body: { set_name },
  });

export const removeMyStickerSet = (rowId: number) =>
  panelApi<{ ok: boolean }>(`/operator/chat/my-sticker-sets/${rowId}`, {
    scope: "operator",
    method: "DELETE",
  });

export const listQuickReplies = (scope: PanelScope) =>
  panelApi<{ global: QuickReplyTemplate[]; personal: QuickReplyTemplate[] } | { items: QuickReplyTemplate[] }>(
    `${base(scope)}/chat/quick-replies`,
    { scope },
  );

export const createQuickReply = (
  scope: PanelScope,
  body: { title: string; body: string; trigger_phrase?: string; sort_order?: number },
) =>
  panelApi<{ item: QuickReplyTemplate }>(`${base(scope)}/chat/quick-replies`, {
    scope,
    method: "POST",
    body,
  });

export const updateQuickReply = (
  scope: PanelScope,
  id: number,
  body: Partial<{ title: string; body: string; trigger_phrase: string | null; sort_order: number; is_active: boolean }>,
) =>
  panelApi<{ item: QuickReplyTemplate }>(`${base(scope)}/chat/quick-replies/${id}`, {
    scope,
    method: "PATCH",
    body,
  });

export const deleteQuickReply = (scope: PanelScope, id: number) =>
  panelApi<{ ok: boolean }>(`${base(scope)}/chat/quick-replies/${id}`, { scope, method: "DELETE" });

/** Shared (global) templates — visible/editable by policy (RBAC on server). */
export const listSharedTemplates = () =>
  panelApi<{ items: QuickReplyTemplate[]; permissions?: string[] }>("/operator/chat/templates", {
    scope: "operator",
  });

export const createSharedTemplate = (body: {
  title: string;
  body: string;
  trigger_phrase?: string;
  sort_order?: number;
}) =>
  panelApi<{ item: QuickReplyTemplate }>("/operator/chat/templates", {
    scope: "operator",
    method: "POST",
    body,
  });

export const updateSharedTemplate = (
  id: number,
  body: Partial<{
    title: string;
    body: string;
    trigger_phrase: string | null;
    sort_order: number;
    is_active: boolean;
    version: number;
  }>,
) =>
  panelApi<{ item: QuickReplyTemplate }>(`/operator/chat/templates/${id}`, {
    scope: "operator",
    method: "PATCH",
    body,
  });

export const reorderSharedTemplates = (body: {
  a_id: number;
  b_id: number;
  a_version?: number;
  b_version?: number;
}) =>
  panelApi<{ items: QuickReplyTemplate[] }>("/operator/chat/templates/reorder", {
    scope: "operator",
    method: "POST",
    body,
  });

export const deleteSharedTemplate = (id: number, version?: number) =>
  panelApi<{ ok: boolean }>(
    `/operator/chat/templates/${id}${version != null ? `?version=${version}` : ""}`,
    {
      scope: "operator",
      method: "DELETE",
    },
  );

/** Panel SSE: cookie session (same-origin EventSource). No JWT in URL/logs. */
export function chatEventsUrl(scope: PanelScope): string {
  return `/api/${scope}/chat/events`;
}

/** @deprecated use chatEventsUrl("operator") */
export function operatorChatEventsUrl(): string {
  return chatEventsUrl("operator");
}
