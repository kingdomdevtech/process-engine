import { Inbox } from 'lucide-react'

/**
 * Empty states explain what the space is for and offer the action that fills
 * it — an empty area with no next step is a dead end.
 */
export default function EmptyState({ icon: Icon = Inbox, title, children, action, compact = false }) {
  return (
    <div
      className={`flex flex-col items-center justify-center rounded-xl border border-dashed border-line bg-surface text-center ${
        compact ? 'px-4 py-8' : 'px-6 py-14'
      }`}
    >
      {/* The soft brand sweep, not grey — an empty state is an invitation,
          and grey-on-grey reads as "nothing to do here". */}
      <span className="brand-tile-soft mb-3 grid size-11 place-items-center rounded-xl" aria-hidden="true">
        <Icon size={20} />
      </span>
      <h3 className="text-sm font-semibold">{title}</h3>
      {children && <p className="mt-1.5 max-w-md text-[13px] text-fg-muted">{children}</p>}
      {action && <div className="mt-4 flex flex-wrap justify-center gap-2">{action}</div>}
    </div>
  )
}
