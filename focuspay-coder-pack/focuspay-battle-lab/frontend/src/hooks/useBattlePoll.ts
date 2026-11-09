import { useCallback, useEffect, useRef, useState } from "react";
import type { CurrentRound } from "../api/client";
import { fetchCurrent } from "../api/client";

export function useBattlePoll(intervalMs = 2000) {
  const [data, setData] = useState<CurrentRound | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const prevRoundId = useRef<number | null>(null);
  const [justResolved, setJustResolved] = useState<{
    roundId: number;
    delta: number | null;
  } | null>(null);

  const refresh = useCallback(async () => {
    try {
      const current = await fetchCurrent();
      if (prevRoundId.current !== null && current.round_id !== prevRoundId.current) {
        setJustResolved({ roundId: prevRoundId.current, delta: null });
      }
      prevRoundId.current = current.round_id;
      setData(current);
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "load failed");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    refresh();
    const id = setInterval(refresh, intervalMs);
    return () => clearInterval(id);
  }, [refresh, intervalMs]);

  const clearResolved = useCallback(() => setJustResolved(null), []);

  const setResultDelta = useCallback((delta: number) => {
    setJustResolved((prev) => (prev ? { ...prev, delta } : null));
  }, []);

  return { data, error, loading, refresh, justResolved, clearResolved, setResultDelta };
}
