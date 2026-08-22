import { useEffect, useMemo, useState } from 'react'
import {
  Bell,
  FolderTree,
  Puzzle,
  Search,
  Send,
  Server,
  Shield,
  Trash2,
  UserPlus,
  Users as UsersIcon,
} from 'lucide-react'

import { api, getUser } from '../api.js'
import { PluginIcon } from '../pluginMeta.jsx'
import AppShell from '../components/AppShell.jsx'
import EmptyState from '../components/EmptyState.jsx'
import { useToast } from '../components/Toast.jsx'
import Field from '../components/ui/Field.jsx'
import { useDialogs } from '../components/ui/Dialogs.jsx'

/* ---- working directory --------------------------------------------------- */

function FilesSection() {
  const [info, setInfo] = useState(null)

  useEffect(() => {
    api.get('/api/workspace').then(setInfo).catch(() => setInfo({}))
  }, [])

  if (info === null) return <div className="skeleton h-40" />

  return (
    <section className="card p-5">
      <div className="flex items-start gap-3">
        <span className="grid size-9 shrink-0 place-items-center rounded-lg bg-alt-bg text-alt-fg" aria-hidden="true">
          <FolderTree size={17} />
        </span>
        <div>
          <h3 className="text-sm font-semibold">Working directory</h3>
          <p className="mt-1 max-w-prose text-[13px] text-fg-muted">
            The only folder file steps — <code className="code">s3_download</code>,{' '}
            <code className="code">file_purge</code> — may read or write. Their paths are relative to it, and
            anything resolving outside it (including through a symlink) fails the step, so no process can reach
            system folders or the engine&rsquo;s own database.
          </p>
        </div>
      </div>

      <dl className="mt-4 grid gap-3 border-t border-line pt-4 sm:grid-cols-[10rem_1fr]">
        <dt className="label">Path</dt>
        <dd className="break-all font-mono text-[13px]">{info.path ?? '—'}</dd>
        <dt className="label">Set by</dt>
        <dd className="text-[13px] text-fg-muted">
          <code className="code">{info.env_var ?? 'PROCESS_ENGINE_WORK_DIR'}</code>{' '}
          {info.configured ? '(set on the server)' : '(not set — using the default folder)'}
        </dd>
        <dt className="label">Status</dt>
        <dd className="flex flex-wrap gap-1.5">
          <span className={`badge ${info.exists ? 'bg-ok-bg text-ok-fg' : 'bg-warn-bg text-warn-fg'}`}>
            {info.exists ? 'Exists' : 'Created on first use'}
          </span>
          {info.exists && (
            <span className={`badge ${info.writable ? 'bg-ok-bg text-ok-fg' : 'bg-bad-bg text-bad-fg'}`}>
              {info.writable ? 'Writable' : 'Not writable by the engine account'}
            </span>
          )}
        </dd>
      </dl>

      <p className="mt-4 border-t border-line pt-4 text-[13px] text-fg-muted">
        Changing it is a server-side decision on purpose: set{' '}
        <code className="code">{info.env_var ?? 'PROCESS_ENGINE_WORK_DIR'}</code> before starting the API, so
        nobody signed in here can widen what their steps are allowed to touch.
      </p>
    </section>
  )
}

/* ---- execution ----------------------------------------------------------- */

