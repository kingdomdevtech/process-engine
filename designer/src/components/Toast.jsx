import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState } from 'react'
import { AlertCircle, CheckCircle2, Info, X } from 'lucide-react'

const ToastContext = createContext(() => {})

export function useToast() {
  return useContext(ToastContext)
}

const TONES = {
  ok: { icon: CheckCircle2, accent: 'text-ok-fg', bar: 'bg-ok-fg', ttl: 4000, live: 'polite' },
  bad: { icon: AlertCircle, accent: 'text-bad-fg', bar: 'bg-bad-fg', ttl: 0, live: 'assertive' },
  info: { icon: Info, accent: 'text-info-fg', bar: 'bg-info-fg', ttl: 5000, live: 'polite' },
}

const MAX_VISIBLE = 4

let nextId = 0

function Toast({ toast, onDismiss }) {
  const tone = TONES[toast.tone] ?? TONES.info
  const Icon = tone.icon
  const [paused, setPaused] = useState(false)
  const remaining = useRef(tone.ttl)
  const startedAt = useRef(Date.now())

  /* Errors persist until dismissed; successes auto-expire, but the timer holds
     while the pointer is over the toast so a message cannot vanish mid-read. */
  useEffect(() => {
    if (!tone.ttl || paused) return undefined
    startedAt.current = Date.now()
    const timer = setTimeout(() => onDismiss(toast.id), remaining.current)
    return () => {
      clearTimeout(timer)
      remaining.current -= Date.now() - startedAt.current
    }
  }, [paused, tone.ttl, toast.id, onDismiss])

  return (
    <div
      role={toast.tone === 'bad' ? 'alert' : 'status'}
      className="animate-rise pointer-events-auto flex w-full items-start gap-2.5 overflow-hidden rounded-lg border border-line bg-raised p-3 shadow-lg"
      onMouseEnter={() => setPaused(true)}
      onMouseLeave={() => setPaused(false)}
    >
      <Icon size={16} className={`mt-px shrink-0 ${tone.accent}`} aria-hidden="true" />
      <div className="min-w-0 flex-1">
        <p className="text-[13px] leading-snug break-words">{toast.message}</p>
        {toast.action && (
          <button
            className="link mt-1 text-xs font-medium"
            onClick={() => {
              toast.action.onClick()
              onDismiss(toast.id)
            }}
          >
            {toast.action.label}
          </button>
        )}
      </div>
      <button
        className="btn btn-ghost btn-icon btn-sm -mr-1 -mt-1 shrink-0"
        onClick={() => onDismiss(toast.id)}
        aria-label="Dismiss notification"
      >
        <X size={14} />
      </button>
    </div>
  )
}

export function ToastProvider({ children }) {
  const [toasts, setToasts] = useState([])

  const dismiss = useCallback((id) => setToasts((list) => list.filter((entry) => entry.id !== id)), [])

  const push = useCallback((message, tone = 'info', options = {}) => {
    const id = ++nextId
    setToasts((list) => {
      // Repeating the same message stacks up noise; refresh the existing one.
      const duplicate = list.find((entry) => entry.message === message && entry.tone === tone)
      if (duplicate) return list
      return [...list, { id, message, tone, ...options }].slice(-MAX_VISIBLE)
    })
    return id
  }, [])

  const api = useMemo(
    () =>
      Object.assign(push, {
        ok: (message, options) => push(message, 'ok', options),
        error: (message, options) => push(message, 'bad', options),
        info: (message, options) => push(message, 'info', options),
        dismiss,
      }),
    [push, dismiss],
  )

  return (
    <ToastContext.Provider value={api}>
      {children}
      {/* Bottom-right, above every surface, and never intercepting clicks. */}
      <div
        className="pointer-events-none fixed bottom-4 right-4 z-[60] flex w-[min(24rem,calc(100vw-2rem))] flex-col gap-2"
        aria-live="polite"
        aria-atomic="false"
      >
        {toasts.map((toast) => (
          <Toast key={toast.id} toast={toast} onDismiss={dismiss} />
        ))}
      </div>
    </ToastContext.Provider>
  )
}
