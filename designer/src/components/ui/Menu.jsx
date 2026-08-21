import { useEffect, useId, useLayoutEffect, useRef, useState } from 'react'

const GAP = 6 // matches the mt-1.5/mb-1.5 offset below

/**
 * Dropdown menu. Closes on outside click, on Escape (returning focus to the
 * trigger) and on selection; arrow keys move between items so it is operable
 * without a mouse.
 *
 * Drops upward when there is no room below — the account menu hangs off a
 * trigger pinned to the bottom of the sidebar, so dropping down would put every
 * item, sign out included, past the bottom of the window with no way to scroll
 * to it.
 */
export default function Menu({ trigger, children, align = 'end', className = '', label = 'Open menu' }) {
  const [open, setOpen] = useState(false)
  const [dropUp, setDropUp] = useState(false)
  const wrap = useRef(null)
  const list = useRef(null)
  const id = useId()

  // Before paint, so the menu never shows in the wrong place first.
  useLayoutEffect(() => {
    if (!open || !wrap.current || !list.current) return
    const trigger = wrap.current.getBoundingClientRect()
    const needed = list.current.offsetHeight + GAP
    const below = window.innerHeight - trigger.bottom
    setDropUp(below < needed && trigger.top > below)
  }, [open])

  useEffect(() => {
    if (!open) return undefined

    const onPointerDown = (event) => {
      if (!wrap.current?.contains(event.target)) setOpen(false)
    }
    const onKeyDown = (event) => {
      if (event.key === 'Escape') {
        setOpen(false)
        wrap.current?.querySelector('[aria-haspopup]')?.focus()
        return
      }
      if (event.key !== 'ArrowDown' && event.key !== 'ArrowUp') return
      const items = [...(list.current?.querySelectorAll('[role="menuitem"]:not([disabled])') ?? [])]
      if (items.length === 0) return
      event.preventDefault()
      const at = items.indexOf(document.activeElement)
      const next = event.key === 'ArrowDown' ? at + 1 : at - 1
      items[(next + items.length) % items.length].focus()
    }

    document.addEventListener('pointerdown', onPointerDown)
    document.addEventListener('keydown', onKeyDown)
    return () => {
      document.removeEventListener('pointerdown', onPointerDown)
      document.removeEventListener('keydown', onKeyDown)
    }
  }, [open])

  return (
    <div ref={wrap} className={`relative ${className}`}>
      <button
        type="button"
        aria-haspopup="menu"
        aria-expanded={open}
        aria-controls={open ? id : undefined}
        aria-label={typeof trigger === 'string' ? undefined : label}
        className="contents"
        onClick={() => setOpen((value) => !value)}
      >
        {trigger}
      </button>
      {open && (
        <div
          id={id}
          ref={list}
          role="menu"
          className={`animate-zoom absolute z-40 min-w-52 rounded-lg border border-line bg-raised p-1 shadow-lg ${
            align === 'end' ? 'right-0' : 'left-0'
          } ${dropUp ? 'bottom-full mb-1.5' : 'top-full mt-1.5'}`}
          onClick={(event) => {
            // Any activated item dismisses the menu, matching platform behaviour.
            if (event.target.closest('[role="menuitem"]')) setOpen(false)
          }}
        >
          {children}
        </div>
      )}
    </div>
  )
}

export function MenuItem({ icon, children, danger = false, className = '', ...props }) {
  return (
    <button
      type="button"
      role="menuitem"
      className={`menu-item ${danger ? 'menu-item-danger' : ''} ${className}`}
      {...props}
    >
      {icon && <span className="shrink-0 text-fg-subtle">{icon}</span>}
      <span className="min-w-0 flex-1 truncate">{children}</span>
    </button>
  )
}

export function MenuLabel({ children, className = '', ...props }) {
  return (
    <div className={`px-2.5 py-1 text-[10px] font-bold uppercase tracking-wider text-fg-subtle ${className}`} {...props}>
      {children}
    </div>
  )
}

export function MenuSeparator() {
  return <div role="separator" className="my-1 h-px bg-line" />
}
