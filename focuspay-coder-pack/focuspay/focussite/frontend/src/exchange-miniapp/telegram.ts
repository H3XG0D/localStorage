export interface TelegramThemeParams {
  bg_color?: string;
  text_color?: string;
}

export interface TelegramWebApp {
  initData?: string;
  initDataUnsafe?: { user?: unknown };
  platform?: string;
  colorScheme?: "light" | "dark";
  themeParams?: TelegramThemeParams;
  viewportHeight?: number;
  viewportStableHeight?: number;
  contentSafeAreaInset?: { top?: number; bottom?: number; left?: number; right?: number };
  safeAreaInset?: { top?: number; bottom?: number; left?: number; right?: number };
  ready: () => void;
  expand: () => void;
  disableVerticalSwipes?: () => void;
  setHeaderColor?: (color: string) => void;
  setBackgroundColor?: (color: string) => void;
  openLink?: (url: string) => void;
  openTelegramLink?: (url: string) => void;
  onEvent: (event: string, handler: () => void) => void;
  offEvent?: (event: string, handler: () => void) => void;
}

type TelegramWindow = Window & { Telegram?: { WebApp?: TelegramWebApp } };

export function isExchangeMiniApp(): boolean {
  if (typeof document === "undefined") return false;
  return document.documentElement.getAttribute("data-exchange-entry") === "tg";
}

export function getTelegramWebApp(): TelegramWebApp | undefined {
  return (window as TelegramWindow).Telegram?.WebApp;
}

export function getTelegramInitData(): string {
  try {
    return getTelegramWebApp()?.initData || "";
  } catch {
    return "";
  }
}

export function getTelegramUserId(): number | null {
  try {
    const raw = getTelegramWebApp()?.initDataUnsafe?.user as { id?: unknown } | undefined;
    const id = raw?.id;
    return typeof id === "number" && Number.isInteger(id) && id > 0 ? id : null;
  } catch {
    return null;
  }
}

function isInsideTelegram(): boolean {
  const tg = getTelegramWebApp();
  if (!tg || typeof tg.ready !== "function") return false;
  if (tg.initData) return true;
  const platform = String(tg.platform || "").toLowerCase();
  return platform !== "" && platform !== "unknown";
}

function isLightColor(color: string | undefined): boolean {
  if (!color) return false;
  const hex = color.trim().replace("#", "");
  const full = hex.length === 3 ? hex.split("").map((c) => c + c).join("") : hex;
  if (full.length !== 6) return false;
  const r = Number.parseInt(full.slice(0, 2), 16);
  const g = Number.parseInt(full.slice(2, 4), 16);
  const b = Number.parseInt(full.slice(4, 6), 16);
  return (r * 299 + g * 587 + b * 114) / 1000 > 160;
}

function applyTheme(tg?: TelegramWebApp) {
  const root = document.documentElement;
  const params = new URLSearchParams(window.location.search);
  const queryLight = params.get("tgTheme") === "light";
  const queryDark = params.get("tgTheme") === "dark";
  const inside = Boolean(tg?.initData || (tg && String(tg.platform || "").toLowerCase() !== "" && String(tg.platform).toLowerCase() !== "unknown"));
  const telegramLight = tg?.colorScheme === "light" || isLightColor(tg?.themeParams?.bg_color);
  const light = queryLight || (!queryDark && (!inside || telegramLight));
  root.classList.toggle("dark", !light);
  root.style.colorScheme = light ? "light" : "dark";
  const bg = light ? "#fafafa" : "#0a0a0b";
  const header = document.querySelector('meta[name="theme-color"]');
  if (header) header.setAttribute("content", bg);
  if (tg && isInsideTelegram()) {
    tg.setHeaderColor?.(bg);
    tg.setBackgroundColor?.(bg);
  }
}

function isTyping(): boolean {
  const el = document.activeElement;
  return el instanceof HTMLInputElement || el instanceof HTMLTextAreaElement;
}

function knownHeights(tg?: TelegramWebApp): number[] {
  return [Number(tg?.viewportHeight) || 0, Number(window.visualViewport?.height) || 0, window.innerHeight || 0].filter((value) => value > 0);
}

function applyChrome(tg?: TelegramWebApp) {
  const inset = tg?.contentSafeAreaInset || tg?.safeAreaInset || {};
  const root = document.documentElement;
  const stable = Number(tg?.viewportStableHeight) || 0;
  const telegramLive = Number(tg?.viewportHeight) || 0;
  const shrunk = stable > 0 && telegramLive > 0 && stable - telegramLive > 80;
  const keyboard = shrunk || isTyping();
  const openHeights = knownHeights(tg);
  const height = keyboard
    ? Math.min(...(openHeights.length ? openHeights : [window.innerHeight || 1]))
    : (stable || telegramLive || window.innerHeight || 1);
  root.classList.toggle("ex-keyboard", keyboard);
  root.style.setProperty("--ex-safe-top", `${Number(inset.top) || 0}px`);
  root.style.setProperty("--ex-safe-bottom", keyboard ? "0px" : `${Number(inset.bottom) || 0}px`);
  root.style.setProperty("--ex-app-h", `${Math.max(1, height)}px`);
}

function scrollFocusedField() {
  const el = document.activeElement;
  if (!(el instanceof HTMLElement) || !isTyping()) return;
  window.setTimeout(() => {
    el.scrollIntoView({ block: "center", inline: "nearest" });
  }, 40);
}

export function openExternal(url: string) {
  const tg = getTelegramWebApp();
  if (url.startsWith("https://t.me/") && tg?.openTelegramLink && isInsideTelegram()) {
    tg.openTelegramLink(url);
    return;
  }
  if (tg?.openLink && isInsideTelegram()) {
    tg.openLink(url);
    return;
  }
  window.open(url, "_blank", "noopener,noreferrer");
}

export function bootTelegram() {
  if (!isExchangeMiniApp()) return;
  const tg = getTelegramWebApp();
  if (tg && isInsideTelegram()) {
    tg.ready();
    tg.expand();
    tg.disableVerticalSwipes?.();
    applyTheme(tg);
    applyChrome(tg);
    const onChange = () => {
      applyTheme(tg);
      applyChrome(tg);
    };
    tg.onEvent("themeChanged", onChange);
    tg.onEvent("viewportChanged", onChange);
    window.visualViewport?.addEventListener("resize", onChange);
    watchTyping(tg);
  } else {
    applyTheme();
    applyChrome();
    window.addEventListener("resize", () => applyChrome());
    window.visualViewport?.addEventListener("resize", () => applyChrome());
    watchTyping();
  }
}

function watchTyping(tg?: TelegramWebApp) {
  let timer = 0;
  document.addEventListener("focusin", (event) => {
    if (!(event.target instanceof HTMLInputElement || event.target instanceof HTMLTextAreaElement)) return;
    window.clearTimeout(timer);
    applyChrome(tg);
    scrollFocusedField();
  });
  document.addEventListener("focusout", () => {
    window.clearTimeout(timer);
    timer = window.setTimeout(() => applyChrome(tg), 80);
  });
}
