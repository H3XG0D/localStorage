import { useEffect, useState } from "react";
import { Navigate, Route, Routes, useNavigate } from "react-router-dom";
import {
  Archive,
  Bell,
  Building2,
  CalendarDays,
  Coins,
  CreditCard,
  FileText,
  History,
  LayoutDashboard,
  ListTodo,
  MessageSquare,
  Plus,
  Star,
  Tag,
  UserCircle,
  Wallet,
  Zap,
  ShieldBan,
} from "lucide-react";
import { PanelShell, type NavSection } from "@/panel/ui/PanelShell";
import { OperatorChat } from "@/panel/operator/OperatorChat";
import { OperatorAi } from "@/panel/operator/OperatorAi";
import { OperatorAiWidget } from "@/panel/operator/OperatorAiWidget";
import { OperatorDevRequests } from "@/panel/operator/OperatorDevRequests";
import { OperatorChangelog } from "@/panel/operator/OperatorChangelog";
import { OperatorTemplates } from "@/panel/operator/OperatorTemplates";
import { OperatorAntispam } from "@/panel/operator/OperatorAntispam";
import { ReviewsPanel } from "@/panel/ui/ReviewsPanel";
import { BroadcastPanel } from "@/panel/ui/BroadcastPanel";
import { ClientSearch } from "@/panel/ui/ClientSearch";
import { OperatorDashboard } from "@/panel/operator/OperatorDashboard";
import { OperatorOrders } from "@/panel/operator/OperatorOrders";
import { OperatorOrderHistory } from "@/panel/operator/OperatorOrderHistory";
import { OperatorCreate } from "@/panel/operator/OperatorCreate";
import { ClientProfile } from "@/panel/operator/ClientProfile";
import { OperatorCasinoPayouts } from "@/panel/operator/OperatorCasinoPayouts";
import { OperatorPromo } from "@/panel/operator/OperatorPromo";
import { OperatorPayroll } from "@/panel/operator/OperatorPayroll";
import { OperatorPayoutRequisites } from "@/panel/operator/OperatorPayoutRequisites";
import { OperatorExternal } from "@/panel/operator/OperatorExternal";
import { OperatorShifts } from "@/panel/operator/OperatorShifts";
import { OperatorProfile } from "@/panel/operator/OperatorProfile";
import { getQueue, getReviewsPendingCount, listExternalDeals } from "@/panel/lib/operatorApi";
import { unreadCount } from "@/panel/lib/chatApi";
import { panelMe } from "@/panel/lib/panelAuth";
import { useAuthedPoll } from "@/panel/lib/useAuthedPoll";

const SECTIONS_BASE: NavSection[] = [
  {
    label: "Основное",
    items: [
      { to: "/ops", label: "Дашборд", icon: LayoutDashboard, end: true },
      { to: "/ops/orders", label: "Заявки", icon: FileText },
      { to: "/ops/external", label: "Внештатные обмены", icon: Building2 },
      { to: "/ops/history", label: "История", icon: Archive },
      { to: "/ops/create", label: "Создать заявку", icon: Plus },
    ],
  },
  {
    label: "Финансы",
    items: [
      { to: "/ops/payroll", label: "Зарплата", icon: Wallet },
      { to: "/ops/payout-requisites", label: "Приём средств", icon: CreditCard },
      { to: "/ops/casino-payouts", label: "Выплаты казино", icon: Coins },
      { to: "/ops/promo", label: "Промо и скидки", icon: Tag },
    ],
  },
  {
    label: "Управление",
    items: [
      { to: "/ops/chat", label: "Чаты", icon: MessageSquare },
      { to: "/ops/templates", label: "Шаблоны", icon: Zap },
      { to: "/ops/antispam", label: "Антиспам", icon: ShieldBan },
      { to: "/ops/dev-requests", label: "Задачи AI", icon: ListTodo },
      { to: "/ops/changelog", label: "Changelog", icon: History },
      { to: "/ops/shifts", label: "Смены", icon: CalendarDays },
      { to: "/ops/reviews", label: "Отзывы", icon: Star },
      { to: "/ops/broadcast", label: "Рассылка", icon: Bell },
      { to: "/ops/profile", label: "Профиль", icon: UserCircle },
    ],
  },
];

