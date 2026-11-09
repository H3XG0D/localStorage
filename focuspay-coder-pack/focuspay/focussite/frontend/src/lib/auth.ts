// Typed auth calls for the FocusPay public site (buyer / partner / exchanger).
import { ApiError, api, setToken, clearToken, type TokenScope } from "@/lib/api";

export interface User {
  id?: number;
  username?: string;
  display_name?: string;
  is_admin?: boolean;
  telegram_id?: number | null;
  has_password?: boolean;
  totp_enabled?: boolean;
  [key: string]: unknown;
}

export interface LoginSuccess {
  access_token: string;
  token_type?: string;
  user: User;
}
export interface Login2FARequired {
  requires_2fa: true;
  pre_auth_token: string;
  user: User;
}
export interface PartnerLoginPayload {
  account_kind: "partner";
  requires_2fa?: boolean;
  pre_auth_token?: string;
  access_token?: string;
  partner: Record<string, unknown>;
}
export type LoginResult = LoginSuccess | Login2FARequired | PartnerLoginPayload;

export interface Captcha {
  /** Base64 PNG (image captcha). Some deployments may return a text question. */
  image?: string;
  question?: string;
  challenge_id?: string;
  token?: string;
}

export async function getCaptcha(): Promise<Captcha & { token: string }> {
  let captcha: Captcha;
  try {
    captcha = await api<Captcha>("/public/human-check", { method: "GET", scope: null });
  } catch (e) {
    if (!(e instanceof ApiError) || e.status !== 404) throw e;
    captcha = await api<Captcha>("/public/captcha", { method: "GET", scope: null });
  }
  const token = String(captcha.challenge_id || captcha.token || "");
  if (!token) throw new Error("Сервер не вернул идентификатор проверки");
  return { ...captcha, token };
}

export function is2FA(r: LoginResult): r is Login2FARequired {
  return (r as Login2FARequired).requires_2fa === true && !("account_kind" in r);
}
export function isPartner(r: LoginResult): r is PartnerLoginPayload {
  return (r as PartnerLoginPayload).account_kind === "partner";
}

export const getSiteConfig = () =>
  api<{
    telegram_bot_username: string;
    public_site_url: string;
    public_onion_url?: string | null;
    doliv_onion_url?: string | null;
  }>("/public/site-config", { scope: null });

export const getTelegramLoginUrl = (origin: string, returnPath = "/login") =>
  api<{ url: string }>("/public/telegram-login-url", { scope: null, query: { origin, return_path: returnPath } });

// --- Buyer ---
export function login(username: string, password: string, captcha_token?: string, captcha_answer?: string) {
  return api<LoginResult>("/auth/login", {
    method: "POST",
    scope: null,
    body: { username, password, captcha_token, captcha_answer },
  });
}
export function login2FA(pre_auth_token: string, code: string) {
  return api<LoginSuccess>("/auth/login/2fa", { method: "POST", scope: null, body: { pre_auth_token, code } });
}
export function register(
  username: string,
  password: string,
  display_name: string | undefined,
  captcha_token: string,
  captcha_answer: string,
) {
  return api<LoginSuccess & { recovery_code?: string }>("/auth/register", {
    method: "POST",
    scope: null,
    body: { username, password, display_name, captcha_token, captcha_answer },
  });
}
export function forgotRecover(username: string, recovery_code: string, new_password: string) {
  return api<{ ok: boolean; recovery_code: string }>("/auth/forgot/recover", {
    method: "POST",
    scope: null,
    body: { username, recovery_code, new_password },
  });
}
export function telegramAuth(payload: Record<string, unknown>) {
  return api<LoginSuccess>("/auth/telegram", { method: "POST", scope: null, body: payload });
}
export function telegramLink(payload: Record<string, unknown>) {
  return api<{ user: User }>("/auth/telegram/link", { method: "POST", body: payload });
}

export function telegramBotStart(returnPath: string) {
  return api<{ deep_link: string; wait_token: string; expires_at?: string; return_path?: string }>(
    "/auth/telegram/bot-start",
    { method: "POST", scope: null, body: { return_path: returnPath } },
  );
}

export type TelegramBotWait =
  | { status: "pending" | "expired" | "consumed" }
  | (LoginSuccess & { status: "ready"; return_path?: string });

export function telegramBotWait(token: string) {
  return api<TelegramBotWait>("/auth/telegram/bot-wait", {
    method: "GET",
    scope: null,
    query: { token },
  });
}

export function telegramBotComplete(ticket: string) {
  return api<LoginSuccess & { status?: string; return_path?: string }>("/auth/telegram/bot-complete", {
    method: "POST",
    scope: null,
    body: { ticket },
  });
}
export const fetchMe = () => api<{ user: User }>("/auth/me", { method: "GET" });
export const logoutRequest = () => api<{ ok: boolean }>("/auth/logout", { method: "POST", scope: null });

export function changePassword(current_password: string, new_password: string) {
  return api<{ ok: boolean }>("/auth/change-password", { method: "POST", body: { current_password, new_password } });
}
export const totpSetup = () =>
  api<{ secret: string; uri: string; enabled: boolean }>("/auth/totp/setup", { method: "POST" });
export const totpConfirm = (code: string) =>
  api<{ ok: boolean; enabled: boolean }>("/auth/totp/confirm", { method: "POST", body: { code } });
export const totpDisable = (current_password: string, code: string) =>
  api<{ ok: boolean; enabled: boolean }>("/auth/totp/disable", { method: "POST", body: { current_password, code } });

/** Persist a freshly issued bearer token for a scope. */
export function persistToken(scope: TokenScope, token: string) {
  setToken(scope, token);
}
export function dropToken(scope: TokenScope) {
  clearToken(scope);
}
