import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { COMMUNITY_URL, FOCUS_BET_URL, FOCUS_VPN_URL, REVIEWS_URL, supportUrl } from "../links";
import { PREVIEW } from "../preview";
import { openExternal } from "../telegram";
import { Card, PageTitle, PrimaryButton, ProgressLine } from "../ui";

interface VpnProgress {
  exchanges: { have: number; need: number };
  invited: { have: number; need: number };
  purchase_open: boolean;
  plans: { title?: string; price_rub?: number }[];
}

const PREVIEW_VPN: VpnProgress = {
  exchanges: { have: 4, need: 10 },
  invited: { have: 2, need: 30 },
  purchase_open: false,
  plans: [
    { title: "Неделя", price_rub: 300 },
    { title: "Месяц", price_rub: 990 },
    { title: "3 месяца", price_rub: 2490 },
  ],
};

function LinkRow({ label, href }: { label: string; href: string }) {
  return (
    <button type="button" onClick={() => openExternal(href)} className="flex h-12 items-center justify-between rounded-xl border border-border px-3 text-left text-sm font-semibold">
      {label}
      <span className="text-muted-foreground">↗</span>
    </button>
  );
}

export function MoreScreen() {
  const [site, setSite] = useState(PREVIEW ? "https://focuspay.org" : "https://focuspay.org");
  const [vpn, setVpn] = useState<VpnProgress | null>(PREVIEW ? PREVIEW_VPN : null);

  useEffect(() => {
    if (PREVIEW) return;
    api<{ public_site_url?: string }>("/public/site-config", { scope: null })
      .then((config) => {
        if (config.public_site_url) setSite(config.public_site_url);
      })
      .catch(() => undefined);
    api<VpnProgress>("/user/vpn-progress")
      .then(setVpn)
      .catch(() => undefined);
  }, []);

  const plans = (vpn?.plans || []).map((plan) => plan.title).filter(Boolean).join(", ");

  return (
    <div className="flex flex-col gap-4">
      <PageTitle title="Ещё" />
      <Card>
        <p className="text-sm leading-6">
          FocusPay меняет <b>BTC, USDT, LTC, TRX</b> на рубли и обратно.
        </p>
      </Card>
      <div className="flex flex-col gap-2">
        <LinkRow label="Поддержка" href={supportUrl(site)} />
        <LinkRow label="Чат" href={COMMUNITY_URL} />
        <LinkRow label="Отзывы" href={REVIEWS_URL} />
        <LinkRow label="Сайт focuspay.org" href={site} />
      </div>
      <Card>
        <p className="text-sm font-semibold">FocusVPN</p>
        <p className="mt-2 text-sm leading-6 text-muted-foreground">
          Пробный период бесплатно. Оплата с баланса FocusPay{plans ? `: ${plans}` : ": неделя, месяц, 3 месяца"}.
        </p>
        <div className="mt-4 flex flex-col gap-3">
          <ProgressLine label="Обмены" have={vpn?.exchanges.have ?? 0} need={vpn?.exchanges.need ?? 10} />
          <ProgressLine label="Приглашённые" have={vpn?.invited.have ?? 0} need={vpn?.invited.need ?? 30} />
        </div>
        {vpn?.purchase_open ? <p className="mt-3 text-sm">Тарифы для вас уже открыты.</p> : null}
        <div className="mt-4">
          <PrimaryButton onClick={() => openExternal(FOCUS_VPN_URL)}>Открыть FocusVPN</PrimaryButton>
        </div>
      </Card>
      <Card>
        <p className="text-sm font-semibold">FocusBet</p>
        <p className="mt-2 text-sm text-muted-foreground">Игры открываются в боте FocusBet.</p>
        <div className="mt-4">
          <PrimaryButton onClick={() => openExternal(FOCUS_BET_URL)}>Открыть FocusBet</PrimaryButton>
        </div>
      </Card>
    </div>
  );
}
