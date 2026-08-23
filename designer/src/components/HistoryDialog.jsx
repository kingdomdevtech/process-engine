import { useCallback, useEffect, useState } from 'react'
import { History, RotateCcw, UserRound } from 'lucide-react'

import { api } from '../api.js'
import { absoluteTime, relativeTime } from '../format.js'
import { useToast } from './Toast.jsx'
import Modal from './ui/Modal.jsx'
import { useDialogs } from './ui/Dialogs.jsx'

/**
 * What has happened to this process, and the way back to any of it.
 *
 * Every save, publish, move and share is an entry; the ones that changed the
 * definition carry the draft as it stood afterwards, which is what *Restore*
 * writes back. Restoring is an ordinary edit rather than a rewind — it becomes
 * an entry of its own, so the state it replaced is still one click away, and it
 * leaves published versions alone: what a schedule runs does not change until
 * somebody publishes again.
 */
const ACTION_LABEL = {
  created: 'Created',
  updated: 'Edited',
  published: 'Published',
  shared: 'Sharing changed',
  moved: 'Moved',
  restored: 'Restored',
}

const ACTION_TONE = {
  published: 'badge-succeeded',
  restored: 'badge-running',
}

export default function HistoryDialog({ processId, processName, open, onClose, onRestored }) {
  const [entries, setEntries] = useState(null)
  const [busy, setBusy] = useState(false)
  const toast = useToast()
  const dialogs = useDialogs()

  const load = useCallback(async () => {
    if (!processId) return
    try {
      setEntries(await api.get(`/api/processes/${processId}/history`))
    } catch (error) {
      toast.error(String(error.message))
      setEntries([])
    }
  }, [processId, toast])

  useEffect(() => {
    if (open) load()
  }, [open, load])

  const restore = async (entry) => {
    const ok = await dialogs.confirm({
      title: `Restore the state from ${absoluteTime(entry.at)}?`,
      body:
        'The canvas goes back to how it was saved then, as a draft. Published versions are untouched, ' +
        'and this restore is recorded too — so you can come straight back here.',
      confirmLabel: 'Restore this state',
    })
    if (!ok) return
    setBusy(true)
    try {
      const restored = await api.post(`/api/processes/${processId}/history/${entry.id}/restore`)
      toast.ok('Restored — publish it when you are happy with it')
      onRestored?.(restored)
      onClose()
    } catch (error) {
      toast.error(String(error.message))
    } finally {
      setBusy(false)
    }
  }

  return (
    <Modal
      open={open}
      onClose={onClose}
      size="md"
      title={`History of “${processName ?? ''}”`}
      description="Every change to this process, newest first."
      icon={
        <span
          className="grid size-9 shrink-0 place-items-center rounded-lg bg-brand-soft text-brand-text"
          aria-hidden="true"
        >
          <History size={17} />
        </span>
      }
      footer={
        <button className="btn" onClick={onClose} disabled={busy}>
          Close
        </button>
      }
    >
      {entries === null ? (
        <div className="space-y-2">
          {[0, 1, 2].map((index) => (
            <div className="skeleton h-12" key={index} />
          ))}
        </div>
      ) : entries.length === 0 ? (
        <p className="muted py-3">
          Nothing yet. This process has not been saved since history was kept — the next save starts it.
        </p>
      ) : (
        <ul className="max-h-80 space-y-1 overflow-y-auto" aria-label="Process history">
          {entries.map((entry) => (
            <li
              key={entry.id}
              className="flex items-start gap-2.5 rounded-lg border border-line px-2.5 py-2"
            >
              <div className="min-w-0 flex-1">
                <div className="flex flex-wrap items-center gap-1.5">
                  <span className={`badge badge-dot ${ACTION_TONE[entry.action] ?? ''}`}>
                    {ACTION_LABEL[entry.action] ?? entry.action}
                  </span>
                  {entry.version > 0 && <span className="badge">v{entry.version}</span>}
                  <span className="text-[11px] text-fg-subtle" title={absoluteTime(entry.at)}>
                    {relativeTime(entry.at)}
                  </span>
                </div>
                {entry.summary && <p className="mt-0.5 truncate text-[13px]" title={entry.summary}>{entry.summary}</p>}
                {entry.actor && (
                  <p className="mt-0.5 flex items-center gap-1 text-[11px] text-fg-subtle">
                    <UserRound size={10} aria-hidden="true" />
                    {entry.actor}
                  </p>
                )}
              </div>
              {/* A sharing change carries no snapshot, so there is nothing to
                  put back — the row says so rather than offering a dead button. */}
              {entry.restorable ? (
                <button
                  className="btn btn-sm shrink-0"
                  onClick={() => restore(entry)}
                  disabled={busy}
                  title="Put the canvas back to this state, as a draft"
                >
                  <RotateCcw size={13} />
                  Restore
                </button>
              ) : (
                <span className="shrink-0 self-center text-[11px] text-fg-subtle">no snapshot</span>
              )}
            </li>
          ))}
        </ul>
      )}
    </Modal>
  )
}
