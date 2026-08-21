import { useMemo } from 'react'
import { AlertTriangle, Check, Clock, Copy, Link2, Plus, Trash2, Webhook } from 'lucide-react'
import { relativeTime, shortId } from '../format.js'
import { useToast } from './Toast.jsx'
import StatusBadge from './ui/StatusBadge.jsx'

const CRON_PRESETS = [
  { label: 'Every 15 min', cron: '*/15 * * * *' },
  { label: 'Hourly', cron: '0 * * * *' },
  { label: 'Daily 07:00', cron: '0 7 * * *' },
  { label: 'Weekdays 08:00', cron: '0 8 * * 1-5' },
]

/** The inspector when no step is selected: how this process starts, what to
 *  feed it while testing, and what it has done lately.
 *
 *  `children` are further process-level panels — notifications today — placed
 *  with the rest of the configuration, above the run history rather than after
 *  it. */
export default function TriggersPanel({
  processId,
  triggers,
  onChange,
  triggerInput,
  onTriggerInput,
  runs,
  issueCount = 0,
  onViewRun,
  onResumeRun,
  onCancelRun,
  children,
}) {
  const toast = useToast()

  const update = (index, patch) => onChange(triggers.map((t, i) => (i === index ? { ...t, ...patch } : t)))
  const remove = (index) => onChange(triggers.filter((_, i) => i !== index))
  const add = (type) =>
    onChange([
      ...triggers,
      type === 'schedule'
        ? { type: 'schedule', cron: '0 7 * * *', enabled: true }
        : { type: 'webhook', path: '', enabled: true },
    ])

  /* Malformed test JSON is silently ignored at run time, so say so up front
     rather than letting a typo look like an engine bug. */
  const inputValid = useMemo(() => {
    if (!triggerInput?.trim()) return true
    try {
      JSON.parse(triggerInput)
      return true
    } catch {
      return false
    }
  }, [triggerInput])

  return (
    <>
      {issueCount > 0 && (
        <div className="flex items-center gap-2 border-b border-line bg-warn-bg px-4 py-2.5 text-xs text-warn-fg">
          <AlertTriangle size={14} className="shrink-0" aria-hidden="true" />
          <span>
            {issueCount} step {issueCount === 1 ? 'issue' : 'issues'} — select a flagged step to fix it.
          </span>
        </div>
      )}

      <div className="panel">
        <div className="panel-title">Test input</div>
        <p className="hint mb-2">
          Sent as <code className="code">trigger</code> when you press Run draft. Reference it with{' '}
          <code className="code">{'{{ trigger.field }}'}</code>.
        </p>
        <textarea
          className={`textarea min-h-16 ${inputValid ? '' : 'input-invalid'}`}
          rows={3}
          spellCheck={false}
          value={triggerInput}
          aria-label="Trigger JSON for test runs"
          aria-invalid={!inputValid}
          placeholder='{"total": 250}'
          onChange={(event) => onTriggerInput(event.target.value)}
        />
        <p className={`mt-1 flex items-center gap-1 text-[11px] ${inputValid ? 'text-fg-subtle' : 'text-bad-fg'}`}>
          {inputValid ? (
            <>
              <Check size={11} /> Valid JSON
            </>
          ) : (
            <>
              <AlertTriangle size={11} /> Not valid JSON — the run will start with no trigger data.
            </>
          )}
        </p>
      </div>

      <div className="panel">
        <div className="panel-title">
          Triggers
          <span className="ml-auto font-mono text-[10px] normal-case tracking-normal">{triggers.length}</span>
        </div>

        {triggers.length === 0 && (
          <p className="muted mb-2">Runs manually only. Add a trigger to automate it.</p>
        )}

        {triggers.map((trigger, index) => (
          <div key={trigger.id ?? index} className="mb-2 rounded-lg border border-line bg-surface-2 p-2.5">
            <div className="mb-2 flex items-center gap-2">
              <span
                className={`grid size-6 shrink-0 place-items-center rounded-md ${
                  trigger.type === 'schedule' ? 'bg-warn-bg text-warn-fg' : 'bg-info-bg text-info-fg'
                }`}
                aria-hidden="true"
              >
                {trigger.type === 'schedule' ? <Clock size={13} /> : <Webhook size={13} />}
              </span>
              <strong className="text-xs capitalize">{trigger.type}</strong>

              <label className="ml-auto flex cursor-pointer items-center gap-1.5 text-[11px] text-fg-muted">
                <input
                  type="checkbox"
                  className="checkbox size-3.5"
                  checked={trigger.enabled}
                  onChange={(event) => update(index, { enabled: event.target.checked })}
                />
                enabled
              </label>
              <button
                className="btn btn-ghost btn-icon btn-sm text-fg-subtle hover:text-bad-fg"
                onClick={() => remove(index)}
                aria-label={`Remove ${trigger.type} trigger`}
              >
                <Trash2 size={13} />
              </button>
            </div>

            {trigger.type === 'schedule' ? (
              <>
                <input
                  className="input font-mono text-xs"
                  value={trigger.cron}
                  placeholder="*/15 * * * *"
                  aria-label="Cron expression"
                  onChange={(event) => update(index, { cron: event.target.value })}
                />
                <div className="mt-1.5 flex flex-wrap gap-1">
                  {CRON_PRESETS.map((preset) => (
                    <button
                      key={preset.cron}
                      className="badge hover:bg-brand-soft hover:text-brand-text"
                      onClick={() => update(index, { cron: preset.cron })}
                    >
                      {preset.label}
                    </button>
                  ))}
                </div>
                <p className="hint mt-1.5">minute · hour · day of month · month · day of week</p>
              </>
            ) : (
              <>
                <input
                  className="input font-mono text-xs"
                  value={trigger.path}
                  placeholder={`path (default: ${processId ?? 'process id'})`}
                  aria-label="Webhook path"
                  onChange={(event) => update(index, { path: event.target.value })}
                />
                <div className="mt-1.5 flex items-center gap-1.5 rounded-md bg-surface-3 px-2 py-1">
                  <Link2 size={11} className="shrink-0 text-fg-subtle" aria-hidden="true" />
                  <code className="min-w-0 flex-1 truncate font-mono text-[10px] text-fg-muted">
                    POST /api/hooks/{trigger.path || processId || '…save first…'}
                  </code>
                  <button
                    className="btn btn-ghost btn-icon size-5"
                    aria-label="Copy webhook URL"
                    onClick={() => {
                      navigator.clipboard
                        ?.writeText(`${window.location.origin}/api/hooks/${trigger.path || processId || ''}`)
                        .then(() => toast.ok('Webhook URL copied'))
                        .catch(() => toast.error('Could not copy to the clipboard'))
                    }}
                  >
                    <Copy size={11} />
                  </button>
                </div>
                <p className="hint mt-1.5">No authentication — treat the URL itself as the credential.</p>
              </>
            )}
          </div>
        ))}

        <div className="flex gap-1.5">
          <button className="btn btn-sm" onClick={() => add('schedule')}>
            <Plus size={13} />
            Schedule
          </button>
          <button className="btn btn-sm" onClick={() => add('webhook')}>
            <Plus size={13} />
            Webhook
          </button>
        </div>
        <p className="hint mt-2">Triggers fire the latest published version — publish after changes.</p>
      </div>

      {children}

      <div className="panel">
        <div className="panel-title">Recent runs</div>
        {runs.length === 0 ? (
          <p className="muted">No runs yet.</p>
        ) : (
          <ul className="space-y-1">
            {runs.slice(0, 8).map((run) => (
              <li key={run.id} className="flex items-center gap-2">
                <button
                  className="link min-w-0 font-mono text-[11px]"
                  onClick={() => onViewRun(run.id)}
                  title={`Open run ${run.id}`}
                >
                  {shortId(run.id)}
                </button>
                <StatusBadge status={run.status} />
                <span className="ml-auto shrink-0 text-[11px] text-fg-subtle">
                  {relativeTime(run.created_at)}
                </span>
                {run.status === 'paused' && (
                  <button className="link shrink-0 text-[11px]" onClick={() => onResumeRun(run.id)}>
                    resume
                  </button>
                )}
                {run.status === 'running' && (
                  <button
                    className="link shrink-0 text-[11px] text-bad-fg"
                    onClick={() => onCancelRun(run.id)}
                  >
                    cancel
                  </button>
                )}
              </li>
            ))}
          </ul>
        )}
      </div>
    </>
  )
}
