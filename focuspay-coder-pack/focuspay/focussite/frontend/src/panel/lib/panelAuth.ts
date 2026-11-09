// Admin / operator authentication. Contract from auth_router.py:
//   POST /api/auth/{admin|operator}/login       -> {access_token, user|operator} | {requires_2fa, pre_auth_token}
//   POST /api/auth/{admin|operator}/login/2fa    -> {access_token, ...}
//   GET  /api/auth/{admin|operator}/me
//   POST /api/auth/{admin|operator}/logout
//   POST /api/auth/{admin|operator}/change-password, /totp/{setup,confirm,disable}
import { panelApi, setPanelToken, clearPanelToken, type PanelScope } from "@/panel/lib/panelApi";

export type { PanelScope };

export interface PanelAccount {
  id?: number;
  username?: string;
  display_name?: string;
  is_admin?: boolean;
  totp_enabled?: boolean;
  can_view_finance?: boolean;
  permissions?: string[];
  rbac_role?: "ADMIN" | "OPERATOR" | string;
  [key: string]: unknown;
}

export interface PanelLoginSuccess {
  access_token: string;
  token_type?: string;
  user?: PanelAccount;
  operator?: PanelAccount;
}
export interface PanelLogin2FA {
  requires_2fa: true;
  pre_auth_token: string;
  user?: PanelAccount;
  operator?: PanelAccount;
}
export type PanelLoginResult = PanelLoginSuccess | PanelLogin2FA;

export function needs2FA(r: PanelLoginResult): r is PanelLogin2FA {
  return (r as PanelLogin2FA).requires_2fa === true;
}

function accountOf(scope: PanelScope, r: PanelLoginSuccess | { user?: PanelAccount; operator?: PanelAccount }): PanelAccount {
  return (scope === "admin" ? r.user : r.operator) ?? {};
}

export async function panelLogin(scope: PanelScope, username: string, password: string): Promise<PanelLoginResult> {
  return panelApi<PanelLoginResult>(`/auth/${scope}/login`, { method: "POST", scope, body: { username, password } });
}
export async function panelLogin2FA(scope: PanelScope, pre_auth_token: string, code: string): Promise<PanelLoginSuccess> {
  return panelApi<PanelLoginSuccess>(`/auth/${scope}/login/2fa`, { method: "POST", scope, body: { pre_auth_token, code } });
}
export async function panelMe(scope: PanelScope): Promise<PanelAccount> {
  const r = await panelApi<{ user?: PanelAccount; operator?: PanelAccount }>(`/auth/${scope}/me`, { scope });
  return accountOf(scope, r);
}
export async function panelLogout(scope: PanelScope) {
  try {
    await panelApi(`/auth/${scope}/logout`, { method: "POST", scope });
  } catch {
    /* ignore */
  }
  clearPanelToken(scope);
}

export function adoptPanelToken(scope: PanelScope, r: PanelLoginSuccess): PanelAccount {
  if (r.access_token) setPanelToken(scope, r.access_token);
  return accountOf(scope, r);
}

export const panelChangePassword = (scope: PanelScope, current_password: string, new_password: string) =>
  panelApi<{ ok: boolean }>(`/auth/${scope}/change-password`, { method: "POST", scope, body: { current_password, new_password } });
export const panelTotpSetup = (scope: PanelScope) =>
  panelApi<{ secret: string; uri: string; enabled: boolean }>(`/auth/${scope}/totp/setup`, { method: "POST", scope });
export const panelTotpConfirm = (scope: PanelScope, code: string) =>
  panelApi<{ ok: boolean; enabled: boolean }>(`/auth/${scope}/totp/confirm`, { method: "POST", scope, body: { code } });
export const panelTotpDisable = (scope: PanelScope, current_password: string, code: string) =>
  panelApi<{ ok: boolean; enabled: boolean }>(`/auth/${scope}/totp/disable`, { method: "POST", scope, body: { current_password, code } });
