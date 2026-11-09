import { Navigate, Route, Routes, useLocation } from "react-router-dom";
import { PublicHome } from "@/pages/PublicHome";
import { Exchange } from "@/pages/Exchange";
import { Login } from "@/pages/Login";
import { TelegramBotLogin } from "@/pages/TelegramBotLogin";
import { Register } from "@/pages/Register";
import { Forgot } from "@/pages/Forgot";
import { Order } from "@/pages/Order";
import { Cabinet } from "@/pages/Cabinet";
import { CabinetSettings } from "@/pages/CabinetSettings";
import { CabinetReferral } from "@/pages/CabinetReferral";
import { CabinetBattle } from "@/pages/CabinetBattle";
import CasinoCreatorDashboard from "@/pages/CasinoCreatorDashboard";
import { CasinoTokensPreview } from "@/casino/CasinoTokensPreview";
import { CasinoShell } from "@/casino/CasinoShell";
import { CasinoOverlay, isCasinoOverlayLocation } from "@/casino/casinoOverlay";
import { casinoChildRoutes } from "@/casino/casinoRoutes";
import { PartnerLoginPage, PartnerDashboardPage } from "@/pages/PartnerPortal";
import { ExchangerLoginPage, ExchangerDashboardPage } from "@/pages/ExchangerPortal";
import { RefLanding } from "@/pages/RefLanding";
import { WalletConfirmGate } from "@/components/WalletConfirmNotice";
import { useSession } from "@/lib/session";
import { isLocalDev } from "@/lib/isLocalDev";
import { authPathWithNext } from "@/lib/postLoginPath";

const siteCasinoRoute = (
  <Route path="/casino" element={<CasinoShell />}>
    {casinoChildRoutes}
  </Route>
);

const overlayCasinoRoute = (
  <Route path="/casino" element={<CasinoShell />}>
    {casinoChildRoutes}
  </Route>
);

const siteRoutes = (
  <>
    <Route path="/" element={<PublicHome />} />
    <Route path="/exchange" element={<Exchange />} />
    <Route path="/exchange/order/:orderId" element={<Order />} />

    <Route path="/login" element={<Login />} />
    <Route path="/login/telegram" element={<TelegramBotLogin />} />
    <Route path="/register" element={<Register />} />
    <Route path="/forgot" element={<Forgot />} />

    <Route
      path="/cabinet"
      element={
        <RequireAuth>
          <Cabinet />
        </RequireAuth>
      }
    />
    <Route
      path="/cabinet/settings"
      element={
        <RequireAuth>
          <CabinetSettings />
        </RequireAuth>
      }
    />
    <Route
      path="/cabinet/referral"
      element={
        <RequireAuth>
          <CabinetReferral />
        </RequireAuth>
      }
    />
    <Route
      path="/cabinet/battle"
      element={
        <RequireAuth>
          <CabinetBattle />
        </RequireAuth>
      }
    />

    <Route path="/ref/:token" element={<RefLanding kind="ref" />} />
    <Route path="/invite/:token" element={<RefLanding kind="invite" />} />

    <Route path="/partner/login" element={<PartnerLoginPage />} />
    <Route path="/partner" element={<PartnerDashboardPage />} />
    <Route path="/exchanger/login" element={<ExchangerLoginPage />} />
    <Route path="/exchanger" element={<ExchangerDashboardPage />} />

    <Route path="/casino/tokens" element={<CasinoTokensPreview />} />
    <Route
      path="/casino/creator"
      element={
        <RequireAuth>
          <CasinoCreatorDashboard />
        </RequireAuth>
      }
    />
    {siteCasinoRoute}

    <Route path="*" element={<Navigate to="/" replace />} />
  </>
);

// NOTE: the admin (/x8) and operator (/ops) SPAs are served separately by nginx
// (panel.html) and are intentionally NOT handled here.
export default function App() {
  const location = useLocation();
  const overlayBackground = isCasinoOverlayLocation(location);

  return (
    <>
      <Routes location={overlayBackground ?? location}>{siteRoutes}</Routes>
      {overlayBackground ? (
        <CasinoOverlay>
          <Routes location={location}>{overlayCasinoRoute}</Routes>
        </CasinoOverlay>
      ) : null}
      <WalletConfirmGate surface="site" />
    </>
  );
}

function RequireAuth({ children }: { children: React.ReactNode }) {
  const { isAuthed, loading } = useSession();
  const location = useLocation();
  if (isLocalDev()) return <>{children}</>;
  if (loading) return null;
  if (!isAuthed) {
    const from = `${location.pathname}${location.search}`;
    return <Navigate to={authPathWithNext("/login", from)} replace state={{ from }} />;
  }
  return <>{children}</>;
}
