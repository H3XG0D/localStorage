import "./casino.css";
import "./casino-skin.css";
import {
  createContext,
  useCallback,
  useContext,
  useMemo,
  useRef,
  type ReactNode,
} from "react";
import * as Dialog from "@radix-ui/react-dialog";
import {
  UNSAFE_NavigationContext,
  useLocation,
  useNavigate,
  type Location,
  type NavigateOptions,
  type To,
} from "react-router-dom";

export type CasinoBackground = Pick<Location, "pathname" | "search" | "hash"> & {
  state: unknown;
};

export type CasinoLocationState = {
  casinoBackground?: CasinoBackground;
  from?: string;
  scrollY?: number;
};

type OverlayValue = {
  background: CasinoBackground | null;
  overlay: boolean;
  close: () => void;
};

const CasinoOverlayContext = createContext<OverlayValue>({
  background: null,
  overlay: false,
  close: () => undefined,
});

export function isCasinoShellPath(pathname: string): boolean {
  if (pathname === "/casino" || pathname === "/casino/") return true;
  if (!pathname.startsWith("/casino/")) return false;
  if (pathname.startsWith("/casino/tg")) return false;
  if (pathname.startsWith("/casino/tokens")) return false;
  if (pathname.startsWith("/casino/creator")) return false;
  return true;
}

export function snapshotCasinoBackground(location: Location): CasinoBackground {
  const prev =
    location.state && typeof location.state === "object" && !Array.isArray(location.state)
      ? (location.state as Record<string, unknown>)
      : {};
  return {
    pathname: location.pathname,
    search: location.search,
    hash: location.hash,
    state: { ...prev, scrollY: typeof window !== "undefined" ? window.scrollY : 0 },
  };
}

export function readCasinoBackground(location: Location): CasinoBackground | null {
  const state = location.state as CasinoLocationState | null;
  const bg = state?.casinoBackground;
  if (!bg || typeof bg !== "object" || typeof bg.pathname !== "string") return null;
  return bg;
}

export function isCasinoOverlayLocation(location: Location): Location | null {
  if (!isCasinoShellPath(location.pathname)) return null;
  const background = readCasinoBackground(location);
  if (!background) return null;
  if (isCasinoShellPath(background.pathname)) return null;
  return {
    pathname: background.pathname,
    search: background.search,
    hash: background.hash,
    state: background.state,
    key: "casino-background",
  };
}

function mergeCasinoState(state: unknown, background: CasinoBackground | null): unknown {
  if (!background) return state;
  if (state && typeof state === "object" && !Array.isArray(state)) {
    const rec = state as Record<string, unknown>;
    if (rec.casinoBackground) return state;
    return { ...rec, casinoBackground: background };
  }
  if (state == null) return { casinoBackground: background };
  return { casinoBackground: background, value: state };
}

export function navigateToCasinoBackground(
  navigate: ReturnType<typeof useNavigate>,
  background: CasinoBackground | null,
) {
  if (!background) {
    navigate("/", { replace: true });
    return;
  }
  const scrollY = (background.state as CasinoLocationState | null)?.scrollY;
  navigate(
    {
      pathname: background.pathname,
      search: background.search,
      hash: background.hash,
    },
    { preventScrollReset: true, state: background.state },
  );
  if (typeof scrollY === "number") {
    requestAnimationFrame(() => window.scrollTo(0, scrollY));
  }
}

export function useCasinoOverlay(): OverlayValue {
  return useContext(CasinoOverlayContext);
}

export function CasinoOverlayProvider({ children }: { children: ReactNode }) {
  const location = useLocation();
  const navigate = useNavigate();
  const navContext = useContext(UNSAFE_NavigationContext);
  const background = readCasinoBackground(location);
  const backgroundRef = useRef(background);
  backgroundRef.current = background;

  const close = useCallback(() => {
    navigateToCasinoBackground(navigate, backgroundRef.current);
  }, [navigate]);

  const patchedNavigator = useMemo(() => {
    const { navigator } = navContext;
    return {
      ...navigator,
      push(to: To, state?: unknown, opts?: NavigateOptions) {
        navigator.push(to, mergeCasinoState(state, backgroundRef.current), opts);
      },
      replace(to: To, state?: unknown, opts?: NavigateOptions) {
        navigator.replace(to, mergeCasinoState(state, backgroundRef.current), opts);
      },
    };
  }, [navContext]);

  const value = useMemo(
    () => ({ background, overlay: Boolean(background), close }),
    [background, close],
  );

  return (
    <CasinoOverlayContext.Provider value={value}>
      <UNSAFE_NavigationContext.Provider value={{ ...navContext, navigator: patchedNavigator }}>
        {children}
      </UNSAFE_NavigationContext.Provider>
    </CasinoOverlayContext.Provider>
  );
}

export function CasinoOverlay({ children }: { children: ReactNode }) {
  const location = useLocation();
  const navigate = useNavigate();
  const background = readCasinoBackground(location);

  function onOpenChange(open: boolean) {
    if (!open) navigateToCasinoBackground(navigate, background);
  }

  return (
    <Dialog.Root open onOpenChange={onOpenChange}>
      <Dialog.Portal>
        <Dialog.Overlay className="casino-overlay-backdrop" data-casino-overlay-backdrop="" />
        <Dialog.Content
          className="casino-overlay-sheet"
          data-casino-overlay="1"
          aria-describedby={undefined}
          onOpenAutoFocus={(event) => event.preventDefault()}
          onCloseAutoFocus={(event) => event.preventDefault()}
          onInteractOutside={(event) => {
            const target = event.target as HTMLElement | null;
            if (target?.closest("[data-radix-popper-content-wrapper], [data-sonner-toaster], [data-casino-overlay]")) {
              event.preventDefault();
            }
          }}
        >
          <Dialog.Title className="casino-sr-only">FocusBet</Dialog.Title>
          <div className="casino-overlay-handle" aria-hidden />
          {children}
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}
