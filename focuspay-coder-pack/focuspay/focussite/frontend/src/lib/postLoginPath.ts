/** Safe same-origin path to open after login/register. Default is the cabinet. */
export const POST_LOGIN_FALLBACK = "/cabinet";

function pathOnly(value: string): string {
  return value.split("?")[0].split("#")[0];
}

function isBlockedAuthPath(path: string): boolean {
  return path === "/login" || path === "/register" || path === "/forgot"
    || path === "/login/telegram"
    || path.startsWith("/login/") || path.startsWith("/register/") || path.startsWith("/forgot/");
}

export function resolvePostLoginPath(raw: unknown, fallback = POST_LOGIN_FALLBACK): string {
  if (typeof raw !== "string") return fallback;
  const trimmed = raw.trim();
  if (!trimmed.startsWith("/") || trimmed.startsWith("//") || trimmed.includes("\\")) return fallback;
  if (/[\s<>]/.test(trimmed)) return fallback;
  let decodedPath: string;
  try {
    decodedPath = decodeURIComponent(pathOnly(trimmed));
  } catch {
    return fallback;
  }
  if (!decodedPath.startsWith("/") || decodedPath.startsWith("//") || decodedPath.includes("\\") || decodedPath.includes("://")) {
    return fallback;
  }
  if (isBlockedAuthPath(decodedPath)) return fallback;
  return trimmed;
}

export function authPathWithNext(
  authPath: "/login" | "/register" | "/login/telegram",
  from?: string | null,
): string {
  if (authPath === "/login/telegram") {
    const raw = resolvePostLoginPath(from, "/casino");
    const next = raw.startsWith("/casino") ? raw : "/casino";
    return `${authPath}?${new URLSearchParams({ next }).toString()}`;
  }
  const safe = resolvePostLoginPath(from);
  if (safe === POST_LOGIN_FALLBACK) return authPath;
  return `${authPath}?${new URLSearchParams({ next: safe }).toString()}`;
}
