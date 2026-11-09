import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { Check, Copy, Play, X } from "lucide-react";
import { toast } from "sonner";
import { PanelApiError } from "@/panel/lib/panelApi";
import {
  aiApproveTask,
  aiDoneTask,
  aiGetTask,
  aiListTasks,
  aiRegressionLatest,
  aiRegressionStart,
  aiRejectTask,
  aiSelfcheckLatest,
  aiTaskAttachmentUrl,
  type AdminAiTask,
  type AiRegressionReport,
  type AiRegressionRun,
  type AiSelfcheckRun,
} from "@/panel/lib/adminApi";
import {
  AI_TASKS_HINT,
  AI_TASKS_PATH,
  buildRegressionPayload,
  startConsoleNetworkCapture,
} from "@/panel/lib/aiTasksRegression";
import {
  isCheckStatusFinding,
  isSelfcheckAlarm,
  selfcheckBadgeTone,
} from "@/panel/lib/aiTasksSelfcheck";
import { formatTaskAge } from "@/panel/lib/taskAge";
import { getPanelToken } from "@/panel/lib/panelApi";
import { useAuthedPoll } from "@/panel/lib/useAuthedPoll";
import { Badge, Button, Card, PageHeader, Select, type BadgeTone } from "@/panel/ui/primitives";

const statusTone: Record<string, BadgeTone> = {
  review: "yellow",
  approved: "green",
  rejected: "red",
  done: "purple",
  drafting: "blue",
  passed: "green",
  failed: "red",
  running: "blue",
  queued: "default",
  error: "red",
  unavailable: "red",
  skipped: "red",
};

/** Queue refresh while the admin stays on /x8/ai-tasks. */
const AI_TASKS_POLL_MS = 8000;

