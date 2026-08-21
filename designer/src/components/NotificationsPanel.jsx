import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { AlertTriangle, Bell } from 'lucide-react'

import { api, getUser } from '../api.js'
import TagListField from './fields/TagListField.jsx'

/* Worded as things that happen to the process, not as run statuses: the person
   ticking these boxes is asking "tell me when it breaks", not selecting an
   enum. "finishes" is last because it is the catch-all the others narrow. */
const EVENTS = [
  { key: 'started', label: 'starts', hint: 'One email as the run begins.' },
  { key: 'succeeded', label: 'succeeds' },
  { key: 'failed', label: 'fails', hint: 'Includes the step that failed and why.' },
  { key: 'completed', label: 'finishes', hint: 'Whatever the outcome — including cancelled.' },
]

const LOOKS_LIKE_EMAIL = /^[^\s@]+@[^\s@]+\.[^\s@]+$/

/** Who to email about this process's runs. Sits under Triggers in the
 *  inspector: both answer "what happens around a run", rather than in it. */
export default function NotificationsPanel({ notifications, onChange, createdBy }) {
  const [mail, setMail] = useState(null)
  const [directory, setDirectory] = useState([])
  const settings = notifications ?? {}
  const events = settings.events ?? []
  const recipients = settings.recipients ?? []
  const notifyCreator = settings.notify_creator !== false

  useEffect(() => {
    api.get('/api/notifications/mail').then(setMail).catch(() => setMail({}))
    api.get('/api/users/directory').then(setDirectory).catch(() => {})
  }, [])

  const update = (patch) => onChange({ ...settings, ...patch })
  const toggleEvent = (key, on) =>
    update({ events: on ? [...events, key] : events.filter((event) => event !== key) })

  /* An unsaved process has no creator yet; it will be whoever is signed in. */
  const creator = createdBy || getUser()?.username || ''
  const creatorAddressable = LOOKS_LIKE_EMAIL.test(creator)
  const on = events.length > 0
  const willReach = (notifyCreator && creatorAddressable) || recipients.some((r) => LOOKS_LIKE_EMAIL.test(r))
  /* Ticking "finishes" as well as an outcome is not two emails — say so before
     someone unticks the wrong one to avoid the duplicate they expect. */
  const overlaps = events.includes('completed') && (events.includes('succeeded') || events.includes('failed'))

  return (
    <div className="panel">
      <div className="panel-title">
        Notifications
        {on && <span className="badge badge-brand ml-auto normal-case tracking-normal">{events.length} on</span>}
      </div>
      <p className="hint mb-2">Email people about this process&rsquo;s runs. Nothing is sent until you tick one.</p>

      <fieldset className="mb-3">
        <legend className="label mb-1.5">Email when this process</legend>
        {EVENTS.map((event) => (
          <label key={event.key} className="mb-1 flex cursor-pointer items-start gap-2 text-xs">
            <input
              type="checkbox"
              className="checkbox mt-0.5 size-3.5 shrink-0"
              checked={events.includes(event.key)}
              onChange={(e) => toggleEvent(event.key, e.target.checked)}
            />
            <span className="min-w-0">
              <span className="font-medium">{event.label}</span>
              {event.hint && <span className="block text-[11px] text-fg-subtle">{event.hint}</span>}
            </span>
          </label>
        ))}
      </fieldset>

      {overlaps && (
        <p className="hint mb-3">
          Still one email per run — a run that fails is reported as <strong>fails</strong>, and{' '}
          <strong>finishes</strong> covers the outcomes you have not ticked.
        </p>
      )}

      {on && (
        <>
          <label className="mb-2 flex cursor-pointer items-start gap-2 text-xs">
            <input
              type="checkbox"
              className="checkbox mt-0.5 size-3.5 shrink-0"
              checked={notifyCreator}
              onChange={(event) => update({ notify_creator: event.target.checked })}
            />
            <span className="min-w-0">
              <span className="font-medium">Email whoever created this process</span>
              <span className="block truncate text-[11px] text-fg-subtle" title={creator}>
                {creator || 'set when you first save'}
                {creator && !creatorAddressable && ' — not an email address, so it will be skipped'}
              </span>
            </span>
          </label>

          <div className="mb-1.5">
            <span className="label">Also email</span>
          </div>
          <TagListField
            value={recipients}
            onCommit={(next) => update({ recipients: next ?? [] })}
            hints={{ widget: 'emails', addLabel: 'Add' }}
            suggestions={directory}
            placeholder="name@example.com"
          />

          {!willReach && (
            <p className="mt-2 flex items-start gap-1.5 text-[11px] text-warn-fg">
              <AlertTriangle size={12} className="mt-px shrink-0" aria-hidden="true" />
              Nobody would be emailed yet — add an address above.
            </p>
          )}

          {mail && mail.active === false && (
            <p className="mt-2 flex items-start gap-1.5 text-[11px] text-warn-fg">
              <Bell size={12} className="mt-px shrink-0" aria-hidden="true" />
              <span>
                {mail.configured
                  ? 'Notifications are switched off for this deployment.'
                  : 'No mail server is set up yet, so nothing can be sent.'}{' '}
                {getUser()?.role === 'admin' ? (
                  <Link className="link" to="/app/settings">
                    Open Settings
                  </Link>
                ) : (
                  'Ask an administrator to set one up.'
                )}
              </span>
            </p>
          )}
        </>
      )}
    </div>
  )
}
