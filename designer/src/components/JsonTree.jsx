import { useState } from 'react'
import { ChevronDown, ChevronRight } from 'lucide-react'

/**
 * Collapsible JSON viewer where every leaf is clickable — clicking copies the
 * expression that addresses it, so you can see a real value and wire it into a
 * config field in one move.
 */
function typeOf(value) {
  if (value === null) return 'null'
  if (Array.isArray(value)) return 'array'
  return typeof value
}

const TONE = {
  string: 'text-[var(--tok-string)]',
  number: 'text-[var(--tok-number)]',
  boolean: 'text-[var(--tok-boolean)]',
  null: 'italic text-fg-subtle',
}

function Leaf({ label, value, path, onPick }) {
  const kind = typeOf(value)
  const rendered = kind === 'string' ? `"${value}"` : String(value)
  const clickable = Boolean(onPick && path)
  return (
    <div className="flex items-baseline gap-1.5">
      <span className="shrink-0 font-semibold text-fg-muted after:text-fg-subtle after:content-[':']">{label}</span>
      <button
        type="button"
        className={`min-w-0 break-all rounded px-1 text-left ${TONE[kind] ?? 'text-fg'} ${
          clickable ? 'hover:bg-brand-soft hover:outline hover:outline-1 hover:outline-brand' : 'cursor-default'
        }`}
        title={clickable ? `Use ${path}` : undefined}
        disabled={!clickable}
        onClick={() => onPick?.(path)}
      >
        {rendered}
      </button>
    </div>
  )
}

function Node({ label, value, path, onPick, depth }) {
  const [open, setOpen] = useState(depth < 2)
  const kind = typeOf(value)

  if (kind !== 'object' && kind !== 'array') {
    return <Leaf label={label} value={value} path={path} onPick={onPick} />
  }

  const entries = kind === 'array' ? value.map((item, index) => [String(index), item]) : Object.entries(value)

  return (
    <div>
      <button
        type="button"
        className="flex items-center gap-1 text-fg-muted hover:text-fg"
        onClick={() => setOpen(!open)}
        aria-expanded={open}
      >
        {open ? <ChevronDown size={11} className="text-fg-subtle" /> : <ChevronRight size={11} className="text-fg-subtle" />}
        <span className="font-semibold after:text-fg-subtle after:content-[':']">{label}</span>
        <span className="text-fg-subtle">{kind === 'array' ? `[${entries.length}]` : `{${entries.length}}`}</span>
      </button>
      {open && (
        <div className="ml-1 border-l border-dotted border-line pl-3">
          {entries.length === 0 && <span className="text-fg-subtle">empty</span>}
          {entries.map(([key, item]) => (
            <Node
              key={key}
              label={key}
              value={item}
              path={path ? `${path}.${key}` : ''}
              onPick={onPick}
              depth={depth + 1}
            />
          ))}
        </div>
      )}
    </div>
  )
}

export default function JsonTree({ label = 'value', data, basePath = '', onPick }) {
  if (data === undefined) return <p className="muted">No data.</p>
  return (
    <div className="font-mono text-[11.5px] leading-6">
      <Node label={label} value={data} path={basePath} onPick={onPick} depth={0} />
    </div>
  )
}
