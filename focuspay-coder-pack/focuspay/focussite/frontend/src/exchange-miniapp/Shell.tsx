import { WalletConfirmGate } from "@/components/WalletConfirmNotice";
import { ArrowLeftRight, Ellipsis, Receipt, Sparkles, Wallet } from "lucide-react";
import { NavLink, Navigate, Route, Routes } from "react-router-dom";
import { ExchangeScreen } from "./screens/ExchangeScreen";
import { LuckyScreen } from "./screens/LuckyScreen";
import { MoreScreen } from "./screens/MoreScreen";
import { OrderScreen } from "./screens/OrderScreen";
import { ProfileScreen } from "./screens/ProfileScreen";
import { ReferralScreen } from "./screens/ReferralScreen";

const TABS = [
  { to: "/", label: "Обмен", icon: ArrowLeftRight, end: true },
  { to: "/order", label: "Заявка", icon: Receipt, end: true },
  { to: "/wallet", label: "Кошелёк", icon: Wallet, end: false },
  { to: "/lucky", label: "Lucky", icon: Sparkles, end: true },
  { to: "/more", label: "Ещё", icon: Ellipsis, end: true },
];

export function Shell() {
  return (
    <div className="ex-app">
      <div className="ex-scroll">
        <Routes>
          <Route path="/" element={<ExchangeScreen />} />
          <Route path="/order" element={<OrderScreen />} />
          <Route path="/wallet" element={<ProfileScreen />} />
          <Route path="/wallet/referral" element={<ReferralScreen />} />
          <Route path="/profile" element={<Navigate to="/wallet" replace />} />
          <Route path="/profile/referral" element={<Navigate to="/wallet/referral" replace />} />
          <Route path="/lucky" element={<LuckyScreen />} />
          <Route path="/more" element={<MoreScreen />} />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </div>
      <WalletConfirmGate surface="miniapp" />
      <nav className="ex-tabs" aria-label="Разделы">
        {TABS.map((tab) => {
          const Icon = tab.icon;
          return (
            <NavLink key={tab.to} to={tab.to} end={tab.end} className="ex-tab">
              <Icon className="size-5" strokeWidth={1.75} />
              {tab.label}
            </NavLink>
          );
        })}
      </nav>
    </div>
  );
}
