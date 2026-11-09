import { ReactNode } from 'react';
import { useQuery } from '@tanstack/react-query';
import { Activity, CreditCard, Droplets, Plus } from 'lucide-react';
import { api } from '../../api/client';
import { useAuth } from '../../context/AuthContext';

const ACTIVITY_ICONS = {
  requisite: CreditCard,
  zaliv: Plus,
  doliv: Droplets,
};

export function RightPanel() {
  const { user } = useAuth();
  const queryEnabled = !!user;

  const dashboardQuery = useQuery({
    queryKey: ['admin-dashboard-stats'],
    queryFn: () => api.statsDashboard(),
    refetchInterval: 30000,
    enabled: queryEnabled,
  });
  const activityQuery = useQuery({
    queryKey: ['admin-activity'],
    queryFn: api.activity,
    refetchInterval: 30000,
    enabled: queryEnabled,
  });

  const dashboard = dashboardQuery.data;
  const activity = activityQuery.data;
  const operations = dashboard?.operations_today;

  return (
    <aside className="w-72 shrink-0 space-y-4 hidden xl:block">
      <div className="card">
        <h3 className="text-sm font-semibold mb-3">Операции сегодня</h3>
        {dashboardQuery.isError ? (
          <div className="space-y-2">
            <p className="text-xs text-red-300">Не удалось загрузить</p>
            <button type="button" onClick={() => dashboardQuery.refetch()} className="text-xs text-accent hover:underline">
              Повторить
            </button>
          </div>
        ) : dashboardQuery.isLoading && !dashboard ? (
          <p className="text-xs text-muted">Загрузка…</p>
        ) : (
          <div className="grid grid-cols-2 gap-2">
            {[
              { label: 'Новых реквизитов', value: operations?.new_requisites ?? 0 },
              { label: 'Заливов', value: operations?.zalivs ?? 0 },
              { label: 'Доливов', value: operations?.dolivs ?? 0 },
              { label: 'Закрыто', value: operations?.closed_requisites ?? 0 },
            ].map((item) => (
              <div key={item.label} className="bg-elevated rounded-lg p-3">
                <p className="text-lg font-bold">{item.value}</p>
                <p className="text-[10px] text-muted mt-0.5">{item.label}</p>
              </div>
            ))}
          </div>
        )}
      </div>

      <div className="card">
        <div className="flex items-center justify-between mb-3">
          <h3 className="text-sm font-semibold">Последние действия</h3>
          <button className="text-xs text-accent hover:underline">Все</button>
        </div>
        {activityQuery.isError ? (
          <div className="space-y-2">
            <p className="text-xs text-red-300">Не удалось загрузить действия</p>
            <button type="button" onClick={() => activityQuery.refetch()} className="text-xs text-accent hover:underline">
              Повторить
            </button>
          </div>
        ) : activityQuery.isLoading && !activity ? (
          <p className="text-xs text-muted">Загрузка…</p>
        ) : (
          <ul className="space-y-3">
            {(activity ?? []).slice(0, 8).map((event) => {
              const Icon = ACTIVITY_ICONS[event.type] ?? Activity;
              return (
                <li key={event.id} className="flex gap-2.5">
                  <div className="w-7 h-7 rounded-lg bg-elevated flex items-center justify-center shrink-0">
                    <Icon size={12} className="text-muted" />
                  </div>
                  <div>
                    <p className="text-xs leading-snug">{event.text}</p>
                    <p className="text-[10px] text-muted mt-0.5">
                      {new Date(event.created_at).toLocaleTimeString('ru', { hour: '2-digit', minute: '2-digit' })}
                    </p>
                  </div>
                </li>
              );
            })}
            {!activity?.length && <li className="text-xs text-muted">Пока нет действий</li>}
          </ul>
        )}
      </div>
    </aside>
  );
}

interface DashboardLayoutProps {
  children: ReactNode;
  rightPanel?: boolean;
}

export function DashboardLayout({ children, rightPanel }: DashboardLayoutProps) {
  return (
    <div className="flex gap-5">
      <div className="flex-1 min-w-0">{children}</div>
      {rightPanel && <RightPanel />}
    </div>
  );
}
