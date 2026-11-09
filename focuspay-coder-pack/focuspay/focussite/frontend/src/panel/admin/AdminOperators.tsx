import { useCallback, useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { ChevronRight } from "lucide-react";
import { toast } from "sonner";
import { PanelApiError } from "@/panel/lib/panelApi";
import { createOperator, getOperators, patchOperator, type Dict } from "@/panel/lib/adminApi";
import { Badge, Button, Card, Field, Input, Modal, PageHeader, Select, Table, type Column } from "@/panel/ui/primitives";

function money(v: unknown) { return new Intl.NumberFormat("ru-RU", { maximumFractionDigits: 0 }).format(Number(v ?? 0)); }
function rolesOf(r: Dict) { return Array.isArray(r.operator_roles) ? r.operator_roles.map(String) : [String(r.operator_role ?? "client")]; }
function roleLabels(r: Dict) { const roles = rolesOf(r); return roles.includes("client") && roles.includes("finance") ? "Клиент + финансы" : roles.includes("finance") ? "Финансы" : "Клиент"; }
function isOnShift(r: Dict) { return r.on_shift === true || Number(r.active_shifts ?? 0) > 0; }
function roleName(role: string) { return role === "finance" ? "финансовый" : "клиентский"; }
function operatorIdOf(r: Dict): number | null {
  const n = Number(r.id);
  return Number.isInteger(n) && n > 0 ? n : null;
}
function operatorHref(r: Dict): string | null {
  const id = operatorIdOf(r);
  return id != null ? `/x8/operators/${id}` : null;
}
function coveredRoles(rows: Dict[]) { return new Set(rows.flatMap(rolesOf)); }
function buyIsReady(gate: Dict | null, onShiftRows: Dict[]) {
  if (gate && typeof gate.allow === "boolean") return gate.allow;
  const roles = coveredRoles(onShiftRows);
  return roles.has("client") && roles.has("finance");
}
function RoleChecks({ roles, setRoles }: { roles: string[]; setRoles: (roles: string[]) => void }) {
  return <div className="flex flex-col gap-2 rounded-[var(--radius)] bg-[var(--bg-elevated)] p-3"><div className="text-[12px] font-medium">Доступы</div>{[["client", "Клиентские операции"], ["finance", "Финансовые операции"]].map(([role, label]) => <label key={role} className="flex items-center gap-2 text-[13px]"><input type="checkbox" checked={roles.includes(role)} onChange={(e) => setRoles(e.target.checked ? [...roles, role] : roles.filter((v) => v !== role))} /><span>{label}</span></label>)}<div className="text-[11px] text-[var(--text-muted)]">Можно назначить обе роли. Смена роли не переназначает уже взятые заявки.</div></div>;
}
function RoleGrades({ roles, grades, setGrades }: { roles: string[]; grades: Dict; setGrades: (grades: Dict) => void }) {
  return <div className="flex flex-col gap-2 rounded-[var(--radius)] bg-[var(--bg-elevated)] p-3"><div className="text-[12px] font-medium">Уровень в каждой роли</div>{roles.map((role) => <Field key={role} label={role === "finance" ? "Финансовые операции" : "Клиентские операции"}><Select value={String(grades[role] ?? "junior")} onChange={(e) => setGrades({ ...grades, [role]: e.target.value })}><option value="trainee">Стажёр</option><option value="junior">Новичок</option><option value="senior">Старший</option></Select></Field>)}</div>;
}

export function AdminOperators() {
  const navigate = useNavigate();
  const [rows, setRows] = useState<Dict[]>([]); const [shiftGate, setShiftGate] = useState<Dict | null>(null); const [canViewFinance, setCanViewFinance] = useState(false); const [loading, setLoading] = useState(true); const [createOpen, setCreateOpen] = useState(false);
  const load = useCallback(() => { setLoading(true); getOperators({ status: "all" }).then((r) => { if (Array.isArray(r)) { setRows(r); setShiftGate(null); setCanViewFinance(false); return; } setRows(r.operators || []); setShiftGate((r.shift_gate as Dict) || null); setCanViewFinance(r.can_view_finance !== false); }).catch((e) => toast.error(e instanceof PanelApiError ? e.message : "Ошибка")).finally(() => setLoading(false)); }, []);
  useEffect(() => load(), [load]);
  const onShiftRows = rows.filter(isOnShift);
  const missingRoles = Array.isArray(shiftGate?.missing_roles) ? shiftGate.missing_roles.map(String) : [...new Set(["client", "finance"].filter((role) => !coveredRoles(onShiftRows).has(role)))];
  const buyReady = buyIsReady(shiftGate, onShiftRows);
  const cols: Column<Dict>[] = [
    { key: "username", label: "Логин", render: (r) => <span className="font-mono">{String(r.username ?? "—")}</span> },
    { key: "display_name", label: "Имя", render: (r) => String(r.display_name || r.username || "—") },
    { key: "operator_roles", label: "Роли", render: (r) => roleLabels(r) },
    { key: "on_shift", label: "Смена", width: "130px", render: (r) => <Badge tone={isOnShift(r) ? "green" : "default"}>{isOnShift(r) ? "на смене" : "нет"}</Badge> },
    { key: "is_active", label: "Статус", width: "110px", render: (r) => <Badge tone={r.is_active ? "green" : "red"}>{r.is_active ? "активен" : "выключен"}</Badge> },
    { key: "orders_today", label: "Заявок сегодня", width: "130px", align: "right", render: (r) => String(r.orders_today ?? "—") },
    ...(canViewFinance ? [
      { key: "accrued", label: "Начислено ₽", width: "140px", align: "right" as const, render: (r: Dict) => (
        <div className="text-right font-mono tabular-nums">
          <div>{money(r.earnings_accrued_rub)}</div>
          {Number(r.earnings_shift_rub) > 0 ? <div className="text-[11px] text-[var(--text-muted)]">+{money(r.earnings_shift_rub)} на смене</div> : null}
        </div>
      ) },
      { key: "available", label: "Доступно ₽", width: "120px", align: "right" as const, render: (r: Dict) => <span className="font-mono tabular-nums">{money(r.payroll_available_rub)}</span> },
    ] : []),
    { key: "_open", label: "", width: "36px", align: "right", render: () => <ChevronRight className="ml-auto size-4 text-[var(--text-muted)]" /> },
  ];
  function openOperator(r: Dict) {
    const href = operatorHref(r);
    if (!href) {
      toast.error("У оператора нет id — карточку открыть нельзя");
      return;
    }
    navigate(href, { state: { operator: r } });
  }
  return <><PageHeader title="Операторы" subtitle="Учётные записи и фактические открытые смены. Клик по строке — статистика смен." actions={<Button variant="primary" onClick={() => setCreateOpen(true)}>+ Создать оператора</Button>} /><Card><div className="mb-4 flex flex-wrap items-center gap-2 text-[12.5px]"><Badge tone={buyReady ? "green" : "red"}>{buyReady ? "Реквизиты открыты" : "Реквизиты заблокированы"}</Badge><span className="text-[var(--text-secondary)]">На смене: {onShiftRows.length ? onShiftRows.map((r) => String(r.display_name || r.username || r.id)).join(", ") : "никого"}</span>{!buyReady && missingRoles.length > 0 && <span className="text-[var(--text-muted)]">Не хватает: {missingRoles.map(roleName).join(", ")}</span>}</div><Table columns={cols} rows={rows} empty={loading ? "Загрузка…" : "Пусто"} rowHref={operatorHref} rowState={(r) => ({ operator: r })} onRowClick={openOperator} /></Card>{createOpen && <CreateModal onClose={() => setCreateOpen(false)} onDone={() => { setCreateOpen(false); load(); }} />}</>;
}

function CreateModal({ onClose, onDone }: { onClose: () => void; onDone: () => void }) {
  const [username, setUsername] = useState(""); const [password, setPassword] = useState(""); const [displayName, setDisplayName] = useState("");   const [roles, setRoles] = useState<string[]>(["client"]); const [grades, setGrades] = useState<Dict>({ client: "junior" }); const [confirmPayouts, setConfirmPayouts] = useState(false); const [busy, setBusy] = useState(false);
  async function submit() { if (!username.trim() || password.length < 6) return toast.error("Логин и пароль (мин. 6 символов) обязательны"); if (!roles.length) return toast.error("Назначьте хотя бы одну роль"); setBusy(true); try { await createOperator({ username: username.trim(), password, display_name: displayName.trim() || undefined, operator_roles: roles, role_grades: Object.fromEntries(roles.map((role) => [role, grades[role] ?? "junior"])), payout_requisites_confirm: confirmPayouts }); toast.success("Оператор создан"); onDone(); } catch (e) { toast.error(e instanceof PanelApiError ? e.message : "Ошибка"); } finally { setBusy(false); } }
  return <Modal open title="Новый оператор" onClose={onClose} footer={<><Button variant="ghost" onClick={onClose}>Отмена</Button><Button variant="primary" disabled={busy} onClick={submit}>Создать</Button></>}><div className="flex flex-col gap-3"><Field label="Логин"><Input value={username} onChange={(e) => setUsername(e.target.value)} className="font-mono" /></Field><Field label="Пароль"><Input type="password" value={password} onChange={(e) => setPassword(e.target.value)} placeholder="Минимум 6 символов" /></Field><Field label="Имя (необязательно)"><Input value={displayName} onChange={(e) => setDisplayName(e.target.value)} /></Field><RoleChecks roles={roles} setRoles={setRoles} /><RoleGrades roles={roles} grades={grades} setGrades={setGrades} /><label className="flex items-center gap-2 text-[13px]"><input type="checkbox" checked={confirmPayouts} onChange={(e) => setConfirmPayouts(e.target.checked)} /><span>Подтверждение выплат</span></label><div className="text-[11px] text-[var(--text-muted)]">Старший финанс получает это право сам. Иначе — явная галка.</div></div></Modal>;
}

export function OperatorEditModal({ operator, onClose, onDone }: { operator: Dict; onClose: () => void; onDone: () => void }) {
  const id = Number(operator.id); const [displayName, setDisplayName] = useState(String(operator.display_name ?? "")); const [roles, setRoles] = useState<string[]>(rolesOf(operator)); const [grades, setGrades] = useState<Dict>((operator.role_grades ?? {}) as Dict); const [isActive, setIsActive] = useState(!!operator.is_active); const [confirmPayouts, setConfirmPayouts] = useState(!!operator.payout_requisites_confirm); const [newPassword, setNewPassword] = useState(""); const [busy, setBusy] = useState(false);
  async function submit() { if (!roles.length) return toast.error("Назначьте хотя бы одну роль"); setBusy(true); try { const body: Dict = { display_name: displayName.trim() || undefined, operator_roles: roles, role_grades: Object.fromEntries(roles.map((role) => [role, grades[role] ?? "junior"])), is_active: isActive, payout_requisites_confirm: confirmPayouts }; if (newPassword) body.password = newPassword; await patchOperator(id, body); toast.success("Сохранено"); onDone(); } catch (e) { toast.error(e instanceof PanelApiError ? e.message : "Ошибка"); } finally { setBusy(false); } }
  return <Modal open title={String(operator.display_name || operator.username || `Оператор ${id}`)} onClose={onClose} footer={<><Button variant="ghost" onClick={onClose}>Отмена</Button><Button variant="primary" disabled={busy} onClick={submit}>Сохранить</Button></>}><div className="flex flex-col gap-3"><Field label="Имя"><Input value={displayName} onChange={(e) => setDisplayName(e.target.value)} /></Field><RoleChecks roles={roles} setRoles={setRoles} /><RoleGrades roles={roles} grades={grades} setGrades={setGrades} /><label className="flex items-center gap-2 text-[13px]"><input type="checkbox" checked={isActive} onChange={(e) => setIsActive(e.target.checked)} /><span>Активен</span></label><label className="flex items-center gap-2 text-[13px]"><input type="checkbox" checked={confirmPayouts} onChange={(e) => setConfirmPayouts(e.target.checked)} /><span>Подтверждение выплат</span></label><div className="text-[11px] text-[var(--text-muted)]">В пул реквизита и «Рубли получены» на пейин-рельсе. Старший финанс — автоматически.</div><Field label="Новый пароль (необязательно)"><Input type="password" value={newPassword} onChange={(e) => setNewPassword(e.target.value)} placeholder="Оставьте пустым, чтобы не менять" /></Field></div></Modal>;
}
