import { useEffect, useRef, useState } from 'react'
import { Search, Wand2 } from 'lucide-react'
import { api } from '../api.js'
import Modal from './ui/Modal.jsx'

/**
 * "Assign from a previous step" — lists the trigger payload and every upstream
 * step's outputs as ready-to-insert expressions, with sample values taken from
 * the most recent run.
 */
export default function DataPicker({ processId, stepId, fieldName, onPick, onClose }) {
  const [groups, setGroups] = useState(null)
  const [error, setError] = useState('')
  const [query, setQuery] = useState('')
  const searchRef = useRef(null)

  useEffect(() => {
    if (!processId) {
      setError('Save the process first so its steps can be resolved.')
      return
    }
    api
      .get(`/api/processes/${processId}/steps/${stepId}/picker`)
      .then((data) => setGroups(data.groups))
      .catch((err) => setError(String(err.message)))
  }, [processId, stepId])

  const term = query.trim().toLowerCase()
  const visible = (groups ?? [])
    .map((group) => ({
      ...group,
      fields: group.fields.filter(
        (field) => !term || field.path.toLowerCase().includes(term) || group.label.toLowerCase().includes(term),
      ),
    }))
    .filter((group) => group.fields.length > 0)

  return (
    <Modal
      open
      onClose={onClose}
      size="md"
      title={`Assign to “${fieldName}”`}
      description="Pick a value from the trigger or an earlier step. Sample data comes from the latest run."
      initialFocus={searchRef}
      icon={
        <span className="grid size-9 shrink-0 place-items-center rounded-lg bg-brand-soft text-brand-text" aria-hidden="true">
          <Wand2 size={18} />
        </span>
      }
      footer={
        <>
          <span className="mr-auto text-[11px] text-fg-subtle">
            Inserted as an expression — it resolves when the step runs.
          </span>
          <button className="btn" onClick={onClose}>
            Cancel
          </button>
        </>
      }
    >
      <div className="relative mb-3">
        <Search
          size={15}
          className="pointer-events-none absolute left-2.5 top-1/2 -translate-y-1/2 text-fg-subtle"
          aria-hidden="true"
        />
        <input
          ref={searchRef}
          className="input pl-8"
          placeholder="Filter fields…"
          aria-label="Filter fields"
          value={query}
          onChange={(event) => setQuery(event.target.value)}
        />
      </div>

      {error && (
        <p className="error-text" role="alert">
          {error}
        </p>
      )}
      {!groups && !error && <p className="muted">Loading…</p>}
      {groups && visible.length === 0 && (
        <p className="muted">
          {term
            ? `No field matches “${query}”.`
            : 'Nothing to pick yet — connect this step to an earlier one, or run the process once to capture sample data.'}
        </p>
      )}

      {visible.map((group) => (
        <div key={group.key} className="mb-3 last:mb-0">
          <h4 className="section-label flex items-center gap-2">
            {group.label}
            {group.plugin && <code className="code font-normal normal-case tracking-normal">{group.plugin}</code>}
          </h4>
          <div className="space-y-0.5">
            {group.fields.map((field) => (
              <button
                key={field.path}
                className="flex w-full items-center gap-3 rounded-md px-2 py-1.5 text-left transition-colors hover:bg-surface-2"
                onClick={() => {
                  onPick({ path: field.path, type: field.type })
                  onClose()
                }}
              >
                <code className="min-w-0 truncate font-mono text-[11.5px] text-brand-text">{field.path}</code>
                <span className="ml-auto max-w-[45%] shrink-0 truncate text-[11px] text-fg-subtle">
                  {field.preview}
                </span>
              </button>
            ))}
          </div>
        </div>
      ))}
    </Modal>
  )
}
