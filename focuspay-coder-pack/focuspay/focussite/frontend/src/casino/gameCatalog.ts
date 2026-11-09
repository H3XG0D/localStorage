export type CasinoCategory = "duels" | "cards" | "house";

export interface CasinoCatalogGame {
  id: string;
  name: string;
  category: CasinoCategory;
  emoji: string;
  aliases: string[];
  href: string;
  howTo: string;
  /** Hidden from lobby/nav/search. Routes and files stay as parked stubs. */
  hidden?: boolean;
}

export const CASINO_CATALOG: CasinoCatalogGame[] = [
  {
    id: "pvp_dice",
    name: "Кубики",
    category: "duels",
    emoji: "🎲",
    aliases: ["кубик", "кость", "кости", "dice", "cub", "дом", "house"],
    href: "/casino/play/pvp_dice?mode=players",
    howTo: "2–6 игроков. Кто больше на кубах. Бота можно добавить.",
  },
  {
    id: "baccara",
    name: "Баккара",
    category: "cards",
    emoji: "🃏",
    aliases: ["баккара", "baccara", "карты"],
    href: "/casino/play/baccara?mode=players",
    howTo: "2–6 игроков. Ближе к 9. Бота можно добавить.",
  },
  {
    id: "blackjack",
    name: "Блэкджек",
    category: "cards",
    emoji: "🂡",
    aliases: ["блекджек", "blackjack", "21", "карты"],
    href: "/casino/play/blackjack?mode=players",
    howTo: "2–6 игроков. Ближе к 21. Бота можно добавить.",
  },
  {
    id: "russian_draughts",
    name: "Русские шашки",
    category: "duels",
    emoji: "⚫",
    aliases: ["шашки", "русские шашки", "шашка", "draughts", "checkers"],
    href: "/casino/play/russian_draughts",
    howTo: "Двое, одна ставка. Дамка летает. Бой обязателен, какой — выбираете вы. Ничья возвращает обе ставки.",
    hidden: true,
  },
  {
    id: "nardy",
    name: "Нарды",
    category: "duels",
    emoji: "🎲",
    aliases: ["нарды", "длинные", "нард", "nardy", "backgammon"],
    href: "/casino/play/nardy",
    howTo: "Двое. Длинные нарды. Ставка, марс удваивает.",
    hidden: true,
  },
  {
    id: "holdem",
    name: "Техасский холдем",
    category: "cards",
    emoji: "🂠",
    aliases: ["покер", "холдем", "holdem", "texas", "poker"],
    href: "/casino/play/holdem",
    howTo: "Две свои, пять общих. Лучшая комбинация.",
    hidden: true,
  },
  {
    id: "roulette",
    name: "Рулетка",
    category: "house",
    emoji: "🎡",
    aliases: ["рулетка", "европейская", "roulette", "колесо", "красное", "чёрное", "черное", "зеро", "zero", "red", "black", "36+0", "1rd"],
    href: "/casino/play/roulette?mode=players",
    howTo: "Общий стол 0–36. Своя фишка. Из Telegram тоже.",
  },
  {
    id: "jackpot",
    name: "Джекпот",
    category: "duels",
    emoji: "🎡",
    aliases: ["джекпот", "jackpot", "csgo", "колесо", "аватарки"],
    href: "/casino/play/jackpot",
    howTo: "Общий банк. Больше ставка — больше шанс.",
  },
  {
    id: "fixed_room",
    name: "Комнаты",
    category: "duels",
    emoji: "🎯",
    aliases: ["комната", "комнаты", "фикс", "fixed", "n мест", "равная ставка", "дуэль", "дуэли"],
    href: "/casino/play/fixed_room?mode=players",
    howTo: "Одна ставка, 2–6 мест. Колесо выбирает одного. Банк минус комиссия. Пустое место — бот.",
  },
  {
    id: "raffle",
    name: "FocusLucky",
    category: "house",
    emoji: "🎰",
    aliases: ["фокус лаки", "focuslucky", "raffle", "розыгрыш", "билеты"],
    href: "/casino/play/raffle",
    howTo: "Билеты за обмены. Живой розыгрыш.",
  },
  {
    id: "clan_war",
    name: "Клан vs клан",
    category: "duels",
    emoji: "⚔️",
    aliases: ["клан", "война", "war", "команда"],
    href: "/casino/play/clan_war",
    howTo: "Два клана. Ставки с кошельков игроков.",
    hidden: true,
  },
];

