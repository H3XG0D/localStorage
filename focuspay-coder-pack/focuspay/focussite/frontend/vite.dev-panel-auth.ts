// @ts-nocheck — Vite Node plugin; @types/node is not a frontend dependency.
import { createHmac } from "node:crypto";
import fs from "node:fs";
import path from "node:path";
import type { IncomingMessage } from "node:http";
import { loadEnv, type Plugin, type ProxyOptions } from "vite";

type Scope = "admin" | "operator";

const CACHE_FILE = ".dev-panel-auth.json";

export const devPanelTokens: Partial<Record<Scope, string>> = {};

function isLoopback(req: IncomingMessage): boolean {
  const ip = req.socket.remoteAddress || "";
  return ip === "127.0.0.1" || ip === "::1" || ip === "::ffff:127.0.0.1";
}

function cachePath(): string {
  return path.join(process.cwd(), CACHE_FILE);
}

function readCache(): Partial<Record<Scope, string>> {
  try {
    const raw = JSON.parse(fs.readFileSync(cachePath(), "utf8")) as Record<string, unknown>;
    const out: Partial<Record<Scope, string>> = {};
    for (const scope of ["admin", "operator"] as const) {
      const t = raw[scope];
      if (typeof t === "string" && t.split(".").length === 3) out[scope] = t;
    }
    return out;
  } catch {
    return {};
  }
}

function writeCache(tokens: Partial<Record<Scope, string>>) {
  const body = {
    admin: tokens.admin || null,
    operator: tokens.operator || null,
    updated_at: new Date().toISOString(),
  };
  fs.writeFileSync(cachePath(), JSON.stringify(body) + "\n", { mode: 0o600 });
}

function base32Decode(input: string): Buffer {
  const alphabet = "ABCDEFGHIJKLMNOPQRSTUVWXYZ234567";
  const s = input.toUpperCase().replace(/[\s=-]/g, "");
  let bits = "";
  for (const c of s) {
    const v = alphabet.indexOf(c);
    if (v < 0) continue;
    bits += v.toString(2).padStart(5, "0");
  }
  const bytes: number[] = [];
  for (let i = 0; i + 8 <= bits.length; i += 8) bytes.push(parseInt(bits.slice(i, i + 8), 2));
  return Buffer.from(bytes);
}

function totpCode(secret: string, period = 30, digits = 6): string {
  const key = base32Decode(secret);
  const counter = Math.floor(Date.now() / 1000 / period);
  const buf = Buffer.alloc(8);
  buf.writeUInt32BE(Math.floor(counter / 0x100000000), 0);
  buf.writeUInt32BE(counter >>> 0, 4);
  const hmac = createHmac("sha1", key).update(buf).digest();
  const offset = hmac[hmac.length - 1] & 0xf;
  const bin =
    ((hmac[offset] & 0x7f) << 24) |
    ((hmac[offset + 1] & 0xff) << 16) |
    ((hmac[offset + 2] & 0xff) << 8) |
    (hmac[offset + 3] & 0xff);
  return String(bin % 10 ** digits).padStart(digits, "0");
}

async function apiJson(apiTarget: string, apiPath: string, init?: RequestInit): Promise<{ status: number; data: Record<string, unknown> }> {
  const res = await fetch(`${apiTarget.replace(/\/$/, "")}${apiPath}`, {
    ...init,
    signal: init?.signal ?? AbortSignal.timeout(15000),
    headers: { "Content-Type": "application/json", ...(init?.headers || {}) },
  });
  const text = await res.text();
  let data: Record<string, unknown> = {};
  if (text) {
    try {
      data = JSON.parse(text) as Record<string, unknown>;
    } catch {
      data = { detail: text };
    }
  }
  return { status: res.status, data };
}

async function probeMe(apiTarget: string, scope: Scope, token: string): Promise<"ok" | "unauth" | "down"> {
  try {
    const { status } = await apiJson(apiTarget, `/api/auth/${scope}/me`, {
      headers: { Authorization: `Bearer ${token}` },
    });
    if (status === 200) return "ok";
    if (status === 401) return "unauth";
    return "down";
  } catch {
    return "down";
  }
}

