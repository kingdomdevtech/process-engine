import { useCallback, useEffect, useState } from 'react'
import { Info, RefreshCw } from 'lucide-react'
import { api } from '../api.js'
import { absoluteTime, shortId } from '../format.js'
import JsonTree from './JsonTree.jsx'

const TRIGGER = '__trigger__'

/**
 * How the select encodes a step source: `step:<id>` on a plain main port, and
 * `step:<id>:<port>` on a named one. Ids never contain a colon, so the first one
 * separates the two.
 */
function parseStep(value) {
  if (!value.startsWith('step:')) return null
  const rest = value.slice('step:'.length)
  const cut = rest.indexOf(':')
  return cut === -1
    ? { id: rest, port: 'main' }
    : { id: rest.slice(0, cut), port: rest.slice(cut + 1) }
}

/** One option per way into a step: its main port, or each branch it emits on. */
function sourceOptions(step) {
  const ports = step.ports?.length ? step.ports : ['main']
  if (ports.length === 1 && ports[0] === 'main') return [{ value: `step:${step.id}`, label: step.label }]
  return ports.map((port) => ({ value: `step:${step.id}:${port}`, label: `${step.label} (${port})` }))
}

/**
 * The step input panel: where this step's work comes from, and what arrived
 * from there last time.
 *
 * The source list is the answer to a question about the graph, so choosing
 * from it edits the graph. Two kinds of source can answer it:
 *
 * - **a step** (or the trigger box, which is where the process itself starts) —
 *   picking one re-points this step's incoming arrow at it, so the canvas and
 *   this panel can never disagree about what feeds this step. Only steps that
 *   cannot already be reached *from* here are offered: the graph is a DAG, and
 *   an arrow back would be a cycle the save would reject. A step that branches
 *   is offered once per branch, because "after the check" is not an answer the
 *   graph can hold — a Condition emits on `true` or `false` and the arrow has to
 *   say which.
 * - **a published process**, offered only for a step that can actually take one
 *   (`for_each` runs one per item). That is not an arrow on this canvas, so it
 *   is wired by writing the step's own process field instead — the incoming
 *   arrow, which still delivers the list to iterate, is left alone.
 *
 * The raw combined-input view is a debugging aid, not a UX choice for normal
 * editing, so it is deliberately not offered here.
 */
