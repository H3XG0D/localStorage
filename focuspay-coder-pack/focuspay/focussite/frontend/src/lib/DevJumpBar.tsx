import { useEffect, useMemo, useRef, useState } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import { isLocalDev } from "@/lib/isLocalDev";

type SurfaceId = "admin" | "ops" | "exchanger" | "partner" | "site" | "exchange" | "cabinet";

interface JumpItem {
  label: string;
  href: string;
}

const SURFACES: Array<{ id: SurfaceId; label: string; href: string; match: (path: string) => boolean }> = [
  { id: "admin", label: "Админ", href: "/x8", match: (p) => p.startsWith("/x8") },
  { id: "ops", label: "Оператор", href: "/ops", match: (p) => p.startsWith("/ops") },
  { id: "exchanger", label: "Внештат", href: "/exchanger", match: (p) => p.startsWith("/exchanger") },
  { id: "partner", label: "Партнёр", href: "/partner", match: (p) => p.startsWith("/partner") },
  { id: "site", label: "Сайт", href: "/", match: (p) => p === "/" },
  { id: "exchange", label: "Обмен", href: "/exchange", match: (p) => p.startsWith("/exchange") },
  { id: "cabinet", label: "Кабинет", href: "/cabinet", match: (p) => p.startsWith("/cabinet") },
];

const SCREENS: Record<SurfaceId, JumpItem[]> = {
  admin: [
    { label: "Обзор", href: "/x8" },
    { label: "Заявки", href: "/x8/orders" },
    { label: "Пользователи", href: "/x8/users" },
    { label: "Чаты", href: "/x8/chat" },
    { label: "AI-задачи", href: "/x8/ai-tasks" },
    { label: "Стикеры", href: "/x8/sticker-ai" },
    { label: "Финансы", href: "/x8?tab=finance" },
    { label: "Трафик", href: "/x8?tab=traffic" },
    { label: "Клиенты", href: "/x8?tab=clients" },
    { label: "Каналы", href: "/x8?tab=channels" },
    { label: "Балансы", href: "/x8/balances" },
    { label: "Цены", href: "/x8/pricing" },
    { label: "Зарплаты", href: "/x8/payroll" },
    { label: "Выплаты оп.", href: "/x8/operator-payroll" },
    { label: "Расходы", href: "/x8/expenses" },
    { label: "Внешние обмены", href: "/x8/external" },
    { label: "USDT", href: "/x8/usdt" },
    { label: "Промо", href: "/x8/promo" },
    { label: "FocusLucky", href: "/x8/focus-lucky" },
    { label: "Партнёры", href: "/x8/partners" },
    { label: "Отзывы", href: "/x8/reviews" },
    { label: "Рассылка", href: "/x8/broadcast" },
    { label: "Операторы", href: "/x8/operators" },
    { label: "Смены", href: "/x8/shifts" },
    { label: "Безопасность", href: "/x8/security" },
    { label: "Настройки", href: "/x8/settings" },
  ],
  ops: [
    { label: "Дашборд", href: "/ops" },
    { label: "Заявки", href: "/ops/orders" },
    { label: "Создать", href: "/ops/create" },
    { label: "Зарплата", href: "/ops/payroll" },
    { label: "Промо", href: "/ops/promo" },
    { label: "Чаты", href: "/ops/chat" },
    { label: "Шаблоны", href: "/ops/templates" },
    { label: "Задачи AI", href: "/ops/dev-requests" },
    { label: "Changelog", href: "/ops/changelog" },
    { label: "Смены", href: "/ops/shifts" },
    { label: "Отзывы", href: "/ops/reviews" },
    { label: "Рассылка", href: "/ops/broadcast" },
    { label: "Профиль", href: "/ops/profile" },
  ],
  exchanger: [
    { label: "Обзор", href: "/exchanger" },
    { label: "Сделки", href: "/exchanger?tab=deals" },
    { label: "Выводы", href: "/exchanger?tab=payouts" },
    { label: "История", href: "/exchanger?tab=history" },
    { label: "Чат", href: "/exchanger?tab=chat" },
  ],
  partner: [{ label: "Кабинет", href: "/partner" }],
  site: [
    { label: "Главная", href: "/" },
    { label: "Вход", href: "/login" },
    { label: "Регистрация", href: "/register" },
  ],
  exchange: [
    { label: "Калькулятор", href: "/exchange" },
  ],
  cabinet: [
    { label: "Обзор", href: "/cabinet" },
    { label: "Настройки", href: "/cabinet/settings" },
    { label: "Рефералка", href: "/cabinet/referral" },
    { label: "FocusLucky", href: "/casino/play/raffle" },
  ],
};

const LS_KEY = "focuspay_dev_jump_collapsed";

function isPanelPath(path: string) {
  return path.startsWith("/x8") || path.startsWith("/ops");
}

