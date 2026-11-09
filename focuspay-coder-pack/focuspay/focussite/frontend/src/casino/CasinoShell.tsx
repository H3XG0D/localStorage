import { useCallback, useEffect, useMemo, useState } from "react";
import { Bell, ChevronLeft, ChevronRight, Eye, EyeOff, Home, MessageCircle, PanelLeftClose, PanelLeftOpen, Plus, Settings, ShieldCheck, Trophy, UserRound, Wallet, X } from "lucide-react";
import { Link, NavLink, Outlet, useLocation, useNavigate } from "react-router-dom";
import {
  cancelCasinoDuel,
  cancelCasinoV2Table,
  getCasinoInbox,
  getCasinoPlayer,
  getCasinoRoom,
  getCasinoV2Table,
  getRates,
  leaveCasinoHouseTable,
  leaveCasinoV2Table,
  postCasinoRoomCancel,
  postCasinoRoomLeave,
  readCasinoInbox,
  refillCasinoBonusChips,
  type CasinoChatActor,
  type CasinoInboxItem,
  type CasinoInboxSession,
  type CasinoWalletRow,
} from "@/lib/public";
import { API_BASE, getToken } from "@/lib/api";
import { toast } from "sonner";
import { useSession } from "@/lib/session";
import { getBalance } from "@/lib/user";
import { CasinoCashierProvider, CasinoCashierHost, useCasinoCashier } from "./CasinoCashier";
import { casinoRest, casinoTo, casinoWalletPath, casinoInboxPlayHref, CasinoLoginLink } from "./casinoPaths";
import { CasinoOverlayProvider, useCasinoOverlay } from "./casinoOverlay";
import { CasinoChatPanel } from "./CasinoChatPanel";
import { CasinoPlayerAvatar } from "./CasinoPlayerChip";
import { getTelegramWebApp, isCasinoMiniApp } from "./telegram";
import { useCasinoCurrency } from "./casinoCurrency";
import { spendableBalanceRub } from "./casinoWalletRules";
import { CASINO_BALANCE_EVENT, CASINO_BALANCE_HOLD_EVENT, CASINO_BALANCE_RELEASE_EVENT, CASINO_CLANS_PAGE_HIDDEN, CASINO_LOOK_EVENT, visibleCasinoCatalog } from "./gameCatalog";
import { gameRailIcon } from "./gameRailIcon";
import {
  formatWalletAmount,
  useCasinoWallet,
  walletRowBalance,
  type CasinoWalletState,
} from "./walletScope";
import "./casino.css";
import "./casino-skin.css";

function formatRub(value: number): string {  return `${new Intl.NumberFormat("ru-RU", { maximumFractionDigits: 2 }).format(value)} ₽`;
}

function hrefMatchesPath(href: string, pathname: string, search: string): boolean {
  const [rawPath, query] = href.split("?");
  const mapped = casinoTo(rawPath.startsWith("/") ? rawPath : `/${rawPath}`);
  if (pathname !== mapped && casinoRest(pathname) !== casinoRest(mapped)) return false;
  if (!query) return true;
  const want = new URLSearchParams(query);
  const have = new URLSearchParams(search.startsWith("?") ? search.slice(1) : search);
  for (const [key, value] of want.entries()) {
    if (have.get(key) !== value) return false;
  }
  return true;
}

function mobileScreenTitle(rest: string): string {
  if (rest.startsWith("/play/pvp_dice") || rest.startsWith("/play/cub")) return "Кубики";
  if (rest.startsWith("/play/baccara")) return "Баккара";
  if (rest.startsWith("/play/blackjack")) return "Блэкджек";
  if (rest.startsWith("/play/roulette")) return "Рулетка";
  if (rest.startsWith("/play/fixed_room") || rest.startsWith("/rooms")) return "Комнаты";
  if (rest.startsWith("/play/raffle")) return "FocusLucky";
  if (rest.startsWith("/play/")) return "Игра";
  if (rest.startsWith("/tournaments")) return "Турниры";
  if (rest.startsWith("/fairness")) return "Честность";
  if (rest.startsWith("/settings")) return "Настройки";
  if (rest.startsWith("/wallet")) return "Кошелёк";
  if (rest.startsWith("/me") || rest.startsWith("/u/")) return "Профиль";
  return "FocusBet";
}

