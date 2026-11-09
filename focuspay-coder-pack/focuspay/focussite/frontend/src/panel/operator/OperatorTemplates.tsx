import { useCallback, useEffect, useMemo, useState } from "react";
import { ArrowDown, ArrowUp, Pencil, Plus, Trash2 } from "lucide-react";
import { toast } from "sonner";
import { PanelApiError } from "@/panel/lib/panelApi";
import { panelMe } from "@/panel/lib/panelAuth";
import {
  createSharedTemplate,
  deleteSharedTemplate,
  listSharedTemplates,
  reorderSharedTemplates,
  updateSharedTemplate,
  type QuickReplyTemplate,
} from "@/panel/lib/chatApi";
import { Badge, Button, Card, Field, Input, Modal, PageHeader, Table, type Column } from "@/panel/ui/primitives";

type TemplateRow = QuickReplyTemplate & Record<string, unknown>;

function safeError(e: unknown, fallback: string) {
  if (e instanceof PanelApiError) {
    if (e.status === 401 || e.status === 403) return "Нет доступа";
    if (e.status === 404) return "Шаблон не найден";
    if (e.status === 409) return e.message || "Конфликт версий — обновите список";
    if (typeof e.message === "string" && e.message && e.message.length < 120) return e.message;
  }
  return fallback;
}

function formatDate(value?: string | null) {
  if (!value) return "—";
  const d = new Date(value);
  return Number.isNaN(d.getTime())
    ? "—"
    : d.toLocaleString("ru-RU", { day: "2-digit", month: "2-digit", year: "2-digit", hour: "2-digit", minute: "2-digit" });
}

function canMutateRow(
  r: TemplateRow,
  perms: Set<string>,
  operatorId: number | null,
): { edit: boolean; remove: boolean; priority: boolean } {
  const isSystem = Boolean(r.is_system);
  const isOwner =
    operatorId != null &&
    (r.created_by_operator_id === operatorId ||
      (r.created_by_operator_id == null && r.operator_id === operatorId));
  if (isSystem && !perms.has("templates.edit_system")) {
    return { edit: false, remove: false, priority: false };
  }
  const edit =
    (isOwner && perms.has("templates.edit_own")) ||
    perms.has("templates.edit_any") ||
    (isSystem && perms.has("templates.edit_system"));
  const remove =
    (isOwner && perms.has("templates.delete_own")) ||
    perms.has("templates.delete_any") ||
    (isSystem && perms.has("templates.edit_system"));
  const priority =
    perms.has("templates.manage_priority") &&
    (isOwner || perms.has("templates.edit_any") || perms.has("templates.edit_system"));
  return { edit, remove, priority };
}

