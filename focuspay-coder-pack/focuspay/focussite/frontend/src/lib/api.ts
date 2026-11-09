// FocusPay public API client. Same-origin requests only.
// Same-origin `/api` (nginx proxies to FastAPI :8000). Supports Bearer JWT
// (localStorage) + HttpOnly cookie session (credentials:"include"), plus the
// anti-fraud / attribution headers X-Guest-Session and X-Device-Fingerprint.

export const API_BASE = "/api";

/** Account kinds that hold their own bearer token. Regular buyer = "user". */
export type TokenScope = "user" | "partner" | "exchanger";

const TOKEN_KEYS: Record<TokenScope, string> = {
  user: "focuspay_user_token",
  partner: "focuspay_partner_token",
  exchanger: "focuspay_exchanger_token",
};

const GUEST_KEY = "focuspay_guest_session";
const FP_KEY = "focuspay_device_fp";

function randomId(): string {
  try {
    if (typeof crypto !== "undefined" && crypto.randomUUID) return crypto.randomUUID();
  } catch {
    /* ignore */
  }
  return "xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx".replace(/[xy]/g, (c) => {
    const r = (Math.random() * 16) | 0;
    const v = c === "x" ? r : (r & 0x3) | 0x8;
    return v.toString(16);
  });
}

/** Stable per-browser guest-session UUID (used for attribution + guest→account merge). */
export function getGuestSession(): string {
  let id = window.localStorage.getItem(GUEST_KEY);
  if (!id) {
    id = randomId();
    window.localStorage.setItem(GUEST_KEY, id);
  }
  return id;
}

/** Lightweight device fingerprint (stable per browser). Server treats it as advisory. */
export function getDeviceFingerprint(): string {
  let fp = window.localStorage.getItem(FP_KEY);
  if (!fp) {
    const seed = [
      navigator.userAgent,
      navigator.language,
      screen.width + "x" + screen.height,
      new Date().getTimezoneOffset(),
    ].join("|");
    let hash = 0;
    for (let i = 0; i < seed.length; i++) hash = (hash * 31 + seed.charCodeAt(i)) | 0;
    fp = Math.abs(hash).toString(16) + randomId().slice(0, 8);
    window.localStorage.setItem(FP_KEY, fp);
  }
  return fp;
}

export function getToken(scope: TokenScope = "user"): string | null {
  return window.localStorage.getItem(TOKEN_KEYS[scope]);
}
export function setToken(scope: TokenScope, token: string) {
  window.localStorage.setItem(TOKEN_KEYS[scope], token);
}
export function clearToken(scope: TokenScope) {
  window.localStorage.removeItem(TOKEN_KEYS[scope]);
}

export class ApiError extends Error {
  status: number;
  payload: unknown;
  constructor(message: string, status: number, payload: unknown) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.payload = payload;
  }
}

function formatApiDetail(detail: unknown, data?: unknown): string {
  if (typeof detail === "string" && detail.trim()) return detail.trim();
  if (Array.isArray(detail)) {
    const parts = detail.flatMap((item) => {
      if (!item || typeof item !== "object") return [];
      const msg = (item as { msg?: unknown }).msg;
      return typeof msg === "string" && msg.trim() ? [msg.trim()] : [];
    });
    if (parts.length) return parts.join("; ");
  }
  if (detail && typeof detail === "object") {
    const row = detail as { message?: unknown; detail?: unknown };
    if (typeof row.message === "string" && row.message.trim()) return row.message.trim();
    if (typeof row.detail === "string" && row.detail.trim()) return row.detail.trim();
  }
  if (typeof data === "string") {
    const text = data.trim();
    if (text && text.length < 180 && !text.startsWith("<")) return text;
  }
  return "Не удалось выполнить запрос";
}

export function apiErrorTableId(error: unknown): string | null {
  if (!(error instanceof ApiError)) return null;
  const payload = error.payload;
  if (!payload || typeof payload !== "object" || !("detail" in payload)) return null;
  const detail = (payload as { detail?: unknown }).detail;
  if (!detail || typeof detail !== "object") return null;
  const tableId = (detail as { table_id?: unknown }).table_id;
  return typeof tableId === "string" && tableId.trim() ? tableId.trim() : null;
}

type Query = Record<string, string | number | boolean | null | undefined>;

export interface ApiOptions extends Omit<RequestInit, "body"> {
  /** JSON body (object) or raw FormData for multipart uploads. */
  body?: unknown;
  /** Bearer scope to attach (defaults to "user"). Pass null to send no bearer. */
  scope?: TokenScope | null;
  /** Query-string params. */
  query?: Query;
}

function buildQuery(query?: Query): string {
  if (!query) return "";
  const params = new URLSearchParams();
  for (const [k, v] of Object.entries(query)) {
    if (v !== undefined && v !== null) params.set(k, String(v));
  }
  const s = params.toString();
  return s ? `?${s}` : "";
}

export async function api<T = unknown>(path: string, options: ApiOptions = {}): Promise<T> {
  const { body, scope = "user", query, headers, ...rest } = options;
  const h = new Headers(headers);

  const isForm = typeof FormData !== "undefined" && body instanceof FormData;
  let payload: BodyInit | undefined;
  if (body !== undefined && body !== null) {
    if (isForm) {
      payload = body as FormData;
    } else {
      payload = JSON.stringify(body);
      if (!h.has("Content-Type")) h.set("Content-Type", "application/json");
    }
  }

  const token = scope ? getToken(scope) : null;
  if (token) h.set("Authorization", `Bearer ${token}`);
  h.set("X-Guest-Session", getGuestSession());
  h.set("X-Device-Fingerprint", getDeviceFingerprint());

  const url = (path.startsWith("http") || path.startsWith("/api") ? path : API_BASE + path) + buildQuery(query);

  const response = await fetch(url, { ...rest, headers: h, body: payload, credentials: "include" });

  let data: unknown = null;
  const text = await response.text();
  if (text) {
    try {
      data = JSON.parse(text);
    } catch {
      data = text;
    }
  }

  if (!response.ok) {
    if (scope && response.status === 401) clearToken(scope);
    const detail =
      (data && typeof data === "object" && "detail" in data && (data as { detail?: unknown }).detail) || null;
    throw new ApiError(formatApiDetail(detail, data), response.status, data);
  }

  return data as T;
}
