import { useCallback, useEffect, useState, type ReactNode } from "react";
import { Link } from "react-router-dom";
import { ChevronDown, ExternalLink, RefreshCw } from "lucide-react";
import { toast } from "sonner";
import {
  getAutopilotFunds,
  getAutopilotOverview,
  getOperatorPayrollSettings,
  getUsdRateRub,
  patchAutopilot,
  requeueAutopilotOrder,
  rotateAutopilotAddress,
  trustAutopilotTopup,
  type Dict,
} from "@/panel/lib/adminApi";
import { PanelApiError } from "@/panel/lib/panelApi";
import { useAuthedPoll } from "@/panel/lib/useAuthedPoll";
import { CopyField } from "@/panel/ui/CopyField";
import {
  Badge,
  Button,
  Card,
  Field,
  Input,
  Kpi,
  PageHeader,
  Table,
  cx,
  type BadgeTone,
  type Column,
} from "@/panel/ui/primitives";
import { MOMENT_BADGE, PAYOUT_STATUS, REQUEUE_ERRORS, TOPUP_ERRORS, reasonLabel } from "@/panel/admin/autopilotReasons";

type SettingSpec = { key: string; label: string; hint?: string; kind: "bool" | "number" | "wallet"; money?: true };

const SECTIONS: { title: string; hint: string; fields: SettingSpec[] }[] = [
  {
    title: "Общее",
    hint: "Главный выключатель гасит всё сразу. В тестовом режиме автопилот только записывает, что сделал бы.",
    fields: [
      {
        key: "auto_mode_enabled",
        label: "Автопилот включён",
        hint: "Новые завершённые заявки после включения считаются по ставкам в разделе «Зарплаты», не по фонду 30%",
        kind: "bool",
      },
      {
        key: "auto_no_shift_shadow_mode",
        label: "Тестовый режим",
        hint: "Ничего не выдаёт и не отправляет — только журнал решений",
        kind: "bool",
      },
    ],
  },
  {
    title: "Реквизиты без смены",
    hint: "Когда операторов нет, постоянный клиент получает реквизиты на покупку сам.",
    fields: [
      { key: "auto_no_shift_enabled", label: "Выдавать реквизиты", kind: "bool" },
      { key: "auto_no_shift_min_buy_paid", label: "Покупок до автопилота", hint: "Оплаченных обменов у клиента", kind: "number" },
      { key: "auto_no_shift_max_rub", label: "Макс. сумма заявки, ₽", kind: "number", money: true },
    ],
  },
  {
    title: "Автовыплата крипты",
    hint: "Только после подтверждения оплаты Payfast (трейдер подтвердил), затем отправка с горячего кошелька.",
    fields: [
      { key: "auto_payout_enabled", label: "Отправлять крипту", kind: "bool" },
      { key: "auto_payout_max_rub", label: "Макс. выплата, ₽", kind: "number", money: true },
      { key: "auto_payout_daily_cap_rub", label: "Лимит в сутки, ₽", kind: "number", money: true },
      { key: "auto_min_hot_balance_rub", label: "Мин. остаток кошелька, ₽", hint: "Ниже — автопилот не отправляет", kind: "number", money: true },
      {
        key: "auto_payout_wait_funds_max_min",
        label: "Ждать пополнение, мин",
        hint: "Пока пополнение не подтвердилось, выплаты ждут; дольше — уходят оператору. 0 — сразу оператору",
        kind: "number",
      },
      {
        key: "auto_payout_trusted_topups",
        label: "Доверенные пополнения",
        hint: "Неподтверждённый BTC на горячем кошельке тратится сразу, без ожидания блока",
        kind: "bool",
      },
    ],
  },
  {
    title: "Автовывод баланса",
    hint: "Кэшбэк и реферальные: резерв, проверка клиента, затем отправка.",
    fields: [
      { key: "auto_withdraw_enabled", label: "Выводить автоматически", kind: "bool" },
      { key: "auto_withdraw_max_rub", label: "Макс. вывод, ₽", kind: "number", money: true },
    ],
  },
  {
    title: "Ручные заявки",
    hint: "С кошелька проекта финансовый оператор отправляет BTC/LTC кнопкой с кодом 2FA — ключей у него нет. USDT/TRX всегда со своего кошелька.",
    fields: [
      { key: "manual_payout_wallet", label: "Откуда платим", kind: "wallet" },
      { key: "manual_wallet_payout_max_rub", label: "Макс. одна отправка, ₽", kind: "number", money: true },
      { key: "manual_wallet_payout_operator_daily_rub", label: "На оператора в сутки, ₽", kind: "number", money: true },
    ],
  },
  {
    title: "Потолки кошелька проекта",
    hint: "Лимиты в монете на горячем кошельке. Рублёвые поля выше их не меняют — после «Сохранить» уходят на подписант сами.",
    fields: [
      { key: "signer_max_tx_ltc", label: "LTC за одну отправку", kind: "number" },
      { key: "signer_daily_cap_ltc", label: "LTC за сутки", kind: "number" },
      { key: "signer_max_tx_btc", label: "BTC за одну отправку", kind: "number" },
      { key: "signer_daily_cap_btc", label: "BTC за сутки", kind: "number" },
    ],
  },
];

const WALLET_OPTIONS = [
  { value: "operator", label: "Кошелёк оператора", hint: "оператор вставляет хеш" },
  { value: "project", label: "Кошелёк проекта", hint: "кнопка + 2FA" },
];

const ALL_FIELDS = SECTIONS.flatMap((s) => s.fields);

const EXPLORER: Record<string, (tx: string) => string> = {
  btc: (tx) => `https://mempool.space/tx/${tx}`,
  ltc: (tx) => `https://litecoinspace.org/tx/${tx}`,
};

