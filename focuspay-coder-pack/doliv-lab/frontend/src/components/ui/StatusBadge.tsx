import { statusLabel } from '../../api/client';

const STATUS_CLASS: Record<string, string> = {
  active: 'badge-active',
  in_work: 'badge-in_work',
  awaiting_doliv: 'badge-awaiting_doliv',
  doliv_in_progress: 'badge-doliv_in_progress',
  closed: 'badge-closed',
  archive: 'badge-archive',
  pending: 'badge-pending',
  in_progress: 'badge-in_progress',
  completed: 'badge-completed',
  cancelled: 'badge-cancelled',
};

export function StatusBadge({ status }: { status: string }) {
  return (
    <span className={STATUS_CLASS[status] || 'badge bg-zinc-500/15 text-zinc-400'}>
      {statusLabel(status)}
    </span>
  );
}
