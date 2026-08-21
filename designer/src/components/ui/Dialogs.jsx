import { createContext, useCallback, useContext, useMemo, useRef, useState } from 'react'
import { AlertTriangle, Trash2 } from 'lucide-react'
import Modal from './Modal.jsx'

/**
 * Promise-based replacements for window.confirm / window.prompt.
 *
 * The native ones block the whole browser, cannot be styled or themed, give no
 * context about consequences, and read as a browser warning rather than as part
 * of the product. These match the app, name the object being acted on, and let
 * a destructive action be labelled as such.
 *
 *   const ok = await dialogs.confirm({ title: 'Delete X?', tone: 'danger' })
 *   const name = await dialogs.prompt({ title: 'Move to folder' })
 */
const DialogContext = createContext(null)

export function useDialogs() {
  const value = useContext(DialogContext)
  if (!value) throw new Error('useDialogs must be used inside <DialogProvider>')
  return value
}

export function DialogProvider({ children }) {
  const [request, setRequest] = useState(null)
  const [draft, setDraft] = useState('')
  const resolver = useRef(null)
  const inputRef = useRef(null)

  const settle = useCallback((value) => {
    resolver.current?.(value)
    resolver.current = null
    setRequest(null)
  }, [])

  const open = useCallback((next) => {
    setDraft(next.defaultValue ?? '')
    setRequest(next)
    return new Promise((resolve) => {
      resolver.current = resolve
    })
  }, [])

  const api = useMemo(
    () => ({
      confirm: (options) => open({ kind: 'confirm', ...options }),
      prompt: (options) => open({ kind: 'prompt', ...options }),
    }),
    [open],
  )

  const isDanger = request?.tone === 'danger'
  const isPrompt = request?.kind === 'prompt'

  return (
    <DialogContext.Provider value={api}>
      {children}
      <Modal
        open={Boolean(request)}
        onClose={() => settle(isPrompt ? null : false)}
        size="sm"
        title={request?.title}
        description={request?.description}
        initialFocus={isPrompt ? inputRef : undefined}
        icon={
          <span
            className={`grid size-9 shrink-0 place-items-center rounded-lg ${
              isDanger ? 'bg-bad-bg text-bad-fg' : 'bg-brand-soft text-brand-text'
            }`}
            aria-hidden="true"
          >
            {isDanger ? <Trash2 size={18} /> : <AlertTriangle size={18} />}
          </span>
        }
        footer={
          <>
            <button className="btn" onClick={() => settle(isPrompt ? null : false)}>
              {request?.cancelLabel ?? 'Cancel'}
            </button>
            <button
              className={`btn ${isDanger ? 'btn-danger-solid' : 'btn-primary'}`}
              onClick={() => settle(isPrompt ? draft : true)}
            >
              {request?.confirmLabel ?? (isDanger ? 'Delete' : 'Confirm')}
            </button>
          </>
        }
      >
        {request?.body && <p className="text-[13px] text-fg-muted">{request.body}</p>}
        {isPrompt && (
          <form
            className="mt-3"
            onSubmit={(event) => {
              event.preventDefault()
              settle(draft)
            }}
          >
            {request.label && (
              <label className="label mb-1.5" htmlFor="pe-prompt-input">
                {request.label}
              </label>
            )}
            <input
              id="pe-prompt-input"
              ref={inputRef}
              className="input"
              value={draft}
              placeholder={request.placeholder}
              list={request.options?.length ? 'pe-prompt-options' : undefined}
              onChange={(event) => setDraft(event.target.value)}
            />
            {request.options?.length > 0 && (
              <datalist id="pe-prompt-options">
                {request.options.map((option) => (
                  <option key={option} value={option} />
                ))}
              </datalist>
            )}
            {request.hint && <p className="hint mt-1.5">{request.hint}</p>}
          </form>
        )}
      </Modal>
    </DialogContext.Provider>
  )
}