const rub = (v: unknown) => `${Math.round(Number(v) || 0).toLocaleString("ru-RU")} ₽`;
const usdFmt = new Intl.NumberFormat("en-US", { style: "currency", currency: "USD", minimumFractionDigits: 2, maximumFractionDigits: 2 });
/** Доллары по сырому курсу USDT, с центами. Пустая строка — курса нет. */
const usd = (v: unknown, rate: number) => {
  if (!(rate > 0)) return "";
  const n = (Number(v) || 0) / rate;
  return Number.isFinite(n) ? usdFmt.format(n) : "";
};
const rubUsd = (v: unknown, rate: number) => {
  const dollars = usd(v, rate);
  return dollars ? `${rub(v)} · ${dollars}` : rub(v);
};
const joinHint = (...parts: string[]) => parts.filter(Boolean).join(" · ");

function MoneyFigure({ amount, rate }: { amount: unknown; rate: number }) {
  const dollars = usd(amount, rate);
  return (
    <span className="block">
      <span className="block">{rub(amount)}</span>
      {dollars ? <span className="mt-0.5 block text-[15px] font-semibold leading-none text-[var(--text-secondary)]">{dollars}</span> : null}
    </span>
  );
}
const coinAmt = (v: unknown) => (v == null ? "—" : Number(v).toLocaleString("ru-RU", { maximumFractionDigits: 8 }));
const time = (v: unknown) =>
  v ? new Date(String(v)).toLocaleString("ru-RU", { day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" }) : "—";
const short = (s: unknown, n = 6) => {
  const v = String(s ?? "");
  return v.length > n * 2 + 1 ? `${v.slice(0, n)}…${v.slice(-n)}` : v || "—";
};

function who(r: Dict): string {
  return String(r.username || r.first_name || (r.user_id ? `id ${r.user_id}` : "—"));
}

function Toggle({ on, onChange, disabled }: { on: boolean; onChange: (v: boolean) => void; disabled?: boolean }) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={on}
      disabled={disabled}
      onClick={() => onChange(!on)}
      className={cx(
        "relative h-6 w-11 shrink-0 rounded-full border transition-colors disabled:opacity-50",
        on ? "border-[var(--green)] bg-[var(--green-bg)]" : "border-[var(--border)] bg-[var(--bg-elevated)]",
      )}
    >
      <span
        className={cx(
          "absolute top-0.5 size-4.5 rounded-full transition-all",
          on ? "left-[22px] bg-[var(--green)]" : "left-0.5 bg-[var(--text-muted)]",
        )}
      />
    </button>
  );
}

function StatusChip({ tone, children }: { tone: BadgeTone; children: ReactNode }) {
  return <Badge tone={tone}>{children}</Badge>;
}

function modeOf(s: Dict, signer: Dict): { label: string; text: string; tone: BadgeTone } {
  if (s.auto_mode_enabled !== true) {
    return { label: "Выключен", text: "Всё ведут операторы. Автопилот ничего не делает.", tone: "default" };
  }
  if (s.auto_no_shift_shadow_mode !== false) {
    return {
      label: "Тестовый режим",
      text: "Автопилот только записывает, что сделал бы. Клиенты ничего не замечают — смотрите журнал ниже и отметки в заявках.",
      tone: "yellow",
    };
  }
  if (signer.configured !== true) {
    return {
      label: "Стоит",
      text: "Выключатель включён, но кошелёк не подключён. Реквизиты и выплаты не уходят.",
      tone: "red",
    };
  }
  if (signer.reachable !== true) {
    return {
      label: "Стоит",
      text: "Выключатель включён, но кошелёк не отвечает. Реквизиты и выплаты не уходят.",
      tone: "red",
    };
  }
  if (signer.circuit_closed !== true) {
    return {
      label: "Стоит",
      text: "Выключатель включён, предохранитель открыт. Реквизиты и выплаты не уходят.",
      tone: "red",
    };
  }
  return { label: "Работает", text: "Автопилот выдаёт реквизиты и отправляет крипту в пределах лимитов.", tone: "green" };
}

function CoinCard({
  c,
  pace,
  usdRate,
  rotating,
  onNewAddress,
}: {
  c: Dict;
  pace?: string;
  usdRate: number;
  rotating: boolean;
  onNewAddress: (coin: string) => void;
}) {
  const coin = String(c.coin ?? "").toUpperCase();
  const node = (c.node ?? null) as Dict | null;
  const progress = node?.progress != null ? Math.min(100, Number(node.progress) * 100) : null;
  return (
    <Card className="space-y-3 p-5">
      <div className="flex items-center justify-between gap-2">
        <span className="text-sm font-semibold">{coin}</span>
        {node == null ? (
          <Badge>нода: нет данных</Badge>
        ) : node.ok === false ? (
          <Badge tone="red">нода недоступна</Badge>
        ) : node.syncing ? (
          <Badge tone="yellow">синхронизация {progress != null ? `${progress.toFixed(1)}%` : ""}</Badge>
        ) : (
          <Badge tone="green">нода готова</Badge>
        )}
      </div>
      {c.available ? (
        <>
          <div>
            <div className="font-mono text-2xl font-extrabold tabular-nums">{coinAmt(c.spendable)}</div>
            <div className="text-[12px] text-[var(--text-muted)]">
              ≈ {rubUsd(c.value_rub, usdRate)}
              {pace ? <> · {pace}</> : null}
              {Number(c.unconfirmed) > 0 && <> · ещё {coinAmt(c.unconfirmed)} ждёт подтверждения</>}
            </div>
          </div>
          {progress != null && node?.syncing ? (
            <div className="h-1.5 overflow-hidden rounded-full bg-[var(--bg-elevated)]">
              <div className="h-full bg-[var(--yellow)]" style={{ width: `${progress}%` }} />
            </div>
          ) : null}
        </>
      ) : (
        <div className="text-[13px] text-[var(--text-muted)]">Баланс недоступен</div>
      )}
      {c.deposit_address ? (
        <>
          <CopyField label="Адрес пополнения" value={String(c.deposit_address)} />
          <p className="text-[12px] leading-snug text-[var(--text-muted)]">
            Свободный адрес. После прихода монет здесь будет следующий. Старые остаются в этом кошельке: перевод на них дойдёт, баланс и выплаты общие.
          </p>
          <Button type="button" variant="secondary" size="sm" className="self-start" disabled={rotating} onClick={() => onNewAddress(String(c.coin))}>
            Новый адрес
          </Button>
        </>
      ) : (
        <div className="text-[12px] text-[var(--text-muted)]">Адрес пополнения появится, когда кошелёк будет на связи</div>
      )}
    </Card>
  );
}

