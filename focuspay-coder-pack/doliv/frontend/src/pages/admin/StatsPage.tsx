import { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { AlertTriangle, BarChart3, Download } from 'lucide-react';
import { LineChart, Line, XAxis, YAxis, Tooltip, ResponsiveContainer, BarChart, Bar } from 'recharts';
import { formatUsdt, getStatsApi, StatsScope } from '../../api/client';
import { AppShell } from '../../components/layout/AppShell';
import { PageHeader } from '../../components/ui/SearchInput';
import { StatCard } from '../../components/ui/StatCard';
import { ChartCard } from '../../components/ui/StatCard';

interface StatsRecord {
  total_turnover?: string | number;
  total_turnover_usdt?: string | number;
  total_profit?: string | number;
  requisites_count?: number;
  dolivs_count?: number;
  profit_by_day?: { day: string; profit: number; doliv_loss?: number; fake_check_loss?: number; net_profit?: number }[];
  profit_by_week?: { week: string; profit: number; doliv_loss?: number; fake_check_loss?: number; net_profit?: number }[];
  profit_by_month?: { month: string; profit: number; doliv_loss?: number; fake_check_loss?: number; net_profit?: number }[];
  fake_check_count?: number;
  fake_check_loss_rub?: string | number;
  fake_check_loss_usdt?: string | number;
  fake_check_avg_rate?: string | number;
  fake_check_top_requisites?: { requisite_id: number; name: string; loss_usdt: string | number; count: number }[];
  fake_check_top_traders?: { trader_id: number; name: string; loss_usdt: string | number; count: number }[];
}

const TOOLTIP_STYLE = { background: '#141416', border: '1px solid #27272a', borderRadius: 8 };

export function StatsPage({ scope = 'admin' }: { scope?: StatsScope }) {
  const statsApi = getStatsApi(scope);
  const queryPrefix = scope === 'owner' ? 'owner' : 'admin';
  const [chartPeriod, setChartPeriod] = useState<'day' | 'week' | 'month'>('day');
  const [dateStart, setDateStart] = useState('');
  const [dateEnd, setDateEnd] = useState('');
  const [exportError, setExportError] = useState('');

  const params = {
    ...(dateStart ? { start: dateStart } : {}),
    ...(dateEnd ? { end: dateEnd } : {}),
  };

  const { data: overview, isError, refetch } = useQuery({
    queryKey: [`${queryPrefix}-overview`, dateStart, dateEnd],
    queryFn: () => statsApi.statsOverview(
      Object.keys(params).length ? params : undefined
    ),
  }) as { data: StatsRecord | undefined; isError: boolean; refetch: () => void };

  const dayData = (overview?.profit_by_day ?? []).slice().reverse().map((d) => ({
    label: d.day.slice(5),
    profit: d.profit,
  }));

  const weekData = (overview?.profit_by_week ?? []).map((d) => ({
    label: d.week,
    profit: d.profit,
  }));

  const monthData = (overview?.profit_by_month ?? []).map((d) => ({
    label: d.month,
    profit: d.profit,
  }));

  const activeChartData =
    chartPeriod === 'day' ? dayData :
    chartPeriod === 'week' ? weekData :
    monthData;

  const fallback = [{ label: '—', profit: 0 }];

  const exportExcel = async () => {
    setExportError('');
    try {
      const blob = await statsApi.exportExcel();
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = 'stats.xlsx';
      a.click();
      URL.revokeObjectURL(url);
    } catch {
      setExportError('Не удалось выгрузить Excel. Попробуйте позже.');
    }
  };

  const clearDates = () => { setDateStart(''); setDateEnd(''); };

  return (
    <AppShell title="Статистика">
      <PageHeader
        title="Статистика"
        subtitle="Общие показатели системы"
        action={
          <button onClick={exportExcel} className="btn-secondary flex items-center gap-2 text-sm">
            <Download size={14} /> Excel
          </button>
        }
      />

      {isError && (
        <div className="mb-4 rounded-xl border border-red-500/30 bg-red-500/10 px-4 py-3 text-sm text-red-300 flex items-center justify-between gap-3">
          <span>Не удалось загрузить статистику</span>
          <button type="button" className="text-accent hover:text-accent-hover shrink-0" onClick={() => void refetch()}>
            Повторить
          </button>
        </div>
      )}
      {exportError && (
        <div className="mb-4 rounded-xl border border-red-500/30 bg-red-500/10 px-4 py-3 text-sm text-red-300">
          {exportError}
        </div>
      )}

      {/* Date filter */}
      <div className="card mb-5 flex flex-wrap items-center gap-3">
        <span className="text-xs text-muted">Период:</span>
        <div className="flex items-center gap-2">
          <label className="text-xs text-muted">с</label>
          <input
            type="date"
            className="input py-1.5"
            value={dateStart}
            onChange={(e) => setDateStart(e.target.value)}
          />
        </div>
        <div className="flex items-center gap-2">
          <label className="text-xs text-muted">по</label>
          <input
            type="date"
            className="input py-1.5"
            value={dateEnd}
            onChange={(e) => setDateEnd(e.target.value)}
          />
        </div>
        {(dateStart || dateEnd) && (
          <button onClick={clearDates} className="text-xs text-muted hover:text-accent">
            Сбросить
          </button>
        )}
      </div>

      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4 mb-6">
        <StatCard label="Оборот" value={formatUsdt(String(overview?.total_turnover_usdt ?? 0))} icon={BarChart3} accent="#6366f1" />
        <StatCard label="Прибыль" value={formatUsdt(String(overview?.total_profit ?? 0))} icon={BarChart3} accent="#22c55e" />
        <StatCard label="Закрытых сделок" value={overview?.requisites_count ?? 0} icon={BarChart3} accent="#22d3ee" />
        <StatCard label="Доливов" value={overview?.dolivs_count ?? 0} icon={BarChart3} accent="#a78bfa" />
      </div>

      {/* Period selector */}
      <div className="flex gap-2 mb-4">
        {(['day', 'week', 'month'] as const).map((p) => (
          <button
            key={p}
            onClick={() => setChartPeriod(p)}
            className={`px-3 py-1.5 rounded-lg text-xs font-medium transition-colors ${
              chartPeriod === p ? 'bg-accent/15 text-accent' : 'bg-elevated text-muted hover:text-white'
            }`}
          >
            {p === 'day' ? 'По дням' : p === 'week' ? 'По неделям' : 'По месяцам'}
          </button>
        ))}
      </div>

      {(overview?.fake_check_count ?? 0) > 0 && (
        <div className="card mb-6 border border-orange-500/20">
          <div className="flex items-center gap-2 mb-4">
            <AlertTriangle size={16} className="text-orange-400" />
            <h3 className="font-semibold text-sm">Потери по фейк-чекам</h3>
          </div>
          <div className="grid grid-cols-2 lg:grid-cols-4 gap-4 mb-6">
            <div>
              <p className="text-xs text-muted">Количество</p>
              <p className="text-xl font-bold mt-1">{overview?.fake_check_count ?? 0}</p>
            </div>
            <div>
              <p className="text-xs text-muted">Сумма (₽)</p>
              <p className="text-xl font-bold mt-1 text-orange-400">
                {new Intl.NumberFormat('ru-RU', { style: 'currency', currency: 'RUB' }).format(
                  parseFloat(String(overview?.fake_check_loss_rub ?? 0))
                )}
              </p>
            </div>
            <div>
              <p className="text-xs text-muted">Сумма (USDT)</p>
              <p className="text-xl font-bold mt-1 text-red-400">-{formatUsdt(String(overview?.fake_check_loss_usdt ?? 0))}</p>
            </div>
            <div>
              <p className="text-xs text-muted">Средний курс</p>
              <p className="text-xl font-bold mt-1">{parseFloat(String(overview?.fake_check_avg_rate ?? 0)).toFixed(2)}</p>
            </div>
          </div>
          <div className="grid lg:grid-cols-2 gap-4">
            <div>
              <h4 className="text-xs font-medium text-muted mb-2">Топ реквизитов по потерям</h4>
              <ul className="space-y-2">
                {(overview?.fake_check_top_requisites ?? []).map((r) => (
                  <li key={r.requisite_id} className="flex justify-between text-sm rounded-lg bg-elevated/40 px-3 py-2">
                    <span>#{r.requisite_id} {r.name}</span>
                    <span className="text-orange-400">-{formatUsdt(String(r.loss_usdt))} <span className="text-muted">({r.count})</span></span>
                  </li>
                ))}
                {!(overview?.fake_check_top_requisites ?? []).length && (
                  <li className="text-muted text-sm">Нет данных</li>
                )}
              </ul>
            </div>
            <div>
              <h4 className="text-xs font-medium text-muted mb-2">Топ трейдеров</h4>
              <ul className="space-y-2">
                {(overview?.fake_check_top_traders ?? []).map((t) => (
                  <li key={t.trader_id} className="flex justify-between text-sm rounded-lg bg-elevated/40 px-3 py-2">
                    <span>{t.name}</span>
                    <span className="text-orange-400">-{formatUsdt(String(t.loss_usdt))} <span className="text-muted">({t.count})</span></span>
                  </li>
                ))}
                {!(overview?.fake_check_top_traders ?? []).length && (
                  <li className="text-muted text-sm">Нет данных</li>
                )}
              </ul>
            </div>
          </div>
        </div>
      )}

      <div className="grid lg:grid-cols-2 gap-4">
        <ChartCard title={`Прибыль ${chartPeriod === 'day' ? 'по дням' : chartPeriod === 'week' ? 'по неделям' : 'по месяцам'}`}>
          <ResponsiveContainer width="100%" height={220}>
            <LineChart data={activeChartData.length ? activeChartData : fallback}>
              <XAxis dataKey="label" /><YAxis />
              <Tooltip contentStyle={TOOLTIP_STYLE} formatter={(v) => [`${Number(v).toFixed(2)} USDT`, 'Прибыль']} />
              <Line type="monotone" dataKey="profit" stroke="#6366f1" strokeWidth={2} dot={false} />
            </LineChart>
          </ResponsiveContainer>
        </ChartCard>

        <ChartCard title={`Прибыль (столбцы) ${chartPeriod === 'day' ? '— дни' : chartPeriod === 'week' ? '— недели' : '— месяцы'}`}>
          <ResponsiveContainer width="100%" height={220}>
            <BarChart data={activeChartData.length ? activeChartData : fallback}>
              <XAxis dataKey="label" /><YAxis />
              <Tooltip contentStyle={TOOLTIP_STYLE} formatter={(v) => [`${Number(v).toFixed(2)} USDT`, 'Прибыль']} />
              <Bar dataKey="profit" fill="#6366f1" radius={[4, 4, 0, 0]} />
            </BarChart>
          </ResponsiveContainer>
        </ChartCard>
      </div>
    </AppShell>
  );
}

export default function AdminStats() {
  return <StatsPage scope="admin" />;
}