async function loginScope(apiTarget: string, scope: Scope, env: Record<string, string>): Promise<string | null> {
  const prefix = scope === "admin" ? "FOCUSPAY_DEV_ADMIN" : "FOCUSPAY_DEV_OPERATOR";
  const preset = (env[`${prefix}_TOKEN`] || "").trim();
  if (preset && (await probeMe(apiTarget, scope, preset)) === "ok") return preset;

  const username = (env[`${prefix}_USER`] || "").trim();
  const password = env[`${prefix}_PASSWORD`] || "";
  if (!username || !password) return null;

  try {
    const first = await apiJson(apiTarget, `/api/auth/${scope}/login`, {
      method: "POST",
      body: JSON.stringify({ username, password }),
    });
    if (first.status === 200 && typeof first.data.access_token === "string") return first.data.access_token;
    if (first.status === 200 && first.data.requires_2fa === true) {
      const totpRaw = (env[`${prefix}_TOTP`] || "").trim();
      if (!totpRaw) {
        console.warn(`[dev-panel-auth] ${scope}: нужен 2FA — задай ${prefix}_TOTP (секрет или код) в .env.local`);
        return null;
      }
      const code = /^\d{6,8}$/.test(totpRaw) ? totpRaw : totpCode(totpRaw);
      const pre = String(first.data.pre_auth_token || "");
      const second = await apiJson(apiTarget, `/api/auth/${scope}/login/2fa`, {
        method: "POST",
        body: JSON.stringify({ pre_auth_token: pre, code }),
      });
      if (second.status === 200 && typeof second.data.access_token === "string") return second.data.access_token;
      console.warn(`[dev-panel-auth] ${scope}: 2FA не принят (${second.status})`);
      return null;
    }
    console.warn(`[dev-panel-auth] ${scope}: логин не удался (${first.status})`);
    return null;
  } catch (err) {
    console.warn(`[dev-panel-auth] ${scope}: логин оборвался`, err instanceof Error ? err.message : err);
    return null;
  }
}

export async function ensureDevPanelTokens(apiTarget: string, mode: string): Promise<void> {
  const env = loadEnv(mode, process.cwd(), "");
  const cached = readCache();
  let cacheDirty = false;
  for (const scope of ["admin", "operator"] as const) {
    const fromCache = cached[scope];
    if (fromCache) {
      const probe = await probeMe(apiTarget, scope, fromCache);
      if (probe === "ok") {
        devPanelTokens[scope] = fromCache;
        console.log(`[dev-panel-auth] ${scope}: кэш живой`);
        continue;
      }
      if (probe === "down") {
        devPanelTokens[scope] = fromCache;
        console.warn(`[dev-panel-auth] ${scope}: API не ответил, оставляю кэш`);
      }
    }
    const fresh = await loginScope(apiTarget, scope, env);
    if (fresh) {
      devPanelTokens[scope] = fresh;
      cacheDirty = true;
      console.log(`[dev-panel-auth] ${scope}: сессия готова`);
    } else if (fromCache && !devPanelTokens[scope]) {
      const userVar = scope === "admin" ? "FOCUSPAY_DEV_ADMIN_USER/PASSWORD" : "FOCUSPAY_DEV_OPERATOR_USER/PASSWORD";
      console.warn(`[dev-panel-auth] ${scope}: кэш протух, задай ${userVar} в .env.local`);
    }
  }
  if (cacheDirty) writeCache(devPanelTokens);
}

function scopeFromApiUrl(url: string): Scope | null {
  const path = url.split("?")[0];
  if (path.includes("/auth/operator") || path.startsWith("/api/operator") || path.startsWith("/operator")) return "operator";
  if (path.includes("/auth/admin") || path.startsWith("/api/admin") || path.startsWith("/admin")) return "admin";
  return null;
}

function isLoginPath(url: string): boolean {
  return /\/auth\/(admin|operator)\/login(\/2fa)?$/.test(url.split("?")[0]);
}

export function devPanelProxyConfigure(): NonNullable<ProxyOptions["configure"]> {
  return (proxy) => {
    proxy.on("proxyReq", (proxyReq, req) => {
      if (!isLoopback(req)) return;
      if (proxyReq.getHeader("authorization")) return;
      const url = req.url || "";
      if (isLoginPath(url)) return;
      const scope = scopeFromApiUrl(url);
      if (!scope) return;
      const token = devPanelTokens[scope];
      if (token) proxyReq.setHeader("Authorization", `Bearer ${token}`);
    });
  };
}

export function devPanelAuthPlugin(apiTarget: string): Plugin {
  let ready = Promise.resolve();
  return {
    name: "dev-panel-auth",
    apply: "serve",
    configureServer(server) {
      ready = ensureDevPanelTokens(apiTarget, server.config.mode).catch((err) => {
        console.warn("[dev-panel-auth] не удалось получить сессию:", err instanceof Error ? err.message : err);
      });
      server.middlewares.use((req, _res, next) => {
        const url = String(req.url || "");
        if (!url.startsWith("/api/") || !isLoopback(req)) {
          next();
          return;
        }
        ready.then(() => next()).catch(() => next());
      });
    },
  };
}
