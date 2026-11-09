import { useState } from "react";
import { PageHeader, Tabs } from "@/panel/ui/primitives";
import { PurchasesTab } from "@/panel/admin/vpn/PurchasesTab";
import { ReconTab } from "@/panel/admin/vpn/ReconTab";
import { SettingsTab } from "@/panel/admin/vpn/SettingsTab";
import { SummaryTab } from "@/panel/admin/vpn/SummaryTab";
import { UserTab } from "@/panel/admin/vpn/UserTab";

const TABS = [
  { id: "summary", label: "Сводка" },
  { id: "settings", label: "Тарифы и доступ" },
  { id: "purchases", label: "Покупки" },
  { id: "user", label: "Пользователь" },
  { id: "recon", label: "Сверка" },
];

export function AdminVpn() {
  const [tab, setTab] = useState("summary");
  const [telegramId, setTelegramId] = useState("");
  const openUser = (id: string) => {
    setTelegramId(id);
    setTab("user");
  };
  return (
    <div className="space-y-5">
      <PageHeader title="FocusVPN" subtitle="Продажи из баланса FocusPay, тарифы, устройства и сверка с control plane" />
      <Tabs value={tab} onChange={setTab} items={TABS} />
      {tab === "summary" ? <SummaryTab /> : null}
      {tab === "settings" ? <SettingsTab /> : null}
      {tab === "purchases" ? <PurchasesTab onOpenUser={openUser} /> : null}
      {tab === "user" ? <UserTab telegramId={telegramId} onChange={setTelegramId} /> : null}
      {tab === "recon" ? <ReconTab onOpenUser={openUser} /> : null}
    </div>
  );
}