const SOURCE_LABEL: Record<string, string> = {
  hot_wallet: "Горячий кошелёк",
  sell_deposit: "Приём продаж",
};

const addressCols: Column<Dict>[] = [
  { key: "coin", label: "Монета", width: "70px", render: (r) => String(r.coin ?? "").toUpperCase() },
  { key: "source", label: "Откуда", render: (r) => SOURCE_LABEL[String(r.source)] ?? String(r.source ?? "—") },
  {
    key: "address",
    label: "Адрес",
    render: (r) => <span className="font-mono text-[12px]">{String(r.address ?? "—")}</span>,
  },
  {
    key: "current",
    label: "Статус",
    width: "120px",
    render: (r) =>
      r.current ? (
        <Badge tone="green">текущий</Badge>
      ) : (
        <span title={r.retired_at ? `показан был до ${time(r.retired_at)}` : undefined}>
          <Badge>принимает</Badge>
        </span>
      ),
  },
];

function payoutCols(usdRate: number): Column<Dict>[] {
  return [
  { key: "created_at", label: "Когда", width: "110px", render: (r) => <span className="font-mono text-[12px]">{time(r.created_at)}</span> },
  {
    key: "who",
    label: "Кому",
    render: (r) => (
      <div className="min-w-0">
        <div className="truncate">{who(r)}</div>
        <div className="font-mono text-[11px] text-[var(--text-muted)]" title={String(r.address ?? "")}>
          {short(r.address, 8)}
        </div>
      </div>
    ),
  },
  {
    key: "kind",
    label: "За что",
    render: (r) =>
      String(r.kind) === "withdrawal" ? (
        <span>Вывод баланса #{String(r.ref_id ?? "")}</span>
      ) : String(r.kind) === "manual_buy" ? (
        <span>Ручная {String(r.ref_id ?? "")}</span>
      ) : (
        <span>Покупка {String(r.ref_id ?? "")}</span>
      ),
  },
  {
    key: "amount",
    label: "Сумма",
    align: "right",
    render: (r) => (
      <div className="text-right">
        <div className="font-mono">
          {coinAmt(r.amount_crypto)} {String(r.coin ?? "").toUpperCase()}
        </div>
        <div className="text-[11px] text-[var(--text-muted)]">{rubUsd(r.amount_rub, usdRate)}</div>
      </div>
    ),
  },
  {
    key: "status",
    label: "Статус",
    render: (r) => {
      const st = PAYOUT_STATUS[String(r.status)] ?? { label: String(r.status ?? "—"), tone: "default" as const };
      return (
        <div className="space-y-1">
          <Badge tone={st.tone}>{st.label}</Badge>
          {r.reject_reason ? <div className="text-[11px] text-[var(--text-muted)]">{String(r.reject_reason)}</div> : null}
        </div>
      );
    },
  },
  {
    key: "txid",
    label: "Транзакция",
    render: (r) => {
      const tx = String(r.txid ?? "");
      const link = EXPLORER[String(r.coin ?? "").toLowerCase()];
      if (!tx) return <span className="text-[var(--text-muted)]">—</span>;
      return link ? (
        <a
          href={link(tx)}
          target="_blank"
          rel="noreferrer"
          className="inline-flex items-center gap-1 font-mono text-[12px] underline-offset-2 hover:underline"
        >
          {short(tx)} <ExternalLink className="size-3" />
        </a>
      ) : (
        <span className="font-mono text-[12px]">{short(tx)}</span>
      );
    },
  },
  ];
}

function shadowCols(usdRate: number): Column<Dict>[] {
  return [
  { key: "created_at", label: "Когда", width: "110px", render: (r) => <span className="font-mono text-[12px]">{time(r.created_at)}</span> },
  {
    key: "order_id",
    label: "Заявка",
    render: (r) => (
      <Link
        to={`/x8/orders?order=${encodeURIComponent(String(r.order_id ?? ""))}`}
        className="font-mono underline-offset-2 hover:underline"
      >
        {String(r.order_id ?? "")}
      </Link>
    ),
  },
  { key: "who", label: "Клиент", render: (r) => who(r) },
  {
    key: "fiat_amount",
    label: "Сумма",
    align: "right",
    render: (r) => (
      <span className="font-mono">
        {rubUsd(r.fiat_amount, usdRate)}{" "}
        <span className="text-[var(--text-muted)]">{String(r.crypto ?? "").split("_")[0].toUpperCase()}</span>
      </span>
    ),
  },
  {
    key: "moment",
    label: "Момент",
    render: (r) => {
      const badge = MOMENT_BADGE[String(r.moment_key)] ?? { label: String(r.moment_key || "—"), tone: "default" as const };
      const why = [
        ...(Array.isArray(r.reasons) ? (r.reasons as unknown[]) : []),
        ...(Array.isArray(r.blockers) ? (r.blockers as unknown[]) : []),
      ];
      return (
        <div className="max-w-[420px] space-y-1">
          <Badge tone={badge.tone}>{badge.label}</Badge>
          <div className="text-[12px] text-[var(--text-secondary)]">{String(r.headline || "")}</div>
          {why.length ? <div className="text-[11px] text-[var(--text-muted)]">{why.map(reasonLabel).join(" · ")}</div> : null}
        </div>
      );
    },
  },
  ];
}

function decisionBadge(r: Dict) {
  if (r.reason === "shadow_would_auto") return <Badge tone="yellow">Тест: было бы авто</Badge>;
  if (r.decision === "allow_auto") return <Badge tone="green">Авто</Badge>;
  if (r.decision === "allow_shift") return <Badge tone="blue">Оператор на смене</Badge>;
  return <Badge>Оператору</Badge>;
}

