export interface TelegramThemeParams {
  bg_color?: string;
  text_color?: string;
  hint_color?: string;
  link_color?: string;
  button_color?: string;
  button_text_color?: string;
  secondary_bg_color?: string;
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
  setBottomBarColor?: (color: string) => void;
  onEvent: (event: string, handler: () => void) => void;
  offEvent?: (event: string, handler: () => void) => void;
  openLink?: (url: string) => void;
  BackButton?: {
    show: () => void;
    hide: () => void;
    onClick: (handler: () => void) => void;
    offClick: (handler: () => void) => void;
  };
  MainButton: {
    text: string;
    isVisible: boolean;
    setText: (text: string) => void;
    setParams?: (params: { text?: string; is_visible?: boolean }) => void;
    show: () => void;
    hide: () => void;
    onClick: (handler: () => void) => void;
    offClick?: (handler: () => void) => void;
  };
  HapticFeedback?: {
    impactOccurred: (style: "light" | "medium" | "heavy" | "rigid" | "soft") => void;
    notificationOccurred: (type: "error" | "success" | "warning") => void;
    selectionChanged: () => void;
  };
}

declare global {
  interface Window {
    Telegram?: { WebApp?: TelegramWebApp };
  }
}

const MOCK_BUTTON_ID = "casino-tg-main-button";
const HAPTIC_GAP_MS = 80;

let hapticMuted = false;
let lastHapticAt = 0;
let mainClick: (() => void) | null = null;
let viewportHandler: (() => void) | null = null;
let themeHandler: (() => void) | null = null;
let viewportListenersBound = false;
let largestViewportHeight = 0;

export function isCasinoMiniApp(): boolean {
  if (typeof document === "undefined") return false;
  return document.documentElement.getAttribute("data-casino-entry") === "tg";
}

export function getTelegramWebApp(): TelegramWebApp | undefined {
  return window.Telegram?.WebApp;
}

/** Raw initData string for backend verification (HMAC WebAppData). Empty outside Telegram. */
export function getTelegramInitData(): string {
  try {
    return getTelegramWebApp()?.initData || "";
  } catch {
    return "";
  }
}

/** Telegram user id from initDataUnsafe (unverified, UI-only). Backend re-verifies via hash. */
export function getTelegramUserId(): number | null {
  try {
    const raw = getTelegramWebApp()?.initDataUnsafe?.user as { id?: unknown } | undefined;
    const id = raw?.id;
    return typeof id === "number" && Number.isInteger(id) && id > 0 ? id : null;
  } catch {
    return null;
  }
}

export function isInsideTelegram(): boolean {
  const tg = getTelegramWebApp();
  if (!tg || typeof tg.ready !== "function") return false;
  if (tg.initData) return true;
  if (tg.initDataUnsafe?.user) return true;
  const platform = String(tg.platform || "").toLowerCase();
  return platform !== "" && platform !== "unknown";
}

export function setHapticMuted(muted: boolean) {
  hapticMuted = muted;
}

export function haptic(kind: "selection" | "bet" | "win" | "lose") {
  if (hapticMuted) return;
  const now = Date.now();
  if (now - lastHapticAt < HAPTIC_GAP_MS) return;
  lastHapticAt = now;
  const feedback = getTelegramWebApp()?.HapticFeedback;
  if (!feedback || !isInsideTelegram()) return;
  if (kind === "selection") feedback.selectionChanged();
  else if (kind === "bet") feedback.impactOccurred("light");
  else if (kind === "win") feedback.notificationOccurred("success");
  else feedback.notificationOccurred("error");
}

function parseHex(color: string | undefined): number[] | null {
  if (!color) return null;
  const raw = color.trim();
  const hex = raw.startsWith("#") ? raw.slice(1) : "";
  if (hex.length === 3) {
    return [0, 1, 2].map((i) => Number.parseInt(hex[i] + hex[i], 16));
  }
  if (hex.length === 6) {
    return [0, 2, 4].map((i) => Number.parseInt(hex.slice(i, i + 2), 16));
  }
  const rgb = raw.match(/rgba?\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)/i);
  if (!rgb) return null;
  return [Number(rgb[1]), Number(rgb[2]), Number(rgb[3])];
}

