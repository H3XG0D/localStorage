import { Link, useLocation } from 'react-router-dom';
import { LogOut, X, Zap } from 'lucide-react';
import { useAuth } from '../../context/AuthContext';
import { getNavForRole } from '../../config/navigation';

interface SidebarProps {
  open: boolean;
  onClose: () => void;
}

export function Sidebar({ open, onClose }: SidebarProps) {
  const { user, logout } = useAuth();
  const location = useLocation();
  const groups = user ? getNavForRole(user.role) : [];

  const isActive = (to: string) => {
    if (to === '/admin' || to === '/owner' || to === '/trader' || to === '/doliv') {
      return location.pathname === to;
    }
    return location.pathname.startsWith(to);
  };

  return (
    <>
      {open && (
        <div className="fixed inset-0 bg-black/60 z-40 lg:hidden" onClick={onClose} />
      )}
      <aside
        className={`fixed top-0 left-0 h-full w-60 bg-sidebar border-r border-border z-50 flex flex-col transition-transform duration-200 lg:translate-x-0 ${
          open ? 'translate-x-0' : '-translate-x-full'
        }`}
      >
        <div className="flex items-center justify-between px-4 py-5 border-b border-border">
          <Link to={user ? (user.role === 'owner' ? '/owner' : user.role === 'trader' ? '/trader' : user.role === 'dolivshchik' ? '/doliv' : '/admin') : '/'} className="flex items-center gap-2">
            <div className="w-8 h-8 rounded-lg bg-accent flex items-center justify-center">
              <Zap size={16} className="text-white" />
            </div>
            <span className="font-bold text-sm tracking-wide">P2P PANEL</span>
          </Link>
          <button onClick={onClose} className="lg:hidden text-muted hover:text-white">
            <X size={18} />
          </button>
        </div>

        <nav className="flex-1 overflow-y-auto py-4 px-3 space-y-5">
          {groups.map((group) => (
            <div key={group.title}>
              <p className="text-[10px] font-semibold text-muted tracking-widest px-3 mb-2">
                {group.title}
              </p>
              <ul className="space-y-0.5">
                {group.items.map((item) => {
                  const Icon = item.icon;
                  const active = isActive(item.to);
                  return (
                    <li key={item.to}>
                      <Link
                        to={item.to}
                        onClick={onClose}
                        className={`flex items-center gap-3 px-3 py-2.5 rounded-xl text-sm transition-colors ${
                          active
                            ? 'bg-accent/15 text-accent font-medium'
                            : 'text-muted hover:text-white hover:bg-elevated'
                        }`}
                      >
                        <Icon size={16} />
                        {item.label}
                      </Link>
                    </li>
                  );
                })}
              </ul>
            </div>
          ))}
        </nav>

        <div className="p-3 border-t border-border">
          <button
            onClick={logout}
            className="flex items-center gap-3 w-full px-3 py-2.5 rounded-xl text-sm text-muted hover:text-red-400 hover:bg-red-500/10 transition-colors"
          >
            <LogOut size={16} />
            Выйти
          </button>
        </div>
      </aside>
    </>
  );
}
