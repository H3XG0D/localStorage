import { forwardRef, type ReactNode } from "react";
import { Link, Navigate, useLocation, useNavigate, type LinkProps } from "react-router-dom";
import { authPathWithNext, resolvePostLoginPath } from "@/lib/postLoginPath";
import { snapshotCasinoBackground, useCasinoOverlay } from "./casinoOverlay";
import { getTelegramWebApp, isCasinoMiniApp, isInsideTelegram } from "./telegram";

export function casinoInboxPlayHref(
  href: string,
  opts?: { kind?: string | null; gameId?: string | null; gameType?: string | null },
): string {
  const kind = String(opts?.kind ?? "").trim().toLowerCase();
  const gameId = String(opts?.gameId ?? "").trim();
  const raw = String(href || "").trim();
  if (kind === "v2" && gameId) return `/casino/tables/${gameId}`;
  if (kind === "room" && gameId) return `/casino/rooms/${gameId}`;
  if (raw.includes("/casino/duels/") && kind !== "duel" && (kind === "v2" || gameId.startsWith("web-"))) {
    return `/casino/tables/${gameId || raw.slice(raw.lastIndexOf("/") + 1)}`;
  }
  return raw || "/casino";
}

export const CASINO_TG_BASENAME = "/casino/tg";

export function casinoRest(pathname: string): string {
  if (pathname === "/" || pathname === "/casino" || pathname === "/casino/") return "/";
  if (pathname.startsWith("/casino/")) return pathname.slice("/casino".length) || "/";
  return pathname || "/";
}

export function casinoTo(sitePath: string): string {
  const [rawPath, query] = sitePath.split("?");
  const path = rawPath.startsWith("/") ? rawPath : `/${rawPath}`;
  let mapped = path;
  if (isCasinoMiniApp()) {
    if (path === "/casino" || path === "/casino/") mapped = "/";
    else if (path.startsWith("/casino/")) mapped = path.slice("/casino".length) || "/";
  }
  return query ? `${mapped}?${query}` : mapped;
}

export const CASINO_DEPOSIT_HASH = "deposit";
export const CASINO_WITHDRAW_HASH = "withdraw";

export function casinoWalletPath(opts?: { deposit?: boolean; withdraw?: boolean }): string {
  const path = casinoTo("/casino/wallet");
  if (opts?.withdraw) return `${path}#${CASINO_WITHDRAW_HASH}`;
  if (opts?.deposit) return `${path}#${CASINO_DEPOSIT_HASH}`;
  return path;
}

export function goOutsideCasino(path: string) {
  const abs = path.startsWith("http") ? path : `${window.location.origin}${path}`;
  const tg = getTelegramWebApp();
  if (isCasinoMiniApp() && isInsideTelegram() && tg?.openLink) {
    tg.openLink(abs);
    return;
  }
  window.location.assign(path.startsWith("http") ? path : path);
}

export function RedirectToCasinoPlay({
  gameId,
  mode,
}: {
  gameId: string;
  mode: "house" | "players";
}) {
  return <Navigate to={casinoTo(`/casino/play/${gameId}?mode=${mode}`)} replace />;
}

/** Map a casino (or mini-app) location to a site path like `/casino/play/...`. */
export function casinoSitePath(pathname: string, search = ""): string {
  const query = !search || search === "?" ? "" : search.startsWith("?") ? search : `?${search}`;
  let path = pathname || "/";
  if (isCasinoMiniApp()) {
    if (path === "/" || path === "") path = "/casino";
    else if (!path.startsWith("/casino")) path = `/casino${path.startsWith("/") ? path : `/${path}`}`;
  }
  return resolvePostLoginPath(`${path}${query}`, "/casino");
}

export function goCasinoLogin(
  navigate: (to: string, opts?: { state?: unknown }) => void,
  from: string,
  extraState?: { casinoBackground?: unknown },
) {
  const qIndex = from.indexOf("?");
  const pathPart = qIndex >= 0 ? from.slice(0, qIndex) : from;
  const query = qIndex >= 0 ? from.slice(qIndex) : "";
  const siteFrom = casinoSitePath(pathPart, query);
  const href = authPathWithNext("/login/telegram", siteFrom);
  if (isCasinoMiniApp()) {
    goOutsideCasino(href);
    return;
  }
  navigate(href, { state: { from: siteFrom, ...extraState } });
}

export function CasinoLoginLink({
  className,
  children,
  "aria-label": ariaLabel,
}: {
  className?: string;
  children: ReactNode;
  "aria-label"?: string;
}) {
  const location = useLocation();
  const navigate = useNavigate();
  const { background } = useCasinoOverlay();
  const from = casinoSitePath(location.pathname, location.search);
  const href = authPathWithNext("/login/telegram", from);
  // Inside the Mini App the TelegramSession auto-verifies via init_data,
  // so login links just reload the session instead of leaving Telegram.
  if (isCasinoMiniApp() && isInsideTelegram()) {
    return (
      <button
        type="button"
        className={className}
        aria-label={ariaLabel}
        onClick={() => window.location.reload()}
      >
        {children}
      </button>
    );
  }
  return (
    <a
      href={href}
      className={className}
      aria-label={ariaLabel}
      onClick={(event) => {
        if (event.metaKey || event.ctrlKey || event.shiftKey || event.altKey || event.button !== 0) return;
        event.preventDefault();
        goCasinoLogin(navigate, from, background ? { casinoBackground: background } : undefined);
      }}
    >
      {children}
    </a>
  );
}

export const CasinoOpenLink = forwardRef<
  HTMLAnchorElement,
  {
    to?: string;
    className?: string;
    children: ReactNode;
    onClick?: LinkProps["onClick"];
    "aria-label"?: string;
  }
>(function CasinoOpenLink({ to = "/casino", className, children, onClick, "aria-label": ariaLabel }, ref) {
  const location = useLocation();
  if (isCasinoMiniApp() || location.pathname.startsWith("/casino")) {
    return (
      <Link ref={ref} to={casinoTo(to)} className={className} aria-label={ariaLabel} onClick={onClick}>
        {children}
      </Link>
    );
  }
  return (
    <Link
      ref={ref}
      to={to}
      className={className}
      aria-label={ariaLabel}
      preventScrollReset
      state={{ casinoBackground: snapshotCasinoBackground(location) }}
      onClick={onClick}
    >
      {children}
    </Link>
  );
});
CasinoOpenLink.displayName = "CasinoOpenLink";

export function CasinoExitLink({
  to,
  className,
  children,
  "aria-label": ariaLabel,
}: {
  to: string;
  className?: string;
  children: ReactNode;
  "aria-label"?: string;
}) {
  if (!isCasinoMiniApp()) {
    return (
      <Link to={to} className={className} aria-label={ariaLabel}>
        {children}
      </Link>
    );
  }
  return (
    <a
      href={to}
      className={className}
      aria-label={ariaLabel}
      onClick={(event) => {
        event.preventDefault();
        goOutsideCasino(to);
      }}
    >
      {children}
    </a>
  );
}
