// Telegram login: injects the official Login Widget when a bot username is
// available; falls back to an OAuth redirect URL (Firefox ETP / blocked
// third-party cookies). The widget calls a global callback with the auth payload.
import { useEffect, useRef, useState } from "react";
import { Send } from "lucide-react";
import { Button } from "@/components/ui/button";
import { getSiteConfig, getTelegramLoginUrl } from "@/lib/auth";

declare global {
  interface Window {
    onTelegramAuth?: (user: Record<string, unknown>) => void;
  }
}

export function TelegramLoginButton({
  onAuth,
  returnPath = "/login",
}: {
  onAuth: (payload: Record<string, unknown>) => void;
  returnPath?: string;
}) {
  const containerRef = useRef<HTMLDivElement>(null);
  const [botUsername, setBotUsername] = useState<string | null>(null);
  const [fallbackUrl, setFallbackUrl] = useState<string | null>(null);

  useEffect(() => {
    getSiteConfig()
      .then((c) => setBotUsername(c.telegram_bot_username || null))
      .catch(() => setBotUsername(null));
  }, []);

  useEffect(() => {
    if (!botUsername || !containerRef.current) return;
    window.onTelegramAuth = (user) => onAuth(user);
    const script = document.createElement("script");
    script.src = "https://telegram.org/js/telegram-widget.js?22";
    script.async = true;
    script.setAttribute("data-telegram-login", botUsername);
    script.setAttribute("data-size", "large");
    script.setAttribute("data-radius", "10");
    script.setAttribute("data-request-access", "write");
    script.setAttribute("data-onauth", "onTelegramAuth(user)");
    const el = containerRef.current;
    el.innerHTML = "";
    el.appendChild(script);
    // Prepare OAuth fallback in parallel.
    getTelegramLoginUrl(window.location.origin, returnPath)
      .then((r) => setFallbackUrl(r.url))
      .catch(() => undefined);
    return () => {
      el.innerHTML = "";
      delete window.onTelegramAuth;
    };
  }, [botUsername, onAuth, returnPath]);

  if (!botUsername) {
    // No bot configured — offer the redirect fallback if we have it.
    return fallbackUrl ? (
      <Button variant="outline" className="w-full" asChild>
        <a href={fallbackUrl}>
          <Send data-icon="inline-start" />
          Войти через Telegram
        </a>
      </Button>
    ) : null;
  }

  return (
    <div className="flex flex-col items-center gap-2">
      <div ref={containerRef} className="flex min-h-[48px] items-center justify-center" />
      {fallbackUrl && (
        <a href={fallbackUrl} className="text-xs text-muted-foreground underline-offset-4 hover:text-foreground hover:underline">
          Не открывается виджет? Войти через Telegram
        </a>
      )}
    </div>
  );
}
