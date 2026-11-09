import { useQuery } from '@tanstack/react-query';
import { formatUsdt, getStatsApi, StatsScope } from '../../api/client';
import { AppShell } from '../../components/layout/AppShell';
import { PageHeader } from '../../components/ui/SearchInput';
import { Tabs } from '../../components/ui/Tabs';
import { useState } from 'react';

interface TraderStatRow {
  user_id: number;
  login: string;
  full_name: string;
  requisites_count: number;
  total_turnover: string;
  total_turnover_usdt?: string;
  total_profit: string;
  avg_profit_per_requisite: string;
}

interface DolivStatRow {
  user_id: number;
  login: string;
  full_name: string;
  dolivs_count: number;
  total_doliv_amount: string;
  total_doliv_amount_usdt?: string;
  avg_doliv_rate: string;
  total_processed: string;
  total_doliv_loss: string;
}

const MEDALS = ['🥇', '🥈', '🥉'];
const PODIUM_HEIGHT = ['h-28', 'h-20', 'h-16'];
const PODIUM_LABEL = ['1', '2', '3'];
const PODIUM_ORDER = [1, 0, 2]; // 2nd, 1st, 3rd visual order for podium

interface PodiumCardProps {
  rank: number;
  login: string;
  fullName: string;
  mainValue: string;
  subLabel: string;
}

function PodiumCard({ rank, login, fullName, mainValue, subLabel }: PodiumCardProps) {
  const isFirst = rank === 0;
  return (
    <div className={`flex flex-col items-center gap-2 ${isFirst ? 'order-2' : rank === 1 ? 'order-1' : 'order-3'}`}>
      <div className="text-2xl">{MEDALS[rank]}</div>
      <div className={`w-10 h-10 rounded-full flex items-center justify-center text-sm font-bold ${
        isFirst ? 'bg-amber-500/30 text-amber-200' : 'bg-elevated text-muted'
      }`}>
        {login.slice(0, 2).toUpperCase()}
      </div>
      <div className="text-center">
        <p className={`text-sm font-semibold ${isFirst ? 'text-accent' : 'text-white'}`}>@{login}</p>
        {fullName && <p className="text-[10px] text-muted truncate max-w-24">{fullName}</p>}
        <p className={`text-xs font-bold mt-0.5 ${isFirst ? 'text-emerald-400' : 'text-emerald-300/70'}`}>{mainValue}</p>
        <p className="text-[10px] text-muted">{subLabel}</p>
      </div>
      <div className={`w-full rounded-t-lg flex items-center justify-center text-xs font-bold text-muted ${PODIUM_HEIGHT[rank]} ${
        isFirst ? 'bg-amber-500/20 border border-amber-500/30' : 'bg-elevated/60 border border-border/40'
      }`}>
        {PODIUM_LABEL[rank]}
      </div>
    </div>
  );
}

