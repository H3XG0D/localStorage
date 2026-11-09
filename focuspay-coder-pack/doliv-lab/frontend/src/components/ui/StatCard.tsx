import { ReactNode } from 'react';
import { LucideIcon } from 'lucide-react';

interface StatCardProps {
  label: string;
  value: string | number;
  icon: LucideIcon;
  trend?: string;
  trendUp?: boolean;
  accent?: string;
}

export function StatCard({ label, value, icon: Icon, trend, trendUp, accent }: StatCardProps) {
  return (
    <div className="card flex flex-col gap-3">
      <div className="flex items-start justify-between">
        <div
          className="p-2 rounded-lg"
          style={{ backgroundColor: accent ? `${accent}20` : '#6366f120' }}
        >
          <Icon size={18} style={{ color: accent || '#6366f1' }} />
        </div>
        {trend && (
          <span className={`text-xs font-medium ${trendUp ? 'text-emerald-400' : 'text-red-400'}`}>
            {trend}
          </span>
        )}
      </div>
      <div>
        <p className="text-xs text-muted mb-1">{label}</p>
        <p className="text-xl font-bold tracking-tight text-[#fafafa]">{value}</p>
      </div>
    </div>
  );
}

interface ChartCardProps {
  title: string;
  children: ReactNode;
  action?: ReactNode;
}

export function ChartCard({ title, children, action }: ChartCardProps) {
  return (
    <div className="card">
      <div className="flex items-center justify-between mb-4">
        <h3 className="font-semibold text-sm text-[#fafafa]">{title}</h3>
        {action}
      </div>
      {children}
    </div>
  );
}