export default function StepInput({
  processId,
  stepId,
  fields,
  onAssign,
  steps = [],
  processes = [],
  connectedTo = TRIGGER,
  onConnect,
  processField = null,
  processValue = '',
  onPickProcess,
}) {
  const [data, setData] = useState(null)
  const [error, setError] = useState('')
  // `connectedTo` arrives already in the select's own vocabulary — see parseStep
  const [choice, setChoice] = useState(processField && processValue ? `process:${processValue}` : connectedTo)
  const [target, setTarget] = useState(fields[0] ?? '')

  const load = useCallback(() => {
    if (!processId) {
      setError('Save the process to see the values that reach this step.')
      return
    }
    setError('')
    api
      .get(`/api/processes/${processId}/steps/${stepId}/input`)
      .then((answer) => {
        setError('')
        setData(answer)
      })
      /* A step that has not been saved yet is not in the definition the server
         holds, so it has no values to report — which is a note beside the tree,
         not a broken panel. Where the work comes from is answered by the canvas
         and stays editable either way. */
      .catch((err) =>
        setError(
          err.status === 404 ? 'Save the process to see the values that reach this step.' : String(err.message),
        ),
      )
  }, [processId, stepId])

  useEffect(() => {
    load()
  }, [load])

  useEffect(() => {
    if (!fields.includes(target)) setTarget(fields[0] ?? '')
  }, [fields, target])

  /* The canvas is the authority on what feeds this step, so a connection made
     out there (dragging an edge, deleting one) moves this selection too —
     except while a process is selected, which is a view of something the graph
     does not draw. */
  useEffect(() => {
    setChoice((current) => (current.startsWith('process:') ? current : connectedTo))
  }, [connectedTo])

  if (!data && !error) {
    return (
      <div className="panel">
        <div className="skeleton h-32" />
      </div>
    )
  }

  const sources = data?.sources ?? []
  const pickedProcess = choice.startsWith('process:')
    ? processes.find((process) => process.id === choice.slice('process:'.length))
    : null
  const picked = parseStep(choice)
  const pickedStepId = picked?.id ?? null
  const selected = picked
    ? sources.find((entry) => entry.step_id === picked.id && entry.source_port === picked.port)
    : null
  const pickedStep = pickedStepId ? steps.find((step) => step.id === pickedStepId) : null

  let shown
  let basePath = ''
  let label = 'input'
  if (pickedProcess) {
    shown = undefined
    label = pickedProcess.name
  } else if (!pickedStepId) {
    shown = data?.trigger
    basePath = '{{ trigger'
    label = 'trigger'
  } else if (selected) {
    shown = selected.data
    basePath =
      selected.source_port === 'main'
        ? `{{ steps.${selected.reference}.output`
        : `{{ steps.${selected.reference}.outputs.${selected.source_port}`
    label = selected.label
  } else {
    label = pickedStep?.label ?? 'input'
  }

  const change = (value) => {
    setChoice(value)
    const step = parseStep(value)
    if (value.startsWith('process:')) onPickProcess?.(value.slice('process:'.length))
    else if (step) onConnect?.(step.id, step.port)
    else onConnect?.(TRIGGER)
  }

  const pick = (path) => {
    if (!target) return
    onAssign(target, `${path} }}`)
  }

  return (
    <div className="panel">
      <div className="panel-title">
        Input
        <button
          className="btn btn-ghost btn-icon btn-sm ml-auto"
          onClick={load}
          aria-label="Reload input data"
          title="Reload"
        >
          <RefreshCw size={13} />
        </button>
      </div>

      <p className="hint mb-2">
        {error ? (
          error
        ) : data.run_id ? (
          <>
            Values from run{' '}
            <code className="code" title={data.run_id}>
              {shortId(data.run_id)}
            </code>
            {data.run_started_at && ` · ${absoluteTime(data.run_started_at)}`}
          </>
        ) : (
          'No run recorded yet — run the process once to capture real values.'
        )}
      </p>

      <select className="select" aria-label="Input source" value={choice} onChange={(event) => change(event.target.value)}>
        <optgroup label="This process">
          <option value={TRIGGER}>Trigger data</option>
        </optgroup>
        {steps.length > 0 && (
          <optgroup label="Steps">
            {steps.flatMap(sourceOptions).map((option) => (
              <option key={option.value} value={option.value}>
                {option.label}
              </option>
            ))}
          </optgroup>
        )}
        {processField && processes.length > 0 && (
          <optgroup label="Processes">
            {processes.map((process) => (
              <option key={process.id} value={`process:${process.id}`}>
                {process.name}
              </option>
            ))}
          </optgroup>
        )}
      </select>

      <p className="hint mt-1.5 flex items-start gap-1.5">
        <Info size={12} className="mt-px shrink-0" aria-hidden="true" />
        {pickedProcess ? (
          <span>
            Each item is handed to <strong className="font-semibold text-fg">{pickedProcess.name}</strong> as{' '}
            <code className="code">{'{{ trigger.item }}'}</code>, with its position as{' '}
            <code className="code">{'{{ trigger.index }}'}</code>.
            {pickedProcess.latest_version
              ? ` Version ${pickedProcess.latest_version} is what will run.`
              : ' It has never been published, so publish it before this runs.'}
          </span>
        ) : !pickedStepId ? (
          sources.length === 0 ? (
            <span>Connected to the trigger box, so this step receives the run&apos;s trigger payload.</span>
          ) : (
            <span>Choosing this re-points the incoming arrow at the trigger box.</span>
          )
        ) : selected ? (
          selected.has_data ? (
            <span>The arrow on the canvas comes from here.</span>
          ) : (
            <span>
              This upstream step {selected.status ? `was ${selected.status}` : 'has not run'} in that run, so no value
              was delivered.
            </span>
          )
        ) : (
          <span>Arrow re-connected — save the process to load the values this step delivers.</span>
        )}
      </p>

      <div className="mt-2 max-h-80 overflow-auto rounded-md border border-line bg-surface-2 p-2">
        <JsonTree label={label} data={shown} basePath={basePath} onPick={pick} />
      </div>

      {fields.length > 0 && (
        <div className="mt-2 flex items-center gap-2">
          <span className="hint shrink-0">Click a value to assign it to</span>
          <select
            className="select min-w-0 flex-1 py-1 text-xs"
            aria-label="Field to assign to"
            value={target}
            onChange={(event) => setTarget(event.target.value)}
          >
            {fields.map((field) => (
              <option key={field} value={field}>
                {field}
              </option>
            ))}
          </select>
        </div>
      )}
    </div>
  )
}