export function AdminAiTasks() {
  const [params, setParams] = useSearchParams();
  const focusId = Number(params.get("id") || 0) || null;
  const action = params.get("action");
  const [status, setStatus] = useState(params.get("status") || "review");
  const [tasks, setTasks] = useState<AdminAiTask[]>([]);
  const [selected, setSelected] = useState<AdminAiTask | null>(null);
  const [busy, setBusy] = useState(false);
  const [rejectReason, setRejectReason] = useState("");
  const [regBusy, setRegBusy] = useState(false);
  const [regRun, setRegRun] = useState<AiRegressionRun | null>(null);
  const [regReport, setRegReport] = useState<AiRegressionReport | null>(null);
  const [scRun, setScRun] = useState<AiSelfcheckRun | null>(null);
  /** After first successful fetch, poll errors stay quiet so the list is not wiped. */
  const loadedOnceRef = useRef(false);
  const [, setAgeTick] = useState(0);

  useEffect(() => {
    const id = window.setInterval(() => setAgeTick((n) => n + 1), 30000);
    return () => window.clearInterval(id);
  }, []);

  const load = useCallback(async () => {
    try {
      const r = await aiListTasks(status);
      setTasks(r.tasks || []);
      loadedOnceRef.current = true;
    } catch (e) {
      if (!loadedOnceRef.current) {
        toast.error(e instanceof PanelApiError ? e.message : "Ошибка");
      }
    }
  }, [status]);

  const loadRegression = useCallback(async () => {
    try {
      const r = await aiRegressionLatest();
      setRegRun(r.run);
      setRegReport(r.run?.report || null);
    } catch {
      /* quiet — regression is optional */
    }
  }, []);

  const loadSelfcheck = useCallback(async () => {
    try {
      const r = await aiSelfcheckLatest();
      setScRun(r.run || null);
    } catch {
      /* quiet — self-check card is optional until first run */
    }
  }, []);

  useEffect(() => {
    loadedOnceRef.current = false;
  }, [status]);

  useAuthedPoll("admin", load, AI_TASKS_POLL_MS, [load]);
  useAuthedPoll("admin", loadSelfcheck, AI_TASKS_POLL_MS, [loadSelfcheck]);
  useEffect(() => {
    void loadRegression();
  }, [loadRegression]);

  useEffect(() => {
    if (!focusId) return;
    aiGetTask(focusId)
      .then(async (t) => {
        setSelected(t);
        if (action === "approve" && t.status === "review") {
          setBusy(true);
          try {
            const u = await aiApproveTask(t.id);
            setSelected(u);
            toast.success("Approved — скопируйте промпт в Cursor");
            await load();
          } catch (e) {
            toast.error(e instanceof PanelApiError ? e.message : "Ошибка approve");
          } finally {
            setBusy(false);
            setParams((p) => {
              const n = new URLSearchParams(p);
              n.delete("action");
              return n;
            });
          }
        }
      })
      .catch(() => {});
  }, [focusId, action, load, setParams]);

  const sorted = useMemo(() => tasks, [tasks]);

  async function approve(id: number) {
    setBusy(true);
    try {
      const t = await aiApproveTask(id);
      setSelected(t);
      toast.success("Approved");
      await load();
    } catch (e) {
      toast.error(e instanceof PanelApiError ? e.message : "Ошибка");
    } finally {
      setBusy(false);
    }
  }

  async function reject(id: number) {
    setBusy(true);
    try {
      const t = await aiRejectTask(id, rejectReason || undefined);
      setSelected(t);
      setRejectReason("");
      toast.success("Rejected");
      await load();
    } catch (e) {
      toast.error(e instanceof PanelApiError ? e.message : "Ошибка");
    } finally {
      setBusy(false);
    }
  }

  async function done(id: number) {
    setBusy(true);
    try {
      const t = await aiDoneTask(id);
      setSelected(t);
      toast.success("Done — записано в learning log");
      await load();
    } catch (e) {
      toast.error(e instanceof PanelApiError ? e.message : "Ошибка");
    } finally {
      setBusy(false);
    }
  }

  async function runRegression() {
    setRegBusy(true);
    const capture = startConsoleNetworkCapture();
    try {
      // Safe UI walk only: filter + open first row (no Approve/Reject/Done).
      const prev = status;
      if (status !== "review") setStatus("review");
      await load();
      const first = (await aiListTasks("review")).tasks?.[0];
      if (first) setSelected(first);
      await new Promise((r) => setTimeout(r, 400));
      const payload = buildRegressionPayload({
        statusFilter: "review",
        selectedTaskId: first?.id ?? selected?.id,
        consoleErrors: capture.errors,
        networkErrors: capture.network,
        // PageHeader title on this screen — not browser tab (often "FocusPay · Панель").
        pageTitle: "AI · задачи от операторов",
        version: undefined,
      });
      const r = await aiRegressionStart(payload);
      setRegRun(r.run);
      setRegReport(r.run?.report || null);
      toast.success(
        r.run?.status === "passed"
          ? "UI-регрессия: passed"
          : `UI-регрессия: ${r.run?.status || "done"}`,
      );
      if (prev !== "review") setStatus(prev);
    } catch (e) {
      toast.error(e instanceof PanelApiError ? e.message : "Ошибка регрессии");
    } finally {
      capture.dispose();
      setRegBusy(false);
    }
  }

  return (
    <>
      <PageHeader
        title="AI · задачи от операторов"
        subtitle="Approve отдаёт промпт для Cursor. Без автокоммита и без деплоя. UI-регрессия — только read-only."
        actions={
          <div className="flex flex-wrap items-center gap-2">
            <Button size="sm" disabled={regBusy} onClick={() => void runRegression()}>
              <Play className="size-3.5" /> {regBusy ? "Регрессия…" : "UI-регрессия"}
            </Button>
            <Select value={status} onChange={(e) => setStatus(e.target.value)} className="w-auto">
              <option value="review">review</option>
              <option value="approved">approved</option>
              <option value="rejected">rejected</option>
              <option value="done">done</option>
              <option value="all">all</option>
            </Select>
          </div>
        }
      />

      {scRun && (
        <Card
          className={
            scRun.alarm || isSelfcheckAlarm(scRun.job_status) || (scRun.checks || []).some((c) => isSelfcheckAlarm(c.status))
              ? "mb-4 space-y-2 border-[var(--red)]/40 bg-[var(--red-bg)]/30 p-3"
              : "mb-4 space-y-2 p-3"
          }
        >
          <div className="flex flex-wrap items-center gap-2">
            <span className="text-[11px] font-semibold uppercase text-[var(--text-muted)]">
              SAST self-check · {AI_TASKS_PATH}
            </span>
            {scRun.job_status && (
              <Badge tone={selfcheckBadgeTone(scRun.job_status)}>{String(scRun.job_status)}</Badge>
            )}
            <span className="text-[11px] text-[var(--text-muted)]">
              exit {scRun.exit_code ?? "—"}
              {" · "}
              {scRun.finished_at || scRun.started_at || "—"}
              {scRun.artifact_rel ? ` · ${scRun.artifact_rel}` : ""}
              {" · "}
              {AI_TASKS_HINT}
            </span>
          </div>
          <ul className="m-0 max-h-48 list-none space-y-1.5 overflow-auto p-0">
            {(scRun.checks || []).map((c, i) => (
              <li key={`${c.tool}-${c.target}-${i}`} className="text-[12px] leading-snug">
                <Badge tone={selfcheckBadgeTone(c.status)}>{String(c.status || "—")}</Badge>{" "}
                <strong>
                  {c.tool}[{c.target}]
                </strong>
                {c.reason ? ` · ${c.reason}` : ""}
                {c.exit_code != null ? ` · exit ${c.exit_code}` : ""}
                {c.version ? ` · ${c.version}` : ""}
                {c.finding_count ? ` · findings ${c.finding_count}` : ""}
                {c.artifact_rel ? (
                  <span className="text-[var(--text-muted)]"> · {c.artifact_rel}</span>
                ) : null}
                {c.timestamp ? (
                  <span className="text-[var(--text-muted)]"> · {c.timestamp}</span>
                ) : null}
              </li>
            ))}
            {!scRun.checks?.length && (
              <li className="text-[12px] text-[var(--text-muted)]">Нет checks</li>
            )}
          </ul>
          <div className="text-[11px] text-[var(--text-muted)]">
            unavailable / skipped / failed — авария (проверки не считаются успешными). Не путать с findings уязвимостей.
          </div>
        </Card>
      )}

      {(regRun || regReport) && (
        <Card className="mb-4 space-y-2 p-3">
          <div className="flex flex-wrap items-center gap-2">
            <span className="text-[11px] font-semibold uppercase text-[var(--text-muted)]">
              UI regression · {AI_TASKS_PATH}
            </span>
            {regRun?.status && (
              <Badge tone={statusTone[String(regRun.status)] || "default"}>{String(regRun.status)}</Badge>
            )}
            {regReport?.max_severity && regReport.max_severity !== "info" && (
              <Badge
                tone={
                  regReport.max_severity === "critical" || regReport.max_severity === "high"
                    ? "red"
                    : "yellow"
                }
              >
                {regReport.max_severity}
              </Badge>
            )}
            <span className="text-[11px] text-[var(--text-muted)]">
              {String((regRun?.deployment as { version?: string } | undefined)?.version || "—")}
              {" · "}
              {AI_TASKS_HINT}
            </span>
          </div>
          {regReport?.summary && (
            <div className="text-[12.5px] text-[var(--text-secondary)]">{regReport.summary}</div>
          )}
          {!!regReport?.steps?.length && (
            <ul className="m-0 max-h-48 list-none space-y-1.5 overflow-auto p-0">
              {regReport.steps.map((s, i) => (
                <li key={`${s.step}-${i}`} className="text-[12px] leading-snug">
                  <Badge
                    tone={
                      s.ok
                        ? "green"
                        : s.severity === "critical" || s.severity === "high"
                          ? "red"
                          : "yellow"
                    }
                  >
                    {s.ok ? "ok" : s.severity || "fail"}
                  </Badge>{" "}
                  <strong>{s.step}</strong>: {s.expected}
                  {!s.ok && (
                    <span className="text-[var(--text-muted)]">
                      {" "}
                      → {s.actual}
                      {s.bugfix_proposal ? ` · fix: ${s.bugfix_proposal}` : ""}
                    </span>
                  )}
                </li>
              ))}
            </ul>
          )}
          <div className="text-[11px] text-[var(--text-muted)]">
            Агент не нажимает Approve / Reject / Done и не исполняет Cursor / git / deploy.
          </div>
        </Card>
      )}

      <div className="grid gap-4 lg:grid-cols-[1fr_1.2fr]">
        <Card className="max-h-[70vh] space-y-2 overflow-auto p-3">
          {sorted.map((t) => (
            <button
              key={t.id}
              type="button"
              onClick={() => {
                setSelected(t);
                setParams({ id: String(t.id) });
              }}
              className="flex w-full items-start justify-between gap-2 rounded-[var(--radius)] border border-[var(--border)] px-3 py-2 text-left hover:bg-[var(--bg-elevated)]"
            >
              <div>
                <div className="text-[13px] font-medium">
                  #{t.id} {t.title}
                </div>
                <div className="text-[11px] text-[var(--text-muted)]">
                  {formatTaskAge(t.created_at)} · op {t.operator_id ?? "—"} · {t.priority}
                  {t.freeze_hit ? " · FREEZE" : ""}
                </div>
              </div>
              <Badge tone={statusTone[t.status] || "default"}>{t.status}</Badge>
            </button>
          ))}
          {!sorted.length && <div className="p-2 text-[12px] text-[var(--text-muted)]">Очередь пуста</div>}
        </Card>

        {selected ? (
          <Card className="space-y-3">
            <div className="flex flex-wrap items-center gap-2">
              <h3 className="m-0 text-[16px] font-bold">
                #{selected.id} {selected.title}
              </h3>
              <Badge tone={statusTone[selected.status] || "default"}>{selected.status}</Badge>
              {selected.freeze_hit && <Badge tone="red">FREEZE</Badge>}
              <span className="text-[12px] text-[var(--text-muted)]">{formatTaskAge(selected.created_at)}</span>
            </div>
            <div className="text-[13px] whitespace-pre-wrap text-[var(--text-secondary)]">
              <strong>Запрос:</strong>
              {"\n"}
              {selected.request_text}
            </div>
            {selected.summary && (
              <div className="text-[13px] whitespace-pre-wrap">
                <strong>План:</strong>
                {"\n"}
                {selected.summary}
              </div>
            )}
            {!!selected.attachments?.length && (
              <div className="flex flex-wrap gap-2">
                {selected.attachments.map((a) => (
                  <a
                    key={a.index}
                    href={aiTaskAttachmentUrl(selected.id, a.index)}
                    target="_blank"
                    rel="noreferrer"
                    className="block overflow-hidden rounded border border-[var(--border)]"
                    onClick={async (e) => {
                      e.preventDefault();
                      const token = getPanelToken("admin");
                      const res = await fetch(aiTaskAttachmentUrl(selected.id, a.index), {
                        credentials: "include",
                        headers: token ? { Authorization: `Bearer ${token}` } : {},
                      });
                      if (!res.ok) {
                        toast.error("Не удалось открыть фото");
                        return;
                      }
                      const blob = await res.blob();
                      window.open(URL.createObjectURL(blob), "_blank");
                    }}
                  >
                    <img
                      alt={a.name || `att-${a.index}`}
                      className="h-24 w-auto max-w-[180px] object-contain bg-[var(--bg-elevated)]"
                      src={aiTaskAttachmentUrl(selected.id, a.index)}
                      onError={(ev) => {
                        const el = ev.currentTarget;
                        const token = getPanelToken("admin");
                        fetch(aiTaskAttachmentUrl(selected.id, a.index), {
                          credentials: "include",
                          headers: token ? { Authorization: `Bearer ${token}` } : {},
                        })
                          .then((r) => r.blob())
                          .then((b) => {
                            el.src = URL.createObjectURL(b);
                          })
                          .catch(() => {});
                      }}
                    />
                  </a>
                ))}
              </div>
            )}
            {!!selected.file_list?.length && (
              <ul className="m-0 list-disc pl-5 font-mono text-[12px]">
                {selected.file_list.map((f) => (
                  <li key={f}>{f}</li>
                ))}
              </ul>
            )}
            {selected.agents?.enabled && (
              <div className="rounded-[var(--radius)] border border-[var(--border)] bg-[var(--bg-elevated)] p-3">
                <div className="mb-2 text-[11px] font-semibold uppercase text-[var(--text-muted)]">
                  Agents
                  {selected.agents.triage?.zones?.length
                    ? ` · ${(selected.agents.triage.zones || []).join(", ")}`
                    : ""}
                </div>
                {selected.agents.triage?.brief && (
                  <div className="mb-2 text-[12.5px] text-[var(--text-secondary)]">
                    {selected.agents.triage.brief}
                  </div>
                )}
                {selected.agents.selfcheck && (
                  <div
                    className={
                      isSelfcheckAlarm(selected.agents.selfcheck.job_status) ||
                      (selected.agents.selfcheck.checks || []).some((c) => isSelfcheckAlarm(c.status))
                        ? "mb-2 rounded border border-[var(--red)]/40 bg-[var(--red-bg)]/40 p-2"
                        : "mb-2 rounded border border-[var(--border)] p-2"
                    }
                  >
                    <div className="mb-1 text-[11px] font-semibold uppercase text-[var(--text-muted)]">
                      SAST self-check{" "}
                      <Badge tone={selfcheckBadgeTone(selected.agents.selfcheck.job_status)}>
                        {String(selected.agents.selfcheck.job_status || "—")}
                      </Badge>
                    </div>
                    <ul className="m-0 list-none space-y-1 p-0">
                      {(selected.agents.selfcheck.checks || []).map((c, i) => (
                        <li key={`${c.tool}-${c.target}-${i}`} className="text-[12px]">
                          <Badge tone={selfcheckBadgeTone(c.status)}>{String(c.status || "—")}</Badge>{" "}
                          {c.tool}[{c.target}] {c.reason || ""}
                          {c.exit_code != null ? ` · exit ${c.exit_code}` : ""}
                          {c.artifact_rel ? ` · ${c.artifact_rel}` : ""}
                        </li>
                      ))}
                    </ul>
                  </div>
                )}
                <ul className="m-0 max-h-40 list-none space-y-1.5 overflow-auto p-0">
                  {(selected.agents.merged || [])
                    .filter((f) => !isCheckStatusFinding(f))
                    .slice(0, 12)
                    .map((f, i) => (
                    <li key={i} className="text-[12px] leading-snug">
                      <Badge tone={f.severity === "high" ? "red" : f.severity === "low" ? "default" : "yellow"}>
                        {f.role}/{f.severity}
                      </Badge>{" "}
                      {f.text}
                    </li>
                  ))}
                  {!(selected.agents.merged || []).filter((f) => !isCheckStatusFinding(f)).length && (
                    <li className="text-[12px] text-[var(--text-muted)]">Нет findings</li>
                  )}
                </ul>
              </div>
            )}
            {selected.risks && (
              <div className="rounded-[var(--radius)] border border-[var(--yellow)]/30 bg-[var(--yellow-bg)] p-3 text-[12.5px]">
                {selected.risks}
              </div>
            )}
            {selected.smoke_plan && (
              <div className="text-[12.5px] whitespace-pre-wrap text-[var(--text-secondary)]">
                <strong>Smoke:</strong>
                {"\n"}
                {selected.smoke_plan}
              </div>
            )}
            {selected.cursor_prompt && (
              <div>
                <div className="mb-1 flex justify-between">
                  <span className="text-[11px] font-semibold uppercase text-[var(--text-muted)]">Cursor prompt</span>
                  <Button
                    size="sm"
                    onClick={() => {
                      navigator.clipboard.writeText(selected.cursor_prompt || "");
                      toast.success("Скопировано");
                    }}
                  >
                    <Copy className="size-3.5" /> Копировать
                  </Button>
                </div>
                <pre className="max-h-56 overflow-auto rounded-[var(--radius)] border border-[var(--border)] bg-[var(--bg-elevated)] p-3 text-[12px] whitespace-pre-wrap">
                  {selected.cursor_prompt}
                </pre>
              </div>
            )}

            <div className="flex flex-wrap gap-2 border-t border-[var(--border)] pt-3">
              {selected.status === "review" && (
                <>
                  <Button variant="primary" disabled={busy} onClick={() => approve(selected.id)}>
                    <Check className="size-3.5" /> Approve
                  </Button>
                  <input
                    value={rejectReason}
                    onChange={(e) => setRejectReason(e.target.value)}
                    placeholder="Причина reject"
                    className="h-9 min-w-[160px] flex-1 rounded-[var(--radius)] border border-[var(--border-strong)] bg-[var(--bg-elevated)] px-3 text-[13px]"
                  />
                  <Button variant="danger" disabled={busy} onClick={() => reject(selected.id)}>
                    <X className="size-3.5" /> Reject
                  </Button>
                </>
              )}
              {(selected.status === "approved" || selected.status === "review") && (
                <Button disabled={busy} onClick={() => done(selected.id)}>
                  Done + learning
                </Button>
              )}
            </div>
          </Card>
        ) : (
          <Card className="text-[13px] text-[var(--text-muted)]">Выберите задачу</Card>
        )}
      </div>
    </>
  );
}
