// Poll while the panel scope still has a bearer token. Stops on 401 / auth loss
// so expired sessions do not hammer /api/operator/* and trip operator_probe.
import { useEffect, useRef } from "react";
import { isLocalDevPanel } from "@/panel/lib/devHost";
import { getPanelToken, onPanelAuthLoss, type PanelScope } from "@/panel/lib/panelApi";

function canPoll(scope: PanelScope): boolean {
  if (getPanelToken(scope)) return true;
  // Local skip-login has no JWT in localStorage; Vite snapshot/proxy still serve /api.
  return isLocalDevPanel();
}

export function useAuthedPoll(
  scope: PanelScope,
  tick: () => void | Promise<void>,
  intervalMs: number,
  deps: unknown[] = [],
) {
  const tickRef = useRef(tick);
  tickRef.current = tick;
  const busyRef = useRef(false);

  useEffect(() => {
    let stopped = false;
    let timer: number | null = null;

    const run = () => {
      if (stopped) return;
      if (!canPoll(scope)) {
        stopped = true;
        if (timer != null) window.clearInterval(timer);
        return;
      }
      // Skip overlapping ticks so a slow GET cannot pile up requests.
      if (busyRef.current) return;
      busyRef.current = true;
      void Promise.resolve()
        .then(() => tickRef.current())
        .finally(() => {
          busyRef.current = false;
        });
    };

    run();
    timer = window.setInterval(run, intervalMs);
    const unsub = onPanelAuthLoss((s) => {
      if (s !== scope) return;
      if (isLocalDevPanel()) return;
      stopped = true;
      if (timer != null) window.clearInterval(timer);
    });

    return () => {
      stopped = true;
      if (timer != null) window.clearInterval(timer);
      unsub();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps -- caller passes explicit deps
  }, [scope, intervalMs, ...deps]);
}
