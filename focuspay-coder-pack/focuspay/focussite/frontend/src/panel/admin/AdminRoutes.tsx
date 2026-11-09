import { useState } from "react";
import { Navigate, Route, Routes } from "react-router-dom";
import {
  Activity,
  Bell,
  Bot,
  Building2,
  CalendarDays,
  Coins,
  CreditCard,
  Dice5,
  FileText,
  History,
  LayoutDashboard,
  MessageSquare,
  Receipt,
  RefreshCw,
  Settings2,
  Shield,
  Sparkles,
  Star,
  Trophy,
  Sticker,
  Tag,
  Users,
  UsersRound,
  Wallet,
  Wand2,
} from "lucide-react";
import { PanelShell, type NavSection } from "@/panel/ui/PanelShell";
import { SupportChat } from "@/panel/ui/SupportChat";
import { ReviewsPanel } from "@/panel/ui/ReviewsPanel";
import { BroadcastPanel } from "@/panel/ui/BroadcastPanel";
import { AdminDashboard } from "@/panel/admin/AdminDashboard";
import { AdminOrders } from "@/panel/admin/AdminOrders";
import { AdminUsers } from "@/panel/admin/AdminUsers";
import { AdminBalances } from "@/panel/admin/AdminBalances";
import { AdminPricing } from "@/panel/admin/AdminPricing";
import { AdminAutopilot } from "@/panel/admin/AdminAutopilot";
import { AdminVpn } from "@/panel/admin/AdminVpn";
import { AdminPayroll } from "@/panel/admin/AdminPayroll";
import { AdminOperatorPayroll } from "@/panel/admin/AdminOperatorPayroll";
import { AdminExpenses } from "@/panel/admin/AdminExpenses";
import { AdminRecurringExpenses } from "@/panel/admin/AdminRecurringExpenses";
import { AdminExternal } from "@/panel/admin/AdminExternal";
import { AdminExchangerDetail } from "@/panel/admin/AdminExchangerDetail";
import { AdminExchangerBot } from "@/panel/admin/AdminExchangerBot";
import { AdminUsdt } from "@/panel/admin/AdminUsdt";
import { AdminOperators } from "@/panel/admin/AdminOperators";
import { AdminOperatorDetail } from "@/panel/admin/AdminOperatorDetail";
import { AdminShifts } from "@/panel/admin/AdminShifts";
import { AdminPromo } from "@/panel/admin/AdminPromo";
import { AdminPromoDetail } from "@/panel/admin/AdminPromoDetail";
import { AdminPartners } from "@/panel/admin/AdminPartners";
import { AdminPartnerDetail } from "@/panel/admin/AdminPartnerDetail";
import { AdminFocusLucky } from "@/panel/admin/AdminFocusLucky";
import { AdminCasinoTournaments } from "@/panel/admin/AdminCasinoTournaments";
import { AdminSecurity } from "@/panel/admin/AdminSecurity";
import { AdminSettings } from "@/panel/admin/AdminSettings";
import { AdminAiTasks } from "@/panel/admin/AdminAiTasks";
import { AdminAiWidget } from "@/panel/admin/AdminAiWidget";
import { AdminStickerAi } from "@/panel/admin/AdminStickerAi";
import {
  CasinoDashboard,
  CasinoRisk,
  CasinoAudit,
  CasinoGames,
  CasinoSettings,
  CasinoCreatorPayouts,
  CasinoHouse,
} from "@/panel/admin/Casino";
import { unreadCount } from "@/panel/lib/chatApi";
import { useAuthedPoll } from "@/panel/lib/useAuthedPoll";

