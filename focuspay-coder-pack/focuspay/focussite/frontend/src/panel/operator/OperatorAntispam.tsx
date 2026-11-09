import { useCallback, useEffect, useState, type FormEvent } from "react";
import { Plus, ShieldBan, Trash2 } from "lucide-react";
import { toast } from "sonner";
import { PanelApiError } from "@/panel/lib/panelApi";
import { panelMe } from "@/panel/lib/panelAuth";
import {
  createAntispamPhrase,
  deleteAntispamPhrase,
  listAntispamPhrases,
  type AntispamPhrase,
} from "@/panel/lib/operatorApi";
import { Badge, Button, Card, Field, Input, PageHeader } from "@/panel/ui/primitives";

function errText(e: unknown, fallback: string) {
  if (e instanceof PanelApiError) {
    if (e.status === 401 || e.status === 403) return "Нет доступа";
    if (typeof e.message === "string" && e.message && e.message.length < 160) return e.message;
  }
  return fallback;
}

export function OperatorAntispam() {
  const [allowed, setAllowed] = useState<boolean | null>(null);
  const [items, setItems] = useState<AntispamPhrase[]>([]);
  const [builtin, setBuiltin] = useState<string[]>([]);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [draft, setDraft] = useState("");

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const r = await listAntispamPhrases();
      setItems(Array.isArray(r.items) ? r.items : []);
      setBuiltin(Array.isArray(r.builtin) ? r.builtin.map(String) : []);
    } catch (e) {
      setError(errText(e, "Не удалось загрузить список"));
      setItems([]);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    let cancelled = false;
    panelMe("operator")
      .then((me) => {
        if (cancelled) return;
        const perms = Array.isArray(me.permissions) ? me.permissions.map(String) : [];
        const ok = perms.includes("antispam.phrases");
        setAllowed(ok);
        if (ok) void load();
        else setLoading(false);
      })
      .catch(() => {
        if (!cancelled) {
          setAllowed(false);
          setLoading(false);
        }
      });
    return () => {
      cancelled = true;
    };
  }, [load]);

  async function addPhrase(e: FormEvent) {
    e.preventDefault();
    const phrase = draft.trim();
    if (!phrase) return;
    setBusy(true);
    try {
      await createAntispamPhrase(phrase);
      toast.success("Фраза добавлена — бот подхватит в течение полуминуты");
      setDraft("");
      await load();
    } catch (err) {
      toast.error(errText(err, "Не удалось добавить"));
    } finally {
      setBusy(false);
    }
  }

  async function remove(row: AntispamPhrase) {
    setBusy(true);
    try {
      await deleteAntispamPhrase(Number(row.id));
      toast.success("Фраза удалена");
      await load();
    } catch (err) {
      toast.error(errText(err, "Не удалось удалить"));
    } finally {
      setBusy(false);
    }
  }

  if (allowed === false) {
    return (
      <>
        <PageHeader title="Антиспам" subtitle="Нет права antispam.phrases" />
        <Card>
          <p className="text-[13px] text-[var(--text-muted)]">Этот раздел недоступен.</p>
        </Card>
      </>
    );
  }

  return (
    <>
      <PageHeader
        title="Антиспам"
        subtitle="Слова и предложения, по которым бот удаляет сообщение и банит автора в focus-чате. Системные маркеры не удаляются."
      />

      <Card className="mb-4">
        <form className="flex flex-wrap items-end gap-3" onSubmit={(e) => void addPhrase(e)}>
          <Field label="Слово или фраза">
            <Input
              value={draft}
              onChange={(e) => setDraft(e.target.value)}
              placeholder="например: боты распределители"
              className="min-w-[260px]"
              maxLength={200}
              disabled={busy}
            />
          </Field>
          <Button type="submit" variant="primary" disabled={busy || !draft.trim()}>
            <Plus className="size-3.5" />
            Добавить
          </Button>
        </form>
      </Card>

      {error && (
        <p className="mb-3 text-[13px] text-[var(--red)]">{error}</p>
      )}

      <Card className="mb-4">
        <h2 className="mb-3 text-[13px] font-semibold">Ваши фразы</h2>
        {loading ? (
          <p className="text-[13px] text-[var(--text-muted)]">Загрузка…</p>
        ) : items.length === 0 ? (
          <p className="text-[13px] text-[var(--text-muted)]">Пока пусто — добавьте то, что прилетает в чат.</p>
        ) : (
          <ul className="divide-y divide-[var(--border)]">
            {items.map((row) => (
              <li key={row.id} className="flex items-center justify-between gap-3 py-2">
                <span className="text-[13px]">{String(row.phrase)}</span>
                <Button
                  type="button"
                  variant="ghost"
                  size="sm"
                  disabled={busy}
                  onClick={() => void remove(row)}
                >
                  <Trash2 className="size-3.5" />
                  Удалить
                </Button>
              </li>
            ))}
          </ul>
        )}
      </Card>

      <Card>
        <h2 className="mb-2 flex items-center gap-2 text-[13px] font-semibold">
          <ShieldBan className="size-3.5" />
          Системные
        </h2>
        <p className="mb-3 text-[12.5px] text-[var(--text-muted)]">
          Уже вшиты в бота. Дублировать не нужно.
        </p>
        <div className="flex flex-wrap gap-1.5">
          {builtin.map((p) => (
            <Badge key={p}>{p}</Badge>
          ))}
        </div>
      </Card>
    </>
  );
}
