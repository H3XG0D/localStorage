import { PageHeader, Card } from "@/panel/ui/primitives";

// Temporary screen for panel routes not yet ported. Replaced section by section.
export function PanelPlaceholder({ title }: { title: string }) {
  return (
    <>
      <PageHeader title={title} subtitle="Раздел переносится на новый интерфейс" />
      <Card>
        <p className="text-[13px] text-[var(--text-muted)]">Экран «{title}» готовится. Данные и действия появятся здесь.</p>
      </Card>
    </>
  );
}
