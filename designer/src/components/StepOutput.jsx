import { useEffect, useRef, useState } from 'react'
import { AlertTriangle, ChevronRight, Loader2, Play, Server } from 'lucide-react'
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

const POLL_MS = 700
const GIVE_UP_MS = 15 * 60 * 1000 // an Excel refresh is slow; eventually say so

const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms))

/** What a step is waiting on, in the words of whoever is waiting. */
function waitingText({ state, worker, workers_online: online }) {
  if (state === 'running') return `Running on ${worker?.split(':')[0] || 'the worker'}…`
  if (!online) return 'Waiting for a worker — none is running right now.'
  return 'Queued behind other work on the worker…'
}

/**
 * Runs just this step against the latest recorded run and shows what it
 * produced. The plugin executes for real, so side effects happen — the panel
 * says so before you press the button.
 *
 * The step may not execute on the machine serving this API: a deployment can
 * put the engine's work on remote workers (a Windows host, for the Excel
 * plugins) which serve no HTTP of their own. Then the POST only queues the
 * request and the answer arrives by polling, so this waits — and says what it
 * is waiting for, since "queued" and "no worker is running" are the same
 * spinner otherwise.
 */
export default function StepOutput({ processId, stepId, stepLabel, onBeforeRun }) {
  const [result, setResult] = useState(null)
  const [busy, setBusy] = useState(false)
  const [waiting, setWaiting] = useState(null)
  const [error, setError] = useState('')
  const live = useRef(true)

  // deselecting the step unmounts this panel; the poll must not outlive it
  useEffect(() => {
    live.current = true
    return () => {
      live.current = false
    }
  }, [])

  /** Poll a queued preview until a worker answers it. */
  const collect = async (previewId) => {
    const deadline = Date.now() + GIVE_UP_MS
    while (live.current && Date.now() < deadline) {
      await sleep(POLL_MS)
      if (!live.current) return null
      const state = await api.get(`/api/processes/${processId}/previews/${previewId}`)
      if (state.state === 'done' || state.state === 'failed') return state
      setWaiting(state)
    }
    return live.current ? { state: 'failed', issues: ['Still running on the worker — check back shortly.'] } : null
  }

  const run = async () => {
    setBusy(true)
    setError('')
    setWaiting(null)
    try {
      await onBeforeRun?.() // save first so the server previews the current config
      let reply = await api.post(`/api/processes/${processId}/steps/${stepId}/preview`, {})
      if (reply.state !== 'done') {
        setWaiting(reply)
        reply = await collect(reply.preview_id)
        if (!reply) return // panel closed while we waited
      }
      if (reply.state === 'failed') throw new Error(reply.issues.join('; '))
      setResult(reply)
    } catch (err) {
      setError(String(err.message))
      setResult(null)
    } finally {
      setWaiting(null)
      if (live.current) setBusy(false)
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
          {waiting && (
            <p className="hint mt-2 flex items-start gap-1.5" aria-live="polite">
              <Server size={12} className="mt-px shrink-0" aria-hidden="true" />
              {waitingText(waiting)}
            </p>
          )}
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