/** Parked player pages. Do not delete — unhide later. */
export const CASINO_SHELVED_STUBS = [
  { id: "clan_war", title: "Клан vs клан", href: "/casino/play/clan_war", files: "CasinoClanWars.tsx, casino_clan_wars.py" },
  { id: "clans", title: "Команды / кланы", href: "/casino/clans", files: "CasinoClans.tsx, casino_clans.py" },
  { id: "holdem", title: "Техасский холдем", href: "/casino/play/holdem", files: "CasinoPoker.tsx, CasinoPokerTable.tsx" },
  { id: "nardy", title: "Нарды", href: "/casino/play/nardy", files: "CasinoNardy.tsx, CasinoNardyTable.tsx" },
  { id: "russian_draughts", title: "Русские шашки", href: "/casino/play/russian_draughts", files: "CasinoDraughts.tsx, CasinoDraughtsTable.tsx" },
] as const;

export const CASINO_CLANS_PAGE_HIDDEN = true;

export const CATEGORY_LABEL: Record<CasinoCategory, string> = {
  duels: "Дуэли",
  cards: "Карты",
  house: "Общий стол",
};

export const RECENT_KEY = "focuspay_casino_recent";
export const FAVORITE_KEY = "focuspay_casino_favorites";
export const CASINO_BALANCE_EVENT = "focuspay-casino-balance";
/** Freeze the header chip until the wheel (or other animation) parks. */
export const CASINO_BALANCE_HOLD_EVENT = "focuspay-casino-balance-hold";
/** Drop a hold without fetching — play failed or the player left. */
export const CASINO_BALANCE_RELEASE_EVENT = "focuspay-casino-balance-release";
export const CASINO_LOOK_EVENT = "focuspay-casino-look";
/** The active tournament wallet changed — header pill and tables must re-read it. */
export const CASINO_TOURNAMENT_EVENT = "focuspay-casino-tournament";

export const HEAD_TO_HEAD_IDS = ["pvp_dice", "baccara", "blackjack"] as const;

export function canonicalGameId(id: string): string {
  return id === "cub" ? "pvp_dice" : id;
}

export function catalogGame(id: string | undefined): CasinoCatalogGame | undefined {
  if (!id) return undefined;
  return CASINO_CATALOG.find((item) => item.id === canonicalGameId(id));
}

export function isShelvedCasinoGame(id: string): boolean {
  return Boolean(catalogGame(id)?.hidden);
}

export function visibleCasinoCatalog(): CasinoCatalogGame[] {
  return CASINO_CATALOG.filter((game) => !game.hidden);
}

export function readIdList(key: string): string[] {
  try {
    const raw = window.localStorage.getItem(key);
    const parsed = raw ? JSON.parse(raw) : [];
    if (!Array.isArray(parsed)) return [];
    const seen = new Set<string>();
    const out: string[] = [];
    for (const item of parsed.map(String).map(canonicalGameId)) {
      if (seen.has(item)) continue;
      seen.add(item);
      out.push(item);
    }
    return out;
  } catch {
    return [];
  }
}

export function writeIdList(key: string, ids: string[]) {
  window.localStorage.setItem(key, JSON.stringify(ids.map(canonicalGameId)));
}

export function pushRecent(gameId: string) {
  const id = canonicalGameId(gameId);
  const next = [id, ...readIdList(RECENT_KEY).filter((item) => item !== id)].slice(0, 8);
  writeIdList(RECENT_KEY, next);
}
