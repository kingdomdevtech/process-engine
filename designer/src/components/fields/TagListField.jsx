import { useId, useState } from 'react'
import { Plus, X } from 'lucide-react'

/**
 * One chip per entry, for the list fields — recipients, attachments, column
 * names, procedure arguments.
 *
 * These used to be a JSON textarea, which meant sending an email required
 * typing `["ops@example.com"]`, brackets and quotes included. Entries are
 * added by typing and pressing Enter; pasting a comma- or newline-separated
 * list splits it into chips.
 *
 * `suggestions` offers known values as browser autocomplete without ever
 * restricting what can be typed — the notification recipient list uses it to
 * offer teammates by name.
 */

const SEPARATORS = /[,;\n\t]+/
const LOOKS_LIKE_EMAIL = /^[^\s@]+@[^\s@]+\.[^\s@]+$/

/** A value the user assigned with ƒx resolves at run time — never flag it. */
const isExpression = (text) => text.includes('{{')

function chipLabel(item) {
  if (typeof item === 'string') return item
  if (item && typeof item === 'object' && typeof item.key === 'string') return item.key
  return JSON.stringify(item)
}

export default function TagListField({
  value,
  onCommit,
  hints = {},
  placeholder,
  id,
  describedBy,
  suggestions = [],
}) {
  const items = Array.isArray(value) ? value : []
  const [draft, setDraft] = useState('')
  const listId = `${useId()}-options`
  const unused = suggestions.filter((option) => !items.includes(option))

  const commit = (next) => onCommit(next.length ? next : undefined)

  const add = (raw) => {
    const existing = new Set(items.filter((item) => typeof item === 'string'))
    const fresh = []
    for (const part of String(raw).split(SEPARATORS)) {
      const entry = part.trim()
      if (!entry || existing.has(entry)) continue
      existing.add(entry)
      fresh.push(entry)
    }
    if (fresh.length) commit([...items, ...fresh])
    setDraft('')
  }

  const removeAt = (index) => commit(items.filter((_, position) => position !== index))

  const onKeyDown = (event) => {
    if (event.key === 'Enter' || (event.key === ',' && hints.widget !== 'tags')) {
      event.preventDefault()
      add(draft)
    } else if (event.key === 'Backspace' && !draft && items.length) {
      removeAt(items.length - 1)
    }
  }

  return (
    <div>
      {items.length > 0 && (
        <ul className="mb-1.5 flex flex-wrap gap-1">
          {items.map((item, index) => {
            const label = chipLabel(item)
            const suspect =
              hints.widget === 'emails' && typeof item === 'string' && !isExpression(label) && !LOOKS_LIKE_EMAIL.test(label)
            return (
              <li
                key={`${label}:${index}`}
                className={`inline-flex max-w-full items-center gap-1 rounded-full py-0.5 pl-2.5 pr-1 text-[11px] font-medium ${
                  suspect ? 'bg-warn-bg text-warn-fg' : 'bg-surface-3 text-fg'
                }`}
                title={suspect ? `“${label}” does not look like an email address` : label}
              >
                <span className="truncate">{label}</span>
                <button
                  type="button"
                  className="grid size-4 shrink-0 place-items-center rounded-full text-fg-subtle transition-colors hover:bg-bad-bg hover:text-bad-fg"
                  aria-label={`Remove ${label}`}
                  onClick={() => removeAt(index)}
                >
                  <X size={11} />
                </button>
              </li>
            )
          })}
        </ul>
      )}

      <div className="flex gap-1.5">
        <input
          id={id}
          aria-describedby={describedBy}
          className="input"
          type="text"
          value={draft}
          placeholder={placeholder}
          list={unused.length ? listId : undefined}
          onChange={(event) => setDraft(event.target.value)}
          onKeyDown={onKeyDown}
          onBlur={() => add(draft)} // clicking straight to another field must not lose what was typed
        />
        {unused.length > 0 && (
          <datalist id={listId}>
            {unused.map((option) => (
              <option key={option} value={option} />
            ))}
          </datalist>
        )}
        <button
          type="button"
          className="btn btn-sm shrink-0"
          disabled={!draft.trim()}
          onClick={() => add(draft)}
        >
          <Plus size={13} />
          {hints.addLabel ?? 'Add'}
        </button>
      </div>
    </div>
  )
}