function pathOf(href: string) {
  return href.split("?")[0];
}

function screenActive(href: string, pathname: string, search: string) {
  const [p, q] = href.split("?");
  if (p === "/x8" || p === "/ops" || p === "/" || p === "/exchanger" || p === "/partner" || p === "/cabinet" || p === "/exchange") {
    if (q) return pathname === p && search.replace(/^\?/, "") === q;
    if (p === "/exchanger") return pathname === "/exchanger" && !search.includes("tab=");
    if (p === "/x8" || p === "/ops") return pathname === p;
    return pathname === p;
  }
  return pathname === p || pathname.startsWith(`${p}/`);
}

export function DevJumpBar() {
  const loc = useLocation();
  const navigate = useNavigate();
  const ref = useRef<HTMLDivElement>(null);
  const [collapsed, setCollapsed] = useState(() => window.localStorage.getItem(LS_KEY) === "1");

  const surface = useMemo(
    () => SURFACES.find((s) => s.match(loc.pathname)) ?? SURFACES[0],
    [loc.pathname],
  );
  const screens = SCREENS[surface.id];

  useEffect(() => {
    if (!isLocalDev()) return;
    const node = ref.current;
    if (!node) return;
    const apply = () => {
      document.documentElement.style.paddingTop = `${node.offsetHeight}px`;
    };
    apply();
    const ro = new ResizeObserver(apply);
    ro.observe(node);
    return () => {
      ro.disconnect();
      document.documentElement.style.paddingTop = "";
    };
  }, [collapsed, loc.pathname]);

  if (!isLocalDev()) return null;

  function go(href: string) {
    const dest = pathOf(href);
    if (isPanelPath(dest) !== isPanelPath(loc.pathname)) {
      window.location.assign(href);
      return;
    }
    navigate(href);
  }

  function toggle() {
    setCollapsed((c) => {
      const next = !c;
      window.localStorage.setItem(LS_KEY, next ? "1" : "0");
      return next;
    });
  }

  return (
    <div
      ref={ref}
      role="navigation"
      aria-label="Dev: поверхности FocusPay"
      style={{
        position: "fixed",
        top: 0,
        left: 0,
        right: 0,
        zIndex: 99999,
        background: "#0c0c0c",
        color: "#e8e8e8",
        borderBottom: "1px solid #2a2a2a",
        fontFamily: "Inter, ui-sans-serif, system-ui, sans-serif",
        fontSize: 12,
        lineHeight: 1.2,
      }}
    >
      <div style={{ display: "flex", alignItems: "center", gap: 8, padding: "7px 10px", overflowX: "auto" }}>
        <span
          style={{
            flexShrink: 0,
            fontSize: 10,
            fontWeight: 700,
            letterSpacing: "0.12em",
            color: "#8a8a8a",
            padding: "2px 6px",
            border: "1px solid #333",
            borderRadius: 4,
          }}
        >
          DEV
        </span>
        {SURFACES.map((item) => {
          const on = item.id === surface.id;
          return (
            <button
              key={item.id}
              type="button"
              onClick={() => go(item.href)}
              style={{
                flexShrink: 0,
                border: on ? "1px solid #fff" : "1px solid #333",
                background: on ? "#fff" : "transparent",
                color: on ? "#111" : "#d0d0d0",
                borderRadius: 999,
                padding: "4px 10px",
                fontWeight: on ? 700 : 500,
                cursor: "pointer",
              }}
            >
              {item.label}
            </button>
          );
        })}
        <button
          type="button"
          onClick={toggle}
          aria-label={collapsed ? "Показать экраны" : "Скрыть экраны"}
          style={{
            marginLeft: "auto",
            flexShrink: 0,
            border: 0,
            background: "transparent",
            color: "#888",
            cursor: "pointer",
            fontSize: 11,
          }}
        >
          {collapsed ? "экраны ▾" : "свернуть ▴"}
        </button>
      </div>
      {!collapsed && (
        <div
          style={{
            display: "flex",
            flexWrap: "wrap",
            gap: 4,
            padding: "0 10px 8px 52px",
            borderTop: "1px solid #1f1f1f",
            paddingTop: 6,
          }}
        >
          {screens.map((item) => {
            const on = screenActive(item.href, loc.pathname, loc.search);
            return (
              <button
                key={item.href}
                type="button"
                onClick={() => go(item.href)}
                style={{
                  border: 0,
                  background: on ? "#2a2a2a" : "transparent",
                  color: on ? "#fff" : "#9a9a9a",
                  borderRadius: 4,
                  padding: "3px 8px",
                  cursor: "pointer",
                  fontWeight: on ? 600 : 400,
                }}
              >
                {item.label}
              </button>
            );
          })}
        </div>
      )}
    </div>
  );
}