export function RatingsPage({ scope = 'admin' }: { scope?: StatsScope }) {
  const statsApi = getStatsApi(scope);
  const queryPrefix = scope === 'owner' ? 'owner' : 'admin';
  const [tab, setTab] = useState('traders');

  const { data: traders } = useQuery({
    queryKey: [`${queryPrefix}-traders`],
    queryFn: statsApi.statsTraders,
  }) as { data: TraderStatRow[] | undefined };

  const { data: dolivshchiks } = useQuery({
    queryKey: [`${queryPrefix}-dolivshchiks`],
    queryFn: statsApi.statsDolivshchiks,
  }) as { data: DolivStatRow[] | undefined };

  const sortedTraders = [...(traders ?? [])].sort((a, b) => parseFloat(b.total_profit) - parseFloat(a.total_profit));
  const sortedDoliv = [...(dolivshchiks ?? [])].sort((a, b) => parseFloat(b.total_doliv_loss ?? '0') - parseFloat(a.total_doliv_loss ?? '0'));

  const topTraders = sortedTraders.slice(0, 3);
  const restTraders = sortedTraders.slice(3);
  const topDoliv = sortedDoliv.slice(0, 3);
  const restDoliv = sortedDoliv.slice(3);

  return (
    <AppShell title="Рейтинги">
      <PageHeader title="Рейтинги" subtitle="Топ сотрудников по результатам" />

      <Tabs
        tabs={[
          { id: 'traders', label: 'Трейдеры' },
          { id: 'dolivshchiks', label: 'Доливщики' },
        ]}
        active={tab}
        onChange={setTab}
      />

      {tab === 'traders' && (
        <div className="space-y-6 mt-2">
          {/* Podium */}
          {topTraders.length > 0 && (
            <div className="card">
              <h3 className="text-sm font-semibold text-muted mb-6 text-center">Топ-3 трейдера по прибыли</h3>
              <div className="overflow-x-auto">
              <div className="flex items-end justify-center gap-4 px-4 min-w-[300px]">
                {PODIUM_ORDER.map((rankIdx) => {
                  const t = topTraders[rankIdx];
                  if (!t) return <div key={rankIdx} className="flex-1 max-w-32" />;
                  return (
                    <div key={t.user_id} className="flex-1 max-w-32">
                      <PodiumCard
                        rank={rankIdx}
                        login={t.login || t.full_name}
                        fullName={t.login ? t.full_name : ''}
                        mainValue={formatUsdt(t.total_profit)}
                        subLabel={`${t.requisites_count} реквизитов`}
                      />
                    </div>
                  );
                })}
              </div>
              </div>
            </div>
          )}

          {/* Rest of the table */}
          {restTraders.length > 0 && (
            <div className="overflow-x-auto rounded-xl border border-border/50">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-border/50 bg-elevated/60 text-xs text-muted font-medium">
                    <th className="px-4 py-3 text-left w-12">#</th>
                    <th className="px-4 py-3 text-left">Трейдер</th>
                    <th className="px-4 py-3 text-right">Реквизитов</th>
                    <th className="px-4 py-3 text-right">Оборот (USDT)</th>
                    <th className="px-4 py-3 text-right">Прибыль (USDT)</th>
                    <th className="px-4 py-3 text-right">Сред. прибыль (USDT)</th>
                  </tr>
                </thead>
                <tbody>
                  {restTraders.map((t, i) => (
                    <tr key={t.user_id} className="border-b border-border/30 hover:bg-elevated/40 transition-colors">
                      <td className="px-4 py-3 text-muted">{i + 4}</td>
                      <td className="px-4 py-3">
                        <p className="font-semibold">@{t.login || t.full_name}</p>
                        {t.login && t.full_name && <p className="text-xs text-muted">{t.full_name}</p>}
                      </td>
                      <td className="px-4 py-3 text-right text-muted">{t.requisites_count}</td>
                      <td className="px-4 py-3 text-right">{formatUsdt(t.total_turnover_usdt ?? '0')}</td>
                      <td className="px-4 py-3 text-right text-emerald-400 font-medium">{formatUsdt(t.total_profit)}</td>
                      <td className="px-4 py-3 text-right text-muted">{formatUsdt(t.avg_profit_per_requisite)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}

          {sortedTraders.length === 0 && (
            <p className="text-center text-muted py-12">Нет данных по трейдерам</p>
          )}
        </div>
      )}

      {tab === 'dolivshchiks' && (
        <div className="space-y-6 mt-2">
          {/* Podium */}
          {topDoliv.length > 0 && (
            <div className="card">
              <h3 className="text-sm font-semibold text-muted mb-6 text-center">Топ-3 доливщика по потерям</h3>
              <div className="overflow-x-auto">
              <div className="flex items-end justify-center gap-4 px-4 min-w-[300px]">
                {PODIUM_ORDER.map((rankIdx) => {
                  const d = topDoliv[rankIdx];
                  if (!d) return <div key={rankIdx} className="flex-1 max-w-32" />;
                  return (
                    <div key={d.user_id} className="flex-1 max-w-32">
                      <PodiumCard
                        rank={rankIdx}
                        login={d.login || d.full_name}
                        fullName={d.login ? d.full_name : ''}
                        mainValue={formatUsdt(d.total_doliv_loss ?? '0')}
                        subLabel={`${d.dolivs_count} доливов`}
                      />
                    </div>
                  );
                })}
              </div>
              </div>
            </div>
          )}

          {restDoliv.length > 0 && (
            <div className="overflow-x-auto rounded-xl border border-border/50">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-border/50 bg-elevated/60 text-xs text-muted font-medium">
                    <th className="px-4 py-3 text-left w-12">#</th>
                    <th className="px-4 py-3 text-left">Доливщик</th>
                    <th className="px-4 py-3 text-right">Доливов</th>
                    <th className="px-4 py-3 text-right">Сумма (USDT)</th>
                    <th className="px-4 py-3 text-right">Сред. курс</th>
                    <th className="px-4 py-3 text-right">Потери (USDT)</th>
                  </tr>
                </thead>
                <tbody>
                  {restDoliv.map((d, i) => (
                    <tr key={d.user_id} className="border-b border-border/30 hover:bg-elevated/40 transition-colors">
                      <td className="px-4 py-3 text-muted">{i + 4}</td>
                      <td className="px-4 py-3">
                        <p className="font-semibold">@{d.login || d.full_name}</p>
                        {d.login && d.full_name && <p className="text-xs text-muted">{d.full_name}</p>}
                      </td>
                      <td className="px-4 py-3 text-right text-muted">{d.dolivs_count}</td>
                      <td className="px-4 py-3 text-right font-medium">{formatUsdt(d.total_doliv_amount_usdt ?? '0')}</td>
                      <td className="px-4 py-3 text-right text-muted">{d.avg_doliv_rate}</td>
                      <td className="px-4 py-3 text-right text-red-400">{formatUsdt(d.total_doliv_loss ?? '0')}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}

          {sortedDoliv.length === 0 && (
            <p className="text-center text-muted py-12">Нет данных по доливщикам</p>
          )}
        </div>
      )}
    </AppShell>
  );
}

export default function AdminRatings() {
  return <RatingsPage scope="admin" />;
}
