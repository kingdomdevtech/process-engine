import { brand } from '../brand.js'

/**
 * The mark: a process in miniature — one step branching into two, drawn with
 * the same rounded step cards and smoothstep edges as the canvas itself. The
 * product's own geometry is its identity.
 *
 * The gradient is the one place brand colour is allowed to be decorative;
 * everywhere else colour carries meaning. It holds contrast on both themes,
 * so there is no separate dark-mode mark to keep in sync.
 *
 * These two stops are literals rather than tokens on purpose: a logo is a
 * fixed asset, and a mark that re-themed with the app would not be one. They
 * run from just below --brand to a cyan, so the mark stays in the brand family
 * without being tied to it — move them by hand if the brand hue moves. The
 * favicon (designer/public/favicon.svg) duplicates this geometry; keep the
 * two in step.
 */
export function LogoMark({ size = 28, id = 'pe' }) {
  return (
    <svg width={size} height={size} viewBox="0 0 64 64" aria-hidden="true" className="shrink-0">
      <defs>
        <linearGradient id={`${id}-g`} x1="0" y1="1" x2="1" y2="0">
          <stop offset="0" stopColor="#2550a4" />
          <stop offset="1" stopColor="#02a6ad" />
        </linearGradient>
      </defs>
      <rect width="64" height="64" rx="15" fill={`url(#${id}-g)`} />
      <path
        d="M22 32 C32 32 32 16 42 16 M22 32 C32 32 32 48 42 48"
        stroke="#ffffff"
        strokeWidth="5"
        strokeLinecap="round"
        fill="none"
        opacity="0.85"
      />
      <rect x="9" y="25.5" width="13" height="13" rx="3.5" fill="#ffffff" />
      <rect x="42" y="9.5" width="13" height="13" rx="3.5" fill="#ffffff" />
      <rect x="42" y="41.5" width="13" height="13" rx="3.5" fill="#ffffff" />
    </svg>
  )
}

export default function Logo({ size = 28, showName = true, id = 'pe', className = '' }) {
  return (
    <span className={`inline-flex items-center gap-2 ${className}`}>
      <LogoMark size={size} id={id} />
      {showName && (
        <span className="truncate text-[15px] font-bold tracking-[-0.015em] text-fg">{brand.name}</span>
      )}
    </span>
  )
}
