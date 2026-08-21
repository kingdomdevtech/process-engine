import { useCallback, useEffect, useRef, useState } from 'react'
import { useLocation, useNavigate } from 'react-router-dom'
import { BookOpen, Compass, X } from 'lucide-react'

import {
  TOUR_DOC_URL,
  routeFor,
  startTour,
  tourSeen,
  useTour,
  wouldLoseWork,
} from '../tour.js'
import { useToast } from './Toast.jsx'
import { useDialogs } from './ui/Dialogs.jsx'

const CARD_WIDTH = 344
const CARD_ROOM = 280 // room a card needs on the side it opens towards
const GAP = 14
const PAD = 6 // breathing room around the highlighted element

const FOCUSABLE = 'a[href], button:not([disabled])'

/** Same rectangle to the pixel? Then nothing needs to re-render. */
function same(a, b) {
  if (!a || !b) return a === b
  return a.top === b.top && a.left === b.left && a.width === b.width && a.height === b.height
}

/**
 * Where the card goes, given the highlighted rectangle and a preferred side.
 *
 * Each placement is expressed so the card's own height never has to be known —
 * "above" is the anchor's top edge plus a -100% translate — which keeps this
 * a pure function of the rectangle and the viewport.
 */
function place(rect, preferred = 'bottom') {
  const vw = window.innerWidth
  const vh = window.innerHeight
  const clampY = (value) => Math.min(Math.max(value, 8), Math.max(8, vh - CARD_ROOM))
  const clampX = (value) => Math.min(Math.max(value, 8), Math.max(8, vw - CARD_WIDTH - 8))

  let side = preferred
  if (side === 'bottom' && vh - rect.top - rect.height < CARD_ROOM && rect.top > CARD_ROOM) side = 'top'
  else if (side === 'top' && rect.top < CARD_ROOM) side = 'bottom'
  else if (side === 'right' && vw - rect.left - rect.width < CARD_WIDTH + 32) side = 'left'
  else if (side === 'left' && rect.left < CARD_WIDTH + 32) side = 'right'

  switch (side) {
    case 'top':
      return { top: rect.top - GAP - PAD, left: clampX(rect.left), transform: 'translateY(-100%)' }
    case 'right':
      return { top: clampY(rect.top), left: rect.left + rect.width + GAP + PAD, transform: 'none' }
    case 'left':
      return {
        top: clampY(rect.top),
        left: Math.max(CARD_WIDTH + 8, rect.left - GAP - PAD),
        transform: 'translateX(-100%)',
      }
    default:
      return { top: rect.top + rect.height + GAP + PAD, left: clampX(rect.left), transform: 'none' }
  }
}

/**
 * The guided tour overlay.
 *
 * Rendered by the shell, so it survives the navigation it does itself. It
 * dims the app, cuts a hole around the element the current step is about, and
 * blocks interaction underneath — a tour that lets you wander mid-step is a
 * tour talking about something that is no longer on screen.
 */