function isLightColor(color: string | undefined): boolean {
  const rgb = parseHex(color);
  if (!rgb) return false;
  const [r, g, b] = rgb;
  return (r * 299 + g * 587 + b * 114) / 1000 > 160;
}

function themeFromQuery(): TelegramThemeParams {
  const params = new URLSearchParams(window.location.search);
  if (params.get("tgTheme") === "light") {
    return {
      bg_color: "#ffffff",
      text_color: "#111111",
      hint_color: "#6b6b6b",
      button_color: "#f4f4f4",
      button_text_color: "#0a0a0b",
      secondary_bg_color: "#f1f1f1",
    };
  }
  return {
    bg_color: "#0c0c0c",
    text_color: "#f0f0f0",
    hint_color: "#9a9a9a",
    button_color: "#f4f4f4",
    button_text_color: "#0a0a0b",
    secondary_bg_color: "#111111",
  };
}

function applyTheme(params: TelegramThemeParams) {
  const root = document.documentElement;
  const bg = params.bg_color || "#0c0c0c";
  const text = params.text_color || "#f0f0f0";
  const hint = params.hint_color || "#9a9a9a";
  const button = "#f4f4f4";
  const secondary = params.secondary_bg_color || "#111111";
  root.style.setProperty("--tg-theme-bg-color", bg);
  root.style.setProperty("--tg-theme-text-color", text);
  root.style.setProperty("--tg-theme-hint-color", hint);
  root.style.setProperty("--tg-theme-button-color", button);
  root.style.setProperty("--tg-theme-button-text-color", "#0a0a0b");
  root.style.setProperty("--tg-theme-secondary-bg-color", secondary);
  const light = isLightColor(bg);
  root.style.colorScheme = light ? "light" : "dark";
  root.classList.toggle("dark", !light);
  root.classList.toggle("casino-tg-light", light);
  const header = document.querySelector('meta[name="theme-color"]');
  if (header) header.setAttribute("content", bg);
}

function applySafeArea(tg?: TelegramWebApp) {
  const content = tg?.contentSafeAreaInset || {};
  const safe = tg?.safeAreaInset || {};
  const root = document.documentElement;
  for (const edge of ["top", "bottom", "left", "right"] as const) {
    const inset = Math.max(Number(content[edge]) || 0, Number(safe[edge]) || 0);
    root.style.setProperty(`--casino-safe-${edge}`, `${inset}px`);
    root.style.setProperty(`--app-safe-${edge}`, `${inset}px`);
  }
}

function applyViewport(tg?: TelegramWebApp) {
  const viewport = window.visualViewport;
  const visible = Number(viewport?.height) || window.innerHeight || 0;
  largestViewportHeight = Math.max(largestViewportHeight, visible);
  const stable = Number(tg?.viewportStableHeight) || 0;
  const fallback = Number(tg?.viewportHeight) || window.innerHeight || 0;
  const mockButton = document.getElementById(MOCK_BUTTON_ID);
  const mockH = mockButton && !mockButton.hasAttribute("hidden") ? mockButton.getBoundingClientRect().height : 0;
  const height = Math.max(1, (stable || fallback) - mockH);
  const root = document.documentElement;
  const editing = /^(INPUT|TEXTAREA)$/.test(document.activeElement?.tagName || "");
  const keyboard = editing && largestViewportHeight - visible > 120;
  root.dataset.keyboard = String(keyboard);
  root.style.setProperty("--casino-app-h", `${height}px`);
  root.style.setProperty("--app-visible-height", `${visible}px`);
  root.style.setProperty("--app-viewport-top", `${Number(viewport?.offsetTop) || 0}px`);
  root.style.setProperty("--app-stable-height", `${stable || window.innerHeight || height}px`);
  root.style.setProperty("--app-head-height", "72px");
  root.style.setProperty("--app-bottom-height", "72px");
}

