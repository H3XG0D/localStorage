import type { AnalyticsBundle } from "@/panel/lib/useAnalyticsData";
import { DataIssues } from "@/panel/admin/analytics/DataIssues";
import { CasinoStatsView } from "@/panel/admin/Casino/CasinoStatsView";
import { Card } from "@/panel/ui/primitives";

export function CasinoTab({ data }: { data: AnalyticsBundle }) {
  return (
    <>
      <DataIssues data={data} slices={["casino", "finance"]} />
      {data.casino ? (
        <CasinoStatsView data={data.casino} />
      ) : (
        <Card className="py-12 text-center text-[13px] text-[var(--text-muted)]">Показатели казино не получены</Card>
      )}
    </>
  );
}