export function CasinoShell() {
  return (
    <CasinoOverlayProvider>
      <CasinoCashierProvider>
        <CasinoShellView />
      </CasinoCashierProvider>
    </CasinoOverlayProvider>
  );
}

function CasinoShellView() {
  const { user, isAuthed } = useSession();
  const { overlay, close } = useCasinoOverlay();
  const { openCashier } = useCasinoCashier();
  const location = useLocation();
  const navigate = useNavigate();
  const { currency, setCurrency } = useCasinoCurrency();
  const wallet = useCasinoWallet(isAuthed);
  const chipsMode = wallet.active.unit === "chips";
  const [balanceRub, setBalanceRub] = useState<number | null>(null);
  const [balanceHeld, setBalanceHeld] = useState(false);
  const [usdtRate, setUsdtRate] = useState(0);
  const [bellOpen, setBellOpen] = useState(false);
  const [chatOpen, setChatOpen] = useState(false);
  const [me, setMe] = useState<CasinoChatActor | null>(null);
  const [inboxItems, setInboxItems] = useState<CasinoInboxItem[]>([]);
  const [sessions, setSessions] = useState<CasinoInboxSession[]>([]);
  const [inboxUnread, setInboxUnread] = useState(0);
  const [gamesOpen, setGamesOpen] = useState(false);
  const [profileOpen, setProfileOpen] = useState(false);
  const [railOpen, setRailOpen] = useState(() => {
    try {
      return sessionStorage.getItem("focusbet-rail") !== "0";
    } catch {
      return true;
    }
  });
  const [balanceHidden, setBalanceHidden] = useState(() => {
    try {
      return sessionStorage.getItem("focusbet-balance-hidden") === "1";
    } catch {
      return false;
    }
  });
  const rest = casinoRest(location.pathname);
  const homeTo = casinoTo("/casino");
  useEffect(() => {
    const button = isCasinoMiniApp() ? getTelegramWebApp()?.BackButton : undefined;
    if (!button) return;
    const goBack = () => {
      if (!window.dispatchEvent(new Event("focusbet:back", { cancelable: true }))) return;
      if (overlay) close();
      else if (Number(window.history.state?.idx) > 0) navigate(-1);
      else navigate(homeTo, { replace: true });
    };
    if (rest === "/" && !overlay) button.hide();
    else button.show();
    button.onClick(goBack);
    return () => {
      button.offClick(goBack);
      button.hide();
    };
  }, [rest, overlay, close, navigate, homeTo]);
  const roomsTo = casinoTo("/casino/play/fixed_room?mode=players");
  const walletTo = isAuthed ? casinoWalletPath() : "/login";

  useEffect(() => {
    if (!chatOpen && !profileOpen) return;
    const onKey = (event: KeyboardEvent) => {
      if (event.key !== "Escape") return;
      setChatOpen(false);
      setProfileOpen(false);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [chatOpen, profileOpen]);

  useEffect(() => {
    const root = document.documentElement;
    const viewport = window.visualViewport;
    const syncKeyboard = () => {
      const overlap = viewport
        ? Math.max(0, window.innerHeight - viewport.height - viewport.offsetTop)
        : 0;
      root.style.setProperty("--casino-keyboard-h", `${Math.round(overlap)}px`);
    };
    syncKeyboard();
    viewport?.addEventListener("resize", syncKeyboard);
    viewport?.addEventListener("scroll", syncKeyboard);
    window.addEventListener("resize", syncKeyboard);
    return () => {
      viewport?.removeEventListener("resize", syncKeyboard);
      viewport?.removeEventListener("scroll", syncKeyboard);
      window.removeEventListener("resize", syncKeyboard);
      root.style.removeProperty("--casino-keyboard-h");
    };
  }, []);

  useEffect(() => {
    if (!isAuthed) {
      setBalanceRub(null);
      setBalanceHeld(false);
      return;
    }
    let timer = 0;
    let seq = 0;
    let held = false;
    function reload() {
      const id = ++seq;
      getBalance()
        .then((row) => {
          if (held || id !== seq) return;
          setBalanceRub(spendableBalanceRub(row));
        })
        .catch(() => undefined);
    }
    function schedule() {
      if (held) return;
      window.clearTimeout(timer);
      timer = window.setTimeout(reload, 800);
    }
    function onEvent() {
      const wasHeld = held;
      held = false;
      setBalanceHeld(false);
      if (wasHeld) {
        window.clearTimeout(timer);
        reload();
        return;
      }
      schedule();
    }
    function onHold() {
      held = true;
      seq += 1;
      setBalanceHeld(true);
      window.clearTimeout(timer);
    }
    function onRelease() {
      held = false;
      seq += 1;
      setBalanceHeld(false);
    }
    reload();
    window.addEventListener(CASINO_BALANCE_EVENT, onEvent);
    window.addEventListener(CASINO_BALANCE_HOLD_EVENT, onHold);
    window.addEventListener(CASINO_BALANCE_RELEASE_EVENT, onRelease);
    return () => {
      window.clearTimeout(timer);
      window.removeEventListener(CASINO_BALANCE_EVENT, onEvent);
      window.removeEventListener(CASINO_BALANCE_HOLD_EVENT, onHold);
      window.removeEventListener(CASINO_BALANCE_RELEASE_EVENT, onRelease);
    };
  }, [isAuthed]);

  useEffect(() => {
    if (!isAuthed) {
      setMe(null);
      return;
    }
    function reload() {
      getCasinoPlayer("me")
        .then((payload) => setMe(payload.player))
        .catch(() => setMe(null));
    }
    reload();
    window.addEventListener(CASINO_LOOK_EVENT, reload);
    return () => window.removeEventListener(CASINO_LOOK_EVENT, reload);
  }, [isAuthed]);

  useEffect(() => {
    if (!isAuthed) {
      setInboxItems([]);
      setSessions([]);
      setInboxUnread(0);
      return;
    }
    let cancelled = false;
    function apply(payload: { unread: number; items: CasinoInboxItem[]; sessions: CasinoInboxSession[] }) {
      if (cancelled) return;
      setInboxItems(payload.items);
      setSessions(payload.sessions);
      setInboxUnread(payload.unread);
    }
    function reload() {
      getCasinoInbox().then(apply).catch(() => undefined);
    }
    reload();
    const poll = window.setInterval(reload, 8000);
    const token = getToken("user");
    const qs = token ? `?access_token=${encodeURIComponent(token)}` : "";
    let es: EventSource | null = null;
    try {
      es = new EventSource(`${API_BASE}/user/casino/chat/events${qs}`, { withCredentials: true });
      es.onmessage = (event) => {
        try {
          const payload = JSON.parse(event.data) as { type?: string };
          if (payload.type === "inbox") reload();
        } catch {
          /* ignore malformed SSE */
        }
      };
    } catch {
      es = null;
    }
    return () => {
      cancelled = true;
      window.clearInterval(poll);
      es?.close();
    };
  }, [isAuthed]);

  useEffect(() => {
    getRates()
      .then((payload) => {
        const rate = payload.rates.usdt?.sell || payload.rates.usdt?.market || 0;
        setUsdtRate(Number(rate) || 0);
      })
      .catch(() => setUsdtRate(0));
  }, []);

  const chipsBalance = useMemo(() => {
    const row = wallet.wallets.find((item) => item.selected);
    return row && row.unit === "chips" ? walletRowBalance(row) : null;
  }, [wallet.wallets]);

  const displayBalance = useMemo(() => {
    if (chipsBalance != null) return formatWalletAmount(chipsBalance, "chips");
    if (balanceRub == null) return isAuthed ? "…" : "Войти";
    if (currency === "usdt") {
      if (!usdtRate) return formatRub(balanceRub);
      return `${(balanceRub / usdtRate).toFixed(2)} USDT`;
    }
    return formatRub(balanceRub);
  }, [balanceRub, chipsBalance, currency, isAuthed, usdtRate]);
  const hiddenBalance = chipsMode ? "•••• Ф" : currency === "usdt" ? "•••• USDT" : "•••• ₽";
  const shownBalance = balanceHidden ? hiddenBalance : displayBalance;

  function toggleBalanceHidden() {
    setBalanceHidden((hidden) => {
      const next = !hidden;
      try {
        sessionStorage.setItem("focusbet-balance-hidden", next ? "1" : "0");
      } catch {
        /* private mode */
      }
      return next;
    });
  }

  const awaySessions = useMemo(
    () => sessions.filter((row) => !hrefMatchesPath(row.href, location.pathname, location.search)),
    [location.pathname, location.search, sessions],
  );
  const bellCount = inboxUnread + awaySessions.length;
  const initial = (me?.display_name || user?.display_name || user?.username || "F").trim().slice(0, 1).toUpperCase();
  const profileTo = isAuthed ? casinoTo("/casino/me") : "/login";

  useEffect(() => {
    if (rest === "/" && location.hash === "#duels") {
      navigate(roomsTo, { replace: true });
    }
  }, [roomsTo, location.hash, navigate, rest]);

  function goToGame(
    href: string,
    item?: { id?: number; game_id?: string; href?: string; kind?: string; payload?: { kind?: string; game_type?: string } },
  ) {
    setBellOpen(false);
    if (item?.id) {
      readCasinoInbox([item.id])
        .then((payload) => {
          setInboxItems(payload.items);
          setSessions(payload.sessions);
          setInboxUnread(payload.unread);
        })
        .catch(() => undefined);
    }
    const next = casinoInboxPlayHref(href, {
      kind: item?.payload?.kind ?? item?.kind,
      gameId: item?.game_id,
      gameType: item?.payload?.game_type,
    });
    navigate(casinoTo(next));
  }

  async function dropSession(row: CasinoInboxSession) {
    try {
      if (row.kind === "duel") {
        await cancelCasinoDuel(row.game_id);
        toast.success("Игра отменена, ставка вернулась");
      } else if (row.kind === "house") {
        await leaveCasinoHouseTable(row.game_id);
        toast.success("Вы встали со стола");
      } else if (row.kind === "v2") {
        const table = await getCasinoV2Table(row.game_id);
        if (table.can_cancel) {
          await cancelCasinoV2Table(table.table_id, table.state_version);
          toast.success("Стол отменён");
        } else {
          await leaveCasinoV2Table(table.table_id, table.state_version);
          toast.success("Вы встали со стола");
        }
      } else if (row.kind === "room") {
        const room = await getCasinoRoom(row.game_id);
        if (room.can_cancel) {
          await postCasinoRoomCancel(room.room_id);
          toast.success("Комната отменена");
        } else {
          await postCasinoRoomLeave(room.room_id);
          toast.success("Вы вышли");
        }
      } else {
        goToGame(row.href);
        return;
      }
      window.dispatchEvent(new Event(CASINO_BALANCE_EVENT));
      const payload = await getCasinoInbox();
      setInboxItems(payload.items);
      setSessions(payload.sessions);
      setInboxUnread(payload.unread);
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Не удалось отменить");
    }
  }

  function sessionDropLabel(row: CasinoInboxSession): string {
    if (row.kind === "house" || row.can_leave) return "Встать";
    return "Отменить";
  }

  function closeLayer() {
    setGamesOpen(false);
    if (overlay) close();
    else navigate("/");
  }

  return (
    <div className={`casino-root casino-shell${overlay ? " is-overlay" : ""}`} data-tg={isCasinoMiniApp() ? "1" : "0"} data-casino-overlay-shell={overlay ? "1" : "0"} data-casino-wallet-kind={wallet.active.kind}>
      <a className="casino-sr-only casino-skip" href="#casino-content">
        К содержимому
      </a>
      <header className="casino-header" data-casino-header="">
        <div className="casino-header-start">
          {rest !== "/" ? (
            <button
              type="button"
              className="casino-mobile-back"
              onClick={() => {
                if (!window.dispatchEvent(new Event("focusbet:back", { cancelable: true }))) return;
                if (Number(window.history.state?.idx) > 0) navigate(-1);
                else navigate(homeTo, { replace: true });
              }}
              aria-label="Назад"
            >
              <ChevronLeft size={24} />
            </button>
          ) : null}
          {isCasinoMiniApp() ? null : (
            <button type="button" className="casino-icon-btn casino-close-btn" onClick={closeLayer} aria-label="Закрыть FocusBet">
              <X size={18} />
            </button>
          )}
          <Link to={homeTo} className="casino-brand" aria-label="FocusBet">
            <img className="casino-brand-logo-img" src="/casino/focusbet-logo.svg" alt="" width={92} height={46} />
          </Link>
          {rest !== "/" ? <strong className="casino-mobile-screen-title">{mobileScreenTitle(rest)}</strong> : null}
        </div>
        <div className="casino-header-mid">
          <div className="casino-wallet" data-casino-wallet="">
            {isAuthed ? (
              <>
                <CasinoWalletSwitch wallet={wallet} />
                <Link
                  to={walletTo}
                  className="casino-balance-pill casino-wallet-balance"
                  data-casino-balance=""
                  data-casino-balance-hold={balanceHeld ? "1" : "0"}
                  aria-label={balanceHidden ? "Баланс скрыт. Открыть кошелёк. Долгое нажатие — сменить валюту." : `Баланс ${displayBalance}. Открыть кошелёк. Долгое нажатие — сменить валюту.`}
                  title="Кошелёк · долгое нажатие — ₽/USDT"
                  onContextMenu={(event) => {
                    if (!usdtRate) return;
                    event.preventDefault();
                    setCurrency(currency === "usdt" ? "rub" : "usdt");
                  }}
                >
                  <span className="casino-wallet-label">Баланс</span>
                  <strong className="casino-balance-amount" data-casino-balance-hidden={balanceHidden ? "1" : "0"}>{shownBalance}</strong>
                  <ChevronRight className="casino-mobile-balance-chevron" size={16} aria-hidden />
                </Link>
                <button
                  type="button"
                  className="casino-wallet-eye"
                  aria-label={balanceHidden ? "Показать баланс" : "Скрыть баланс"}
                  aria-pressed={balanceHidden}
                  data-casino-balance-eye=""
                  onClick={toggleBalanceHidden}
                >
                  {balanceHidden ? <EyeOff size={16} aria-hidden /> : <Eye size={16} aria-hidden />}
                </button>
                <button
                  type="button"
                  className="casino-btn casino-btn-ghost casino-header-withdraw"
                  data-casino-header-withdraw=""
                  disabled={chipsMode}
                  title={chipsMode ? "Фишки не выводятся" : undefined}
                  onClick={() => openCashier("withdraw")}
                >
                  Вывести
                </button>
                <button type="button" className="casino-btn casino-header-deposit" data-casino-header-deposit="" disabled={chipsMode} title={chipsMode ? "Касса работает на основном балансе" : undefined} onClick={() => openCashier("deposit")}>
                  <Plus size={16} aria-hidden />
                  Пополнить
                </button>
              </>
            ) : (
              <CasinoLoginLink className="casino-balance-pill is-guest" aria-label="Войти">
                Войти
              </CasinoLoginLink>
            )}
          </div>
        </div>
        <div className="casino-header-end">
        <div className="casino-header-actions">
          <button
            type="button"
            className={`casino-icon-btn casino-header-chat${chatOpen ? " is-on" : ""}`}
            aria-label={chatOpen ? "Закрыть чат" : "Открыть чат"}
            aria-pressed={chatOpen}
            data-casino-chat-toggle=""
            onClick={() => {
              setChatOpen((open) => !open);
              setBellOpen(false);
              setGamesOpen(false);
            }}
          >
            <MessageCircle size={18} />
          </button>
          <div className="casino-bell-wrap">
            <button
              type="button"
              className="casino-icon-btn"
              aria-label="Уведомления"
              data-casino-bell=""
              onClick={() => setBellOpen((open) => !open)}
            >
              <Bell size={18} />
              {bellCount > 0 ? <span className="casino-bell-badge">{bellCount > 9 ? "9+" : bellCount}</span> : null}
            </button>
            {bellOpen ? (
              <div className="casino-bell-panel" data-casino-inbox="">
                {sessions.length ? (
                  <div className="casino-bell-group">
                    <p className="casino-bell-heading">Вы в игре</p>
                    {sessions.map((row) => (
                      <div key={`${row.kind}-${row.game_id}`} className="casino-bell-row casino-bell-session">
                        <button type="button" className="casino-bell-row-main" onClick={() => goToGame(row.href, row)}>
                          <span>
                            <strong>{row.title}</strong>
                            <span className="casino-bell-meta">{row.body}</span>
                          </span>
                          <span className="casino-bell-go">Перейти</span>
                        </button>
                        {row.can_cancel || row.can_leave ? (
                          <button
                            type="button"
                            className="casino-bell-drop"
                            onClick={() => void dropSession(row)}
                          >
                            {sessionDropLabel(row)}
                          </button>
                        ) : null}
                      </div>
                    ))}
                  </div>
                ) : null}
                    {inboxItems.length ? (
                  <div className="casino-bell-group">
                    <div className="casino-bell-section-head">
                      <p className="casino-bell-heading">Уведомления</p>
                      <span>{inboxItems.length}</span>
                    </div>
                    {inboxItems.map((item) => (
                      <button
                        key={item.id ?? `${item.event_type}-${item.game_id}`}
                        type="button"
                        className={`casino-bell-row${item.read_at ? "" : " is-unread"}`}
                        onClick={() => goToGame(item.href, item)}
                      >
                        <span className="casino-bell-dot" aria-hidden />
                        <span className="casino-bell-copy">
                          <strong>{item.title}</strong>
                          <span className="casino-bell-meta">{item.body}</span>
                        </span>
                        <span className="casino-bell-go">Открыть</span>
                      </button>
                    ))}
                  </div>
                ) : null}
                {!sessions.length && !inboxItems.length ? <div className="casino-bell-empty">Нет уведомлений</div> : null}
              </div>
            ) : null}
          </div>
          {isAuthed ? (
            <button
              type="button"
              className={`casino-avatar casino-profile-trigger${profileOpen ? " is-on" : ""}`}
              aria-label="Открыть профиль и действия с кошельком"
              aria-expanded={profileOpen}
              onClick={() => {
                setProfileOpen((open) => !open);
                setBellOpen(false);
                setChatOpen(false);
                setGamesOpen(false);
              }}
            >
              {me ? <CasinoPlayerAvatar actor={me} size={40} /> : initial}
            </button>
          ) : (
            <CasinoLoginLink className="casino-avatar" aria-label="Войти">
              <UserRound size={16} />
            </CasinoLoginLink>
          )}
        </div>
        </div>
      </header>
      {profileOpen && isAuthed ? (
        <>
          <button type="button" className="casino-profile-sheet-backdrop" aria-label="Закрыть профиль" onClick={() => setProfileOpen(false)} />
          <section className="casino-profile-sheet" aria-label="Профиль и кошелёк">
            <div className="casino-profile-sheet-head">
              <div className="casino-profile-sheet-user">
                {me ? <CasinoPlayerAvatar actor={me} size={44} /> : <span className="casino-profile-sheet-initial">{initial}</span>}
                <span>
                  <strong>{me?.display_name || user?.display_name || user?.username || "Профиль"}</strong>
                  <small>FocusBet</small>
                </span>
              </div>
              <button type="button" className="casino-profile-sheet-close" aria-label="Закрыть" onClick={() => setProfileOpen(false)}>
                <X size={18} />
              </button>
            </div>
            <Link to={walletTo} className="casino-profile-sheet-balance" onClick={() => setProfileOpen(false)}>
              <span>Баланс</span>
              <strong>{shownBalance}</strong>
            </Link>
            <div className="casino-profile-sheet-actions">
              <button type="button" className="casino-btn casino-profile-sheet-deposit" onClick={() => { setProfileOpen(false); openCashier("deposit"); }}>
                Пополнить
              </button>
              <button type="button" className="casino-btn casino-btn-ghost" onClick={() => { setProfileOpen(false); openCashier("withdraw"); }}>
                Вывести
              </button>
            </div>
            <nav className="casino-profile-sheet-links" aria-label="Разделы профиля">
              <Link to={profileTo} onClick={() => setProfileOpen(false)}><UserRound size={17} /> Профиль</Link>
              <Link to={walletTo} onClick={() => setProfileOpen(false)}><Wallet size={17} /> Кошелёк и история</Link>
              <Link to={casinoTo("/casino/settings")} onClick={() => setProfileOpen(false)}><Settings size={17} /> Настройки</Link>
            </nav>
          </section>
        </>
      ) : null}
      <div className="casino-body">
        <aside className={`casino-rail${railOpen ? " is-open" : ""}`} data-casino-rail={railOpen ? "expanded" : "collapsed"}>
          <button
            type="button"
            className="casino-rail-toggle"
            aria-label={railOpen ? "Свернуть меню" : "Развернуть меню"}
            aria-pressed={railOpen}
            onClick={() => {
              setRailOpen((open) => {
                const next = !open;
                try {
                  sessionStorage.setItem("focusbet-rail", next ? "1" : "0");
                } catch {
                  /* private mode */
                }
                return next;
              });
            }}
          >
            {railOpen ? <PanelLeftClose size={20} aria-hidden /> : <PanelLeftOpen size={20} aria-hidden />}
          </button>
          <NavLink to={homeTo} end className={({ isActive }) => `casino-rail-item${isActive ? " active" : ""}`}>
            <Home size={20} />
            <span className="casino-rail-label">Лобби</span>
          </NavLink>
          <p className="casino-rail-heading">Игры</p>
          {visibleCasinoCatalog().map((game) => {
            const onPlay =
              rest === `/play/${game.id}` || (game.id === "pvp_dice" && (rest === "/play/cub" || rest === "/play/pvp_dice"));
            const onDuelGame = rest === "/duels" && new URLSearchParams(location.search).get("game") === game.id;
            const onJackpot = game.id === "jackpot" && rest.startsWith("/jackpot");
            const onRooms = game.id === "fixed_room" && (rest.startsWith("/rooms") || rest === "/duels");
            return (
              <NavLink
                key={game.id}
                to={casinoTo(game.href)}
                className={`casino-rail-item${onPlay || onDuelGame || onJackpot || onRooms ? " active" : ""}`}
              >
                <span className="casino-rail-icon" aria-hidden>
                  {gameRailIcon(game.id, game.emoji)}
                </span>
                <span className="casino-rail-label">{game.name}</span>
              </NavLink>
            );
          })}
          {CASINO_CLANS_PAGE_HIDDEN ? null : (
            <NavLink to={casinoTo("/casino/clans")} className={({ isActive }) => `casino-rail-item${isActive || rest.startsWith("/clans") ? " active" : ""}`}>
              <span className="casino-rail-label">Команды</span>
            </NavLink>
          )}
          <NavLink
            to={casinoTo("/casino/tournaments")}
            className={({ isActive }) => `casino-rail-item${isActive || rest.startsWith("/tournaments") ? " active" : ""}`}
          >
            <Trophy size={20} />
            <span className="casino-rail-label">Турниры</span>
          </NavLink>
          <NavLink
            to={casinoTo("/casino/fairness")}
            className={({ isActive }) => `casino-rail-item${isActive || rest.startsWith("/fairness") ? " active" : ""}`}
          >
            <ShieldCheck size={20} />
            <span className="casino-rail-label">Честность</span>
          </NavLink>
          <NavLink to={casinoTo("/casino/me")} className={({ isActive }) => `casino-rail-item${isActive || rest.startsWith("/u/") ? " active" : ""}`}>
            <UserRound size={20} />
            <span className="casino-rail-label">Профиль</span>
          </NavLink>
          <NavLink to={casinoTo("/casino/settings")} className={({ isActive }) => `casino-rail-item${isActive || rest.startsWith("/settings") ? " active" : ""}`}>
            <Settings size={20} />
            <span className="casino-rail-label">Настройки</span>
          </NavLink>
        </aside>
        <main className="casino-main" id="casino-content" data-casino-content="">
          {chipsMode ? (
            <div className="casino-chips-banner" data-casino-chips-banner="">
              <Trophy size={15} aria-hidden />
              <span>
                {wallet.active.kind === "bonus"
                  ? "Играете на бонусные фишки — выигрыш не выводится"
                  : `${wallet.active.title}: ставки идут турнирными фишками`}
              </span>
              {/* Выход на рубли нужен с любого экрана: в фишках видны только фишковые столы. */}
              <button
                type="button"
                className="casino-btn casino-btn-ghost casino-chips-banner-exit"
                onClick={async () => {
                  try {
                    await wallet.select("rub");
                    window.dispatchEvent(new Event(CASINO_BALANCE_EVENT));
                    toast.success("Вернулись на основной баланс");
                  } catch (err) {
                    toast.error(err instanceof Error ? err.message : "Не удалось сменить кошелёк");
                  }
                }}
              >
                На ₽
              </button>
            </div>
          ) : null}
          <Outlet />
        </main>
        <CasinoChatPanel open={chatOpen} onClose={() => setChatOpen(false)} docked={chatOpen} />
      </div>

      {gamesOpen ? (
        <div className="casino-games-sheet" data-casino-games-sheet="">
          <p className="casino-games-sheet-title">Игры</p>
          {visibleCasinoCatalog().map((game) => (
            <NavLink
              key={game.id}
              to={casinoTo(game.href)}
              className="casino-games-sheet-item"
              onClick={() => setGamesOpen(false)}
            >
              <span className="casino-rail-icon" aria-hidden>
                {gameRailIcon(game.id, game.emoji)}
              </span>
              {game.name}
            </NavLink>
          ))}
          {CASINO_CLANS_PAGE_HIDDEN ? null : (
            <NavLink to={casinoTo("/casino/clans")} className="casino-games-sheet-item" onClick={() => setGamesOpen(false)}>
              Команды
            </NavLink>
          )}
          <NavLink to={casinoTo("/casino/tournaments")} className="casino-games-sheet-item" onClick={() => setGamesOpen(false)}>
            <Trophy size={18} />
            Турниры
          </NavLink>
          <NavLink to={casinoTo("/casino/fairness")} className="casino-games-sheet-item" onClick={() => setGamesOpen(false)}>
            <ShieldCheck size={18} />
            Честность
          </NavLink>
        </div>
      ) : null}

      <nav className="casino-nav-mobile" data-casino-nav-mobile="">
        <NavLink
          to={homeTo}
          end
          className={({ isActive }) => `casino-nav-item${isActive ? " active" : ""}`}
          onClick={() => {
            setGamesOpen(false);
            setChatOpen(false);
          }}
        >
          <span><Home size={20} /></span>
          Игры
        </NavLink>
        <button
          type="button"
          className={`casino-nav-item${chatOpen ? " active" : ""}`}
          onClick={() => {
            setChatOpen((open) => !open);
            setGamesOpen(false);
          }}
        >
          <span><MessageCircle size={20} /></span>
          Чат
        </button>
        {isAuthed ? (
          <NavLink
            to={profileTo}
            className={({ isActive }) => `casino-nav-item${isActive && !gamesOpen ? " active" : ""}`}
            onClick={() => setGamesOpen(false)}
          >
            <span><UserRound size={20} /></span>
            Профиль
          </NavLink>
        ) : (
          <CasinoLoginLink className="casino-nav-item">
            <span><UserRound size={20} /></span>
            Профиль
          </CasinoLoginLink>
        )}
      </nav>
      <CasinoCashierHost />
    </div>
  );
}

/**
 * Header wallet switch: real money, bonus chips or one of the player's live
 * tournament stacks. Picking a chip wallet reroutes every stake into chips.
 */
function CasinoWalletSwitch({ wallet }: { wallet: CasinoWalletState }) {
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const { wallets, active } = wallet;
  if (wallets.length < 2) return null;

  async function pick(row: CasinoWalletRow) {
    if (busy || row.selected) return;
    setBusy(true);
    try {
      await wallet.select(row.kind, row.tournament_id ?? null);
      setOpen(false);
      window.dispatchEvent(new Event(CASINO_BALANCE_EVENT));
      toast.success(
        row.kind === "rub"
          ? "Вернулись на основной баланс"
          : `Ставки идут фишками: ${row.title}`,
      );
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Не удалось сменить кошелёк");
    } finally {
      setBusy(false);
    }
  }

  const bonusRow = wallets.find((row) => row.kind === "bonus");
  const bonusEmpty = Boolean(bonusRow) && walletRowBalance(bonusRow!) <= 0;

  async function refill() {
    if (busy) return;
    setBusy(true);
    try {
      const res = await refillCasinoBonusChips();
      await wallet.reload();
      toast.success(`Начислено ${Math.round(res.granted_chips)} фишек`);
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Не удалось пополнить фишки");
    } finally {
      setBusy(false);
    }
  }

  const chips = active.unit === "chips";
  return (
    <div className="casino-wallet-switch" data-casino-wallet-switch={active.kind}>
      <button
        type="button"
        className={`casino-balance-pill casino-wallet-switch-btn${chips ? " is-tournament" : ""}`}
        aria-expanded={open}
        onClick={() => setOpen((value) => !value)}
      >
        {chips ? <Trophy size={15} aria-hidden /> : <Wallet size={15} aria-hidden />}
        <span>{chips ? active.title : "Основной ₽"}</span>
      </button>
      {open ? (
        <div className="casino-wallet-switch-menu" role="menu">
          {wallets.map((row) => (
            <button
              key={row.scope}
              type="button"
              role="menuitem"
              disabled={busy || row.selected}
              onClick={() => void pick(row)}
            >
              {row.title}
              <small>{formatWalletAmount(walletRowBalance(row), row.unit)}</small>
            </button>
          ))}
          {bonusEmpty ? (
            <button type="button" role="menuitem" disabled={busy} onClick={() => void refill()}>
              Пополнить бонусные фишки
              <small>раз в сутки, бесплатно</small>
            </button>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}