function bindViewportListeners(tg?: TelegramWebApp) {
  if (viewportListenersBound) return;
  viewportListenersBound = true;
  const sync = () => applyViewport(tg);
  const reset = () => {
    largestViewportHeight = Number(window.visualViewport?.height) || window.innerHeight || 0;
    sync();
  };
  window.visualViewport?.addEventListener("resize", sync);
  window.visualViewport?.addEventListener("scroll", sync);
  window.addEventListener("resize", sync);
  window.addEventListener("orientationchange", reset);
  document.addEventListener("focusin", sync);
  document.addEventListener("focusout", sync);
}

function isLowEndAndroid(tg?: TelegramWebApp): boolean {
  if (String(tg?.platform || "").toLowerCase() !== "android") return false;
  const cores = Number(navigator.hardwareConcurrency) || 8;
  const memory = Number((navigator as Navigator & { deviceMemory?: number }).deviceMemory) || 8;
  return cores <= 4 || memory <= 2;
}

export function showMainButton(text: string, onClick: () => void) {
  const tg = getTelegramWebApp();
  if (tg?.MainButton && isInsideTelegram()) {
    if (mainClick) tg.MainButton.offClick?.(mainClick);
    mainClick = onClick;
    tg.MainButton.setText(text);
    tg.MainButton.setParams?.({ text, is_visible: true });
    tg.MainButton.onClick(onClick);
    tg.MainButton.show();
    applyViewport(tg);
    return;
  }
  let el = document.getElementById(MOCK_BUTTON_ID) as HTMLButtonElement | null;
  if (!el) {
    el = document.createElement("button");
    el.id = MOCK_BUTTON_ID;
    el.type = "button";
    el.className = "casino-tg-main-button";
    el.setAttribute("data-tg-main-button", "1");
    document.body.appendChild(el);
  }
  el.hidden = false;
  el.textContent = text;
  el.onclick = onClick;
  applyViewport(tg);
}

export function hideMainButton() {
  const tg = getTelegramWebApp();
  if (tg?.MainButton && isInsideTelegram()) {
    if (mainClick) tg.MainButton.offClick?.(mainClick);
    mainClick = null;
    tg.MainButton.hide();
    applyViewport(tg);
    return;
  }
  const el = document.getElementById(MOCK_BUTTON_ID);
  if (el) {
    el.setAttribute("hidden", "");
    (el as HTMLButtonElement).onclick = null;
  }
  applyViewport(tg);
}

export function bootTelegram() {
  if (!isCasinoMiniApp()) return;
  const tg = getTelegramWebApp();
  const root = document.documentElement;
  root.dataset.telegram = String(isInsideTelegram());
  root.dataset.telegramBack = String(Boolean(isInsideTelegram() && tg?.BackButton));
  bindViewportListeners(tg);
  if (tg && isInsideTelegram()) {
    tg.ready();
    tg.expand();
    tg.disableVerticalSwipes?.();
    applyTheme(tg.themeParams || themeFromQuery());
    applySafeArea(tg);
    applyViewport(tg);
    const bg = tg.themeParams?.bg_color;
    if (bg) {
      tg.setHeaderColor?.(bg);
      tg.setBackgroundColor?.(bg);
      tg.setBottomBarColor?.(bg);
    }
    if (viewportHandler) tg.offEvent?.("viewportChanged", viewportHandler);
    viewportHandler = () => {
      applySafeArea(tg);
      applyViewport(tg);
      // Telegram re-enables vertical swipes after expand/fullscreen changes.
      tg.disableVerticalSwipes?.();
    };
    tg.onEvent("viewportChanged", viewportHandler);
    if (themeHandler) tg.offEvent?.("themeChanged", themeHandler);
    themeHandler = () => {
      applyTheme(tg.themeParams || {});
      const background = tg.themeParams?.bg_color;
      if (background) {
        tg.setHeaderColor?.(background);
        tg.setBackgroundColor?.(background);
        tg.setBottomBarColor?.(background);
      }
    };
    tg.onEvent("themeChanged", themeHandler);
  } else {
    applyTheme(themeFromQuery());
    applySafeArea();
    applyViewport();
    window.addEventListener("resize", () => applyViewport());
  }
  document.documentElement.classList.toggle("casino-reduce-motion", isLowEndAndroid(tg));
}
