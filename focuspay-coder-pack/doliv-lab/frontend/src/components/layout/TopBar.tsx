import { useState, useEffect, useRef } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Bell, Menu } from 'lucide-react';
import { Link } from 'react-router-dom';
import { api, UserRole } from '../../api/client';
import { useAuth } from '../../context/AuthContext';
import { getHomePath } from '../../config/navigation';
import { RoleSwitcher, roleSwitcherEnabled } from '../dev/RoleSwitcher';
import { SearchInput } from '../ui/SearchInput';

interface TopBarProps {
  title: string;
  onMenuClick: () => void;
  search?: string;
  onSearchChange?: (v: string) => void;
  searchPlaceholder?: string;
}

function notificationLinkForRole(link: string, role: UserRole): string {
  if (role === 'admin' || role === 'owner') return link;
  if (link.startsWith('/admin/requisites/')) {
    return role === 'trader' ? link.replace('/admin/requisites/', '/trader/requisites/') : link;
  }
  if (link.startsWith('/admin/doliv-requests')) {
    return role === 'trader' ? '/trader/doliv-requests' : getHomePath(role);
  }
  if (link.startsWith('/admin/')) return getHomePath(role);
  return link;
}

export function TopBar({ title, onMenuClick, search, onSearchChange, searchPlaceholder }: TopBarProps) {
  const { user } = useAuth();
  const qc = useQueryClient();
  const [notificationsOpen, setNotificationsOpen] = useState(false);
  const notifRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!notificationsOpen) return;
    const handleKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') setNotificationsOpen(false);
    };
    const handleClick = (e: MouseEvent) => {
      if (notifRef.current && !notifRef.current.contains(e.target as Node)) {
        setNotificationsOpen(false);
      }
    };
    document.addEventListener('keydown', handleKey);
    document.addEventListener('mousedown', handleClick);
    return () => {
      document.removeEventListener('keydown', handleKey);
      document.removeEventListener('mousedown', handleClick);
    };
  }, [notificationsOpen]);
  const { data: unread } = useQuery({
    queryKey: ['notifications-unread-count'],
    queryFn: api.unreadNotificationsCount,
    refetchInterval: 30000,
    enabled: !!user,
  });
  const { data: notifications } = useQuery({
    queryKey: ['notifications'],
    queryFn: () => api.notifications({ limit: 8 }),
    refetchInterval: 30000,
    enabled: !!user && notificationsOpen,
  });

  const invalidateNotifications = () => {
    qc.invalidateQueries({ queryKey: ['notifications'] });
    qc.invalidateQueries({ queryKey: ['notifications-unread-count'] });
  };

  const markRead = useMutation({
    mutationFn: api.markNotificationRead,
    onSuccess: invalidateNotifications,
  });
  const markAllRead = useMutation({
    mutationFn: api.markAllNotificationsRead,
    onSuccess: invalidateNotifications,
  });

  const role = user?.role ?? 'admin';

  return (
    <header className="sticky top-0 z-30 bg-base/90 backdrop-blur border-b border-border">
      <div className="flex items-center gap-3 px-4 lg:px-6 py-3">
        <button
          type="button"
          onClick={onMenuClick}
          className="lg:hidden flex min-h-11 min-w-11 items-center justify-center rounded-xl text-muted hover:text-white hover:bg-elevated"
          aria-label="Открыть меню"
        >
          <Menu size={20} />
        </button>
        <h1 className="font-semibold text-base min-w-0 flex-1 truncate text-[#fafafa]">{title}</h1>

        {onSearchChange !== undefined && (
          <SearchInput
            value={search ?? ''}
            onChange={onSearchChange}
            placeholder={searchPlaceholder ?? 'Поиск...'}
            className="flex-1 max-w-md mx-auto hidden md:block"
          />
        )}

        <div className="flex items-center gap-2 ml-auto shrink-0">
          <div className="hidden md:block max-w-[min(28rem,40vw)]">
            <RoleSwitcher compact />
          </div>
          <div className="relative" ref={notifRef}>
            <button
              type="button"
              className="relative flex min-h-11 min-w-11 items-center justify-center rounded-xl text-muted hover:text-white hover:bg-elevated"
              onClick={() => setNotificationsOpen((open) => !open)}
              aria-label="Уведомления"
            >
              <Bell size={18} />
              {!!unread?.count && (
                <span className="absolute right-1 top-1 min-w-4 rounded-full bg-red-500 px-1 text-[10px] font-bold text-white">
                  {unread.count > 9 ? '9+' : unread.count}
                </span>
              )}
            </button>
            {notificationsOpen && (
              <div className="absolute right-0 top-12 z-50 w-80 max-w-[calc(100vw-2rem)] rounded-2xl border border-border bg-surface p-3 shadow-2xl">
                <div className="mb-2 flex items-center justify-between">
                  <h3 className="text-sm font-semibold text-[#fafafa]">Уведомления</h3>
                  <button
                    type="button"
                    className="text-xs text-accent hover:text-accent-hover disabled:text-muted"
                    disabled={!unread?.count || markAllRead.isPending}
                    onClick={() => markAllRead.mutate()}
                  >
                    Прочитать все
                  </button>
                </div>
                <div className="max-h-96 space-y-2 overflow-y-auto">
                  {(notifications ?? []).map((notification) => {
                    const resolvedLink = notification.link
                      ? notificationLinkForRole(notification.link, role)
                      : null;
                    const content = (
                      <div className={`rounded-xl border p-3 text-sm ${notification.is_read ? 'border-border/60 bg-elevated/20' : 'border-accent/30 bg-accent/10'}`}>
                        <div className="flex items-start justify-between gap-2">
                          <p className="font-medium text-[#fafafa]">{notification.title}</p>
                          {!notification.is_read && <span className="mt-1 h-2 w-2 rounded-full bg-accent" />}
                        </div>
                        <p className="mt-1 text-xs text-muted">{notification.message}</p>
                        <p className="mt-2 text-[11px] text-muted">{new Date(notification.created_at).toLocaleString('ru')}</p>
                      </div>
                    );

                    return resolvedLink ? (
                      <Link
                        key={notification.id}
                        to={resolvedLink}
                        onClick={() => {
                          if (!notification.is_read) markRead.mutate(notification.id);
                          setNotificationsOpen(false);
                        }}
                      >
                        {content}
                      </Link>
                    ) : (
                      <button
                        key={notification.id}
                        type="button"
                        className="block w-full text-left"
                        onClick={() => !notification.is_read && markRead.mutate(notification.id)}
                      >
                        {content}
                      </button>
                    );
                  })}
                  {!notifications?.length && <p className="py-6 text-center text-sm text-muted">Уведомлений нет</p>}
                </div>
              </div>
            )}
          </div>
          <div className="flex items-center gap-2 pl-2 border-l border-border">
            <div className="w-8 h-8 rounded-full bg-accent/30 flex items-center justify-center text-xs font-bold text-accent">
              {user?.full_name?.charAt(0) ?? '?'}
            </div>
            <div className="hidden sm:block">
              <p className="text-xs font-medium leading-none text-[#fafafa]">{user?.full_name}</p>
              <p className="text-[10px] text-muted mt-0.5">{user?.login}</p>
            </div>
          </div>
        </div>
      </div>
      {onSearchChange !== undefined && (
        <div className="px-4 pb-3 md:hidden">
          <SearchInput
            value={search ?? ''}
            onChange={onSearchChange}
            placeholder={searchPlaceholder ?? 'Поиск...'}
            className="w-full"
          />
        </div>
      )}
      {roleSwitcherEnabled && (
        <div className="px-4 pb-3 md:hidden border-t border-border/60 pt-2">
          <RoleSwitcher compact />
        </div>
      )}
    </header>
  );
}
