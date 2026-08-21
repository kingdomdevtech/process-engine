import { useCallback, useEffect, useState } from 'react'
import { Info, RefreshCw } from 'lucide-react'
import { api } from '../api.js'
import { absoluteTime, shortId } from '../format.js'
import JsonTree from './JsonTree.jsx'

const TRIGGER = '__trigger__'
const EFFECTIVE = '__effective__'

/**
 * What this step actually receives: the trigger payload and each connected
 * upstream step's recorded output, with real values. Clicking any value assigns
 * the expression for it to the selected config field.
 */
export default function StepInput({ processId, stepId, fields, onAssign }) {
  const [data, setData] = useState(null)
  const [error, setError] = useState('')
  const [source, setSource] = useState(EFFECTIVE)
  const [target, setTarget] = useState(fields[0] ?? '')

  const load = useCallback(() => {
    if (!processId) {
      setError('Save the process first to inspect its data.')
      return
    }
    setError('')
    api
      .get(`/api/processes/${processId}/steps/${stepId}/input`)
      .then(setData)
      .catch((err) => setError(String(err.message)))
  }, [processId, stepId])

  useEffect(() => {
    load()
  }, [load])

  useEffect(() => {
    if (!fields.includes(target)) setTarget(fields[0] ?? '')
  }, [fields, target])

  if (error) {
    return (
      <div className="panel">
        <p className="error-text">{error}</p>
      </div>
    )
  }
  if (!data) {
    return (
      <div className="panel">
        <div className="skeleton h-32" />
      </div>
    )
  }

  const options = [
    { key: EFFECTIVE, label: 'Combined input (what the step receives)' },
    { key: TRIGGER, label: 'Trigger data' },
    ...data.sources.map((entry) => ({
      key: entry.step_id,
      label: `${entry.label}${entry.source_port === 'main' ? '' : ` · ${entry.source_port}`}`,
    })),
  ]

  const selected = data.sources.find((entry) => entry.step_id === source)
  let shown
  let basePath = ''
  let label = 'input'
  if (source === EFFECTIVE) {
    shown = data.effective_input
    basePath = '{{ input'
    label = 'input'
  } else if (source === TRIGGER) {
    shown = data.trigger
    basePath = '{{ trigger'
    label = 'trigger'
  } else if (selected) {
    shown = selected.data
    basePath =
      selected.source_port === 'main'
        ? `{{ steps.${selected.reference}.output`
        : `{{ steps.${selected.reference}.outputs.${selected.source_port}`
    label = selected.label
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
        {data.run_id ? (
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

      <select
        className="select"
        aria-label="Input source"
        value={source}
        onChange={(event) => setSource(event.target.value)}
      >
        {options.map((option) => (
          <option key={option.key} value={option.key}>
            {option.label}
          </option>
        ))}
      </select>

      {data.sources.length === 0 && source === EFFECTIVE && (
        <p className="hint mt-1.5 flex items-start gap-1.5">
          <Info size={12} className="mt-px shrink-0" aria-hidden="true" />
          This step has no incoming connection, so it receives the trigger payload.
        </p>
      )}
      {selected && !selected.has_data && (
        <p className="hint mt-1.5 flex items-start gap-1.5">
          <Info size={12} className="mt-px shrink-0" aria-hidden="true" />
          This upstream step {selected.status ? `was ${selected.status}` : 'has not run'} in that run, so no value was
          delivered.
        </p>
      )}

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
