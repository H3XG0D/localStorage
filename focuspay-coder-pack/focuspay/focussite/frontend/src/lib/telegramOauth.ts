const TELEGRAM_QUERY_KEYS = ["id", "first_name", "last_name", "username", "photo_url", "auth_date", "hash"] as const;

const processedHashes = new Set<string>();

function decodeTelegramAuthResult(raw: string): string {
  const b64 = raw.replace(/-/g, "+").replace(/_/g, "/");
  const padded = b64 + "=".repeat((4 - (b64.length % 4)) % 4);
  return atob(padded);
}

function payloadFromRecord(value: unknown): Record<string, unknown> | null {
  if (!value || typeof value !== "object" || Array.isArray(value)) return null;
  const rec = value as Record<string, unknown>;
  if (rec.hash == null || rec.hash === "") return null;
  if (rec.id == null || rec.auth_date == null) return null;
  return rec;
}

export function parseTelegramOauthResult(search: string, hash: string): Record<string, unknown> | null {
  const hashValue = hash.startsWith("#") ? hash.slice(1) : hash;
  const hashParams = new URLSearchParams(hashValue);
  const raw = hashParams.get("tgAuthResult");
  if (raw) {
    try {
      const parsed = payloadFromRecord(JSON.parse(decodeTelegramAuthResult(raw)));
      if (parsed) return parsed;
    } catch {
      /* ignore malformed hash */
    }
  }
  const params = new URLSearchParams(search.startsWith("?") ? search.slice(1) : search);
  const id = params.get("id");
  const tgHash = params.get("hash");
  const authDate = params.get("auth_date");
  if (!id || !tgHash || !authDate) return null;
  const payload: Record<string, unknown> = { id, hash: tgHash, auth_date: authDate };
  for (const key of ["first_name", "last_name", "username", "photo_url"] as const) {
    const item = params.get(key);
    if (item) payload[key] = item;
  }
  return payload;
}

export function stripTelegramOauthParams(search: string): string {
  const params = new URLSearchParams(search.startsWith("?") ? search.slice(1) : search);
  for (const key of TELEGRAM_QUERY_KEYS) params.delete(key);
  const next = params.toString();
  return next ? `?${next}` : "";
}

/** Parse once per Telegram hash so Strict Mode remounts do not double-submit. */
export function consumeTelegramOauthResult(search: string, hash: string): Record<string, unknown> | null {
  const payload = parseTelegramOauthResult(search, hash);
  if (!payload) return null;
  const key = String(payload.hash);
  if (processedHashes.has(key)) return null;
  processedHashes.add(key);
  return payload;
}