/** Where the engine's work happens — always elsewhere — and who is listening. */
function ExecutionSection() {
  const [status, setStatus] = useState(null)
  const [workers, setWorkers] = useState([])

  useEffect(() => {
    const load = () => {
      api.get('/api/queue').then(setStatus).catch(() => setStatus({}))
      api.get('/api/workers').then(setWorkers).catch(() => setWorkers([]))
    }
    load()
    const timer = setInterval(load, 5000) // a worker starting or dying should show
    return () => clearInterval(timer)
  }, [])

  if (status === null) return <div className="skeleton h-40" />

  return (
    <section className="card p-5">
      <div className="flex items-start gap-3">
        <span className="grid size-9 shrink-0 place-items-center rounded-lg bg-info-bg text-info-fg" aria-hidden="true">
          <Server size={17} />
        </span>
        <div>
          <h3 className="text-sm font-semibold">Execution</h3>
          <p className="mt-1 max-w-prose text-[13px] text-fg-muted">
            Nothing executes on this host. Runs and step previews are queued through the database and claimed by
            engines elsewhere — which is how steps that need Windows (Excel) run while this server is on Linux.
          </p>
        </div>
      </div>

      <dl className="mt-4 grid gap-3 border-t border-line pt-4 sm:grid-cols-[10rem_1fr]">
        <dt className="label">Engines</dt>
        <dd className="flex flex-wrap items-center gap-1.5">
          <span className={`badge ${workers.length ? 'bg-ok-bg text-ok-fg' : 'bg-bad-bg text-bad-fg'}`}>
            {workers.length ? `${workers.length} online` : 'None online'}
          </span>
          {!workers.length && (
            <span className="text-[13px] text-fg-muted">
              Nothing can run. Start an engine with <code className="code">python -m process_engine</code> on the host
              that has the plugins&rsquo; dependencies, pointed at this database.
            </span>
          )}
        </dd>
        <dt className="label">Queued</dt>
        <dd className="text-[13px] tabular">{status.queued ?? 0}</dd>
      </dl>

      {workers.length > 0 && (
        <div className="mt-4 overflow-x-auto border-t border-line pt-4">
          <table className="table">
            <thead>
              <tr>
                <th>Host</th>
                <th className="w-40">Worker</th>
                <th className="w-40">Last seen</th>
              </tr>
            </thead>
            <tbody>
              {workers.map((worker) => (
                <tr key={worker.worker_id}>
                  <td className="font-medium">{worker.hostname || '—'}</td>
                  <td className="font-mono text-[12px] text-fg-muted">{worker.worker_id}</td>
                  <td className="text-[13px] text-fg-muted">{new Date(worker.last_seen).toLocaleTimeString()}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      <p className="mt-4 border-t border-line pt-4 text-[13px] text-fg-muted">
        There is nothing to switch on here. An engine is a separate install pointed at the same database, so which
        host runs the work is a deployment decision — not something anyone signed in here can move.
      </p>
    </section>
  )
}

/* ---- users --------------------------------------------------------------- */

function UsersSection() {
  const [users, setUsers] = useState(null)
  const [form, setForm] = useState({ username: '', password: '', role: 'editor' })
  const toast = useToast()
  const dialogs = useDialogs()
  const me = getUser()

  const refresh = () => api.get('/api/users').then(setUsers).catch(() => setUsers([]))
  useEffect(() => {
    refresh()
  }, [])

  const wrap = (promise, okMessage) =>
    promise
      .then(() => {
        if (okMessage) toast.ok(okMessage)
        refresh()
      })
      .catch((error) => toast.error(String(error.message)))

  const add = (event) => {
    event.preventDefault()
    if (!form.username.trim() || !form.password) {
      toast.error('Username and password are required.')
      return
    }
    wrap(
      api.post('/api/users', { ...form, username: form.username.trim() }),
      `Added ${form.username.trim()}`,
    ).then(() => setForm({ username: '', password: '', role: 'editor' }))
  }

  const resetPassword = async (user) => {
    const next = await dialogs.prompt({
      title: `Reset password for ${user.username}`,
      label: 'New password',
      placeholder: 'Enter a new password',
      confirmLabel: 'Set password',
      hint: 'The user is not notified — tell them out of band.',
    })
    if (next) wrap(api.put(`/api/users/${encodeURIComponent(user.username)}`, { password: next }), 'Password reset')
  }

  const remove = async (user) => {
    const ok = await dialogs.confirm({
      title: `Delete ${user.username}?`,
      body: 'Their sessions end immediately. Processes they created are unaffected.',
      confirmLabel: 'Delete user',
      tone: 'danger',
    })
    if (ok) wrap(api.del(`/api/users/${encodeURIComponent(user.username)}`), `Deleted ${user.username}`)
  }

  if (users === null) return <div className="skeleton h-40" />

  return (
    <section className="card p-5">
      <div className="flex items-start gap-3">
        <span className="grid size-9 shrink-0 place-items-center rounded-lg bg-info-bg text-info-fg" aria-hidden="true">
          <UsersIcon size={17} />
        </span>
        <div>
          <h3 className="text-sm font-semibold">Users</h3>
          <p className="mt-1 max-w-prose text-[13px] text-fg-muted">
            Editors design and run processes; admins also manage users. Disabling a user revokes their sessions
            instantly.
          </p>
        </div>
      </div>

      <div className="mt-4 overflow-x-auto">
        <table className="table">
          <thead>
            <tr>
              <th>User</th>
              <th className="w-32">Role</th>
              <th className="w-28">Status</th>
              <th className="w-52" />
            </tr>
          </thead>
          <tbody>
            {users.map((user) => (
              <tr key={user.username}>
                <td>
                  <div className="flex items-center gap-2.5">
                    <span
                      className="grid size-7 shrink-0 place-items-center rounded-full bg-surface-3 text-[11px] font-bold text-fg-muted"
                      aria-hidden="true"
                    >
                      {user.username.charAt(0).toUpperCase()}
                    </span>
                    <span className="truncate font-medium">{user.username}</span>
                    {user.username === me?.username && <span className="badge">you</span>}
                  </div>
                </td>
                <td>
                  <select
                    className="select w-full"
                    aria-label={`Role for ${user.username}`}
                    value={user.role}
                    onChange={(event) =>
                      wrap(
                        api.put(`/api/users/${encodeURIComponent(user.username)}`, { role: event.target.value }),
                        'Role updated',
                      )
                    }
                  >
                    <option value="editor">editor</option>
                    <option value="admin">admin</option>
                  </select>
                </td>
                <td>
                  <label className="flex cursor-pointer items-center gap-2 text-xs text-fg-muted">
                    <input
                      type="checkbox"
                      className="checkbox"
                      checked={!user.disabled}
                      onChange={(event) =>
                        wrap(
                          api.put(`/api/users/${encodeURIComponent(user.username)}`, {
                            disabled: !event.target.checked,
                          }),
                          event.target.checked ? 'User enabled' : 'User disabled — sessions revoked',
                        )
                      }
                    />
                    {user.disabled ? 'Disabled' : 'Active'}
                  </label>
                </td>
                <td>
                  <div className="flex justify-end gap-1.5">
                    <button className="btn btn-sm" onClick={() => resetPassword(user)}>
                      Reset password
                    </button>
                    <button
                      className="btn btn-sm btn-danger btn-icon"
                      onClick={() => remove(user)}
                      aria-label={`Delete ${user.username}`}
                    >
                      <Trash2 size={13} />
                    </button>
                  </div>
                </td>
              </tr>
            ))}
            {users.length === 0 && (
              <tr>
                <td colSpan={4} className="muted">
                  No users yet — everyone signs in with the API token until you add one.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>

      <form className="mt-4 flex flex-wrap items-end gap-2 border-t border-line pt-4" onSubmit={add}>
        <div className="min-w-40 flex-1">
          <label className="label mb-1.5" htmlFor="pe-new-user">
            Username or email
          </label>
          <input
            id="pe-new-user"
            className="input"
            value={form.username}
            onChange={(event) => setForm({ ...form, username: event.target.value })}
          />
        </div>
        <div className="min-w-40 flex-1">
          <label className="label mb-1.5" htmlFor="pe-new-password">
            Password
          </label>
          <input
            id="pe-new-password"
            className="input"
            type="password"
            autoComplete="new-password"
            value={form.password}
            onChange={(event) => setForm({ ...form, password: event.target.value })}
          />
        </div>
        <div className="w-32">
          <label className="label mb-1.5" htmlFor="pe-new-role">
            Role
          </label>
          <select
            id="pe-new-role"
            className="select"
            value={form.role}
            onChange={(event) => setForm({ ...form, role: event.target.value })}
          >
            <option value="editor">editor</option>
            <option value="admin">admin</option>
          </select>
        </div>
        <button className="btn btn-primary" type="submit">
          <UserPlus size={15} />
          Add user
        </button>
      </form>
    </section>
  )
}

/* ---- notification relay -------------------------------------------------- */

const ENCRYPTION = [
  { value: 'starttls', label: 'STARTTLS — usually port 587' },
  { value: 'ssl', label: 'SSL/TLS — usually port 465' },
  { value: 'none', label: 'None — only for a trusted internal relay' },
]

/* The mail server run notifications are sent through. Deliberately the same
   fields as the Send Email (SMTP) step, so anyone who has configured one
   recognises this. The password is write-only: the API returns password_set,
   never the value, and leaving the box empty keeps whatever is stored. */
function NotificationsSection() {
  const [form, setForm] = useState(null)
  const [password, setPassword] = useState('')
  const [secretKey, setSecretKey] = useState('')
  const [busy, setBusy] = useState(false)
  const toast = useToast()
  const dialogs = useDialogs()

  useEffect(() => {
    api.get('/api/notifications/mail').then(setForm).catch(() => setForm({}))
  }, [])

  if (form === null) return <div className="skeleton h-40" />

  const set = (patch) => setForm({ ...form, ...patch })
  const isSes = (form.provider ?? 'smtp') === 'ses'

  const payload = () => ({
    enabled: form.enabled ?? true,
    provider: form.provider ?? 'smtp',
    sender: form.sender ?? '',
    host: form.host ?? '',
    port: Number(form.port) || 587,
    encryption: form.encryption ?? 'starttls',
    username: form.username ?? '',
    region: form.region ?? 'us-east-1',
    access_key_id: form.access_key_id ?? '',
    configuration_set: form.configuration_set ?? '',
    // undefined leaves the stored credential alone; "" is an explicit clear
    password: password || undefined,
    secret_access_key: secretKey || undefined,
  })

  const save = async (event) => {
    event.preventDefault()
    setBusy(true)
    try {
      setForm(await api.put('/api/notifications/mail', payload()))
      setPassword('')
      setSecretKey('')
      toast.ok('Mail settings saved')
    } catch (error) {
      toast.error(String(error.message))
    } finally {
      setBusy(false)
    }
  }

  const sendTest = async () => {
    const address = await dialogs.prompt({
      title: 'Send a test email',
      label: 'To',
      placeholder: 'you@example.com',
      confirmLabel: 'Send',
      hint: 'Save your changes first — the test uses the stored settings.',
    })
    if (!address) return
    try {
      await api.post('/api/notifications/test', { to: address })
      toast.ok(`Test email sent to ${address}`)
    } catch (error) {
      toast.error(String(error.message))
    }
  }

  return (
    <section className="card p-5">
      <div className="flex items-start gap-3">
        <span className="grid size-9 shrink-0 place-items-center rounded-lg bg-info-bg text-info-fg" aria-hidden="true">
          <Bell size={17} />
        </span>
        <div>
          <h3 className="text-sm font-semibold">Notification email</h3>
          <p className="mt-1 max-w-prose text-[13px] text-fg-muted">
            The mail server used to tell people how their processes are doing — who hears about which process is set
            on the process itself, in the designer. Steps that send email keep their own settings; this relay is
            only for notifications.
          </p>
        </div>
        <span className={`badge ml-auto shrink-0 ${form.active ? 'bg-ok-bg text-ok-fg' : 'bg-warn-bg text-warn-fg'}`}>
          {form.active ? 'Active' : form.configured ? 'Switched off' : 'Not configured'}
        </span>
      </div>

      <form className="mt-4 border-t border-line pt-4" onSubmit={save}>
        <label className="mb-4 flex cursor-pointer items-start gap-2 text-[13px]">
          <input
            type="checkbox"
            className="checkbox mt-0.5"
            checked={form.enabled ?? true}
            onChange={(event) => set({ enabled: event.target.checked })}
          />
          <span>
            <span className="font-medium">Send notification email</span>
            <span className="block text-[11px] text-fg-subtle">
              Unticking this silences every process at once without losing these settings.
            </span>
          </span>
        </label>

        <Field
          label="Send through"
          htmlFor="pe-mail-provider"
          description={
            isSes
              ? 'The SES v2 API. Inside AWS, leave the keys blank and let the instance role sign the call.'
              : 'Any SMTP relay — Exchange, Microsoft 365, Gmail, or one of your own.'
          }
        >
          <select
            id="pe-mail-provider"
            className="select"
            value={form.provider ?? 'smtp'}
            onChange={(event) => set({ provider: event.target.value })}
          >
            <option value="smtp">SMTP server</option>
            <option value="ses">Amazon SES</option>
          </select>
        </Field>

        <div className="grid gap-x-4 sm:grid-cols-2">
          <Field
            label="From"
            htmlFor="pe-mail-sender"
            description={
              isSes
                ? 'Must be an address or domain verified in SES.'
                : 'The address notifications arrive from.'
            }
          >
            <input
              id="pe-mail-sender"
              className="input"
              type="email"
              placeholder="engine@example.com"
              value={form.sender ?? ''}
              onChange={(event) => set({ sender: event.target.value })}
            />
          </Field>

          {isSes ? (
            <>
              <Field label="AWS region" htmlFor="pe-mail-region" description="Where your verified sender lives.">
                <input
                  id="pe-mail-region"
                  className="input"
                  placeholder="us-east-1"
                  value={form.region ?? ''}
                  onChange={(event) => set({ region: event.target.value })}
                />
              </Field>
              <Field
                label="Access key ID"
                htmlFor="pe-mail-access-key"
                description="Leave blank to use the engine machine's own AWS credentials."
              >
                <input
                  id="pe-mail-access-key"
                  className="input"
                  autoComplete="off"
                  value={form.access_key_id ?? ''}
                  onChange={(event) => set({ access_key_id: event.target.value })}
                />
              </Field>
              <Field
                label="Secret access key"
                htmlFor="pe-mail-secret-key"
                description={
                  form.secret_access_key_set
                    ? 'A key is stored. Type to replace it, or clear it below.'
                    : 'Encrypted at rest and never shown again.'
                }
              >
                <input
                  id="pe-mail-secret-key"
                  className="input"
                  type="password"
                  autoComplete="new-password"
                  placeholder={form.secret_access_key_set ? '••••••••' : ''}
                  value={secretKey}
                  onChange={(event) => setSecretKey(event.target.value)}
                />
              </Field>
              <Field
                label="Configuration set"
                htmlFor="pe-mail-config-set"
                description="Optional — for open/click tracking or a dedicated IP pool."
              >
                <input
                  id="pe-mail-config-set"
                  className="input"
                  value={form.configuration_set ?? ''}
                  onChange={(event) => set({ configuration_set: event.target.value })}
                />
              </Field>
            </>
          ) : (
            <>
              <Field label="Mail server" htmlFor="pe-mail-host">
                <input
                  id="pe-mail-host"
                  className="input"
                  placeholder="smtp.office365.com"
                  value={form.host ?? ''}
                  onChange={(event) => set({ host: event.target.value })}
                />
              </Field>
              <Field label="Port" htmlFor="pe-mail-port">
                <input
                  id="pe-mail-port"
                  className="input"
                  type="number"
                  min="1"
                  max="65535"
                  value={form.port ?? 587}
                  onChange={(event) => set({ port: event.target.value })}
                />
              </Field>
              <Field label="Encryption" htmlFor="pe-mail-encryption">
                <select
                  id="pe-mail-encryption"
                  className="select"
                  value={form.encryption ?? 'starttls'}
                  onChange={(event) => set({ encryption: event.target.value })}
                >
                  {ENCRYPTION.map((option) => (
                    <option key={option.value} value={option.value}>
                      {option.label}
                    </option>
                  ))}
                </select>
              </Field>
              <Field
                label="Username"
                htmlFor="pe-mail-username"
                description="Leave blank if the server accepts mail without signing in."
              >
                <input
                  id="pe-mail-username"
                  className="input"
                  value={form.username ?? ''}
                  onChange={(event) => set({ username: event.target.value })}
                />
              </Field>
              <Field
                label="Password"
                htmlFor="pe-mail-password"
                description={
                  form.password_set
                    ? 'A password is stored. Type to replace it, or clear it below.'
                    : 'Encrypted at rest and never shown again.'
                }
              >
                <input
                  id="pe-mail-password"
                  className="input"
                  type="password"
                  autoComplete="new-password"
                  placeholder={form.password_set ? '••••••••' : ''}
                  value={password}
                  onChange={(event) => setPassword(event.target.value)}
                />
              </Field>
            </>
          )}
        </div>

        <div className="mt-2 flex flex-wrap items-center gap-2 border-t border-line pt-4">
          <button className="btn btn-primary" type="submit" disabled={busy}>
            Save
          </button>
          <button className="btn" type="button" onClick={sendTest} disabled={!form.configured}>
            <Send size={15} />
            Send test email
          </button>
          {(isSes ? form.secret_access_key_set : form.password_set) && (
            <button
              className="btn btn-ghost btn-sm ml-auto text-fg-subtle"
              type="button"
              onClick={async () => {
                const label = isSes ? 'secret access key' : 'password'
                const ok = await dialogs.confirm({
                  title: `Clear the stored ${label}?`,
                  body: isSes
                    ? "SES will be called with the engine machine's own AWS credentials instead."
                    : 'The relay will be used without signing in.',
                  confirmLabel: `Clear ${label}`,
                  tone: 'danger',
                })
                if (!ok) return
                try {
                  const cleared = isSes ? { secret_access_key: '' } : { password: '' }
                  setForm(await api.put('/api/notifications/mail', { ...payload(), ...cleared }))
                  toast.ok(`Cleared the ${label}`)
                } catch (error) {
                  toast.error(String(error.message))
                }
              }}
            >
              Clear {isSes ? 'key' : 'password'}
            </button>
          )}
        </div>
      </form>
    </section>
  )
}

/* ---- plugins ------------------------------------------------------------- */

function PluginsSection() {
  const [plugins, setPlugins] = useState([])
  const [query, setQuery] = useState('')

  useEffect(() => {
    api.get('/api/plugins').then(setPlugins).catch(() => {})
  }, [])

  const visible = useMemo(() => {
    const term = query.trim().toLowerCase()
    if (!term) return plugins
    return plugins.filter((plugin) =>
      `${plugin.name} ${plugin.key} ${plugin.category} ${plugin.description ?? ''}`.toLowerCase().includes(term),
    )
  }, [plugins, query])

  return (
    <section className="card p-5">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="flex items-start gap-3">
          <span className="grid size-9 shrink-0 place-items-center rounded-lg bg-brand-soft text-brand-text" aria-hidden="true">
            <Puzzle size={17} />
          </span>
          <div>
            <h3 className="text-sm font-semibold">Installed plugins</h3>
            <p className="mt-1 max-w-prose text-[13px] text-fg-muted">
              {plugins.length} available. A new one is added to the engine's source and ships with it — this list is
              read at startup, so it changes when the API and the engines are restarted.
            </p>
          </div>
        </div>
        <div className="relative min-w-52">
          <Search
            size={15}
            className="pointer-events-none absolute left-2.5 top-1/2 -translate-y-1/2 text-fg-subtle"
            aria-hidden="true"
          />
          <input
            className="input pl-8"
            placeholder="Search plugins…"
            aria-label="Search plugins"
            value={query}
            onChange={(event) => setQuery(event.target.value)}
          />
        </div>
      </div>

      <div className="mt-4 overflow-x-auto">
        <table className="table">
          <thead>
            <tr>
              <th>Plugin</th>
              <th className="w-44">Key</th>
              <th className="w-32">Category</th>
              <th className="w-40">Output ports</th>
            </tr>
          </thead>
          <tbody>
            {visible.map((plugin) => (
              <tr key={plugin.key}>
                <td>
                  <div className="flex items-start gap-2.5">
                    <PluginIcon plugin={plugin} size={14} className="mt-0.5 size-7" />
                    <div className="min-w-0">
                      <div className="font-medium">{plugin.name}</div>
                      <div className="text-[11px] text-fg-muted">{plugin.description}</div>
                    </div>
                  </div>
                </td>
                <td>
                  <code className="code">{plugin.key}</code>
                </td>
                <td className="text-fg-muted">{plugin.category}</td>
                <td className="text-fg-muted">
                  <div className="flex flex-wrap gap-1">
                    {plugin.outputs.map((port) => (
                      <span key={port.name} className="badge font-mono">
                        {port.name}
                      </span>
                    ))}
                  </div>
                </td>
              </tr>
            ))}
            {visible.length === 0 && (
              <tr>
                <td colSpan={4}>
                  <p className="muted py-4 text-center">No plugin matches “{query}”.</p>
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </section>
  )
}

/* ---- page ---------------------------------------------------------------- */

/**
 * Deployment configuration, admin-only in full.
 *
 * What used to live here and did *not* belong to a deployment has moved to
 * where its audience is: theme to the account menu (it is a per-browser
 * preference every user sets for themselves) and secrets to their own page
 * (they are building material an editor needs). What is left is the mail relay,
 * the file sandbox, accounts and the installed plugin inventory — things one
 * person configures for everyone.
 */
const TABS = [
  { key: 'notifications', label: 'Notifications', icon: Bell },
  { key: 'execution', label: 'Execution', icon: Server },
  { key: 'files', label: 'Files', icon: FolderTree },
  { key: 'users', label: 'Users', icon: UsersIcon },
  { key: 'plugins', label: 'Plugins', icon: Puzzle },
]

export default function Settings() {
  const user = getUser()
  const isAdmin = user?.role === 'admin'
  const [tab, setTab] = useState('notifications')

  // The route guard already turns non-admins away, so this is the belt to that
  // braces: a stale session whose role changed under it still sees nothing.
  if (!isAdmin) {
    return (
      <AppShell title="Settings">
        <EmptyState icon={Shield} title="Admins only">
          Settings configures the whole deployment, so it is limited to administrators. Your theme and the guided tour
          are in the account menu, and your secrets are under Secrets.
        </EmptyState>
      </AppShell>
    )
  }

  return (
    <AppShell title="Settings">
      <div className="mb-5 flex flex-wrap items-center justify-between gap-3">
        <div>
          <h2 className="text-xl font-bold">Settings</h2>
          <p className="text-[13px] text-fg-muted">
            Signed in as <strong className="text-fg">{user?.username}</strong>
            <span className="badge badge-brand ml-1.5">
              <Shield size={11} aria-hidden="true" />
              {user?.role}
            </span>
          </p>
        </div>
      </div>

      <div
        className="tab-list mb-5 flex-wrap"
        role="tablist"
        aria-label="Settings sections"
        data-tour="settings-tabs"
      >
        {TABS.map((entry) => {
          const Icon = entry.icon
          return (
            <button
              key={entry.key}
              role="tab"
              aria-selected={tab === entry.key}
              className={`tab flex items-center gap-1.5 ${tab === entry.key ? 'is-active' : ''}`}
              onClick={() => setTab(entry.key)}
            >
              <Icon size={13} aria-hidden="true" />
              {entry.label}
            </button>
          )
        })}
      </div>

      {tab === 'notifications' && <NotificationsSection />}
      {tab === 'execution' && <ExecutionSection />}
      {tab === 'files' && <FilesSection />}
      {tab === 'users' && <UsersSection />}
      {tab === 'plugins' && <PluginsSection />}
    </AppShell>
  )
}
