// Panel session context, parameterised by scope (admin | operator). The panel
// SPA mounts one provider per scope subtree; it bootstraps from the stored
// bearer token via /me and exposes the account + auth actions.
import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";
import { DEV_STUB_ACCOUNT, isLocalDevPanel } from "@/panel/lib/devHost";
import { getPanelToken, onPanelAuthLoss } from "@/panel/lib/panelApi";
import { panelLogout, panelMe, type PanelAccount, type PanelScope } from "@/panel/lib/panelAuth";

interface PanelSessionState {
  scope: PanelScope;
  account: PanelAccount | null;
  loading: boolean;
  isAuthed: boolean;
  setAccount: (a: PanelAccount | null) => void;
  refresh: () => Promise<void>;
  logout: () => Promise<void>;
}

const Ctx = createContext<PanelSessionState | null>(null);

const ACCOUNT_CACHE_KEY: Record<PanelScope, string> = {
  admin: "focuspay_admin_account",
  operator: "focuspay_operator_account",
};

function readCachedAccount(scope: PanelScope): PanelAccount | null {
  try {
    const raw = window.localStorage.getItem(ACCOUNT_CACHE_KEY[scope]);
    if (!raw) return null;
    const parsed = JSON.parse(raw) as PanelAccount;
    return parsed && typeof parsed === "object" ? parsed : null;
  } catch {
    return null;
  }
}

function writeCachedAccount(scope: PanelScope, account: PanelAccount | null) {
  if (!account) {
    window.localStorage.removeItem(ACCOUNT_CACHE_KEY[scope]);
    return;
  }
  window.localStorage.setItem(ACCOUNT_CACHE_KEY[scope], JSON.stringify(account));
}

async function loadAccount(scope: PanelScope): Promise<PanelAccount | null> {
  try {
    const account = await panelMe(scope);
    writeCachedAccount(scope, account);
    return account;
  } catch {
    if (getPanelToken(scope) || isLocalDevPanel()) {
      const cached = readCachedAccount(scope);
      if (cached) return cached;
    }
    if (isLocalDevPanel()) return DEV_STUB_ACCOUNT[scope];
    return null;
  }
}

export function PanelSessionProvider({ scope, children }: { scope: PanelScope; children: ReactNode }) {
  const [account, setAccountState] = useState<PanelAccount | null>(null);
  const [loading, setLoading] = useState(true);

  const setAccount = useCallback(
    (next: PanelAccount | null) => {
      setAccountState(next);
      writeCachedAccount(scope, next);
    },
    [scope],
  );

  const refresh = useCallback(async () => {
    setAccountState(await loadAccount(scope));
  }, [scope]);

  useEffect(() => {
    let alive = true;
    if (!getPanelToken(scope) && !isLocalDevPanel()) {
      setLoading(false);
      return;
    }
    loadAccount(scope)
      .then((a) => alive && setAccountState(a))
      .finally(() => alive && setLoading(false));
    return () => {
      alive = false;
    };
  }, [scope]);

  useEffect(() => {
    return onPanelAuthLoss((s) => {
      if (s !== scope) return;
      if (isLocalDevPanel()) {
        void loadAccount(scope).then(setAccountState);
        return;
      }
      setAccountState(null);
      writeCachedAccount(scope, null);
    });
  }, [scope]);

  const logout = useCallback(async () => {
    await panelLogout(scope);
    writeCachedAccount(scope, null);
    setAccountState(isLocalDevPanel() ? DEV_STUB_ACCOUNT[scope] : null);
  }, [scope]);

  const value = useMemo<PanelSessionState>(
    () => ({
      scope,
      account,
      loading,
      isAuthed: !!account || (isLocalDevPanel() && !loading),
      setAccount,
      refresh,
      logout,
    }),
    [scope, account, loading, setAccount, refresh, logout],
  );
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function usePanelSession(): PanelSessionState {
  const ctx = useContext(Ctx);
  if (!ctx) throw new Error("usePanelSession must be used within <PanelSessionProvider>");
  return ctx;
}
