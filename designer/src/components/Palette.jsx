import { useMemo, useState } from 'react'
import { ChevronDown, ChevronRight, Search, X } from 'lucide-react'
import { PluginIcon } from '../pluginMeta.jsx'

/**
 * The step palette.
 *
 * Dragging is the primary gesture, but every item is also a button: drag-and-drop
 * is not operable by keyboard, so clicking (or Enter) drops the step onto the
 * middle of the canvas instead. Same result, two routes.
 */
export default function Palette({ plugins, onAdd, collapsed, onToggle }) {
  const [query, setQuery] = useState('')
  const [closedGroups, setClosedGroups] = useState(() => new Set())

  const groups = useMemo(() => {
    const term = query.trim().toLowerCase()
    const filtered = plugins.filter(
      (plugin) =>
        !term ||
        plugin.name.toLowerCase().includes(term) ||
        plugin.key.includes(term) ||
        (plugin.description || '').toLowerCase().includes(term),
    )
    const byCategory = new Map()
    for (const plugin of filtered) {
      byCategory.set(plugin.category, [...(byCategory.get(plugin.category) ?? []), plugin])
    }
    return [...byCategory.entries()].sort(([a], [b]) => a.localeCompare(b))
  }, [plugins, query])

  const toggleGroup = (category) =>
    setClosedGroups((current) => {
      const next = new Set(current)
      if (next.has(category)) next.delete(category)
      else next.add(category)
      return next
    })

  if (collapsed) {
    return (
      <aside
        className="flex w-11 shrink-0 flex-col items-center gap-2 border-r border-line bg-surface py-2"
        data-tour="step-palette"
      >
        <button className="btn btn-ghost btn-icon btn-sm" onClick={onToggle} aria-label="Show step palette">
          <ChevronRight size={15} />
        </button>
      </aside>
    )
  }

  return (
    <aside className="flex w-56 shrink-0 flex-col border-r border-line bg-surface" data-tour="step-palette">
      <div className="flex items-center gap-1 border-b border-line p-2">
        <div className="relative min-w-0 flex-1">
          <Search
            size={14}
            className="pointer-events-none absolute left-2 top-1/2 -translate-y-1/2 text-fg-subtle"
            aria-hidden="true"
          />
          <input
            className="input py-1 pl-7 pr-6 text-xs"
            placeholder="Search steps…"
            aria-label="Search steps"
            value={query}
            onChange={(event) => setQuery(event.target.value)}
          />
          {query && (
            <button
              className="absolute right-1 top-1/2 -translate-y-1/2 rounded p-0.5 text-fg-subtle hover:text-fg"
              onClick={() => setQuery('')}
              aria-label="Clear search"
            >
              <X size={13} />
            </button>
          )}
        </div>
        <button className="btn btn-ghost btn-icon btn-sm" onClick={onToggle} aria-label="Hide step palette">
          <ChevronDown size={15} className="-rotate-90" />
        </button>
      </div>

      <div className="min-h-0 flex-1 overflow-y-auto p-2">
        {groups.map(([category, items]) => {
          const closed = closedGroups.has(category)
          return (
            <div key={category} className="mb-2">
              <button
                className="mb-1 flex w-full items-center gap-1 px-1 py-0.5 text-[10px] font-bold uppercase tracking-[0.07em] text-fg-subtle hover:text-fg"
                onClick={() => toggleGroup(category)}
                aria-expanded={!closed}
              >
                {closed ? <ChevronRight size={11} /> : <ChevronDown size={11} />}
                {category}
                <span className="ml-auto font-mono text-[10px] normal-case">{items.length}</span>
              </button>

              {!closed &&
                items.map((plugin) => (
                  <button
                    key={plugin.key}
                    type="button"
                    draggable
                    title={plugin.description}
                    onDragStart={(event) => {
                      event.dataTransfer.setData('application/x-plugin', plugin.key)
                      event.dataTransfer.effectAllowed = 'move'
                    }}
                    onClick={() => onAdd?.(plugin.key)}
                    className="mb-1 flex w-full cursor-grab items-center gap-2 rounded-md border border-line bg-surface p-1.5 text-left transition-colors hover:border-brand hover:bg-surface-2 active:cursor-grabbing"
                  >
                    <PluginIcon plugin={plugin} size={13} className="size-6" />
                    <span className="min-w-0 flex-1">
                      <span className="block truncate text-xs font-semibold">{plugin.name}</span>
                      <span className="block truncate font-mono text-[10px] text-fg-subtle">{plugin.key}</span>
                    </span>
                  </button>
                ))}
            </div>
          )
        })}

        {groups.length === 0 && (
          <p className="px-1 py-6 text-center text-xs text-fg-muted">No step matches “{query}”.</p>
        )}
      </div>

      <p className="hint border-t border-line px-3 py-2">Drag onto the canvas, or click to add.</p>
    </aside>
  )
}
