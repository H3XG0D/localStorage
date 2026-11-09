import { useCallback, useEffect, useState } from "react";
import { toast } from "sonner";
import { PanelApiError } from "@/panel/lib/panelApi";
import { getUsdtContext, getUsdtIssuances, issueUsdt, type Dict } from "@/panel/lib/adminApi";
import { Badge, Button, Card, Field, Input, Modal, PageHeader, Select, Table, type Column } from "@/panel/ui/primitives";

function money(v: unknown) {
  return new Intl.NumberFormat("ru-RU", { maximumFractionDigits: 2 }).format(Number(v ?? 0));
}

export function AdminUsdt() {
  const [ctx, setCtx] = useState<Dict | null>(null);
  const [issuances, setIssuances] = useState<Dict[]>([]);
  const [open, setOpen] = useState(false);

  const load = useCallback(() => {
    getUsdtContext().then(setCtx).catch((e) => toast.error(e instanceof PanelApiError ? e.message : "Только для владельца финансов"));
    getUsdtIssuances({ limit: 50 })
      .then((r) => setIssuances(Array.isArray(r) ? r : (r.issuances as Dict[]) || []))
      .catch(() => undefined);
  }, []);

  useEffect(() => load(), [load]);

  const operators = (ctx?.operators ?? []) as Dict[];

  const cols: Column<Dict>[] = [
    { key: "created_at", label: "Дата", render: (r) => (r.created_at ? new Date(String(r.created_at)).toLocaleString("ru-RU") : "—") },
    { key: "operator_name", label: "Оператор", render: (r) => String(r.operator_name ?? r.operator_id ?? "—") },
    { key: "amount_usdt", label: "USDT", align: "right", render: (r) => <span className="font-mono">{money(r.amount_usdt)}</span> },
    { key: "note", label: "Заметка", render: (r) => String(r.note ?? "—") },
  ];

  return (
    <>
      <PageHeader
        title="Выпуск USDT"
        subtitle="Выдача USDT операторам на смене (только владелец финансов)"
        actions={
          <Button variant="primary" onClick={() => setOpen(true)} disabled={operators.length === 0}>
            + Выпустить
          </Button>
        }
      />
      <Card>
        <div className="mb-3 text-[13.5px] font-semibold">История выпусков</div>
        <Table columns={cols} rows={issuances} empty="Выпусков пока нет" />
      </Card>

      {open && <IssueModal operators={operators} onClose={() => setOpen(false)} onDone={() => { setOpen(false); load(); }} />}
    </>
  );
}

function IssueModal({ operators, onClose, onDone }: { operators: Dict[]; onClose: () => void; onDone: () => void }) {
  const [operatorId, setOperatorId] = useState(String(operators[0]?.operator_id ?? operators[0]?.id ?? ""));
  const [amount, setAmount] = useState("");
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);

  async function submit() {
    if (!operatorId || Number(amount) < 0) return toast.error("Проверьте данные");
    setBusy(true);
    try {
      await issueUsdt(Number(operatorId), Number(amount), note || undefined);
      toast.success("USDT выпущен");
      onDone();
    } catch (e) {
      toast.error(e instanceof PanelApiError ? e.message : "Ошибка");
    } finally {
      setBusy(false);
    }
  }

  return (
    <Modal
      open
      title="Выпуск USDT оператору"
      onClose={onClose}
      footer={
        <>
          <Button variant="ghost" onClick={onClose}>Отмена</Button>
          <Button variant="primary" disabled={busy} onClick={submit}>Выпустить</Button>
        </>
      }
    >
      <div className="flex flex-col gap-3">
        <Field label="Оператор">
          <Select value={operatorId} onChange={(e) => setOperatorId(e.target.value)}>
            {operators.map((o) => (
              <option key={String(o.operator_id ?? o.id)} value={String(o.operator_id ?? o.id)}>
                {String(o.display_name ?? o.username ?? o.operator_name ?? o.operator_id)}
              </option>
            ))}
          </Select>
        </Field>
        <Field label="Сумма USDT">
          <Input inputMode="decimal" value={amount} onChange={(e) => setAmount(e.target.value)} className="font-mono" />
        </Field>
        <Field label="Заметка (необязательно)">
          <Input value={note} onChange={(e) => setNote(e.target.value)} />
        </Field>
      </div>
    </Modal>
  );
}
