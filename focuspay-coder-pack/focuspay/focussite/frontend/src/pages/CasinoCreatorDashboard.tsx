import { useEffect, useRef, useState } from "react";
import { motion } from "framer-motion";
import { Check, Copy, DollarSign, Download, TrendingUp, Trophy, Wallet } from "lucide-react";
import { toast } from "sonner";
import { api } from "@/lib/api";
import { CARD_WITHDRAW_PROMISE } from "@/lib/cardWithdrawCopy";
import { LineAreaChart } from "@/panel/ui/LineAreaChart";

const TERMINAL_WITHDRAWAL_STATUSES = new Set(["approved", "rejected", "cancelled"]);

function createIdempotencyKey(): string {
  if (typeof crypto !== "undefined" && typeof crypto.randomUUID === "function") {
    return crypto.randomUUID();
  }

  return `creator-withdrawal-${Date.now()}-${Math.random().toString(36).slice(2)}`;
}

interface CreatorProfile {
  account_id: number;
  ref_link?: string | null;
  balance_rub: number;
  total_earned_rub: number;
  total_withdrawn_rub: number;
  min_withdrawal_rub: number;
  games_count: number;
  last_game_at: string | null;
}

interface CreatorStats {
  total_games: number;
  total_commission: number;
  games_today: number;
  commission_today: number;
  games_week: number;
  commission_week: number;
  games_month: number;
  commission_month: number;
}

interface CreatorGame {
  id: number;
  game_id: string;
  game_type: string;
  bet_rub: number;
  commission_rub: number;
  my_commission: number;
  winner_id: number | null;
  status: string;
  created_at: string;
  finished_at: string | null;
}

interface CreatorWithdrawal {
  id: number;
  amount_rub: number;
  method: string;
  requisites: string;
  crypto: string | null;
  network: string | null;
  status: string;
  tx_hash: string | null;
  receipt_file: string | null;
  reject_reason: string | null;
  created_at: string;
  processed_at: string | null;
}

interface ChartData {
  days: number;
  data: Array<{
    date: string;
    games: number;
    commission: number;
  }>;
}

