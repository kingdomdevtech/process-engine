import {
  Ban,
  CheckCircle2,
  Circle,
  Clock,
  Loader2,
  MinusCircle,
  PauseCircle,
  XCircle,
} from 'lucide-react'

/**
 * Run and step status, shown as icon + colour + word.
 *
 * Three redundant encodings on purpose: colour alone fails for ~4% of users
 * and in greyscale print-outs, and these badges end up in incident reports.
 */
export const STATUS = {
  succeeded: { label: 'Succeeded', icon: CheckCircle2 },
  failed: { label: 'Failed', icon: XCircle },
  running: { label: 'Running', icon: Loader2 },
  paused: { label: 'Paused', icon: PauseCircle },
  cancelled: { label: 'Cancelled', icon: Ban },
  skipped: { label: 'Skipped', icon: MinusCircle },
  pending: { label: 'Pending', icon: Clock },
}

export default function StatusBadge({ status, size = 12, className = '' }) {
  const meta = STATUS[status] ?? { label: status ?? 'unknown', icon: Circle }
  const Icon = meta.icon
  return (
    <span className={`badge badge-${status} ${className}`}>
      <Icon
        size={size}
        className={status === 'running' ? 'animate-spin-slow' : ''}
        aria-hidden="true"
      />
      {meta.label}
    </span>
  )
}
