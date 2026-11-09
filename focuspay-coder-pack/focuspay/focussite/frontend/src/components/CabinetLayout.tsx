// Cabinet shell: translucent top bar + horizontal nav. Shared by all /cabinet pages.
import { type ReactNode } from "react";
import { Dices, Gift, LayoutDashboard, LogOut, Settings, Sparkles, Users } from "lucide-react";
import { Link, useLocation, useNavigate } from "react-router-dom";
import { toast } from "sonner";
import { Brand } from "@/components/Brand";
import { ThemeToggle } from "@/components/ThemeToggle";
import { Button } from "@/components/ui/button";
import { useSession } from "@/lib/session";
import { cn } from "@/lib/utils";
import { CasinoOpenLink } from "@/casino/casinoPaths";

const NAV = [
  { to: "/cabinet", label: "Обзор", icon: LayoutDashboard, end: true },
  { to: "/cabinet/referral", label: "Рефералы", icon: Users },
  { to: "/casino/play/raffle", label: "FocusLucky", icon: Sparkles },
  { to: "/casino", label: "FocusBet", icon: Dices },
  { to: "/cabinet/settings", label: "Настройки", icon: Settings },
];

export function CabinetLayout({ children }: { children: ReactNode }) {
  const { user, logout } = useSession();
  const location = useLocation();
  const navigate = useNavigate();

  async function onLogout() {
    await logout();
    toast.success("Вы вышли из аккаунта");
    navigate("/", { replace: true });
  }

  return (
    <div className="min-h-screen bg-background">
      <header className="sticky top-0 z-40 border-b border-border/80 bg-background/80 backdrop-blur-xl">
        <div className="mx-auto flex h-16 max-w-5xl items-center justify-between px-4 sm:px-6 lg:px-8">
          <Link to="/" aria-label="FocusPay">
            <Brand />
          </Link>
          <div className="flex items-center gap-2">
            <ThemeToggle />
            <span className="hidden text-sm text-muted-foreground sm:inline">
              {user?.display_name || user?.username}
            </span>
            <Button variant="ghost" size="icon" aria-label="Выйти" onClick={onLogout}>
              <LogOut className="size-4" />
            </Button>
          </div>
        </div>
        <nav className="mx-auto flex max-w-5xl gap-1 overflow-x-auto px-2 sm:px-6 lg:px-8">
          {NAV.map((item) => {
            const casino = item.to.startsWith("/casino");
            const raffle = item.to.startsWith("/casino/play/raffle");
            const active = raffle
              ? location.pathname.startsWith("/casino/play/raffle")
              : item.to === "/casino"
                ? location.pathname.startsWith("/casino") && !location.pathname.startsWith("/casino/play/raffle")
                : item.end
                  ? location.pathname === item.to
                  : location.pathname.startsWith(item.to);
            const className = cn(
              "inline-flex items-center gap-2 whitespace-nowrap border-b-2 px-3 py-3 text-sm font-medium transition-colors",
              active ? "border-foreground text-foreground" : "border-transparent text-muted-foreground hover:text-foreground",
            );
            if (casino) {
              return (
                <CasinoOpenLink key={item.to} to={item.to} className={className}>
                  <item.icon className="size-4" />
                  {item.label}
                </CasinoOpenLink>
              );
            }
            return (
              <Link key={item.to} to={item.to} className={className}>
                <item.icon className="size-4" />
                {item.label}
              </Link>
            );
          })}
        </nav>
      </header>
      <main className="mx-auto max-w-5xl px-4 py-8 sm:px-6 lg:px-8">{children}</main>
    </div>
  );
}

export { Gift };
