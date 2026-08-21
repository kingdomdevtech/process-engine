import { useEffect, useState } from 'react'
import { KeyRound, Lock, Plus, Trash2 } from 'lucide-react'

import { api } from '../api.js'
import { refreshSecretNames } from '../secrets.js'
import AppShell from '../components/AppShell.jsx'
import { useToast } from '../components/Toast.jsx'
import { useDialogs } from '../components/ui/Dialogs.jsx'

/**
 * Stored credentials, as a destination of its own rather than a Settings tab.
 *
 * Secrets are building material — you reach for one while wiring up a step, the
 * same way you reach for a plugin — not deployment configuration like the mail
 * relay or the file sandbox. So this stays with Processes and Runs and is open
 * to editors, while Settings went admin-only.
 */
export default function SecretsPage() {
  const [names, setNames] = useState([])
  const [name, setName] = useState('')
  const [value, setValue] = useState('')
  const [busy, setBusy] = useState(false)
  const toast = useToast()
  const dialogs = useDialogs()

  // also re-reads the copy the step forms' secret pickers share
  const refresh = () =>
    api
      .get('/api/secrets')
      .then((loaded) => {
        setNames(loaded)
        refreshSecretNames()
      })
      .catch(() => {})
  useEffect(() => {
    refresh()
  }, [])

  const save = async (event) => {
    event.preventDefault()
    if (!name.trim() || !value) return
    setBusy(true)
    try {
      await api.put(`/api/secrets/${encodeURIComponent(name.trim())}`, { value })
      toast.ok(`Stored “${name.trim()}”`)
      setName('')
      setValue('')
      refresh()
    } catch (error) {
      toast.error(String(error.message))
    } finally {
      setBusy(false)
    }
  }

  const remove = async (secret) => {
    const ok = await dialogs.confirm({
      title: `Delete secret “${secret}”?`,
      body: 'Any step referencing it will fail on its next run. The value cannot be recovered.',
      confirmLabel: 'Delete secret',
      tone: 'danger',
    })
    if (!ok) return
    api
      .del(`/api/secrets/${encodeURIComponent(secret)}`)
      .then(() => {
        toast.ok(`Deleted ${secret}`)
        refresh()
      })
      .catch((error) => toast.error(String(error.message)))
  }

  return (
    <AppShell title="Secrets">
      <div className="mb-5">
        <h2 className="text-xl font-bold">Secrets</h2>
        <p className="text-[13px] text-fg-muted">Credentials your steps use, encrypted at rest.</p>
      </div>

      <section className="card p-5" data-tour="secrets">
        <div className="flex items-start gap-3">
          <span
            className="grid size-9 shrink-0 place-items-center rounded-lg bg-warn-bg text-warn-fg"
            aria-hidden="true"
          >
            <Lock size={17} />
          </span>
          <div>
            <h3 className="text-sm font-semibold">Stored secrets</h3>
            <p className="mt-1 max-w-prose text-[13px] text-fg-muted">
              Encrypted at rest and never returned by the API — only their names are listed. Reference one in any step
              as <code className="code">{'{{ secrets.name }}'}</code>; it is resolved at execution time.
            </p>
          </div>
        </div>

        <div className="mt-4 flex flex-wrap gap-2">
          {names.map((secret) => (
            <span key={secret} className="badge gap-1.5 py-1 pl-2.5 pr-1 font-mono">
              <KeyRound size={11} aria-hidden="true" />
              {secret}
              <button
                className="btn btn-ghost btn-icon size-5 rounded-full text-fg-subtle hover:text-bad-fg"
                onClick={() => remove(secret)}
                aria-label={`Delete secret ${secret}`}
              >
                <Trash2 size={11} />
              </button>
            </span>
          ))}
          {names.length === 0 && <span className="muted">No secrets stored yet.</span>}
        </div>

        <form className="mt-4 flex flex-wrap items-end gap-2 border-t border-line pt-4" onSubmit={save}>
          <div className="min-w-44 flex-1">
            <label className="label mb-1.5" htmlFor="pe-secret-name">
              Name
            </label>
            <input
              id="pe-secret-name"
              className="input font-mono"
              placeholder="smtp_password"
              value={name}
              onChange={(event) => setName(event.target.value)}
            />
          </div>
          <div className="min-w-44 flex-1">
            <label className="label mb-1.5" htmlFor="pe-secret-value">
              Value
            </label>
            <input
              id="pe-secret-value"
              className="input"
              type="password"
              autoComplete="new-password"
              placeholder="••••••••"
              value={value}
              onChange={(event) => setValue(event.target.value)}
            />
          </div>
          <button className="btn btn-primary" type="submit" disabled={busy || !name.trim() || !value}>
            <Plus size={15} />
            Store
          </button>
        </form>
      </section>
    </AppShell>
  )
}
