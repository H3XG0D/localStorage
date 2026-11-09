// Panel API client (admin + operator scopes). Separate bearer tokens from the
// public site, stored under their own localStorage keys. Reuses fetch semantics
// from the public client but with panel-specific token handling and cookie auth.
import { isJwtExpired, isLocalDevPanel } from "@/panel/lib/devHost";

export type PanelScope = "admin" | "operator";

const TOKEN_KEY: Record<PanelScope, string> = {
  admin: "focuspay_admin_token",
  operator: "focuspay_operator_token",
};

export const API_BASE = "/api";

// Keep every panel request bounded: session bootstrap and dashboard widgets must
// always leave their loading state even when a proxy or network connection stalls.
export const PANEL_API_TIMEOUT_MS = 20_000;

const authLossListeners = new Set<(scope: PanelScope) => void>();

/** Subscribe to loss of a panel session. Returns unsubscribe. */
export function onPanelAuthLoss(cb: (scope: PanelScope) => void): () => void {
  authLossListeners.add(cb);
  return () => {
    authLossListeners.delete(cb);
  };
}

function notifyAuthLoss(scope: PanelScope) {
  for (const cb of [...authLossListeners]) {
    try {
      cb(scope);
    } catch {
      /* ignore listener errors */
    }
  }
}

export function getPanelToken(scope: PanelScope): string | null {
  const token = window.localStorage.getItem(TOKEN_KEY[scope]);
  if (token && isJwtExpired(token)) {
    window.localStorage.removeItem(TOKEN_KEY[scope]);
    return null;
  }
  return token;
}
export function setPanelToken(scope: PanelScope, token: string) {
  window.localStorage.setItem(TOKEN_KEY[scope], token);
}
export function clearPanelToken(scope: PanelScope) {
  window.localStorage.removeItem(TOKEN_KEY[scope]);
}

/** Login / 2FA may run without a stored bearer. */
export function isPanelAuthBootstrapPath(path: string): boolean {
  const p = path.replace(/^\/api/, "").split("?")[0];
  return /^\/auth\/(admin|operator)\/login(\/2fa)?$/.test(p);
}

export class PanelApiError extends Error {
  status: number;
  payload: unknown;
  constructor(message: string, status: number, payload: unknown) {
    super(message);
    this.name = "PanelApiError";
    this.status = status;
    this.payload = payload;
  }
}

function isRejectedPanelSession(scope: PanelScope, status: number, detail: unknown): boolean {
  return status === 401 || (scope === "admin" && status === 403 && detail === "Admin access required");
}

function formatApiDetail(detail: unknown, status: number): string {
  if (typeof detail === "string" && detail.trim()) {
    const text = detail.trim();
    if (status === 404 && /^not found$/i.test(text)) return "Не найдено";
    return text;
  }
  if (Array.isArray(detail)) {
    const parts = detail
      .map((item) => {
        if (typeof item === "string") return item;
        if (item && typeof item === "object" && "msg" in item) {
          const msg = String((item as { msg?: unknown }).msg || "").trim();
          const loc = (item as { loc?: unknown }).loc;
          const where = Array.isArray(loc) ? loc.filter((x) => x !== "body" && x !== "query").join(".") : "";
          return where && msg ? `${where}: ${msg}` : msg;
        }
        return "";
      })
      .filter(Boolean);
    if (parts.length) return parts.slice(0, 3).join("; ");
  }
  if (detail && typeof detail === "object" && "message" in detail) {
    const m = String((detail as { message?: unknown }).message || "").trim();
    if (m) return m;
  }
  if (status === 401) return "Нет сессии";
  if (status === 403) return "Недостаточно прав";
  if (status === 404) return "Не найдено";
  if (status === 429) return "Слишком много запросов";
  if (status === 408 || status === 504) return "Сервер не успел ответить. Обновите список — если заявка уже закрыта, не дублируйте.";
  if (status === 502) return "Шлюз недоступен, повторите через несколько секунд";
  if (status === 503) return "Сервис временно недоступен";
  if (status >= 500) return "Ошибка сервера";
  return "Ошибка запроса";
}

type Query = Record<string, unknown>;

export interface PanelApiOptions extends Omit<RequestInit, "body"> {
  body?: unknown;
  scope: PanelScope;
  query?: Query;
  timeoutMs?: number;
}

function buildQuery(query?: Query): string {
  if (!query) return "";
  const p = new URLSearchParams();
  for (const [k, v] of Object.entries(query)) if (v !== undefined && v !== null) p.set(k, String(v));
  const s = p.toString();
  return s ? `?${s}` : "";
}

export async function panelApi<T = unknown>(path: string, options: PanelApiOptions): Promise<T> {
  const { body, scope, query, headers, signal, timeoutMs = PANEL_API_TIMEOUT_MS, ...rest } = options;
  const h = new Headers(headers);
  const isForm = typeof FormData !== "undefined" && body instanceof FormData;
  let payload: BodyInit | undefined;
  if (body !== undefined && body !== null) {
    if (isForm) payload = body as FormData;
    else {
      payload = JSON.stringify(body);
      if (!h.has("Content-Type")) h.set("Content-Type", "application/json");
    }
  }
  const token = getPanelToken(scope);
  // Do not hit protected endpoints without a bearer — avoids 401→operator_probe spam
  // from dead polling after session expiry. Local Vite may inject the staff token.
  if (!token && !isPanelAuthBootstrapPath(path) && !isLocalDevPanel()) {
    notifyAuthLoss(scope);
    throw new PanelApiError("Нет сессии", 401, null);
  }
  if (token) h.set("Authorization", `Bearer ${token}`);

  const url = (path.startsWith("/api") ? path : API_BASE + path) + buildQuery(query);
  const controller = new AbortController();
  const abort = () => controller.abort();
  if (signal) signal.addEventListener("abort", abort, { once: true });
  if (signal?.aborted) abort();
  const timeout = window.setTimeout(abort, timeoutMs);

  let res: Response;
  let text: string;
  try {
    res = await fetch(url, { ...rest, headers: h, body: payload, credentials: "include", signal: controller.signal });
    text = await res.text();
  } catch {
    throw new PanelApiError(
      "Нет ответа сервера. Обновите список — если операция уже прошла, не нажимайте повторно.",
      0,
      null,
    );
  } finally {
    window.clearTimeout(timeout);
    if (signal) signal.removeEventListener("abort", abort);
  }

  let data: unknown = null;
  if (text) {
    try {
      data = JSON.parse(text);
    } catch {
      data = text;
    }
  }
  if (!res.ok) {
    const detail =
      data && typeof data === "object" && "detail" in data ? (data as { detail?: unknown }).detail : null;
    if (isRejectedPanelSession(scope, res.status, detail)) {
      clearPanelToken(scope);
      notifyAuthLoss(scope);
    }
    throw new PanelApiError(formatApiDetail(detail, res.status), res.status, data);
  }
  return data as T;
}
