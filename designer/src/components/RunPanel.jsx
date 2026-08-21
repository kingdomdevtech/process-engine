import { useState } from 'react'
import { AlertTriangle, ChevronDown, ChevronRight, Play, RefreshCw, Repeat } from 'lucide-react'
import { absoluteTime, duration, durationBetween, shortId } from '../format.js'
import JsonTree from './JsonTree.jsx'
import StatusBadge from './ui/StatusBadge.jsx'

/** One step in the run, collapsed to a line until you ask for its data. */
function StepRow({ step }) {
  const [open, setOpen] = useState(false)
  const hasData =
    step.input !== null || Object.keys(step.outputs ?? {}).length > 0 || Boolean(step.error)

  return (
    <li className="relative pl-6">
      {/* the rail dot, aligned to the connecting line drawn by the parent */}
      <span
        className={`absolute left-[5px] top-2 size-2 rounded-full ring-2 ring-surface ${
          {
            succeeded: 'bg-ok-fg',
            failed: 'bg-bad-fg',
            running: 'bg-info-fg',
            paused: 'bg-warn-fg',
            skipped: 'bg-fg-subtle',
          }[step.status] ?? 'bg-line-strong'
        }`}
        aria-hidden="true"
      />
      <div className="flex flex-wrap items-center gap-x-2 gap-y-1 py-1.5">
        <button
          className="flex min-w-0 flex-1 items-center gap-1.5 text-left"
          onClick={() => hasData && setOpen((value) => !value)}
          disabled={!hasData}
          aria-expanded={hasData ? open : undefined}
        >
          {hasData ? (
            open ? (
              <ChevronDown size={13} className="shrink-0 text-fg-subtle" />
            ) : (
              <ChevronRight size={13} className="shrink-0 text-fg-subtle" />
            )
          ) : (
            <span className="w-[13px] shrink-0" />
          )}
          <span className="truncate text-[13px] font-medium" title={step.step_name || step.step_id}>
            {step.step_name || step.step_id}
          </span>
        </button>

        <span className="flex shrink-0 items-center gap-1.5">
          {step.attempts > 1 && (
            <span className="badge badge-paused" title={`${step.attempts} attempts — the step was retried`}>
              <Repeat size={11} />×{step.attempts}
            </span>
          )}
          {step.duration_ms != null && (
            <span className="tabular text-[11px] text-fg-subtle">{duration(step.duration_ms)}</span>
          )}
          <StatusBadge status={step.status} />
        </span>
      </div>

      {step.error && (
        <p className="mb-1.5 flex items-start gap-1.5 rounded-md bg-bad-bg px-2 py-1.5 text-[11px] text-bad-fg">
          <AlertTriangle size={12} className="mt-px shrink-0" aria-hidden="true" />
          <span className="min-w-0 break-words">{step.error}</span>
        </p>
      )}

      {open && hasData && (
        <div className="mb-2 space-y-2 rounded-md border border-line bg-surface-2 p-2">
          <div>
            <div className="section-label mb-1">Input</div>
            <JsonTree label="input" data={step.input} />
          </div>
          <div>
            <div className="section-label mb-1">Outputs</div>
            <JsonTree label="outputs" data={step.outputs} />
          </div>
        </div>
      )}
    </li>
  )
}

export default function RunPanel({ run, onResume, onCancel, onRefresh, className = '' }) {
  if (!run) return null

  const steps = run.step_runs ?? []
  const done = steps.filter((step) => step.status === 'succeeded').length
  const elapsed = durationBetween(run.started_at, run.finished_at)
  const live = run.status === 'running'

  return (
    <div className={className}>
      <div className="mb-3 flex flex-wrap items-center gap-2">
        <StatusBadge status={run.status} />
        {elapsed && <span className="tabular text-[11px] text-fg-subtle">{elapsed}</span>}
        <code className="code ml-auto" title={run.id}>
          {shortId(run.id)}
        </code>
      </div>

      {run.started_at && (
        <p className="hint mb-3">
          Started {absoluteTime(run.started_at)}
          {run.version ? ` · version ${run.version}` : ''}
        </p>
      )}

      {run.error && (
        <p className="mb-3 flex items-start gap-2 rounded-md border border-bad-fg/30 bg-bad-bg px-2.5 py-2 text-xs text-bad-fg">
          <AlertTriangle size={14} className="mt-px shrink-0" aria-hidden="true" />
          <span className="min-w-0 break-words">{run.error}</span>
        </p>
      )}

      <div className="mb-2 flex items-center gap-2">
        <div className="section-label mb-0">
          Steps · {done}/{steps.length}
        </div>
        <div className="ml-auto flex items-center gap-1.5">
          {onRefresh && (
            <button className="btn btn-sm btn-ghost" onClick={() => onRefresh(run.id)}>
              <RefreshCw size={13} className={live ? 'animate-spin-slow' : ''} />
              Refresh
            </button>
          )}
          {run.status === 'paused' && onResume && (
            <button className="btn btn-sm" onClick={() => onResume(run.id)}>
              <Play size={13} />
              Resume
            </button>
          )}
          {live && onCancel && (
            <button className="btn btn-sm btn-danger" onClick={() => onCancel(run.id)}>
              Cancel
            </button>
          )}
        </div>
      </div>

      {steps.length === 0 ? (
        <p className="muted">No steps recorded.</p>
      ) : (
        // the rail: a single line behind the dots, so the sequence reads as one run
        <ol className="relative before:absolute before:bottom-2 before:left-[9px] before:top-2 before:w-px before:bg-line">
          {steps.map((step) => (
            <StepRow key={step.step_id} step={step} />
          ))}
        </ol>
      )}
    </div>
  )
}
