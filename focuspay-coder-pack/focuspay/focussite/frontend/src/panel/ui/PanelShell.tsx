// Panel shell: collapsible dark sidebar (sectioned nav) + topbar + scrollable
// content. Nav config is passed in so admin and operator reuse the same shell.
import { useEffect, useState, type ReactNode } from "react";
import { Link, useLocation } from "react-router-dom";
import type { LucideIcon } from "lucide-react";
import { ChevronLeft, LogOut, Menu } from "lucide-react";
import { usePanelSession } from "@/panel/lib/panelSession";
import { cx } from "@/panel/ui/primitives";

export interface NavItem {
  to: string;
  label: string;
  icon: LucideIcon;
  end?: boolean;
  badge?: string | number;
}
export interface NavSection {
  label?: string;
  items: NavItem[];
}

const LS_KEY = "focuspay_panel_sidebar_collapsed";

export function PanelShell({ sections, brand, children, headerSlot }: { sections: NavSection[]; brand: string; children: ReactNode; headerSlot?: ReactNode }) {
  const [collapsed, setCollapsed] = useState(() => window.localStorage.getItem(LS_KEY) === "1");
  const [mobileOpen, setMobileOpen] = useState(false);
  const { account, logout } = usePanelSession();
  const loc = useLocation();
  const homeTo = sections[0]?.items[0]?.to || "/";

  useEffect(() => setMobileOpen(false), [loc.pathname]);
  function toggleCollapsed() {
    setCollapsed((c) => {
      window.localStorage.setItem(LS_KEY, c ? "0" : "1");
      return !c;
    });
  }

  const isActive = (item: NavItem) => (item.end ? loc.pathname === item.to : loc.pathname === item.to || loc.pathname.startsWith(item.to + "/"));

  const sidebar = (
    <aside
      className={cx(
        "flex shrink-0 flex-col border-r border-[var(--border)] bg-[var(--bg-surface)] transition-[width] duration-300",
        collapsed ? "w-[60px]" : "w-[232px]",
      )}
    >
      <Link
        to={homeTo}
        onClick={() => setMobileOpen(false)}
        className="flex h-[56px] items-center gap-2.5 overflow-hidden border-b border-[var(--border)] px-3.5 hover:bg-[var(--bg-elevated)]"
        title={brand}
      >
        <div className="flex size-[30px] shrink-0 items-center justify-center rounded-[var(--radius-sm)] bg-[var(--text-primary)] text-[var(--text-inverse)]">
          <svg width="16" height="16" viewBox="0 0 18 18" fill="none">
            <path d="M4 6h10M4 9h7M4 12h8" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" />
          </svg>
        </div>
        {!collapsed && <span className="whitespace-nowrap text-[14.5px] font-bold tracking-tight">{brand}</span>}
      </Link>

      <nav className="flex flex-1 flex-col gap-1 overflow-y-auto overflow-x-hidden p-2">
        {sections.map((section, si) => (
          <div key={si} className={cx("flex flex-col gap-px pb-3", si < sections.length - 1 && "mb-1 border-b border-[var(--border)]")}>
            {!collapsed && section.label && (
              <p className="px-1.5 pb-1.5 text-[10px] font-semibold uppercase tracking-wider text-[var(--text-muted)]">{section.label}</p>
            )}
            {section.items.map((item) => {
              const active = isActive(item);
              const Icon = item.icon;
              return (
                <Link
                  key={item.to}
                  to={item.to}
                  title={collapsed ? item.label : undefined}
                  onClick={() => setMobileOpen(false)}
                  className={cx(
                    "relative flex items-center gap-2.5 overflow-hidden rounded-[var(--radius)] px-2 py-1.5 text-[13px] font-medium transition-colors",
                    active
                      ? "bg-[var(--bg-elevated)] text-[var(--text-primary)]"
                      : "text-[var(--text-secondary)] hover:bg-[var(--bg-elevated)] hover:text-[var(--text-primary)]",
                  )}
                >
                  {active && <span className="absolute left-0 top-1.5 bottom-1.5 w-[3px] rounded-r bg-[var(--text-primary)]" />}
                  <Icon className="size-4 shrink-0" strokeWidth={1.5} />
                  {!collapsed && <span className="truncate">{item.label}</span>}
                  {!collapsed && item.badge != null && (
                    <span className="ml-auto rounded-full border border-[var(--border-strong)] bg-[var(--bg-overlay)] px-1.5 text-[10px] font-semibold text-[var(--text-secondary)]">
                      {item.badge}
                    </span>
                  )}
                </Link>
              );
            })}
          </div>
        ))}
      </nav>

      <button
        onClick={toggleCollapsed}
        className="hidden items-center gap-2 border-t border-[var(--border)] px-3.5 py-3 text-[12.5px] font-medium text-[var(--text-muted)] hover:text-[var(--text-primary)] md:flex"
      >
        <ChevronLeft className={cx("size-3.5 transition-transform", collapsed && "rotate-180")} />
        {!collapsed && <span>Свернуть</span>}
      </button>
    </aside>
  );

  return (
    <div className="flex min-h-[100dvh] bg-[var(--bg-base)] text-[var(--text-primary)]">
      {/* desktop sidebar */}
      <div className="hidden md:flex">{sidebar}</div>
      {/* mobile drawer */}
      {mobileOpen && (
        <div className="fixed inset-0 z-40 md:hidden">
          <div className="absolute inset-0 bg-black/70" onClick={() => setMobileOpen(false)} />
          <div className="relative z-10 h-full w-[232px]">{sidebar}</div>
        </div>
      )}

      <div className="flex min-w-0 flex-1 flex-col">
        <header className="flex h-[56px] shrink-0 items-center justify-between border-b border-[var(--border)] bg-[var(--bg-surface)] px-4">
          <button className="text-[var(--text-secondary)] md:hidden" aria-label="Меню" onClick={() => setMobileOpen(true)}>
            <Menu className="size-5" />
          </button>
          {headerSlot && <div className="ml-2 min-w-0 flex-1 md:ml-3 md:w-full md:max-w-xs md:flex-none">{headerSlot}</div>}
          <div className="ml-auto flex shrink-0 items-center gap-3">
            <span className="hidden text-[13px] text-[var(--text-secondary)] sm:inline">{account?.display_name || account?.username}</span>
            <button onClick={logout} aria-label="Выйти" className="text-[var(--text-muted)] hover:text-[var(--text-primary)]">
              <LogOut className="size-4" />
            </button>
          </div>
        </header>
        <main className="flex-1 overflow-y-auto" data-panel-scroll="">
          <div className="mx-auto flex w-full max-w-[1440px] flex-col gap-6 p-7 max-md:gap-4 max-md:p-4">{children}</div>
        </main>
      </div>
    </div>
  );
}
