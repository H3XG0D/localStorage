import { useCallback, useEffect, useState } from "react";
import { toast } from "sonner";
import { PanelApiError } from "@/panel/lib/panelApi";
import { getSecurityBans, getSecurityEvents, getSecurityStats, unbanSecurityEvent, unbanSecurityIp, type Dict } from "@/panel/lib/adminApi";
import { Badge, Button, Card, Field, Input, Kpi, PageHeader, Table, type Column } from "@/panel/ui/primitives";

function num(v: unknown) {
  return v == null ? "—" : String(v);
}
function dt(v: unknown) {
  if (!v) return "—";
  const d = new Date(String(v));
  return isNaN(d.getTime()) ? String(v) : d.toLocaleString("ru-RU");
}

const BAN_THREATS = new Set([
  "auth_bruteforce",
  "auth_fail_admin",
  "webhook_ip_reject",
]);

function eventIp(row: Dict) {
  return String(row.ip_address ?? row.ip ?? "").trim();
}

function eventId(row: Dict) {
  const extra = row.extra && typeof row.extra === "object" ? (row.extra as Dict) : null;
  return String(extra?.request_id ?? row.id ?? "").trim();
}

export function AdminSecurity() {
  const [hours, setHours] = useState(24);
  const [stats, setStats] = useState<Dict | null>(null);
  const [events, setEvents] = useState<Dict[]>([]);
  const [banThreatEvents, setBanThreatEvents] = useState<Dict[]>([]);
  const [bans, setBans] = useState<Dict[]>([]);
  const [loading, setLoading] = useState(true);
  const [unbanBusy, setUnbanBusy] = useState("");

  const [ip, setIp] = useState("");
  const [threatType, setThreatType] = useState("");
  const [threatsOnly, setThreatsOnly] = useState(false);
  const [bruteOnly, setBruteOnly] = useState(false);
  const [limit, setLimit] = useState("50");

  const loadStats = useCallback(() => {
    getSecurityStats(hours)
      .then(setStats)
      .catch((e) => toast.error(e instanceof PanelApiError ? e.message : "Ошибка stats"));
  }, [hours]);

  const loadBans = useCallback(() => {
    getSecurityBans()
      .then((r) => setBans(Array.isArray(r?.items) ? r.items : []))
      .catch(() => setBans([]));
  }, []);

  const loadBanReports = useCallback(() => {
    getSecurityEvents({ threat_type: "auth_bruteforce", limit: 20 })
      .then((r) => {
        const list = Array.isArray(r) ? r : r.events || [];
        setBanThreatEvents(list.filter((e: Dict) => eventIp(e) || eventId(e)));
      })
      .catch(() => setBanThreatEvents([]));
  }, []);

  const loadEvents = useCallback(() => {
    setLoading(true);
    getSecurityEvents({
      ip: ip.trim() || undefined,
      threat_type: threatType.trim() || undefined,
      threats_only: threatsOnly || bruteOnly || undefined,
      limit: Number(limit) || 50,
    })
      .then((r) => {
        let list = Array.isArray(r) ? r : (r.events || []);
        if (bruteOnly) {
          const set = new Set([
            "auth_bruteforce",
            "auth_fail_admin",
            "admin_probe",
            "operator_probe",
            "scanner",
            "webhook_ip_reject",
          ]);
          list = list.filter((e: Dict) => set.has(String(e.threat_type || "")));
        }
        setEvents(list);
      })
      .catch((e) => toast.error(e instanceof PanelApiError ? e.message : "Ошибка"))
      .finally(() => setLoading(false));
  }, [ip, threatType, threatsOnly, bruteOnly, limit]);

  useEffect(() => {
    loadStats();
    loadEvents();
    loadBans();
    loadBanReports();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [hours]);

  const doUnban = (ip: string, eid?: string) => {
    const target = ip.trim();
    const key = target || eid || "";
    if (!key || unbanBusy) return;
    setUnbanBusy(key);
    const req = target ? unbanSecurityIp(target) : unbanSecurityEvent(String(eid));
    req
      .then((r) => {
        const shown = String(r?.ip || target || eid);
        toast.success(r?.was_banned ? `Разбанен ${shown}` : `${shown} уже не в бане`);
        loadBans();
        loadBanReports();
      })
      .catch((e) => toast.error(e instanceof PanelApiError ? e.message : "Не удалось разбанить"))
      .finally(() => setUnbanBusy(""));
  };

  const UnbanBtn = ({ ip, eid }: { ip: string; eid?: string }) => {
    const key = ip || eid || "";
    if (!key) return null;
    return (
      <Button
        type="button"
        size="sm"
        variant="danger"
        disabled={!!unbanBusy}
        onClick={(ev) => {
          ev.stopPropagation();
          doUnban(ip, eid);
        }}
      >
        {unbanBusy === key ? "…" : "Разбанить"}
      </Button>
    );
  };

  const top = (stats?.top_ips ?? []) as Dict[];
  const byType = (stats?.by_threat_type ?? []) as Dict[];
  const topPaths = (stats?.top_paths ?? []) as Dict[];
  const topLabel = top.length ? String(top[0].ip ?? "—") : "—";

  const cols: Column<Dict>[] = [
    { key: "created_at", label: "Время", render: (r) => dt(r.created_at) },
    {
      key: "ip_address",
      label: "IP",
      width: "140px",
      render: (r) => (
        <button
          type="button"
          className="font-mono text-[var(--accent)] underline-offset-2 hover:underline"
          onClick={() => setIp(String(r.ip_address ?? r.ip ?? ""))}
        >
          {num(r.ip_address ?? r.ip)}
        </button>
      ),
    },
    { key: "method", label: "Метод", width: "80px", render: (r) => num(r.method) },
    {
      key: "path",
      label: "Путь",
      render: (r) => (
        <span className="block max-w-[240px] truncate" title={String(r.path ?? "")}>
          {num(r.path)}
        </span>
      ),
    },
    { key: "status_code", label: "Код", width: "70px", align: "right", render: (r) => num(r.status_code) },
    { key: "zone", label: "Зона", width: "90px", render: (r) => num(r.zone) },
    { key: "country_code", label: "Страна", width: "80px", render: (r) => num(r.country_code) },
    { key: "city", label: "Город", width: "110px", render: (r) => num(r.city) },
    {
      key: "threat_type",
      label: "Угроза",
      width: "120px",
      render: (r) => (r.threat_type ? <Badge tone="red">{String(r.threat_type)}</Badge> : "—"),
    },
    { key: "threat_score", label: "Score", width: "80px", align: "right", render: (r) => num(r.threat_score) },
    {
      key: "unban",
      label: "",
      width: "120px",
      render: (r) => <UnbanBtn ip={eventIp(r)} eid={eventId(r)} />,
    },
  ];

  return (
    <>
      <PageHeader
        title="Безопасность"
        subtitle={`Сводка ${hours}ч · события доступа и угрозы`}
        actions={
          <div className="flex gap-2">
            <Button variant="secondary" onClick={() => setHours(24)}>
              24ч
            </Button>
            <Button variant="secondary" onClick={() => setHours(168)}>
              7д
            </Button>
          </div>
        }
      />

      <div className="grid grid-cols-4 gap-4 max-lg:grid-cols-2 max-[520px]:grid-cols-1">
        <Kpi label="Запросов" value={num(stats?.total_requests ?? stats?.total_events)} />
        <Kpi label="Угроз" value={num(stats?.threat_events ?? stats?.threats)} />
        <Kpi label="Брут/probe" value={num(stats?.brute_probe_events)} />
        <Kpi label="Топ IP" value={<span className="font-mono text-base">{topLabel}</span>} />
      </div>

      <Card>
        <div className="mb-2 text-[13px] font-medium">Активные баны (Redis)</div>
        {bans.length === 0 ? (
          <div className="text-[13px] text-[var(--text-secondary)]">Сейчас никто не забанен</div>
        ) : (
          <ul className="m-0 list-none space-y-2 p-0">
            {bans.map((b) => {
              const banIp = String(b.ip ?? "");
              return (
                <li key={banIp} className="flex flex-wrap items-center justify-between gap-2 rounded border border-[var(--border)] px-3 py-2">
                  <div className="min-w-0 font-mono text-[13px]">
                    <div>{banIp}</div>
                    <div className="text-[11px] text-[var(--text-muted)]">
                      {b.reason ? String(b.reason) : "ban"}
                      {b.ttl_sec != null ? ` · TTL ${num(b.ttl_sec)}с` : ""}
                    </div>
                  </div>
                  <UnbanBtn ip={banIp} />
                </li>
              );
            })}
          </ul>
        )}
      </Card>

      {banThreatEvents.length > 0 && (
        <Card>
          <div className="mb-2 text-[13px] font-medium">Бан по отчётам</div>
          <div className="grid gap-3 md:grid-cols-2">
            {banThreatEvents.slice(0, 8).map((e) => {
              const eip = eventIp(e);
              const eid = eventId(e);
              const loc = [e.city, e.country_code].filter(Boolean).join(", ");
              return (
                <div key={eid || `${eip}-${e.created_at}`} className="rounded border border-[var(--border)] p-3 text-[13px] leading-6">
                  <div className="flex items-start justify-between gap-2">
                    <div className="font-medium">🚨 Безопасность: {String(e.threat_type)}</div>
                    <UnbanBtn ip={eip} eid={eid} />
                  </div>
                  {eid ? <div className="font-mono text-[12px] text-[var(--text-muted)]">🆔 {eid}</div> : null}
                  <div className="font-mono">
                    🌐 {eip}
                    {loc ? ` · ${loc}` : ""}
                  </div>
                  <div>
                    📍 {num(e.method)} {num(e.path)}
                  </div>
                  <div>↩️ HTTP {num(e.status_code)}</div>
                  {e.zone ? <div>Зона: {num(e.zone)}</div> : null}
                </div>
              );
            })}
          </div>
        </Card>
      )}

      <div className="grid grid-cols-2 gap-4 max-lg:grid-cols-1">
        <Card>
          <div className="mb-2 text-[13px] font-medium">По типам угроз</div>
          <ul className="m-0 list-none space-y-1 p-0 text-[13px]">
            {byType.length === 0 && <li className="text-[var(--text-secondary)]">Нет данных</li>}
            {byType.map((t) => (
              <li key={String(t.threat_type)} className="flex justify-between gap-2">
                <Badge tone="red">{String(t.threat_type)}</Badge>
                <span className="font-mono">{num(t.count)}</span>
              </li>
            ))}
          </ul>
        </Card>
        <Card>
          <div className="mb-2 text-[13px] font-medium">Топ путей (угрозы)</div>
          <ul className="m-0 list-none space-y-1 p-0 font-mono text-[12px]">
            {topPaths.length === 0 && <li className="text-[var(--text-secondary)]">Нет данных</li>}
            {topPaths.map((p) => (
              <li key={String(p.path)} className="flex justify-between gap-2">
                <span className="truncate" title={String(p.path)}>
                  {String(p.path)}
                </span>
                <span>{num(p.count)}</span>
              </li>
            ))}
          </ul>
        </Card>
      </div>

      <Card>
        <div className="grid grid-cols-4 items-end gap-3 max-lg:grid-cols-2 max-[520px]:grid-cols-1">
          <Field label="IP">
            <Input value={ip} onChange={(e) => setIp(e.target.value)} className="font-mono" />
          </Field>
          <Field label="Тип угрозы">
            <Input value={threatType} onChange={(e) => setThreatType(e.target.value)} />
          </Field>
          <Field label="Лимит">
            <Input inputMode="numeric" value={limit} onChange={(e) => setLimit(e.target.value)} className="font-mono" />
          </Field>
          <div className="flex flex-wrap items-center gap-3">
            <label className="flex items-center gap-2 text-[13px]">
              <input type="checkbox" checked={threatsOnly} onChange={(e) => setThreatsOnly(e.target.checked)} />
              <span>Только угрозы</span>
            </label>
            <label className="flex items-center gap-2 text-[13px]">
              <input type="checkbox" checked={bruteOnly} onChange={(e) => setBruteOnly(e.target.checked)} />
              <span>Брут/probe</span>
            </label>
            <Button variant="primary" onClick={loadEvents} disabled={loading}>
              Обновить
            </Button>
          </div>
        </div>
      </Card>

      <Card>
        <div className="mb-2 text-[13px] font-medium">Топ IP</div>
        <ul className="mb-4 flex flex-wrap gap-2 p-0 list-none">
          {top.slice(0, 10).map((t) => (
            <li key={String(t.ip)} className="flex items-center gap-1">
              <button
                type="button"
                className="rounded border border-[var(--border)] px-2 py-1 font-mono text-[12px]"
                onClick={() => setIp(String(t.ip))}
              >
                {String(t.ip)} · {num(t.count)}
                {t.last_threat ? ` · ${t.last_threat}` : ""}
              </button>
              {BAN_THREATS.has(String(t.last_threat || "")) ? <UnbanBtn ip={String(t.ip)} /> : null}
            </li>
          ))}
        </ul>
        <Table columns={cols} rows={events} empty={loading ? "Загрузка…" : "Пусто"} />
      </Card>
    </>
  );
}
