import { useEffect, useRef, useState } from 'react'
import { Plus, X } from 'lucide-react'

/**
 * A row of name/value inputs per entry, for the dictionary fields — HTTP
 * headers, SQL parameters, the fields a Transform step sets.
 *
 * Rows are held locally so a name can be retyped without the object being
 * rebuilt (and the focus lost) on every keystroke; the config is rewritten on
 * each change, and rows with a blank name are simply left out of it.
 */

let nextRowId = 0
const makeRow = (key, value) => ({ id: (nextRowId += 1), key, value })

const toRows = (value) =>
  value && typeof value === 'object' && !Array.isArray(value)
    ? Object.entries(value).map(([key, entry]) => makeRow(key, entry))
    : []

const toObject = (rows) => {
  const out = {}
  for (const row of rows) {
    const key = row.key.trim()
    if (key) out[key] = row.value
  }
  return out
}

/** What goes in the input: strings as-is, everything else as its JSON form. */
const asText = (value) => (typeof value === 'string' ? value : JSON.stringify(value) ?? '')

export default function KeyValueField({ value, onCommit, spec = {}, hints = {}, pickExpression, id, describedBy }) {
  const [rows, setRows] = useState(() => toRows(value))
  const committed = useRef(value)

  // dict[str, str] keeps every value a string; dict[str, Any] lets `250` mean the number.
  const typed = spec.additionalProperties?.type !== 'string'
  const parse = (text) => {
    if (!typed) return text
    try {
      return JSON.parse(text)
    } catch {
      return text // an expression, or prose — both stay text
    }
  }

  /* The config can also be rewritten from outside: the JSON tab replaces it
     wholesale, and undo/redo rolls it back. Adopt those, ignore our own echo. */
  useEffect(() => {
    if (JSON.stringify(value ?? null) === JSON.stringify(committed.current ?? null)) return
    committed.current = value
    setRows(toRows(value))
  }, [value])

  const push = (next) => {
    setRows(next)
    const object = toObject(next)
    committed.current = Object.keys(object).length ? object : undefined
    onCommit(committed.current)
  }

  const update = (id, patch) => push(rows.map((row) => (row.id === id ? { ...row, ...patch } : row)))

  /* ƒx on the whole field would swap the object for a string, so each value
     carries its own — the expression is appended to what that row already holds. */
  const appendTo = (id, expression) =>
    setRows((current) => {
      const next = current.map((row) =>
        row.id === id ? { ...row, value: `${asText(row.value)}${expression}` } : row,
      )
      const object = toObject(next)
      committed.current = Object.keys(object).length ? object : undefined
      onCommit(committed.current)
      return next
    })

  return (
    <div>
      {rows.length > 0 && (
        <div className="mb-1.5 space-y-1">
          <div className="flex gap-1.5 px-0.5 text-[10px] font-semibold uppercase tracking-wide text-fg-subtle">
            <span className="w-[38%]">{hints.keyLabel ?? 'Name'}</span>
            <span>{hints.valueLabel ?? 'Value'}</span>
          </div>
          {rows.map((row) => (
            <div key={row.id} className="flex items-center gap-1.5">
              <input
                className="input w-[38%] shrink-0"
                type="text"
                value={row.key}
                aria-label={hints.keyLabel ?? 'Name'}
                onChange={(event) => update(row.id, { key: event.target.value })}
              />
              <input
                className="input"
                type="text"
                value={asText(row.value)}
                aria-label={hints.valueLabel ?? 'Value'}
                onChange={(event) => update(row.id, { value: parse(event.target.value) })}
              />
              {pickExpression && (
                <button
                  type="button"
                  className="shrink-0 rounded border border-line bg-surface px-1 py-px text-[10px] font-semibold text-brand-text transition-colors hover:border-brand hover:bg-brand-soft"
                  aria-label={`Insert a value from an earlier step into ${row.key || 'this entry'}`}
                  title="Insert a value from an earlier step"
                  onClick={() => pickExpression(row.key || 'value', (expression) => appendTo(row.id, expression))}
                >
                  ƒx
                </button>
              )}
              <button
                type="button"
                className="grid size-6 shrink-0 place-items-center rounded text-fg-subtle transition-colors hover:bg-bad-bg hover:text-bad-fg"
                aria-label={`Remove ${row.key || 'entry'}`}
                onClick={() => push(rows.filter((entry) => entry.id !== row.id))}
              >
                <X size={13} />
              </button>
            </div>
          ))}
        </div>
      )}

      <button
        type="button"
        id={id}
        aria-describedby={describedBy}
        className="btn btn-sm"
        onClick={() => setRows([...rows, makeRow('', '')])} // nothing to commit until it has a name
      >
        <Plus size={13} />
        {hints.addLabel ?? 'Add'}
      </button>
    </div>
  )
}