export default function CasinoCreatorDashboard() {
  const [profile, setProfile] = useState<CreatorProfile | null>(null);
  const [stats, setStats] = useState<CreatorStats | null>(null);
  const [games, setGames] = useState<CreatorGame[]>([]);
  const [withdrawals, setWithdrawals] = useState<CreatorWithdrawal[]>([]);
  const [chartData, setChartData] = useState<ChartData | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [chartError, setChartError] = useState<string | null>(null);
  const [chartHover, setChartHover] = useState<number | null>(null);
  const [loading, setLoading] = useState(true);
  const [tab, setTab] = useState<"overview" | "games" | "withdrawals">("overview");
  const [chartPeriod, setChartPeriod] = useState(30);
  const [copiedRefLink, setCopiedRefLink] = useState(false);

  // Withdrawal form
  const [withdrawalForm, setWithdrawalForm] = useState({
    amount_rub: "",
    method: "crypto",
    requisites: "",
    crypto: "usdt",
    network: "trc20",
  });
  const [showWithdrawalModal, setShowWithdrawalModal] = useState(false);
  const [withdrawalSubmitting, setWithdrawalSubmitting] = useState(false);
  const withdrawalIdempotencyKey = useRef<string | null>(null);

  const resetWithdrawalForm = () => {
    withdrawalIdempotencyKey.current = null;
    setWithdrawalForm({
      amount_rub: "",
      method: "crypto",
      requisites: "",
      crypto: "usdt",
      network: "trc20",
    });
  };

  const startWithdrawal = () => {
    resetWithdrawalForm();
    setShowWithdrawalModal(true);
  };

  const updateWithdrawalForm = (update: Partial<typeof withdrawalForm>) => {
    withdrawalIdempotencyKey.current = null;
    setWithdrawalForm((current) => ({ ...current, ...update }));
  };

  useEffect(() => {
    loadData();
  }, []);

  useEffect(() => {
    if (tab === "overview") {
      loadChart(chartPeriod);
    }
  }, [tab, chartPeriod]);

  const loadData = async () => {
    setLoading(true);
    setLoadError(null);
    const [profileResult, statsResult, gamesResult, withdrawalsResult] = await Promise.allSettled([
      api<CreatorProfile>("/casino/creator/me"),
      api<CreatorStats>("/casino/creator/stats"),
      api<CreatorGame[]>("/casino/creator/games", { query: { limit: 20 } }),
      api<CreatorWithdrawal[]>("/casino/creator/withdrawals"),
    ]);

    if (profileResult.status === "fulfilled") setProfile(profileResult.value);
    if (statsResult.status === "fulfilled") setStats(statsResult.value);
    if (gamesResult.status === "fulfilled") setGames(gamesResult.value);
    if (withdrawalsResult.status === "fulfilled") setWithdrawals(withdrawalsResult.value);

    if ([profileResult, statsResult, gamesResult, withdrawalsResult].some((result) => result.status === "rejected")) {
      console.error("Failed to load some creator data", { profileResult, statsResult, gamesResult, withdrawalsResult });
      setLoadError("Часть данных временно недоступна. Обновите страницу, чтобы повторить загрузку.");
    }
    setLoading(false);
  };

  const loadChart = async (days: number) => {
    setChartError(null);
    try {
      setChartData(await api<ChartData>("/casino/creator/chart", { query: { days } }));
    } catch (error) {
      console.error("Failed to load chart:", error);
      setChartError("Не удалось загрузить график прибыли.");
    }
  };

  const handleWithdrawal = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!profile || withdrawalSubmitting) return;

    const amount = Number(withdrawalForm.amount_rub);
    const minimumWithdrawal = profile.min_withdrawal_rub;
    if (!Number.isFinite(amount) || !Number.isFinite(minimumWithdrawal) || minimumWithdrawal <= 0) {
      toast.error("Не удалось определить минимальную сумму вывода. Обновите страницу.");
      return;
    }
    if (amount < minimumWithdrawal) {
      toast.error(`Минимальная сумма вывода: ${minimumWithdrawal.toFixed(2)} ₽`);
      return;
    }

    withdrawalIdempotencyKey.current ??= createIdempotencyKey();
    setWithdrawalSubmitting(true);
    try {
      const createdWithdrawal = await api<CreatorWithdrawal>("/casino/creator/withdrawals", {
        method: "POST",
        headers: { "Idempotency-Key": withdrawalIdempotencyKey.current },
        body: {
          amount_rub: amount,
          method: withdrawalForm.method,
          requisites: withdrawalForm.requisites,
          crypto: withdrawalForm.method === "crypto" ? withdrawalForm.crypto : null,
          network: withdrawalForm.method === "crypto" ? withdrawalForm.network : null,
        },
      });

      if (TERMINAL_WITHDRAWAL_STATUSES.has(createdWithdrawal.status)) {
        setShowWithdrawalModal(false);
        resetWithdrawalForm();
      } else {
        setShowWithdrawalModal(false);
      }
      void loadData();
    } catch (error) {
      console.error("Withdrawal error:", error);
      toast.error("Не удалось создать заявку. Повторите отправку — заявка не будет продублирована.");
    } finally {
      setWithdrawalSubmitting(false);
    }
  };

  const handleCopyRefLink = async () => {
    if (!profile?.ref_link) return;
    try {
      await navigator.clipboard.writeText(profile.ref_link);
      setCopiedRefLink(true);
      toast.success("Реферальная ссылка скопирована");
      window.setTimeout(() => setCopiedRefLink(false), 2_000);
    } catch {
      toast.error("Не удалось скопировать ссылку");
    }
  };

  if (loading) {
    return (
      <div className="min-h-screen bg-[#0a0a0a] flex items-center justify-center">
        <div className="text-white/60">Загрузка...</div>
      </div>
    );
  }

  const chartPoints = [...(chartData?.data ?? [])].reverse();
  const money = (value: number) => `${value.toFixed(2)} ₽`;

  const statusColor = (status: string) => {
    switch (status) {
      case "pending":
        return "text-yellow-400";
      case "approved":
        return "text-green-400";
      case "rejected":
        return "text-red-400";
      default:
        return "text-white/40";
    }
  };

  const gameTypeLabel = (type: string) => {
    const labels: Record<string, string> = {
      pvp_dice: "PVP Кубики",
      baccara: "Баккара",
      blackjack: "Блэкджек",
      raffle: "Розыгрыш",
      roulette: "Рулетка",
    };
    return labels[type] || type;
  };

  return (
    <div className="min-h-screen bg-[#0a0a0a] text-white">
      {/* Header */}
      <div className="border-b border-white/5 bg-[#0f0f0f]">
        <div className="max-w-[1400px] mx-auto px-6 py-6">
          <h1 className="text-2xl font-semibold">Кабинет создателя FocusBet</h1>
          {profile?.ref_link && (
            <div className="mt-3 max-w-2xl">
              <p className="mb-1.5 text-sm text-white/50">Ваша реферальная ссылка</p>
              <div className="flex items-center gap-2 rounded-xl border border-white/10 bg-white/5 p-2">
                <code className="min-w-0 flex-1 truncate px-2 text-sm text-white/80">{profile.ref_link}</code>
                <button
                  type="button"
                  onClick={() => void handleCopyRefLink()}
                  className="shrink-0 rounded-lg bg-white px-3 py-2 text-sm font-medium text-black transition-colors hover:bg-white/90"
                  aria-label="Скопировать реферальную ссылку"
                >
                  {copiedRefLink ? <Check className="h-4 w-4" /> : <Copy className="h-4 w-4" />}
                </button>
              </div>
            </div>
          )}
        </div>
      </div>

      <div className="max-w-[1400px] mx-auto px-6 py-8">
        {loadError && (
          <div className="mb-6 flex items-center justify-between gap-4 rounded-xl border border-yellow-400/20 bg-yellow-400/10 px-4 py-3 text-sm text-yellow-100">
            <span>{loadError}</span>
            <button type="button" onClick={() => void loadData()} className="shrink-0 font-medium text-white hover:text-yellow-100">
              Повторить
            </button>
          </div>
        )}

        {/* Stats Cards */}
        <div className="grid grid-cols-1 md:grid-cols-4 gap-4 mb-8">
          <motion.div
            initial={{ opacity: 0, y: 20 }}
            animate={{ opacity: 1, y: 0 }}
            className="bg-[#0f0f0f] border border-white/5 rounded-2xl p-6"
          >
            <div className="flex items-center gap-3 mb-3">
              <div className="w-10 h-10 rounded-full bg-green-500/10 flex items-center justify-center">
                <Wallet className="w-5 h-5 text-green-400" />
              </div>
              <span className="text-white/60 text-sm">Баланс</span>
            </div>
            <div className="text-3xl font-bold">{money(profile?.balance_rub ?? 0)}</div>
          </motion.div>

          <motion.div
            initial={{ opacity: 0, y: 20 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ delay: 0.1 }}
            className="bg-[#0f0f0f] border border-white/5 rounded-2xl p-6"
          >
            <div className="flex items-center gap-3 mb-3">
              <div className="w-10 h-10 rounded-full bg-blue-500/10 flex items-center justify-center">
                <TrendingUp className="w-5 h-5 text-blue-400" />
              </div>
              <span className="text-white/60 text-sm">Всего заработано</span>
            </div>
            <div className="text-3xl font-bold">{money(profile?.total_earned_rub ?? 0)}</div>
          </motion.div>

          <motion.div
            initial={{ opacity: 0, y: 20 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ delay: 0.2 }}
            className="bg-[#0f0f0f] border border-white/5 rounded-2xl p-6"
          >
            <div className="flex items-center gap-3 mb-3">
              <div className="w-10 h-10 rounded-full bg-purple-500/10 flex items-center justify-center">
                <Trophy className="w-5 h-5 text-purple-400" />
              </div>
              <span className="text-white/60 text-sm">Игр всего</span>
            </div>
            <div className="text-3xl font-bold">{stats?.total_games ?? 0}</div>
          </motion.div>

          <motion.div
            initial={{ opacity: 0, y: 20 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ delay: 0.3 }}
            className="bg-[#0f0f0f] border border-white/5 rounded-2xl p-6"
          >
            <div className="flex items-center gap-3 mb-3">
              <div className="w-10 h-10 rounded-full bg-orange-500/10 flex items-center justify-center">
                <DollarSign className="w-5 h-5 text-orange-400" />
              </div>
              <span className="text-white/60 text-sm">За сегодня</span>
            </div>
            <div className="text-3xl font-bold">{money(stats?.commission_today ?? 0)}</div>
            <div className="text-white/40 text-xs mt-1">{stats?.games_today ?? 0} игр</div>
          </motion.div>
        </div>

        {/* Tabs */}
        <div className="flex gap-4 mb-6 border-b border-white/5">
          {[
            { key: "overview", label: "Обзор" },
            { key: "games", label: "История игр" },
            { key: "withdrawals", label: "Выплаты" },
          ].map((t) => (
            <button
              key={t.key}
              onClick={() => setTab(t.key as typeof tab)}
              className={`px-4 py-3 font-medium transition-colors relative ${
                tab === t.key ? "text-white" : "text-white/40 hover:text-white/60"
              }`}
            >
              {t.label}
              {tab === t.key && (
                <motion.div
                  layoutId="activeTab"
                  className="absolute bottom-0 left-0 right-0 h-0.5 bg-white"
                />
              )}
            </button>
          ))}
        </div>

        {/* Tab Content */}
        {tab === "overview" && (
          <div className="space-y-6">
            {/* Period Selector */}
            <div className="flex gap-2">
              {[7, 30, 90].map((d) => (
                <button
                  key={d}
                  onClick={() => setChartPeriod(d)}
                  className={`px-4 py-2 rounded-lg text-sm font-medium transition-colors ${
                    chartPeriod === d
                      ? "bg-white text-black"
                      : "bg-white/5 text-white/60 hover:bg-white/10"
                  }`}
                >
                  {d} дней
                </button>
              ))}
            </div>

            <div className="bg-[#0f0f0f] border border-white/5 rounded-2xl p-6">
              <h3 className="text-lg font-semibold mb-4">График прибыли</h3>
              {chartError ? (
                <div className="flex h-64 flex-col items-center justify-center gap-3 text-sm text-yellow-100">
                  <span>{chartError}</span>
                  <button type="button" onClick={() => void loadChart(chartPeriod)} className="rounded-lg bg-white px-3 py-2 font-medium text-black hover:bg-white/90">
                    Повторить
                  </button>
                </div>
              ) : (
                <LineAreaChart
                  points={chartPoints.map((point) => ({ key: point.date, label: point.date.slice(5) }))}
                  series={[
                    { key: "commission", label: "Доход", color: "var(--green)", values: chartPoints.map((point) => point.commission), fill: true },
                    { key: "games", label: "Игры", color: "var(--blue)", values: chartPoints.map((point) => point.games), axis: "right" },
                  ]}
                  height={256}
                  hover={chartHover}
                  onHover={setChartHover}
                  formatTick={money}
                  formatTickRight={(value) => String(Math.round(value))}
                  summary={`${money(chartPoints.reduce((total, point) => total + point.commission, 0))} за период · ${chartPoints.reduce((total, point) => total + point.games, 0)} игр`}
                  tooltip={(index) => {
                    const point = chartPoints[index];
                    return point ? <div className="flex flex-col gap-0.5"><span>{point.date}</span><span className="text-green-300">{money(point.commission)} доход</span><span className="text-purple-300">{point.games} игр</span></div> : null;
                  }}
                  emptyHint="За выбранный период ещё нет дохода или завершённых игр"
                />
              )}
            </div>

            {/* Quick Stats */}
            <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
              <div className="bg-[#0f0f0f] border border-white/5 rounded-xl p-4">
                <div className="text-white/60 text-sm mb-2">За неделю</div>
                <div className="text-2xl font-bold">{money(stats?.commission_week ?? 0)}</div>
                <div className="text-white/40 text-xs mt-1">{stats?.games_week ?? 0} игр</div>
              </div>
              <div className="bg-[#0f0f0f] border border-white/5 rounded-xl p-4">
                <div className="text-white/60 text-sm mb-2">За месяц</div>
                <div className="text-2xl font-bold">{money(stats?.commission_month ?? 0)}</div>
                <div className="text-white/40 text-xs mt-1">{stats?.games_month ?? 0} игр</div>
              </div>
              <div className="bg-[#0f0f0f] border border-white/5 rounded-xl p-4">
                <div className="text-white/60 text-sm mb-2">Выведено</div>
                <div className="text-2xl font-bold">{money(profile?.total_withdrawn_rub ?? 0)}</div>
              </div>
            </div>
          </div>
        )}

        {tab === "games" && (
          <div className="bg-[#0f0f0f] border border-white/5 rounded-2xl overflow-hidden">
            <table className="w-full">
              <thead className="bg-white/5">
                <tr>
                  <th className="text-left p-4 text-sm font-medium text-white/60">Дата</th>
                  <th className="text-left p-4 text-sm font-medium text-white/60">Игра</th>
                  <th className="text-right p-4 text-sm font-medium text-white/60">Ставка</th>
                  <th className="text-right p-4 text-sm font-medium text-white/60">Комиссия</th>
                  <th className="text-right p-4 text-sm font-medium text-white/60">Моя доля</th>
                  <th className="text-center p-4 text-sm font-medium text-white/60">Статус</th>
                </tr>
              </thead>
              <tbody>
                {games.map((game) => (
                  <tr key={game.id} className="border-t border-white/5 hover:bg-white/[0.02]">
                    <td className="p-4 text-sm text-white/80">
                      {new Date(game.created_at).toLocaleString("ru")}
                    </td>
                    <td className="p-4 text-sm">{gameTypeLabel(game.game_type)}</td>
                    <td className="p-4 text-sm text-right">{game.bet_rub.toFixed(2)} ₽</td>
                    <td className="p-4 text-sm text-right text-white/60">
                      {game.commission_rub.toFixed(2)} ₽
                    </td>
                    <td className="p-4 text-sm text-right font-semibold text-green-400">
                      +{game.my_commission.toFixed(2)} ₽
                    </td>
                    <td className="p-4 text-center">
                      <span className="text-xs px-2 py-1 rounded-full bg-green-500/10 text-green-400">
                        {game.status}
                      </span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}

        {tab === "withdrawals" && (
          <div className="space-y-6">
            <button
              onClick={startWithdrawal}
              disabled={!profile}
              className="px-6 py-3 bg-white text-black font-medium rounded-xl hover:bg-white/90 transition-colors disabled:cursor-not-allowed disabled:opacity-60 flex items-center gap-2"
            >
              <Download className="w-4 h-4" />
              Создать заявку на вывод
            </button>

            <div className="bg-[#0f0f0f] border border-white/5 rounded-2xl overflow-hidden">
              <table className="w-full">
                <thead className="bg-white/5">
                  <tr>
                    <th className="text-left p-4 text-sm font-medium text-white/60">Дата</th>
                    <th className="text-right p-4 text-sm font-medium text-white/60">Сумма</th>
                    <th className="text-left p-4 text-sm font-medium text-white/60">Метод</th>
                    <th className="text-left p-4 text-sm font-medium text-white/60">Реквизиты</th>
                    <th className="text-center p-4 text-sm font-medium text-white/60">Статус</th>
                  </tr>
                </thead>
                <tbody>
                  {withdrawals.map((w) => (
                    <tr key={w.id} className="border-t border-white/5">
                      <td className="p-4 text-sm text-white/80">
                        {new Date(w.created_at).toLocaleString("ru")}
                      </td>
                      <td className="p-4 text-sm text-right font-semibold">
                        {w.amount_rub.toFixed(2)} ₽
                      </td>
                      <td className="p-4 text-sm">
                        {w.method === "crypto" && w.crypto
                          ? `${w.crypto.toUpperCase()} (${w.network})`
                          : w.method}
                      </td>
                      <td className="p-4 text-sm text-white/60 font-mono text-xs">
                        {w.requisites.length > 30
                          ? w.requisites.substring(0, 30) + "..."
                          : w.requisites}
                      </td>
                      <td className="p-4 text-center">
                        <span className={`text-xs px-2 py-1 rounded-full ${statusColor(w.status)}`}>
                          {w.status}
                        </span>
                        {w.reject_reason && (
                          <div className="text-xs text-red-400 mt-1">{w.reject_reason}</div>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        )}
      </div>

      {/* Withdrawal Modal */}
      {showWithdrawalModal && (
        <div className="fixed inset-0 bg-black/80 flex items-center justify-center z-50 p-4">
          <motion.div
            initial={{ scale: 0.9, opacity: 0 }}
            animate={{ scale: 1, opacity: 1 }}
            className="bg-[#0f0f0f] border border-white/10 rounded-2xl p-6 max-w-md w-full"
          >
            <h2 className="text-xl font-semibold mb-4">Создать заявку на вывод</h2>
            <form onSubmit={handleWithdrawal} className="space-y-4">
              <div>
                <label className="block text-sm text-white/60 mb-2">
                  Сумма (₽), минимум {profile?.min_withdrawal_rub.toFixed(2)} ₽
                </label>
                <input
                  type="number"
                  step="0.01"
                  min={profile?.min_withdrawal_rub ?? 100}
                  value={withdrawalForm.amount_rub}
                  onChange={(e) => updateWithdrawalForm({ amount_rub: e.target.value })}
                  className="w-full bg-white/5 border border-white/10 rounded-lg px-4 py-3 text-white"
                  required
                />
              </div>

              <div>
                <label className="block text-sm text-white/60 mb-2">Метод</label>
                <select
                  value={withdrawalForm.method}
                  onChange={(e) => updateWithdrawalForm({ method: e.target.value })}
                  className="w-full bg-white/5 border border-white/10 rounded-lg px-4 py-3 text-white"
                >
                  <option value="crypto">Криптовалюта</option>
                  <option value="card">Карта</option>
                  <option value="sbp">СБП</option>
                </select>
              </div>

              {withdrawalForm.method === "crypto" && (
                <>
                  <div>
                    <label className="block text-sm text-white/60 mb-2">Монета</label>
                    <select
                      value={withdrawalForm.crypto}
                      onChange={(e) => updateWithdrawalForm({ crypto: e.target.value })}
                      className="w-full bg-white/5 border border-white/10 rounded-lg px-4 py-3 text-white"
                    >
                      <option value="usdt">USDT</option>
                      <option value="btc">BTC</option>
                      <option value="trx">TRX</option>
                    </select>
                  </div>
                  <div>
                    <label className="block text-sm text-white/60 mb-2">Сеть</label>
                    <select
                      value={withdrawalForm.network}
                      onChange={(e) => updateWithdrawalForm({ network: e.target.value })}
                      className="w-full bg-white/5 border border-white/10 rounded-lg px-4 py-3 text-white"
                    >
                      <option value="trc20">TRC20</option>
                      <option value="erc20">ERC20</option>
                      <option value="bep20">BEP20</option>
                    </select>
                  </div>
                </>
              )}

              <div>
                <label className="block text-sm text-white/60 mb-2">Реквизиты</label>
                <input
                  type="text"
                  value={withdrawalForm.requisites}
                  onChange={(e) => updateWithdrawalForm({ requisites: e.target.value })}
                  placeholder={
                    withdrawalForm.method === "crypto"
                      ? "Адрес кошелька"
                      : withdrawalForm.method === "card"
                      ? "Номер карты"
                      : "Номер телефона"
                  }
                  className="w-full bg-white/5 border border-white/10 rounded-lg px-4 py-3 text-white"
                  required
                />
              </div>

              {withdrawalForm.method === "card" ? (
                <p className="text-sm text-white/60">{CARD_WITHDRAW_PROMISE}</p>
              ) : null}
              <p className="text-sm text-white/60">
                Если результат создания не подтвердился, повторите отправку с теми же данными.
              </p>
              <div className="flex gap-3">
                <button
                  type="submit"
                  disabled={withdrawalSubmitting}
                  className="flex-1 px-6 py-3 bg-white text-black font-medium rounded-xl hover:bg-white/90 transition-colors disabled:cursor-not-allowed disabled:opacity-60"
                >
                  {withdrawalSubmitting ? "Создание..." : "Создать"}
                </button>
                <button
                  type="button"
                  disabled={withdrawalSubmitting}
                  onClick={() => {
                    setShowWithdrawalModal(false);
                    resetWithdrawalForm();
                  }}
                  className="px-6 py-3 bg-white/5 text-white font-medium rounded-xl hover:bg-white/10 transition-colors disabled:cursor-not-allowed disabled:opacity-60"
                >
                  Отмена
                </button>
              </div>
            </form>
          </motion.div>
        </div>
      )}
    </div>
  );
}
