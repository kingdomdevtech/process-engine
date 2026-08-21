import { useEffect, useMemo, useState } from 'react'
import { Check, Search, Share2, UserRound, X } from 'lucide-react'

import { api, getUser } from '../api.js'
import { useToast } from './Toast.jsx'
import Modal from './ui/Modal.jsx'

/**
 * Who else can open this process.
 *
 * Access is flat by design: anyone it is shared with holds it exactly as its
 * creator does, including the right to share it on. That is what lets a team
 * hand work over without an admin in the loop — and why this dialog is
 * reachable by anyone who can see the process, not just its owner.
 *
 * The creator is listed but not removable: they hold it by ownership, so
 * dropping them from the list would not revoke anything, it would only lie.
 */
export default function ShareDialog({ process, open, onClose, onSaved }) {
  const [directory, setDirectory] = useState([])
  const [chosen, setChosen] = useState([])
  const [query, setQuery] = useState('')
  const [busy, setBusy] = useState(false)
  const toast = useToast()
  const me = getUser()?.username

  useEffect(() => {
    if (!open) return
    setQuery('')
    setChosen(process?.shared_with ?? [])
    // emails_only=false: sharing works for any account, unlike notifications
    api
      .get('/api/users/directory?emails_only=false')
      .then(setDirectory)
      .catch(() => setDirectory([]))
  }, [open, process])

  const owner = process?.created_by || ''
  const candidates = useMemo(() => {
    const term = query.trim().toLowerCase()
    return directory
      .filter((name) => name !== owner)
      .filter((name) => !term || name.toLowerCase().includes(term))
  }, [directory, owner, query])

  const toggle = (name) =>
    setChosen((current) =>
      current.includes(name) ? current.filter((entry) => entry !== name) : [...current, name],
    )

  const save = async () => {
    setBusy(true)
    try {
      const saved = await api.post(`/api/processes/${process.id}/share`, { usernames: chosen })
      toast.ok(
        saved.shared_with.length
          ? `Shared with ${saved.shared_with.length} ${saved.shared_with.length === 1 ? 'person' : 'people'}`
          : 'Sharing turned off',
      )
      onSaved?.(saved)
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
      title={`Share “${process?.name ?? ''}”`}
      description="Everyone here can open, edit, run and share it on."
      icon={
        <span className="grid size-9 shrink-0 place-items-center rounded-lg bg-brand-soft text-brand-text" aria-hidden="true">
          <Share2 size={17} />
        </span>
      }
      footer={
        <>
          <button className="btn" onClick={onClose} disabled={busy}>
            Cancel
          </button>
          <button className="btn btn-primary" onClick={save} disabled={busy}>
            Save sharing
          </button>
        </>
      }
    >
      <div className="mb-3 flex flex-wrap items-center gap-1.5">
        <span className="badge gap-1.5" title="The creator always has access">
          <UserRound size={11} aria-hidden="true" />
          {owner || 'unknown'}
          <span className="text-fg-subtle">owner</span>
        </span>
        {chosen.map((name) => (
          <span key={name} className="badge badge-brand gap-1.5 py-1 pl-2.5 pr-1">
            {name}
            <button
              className="btn btn-ghost btn-icon size-5 rounded-full"
              onClick={() => toggle(name)}
              aria-label={`Stop sharing with ${name}`}
            >
              <X size={11} />
            </button>
          </span>
        ))}
        {chosen.length === 0 && <span className="muted">Not shared with anyone yet.</span>}
      </div>

      <div className="relative">
        <Search
          size={14}
          className="pointer-events-none absolute left-2.5 top-1/2 -translate-y-1/2 text-fg-subtle"
          aria-hidden="true"
        />
        <input
          className="input pl-8"
          placeholder="Search people…"
          value={query}
          onChange={(event) => setQuery(event.target.value)}
          data-autofocus
        />
      </div>

      <ul className="mt-2 max-h-64 space-y-0.5 overflow-y-auto">
        {candidates.map((name) => {
          const on = chosen.includes(name)
          return (
            <li key={name}>
              <button
                className={`nav-item w-full ${on ? 'is-active' : ''}`}
                onClick={() => toggle(name)}
                aria-pressed={on}
              >
                <span className="grid size-6 shrink-0 place-items-center rounded-full bg-surface-2 text-[10px] font-bold uppercase">
                  {name.slice(0, 1)}
                </span>
                <span className="min-w-0 flex-1 truncate text-left">
                  {name}
                  {name === me && <span className="ml-1.5 text-[11px] text-fg-subtle">you</span>}
                </span>
                {on && <Check size={14} className="shrink-0" aria-hidden="true" />}
              </button>
            </li>
          )
        })}
        {candidates.length === 0 && (
          <li className="muted px-2 py-3">
            {directory.length <= 1 ? 'No other accounts exist yet.' : 'Nobody matches that.'}
          </li>
        )}
      </ul>
    </Modal>
  )
}
