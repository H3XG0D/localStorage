import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useEffect, useState } from 'react';
import { Plus, Pencil } from 'lucide-react';
import { api, UserRole } from '../../api/client';
import { AppShell } from '../../components/layout/AppShell';
import { PageHeader } from '../../components/ui/SearchInput';
import { DataTable, Column } from '../../components/ui/DataTable';
import { Modal } from '../../components/ui/Modal';
import type { User } from '../../api/client';

const ROLE_LABELS: Record<UserRole, string> = {
  owner: 'Владелец',
  admin: 'Админ',
  trader: 'Трейдер',
  dolivshchik: 'Доливщик',
  teamlead: 'Тимлид',
};

export default function AdminUsers() {
  const qc = useQueryClient();
  const { data: users } = useQuery({ queryKey: ['admin-users'], queryFn: api.adminUsers });
  const { data: appSettings } = useQuery({ queryKey: ['admin-settings'], queryFn: api.adminSettings });

  const defaultProfit = appSettings?.default_profit_percent ?? '12';
  const defaultDolivSalary = appSettings?.doliv_salary_percent ?? '1';

  const [createOpen, setCreateOpen] = useState(false);
  const [login, setLogin] = useState('');
  const [password, setPassword] = useState('');
  const [fullName, setFullName] = useState('');
  const [role, setRole] = useState<UserRole>('trader');
  const [createProfitPercent, setCreateProfitPercent] = useState('12');
  const [createDolivSalary, setCreateDolivSalary] = useState('1');
  const [createTeamleadPercent, setCreateTeamleadPercent] = useState('12');
  const [createDepositExempt, setCreateDepositExempt] = useState(false);
  const [createTeamleadId, setCreateTeamleadId] = useState('');
  const [createError, setCreateError] = useState('');

  const [editOpen, setEditOpen] = useState(false);
  const [editUser, setEditUser] = useState<User | null>(null);
  const [editFullName, setEditFullName] = useState('');
  const [editRole, setEditRole] = useState<UserRole>('trader');
  const [editProfitPercent, setEditProfitPercent] = useState('12');
  const [editDolivSalary, setEditDolivSalary] = useState('1');
  const [editTeamleadPercent, setEditTeamleadPercent] = useState('12');
  const [editDepositExempt, setEditDepositExempt] = useState(false);
  const [editTeamleadId, setEditTeamleadId] = useState('');
  const [editPassword, setEditPassword] = useState('');
  const [editActive, setEditActive] = useState(true);
  const [editError, setEditError] = useState('');

  const teamleads = (users ?? []).filter((u) => u.role === 'teamlead');

  useEffect(() => {
    if (appSettings?.default_profit_percent) {
      setCreateProfitPercent(appSettings.default_profit_percent);
    }
    if (appSettings?.doliv_salary_percent) {
      setCreateDolivSalary(appSettings.doliv_salary_percent);
    }
  }, [appSettings?.default_profit_percent, appSettings?.doliv_salary_percent]);

  const create = useMutation({
    mutationFn: () => {
      const payload: Parameters<typeof api.createUser>[0] = {
        login: login.trim(),
        password: password.trim(),
        full_name: fullName.trim(),
        role,
      };
      if (role === 'trader') {
        payload.profit_percent = createProfitPercent;
        payload.deposit_exempt = createDepositExempt;
        if (createTeamleadId) payload.teamlead_id = Number(createTeamleadId);
      }
      if (role === 'dolivshchik') payload.doliv_salary_usdt = createDolivSalary;
      if (role === 'teamlead') payload.teamlead_percent = createTeamleadPercent;
      return api.createUser(payload);
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['admin-users'] });
      setCreateOpen(false);
      setLogin(''); setPassword(''); setFullName(''); setCreateError('');
      setCreateProfitPercent(defaultProfit);
      setCreateDolivSalary(defaultDolivSalary);
      setCreateDepositExempt(false);
      setCreateTeamleadId('');
    },
    onError: (err: Error) => setCreateError(err.message),
  });

  const update = useMutation({
    mutationFn: () => {
      const patch: Parameters<typeof api.updateUser>[1] = {
        full_name: editFullName,
        role: editRole,
        is_active: editActive,
      };
      if (editPassword.trim()) patch.password = editPassword.trim();
      if (editRole === 'trader') {
        patch.profit_percent = editProfitPercent;
        patch.deposit_exempt = editDepositExempt;
        patch.teamlead_id = editTeamleadId ? Number(editTeamleadId) : null;
      }
      if (editRole === 'dolivshchik') patch.doliv_salary_usdt = editDolivSalary;
      if (editRole === 'teamlead') patch.teamlead_percent = editTeamleadPercent;
      return api.updateUser(editUser!.id, patch);
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['admin-users'] });
      setEditOpen(false);
      setEditUser(null); setEditPassword(''); setEditError('');
    },
    onError: (err: Error) => setEditError(err.message),
  });

  function openEdit(u: User) {
    setEditUser(u);
    setEditFullName(u.full_name);
    setEditRole(u.role);
    setEditProfitPercent(u.profit_percent ?? defaultProfit);
    setEditDolivSalary(u.doliv_salary_usdt ?? defaultDolivSalary);
    setEditTeamleadPercent(u.teamlead_percent ?? '12');
    setEditDepositExempt(!!u.deposit_exempt);
    setEditTeamleadId(u.teamlead_id ? String(u.teamlead_id) : '');
    setEditActive(u.is_active);
    setEditPassword('');
    setEditError('');
    setEditOpen(true);
  }

  const columns: Column<User>[] = [
    { key: 'id', header: 'ID', render: (u) => <span className="text-muted">#{u.id}</span> },
    { key: 'name', header: 'ФИО', render: (u) => u.full_name },
    { key: 'login', header: 'Логин', render: (u) => <span className="text-muted">{u.login}</span> },
    { key: 'role', header: 'Роль', render: (u) => ROLE_LABELS[u.role] },
    {
      key: 'tl',
      header: 'Тимлид',
      render: (u) => {
        if (u.role !== 'trader' || !u.teamlead_id) return <span className="text-muted">—</span>;
        const tl = (users ?? []).find((x) => x.id === u.teamlead_id);
        return <span className="text-muted text-sm">{tl?.full_name ?? `#${u.teamlead_id}`}</span>;
      },
    },
    {
      key: 'rate',
      header: 'Ставка',
      render: (u) => {
        if (u.role === 'trader' && u.profit_percent) {
          return <span>{u.profit_percent}%{u.deposit_exempt ? ' · exempt' : ''}</span>;
        }
        if (u.role === 'dolivshchik' && u.doliv_salary_usdt) return <span>{u.doliv_salary_usdt} USDT/долив</span>;
        if (u.role === 'teamlead' && u.teamlead_percent) return <span>пул {u.teamlead_percent}%</span>;
        return <span className="text-muted">—</span>;
      },
    },
    {
      key: 'status',
      header: 'Статус',
      render: (u) => (
        <span className={u.is_active ? 'badge-active' : 'badge-closed'}>
          {u.is_active ? 'Активен' : 'Неактивен'}
        </span>
      ),
    },
    {
      key: 'last_login',
      header: 'Посл. вход',
      render: (u) => u.last_login
        ? new Date(u.last_login).toLocaleString('ru', { dateStyle: 'short', timeStyle: 'short' })
        : <span className="text-muted">—</span>,
    },
    { key: 'created', header: 'Регистрация', render: (u) => new Date(u.created_at).toLocaleDateString('ru') },
    {
      key: 'actions',
      header: '',
      render: (u) => (
        u.role === 'owner' ? (
          <span className="text-muted text-xs">—</span>
        ) : (
          <button
            className="text-muted hover:text-accent p-1 rounded"
            onClick={(e) => { e.stopPropagation(); openEdit(u); }}
            title="Редактировать"
          >
            <Pencil size={15} />
          </button>
        )
      ),
    },
  ];

  return (
    <AppShell title="Пользователи">
      <PageHeader
        title="Пользователи"
        subtitle="Управление доступом"
        action={
          <button
            className="btn-primary flex items-center gap-2"
            onClick={() => {
              setCreateProfitPercent(defaultProfit);
              setCreateDolivSalary(defaultDolivSalary);
              setCreateOpen(true);
            }}
          >
            <Plus size={16} /> Новый пользователь
          </button>
        }
      />
      <DataTable columns={columns} data={users ?? []} keyField="id" />

      <Modal open={createOpen} onClose={() => { setCreateOpen(false); setCreateError(''); }} title="Новый пользователь">
        <form className="space-y-4" onSubmit={(e) => { e.preventDefault(); create.mutate(); }}>
          <input className="input" placeholder="Логин" value={login} onChange={(e) => setLogin(e.target.value)} required />
          <input className="input" placeholder="Пароль" type="password" value={password} onChange={(e) => setPassword(e.target.value)} required minLength={6} />
          <input className="input" placeholder="ФИО" value={fullName} onChange={(e) => setFullName(e.target.value)} required />
          <select className="input" value={role} onChange={(e) => setRole(e.target.value as UserRole)}>
            <option value="trader">Трейдер</option>
            <option value="teamlead">Тимлид</option>
            <option value="dolivshchik">Доливщик</option>
          </select>
          {role === 'trader' && (
            <>
              <div>
                <label className="block text-xs text-muted mb-1">% прибыли</label>
                <input className="input" type="number" min="0" step="0.01" value={createProfitPercent} onChange={(e) => setCreateProfitPercent(e.target.value)} required />
              </div>
              <div>
                <label className="block text-xs text-muted mb-1">Тимлид</label>
                <select className="input" value={createTeamleadId} onChange={(e) => setCreateTeamleadId(e.target.value)}>
                  <option value="">— без тимлида —</option>
                  {teamleads.map((t) => (
                    <option key={t.id} value={t.id}>{t.full_name} ({t.login})</option>
                  ))}
                </select>
              </div>
              <label className="flex items-center gap-2 text-sm">
                <input type="checkbox" checked={createDepositExempt} onChange={(e) => setCreateDepositExempt(e.target.checked)} />
                Без рабочего депозита (merchant)
              </label>
            </>
          )}
          {role === 'teamlead' && (
            <div>
              <label className="block text-xs text-muted mb-1">Пул % тимлида</label>
              <input className="input" type="number" min="0" step="0.01" value={createTeamleadPercent} onChange={(e) => setCreateTeamleadPercent(e.target.value)} required />
            </div>
          )}
          {role === 'dolivshchik' && (
            <div>
              <label className="block text-xs text-muted mb-1">Ставка (USDT/долив)</label>
              <input className="input" type="number" min="0" step="0.01" value={createDolivSalary} onChange={(e) => setCreateDolivSalary(e.target.value)} required />
            </div>
          )}
          {createError && <p className="text-red-400 text-xs">{createError}</p>}
          <button type="submit" className="btn-primary w-full" disabled={create.isPending}>Создать</button>
        </form>
      </Modal>

      <Modal open={editOpen} onClose={() => { setEditOpen(false); setEditError(''); }} title={`Редактировать: ${editUser?.login}`}>
        <form className="space-y-4" onSubmit={(e) => { e.preventDefault(); update.mutate(); }}>
          <div>
            <label className="block text-xs text-muted mb-1">ФИО</label>
            <input className="input" value={editFullName} onChange={(e) => setEditFullName(e.target.value)} required />
          </div>
          <div>
            <label className="block text-xs text-muted mb-1">Роль</label>
            <select className="input" value={editRole} onChange={(e) => setEditRole(e.target.value as UserRole)} disabled={editUser?.role === 'admin' || editUser?.role === 'owner'}>
              <option value="trader">Трейдер</option>
              <option value="teamlead">Тимлид</option>
              <option value="dolivshchik">Доливщик</option>
              {editUser?.role === 'admin' && <option value="admin">Админ</option>}
              {editUser?.role === 'owner' && <option value="owner">Владелец</option>}
            </select>
          </div>
          {editRole === 'trader' && (
            <>
              <div>
                <label className="block text-xs text-muted mb-1">% прибыли</label>
                <input className="input" type="number" min="0" step="0.01" value={editProfitPercent} onChange={(e) => setEditProfitPercent(e.target.value)} required />
              </div>
              <div>
                <label className="block text-xs text-muted mb-1">Тимлид</label>
                <select className="input" value={editTeamleadId} onChange={(e) => setEditTeamleadId(e.target.value)}>
                  <option value="">— без тимлида —</option>
                  {teamleads.map((t) => (
                    <option key={t.id} value={t.id}>{t.full_name} ({t.login})</option>
                  ))}
                </select>
              </div>
              <label className="flex items-center gap-2 text-sm">
                <input type="checkbox" checked={editDepositExempt} onChange={(e) => setEditDepositExempt(e.target.checked)} />
                Без рабочего депозита
              </label>
            </>
          )}
          {editRole === 'teamlead' && (
            <div>
              <label className="block text-xs text-muted mb-1">Пул % тимлида</label>
              <input className="input" type="number" min="0" step="0.01" value={editTeamleadPercent} onChange={(e) => setEditTeamleadPercent(e.target.value)} required />
            </div>
          )}
          {editRole === 'dolivshchik' && (
            <div>
              <label className="block text-xs text-muted mb-1">Ставка (USDT/долив)</label>
              <input className="input" type="number" min="0" step="0.01" value={editDolivSalary} onChange={(e) => setEditDolivSalary(e.target.value)} required />
            </div>
          )}
          <div>
            <label className="block text-xs text-muted mb-1">Новый пароль (оставьте пустым, чтобы не менять)</label>
            <input className="input" type="password" placeholder="••••••••" value={editPassword} onChange={(e) => setEditPassword(e.target.value)} />
          </div>
          <div className="flex items-center gap-3">
            <input id="edit-active" type="checkbox" checked={editActive} onChange={(e) => setEditActive(e.target.checked)} className="w-4 h-4 accent-accent" />
            <label htmlFor="edit-active" className="text-sm select-none cursor-pointer">Аккаунт активен</label>
          </div>
          {editError && <p className="text-red-400 text-xs">{editError}</p>}
          <div className="flex gap-2">
            <button type="button" className="btn-secondary flex-1" onClick={() => setEditOpen(false)}>Отмена</button>
            <button type="submit" className="btn-primary flex-1" disabled={update.isPending}>Сохранить</button>
          </div>
        </form>
      </Modal>
    </AppShell>
  );
}