export function OperatorTemplates() {
  const [items, setItems] = useState<TemplateRow[]>([]);
  const [permissions, setPermissions] = useState<Set<string>>(new Set());
  const [operatorId, setOperatorId] = useState<number | null>(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [modalOpen, setModalOpen] = useState(false);
  const [editId, setEditId] = useState<number | null>(null);
  const [editVersion, setEditVersion] = useState<number | undefined>(undefined);
  const [title, setTitle] = useState("");
  const [body, setBody] = useState("");
  const [trigger, setTrigger] = useState("");
  const [sortOrder, setSortOrder] = useState("10");
  const [deleteTarget, setDeleteTarget] = useState<TemplateRow | null>(null);

  const canCreate = permissions.has("templates.create");
  const canView = permissions.has("templates.view") || permissions.size === 0;

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [me, data] = await Promise.all([panelMe("operator"), listSharedTemplates()]);
      const oid = typeof me.id === "number" ? me.id : null;
      setOperatorId(oid);
      const perms = new Set<string>(
        Array.isArray(me.permissions)
          ? me.permissions.map(String)
          : Array.isArray(data.permissions)
            ? data.permissions.map(String)
            : [],
      );
      setPermissions(perms);
      const rows = [...(data.items || [])].sort(
        (a, b) => (a.sort_order ?? 0) - (b.sort_order ?? 0) || a.id - b.id,
      ) as TemplateRow[];
      setItems(rows);
    } catch (e) {
      const msg = safeError(e, "Не удалось загрузить шаблоны");
      setError(msg);
      setItems([]);
      toast.error(msg);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const resetForm = () => {
    setEditId(null);
    setEditVersion(undefined);
    setTitle("");
    setBody("");
    setTrigger("");
    setSortOrder("10");
  };

  const openCreate = () => {
    if (!canCreate) {
      toast.error("Нет прав на создание");
      return;
    }
    resetForm();
    const next =
      items.length === 0 ? 10 : Math.max(...items.map((i) => Number(i.sort_order) || 0)) + 10;
    setSortOrder(String(next));
    setModalOpen(true);
  };

  const openEdit = (item: TemplateRow) => {
    setEditId(item.id);
    setEditVersion(item.version);
    setTitle(item.title);
    setBody(item.body);
    setTrigger(item.trigger_phrase || "");
    setSortOrder(String(item.sort_order ?? 0));
    setModalOpen(true);
  };

  const save = async () => {
    const t = title.trim();
    const b = body.trim();
    const order = Number.parseInt(sortOrder, 10);
    if (!t || !b) {
      toast.error("Заполните название и текст");
      return;
    }
    if (t.length > 64 || b.length > 2000) {
      toast.error("Слишком длинный текст");
      return;
    }
    if (!Number.isFinite(order) || order < 0 || order > 9999) {
      toast.error("Приоритет: целое число 0–9999");
      return;
    }
    setBusy(true);
    try {
      if (editId) {
        await updateSharedTemplate(editId, {
          title: t,
          body: b,
          trigger_phrase: trigger.trim() || null,
          sort_order: order,
          version: editVersion,
        });
        toast.success("Шаблон обновлён");
      } else {
        await createSharedTemplate({
          title: t,
          body: b,
          trigger_phrase: trigger.trim() || undefined,
          sort_order: order,
        });
        toast.success("Шаблон создан");
      }
      setModalOpen(false);
      resetForm();
      await load();
    } catch (e) {
      toast.error(safeError(e, "Не удалось сохранить шаблон"));
    } finally {
      setBusy(false);
    }
  };

  const confirmDelete = async () => {
    if (!deleteTarget) return;
    setBusy(true);
    try {
      await deleteSharedTemplate(deleteTarget.id, deleteTarget.version);
      toast.success("Шаблон удалён");
      setDeleteTarget(null);
      await load();
    } catch (e) {
      toast.error(safeError(e, "Не удалось удалить шаблон"));
    } finally {
      setBusy(false);
    }
  };

  const move = async (item: TemplateRow, dir: -1 | 1) => {
    const idx = items.findIndex((x) => x.id === item.id);
    const swap = items[idx + dir];
    if (!swap) return;
    setBusy(true);
    try {
      await reorderSharedTemplates({
        a_id: item.id,
        b_id: swap.id,
        a_version: item.version,
        b_version: swap.version,
      });
      toast.success("Порядок обновлён");
      await load();
    } catch (e) {
      toast.error(safeError(e, "Не удалось изменить порядок"));
    } finally {
      setBusy(false);
    }
  };

  const cols: Column<TemplateRow>[] = useMemo(
    () => [
      {
        key: "order",
        label: "Приоритет",
        width: "110px",
        render: (r) => <span className="font-mono tabular-nums">{r.sort_order}</span>,
      },
      {
        key: "title",
        label: "Шаблон",
        render: (r) => (
          <div className="min-w-[180px]">
            <div className="flex items-center gap-2">
              <span className="font-semibold text-[var(--text-primary)]">{r.title}</span>
              {r.is_system ? <Badge tone="blue">системный</Badge> : null}
            </div>
            <div className="mt-0.5 line-clamp-2 text-[12px] text-[var(--text-muted)] whitespace-pre-wrap">
              {r.body}
            </div>
          </div>
        ),
      },
      {
        key: "trigger",
        label: "Триггер",
        width: "140px",
        render: (r) =>
          r.trigger_phrase ? (
            <Badge tone="blue">{r.trigger_phrase}</Badge>
          ) : (
            <span className="text-[var(--text-muted)]">—</span>
          ),
      },
      {
        key: "updated",
        label: "Изменён",
        width: "130px",
        render: (r) => (
          <span className="text-[12px] text-[var(--text-muted)]">{formatDate(r.updated_at || r.created_at)}</span>
        ),
      },
      {
        key: "actions",
        label: "",
        width: "180px",
        render: (r) => {
          const rowIdx = items.findIndex((x) => x.id === r.id);
          const caps = canMutateRow(r, permissions, operatorId);
          const swapUp = rowIdx > 0 ? items[rowIdx - 1] : null;
          const swapDown = rowIdx >= 0 && rowIdx < items.length - 1 ? items[rowIdx + 1] : null;
          const canUp =
            caps.priority &&
            swapUp != null &&
            canMutateRow(swapUp, permissions, operatorId).priority;
          const canDown =
            caps.priority &&
            swapDown != null &&
            canMutateRow(swapDown, permissions, operatorId).priority;
          return (
            <div className="flex flex-wrap gap-1">
              <Button
                size="sm"
                variant="ghost"
                disabled={busy || !canUp}
                aria-label="Выше"
                onClick={() => void move(r, -1)}
              >
                <ArrowUp className="size-3.5" />
              </Button>
              <Button
                size="sm"
                variant="ghost"
                disabled={busy || !canDown}
                aria-label="Ниже"
                onClick={() => void move(r, 1)}
              >
                <ArrowDown className="size-3.5" />
              </Button>
              <Button
                size="sm"
                variant="ghost"
                disabled={busy || !caps.edit}
                onClick={() => openEdit(r)}
              >
                <Pencil className="size-3.5" />
              </Button>
              <Button
                size="sm"
                variant="danger"
                disabled={busy || !caps.remove}
                onClick={() => setDeleteTarget(r)}
              >
                <Trash2 className="size-3.5" />
              </Button>
            </div>
          );
        },
      },
    ],
    [busy, items, permissions, operatorId],
  );

  if (!loading && !canView && permissions.size > 0 && !permissions.has("templates.view")) {
    return (
      <div className="space-y-4">
        <PageHeader title="Шаблоны" subtitle="Нет доступа к шаблонам" />
        <Card className="p-6">
          <p className="text-sm text-[var(--text-muted)]">Недостаточно прав (templates.view).</p>
        </Card>
      </div>
    );
  }

  return (
    <div className="space-y-4">
      <PageHeader
        title="Шаблоны"
        subtitle="Общие быстрые ответы. Чужие и системные — только по правам."
        actions={
          canCreate ? (
            <Button variant="primary" onClick={openCreate}>
              <Plus className="size-4" /> Создать
            </Button>
          ) : null
        }
      />

      <Card className="p-0 overflow-hidden">
        {loading ? (
          <p className="p-6 text-sm text-[var(--text-muted)]">Загрузка…</p>
        ) : error ? (
          <div className="p-6 space-y-3">
            <p className="text-sm text-[var(--red)]">{error}</p>
            <Button size="sm" variant="secondary" onClick={() => void load()}>
              Повторить
            </Button>
          </div>
        ) : items.length === 0 ? (
          <div className="p-8 text-center space-y-3">
            <p className="text-sm text-[var(--text-muted)]">Пока нет общих шаблонов</p>
            {canCreate ? (
              <Button variant="primary" onClick={openCreate}>
                <Plus className="size-4" /> Создать первый
              </Button>
            ) : null}
          </div>
        ) : (
          <Table columns={cols} rows={items} />
        )}
      </Card>

      <Modal
        open={modalOpen}
        onClose={() => {
          if (!busy) {
            setModalOpen(false);
            resetForm();
          }
        }}
        title={editId ? "Редактировать шаблон" : "Новый шаблон"}
      >
        <div className="space-y-3">
          <Field label="Название">
            <Input value={title} onChange={(e) => setTitle(e.target.value)} maxLength={64} placeholder="Короткое имя" />
          </Field>
          <Field label="Текст">
            <textarea
              className="min-h-[120px] w-full rounded-[var(--radius)] border border-[var(--border-strong)] bg-[var(--bg-elevated)] px-3 py-2 text-[13px] text-[var(--text-primary)] outline-none focus:border-[var(--text-muted)]"
              value={body}
              onChange={(e) => setBody(e.target.value)}
              maxLength={2000}
              placeholder="Текст ответа клиенту"
            />
          </Field>
          <Field label="Триггер автоответа (необязательно)">
            <Input
              value={trigger}
              onChange={(e) => setTrigger(e.target.value)}
              maxLength={256}
              placeholder="например: че кого"
            />
          </Field>
          <Field label="Приоритет (порядок)">
            <Input
              value={sortOrder}
              onChange={(e) => setSortOrder(e.target.value)}
              inputMode="numeric"
              placeholder="0–9999"
            />
          </Field>
          <div className="flex justify-end gap-2 pt-2">
            <Button
              variant="ghost"
              disabled={busy}
              onClick={() => {
                setModalOpen(false);
                resetForm();
              }}
            >
              Отмена
            </Button>
            <Button variant="primary" disabled={busy} onClick={() => void save()}>
              Сохранить
            </Button>
          </div>
        </div>
      </Modal>

      <Modal open={deleteTarget != null} onClose={() => !busy && setDeleteTarget(null)} title="Удалить шаблон?">
        <p className="text-sm text-[var(--text-secondary)]">
          Шаблон исчезнет у всех операторов. Это действие нельзя отменить.
        </p>
        <div className="mt-4 flex justify-end gap-2">
          <Button variant="ghost" disabled={busy} onClick={() => setDeleteTarget(null)}>
            Отмена
          </Button>
          <Button variant="danger" disabled={busy} onClick={() => void confirmDelete()}>
            Удалить
          </Button>
        </div>
      </Modal>
    </div>
  );
}
