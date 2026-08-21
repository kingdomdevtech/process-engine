import { useId, useState } from 'react'

/**
 * Hover/focus tooltip for controls whose label is not visible — icon-only
 * buttons and the collapsed sidebar. Shown on focus as well as hover so it is
 * reachable by keyboard, and wired with aria-describedby rather than replacing
 * the accessible name.
 */
export default function Tooltip({ label, side = 'right', children, className = '' }) {
  const [shown, setShown] = useState(false)
  const id = useId()

  const position = {
    right: 'left-full top-1/2 ml-2 -translate-y-1/2',
    left: 'right-full top-1/2 mr-2 -translate-y-1/2',
    top: 'bottom-full left-1/2 mb-2 -translate-x-1/2',
    bottom: 'top-full left-1/2 mt-2 -translate-x-1/2',
  }[side]

  return (
    <span
      className={`relative inline-flex ${className}`}
      onMouseEnter={() => setShown(true)}
      onMouseLeave={() => setShown(false)}
      onFocusCapture={() => setShown(true)}
      onBlurCapture={() => setShown(false)}
    >
      <span aria-describedby={shown ? id : undefined} className="contents">
        {children}
      </span>
      {shown && (
        <span
          id={id}
          role="tooltip"
          className={`animate-fade pointer-events-none absolute z-50 whitespace-nowrap rounded-md border border-line bg-raised px-2 py-1 text-[11px] font-medium text-fg shadow-md ${position}`}
        >
          {label}
        </span>
      )}
    </span>
  )
}
