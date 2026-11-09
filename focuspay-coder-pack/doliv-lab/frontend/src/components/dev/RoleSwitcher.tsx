import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useAuth } from '../../context/AuthContext';
import { getHomePath } from '../../config/navigation';
import { UserRole } from '../../api/client';

export const LAB_ROLES: { role: UserRole; label: string; login: string; password: string }[] = [
  { role: 'owner', label: 'Owner', login: 'owner', password: 'owner123' },
  { role: 'admin', label: 'Админ', login: 'admin', password: 'admin123' },
  { role: 'teamlead', label: 'Тимлид', login: 'teamlead1', password: 'teamlead123' },
  { role: 'trader', label: 'Трейдер', login: 'trader1', password: 'trader123' },
  { role: 'trader', label: 'Мерчант', login: 'merchant1', password: 'merchant123' },
  { role: 'dolivshchik', label: 'Долив', login: 'doliv1', password: 'doliv123' },
];

export const roleSwitcherEnabled =
  import.meta.env.DEV || import.meta.env.VITE_ROLE_SWITCHER === 'true';

export function RoleSwitcher({ compact = false }: { compact?: boolean }) {
  const { login, user } = useAuth();
  const navigate = useNavigate();
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState('');

  if (!roleSwitcherEnabled) return null;

  const switchTo = async (loginStr: string, password: string) => {
    setError('');
    setBusy(loginStr);
    try {
      const me = await login(loginStr, password);
      navigate(getHomePath(me.role), { replace: true });
    } catch (e) {
      const msg = e instanceof Error ? e.message : 'Не удалось сменить роль';
      setError(
        import.meta.env.DEV && msg.includes('Сервер недоступен')
          ? 'Лаба не запущена. В doliv-lab: docker compose up -d'
          : msg,
      );
    } finally {
      setBusy(null);
    }
  };

  return (
    <div className={compact ? '' : 'w-full'}>
      <p className={`text-[10px] uppercase tracking-wider text-muted ${compact ? 'sr-only' : 'mb-2 text-center'}`}>
        Lab · переключить роль
      </p>
      <div className={`flex flex-wrap ${compact ? 'gap-1' : 'gap-2 justify-center'}`}>
        {LAB_ROLES.map((r) => {
          const active = user?.login === r.login;
          return (
            <button
              key={r.login}
              type="button"
              disabled={busy !== null}
              onClick={() => switchTo(r.login, r.password)}
              className={`rounded-lg px-2.5 py-1.5 text-xs font-medium transition-colors ${
                active
                  ? 'bg-accent text-white'
                  : 'bg-elevated text-[#d4d4d8] hover:bg-accent/20 hover:text-white'
              } disabled:opacity-50`}
              title={`${r.login} / ${r.password}`}
            >
              {busy === r.login ? '…' : r.label}
            </button>
          );
        })}
      </div>
      {error && <p className="mt-1 text-[11px] text-danger">{error}</p>}
    </div>
  );
}