export function OperatorRoutes() {
  const navigate = useNavigate();
  const [reviewPending, setReviewPending] = useState(0);
  const [chatUnread, setChatUnread] = useState(0);
  const [ordersIncoming, setOrdersIncoming] = useState(0);
  const [externalOpen, setExternalOpen] = useState(0);
  const [permissions, setPermissions] = useState<string[] | null>(null);

  useEffect(() => {
    let cancelled = false;
    panelMe("operator")
      .then((me) => {
        if (!cancelled) {
          setPermissions(Array.isArray(me.permissions) ? me.permissions.map(String) : []);
        }
      })
      .catch(() => {
        if (!cancelled) setPermissions([]);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  useAuthedPoll(
    "operator",
    () => {
      getReviewsPendingCount()
        .then((r) => setReviewPending(r.count ?? 0))
        .catch(() => {});
      unreadCount("operator")
        .then((r) => setChatUnread(r.count ?? 0))
        .catch(() => {});
      getQueue()
        .then((q) => setOrdersIncoming(Number(q.exchange_incoming_count) || 0))
        .catch(() => {});
      listExternalDeals("open")
        .then((r) => setExternalOpen((r.deals ?? []).length))
        .catch(() => {});
    },
    15000,
  );

  const sections = SECTIONS_BASE.map((section) => ({
    ...section,
    items: section.items
      .filter((item) => {
        if (item.to === "/ops/templates") {
          if (permissions == null) return true;
          return permissions.includes("templates.view");
        }
        if (item.to === "/ops/antispam") {
          if (permissions == null) return true;
          return permissions.includes("antispam.phrases");
        }
        if (item.to === "/ops/payout-requisites") {
          if (permissions == null) return true;
          return permissions.includes("payout.requisites");
        }
        if (item.to === "/ops/casino-payouts") {
          if (permissions == null) return true;
          return permissions.includes("casino.payout");
        }
        if (item.to === "/ops/external") {
          if (permissions == null) return true;
          return permissions.includes("external_deals.view");
        }
        if (item.to === "/ops/history") {
          if (permissions == null) return true;
          return permissions.includes("orders.history");
        }
        return true;
      })
      .map((item) => {
        if (item.to === "/ops/reviews" && reviewPending > 0) {
          return { ...item, badge: reviewPending };
        }
        if (item.to === "/ops/chat" && chatUnread > 0) {
          return { ...item, badge: chatUnread };
        }
        if (item.to === "/ops/orders" && ordersIncoming > 0) {
          return { ...item, badge: ordersIncoming };
        }
        if (item.to === "/ops/external" && externalOpen > 0) {
          return { ...item, badge: externalOpen };
        }
        return item;
      }),
  }));

  const headerSlot = (
    <ClientSearch
      placeholder="Поиск: клиент или заявка (#...)"
      lookupOrders
      onPick={(u) => navigate(`/ops/client/${u.user_id ?? u.id}`)}
      onOrderPick={(order) => navigate(`/ops/orders?order=${encodeURIComponent(order.order_id)}`)}
    />
  );
  return (
    <PanelShell sections={sections} brand="FocusPay Ops" headerSlot={headerSlot}>
      <Routes>
        <Route path="/" element={<OperatorDashboard />} />
        <Route path="queue" element={<Navigate to="/ops/orders" replace />} />
        <Route path="orders" element={<OperatorOrders />} />
        <Route path="external" element={<OperatorExternal />} />
        <Route path="history" element={<OperatorOrderHistory />} />
        <Route path="create" element={<OperatorCreate />} />
        <Route path="client/:userId" element={<ClientProfile />} />
        <Route path="clients/:userId" element={<ClientProfile />} />
        <Route path="clients" element={<ClientProfile />} />
        <Route path="payroll" element={<OperatorPayroll />} />
        <Route path="payout-requisites" element={<OperatorPayoutRequisites />} />
        <Route path="casino-payouts" element={<OperatorCasinoPayouts />} />
        <Route path="promo" element={<OperatorPromo />} />
        <Route path="chat" element={<OperatorChat />} />
        <Route path="templates" element={<OperatorTemplates />} />
        <Route path="antispam" element={<OperatorAntispam />} />
        <Route path="ai" element={<OperatorAi />} />
        <Route path="dev-requests" element={<OperatorDevRequests />} />
        <Route path="changelog" element={<OperatorChangelog />} />
        <Route path="shifts" element={<OperatorShifts />} />
        <Route path="reviews" element={<ReviewsPanel scope="operator" />} />
        <Route path="broadcast" element={<BroadcastPanel scope="operator" />} />
        <Route path="profile" element={<OperatorProfile />} />
        <Route path="*" element={<Navigate to="/ops" replace />} />
      </Routes>
      <OperatorAiWidget />
    </PanelShell>
  );
}
