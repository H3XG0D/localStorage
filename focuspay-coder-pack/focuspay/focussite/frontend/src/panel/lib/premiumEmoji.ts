/** Premium Telegram emoji for the broadcast composer. Ids match services/tg_emoji.py. */

export type PremiumEmoji = {
  key: string;
  id: string;
  fallback: string;
  label: string;
};

export const PREMIUM_EMOJI: PremiumEmoji[] = [
  { key: "announce", id: "5424818078833715060", fallback: "📢", label: "Анонс" },
  { key: "internet", id: "5447410659077661506", fallback: "🌐", label: "Интернет" },
  { key: "info", id: "5323442290708985472", fallback: "ℹ️", label: "Важно" },
  { key: "check", id: "5206607081334906820", fallback: "✅", label: "Готово" },
  { key: "link", id: "5271604874419647061", fallback: "🔗", label: "Ссылка" },
  { key: "bell", id: "5458603043203327669", fallback: "🔔", label: "Колокол" },
  { key: "idea", id: "5422439311196834318", fallback: "💡", label: "Идея" },
  { key: "star", id: "5438496463044752972", fallback: "⭐", label: "Звезда" },
  { key: "wave", id: "5870734657384877785", fallback: "👋", label: "Привет" },
  { key: "people", id: "5942877472163892475", fallback: "👥", label: "Люди" },
  { key: "gift", id: "5406756500108501710", fallback: "🆓", label: "Подарок" },
  { key: "fire", id: "5424972470023104089", fallback: "🔥", label: "Огонь" },
  { key: "obmen", id: "5874986954180791957", fallback: "🔄", label: "Обмен" },
  { key: "wallet", id: "5769403330761593044", fallback: "👛", label: "Кошелёк" },
  { key: "ruble", id: "5231449120635370684", fallback: "💰", label: "Рубль" },
  { key: "percent", id: "5229064374403998351", fallback: "➗", label: "Процент" },
  { key: "qr", id: "5987917196469213507", fallback: "📱", label: "QR" },
  { key: "stats", id: "5231200819986047254", fallback: "📊", label: "Статистика" },
  { key: "chart_up", id: "5449683594425410231", fallback: "📈", label: "Рост" },
  { key: "chart_down", id: "5447183459602669338", fallback: "📉", label: "Спад" },
  { key: "discount", id: "5406683434124859552", fallback: "🏷", label: "Скидка" },
  { key: "sport", id: "5935847413859225147", fallback: "🏆", label: "Кубок" },
  { key: "profile", id: "5879770735999717115", fallback: "👤", label: "Профиль" },
  { key: "calendar", id: "5413879192267805083", fallback: "📅", label: "Дата" },
  { key: "history", id: "5877597667231534929", fallback: "📋", label: "История" },
  { key: "down", id: "5875008416132370818", fallback: "🔽", label: "Вниз" },
  { key: "card", id: "5927169041595634481", fallback: "💳", label: "Карта" },
  { key: "sbp", id: "5206636501860893075", fallback: "💳", label: "СБП" },
  { key: "chat", id: "5443038326535759644", fallback: "💬", label: "Чат" },
  { key: "support", id: "5884510167986343350", fallback: "💬", label: "Поддержка" },
  { key: "dollar", id: "5409048419211682843", fallback: "💵", label: "Доллар" },
  { key: "btc", id: "6032744483102133873", fallback: "💵", label: "Bitcoin" },
  { key: "usdt", id: "6032709766881479783", fallback: "💵", label: "USDT" },
  { key: "trx", id: "6030661990899257068", fallback: "💵", label: "TRX" },
  { key: "ltc", id: "5891232414574841140", fallback: "💵", label: "LTC" },
];

const VS16 = /\uFE0F/g;

function strictRe() {
  return /<tg-emoji emoji-id="(\d{5,32})">([^<]{1,8})<\/tg-emoji>/g;
}

const BY_ID = new Map<string, string>();
for (const item of PREMIUM_EMOJI) {
  if (item.id && item.fallback && !BY_ID.has(item.id)) BY_ID.set(item.id, item.fallback);
}

type UniqueHit = { id: string; fallback: string };

