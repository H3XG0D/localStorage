import { useEffect, useState } from "react";
import { Copy, Plus } from "lucide-react";
import { useLocation } from "react-router-dom";
import { toast } from "sonner";
import { PanelApiError } from "@/panel/lib/panelApi";
import { aiCreateTask, aiGetMyTask, aiListMyTasks, type AiDevTask } from "@/panel/lib/operatorApi";
import { openOpsAi } from "@/panel/operator/OperatorAiWidget";
import { Badge, Button, Card, Field, PageHeader, Select, type BadgeTone } from "@/panel/ui/primitives";

const statusTone: Record<string, BadgeTone> = {
  new: "default",
  drafting: "blue",
  review: "yellow",
  approved: "green",
  rejected: "red",
  done: "purple",
};

export function OperatorDevRequests() {
  const location = useLocation();
  const [tasks, setTasks] = useState<AiDevTask[]>([]);
  const [selected, setSelected] = useState<AiDevTask | null>(null);
  const [status, setStatus] = useState("all");
  const [text, setText] = useState("");
  const [priority, setPriority] = useState("normal");
  const [busy, setBusy] = useState(false);

  async function load() {
    const r = await aiListMyTasks(status);
    setTasks(r.tasks || []);
  }

  useEffect(() => {
    load().catch((e) => toast.error(e instanceof PanelApiError ? e.message : "Ошибка загрузки"));
  }, [status]);

  async function create() {
    if (!text.trim()) return;
    setBusy(true);
    try {
      const t = await aiCreateTask({
        request_text: text.trim(),
        priority,
        ui_context: {
          path: location.pathname,
          search: location.search || undefined,
          title: typeof document !== "undefined" ? document.title : undefined,
          hint: "Inbox: форма создания задачи, не баг-экран",
        },
      });
      setText("");
      toast.success(`Задача #${t.id} в review`);
      await load();
      setSelected(t);
    } catch (e) {
      toast.error(e instanceof PanelApiError ? e.message : "Ошибка");
    } finally {
      setBusy(false);
    }
  }

  async function openTask(id: number) {
    try {
      setSelected(await aiGetMyTask(id));
    } catch (e) {
      toast.error(e instanceof PanelApiError ? e.message : "Ошибка");
    }
  }

  return (
    <>
      <PageHeader
        title="Задачи разработчикам"
        subtitle="AI подготовит промпт и план. После Approve разработчик копирует в Cursor."
        actions={
          <Button size="sm" onClick={() => openOpsAi()}>
            Открыть AI
          </Button>
        }
      />

      <div className="grid gap-4 lg:grid-cols-2">
        <Card className="space-y-3">
          <Field label="Что нужно сделать">
            <textarea
              value={text}
              onChange={(e) => setText(e.target.value)}
              rows={5}
              className="w-full rounded-[var(--radius)] border border-[var(--border-strong)] bg-[var(--bg-elevated)] px-3 py-2 text-[13px] text-[var(--text-primary)] outline-none"
              placeholder="Например: добавить фильтр заявок по сети TRC20 в /ops/orders"
            />
          </Field>
          <Field label="Приоритет">
            <Select value={priority} onChange={(e) => setPriority(e.target.value)}>
              <option value="low">low</option>
              <option value="normal">normal</option>
              <option value="high">high</option>
              <option value="urgent">urgent</option>
            </Select>
          </Field>
          <Button variant="primary" disabled={busy || !text.trim()} onClick={create}>
            <Plus className="size-3.5" /> Создать задачу
          </Button>
        </Card>

        <Card className="space-y-3">
          <div className="flex items-center justify-between gap-2">
            <div className="text-[13px] font-semibold">Мои задачи</div>
            <Select value={status} onChange={(e) => setStatus(e.target.value)} className="w-auto">
              <option value="all">все</option>
              <option value="review">review</option>
              <option value="approved">approved</option>
              <option value="rejected">rejected</option>
              <option value="done">done</option>
            </Select>
          </div>
          <div className="max-h-[50vh] space-y-2 overflow-auto">
            {tasks.map((t) => (
              <button
                key={t.id}
                type="button"
                onClick={() => openTask(t.id)}
                className="flex w-full items-start justify-between gap-2 rounded-[var(--radius)] border border-[var(--border)] bg-[var(--bg-elevated)] px-3 py-2 text-left hover:border-[var(--border-strong)]"
              >
                <div>
                  <div className="text-[13px] font-medium">#{t.id} {t.title}</div>
                  <div className="mt-0.5 text-[11px] text-[var(--text-muted)]">{t.priority}</div>
                </div>
                <Badge tone={statusTone[t.status] || "default"}>{t.status}</Badge>
              </button>
            ))}
            {!tasks.length && <div className="text-[12px] text-[var(--text-muted)]">Пока нет задач</div>}
          </div>
        </Card>
      </div>

      {selected && (
        <Card className="mt-4 space-y-3">
          <div className="flex flex-wrap items-center gap-2">
            <h3 className="m-0 text-[16px] font-bold">#{selected.id} {selected.title}</h3>
            <Badge tone={statusTone[selected.status] || "default"}>{selected.status}</Badge>
            {selected.freeze_hit && <Badge tone="red">FREEZE</Badge>}
          </div>
          <p className="m-0 whitespace-pre-wrap text-[13px] text-[var(--text-secondary)]">{selected.summary || selected.request_text}</p>
          {!!selected.file_list?.length && (
            <div className="text-[12px]">
              <div className="mb-1 font-semibold text-[var(--text-muted)]">Файлы</div>
              <ul className="m-0 list-disc pl-5">
                {selected.file_list.map((f) => (
                  <li key={f} className="font-mono text-[12px]">
                    {f}
                  </li>
                ))}
              </ul>
            </div>
          )}
          {selected.risks && (
            <div className="rounded-[var(--radius)] border border-[var(--yellow)]/30 bg-[var(--yellow-bg)] p-3 text-[12.5px] text-[var(--yellow)]">
              {selected.risks}
            </div>
          )}
          {selected.cursor_prompt && (
            <div>
              <div className="mb-1 flex items-center justify-between">
                <span className="text-[11px] font-semibold uppercase text-[var(--text-muted)]">Промпт для Cursor</span>
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
              <pre className="max-h-64 overflow-auto rounded-[var(--radius)] border border-[var(--border)] bg-[var(--bg-elevated)] p-3 text-[12px] whitespace-pre-wrap">
                {selected.cursor_prompt}
              </pre>
            </div>
          )}
          {selected.status === "rejected" && selected.reject_reason && (
            <div className="text-[13px] text-[var(--red)]">Отклонено: {selected.reject_reason}</div>
          )}
        </Card>
      )}
    </>
  );
}
