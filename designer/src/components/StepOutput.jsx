import { useState } from 'react'
import { AlertTriangle, ChevronRight, Loader2, Play } from 'lucide-react'
import { api } from '../api.js'
import { duration, shortId } from '../format.js'
import JsonTree from './JsonTree.jsx'
import StatusBadge from './ui/StatusBadge.jsx'

/** A collapsible block of run data — closed by default except the payload. */
function Section({ title, defaultOpen = false, children }) {
  const [open, setOpen] = useState(defaultOpen)
  return (
    <div className="mt-2">
      <button
        className="flex w-full items-center gap-1 text-[11px] font-semibold text-fg-muted hover:text-fg"
        onClick={() => setOpen((value) => !value)}
        aria-expanded={open}
      >
        <ChevronRight size={12} className={`transition-transform ${open ? 'rotate-90' : ''}`} />
        {title}
      </button>
      {open && (
        <div className="mt-1 max-h-72 overflow-auto rounded-md border border-line bg-surface-2 p-2">{children}</div>
      )}
    </div>
  )
}

/**
 * Runs just this step against the latest recorded run and shows what it
 * produced. The plugin executes for real, so side effects happen — the panel
 * says so before you press the button.
 */
export default function StepOutput({ processId, stepId, stepLabel, onBeforeRun }) {
  const [result, setResult] = useState(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')

  const run = async () => {
    setBusy(true)
    setError('')
    try {
      await onBeforeRun?.() // save first so the server previews the current config
      setResult(await api.post(`/api/processes/${processId}/steps/${stepId}/preview`, {}))
    } catch (err) {
      setError(String(err.message))
      setResult(null)
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="panel">
      <div className="panel-title">Output</div>

      {!processId ? (
        <p className="hint">Save the process first to preview this step.</p>
      ) : (
        <>
          <button className="btn btn-primary btn-sm w-full" onClick={run} disabled={busy}>
            {busy ? <Loader2 size={13} className="animate-spin-slow" /> : <Play size={13} />}
            {busy ? 'Running…' : `Test “${stepLabel}”`}
          </button>
          {/* Stated before the click, not after: this is a real execution. */}
          <p className="hint mt-2 flex items-start gap-1.5 rounded-md bg-warn-bg px-2 py-1.5 text-warn-fg">
            <AlertTriangle size={12} className="mt-px shrink-0" aria-hidden="true" />
            Runs only this step, using data from the most recent run. The plugin executes for real — a step that sends
            mail or writes rows will do so. Nothing is added to the run history.
          </p>
        </>
      )}

      {error && (
        <p className="error-text mt-2" role="alert">
          {error}
        </p>
      )}

      {result && (
        <div className="mt-3">
          <div className="flex flex-wrap items-center gap-2">
            <StatusBadge status={result.status} />
            {result.duration_ms != null && (
              <span className="tabular text-[11px] text-fg-subtle">{duration(result.duration_ms)}</span>
            )}
            {result.attempts > 1 && (
              <span className="text-[11px] text-fg-subtle">· {result.attempts} attempts</span>
            )}
            {result.based_on_run && (
              <span className="text-[11px] text-fg-subtle" title={result.based_on_run}>
                · input from {shortId(result.based_on_run)}
              </span>
            )}
          </div>

          {result.error && (
            <p className="mt-2 flex items-start gap-1.5 rounded-md bg-bad-bg px-2 py-1.5 text-[11px] text-bad-fg">
              <AlertTriangle size={12} className="mt-px shrink-0" aria-hidden="true" />
              <span className="min-w-0 break-words">{result.error}</span>
            </p>
          )}

          <Section title="Output" defaultOpen={!result.error}>
            {Object.keys(result.outputs ?? {}).length === 0 ? (
              <p className="muted">No output emitted.</p>
            ) : (
              Object.entries(result.outputs).map(([port, payload]) => (
                <JsonTree key={port} label={port} data={payload} />
              ))
            )}
          </Section>

          <Section title="Resolved config (expressions filled in)">
            <JsonTree label="config" data={result.resolved_config} />
          </Section>

          <Section title="Input used">
            <JsonTree label="input" data={result.input} />
          </Section>
        </div>
      )}
    </div>
  )
}