function decisionCols(usdRate: number): Column<Dict>[] {
  return [
  { key: "created_at", label: "Когда", width: "110px", render: (r) => <span className="font-mono text-[12px]">{time(r.created_at)}</span> },
  { key: "who", label: "Клиент", render: (r) => who(r) },
  {
    key: "fiat_amount",
    label: "Сумма",
    align: "right",
    render: (r) => (
      <span className="font-mono">
        {rubUsd(r.fiat_amount, usdRate)}{" "}
        <span className="text-[var(--text-muted)]">{String(r.direction ?? "") === "sell" ? "продажа" : "покупка"}</span>
      </span>
    ),
  },
  { key: "decision", label: "Решение", render: decisionBadge },
  { key: "reason", label: "Почему", render: (r) => <span className="text-[var(--text-secondary)]">{reasonLabel(r.reason)}</span> },
  ];
}

const FEE_SOURCE: Record<string, string> = {
  project_wallet: "Кошелёк проекта",
  operator_wallet: "Кошельки операторов",
};

function feeCols(usdRate: number): Column<Dict>[] {
  return [
  { key: "source", label: "Откуда", render: (r) => FEE_SOURCE[String(r.source)] ?? String(r.source ?? "—") },
  { key: "coin", label: "Монета", render: (r) => String(r.coin ?? "").toUpperCase() },
  { key: "tx", label: "Переводов", align: "right", render: (r) => <span className="font-mono">{Number(r.tx) || 0}</span> },
  {
    key: "fee_rub",
    label: "Комиссия",
    align: "right",
    render: (r) => (
      <div className="text-right">
        <div className="font-mono">{rubUsd(r.fee_rub, usdRate)}</div>
        <div className="text-[11px] text-[var(--text-muted)]">
          {coinAmt(r.fee_crypto)} {String(r.fee_unit ?? "").toUpperCase()}
        </div>
      </div>
    ),
  },
  { key: "avg_fee_rub", label: "В среднем", align: "right", render: (r) => <span className="font-mono">{rubUsd(r.avg_fee_rub, usdRate)}</span> },
  {
    key: "avg_sat_vb",
    label: "sat/vB",
    align: "right",
    render: (r) => <span className="font-mono">{r.avg_sat_vb != null ? Number(r.avg_sat_vb).toFixed(1) : "—"}</span>,
  },
  ];
}

function countLabel(n: number, one: string, few: string, many: string) {
  const abs = Math.abs(n) % 100;
  const last = abs % 10;
  const word = abs > 10 && abs < 20 ? many : last === 1 ? one : last >= 2 && last <= 4 ? few : many;
  return `${n} ${word}`;
}

function HistoryFold({ title, meta, children }: { title: string; meta?: ReactNode; children: ReactNode }) {
  return (
    <section>
      <details className="group">
        <summary className="-mx-2 flex cursor-pointer list-none items-baseline justify-between gap-3 rounded-lg px-2 py-1.5 outline-none hover:bg-[var(--bg-elevated)] [&::-webkit-details-marker]:hidden">
          <span className="flex min-w-0 items-center gap-1.5">
            <ChevronDown
              className="size-4 shrink-0 text-[var(--text-muted)] transition-transform group-open:rotate-180"
              aria-hidden
            />
            <h2 className="text-sm font-semibold">{title}</h2>
          </span>
          {meta ? <span className="text-right text-[12px] text-[var(--text-muted)]">{meta}</span> : null}
        </summary>
        <div className="mt-3 space-y-3">{children}</div>
      </details>
    </section>
  );
}

function FeesSection({ fees, usdRate }: { fees: Dict | null; usdRate: number }) {
  const items = (Array.isArray(fees?.items) ? fees?.items : []) as Dict[];
  const unresolved = Number(fees?.unresolved) || 0;
  return (
    <HistoryFold
      title="Комиссии сети"
      meta={
        <>
          за {Number(fees?.days) || 30} дней ≈{" "}
          <span className="font-mono text-[var(--text-primary)]">{rubUsd(fees?.total_rub, usdRate)}</span>
          {unresolved > 0 && <> · ещё уточняется: {unresolved}</>}
        </>
      }
    >
      <Card className="p-0">
        <Table
          columns={feeCols(usdRate)}
          rows={items}
          empty={fees ? "Комиссии подтягиваются из эксплореров — появятся в течение часа" : "Учёт комиссий ещё не включён"}
        />
      </Card>
    </HistoryFold>
  );
}

const TOPUP_STATUS: Record<string, { label: string; tone: BadgeTone }> = {
  pending: { label: "ждёт блока", tone: "yellow" },
  confirmed: { label: "подтверждено", tone: "green" },
  conflicted: { label: "заменено", tone: "red" },
  dropped: { label: "пропало из mempool", tone: "red" },
  not_in_wallet: { label: "нет в кошельке", tone: "red" },
};

const minutes = (sec: unknown) => `${Math.max(0, Math.round((Number(sec) || 0) / 60))} мин`;

