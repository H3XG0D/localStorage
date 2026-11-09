import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { toast } from "sonner";
import {
  dashLiabilities,
  dashLive,
  dashOwner,
  dashVolumeCohorts,
  getExternalSummary,
  getFinanceOverview,
  getMisses,
  getOrders,
  getPartners,
  getStats,
  getStatsPromo,
  getTrafficStats,
  getCasinoStats,
  type AdminCasinoStats,
  type AdminOrder,
  type AdminTrafficStats,
  type Dict,
} from "@/panel/lib/adminApi";
import {
  isYmd,
  localRange,
  mskClock,
  ownerPeriodOf,
  previousRange,
  shiftIso,
  type AnalyticsTab,
  type PeriodPreset,
} from "@/panel/lib/analyticsPeriod";
import { getPanelToken, PanelApiError } from "@/panel/lib/panelApi";

const ORDER_PAGE = 200;
const ORDER_MAX_PAGES = 15;
const ORDER_CONCURRENCY = 4;
const PERIOD_TTL_MS = 60_000;
const GLOBAL_TTL_MS = 45_000;
const FAILED_RETRY_MS = 15_000;

export type SliceKey =
  | "owner"
  | "live"
  | "liab"
  | "stats"
  | "finance"
  | "promo"
  | "cohorts"
  | "prevCohorts"
  | "misses"
  | "traffic"
  | "partners"
  | "external"
  | "orders"
  | "prevOrders"
  | "casino";

const TAB_SLICES: Record<AnalyticsTab, SliceKey[]> = {
  overview: ["owner", "finance", "live", "liab"],
  finance: ["owner", "stats", "finance"],
  casino: ["casino", "finance"],
  traffic: ["traffic", "misses"],
  clients: ["owner", "cohorts", "prevCohorts", "orders", "prevOrders"],
  channels: ["owner", "partners", "promo", "external", "stats"],
};

const GLOBAL_SLICES = new Set<SliceKey>(["live", "liab", "partners", "external"]);

export type SliceError = { message: string; status: number };

/** Window the /dashboard/owner preset actually covered — it ignores explicit dates. */
export type OwnerWindow = { from: string; to: string; label: string; matchesRequest: boolean };

export type AnalyticsBundle = {
  from: string;
  to: string;
  owner: Dict | null;
  ownerWindow: OwnerWindow | null;
  live: Dict | null;
  liab: Dict | null;
  stats: Dict | null;
  finance: Dict | null;
  promo: Dict | null;
  cohorts: Dict | null;
  prevCohorts: Dict | null;
  misses: Dict | null;
  traffic: AdminTrafficStats | null;
  partners: Dict | Dict[] | null;
  external: Dict | null;
  orders: AdminOrder[];
  prevOrders: AdminOrder[];
  ordersTotal: number;
  truncated: boolean;
  casino: AdminCasinoStats | null;
  errors: Partial<Record<SliceKey, SliceError>>;
};

type CacheEntry = {
  bundle: AnalyticsBundle;
  loaded: Set<SliceKey>;
  failed: Set<SliceKey>;
  // When each failed slice last failed, so a retry is not blocked by `at` moving
  // forward on loads that only touched other slices.
  failedAt: Map<SliceKey, number>;
  at: number;
};

const periodCache = new Map<string, CacheEntry>();
const globalStore: {
  at: number;
  live: Dict | null;
  liab: Dict | null;
  partners: Dict | Dict[] | null;
  external: Dict | null;
} = { at: 0, live: null, liab: null, partners: null, external: null };

const emptyBundle = (from: string, to: string): AnalyticsBundle => ({
  from,
  to,
  owner: null,
  ownerWindow: null,
  live: globalStore.live,
  liab: globalStore.liab,
  stats: null,
  finance: null,
  promo: null,
  cohorts: null,
  prevCohorts: null,
  misses: null,
  traffic: null,
  partners: globalStore.partners,
  external: globalStore.external,
  orders: [],
  prevOrders: [],
  ordersTotal: 0,
  truncated: false,
  casino: null,
  errors: {},
});

function cacheKey(preset: PeriodPreset, from: string, to: string) {
  return `${preset}|${from}|${to}`;
}

