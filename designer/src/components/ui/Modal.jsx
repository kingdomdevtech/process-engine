import { useCallback, useEffect, useRef } from 'react'
import { createPortal } from 'react-dom'
import { X } from 'lucide-react'

const SIZES = {
  sm: 'max-w-sm',
  md: 'max-w-lg',
  lg: 'max-w-2xl',
  xl: 'max-w-4xl',
}

const FOCUSABLE =
  'a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])'

/**
 * Accessible dialog: labelled, modal to assistive tech, Escape to dismiss,
 * focus moved in on open, trapped while open and returned to the trigger on
 * close (WCAG 2.4.3). Body scroll is locked so the page behind cannot move.
 */
export default function Modal({
  open,
  onClose,
  title,
  description,
  icon,
  footer,
  children,
  size = 'md',
  closeOnBackdrop = true,
  initialFocus,
}) {
  const panel = useRef(null)
  const restoreTo = useRef(null)
  const titleId = useRef(`dlg-${Math.random().toString(36).slice(2, 9)}`).current

  const focusFirst = useCallback(() => {
    const target =
      initialFocus?.current ??
      panel.current?.querySelector('[data-autofocus]') ??
      panel.current?.querySelector(FOCUSABLE) ??
      panel.current
    target?.focus()
  }, [initialFocus])

  useEffect(() => {
    if (!open) return undefined

    restoreTo.current = document.activeElement
    const { overflow } = document.body.style
    document.body.style.overflow = 'hidden'
    const raf = requestAnimationFrame(focusFirst)

    const onKeyDown = (event) => {
      if (event.key === 'Escape') {
        event.stopPropagation()
        onClose?.()
        return
      }
      if (event.key !== 'Tab' || !panel.current) return
      const items = [...panel.current.querySelectorAll(FOCUSABLE)].filter(
        (node) => node.offsetParent !== null,
      )
      if (items.length === 0) return
      const first = items[0]
      const last = items[items.length - 1]
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault()
        last.focus()
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault()
        first.focus()
      }
    }

    document.addEventListener('keydown', onKeyDown, true)
    return () => {
      cancelAnimationFrame(raf)
      document.removeEventListener('keydown', onKeyDown, true)
      document.body.style.overflow = overflow
      restoreTo.current?.focus?.()
    }
  }, [open, onClose, focusFirst])

  if (!open) return null

  return createPortal(
    <div
      className="animate-fade fixed inset-0 z-50 grid place-items-center overflow-y-auto bg-overlay p-4 backdrop-blur-[2px]"
      onMouseDown={(event) => {
        if (closeOnBackdrop && event.target === event.currentTarget) onClose?.()
      }}
    >
      <div
        ref={panel}
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        className={`animate-zoom flex max-h-[calc(100vh-2rem)] w-full ${SIZES[size]} flex-col overflow-hidden rounded-xl border border-line bg-raised shadow-xl`}
      >
        <header className="flex items-start gap-3 border-b border-line px-5 py-4">
          {icon}
          <div className="min-w-0 flex-1">
            <h2 id={titleId} className="text-[15px] font-semibold">
              {title}
            </h2>
            {description && <p className="mt-0.5 text-xs text-fg-muted">{description}</p>}
          </div>
          <button className="btn btn-ghost btn-icon btn-sm -mr-1.5" onClick={onClose} aria-label="Close dialog">
            <X size={16} />
          </button>
        </header>

        <div className="min-h-0 flex-1 overflow-y-auto px-5 py-4">{children}</div>

        {footer && (
          <footer className="flex items-center justify-end gap-2 border-t border-line bg-surface-2 px-5 py-3">
            {footer}
          </footer>
        )}
      </div>
    </div>,
    document.body,
  )
}