function FundsSection({ trustedOn }: { trustedOn: boolean }) {
  const [funds, setFunds] = useState<Dict | null>(null);
  const [txid, setTxid] = useState("");
  const [busy, setBusy] = useState("");

  const load = useCallback(async () => {
    try {
      setFunds(await getAutopilotFunds());
    } catch {
      setFunds((prev) => prev ?? {});
    }
  }, []);
  useEffect(() => {
    void load();
  }, [load]);
  useAuthedPoll("admin", load, 30_000);

  const topups = (funds?.topups ?? {}) as Dict;
  const items = (Array.isArray(topups.items) ? topups.items : []) as Dict[];
  const waiting = (Array.isArray(funds?.waiting) ? funds.waiting : []) as Dict[];
  const stuck = (Array.isArray(funds?.stuck) ? funds.stuck : []) as Dict[];
  const signerOn = topups.signer_enabled === true;
  const cleanTxid = txid.trim().toLowerCase();
  const txidOk = /^[0-9a-f]{64}$/.test(cleanTxid);

  const trust = async () => {
    if (!window.confirm("Это перевод с вашего собственного кошелька? Выплаты из него уйдут до подтверждения. Не ускоряйте его через RBF.")) return;
    setBusy("trust");
    try {
      await trustAutopilotTopup(cleanTxid);
      toast.success("Пополнение доверено — выплаты пойдут сразу");
      setTxid("");
      void load();
    } catch (e) {
      const code = e instanceof Error ? e.message : "";
      toast.error(TOPUP_ERRORS[code] ?? (code || "Не удалось"));
    } finally {
      setBusy("");
    }
  };

  const requeue = async (orderId: string) => {
    if (!window.confirm(`Вернуть заявку ${orderId} в автопилот? Убедитесь, что оператор не отправил монеты вручную со своего кошелька.`)) return;
    setBusy(orderId);
    try {
      await requeueAutopilotOrder(orderId);
      toast.success("Заявка вернулась в автопилот");
      void load();
    } catch (e) {
      const code = e instanceof Error ? e.message : "";
      toast.error(REQUEUE_ERRORS[code] ?? (code || "Не удалось"));
    } finally {
      setBusy("");
    }
  };

  const stuckCols: Column<Dict>[] = [
    { key: "order_id", label: "Заявка", render: (r) => <span className="font-mono text-[12px]">{String(r.order_id ?? "—")}</span> },
    { key: "user", label: "Клиент", render: (r) => who(r) },
    {
      key: "amount",
      label: "Сумма",
      render: (r) => (
        <span className="font-mono text-[12px]">
          {coinAmt(r.amount_crypto)} {String(r.coin ?? "").toUpperCase()} · {rub(r.amount_rub)}
        </span>
      ),
    },
    { key: "reason", label: "Причина", render: (r) => <span className="text-[12px]">{reasonLabel(r.reject_reason)}</span> },
    { key: "updated_at", label: "Когда", width: "110px", render: (r) => <span className="font-mono text-[12px]">{time(r.updated_at)}</span> },
    {
      key: "action",
      label: "",
      width: "170px",
      render: (r) => (
        <Button size="sm" disabled={!!busy} onClick={() => void requeue(String(r.order_id))}>
          Вернуть в автопилот
        </Button>
      ),
    },
  ];

  const topupCols: Column<Dict>[] = [
    {
      key: "txid",
      label: "Транзакция",
      render: (r) => (
        <a href={EXPLORER.btc(String(r.txid))} target="_blank" rel="noreferrer" className="inline-flex items-center gap-1 font-mono text-[12px] underline">
          {short(r.txid, 8)} <ExternalLink className="size-3" />
        </a>
      ),
    },
    { key: "amount", label: "BTC", width: "120px", render: (r) => <span className="font-mono text-[12px]">{coinAmt(r.amount)}</span> },
    {
      key: "status",
      label: "Статус",
      width: "150px",
      render: (r) => {
        const st = TOPUP_STATUS[String(r.status)];
        return <Badge tone={st?.tone ?? "default"}>{st?.label ?? String(r.status ?? "—")}</Badge>;
      },
    },
    { key: "note", label: "Кто", render: (r) => <span className="text-[12px]">{String(r.note ?? "—")}</span> },
    { key: "added_at", label: "Когда", width: "110px", render: (r) => <span className="font-mono text-[12px]">{time(Number(r.added_at) * 1000)}</span> },
  ];

  return (
    <section className="space-y-3">
      <div className="flex items-baseline justify-between gap-2">
        <h2 className="text-sm font-semibold">Пополнение</h2>
        <span className="text-[12px] text-[var(--text-muted)]">
          без подтверждения ждём до {String(funds?.wait_max_min ?? "…")} мин, потом — оператору
        </span>
      </div>
      <Card className="space-y-3 p-5">
        <p className="text-[13px] text-[var(--text-secondary)]">
          Неподтверждённый BTC на горячем кошельке уходит в выплату сразу, блок ждать не нужно.
          Лайткоин по-прежнему уходит после 1 подтверждения. Поле txid — только если пополнение само не подхватилось.
        </p>
        <div className="flex flex-wrap gap-2">
          <StatusChip tone={trustedOn ? "green" : "default"}>Доверенные пополнения в автопилоте: {trustedOn ? "вкл" : "выкл"}</StatusChip>
          <StatusChip tone={signerOn ? "green" : "default"}>
            На кошельке: {signerOn ? `вкл, до ${coinAmt(topups.max_pending)} BTC в ожидании` : "выкл"}
          </StatusChip>
        </div>
        <div className="flex flex-wrap items-end gap-2">
          <div className="min-w-[320px] flex-1">
            <Field label="txid пополнения BTC" hint="Только перевод с вашего собственного кошелька">
              <Input className="font-mono" value={txid} placeholder="64 hex" onChange={(e) => setTxid(e.target.value)} />
            </Field>
          </div>
          <Button variant="primary" disabled={!txidOk || !trustedOn || !signerOn || !!busy} onClick={() => void trust()}>
            Это моё пополнение
          </Button>
        </div>
        {items.length > 0 && (
          <div className="overflow-hidden rounded-lg border border-[var(--border)]">
            <Table columns={topupCols} rows={items} />
          </div>
        )}
      </Card>
      {waiting.length > 0 && (
        <Card className="space-y-2 p-5">
          <div className="text-sm font-semibold">Ждут подтверждения пополнения · {waiting.length}</div>
          <div className="divide-y divide-[var(--border)] text-[13px]">
            {waiting.map((w) => (
              <div key={String(w.order_id)} className="flex justify-between gap-3 py-2">
                <span className="font-mono">{String(w.order_id)}</span>
                <span className="font-mono">
                  {coinAmt(w.amount)} {String(w.coin ?? "").toUpperCase()} · ждёт {minutes(w.waiting_sec)}
                </span>
              </div>
            ))}
          </div>
        </Card>
      )}
      <HistoryFold title="Ушли оператору из-за нехватки денег" meta={<>{countLabel(stuck.length, "заявка", "заявки", "заявок")}</>}>
        <Card className="p-0">
          <Table columns={stuckCols} rows={stuck} empty={funds ? "Таких заявок нет" : "Загрузка…"} />
        </Card>
      </HistoryFold>
    </section>
  );
}

function formFrom(s: Dict): Record<string, string> {
  const next: Record<string, string> = {};
  for (const f of ALL_FIELDS) {
    const v = s[f.key];
    if (f.kind === "wallet") next[f.key] = v === "project" ? "project" : "operator";
    else next[f.key] = f.kind === "bool" ? (v === true ? "1" : "0") : v != null ? String(v) : "";
  }
  return next;
}