function applyGlobals(
  bundle: AnalyticsBundle,
  loaded: Set<SliceKey>,
  failed?: Set<SliceKey>,
  failedAt?: Map<SliceKey, number>,
) {
  const put = (slice: SliceKey) => {
    loaded.add(slice);
    failed?.delete(slice);
    failedAt?.delete(slice);
    delete bundle.errors[slice];
  };
  if (globalStore.live) {
    bundle.live = globalStore.live;
    put("live");
  }
  if (globalStore.liab) {
    bundle.liab = globalStore.liab;
    put("liab");
  }
  if (globalStore.partners) {
    bundle.partners = globalStore.partners;
    put("partners");
  }
  if (globalStore.external) {
    bundle.external = globalStore.external;
    put("external");
  }
}

async function poolMap<T, R>(items: T[], concurrency: number, fn: (item: T) => Promise<R>): Promise<R[]> {
  const out: R[] = new Array(items.length);
  let cursor = 0;
  const workers = Array.from({ length: Math.min(concurrency, items.length) }, async () => {
    while (cursor < items.length) {
      const index = cursor;
      cursor += 1;
      out[index] = await fn(items[index]);
    }
  });
  await Promise.all(workers);
  return out;
}

async function loadOrders(from: string, to: string): Promise<{ orders: AdminOrder[]; total: number; truncated: boolean }> {
  const fetchFrom = isYmd(from) ? shiftIso(from, -1) : from;
  const fetchTo = isYmd(to) ? shiftIso(to, 1) : to;
  const first = await getOrders({
    limit: ORDER_PAGE,
    offset: 0,
    date_from: fetchFrom,
    date_to: fetchTo,
  });
  const total = first.total ?? 0;
  const collected: AdminOrder[] = [...(first.orders ?? [])];
  const max = Math.min(total, ORDER_PAGE * ORDER_MAX_PAGES);
  const offsets: number[] = [];
  for (let offset = ORDER_PAGE; offset < max; offset += ORDER_PAGE) offsets.push(offset);
  if (offsets.length) {
    const pages = await poolMap(offsets, ORDER_CONCURRENCY, (offset) =>
      getOrders({
        limit: ORDER_PAGE,
        offset,
        date_from: fetchFrom,
        date_to: fetchTo,
      }),
    );
    for (const chunk of pages) collected.push(...(chunk.orders ?? []));
  }
  const truncated = collected.length < total && collected.length >= ORDER_PAGE * ORDER_MAX_PAGES;
  const inWindow = collected.filter((o) => {
    const day = mskClock(String(o.created_at || ""))?.ymd ?? "";
    return !from || !to || (day >= from && day <= to);
  });
  return { orders: inWindow, total: truncated ? total : inWindow.length, truncated };
}

function periodRange(preset: PeriodPreset, customFrom: string, customTo: string) {
  if (preset === "custom") return { from: customFrom, to: customTo };
  return localRange(preset);
}