const SECTIONS: NavSection[] = [
  {
    label: "Работа",
    items: [
      { to: "/x8", label: "Обзор", icon: LayoutDashboard, end: true },
      { to: "/x8/orders", label: "Заявки", icon: FileText },
      { to: "/x8/users", label: "Пользователи", icon: Users },
      { to: "/x8/chat", label: "Чаты", icon: MessageSquare },
      { to: "/x8/ai-tasks", label: "AI-задачи", icon: Wand2 },
      { to: "/x8/sticker-ai", label: "Стикеры", icon: Sticker },
    ],
  },
  {
    label: "Деньги",
    items: [
      { to: "/x8/balances", label: "Балансы", icon: Wallet },
      { to: "/x8/pricing", label: "Цены и комиссии", icon: CreditCard },
      { to: "/x8/autopilot", label: "Автопилот", icon: Bot },
      { to: "/x8/vpn", label: "VPN", icon: Shield },
      { to: "/x8/payroll", label: "Зарплаты", icon: Coins },
      { to: "/x8/operator-payroll", label: "Выплаты операторам", icon: Wallet },
      { to: "/x8/expenses", label: "Расходы (разовые)", icon: Receipt },
      { to: "/x8/recurring-expenses", label: "Подписки и ROI", icon: RefreshCw },
      { to: "/x8/external", label: "Внешние обмены", icon: Building2 },
      { to: "/x8/exchanger-bot", label: "Бот внештатников", icon: Bot },
      { to: "/x8/usdt", label: "Выпуск USDT", icon: Coins },
    ],
  },
  {
    label: "Рост",
    items: [
      { to: "/x8/promo", label: "Промокоды", icon: Tag },
      { to: "/x8/focus-lucky", label: "FocusLucky", icon: Sparkles },
      { to: "/x8/casino-tournaments", label: "Турниры казино", icon: Trophy },
      { to: "/x8/partners", label: "Партнёры", icon: Building2 },
      { to: "/x8/reviews", label: "Отзывы", icon: Star },
      { to: "/x8/broadcast", label: "Рассылка", icon: Bell },
    ],
  },
  {
    label: "Казино",
    items: [
      { to: "/x8/casino", label: "Дашборд", icon: Dice5, end: true },
      { to: "/x8/casino/risk", label: "Риск", icon: Activity },
      { to: "/x8/casino/games", label: "Игры", icon: FileText },
      { to: "/x8/casino/settings", label: "Настройки", icon: Settings2 },
      { to: "/x8/casino/audit", label: "Аудит", icon: History },
      { to: "/x8/casino/house", label: "Роботы PvP", icon: Wallet },
      { to: "/x8/casino/creator-payouts", label: "Выплаты создателя", icon: Wallet },
    ],
  },
  {
    label: "Управление",
    items: [
      { to: "/x8/operators", label: "Операторы", icon: UsersRound },
      { to: "/x8/shifts", label: "Смены", icon: CalendarDays },
      { to: "/x8/security", label: "Безопасность", icon: Shield },
      { to: "/x8/settings", label: "Настройки", icon: Settings2 },
    ],
  },
];

export function AdminRoutes() {
  const [chatUnread, setChatUnread] = useState(0);
  useAuthedPoll(
    "admin",
    () => {
      unreadCount("admin")
        .then((r) => setChatUnread(r.count ?? 0))
        .catch(() => {});
    },
    15000,
  );

  const sections = SECTIONS.map((section) => ({
    ...section,
    items: section.items.map((item) =>
      item.to === "/x8/chat" && chatUnread > 0 ? { ...item, badge: chatUnread } : item,
    ),
  }));

  return (
    <PanelShell sections={sections} brand="FocusPay Admin">
      <Routes>
        <Route path="/" element={<AdminDashboard />} />
        <Route path="orders" element={<AdminOrders />} />
        <Route path="users" element={<AdminUsers />} />
        <Route path="chat" element={<SupportChat scope="admin" />} />
        <Route path="ai-tasks" element={<AdminAiTasks />} />
        <Route path="sticker-ai" element={<AdminStickerAi />} />
        <Route path="sticker-ai/tasks/:taskId" element={<AdminStickerAi />} />
        <Route path="stats" element={<Navigate to="/x8?tab=finance" replace />} />
        <Route path="balances" element={<AdminBalances />} />
        <Route path="pricing" element={<AdminPricing />} />
        <Route path="autopilot" element={<AdminAutopilot />} />
        <Route path="vpn" element={<AdminVpn />} />
        <Route path="payroll" element={<AdminPayroll />} />
        <Route path="operator-payroll" element={<AdminOperatorPayroll />} />
        <Route path="expenses" element={<AdminExpenses />} />
        <Route path="recurring-expenses" element={<AdminRecurringExpenses />} />
        <Route path="external" element={<AdminExternal />} />
        <Route path="external/:id" element={<AdminExchangerDetail />} />
        <Route path="exchanger-bot" element={<AdminExchangerBot />} />
        <Route path="usdt" element={<AdminUsdt />} />
        <Route path="operators" element={<AdminOperators />} />
        <Route path="operators/:id" element={<AdminOperatorDetail />} />
        <Route path="shifts" element={<AdminShifts />} />
        <Route path="promo" element={<AdminPromo />} />
        <Route path="promo/:id" element={<AdminPromoDetail />} />
        <Route path="focus-lucky" element={<AdminFocusLucky />} />
        <Route path="casino-tournaments" element={<AdminCasinoTournaments />} />
        <Route path="partners" element={<AdminPartners />} />
        <Route path="partners/:id" element={<AdminPartnerDetail />} />
        <Route path="reviews" element={<ReviewsPanel scope="admin" />} />
        <Route path="broadcast" element={<BroadcastPanel scope="admin" />} />
        <Route path="casino" element={<CasinoDashboard />} />
        <Route path="casino/risk" element={<CasinoRisk />} />
        <Route path="casino/games" element={<CasinoGames />} />
        <Route path="casino/settings" element={<CasinoSettings />} />
        <Route path="casino/audit" element={<CasinoAudit />} />
        <Route path="casino/house" element={<CasinoHouse />} />
        <Route path="casino/creator-payouts" element={<CasinoCreatorPayouts />} />
        <Route path="security" element={<AdminSecurity />} />
        <Route path="settings" element={<AdminSettings />} />
        <Route path="*" element={<Navigate to="/x8" replace />} />
      </Routes>
      <AdminAiWidget />
    </PanelShell>
  );
}
