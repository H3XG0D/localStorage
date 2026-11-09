import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useState } from 'react';
import { Plus, Pencil } from 'lucide-react';
import { api } from '../../api/client';
import { AppShell } from '../../components/layout/AppShell';
import { PageHeader } from '../../components/ui/SearchInput';
import { DataTable, Column } from '../../components/ui/DataTable';
import { Modal } from '../../components/ui/Modal';
import type { User } from '../../api/client';

export default function OwnerAdminsPage() {
  const qc = useQueryClient();
  const { data: admins } = useQuery({ queryKey: ['owner-admins'], queryFn: api.ownerAdmins });

  const [createOpen, setCreateOpen] = useState(false);
  const [login, setLogin] = useState('');
  const [password, setPassword] = useState('');
  const [fullName, setFullName] = useState('');
  const [createError, setCreateError] = useState('');

  const [editOpen, setEditOpen] = useState(false);
  const [editAdmin, setEditAdmin] = useState<User | null>(null);
  const [editFullName, setEditFullName] = useState('');
  const [editPassword, setEditPassword] = useState('');
  const [editActive, setEditActive] = useState(true);
  const [editError, setEditError] = useState('');

  const create = useMutation({
    mutationFn: () => api.createAdmin({
      login: login.trim(),
      password: password.trim(),
      full_name: fullName.trim(),
    }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['owner-admins'] });
      qc.invalidateQueries({ queryKey: ['owner-dashboard'] });
      setCreateOpen(false);
      setLogin(''); setPassword(''); setFullName(''); setCreateError('');
    },
    onError: (err: Error) => setCreateError(err.message),
  });

  const update = useMutation({
    mutationFn: () => {
      const patch: Parameters<typeof api.updateAdmin>[1] = {
        full_name: editFullName,
        is_active: editActive,
      };
      if (editPassword.trim()) patch.password = editPassword.trim();
      return api.updateAdmin(editAdmin!.id, patch);
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['owner-admins'] });
      qc.invalidateQueries({ queryKey: ['owner-dashboard'] });
      setEditOpen(false);
      setEditAdmin(null); setEditPassword(''); setEditError('');
    },
    onError: (err: Error) => setEditError(err.message),
  });

  function openEdit(u: User) {
    setEditAdmin(u);
    setEditFullName(u.full_name);
    setEditActive(u.is_active);
    setEditPassword('');
    setEditError('');
    setEditOpen(true);
  }

  const columns: Column<User>[] = [
    { key: 'id', header: 'ID', render: (u) => <span className="text-muted">#{u.id}</span> },
    { key: 'name', header: 'ФИО', render: (u) => u.full_name },
    { key: 'login', header: 'Логин', render: (u) => <span className="text-muted">{u.login}</span> },
    {
      key: 'status',
      header: 'Статус',
      render: (u) => (
        <span className={u.is_active ? 'badge-active' : 'badge-closed'}>
          {u.is_active ? 'Активен' : 'Отключён'}
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
    { key: 'created', header: 'Создан', render: (u) => new Date(u.created_at).toLocaleDateString('ru') },
    {
      key: 'actions',
      header: '',
      render: (u) => (
        <button
          className="text-muted hover:text-accent p-1 rounded"
          onClick={(e) => { e.stopPropagation(); openEdit(u); }}
          title="Редактировать"
        >
          <Pencil size={15} />
        </button>
      ),
    },
  ];

  return (
    <AppShell title="Администраторы">
      <PageHeader
        title="Администраторы"
        subtitle="Создание и управление доступом админов"
        action={
          <button className="btn-primary flex items-center gap-2" onClick={() => setCreateOpen(true)}>
            <Plus size={16} /> Новый админ
          </button>
        }
      />
      <DataTable columns={columns} data={admins ?? []} keyField="id" />

      <Modal open={createOpen} onClose={() => { setCreateOpen(false); setCreateError(''); }} title="Новый администратор">
        <form className="space-y-4" onSubmit={(e) => { e.preventDefault(); create.mutate(); }}>
          <input className="input" placeholder="Логин" value={login} onChange={(e) => setLogin(e.target.value)} required />
          <input className="input" placeholder="Пароль" type="password" value={password} onChange={(e) => setPassword(e.target.value)} required minLength={6} />
          <input className="input" placeholder="ФИО" value={fullName} onChange={(e) => setFullName(e.target.value)} required />
          {createError && <p className="text-red-400 text-xs">{createError}</p>}
          <button type="submit" className="btn-primary w-full" disabled={create.isPending}>Создать</button>
        </form>
      </Modal>

      <Modal open={editOpen} onClose={() => { setEditOpen(false); setEditError(''); }} title={`Редактировать: ${editAdmin?.login}`}>
        <form className="space-y-4" onSubmit={(e) => { e.preventDefault(); update.mutate(); }}>
          <div>
            <label className="block text-xs text-muted mb-1">ФИО</label>
            <input className="input" value={editFullName} onChange={(e) => setEditFullName(e.target.value)} required />
          </div>
          <div>
            <label className="block text-xs text-muted mb-1">Новый пароль (оставьте пустым, чтобы не менять)</label>
            <input className="input" type="password" placeholder="••••••••" value={editPassword} onChange={(e) => setEditPassword(e.target.value)} />
          </div>
          <div className="flex items-center gap-3">
            <input id="edit-admin-active" type="checkbox" checked={editActive} onChange={(e) => setEditActive(e.target.checked)} className="w-4 h-4 accent-accent" />
            <label htmlFor="edit-admin-active" className="text-sm select-none cursor-pointer">Аккаунт активен</label>
          </div>
          {!editActive && (
            <p className="text-xs text-muted">Отключённый админ не сможет войти в систему. Данные сохраняются.</p>
          )}
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