export function AdminAutopilot() {
  const [data, setData] = useState<Dict | null>(null);
  const [form, setForm] = useState<Record<string, string>>({});
  const [whitelistText, setWhitelistText] = useState("");
  const [dirty, setDirty] = useState(false);
  const [busy, setBusy] = useState(false);
  const [rotatingCoin, setRotatingCoin] = useState("");
  const [refreshing, setRefreshing] = useState(false);
  const [payRates, setPayRates] = useState<Dict | null>(null);
  const [fallbackUsd, setFallbackUsd] = useState(0);

  const applySettings = (s: Dict) => {
    setForm(formFrom(s));
    const wl = s.auto_whitelist_user_ids;
    setWhitelistText(Array.isArray(wl) ? wl.map(String).join(", ") : "");
    setDirty(false);
  };

  const load = useCallback(async (initial = false) => {
    try {
      const [r, rates] = await Promise.all([
        getAutopilotOverview(),
        getOperatorPayrollSettings().catch(() => null),
      ]);
      setData(r);
      if (rates) setPayRates(rates);
      if (initial) applySettings((r.settings ?? {}) as Dict);
    } catch {
      if (initial) toast.error("Не удалось загрузить автопилот");
    }
  }, []);

  // Курс тянем отдельно от обзора: он нужен только для подписи в долларах,
  // и его не должно уносить вместе с ошибкой основного запроса.
  const loadUsdRate = useCallback(async () => {
    const rate = await getUsdRateRub().catch(() => 0);
    if (rate > 0) setFallbackUsd(rate);
  }, []);

  useEffect(() => {
    void load(true);
    void loadUsdRate();
  }, [load, loadUsdRate]);
  useAuthedPoll("admin", () => load(false), 30_000);

  const refresh = async () => {
    setRefreshing(true);
    await Promise.all([load(false), loadUsdRate()]);
    setRefreshing(false);
  };

  const setField = (key: string, value: string) => {
    setForm((prev) => ({ ...prev, [key]: value }));
    setDirty(true);
  };

  const newAddress = async (coin: string) => {
    setRotatingCoin(coin);
    try {
      await rotateAutopilotAddress(coin);
      toast.success(`Новый адрес ${coin.toUpperCase()}. Старый по-прежнему принимает`);
      await load(false);
    } catch (e) {
      if (e instanceof PanelApiError && e.status === 403) toast.error("Новый адрес выдаёт только владелец");
      else toast.error(e instanceof PanelApiError ? e.message : "Не удалось получить новый адрес");
    } finally {
      setRotatingCoin("");
    }
  };

  const save = async () => {
    setBusy(true);
    try {
      const body: Dict = {};
      for (const f of ALL_FIELDS) {
        const raw = form[f.key];
        if (f.kind === "wallet") body[f.key] = raw === "project" ? "project" : "operator";
        else body[f.key] = f.kind === "bool" ? raw === "1" : raw === "" ? 0 : Number(raw);
      }
      body.auto_whitelist_user_ids = whitelistText
        .split(",")
        .map((x) => Number(x.trim()))
        .filter((n) => Number.isFinite(n) && n > 0);
      const r = await patchAutopilot(body);
      applySettings((r.settings ?? {}) as Dict);
      toast.success("Сохранено");
      void load(false);
    } catch {
      toast.error("Ошибка сохранения");
    } finally {
      setBusy(false);
    }
  };

  const settings = (data?.settings ?? {}) as Dict;
  const signer = (data?.signer ?? {}) as Dict;
  const wallet = (data?.wallet ?? {}) as Dict;
  const today = (data?.today ?? {}) as Dict;
  const queue = (data?.queue ?? {}) as Dict;
  const shadow = (data?.shadow ?? {}) as Dict;
  const coins = (Array.isArray(wallet.coins) ? wallet.coins : []) as Dict[];
  const payouts = (Array.isArray(data?.recent_payouts) ? data?.recent_payouts : []) as Dict[];
  const decisions = (Array.isArray(data?.recent_decisions) ? data?.recent_decisions : []) as Dict[];
  const payoutShadow = (Array.isArray(data?.payout_shadow) ? data.payout_shadow : []) as Dict[];
  const walletAddresses = (Array.isArray(data?.wallet_addresses) ? data.wallet_addresses : []) as Dict[];
  const savings = (data?.savings ?? null) as Dict | null;
  const savingsLines = (Array.isArray(savings?.lines) ? savings.lines : []) as Dict[];
  const referralExtra = (Number(savings?.user_referral_extra_rub) || 0) + (Number(savings?.partner_extra_rub) || 0);
  const runway = (data?.runway ?? null) as Dict | null;
  const runwayCoins = (Array.isArray(runway?.coins) ? runway.coins : []) as Dict[];
  const paceOf = (coin: unknown) =>
    String(runwayCoins.find((row) => row.coin === coin)?.phrase ?? "");
  const wouldSendNow = payoutShadow.filter((r) => r.moment_key === "would_send_now").length;
  const mode = modeOf(settings, signer);
  const overviewRate = Number(data?.usd_rate_rub);
  const usdRate = overviewRate > 0 ? overviewRate : fallbackUsd;
  const totalRub = Number(wallet.total_rub) || 0;
  const minHot = Number(wallet.min_hot_balance_rub) || 0;
  const cap = Number(today.daily_cap_rub) || 0;
  const room = Number(today.daily_room_rub) || 0;
  const pendingWd = (Number(queue.withdrawals_reserved) || 0) + (Number(queue.withdrawals_sending) || 0);

  return (
    <div className="space-y-6 pb-10">
      <PageHeader
        title="Автопилот"
        subtitle={joinHint(
          "Реквизиты без смены и автовыплаты BTC/LTC постоянным клиентам",
          usdRate > 0
            ? `доллары по курсу USDT ${usdRate.toLocaleString("ru-RU", { minimumFractionDigits: 2, maximumFractionDigits: 2 })} ₽`
            : "",
        )}
        actions={
          <Button onClick={() => void refresh()} disabled={refreshing}>
            <RefreshCw className={cx("size-4", refreshing && "animate-spin")} /> Обновить
          </Button>
        }
      />

      <Card className="space-y-3 p-5">
        <div className="flex flex-wrap items-center gap-3">
          <span className="text-[12px] uppercase tracking-wide text-[var(--text-muted)]">Режим</span>
          <Badge tone={mode.tone} className="text-[13px]">
            {mode.label}
          </Badge>
        </div>
        <p className="text-sm text-[var(--text-secondary)]">{mode.text}</p>
        {payRates && (
          <p className="text-[13px] text-[var(--text-secondary)]">
            Оплата операторов при включённом автопилоте:{" "}
            <span className="font-mono">{String(payRates.autopilot_presence_percent ?? 5)}%</span> за смену,{" "}
            <span className="font-mono">{String(payRates.autopilot_manual_percent ?? 10)}%</span> за ручную заявку
            {payRates.autopilot_hourly_enabled === true
              ? `, почасовая ${String(payRates.autopilot_hourly_rate_rub ?? 0)} ₽/час`
              : ", почасовая выключена"}
            .{" "}
            <Link to="/x8/payroll" className="text-[var(--text-primary)] underline">
              Изменить в зарплатах
            </Link>
          </p>
        )}
        <div className="flex flex-wrap gap-2">
          {!signer.configured ? (
            <StatusChip tone="red">Кошелёк не подключён</StatusChip>
          ) : signer.reachable ? (
            <StatusChip tone="green">Кошелёк на связи</StatusChip>
          ) : (
            <StatusChip tone="red">Кошелёк не отвечает</StatusChip>
          )}
          {signer.dry_run === true && <StatusChip tone="yellow">Отправки холостые (DRY_RUN)</StatusChip>}
          {signer.configured === true && signer.circuit_closed !== true && <StatusChip tone="red">Предохранитель открыт — выплаты стоят</StatusChip>}
          {minHot > 0 && totalRub < minHot && <StatusChip tone="yellow">Кошелёк ниже минимума {rub(minHot)}</StatusChip>}
          {pendingWd > 0 && <StatusChip tone="blue">Выводов в работе: {pendingWd}</StatusChip>}
        </div>
      </Card>

      <section className="space-y-3">
        <div className="flex items-baseline justify-between gap-2">
          <h2 className="text-sm font-semibold">Горячий кошелёк</h2>
          <span className="text-[12px] text-[var(--text-muted)]">
            всего ≈ <span className="font-mono text-[var(--text-primary)]">{rubUsd(totalRub, usdRate)}</span>
            {minHot > 0 && <> · минимум {rubUsd(minHot, usdRate)}</>}
          </span>
        </div>
        {runway?.floor_phrase ? (
          <p className="text-[13px] text-[var(--text-secondary)]">{String(runway.floor_phrase)} · темп за 7 дней</p>
        ) : (
          <p className="text-[13px] text-[var(--text-muted)]">Срок считаем по выплатам BTC/LTC за 7 дней</p>
        )}
        <div className="grid grid-cols-2 gap-4 max-[720px]:grid-cols-1">
          {coins.length ? coins.map((c) => (
            <CoinCard
              key={String(c.coin)}
              c={c}
              pace={paceOf(c.coin)}
              usdRate={usdRate}
              rotating={rotatingCoin === String(c.coin)}
              onNewAddress={(coin) => void newAddress(coin)}
            />
          )) : <Card className="p-5 text-sm text-[var(--text-muted)]">Загрузка…</Card>}
        </div>
      </section>

      <FundsSection trustedOn={settings.auto_payout_trusted_topups === true} />

      <HistoryFold
        title="Все адреса"
        meta={
          <>
            {countLabel(walletAddresses.length, "адрес", "адреса", "адресов")} · старые тоже принимают, баланс общий
          </>
        }
      >
        <Card className="p-0">
          <Table columns={addressCols} rows={walletAddresses} empty="Адреса появятся, когда кошелёк или приём продаж их покажет" />
        </Card>
      </HistoryFold>

      <section className="space-y-3">
        <div className="flex items-baseline justify-between gap-2">
          <h2 className="text-sm font-semibold">Плюс за 7 дней</h2>
          <span className="text-[12px] text-[var(--text-muted)]">ставки не меняем · кешбэк не поднимаем</span>
        </div>
        {savings?.net_rub == null ? (
          <Card className="p-5 text-sm text-[var(--text-muted)]">{String(savings?.line || "Загрузка…")}</Card>
        ) : (
          <>
            <div className="grid grid-cols-3 gap-4 max-[900px]:grid-cols-2">
              <Kpi label="Плюс проекту" value={<MoneyFigure amount={savings.net_rub} rate={usdRate} />} hint="экономия минус рефералы" />
              <Kpi
                label="Экономия на операторах"
                value={<MoneyFigure amount={savings.operator_save_rub} rate={usdRate} />}
                hint={`${Number(savings.auto_deals) || 0} авто · ${Number(savings.manual_deals) || 0} ручных`}
              />
              <Kpi label="Доплата рефералам до 20%" value={<MoneyFigure amount={referralExtra} rate={usdRate} />} hint="выше 20% не поднимаем" />
            </div>
            <HistoryFold title="Из чего сложилось" meta={<>{countLabel(savingsLines.length, "строка", "строки", "строк")}</>}>
              <Card className="divide-y divide-[var(--border)] p-0">
                {savingsLines.map((line) => (
                  <div key={String(line.key)} className="flex items-baseline justify-between gap-3 px-4 py-3 text-[13px]">
                    <div>
                      <div>{String(line.label ?? "")}</div>
                      {line.hint ? <div className="text-[11px] text-[var(--text-muted)]">{String(line.hint)}</div> : null}
                    </div>
                    <span className="font-mono">{rubUsd(line.amount_rub, usdRate)}</span>
                  </div>
                ))}
              </Card>
            </HistoryFold>
          </>
        )}
      </section>

      <section className="space-y-3">
        <h2 className="text-sm font-semibold">Сегодня</h2>
        <div className="grid grid-cols-4 gap-4 max-[900px]:grid-cols-2">
          <Kpi label="Отправлено" value={<MoneyFigure amount={today.sent_rub} rate={usdRate} />} hint={`${Number(today.sent_count) || 0} выплат`} />
          <Kpi label="В очереди" value={<MoneyFigure amount={today.queued_rub} rate={usdRate} />} hint={`${Number(today.queued_count) || 0} выплат`} />
          <Kpi label="Ошибки" value={String(Number(today.failed_count) || 0)} hint="ушли оператору" />
          <Kpi
            label="Остаток лимита"
            value={<MoneyFigure amount={room} rate={usdRate} />}
            hint={cap > 0 ? `из ${rubUsd(cap, usdRate)} в сутки` : "лимит не задан"}
          />
        </div>
        <div className="grid grid-cols-2 gap-4 max-[520px]:grid-cols-1">
          <Kpi label="Тест за 24 ч: выдали бы сами" value={String(Number(shadow.would_auto_24h) || 0)} hint="заявок без смены" />
          <Kpi label="За 24 ч ушло оператору" value={String(Number(shadow.blocked_24h) || 0)} hint="не прошли проверки" />
        </div>
      </section>

      <HistoryFold
        title="Тест автовывода"
        meta={
          <>
            сейчас ушли бы монеты: <span className="font-mono text-[var(--text-primary)]">{wouldSendNow}</span>
            {" · "}
            {countLabel(payoutShadow.length, "заявка", "заявки", "заявок")} · ничего не отправляется
          </>
        }
      >
        <p className="text-[13px] text-[var(--text-secondary)]">
          Свежие покупки за 7 дней. По каждой заявке видно, на каком шаге автовывод отправил бы монеты клиенту.
        </p>
        <Card className="p-0">
          <Table
            columns={shadowCols(usdRate)}
            rows={payoutShadow}
            empty={
              !data
                ? "Загрузка…"
                : Array.isArray(data.payout_shadow)
                  ? "Свежих покупок за 7 дней нет"
                  : "Отчёт появится после обновления сервера"
            }
          />
        </Card>
      </HistoryFold>

      <HistoryFold title="Последние выплаты" meta={<>{countLabel(payouts.length, "выплата", "выплаты", "выплат")}</>}>
        <Card className="p-0">
          <Table columns={payoutCols(usdRate)} rows={payouts} empty="Автовыплат ещё не было" />
        </Card>
      </HistoryFold>

      <FeesSection fees={(data?.fees ?? null) as Dict | null} usdRate={usdRate} />

      <HistoryFold title="Журнал решений" meta={<>{countLabel(decisions.length, "запись", "записи", "записей")}</>}>
        <Card className="p-0">
          <Table columns={decisionCols(usdRate)} rows={decisions} empty="Решений пока нет — они появятся, когда клиент создаст заявку без смены" />
        </Card>
      </HistoryFold>

      <section className="space-y-3">
        <div className="flex items-center justify-between gap-2">
          <h2 className="text-sm font-semibold">Настройки</h2>
          {dirty && <Badge tone="yellow">Есть несохранённые изменения</Badge>}
        </div>
        <div className="grid grid-cols-2 gap-4 max-[900px]:grid-cols-1">
          {SECTIONS.map((sec) => (
            <Card key={sec.title} className="space-y-4 p-5">
              <div>
                <div className="text-sm font-semibold">{sec.title}</div>
                <div className="text-[12px] text-[var(--text-muted)]">{sec.hint}</div>
              </div>
              {sec.fields.map((f) =>
                f.kind === "wallet" ? (
                  <Field key={f.key} label={f.label}>
                    <div role="radiogroup" className="grid grid-cols-2 gap-2">
                      {WALLET_OPTIONS.map((o) => {
                        const active = (form[f.key] ?? "operator") === o.value;
                        return (
                          <button
                            key={o.value}
                            type="button"
                            role="radio"
                            aria-checked={active}
                            disabled={!data}
                            onClick={() => setField(f.key, o.value)}
                            className={cx(
                              "rounded-lg border px-3 py-2 text-left transition-colors disabled:opacity-50",
                              active
                                ? "border-[var(--green)] bg-[var(--green-bg)]"
                                : "border-[var(--border)] bg-[var(--bg-elevated)] hover:border-[var(--text-muted)]",
                            )}
                          >
                            <div className="text-sm font-medium">{o.label}</div>
                            <div className="text-[11px] text-[var(--text-muted)]">{o.hint}</div>
                          </button>
                        );
                      })}
                    </div>
                  </Field>
                ) : f.kind === "bool" ? (
                  <div key={f.key} className="flex items-center justify-between gap-3">
                    <div>
                      <div className="text-sm">{f.label}</div>
                      {f.hint && <div className="text-[11px] text-[var(--text-muted)]">{f.hint}</div>}
                    </div>
                    <Toggle on={form[f.key] === "1"} disabled={!data} onChange={(v) => setField(f.key, v ? "1" : "0")} />
                  </div>
                ) : (
                  <Field key={f.key} label={f.label} hint={joinHint(f.money && form[f.key] ? usd(form[f.key], usdRate) : "", f.hint ?? "")}>
                    <Input
                      inputMode="numeric"
                      className="font-mono"
                      value={form[f.key] ?? ""}
                      disabled={!data}
                      onChange={(e) => setField(f.key, e.target.value.replace(/[^\d.]/g, ""))}
                    />
                  </Field>
                ),
              )}
            </Card>
          ))}
          <Card className="space-y-4 p-5">
            <div>
              <div className="text-sm font-semibold">Белый список</div>
              <div className="text-[12px] text-[var(--text-muted)]">
                Telegram ID через запятую. Пусто — подходит любой, кто набрал нужное число покупок.
              </div>
            </div>
            <Input
              className="font-mono"
              value={whitelistText}
              disabled={!data}
              onChange={(e) => {
                setWhitelistText(e.target.value);
                setDirty(true);
              }}
            />
          </Card>
        </div>
        <div className="flex gap-2">
          <Button variant="primary" disabled={busy || !data || !dirty} onClick={() => void save()}>
            Сохранить
          </Button>
          {dirty && (
            <Button onClick={() => applySettings(settings)} disabled={busy}>
              Отменить
            </Button>
          )}
        </div>
      </section>
    </div>
  );
}