function buildUnique(): Map<string, UniqueHit> {
  const owners = new Map<string, Set<string>>();
  const canonical = new Map<string, string>();
  for (const item of PREMIUM_EMOJI) {
    if (!item.id || !item.fallback) continue;
    for (const form of [item.fallback, item.fallback.replace(VS16, "")]) {
      if (!form) continue;
      const ids = owners.get(form) ?? new Set<string>();
      ids.add(item.id);
      owners.set(form, ids);
      if (!canonical.has(form)) canonical.set(form, item.fallback);
    }
  }
  const out = new Map<string, UniqueHit>();
  for (const [form, ids] of owners) {
    if (ids.size !== 1) continue;
    const id = [...ids][0];
    out.set(form, { id, fallback: canonical.get(form) || form });
  }
  return out;
}

const UNIQUE = buildUnique();
const KEYBOARD_ALIASES: Array<[string, string, string]> = [
  ["🚀", "5424818078833715060", "📢"],
  ["⚡", "5424972470023104089", "🔥"],
  ["⚡️", "5424972470023104089", "🔥"],
  ["🎨", "5422439311196834318", "💡"],
  ["🔒", "5206607081334906820", "✅"],
  ["🤝", "5942877472163892475", "👥"],
];
for (const [glyph, id, fallback] of KEYBOARD_ALIASES) {
  UNIQUE.set(glyph, { id, fallback });
}
const UNIQUE_KEYS = [...UNIQUE.keys()].sort((a, b) => b.length - a.length);

function tag(id: string, fallback: string) {
  return `<tg-emoji emoji-id="${id}">${fallback}</tg-emoji>`;
}

function upgradeChunk(chunk: string): string {
  if (!chunk) return "";
  const unwrapped = chunk
    .replace(/<tg-emoji\b[^>]*>[\s\S]*?<\/tg-emoji>/gi, (full) => full.replace(/<[^>]+>/g, ""))
    .replace(/<\/?tg-emoji\b[^>]*>/gi, "");
  if (!UNIQUE_KEYS.length) return unwrapped;
  const pattern = new RegExp(UNIQUE_KEYS.map((item) => item.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")).join("|"), "g");
  return unwrapped.replace(pattern, (glyph) => {
    const hit = UNIQUE.get(glyph);
    return hit ? tag(hit.id, hit.fallback) : glyph;
  });
}

export function upgradePremiumEmoji(text: string): string {
  if (!text) return "";
  const parts: string[] = [];
  let pos = 0;
  for (const match of text.matchAll(strictRe())) {
    const start = match.index ?? 0;
    parts.push(upgradeChunk(text.slice(pos, start)));
    const id = match[1] || "";
    const fallback = BY_ID.get(id);
    parts.push(fallback ? tag(id, fallback) : upgradeChunk(match[2] || ""));
    pos = start + match[0].length;
  }
  parts.push(upgradeChunk(text.slice(pos)));
  return parts.join("");
}

export function fitPremiumText(text: string, maxLen = 4096): string {
  if (maxLen < 1) return "";
  let value = text || "";
  const finder = /<tg-emoji emoji-id="(\d{5,32})">([^<]{1,8})<\/tg-emoji>/g;
  while (value.length > maxLen) {
    let last: RegExpExecArray | null = null;
    finder.lastIndex = 0;
    for (let hit = finder.exec(value); hit; hit = finder.exec(value)) last = hit;
    if (!last) return value.slice(0, maxLen).trimEnd();
    value = value.slice(0, last.index) + (last[2] || "") + value.slice(last.index + last[0].length);
  }
  return value;
}

export function toTelegramText(text: string, maxLen = 4096): string {
  return fitPremiumText(upgradePremiumEmoji(text), maxLen);
}

export function toEditorText(text: string): string {
  return text.replace(strictRe(), (full, id: string) => {
    const fallback = BY_ID.get(id);
    if (!fallback) return full.replace(/<[^>]+>/g, "");
    const hit = UNIQUE.get(fallback);
    if (hit?.id === id) return fallback;
    return tag(id, fallback);
  });
}

export function premiumInsert(item: PremiumEmoji): string {
  const hit = UNIQUE.get(item.fallback);
  if (hit?.id === item.id) return item.fallback;
  return tag(item.id, item.fallback);
}

export function plainEmojiLeft(text: string): string[] {
  const stripped = text.replace(strictRe(), "");
  return [...new Set(stripped.match(/\p{Extended_Pictographic}/gu) || [])];
}

export function broadcastPlainPreview(text: string): string {
  return text
    .replace(strictRe(), (_full, _id, inner: string) => inner)
    .replace(/<[^>]+>/g, "");
}