export default function Tour() {
  const { open, index, step, count, goTo, stop } = useTour()
  const [rect, setRect] = useState(null)
  const navigate = useNavigate()
  const { pathname } = useLocation()
  const dialogs = useDialogs()
  const toast = useToast()
  const card = useRef(null)
  const measured = useRef(null)

  /* Offered once, on the screen where a new signee lands — and never while it
     is already running, or starting it elsewhere would rewind itself the
     moment its first step navigated here. */
  useEffect(() => {
    if (open || tourSeen() || pathname !== '/app') return undefined
    const timer = setTimeout(() => startTour(), 400)
    return () => clearTimeout(timer)
  }, [open, pathname])

  /* A step that belongs on another screen takes us there — unless that would
     throw away an unsaved canvas, in which case the work wins and the tour
     bows out. */
  useEffect(() => {
    if (!open) return undefined
    const target = routeFor(step, pathname)
    if (!target) return undefined

    let cancelled = false
    const go = async () => {
      if (wouldLoseWork()) {
        const ok = await dialogs.confirm({
          title: 'Leave this process to continue the tour?',
          body: 'It has unsaved changes. Save it first if you want to keep them — the tour will still be in the command palette.',
          confirmLabel: 'Discard and continue',
          tone: 'danger',
        })
        if (cancelled) return
        if (!ok) {
          stop()
          toast.info('Tour closed — your unsaved changes are untouched.')
          return
        }
      }
      if (!cancelled) navigate(target)
    }
    go()
    return () => {
      cancelled = true
    }
  }, [open, step, pathname, navigate, dialogs, toast, stop])

  /* Follow the anchor: it may not exist yet (the page is still loading), may
     move (a panel opens), or may never appear (a viewport too narrow for the
     inspector) — in which case the card simply centres itself. */
  useEffect(() => {
    if (!open) {
      measured.current = null
      setRect(null)
      return undefined
    }

    let scrolled = false
    const measure = () => {
      const element = step?.anchor ? document.querySelector(`[data-tour="${step.anchor}"]`) : null
      if (!element) {
        if (measured.current !== null) {
          measured.current = null
          setRect(null)
        }
        return
      }
      if (!scrolled) {
        scrolled = true
        element.scrollIntoView({ block: 'nearest', inline: 'nearest', behavior: 'smooth' })
      }
      const box = element.getBoundingClientRect()
      const next =
        box.width || box.height
          ? { top: box.top, left: box.left, width: box.width, height: box.height }
          : null
      if (!same(measured.current, next)) {
        measured.current = next
        setRect(next)
      }
    }

    measure()
    const timer = setInterval(measure, 150)
    window.addEventListener('resize', measure)
    window.addEventListener('scroll', measure, true)
    return () => {
      clearInterval(timer)
      window.removeEventListener('resize', measure)
      window.removeEventListener('scroll', measure, true)
    }
  }, [open, step])

  const next = useCallback(() => goTo(index + 1), [goTo, index])
  const back = useCallback(() => goTo(index - 1), [goTo, index])

  /* Keyboard drives the whole thing, and Tab stays inside the card so the
     blocked app underneath cannot be reached by keyboard either. */
  useEffect(() => {
    if (!open) return undefined
    const onKeyDown = (event) => {
      /* A modal or the command palette can open on top of the tour; while one
         has the focus it owns the keyboard, Escape included. */
      const inOther = event.target?.closest?.('[role="dialog"]')
      if (inOther && inOther !== card.current) return

      /* Enter belongs to whichever button has the focus — Next has it by
         default, and handling the key here as well would advance twice. */
      if (event.key === 'Enter' && event.target?.closest?.('button, a')) return

      if (event.key === 'Escape') {
        event.preventDefault()
        event.stopPropagation()
        stop()
      } else if (event.key === 'ArrowRight' || event.key === 'Enter') {
        event.preventDefault()
        next()
      } else if (event.key === 'ArrowLeft') {
        event.preventDefault()
        if (index > 0) back()
      } else if (event.key === 'Tab' && card.current) {
        const items = [...card.current.querySelectorAll(FOCUSABLE)]
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
    }
    document.addEventListener('keydown', onKeyDown, true)
    return () => document.removeEventListener('keydown', onKeyDown, true)
  }, [open, next, back, stop, index])

  useEffect(() => {
    if (!open) return
    card.current?.querySelector('[data-autofocus]')?.focus()
  }, [open, index])

  if (!open || !step) return null

  const last = index === count - 1
  const position = rect ? place(rect, step.placement) : null

  return (
    <div className="fixed inset-0 z-45" aria-live="polite">
      {/* Swallows every click while the tour is up. The dimming itself is the
          spotlight's shadow, so this layer stays invisible. */}
      <div className="absolute inset-0" onMouseDown={(event) => event.preventDefault()} />

      {rect ? (
        <div
          aria-hidden="true"
          className="pointer-events-none absolute rounded-lg transition-all duration-200 ease-out"
          style={{
            top: rect.top - PAD,
            left: rect.left - PAD,
            width: rect.width + PAD * 2,
            height: rect.height + PAD * 2,
            boxShadow: '0 0 0 9999px var(--overlay)',
            outline: '2px solid var(--ring)',
            outlineOffset: '1px',
          }}
        />
      ) : (
        <div aria-hidden="true" className="absolute inset-0 bg-overlay" />
      )}

      <div
        ref={card}
        role="dialog"
        aria-modal="true"
        aria-label={`Guided tour, step ${index + 1} of ${count}: ${step.title}`}
        className={`animate-zoom absolute flex flex-col rounded-xl border border-line bg-raised p-4 shadow-xl ${
          position ? '' : 'left-1/2 top-1/2 -translate-x-1/2 -translate-y-1/2'
        }`}
        style={{ width: CARD_WIDTH, ...(position ?? {}) }}
      >
        <div className="mb-2 flex items-center gap-2">
          <span
            className="grid size-7 shrink-0 place-items-center rounded-lg bg-brand-soft text-brand-text"
            aria-hidden="true"
          >
            <Compass size={15} />
          </span>
          <span className="text-[10px] font-bold uppercase tracking-wider text-fg-subtle">
            {step.chapter}
          </span>
          <span className="tabular ml-auto text-[11px] text-fg-subtle">
            {index + 1} / {count}
          </span>
          <button
            className="btn btn-ghost btn-icon btn-sm -mr-1.5"
            onClick={stop}
            aria-label="Close the tour"
            title="Close the tour (Esc)"
          >
            <X size={15} />
          </button>
        </div>

        <h2 className="text-sm font-semibold">{step.title}</h2>

        {step.body && <p className="mt-1.5 text-[13px] leading-relaxed text-fg-muted">{step.body}</p>}

        {step.bullets && (
          <ul className="mt-2 space-y-1">
            {step.bullets.map((bullet) => (
              <li key={bullet} className="flex gap-1.5 text-[13px] leading-relaxed text-fg-muted">
                <span className="mt-1.5 size-1 shrink-0 rounded-full bg-fg-subtle" aria-hidden="true" />
                {bullet}
              </li>
            ))}
          </ul>
        )}

        {step.code && (
          <pre className="mt-2.5 overflow-x-auto rounded-md bg-surface-2 px-2.5 py-2 font-mono text-[11px] leading-relaxed text-fg-muted">
            {step.code}
          </pre>
        )}

        {step.keys && (
          <div className="mt-2.5 flex flex-wrap items-center gap-1.5">
            {step.keys.map((combo) => (
              <span key={combo.join('+')} className="flex items-center gap-1">
                {combo.map((key) => (
                  <kbd key={key} className="kbd">
                    {key}
                  </kbd>
                ))}
              </span>
            ))}
          </div>
        )}

        {step.doc && (
          <a
            className="mt-3 flex items-center gap-2 rounded-md border border-line bg-surface-2 px-2.5 py-2 text-[12px] font-medium text-fg hover:border-line-strong"
            href={TOUR_DOC_URL}
            target="_blank"
            rel="noreferrer"
          >
            <BookOpen size={14} className="shrink-0 text-brand-text" aria-hidden="true" />
            Read the full walkthrough
          </a>
        )}

        {step.hint && <p className="mt-2.5 text-[11px] text-fg-subtle">{step.hint}</p>}

        <div className="mt-3.5 h-0.5 rounded-full bg-surface-3" aria-hidden="true">
          <div
            className="h-full rounded-full bg-brand transition-[width] duration-200"
            style={{ width: `${((index + 1) / count) * 100}%` }}
          />
        </div>

        <div className="mt-3 flex items-center gap-2">
          <button className="btn btn-ghost btn-sm" onClick={stop}>
            {last ? 'Close' : 'Skip tour'}
          </button>
          <div className="ml-auto flex items-center gap-1.5">
            <button className="btn btn-sm" onClick={back} disabled={index === 0}>
              Back
            </button>
            <button className="btn btn-primary btn-sm" onClick={next} data-autofocus>
              {last ? 'Done' : 'Next'}
            </button>
          </div>
        </div>
      </div>
    </div>
  )
}