export function useAnalyticsData(preset: PeriodPreset, customFrom: string, customTo: string, tab: AnalyticsTab) {
  const [bundle, setBundle] = useState<AnalyticsBundle>(() => {
    const r = periodRange(preset === "custom" ? "week" : preset, customFrom, customTo);
    return emptyBundle(r.from, r.to);
  });
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [stale, setStale] = useState(false);
  const [updatedAt, setUpdatedAt] = useState<Date | null>(null);
  const gen = useRef(0);
  const loadRef = useRef<((opts?: { force?: boolean }) => Promise<void>) | null>(null);

  const load = useCallback(async (opts?: { force?: boolean }) => {
    const force = Boolean(opts?.force);
    const range = periodRange(preset, customFrom, customTo);
    const from = range.from;
    const to = range.to;
    if (!isYmd(from) || !isYmd(to) || from > to) {
      toast.error("Проверьте даты периода");
      setLoading(false);
      setRefreshing(false);
      return;
    }

    const key = cacheKey(preset, from, to);
    const needed = TAB_SLICES[tab];
    const existing = periodCache.get(key);
    const now = Date.now();
    const globalsFresh = now - globalStore.at < GLOBAL_TTL_MS && globalStore.at > 0;
    if (existing) applyGlobals(existing.bundle, existing.loaded, existing.failed, existing.failedAt);
    // A failed slice counts as settled: the tab renders its error banner instead of
    // zeros. But it must come back on its own — a single 401 (session not ready yet)
    // or timeout should not freeze the tab until a full page reload.
    const settled = (entry: CacheEntry, slice: SliceKey) => entry.loaded.has(slice) || entry.failed.has(slice);
    const retryable = (entry: CacheEntry, slice: SliceKey) =>
      entry.failed.has(slice) && now - (entry.failedAt.get(slice) ?? 0) >= FAILED_RETRY_MS;
    const haveTab = existing ? needed.every((slice) => settled(existing, slice)) : false;
    const retryWanted = Boolean(existing && needed.some((slice) => retryable(existing, slice)));
    const periodFresh = Boolean(existing && now - existing.at < PERIOD_TTL_MS);
    const needsGlobal = needed.some((slice) => GLOBAL_SLICES.has(slice));
    const fresh = Boolean(
      existing && haveTab && periodFresh && (!needsGlobal || globalsFresh) && !retryWanted && !force,
    );

    if (existing) {
      setBundle(existing.bundle);
      setLoading(!haveTab);
      if (fresh) {
        setRefreshing(false);
        setUpdatedAt(new Date(existing.at));
        return;
      }
      setRefreshing(haveTab);
    } else {
      const seed = emptyBundle(from, to);
      const loaded = new Set<SliceKey>();
      applyGlobals(seed, loaded);
      periodCache.set(key, { bundle: seed, loaded, failed: new Set(), failedAt: new Map(), at: 0 });
      setBundle(seed);
      setLoading(true);
      setRefreshing(false);
    }

    const entry = periodCache.get(key)!;
    const want = needed.filter((slice) => {
      if (force) return true;
      if (!settled(entry, slice)) return true;
      if (retryable(entry, slice)) return true;
      if (GLOBAL_SLICES.has(slice) && !globalsFresh) return true;
      if (existing && now - existing.at >= PERIOD_TTL_MS) return true;
      return false;
    });
    if (!want.length) {
      setLoading(!needed.every((slice) => settled(entry, slice)));
      setRefreshing(false);
      return;
    }

    const my = ++gen.current;
    const stillMine = () => my === gen.current;

    const jobs: Promise<void>[] = [];
    const failed: string[] = [];

    const ok = (slice: SliceKey) => {
      entry.failed.delete(slice);
      entry.failedAt.delete(slice);
      delete entry.bundle.errors[slice];
      entry.loaded.add(slice);
    };

    const run = (slice: SliceKey, task: () => Promise<void>) => {
      if (!want.includes(slice)) return;
      jobs.push(
        task().catch((err) => {
          if (!stillMine()) return;
          failed.push(slice);
          entry.bundle.errors[slice] = {
            message: err instanceof PanelApiError ? err.message : "Данные временно недоступны",
            status: err instanceof PanelApiError ? err.status : 0,
          };
          entry.loaded.delete(slice);
          entry.failed.add(slice);
          // 401 without a payload means panelApi short-circuited before any request:
          // the bearer was not in place yet. Allow the next load to retry at once.
          const noSession = err instanceof PanelApiError && err.status === 401 && err.payload === null;
          entry.failedAt.set(slice, noSession ? 0 : Date.now());
        }),
      );
    };

    run("owner", async () => {
      const owner = await dashOwner(ownerPeriodOf(preset));
      if (!stillMine()) return;
      entry.bundle.owner = owner;
      // /dashboard/owner takes only a preset and resolves its own window (week =
      // Monday..today). Keep the requested window intact and expose the owner one
      // separately so its cards can say which dates they really cover.
      const period = (owner.period ?? {}) as Dict;
      const current = (period.current ?? {}) as Dict;
      const oFrom = String(current.from ?? "").slice(0, 10);
      const oTo = String(current.to ?? "").slice(0, 10);
      entry.bundle.ownerWindow =
        isYmd(oFrom) && isYmd(oTo)
          ? { from: oFrom, to: oTo, label: String(period.label ?? ""), matchesRequest: oFrom === from && oTo === to }
          : null;
      ok("owner");
    });

    run("live", async () => {
      const live = await dashLive();
      if (!stillMine()) return;
      entry.bundle.live = live;
      globalStore.live = live;
      globalStore.at = Date.now();
      ok("live");
    });

    run("liab", async () => {
      const liab = await dashLiabilities();
      if (!stillMine()) return;
      entry.bundle.liab = liab;
      globalStore.liab = liab;
      globalStore.at = Date.now();
      ok("liab");
    });

    run("stats", async () => {
      const stats = await getStats(from, to);
      if (!stillMine()) return;
      entry.bundle.stats = stats;
      ok("stats");
    });

    run("finance", async () => {
      const finance = await getFinanceOverview(from, to);
      if (!stillMine()) return;
      entry.bundle.finance = finance;
      ok("finance");
    });

    run("promo", async () => {
      const promo = await getStatsPromo(from, to);
      if (!stillMine()) return;
      entry.bundle.promo = promo;
      ok("promo");
    });

    run("cohorts", async () => {
      const cohorts = await dashVolumeCohorts("lifetime", from, to);
      if (!stillMine()) return;
      entry.bundle.cohorts = cohorts;
      ok("cohorts");
    });

    run("prevCohorts", async () => {
      const prev = previousRange(from, to);
      const cohorts = await dashVolumeCohorts("lifetime", prev.from, prev.to);
      if (!stillMine()) return;
      entry.bundle.prevCohorts = cohorts;
      ok("prevCohorts");
    });

    run("traffic", async () => {
      const traffic = await getTrafficStats(from, to);
      if (!stillMine()) return;
      entry.bundle.traffic = traffic;
      ok("traffic");
    });

    run("misses", async () => {
      const misses = await getMisses(from, to);
      if (!stillMine()) return;
      entry.bundle.misses = misses;
      ok("misses");
    });

    run("partners", async () => {
      const partners = await getPartners();
      if (!stillMine()) return;
      entry.bundle.partners = partners;
      globalStore.partners = partners;
      globalStore.at = Date.now();
      ok("partners");
    });

    run("external", async () => {
      const external = await getExternalSummary();
      if (!stillMine()) return;
      entry.bundle.external = external;
      globalStore.external = external;
      globalStore.at = Date.now();
      ok("external");
    });

    run("orders", async () => {
      const pack = await loadOrders(from, to);
      if (!stillMine()) return;
      entry.bundle.orders = pack.orders;
      entry.bundle.ordersTotal = pack.total;
      entry.bundle.truncated = pack.truncated;
      ok("orders");
    });

    run("prevOrders", async () => {
      const prev = previousRange(from, to);
      const pack = await loadOrders(prev.from, prev.to);
      if (!stillMine()) return;
      entry.bundle.prevOrders = pack.orders;
      ok("prevOrders");
    });

    run("casino", async () => {
      const casino = await getCasinoStats(from, to);
      if (!stillMine()) return;
      entry.bundle.casino = casino;
      ok("casino");
    });

    await Promise.all(jobs);
    if (!stillMine()) return;

    entry.at = Date.now();
    periodCache.set(key, {
      bundle: entry.bundle,
      loaded: new Set(entry.loaded),
      failed: new Set(entry.failed),
      failedAt: new Map(entry.failedAt),
      at: entry.at,
    });
    setBundle({ ...entry.bundle, errors: { ...entry.bundle.errors } });
    setStale(failed.length > 0);
    setUpdatedAt(new Date(entry.at));
    setLoading(!needed.every((slice) => settled(entry, slice)));
    setRefreshing(false);

    // Slices that gave up before the bearer existed: retry now that it does,
    // instead of waiting for a tab switch or a manual refresh.
    const sessionMisses = failed.filter((slice) => entry.failedAt.get(slice as SliceKey) === 0);
    if (sessionMisses.length && getPanelToken("admin")) {
      window.setTimeout(() => {
        if (stillMine()) void loadRef.current?.();
      }, 400);
    }
  }, [preset, customFrom, customTo, tab]);

  loadRef.current = load;

  useEffect(() => {
    void load();
  }, [load]);

  const meta = useMemo(
    () => ({
      loading,
      refreshing,
      stale,
      updatedAt,
      reload: () => load({ force: true }),
    }),
    [loading, refreshing, stale, updatedAt, load],
  );

  return { ...bundle, ...meta };
}
