// Subscribe to the server's SSE stream for a given order. Calls `onEvent` when
// the server pushes a chat/status event. Returns whether the live stream is
// currently connected — callers use this to slow their polling fallback right
// down (but never fully off), so the UI stays correct even if SSE drops.
import { useEffect, useRef, useState } from "react";
import { API_BASE } from "@/lib/api";

export interface LiveEvent {
  type: string; // "chat" | "status" | "connected" | ...
  order_id?: string;
  status?: string;
  [key: string]: unknown;
}

export function useLiveEvents(orderId: string | undefined, onEvent: (e: LiveEvent) => void): { live: boolean } {
  const [live, setLive] = useState(false);
  const cbRef = useRef(onEvent);
  cbRef.current = onEvent;

  useEffect(() => {
    if (!orderId || typeof EventSource === "undefined") return;
    const url = `${API_BASE}/public/chat/events?order_id=${encodeURIComponent(orderId)}`;
    let es: EventSource | null = null;
    let closed = false;

    try {
      es = new EventSource(url, { withCredentials: true });
    } catch {
      return; // SSE unavailable → caller keeps polling
    }

    es.onopen = () => !closed && setLive(true);
    es.onmessage = (ev) => {
      try {
        const data = JSON.parse(ev.data) as LiveEvent;
        if (data.type === "connected") {
          setLive(true);
          return;
        }
        cbRef.current(data);
      } catch {
        /* ignore malformed frames */
      }
    };
    // On error the browser auto-reconnects; mark not-live so polling speeds back up.
    es.onerror = () => !closed && setLive(false);

    return () => {
      closed = true;
      setLive(false);
      es?.close();
    };
  }, [orderId]);

  return { live };
}
