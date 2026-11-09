// Shared translucent site header (apple-design §12: content scrolls under a
// blurred material layer). Reused across public pages.
import { Link } from "react-router-dom";
import type { ReactNode } from "react";
import { Brand } from "@/components/Brand";
import { ThemeToggle } from "@/components/ThemeToggle";
import { Button } from "@/components/ui/button";
import { useSession } from "@/lib/session";
import { CasinoOpenLink } from "@/casino/casinoPaths";

export function PublicHeader({
  back,
  fluid,
  compactBrand,
  afterBrand,
  hidePublicLinks,
  homeTo = "/",
}: {
  back?: { to: string; label: string };
  fluid?: boolean;
  compactBrand?: boolean;
  afterBrand?: ReactNode;
  hidePublicLinks?: boolean;
  homeTo?: string;
}) {
  const { isAuthed } = useSession();
  return (
    <header className="sticky top-0 z-40 border-b border-border/80 bg-background/80 backdrop-blur-xl">
      <div className={fluid ? "portal-header-inner" : "mx-auto flex h-16 w-full max-w-7xl items-center justify-between px-4 sm:px-6 lg:px-8"}>
        <div className="flex min-w-0 flex-1 items-center gap-3">
          <Link to={homeTo} aria-label="FocusPay" className="shrink-0">
            <Brand compact={compactBrand} />
          </Link>
          {afterBrand}
        </div>
        <div className="flex shrink-0 items-center gap-2">
          <ThemeToggle />
          {!hidePublicLinks && (
            <>
              <Button variant="ghost" asChild>
                <CasinoOpenLink>FocusBet</CasinoOpenLink>
              </Button>
              {back ? (
                <Button variant="ghost" asChild>
                  <Link to={back.to}>{back.label}</Link>
                </Button>
              ) : (
                <Button variant="ghost" asChild>
                  <Link to={isAuthed ? "/cabinet" : "/login"}>{isAuthed ? "Кабинет" : "Войти"}</Link>
                </Button>
              )}
            </>
          )}
        </div>
      </div>
    </header>
  );
}
