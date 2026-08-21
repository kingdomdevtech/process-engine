import { useEffect, useMemo, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import {
  Compass,
  CornerDownLeft,
  LayoutDashboard,
  ListChecks,
  Moon,
  Plus,
  Search,
  Lock,
  Settings,
  Sun,
  Workflow,
} from 'lucide-react'
import { api, getUser } from '../api.js'
import { usePageCommands } from '../commands.js'
import { useTheme } from '../theme.js'
import { startTour } from '../tour.js'

/**
 * Ctrl/⌘+K command palette.
 *
 * Once an operator has more than a screenful of processes, hunting through the
 * dashboard is the slowest path to any of them. This is the fast one: type a
 * few letters, Enter. It indexes navigation, actions and every process by name
 * and folder, plus whatever the open page registers for itself — see
 * `commands.js`.
 */
export default function CommandPalette({ open, onClose }) {
  const [query, setQuery] = useState('')
  const [active, setActive] = useState(0)
  const [processes, setProcesses] = useState([])
  const navigate = useNavigate()
  const { resolved, setTheme } = useTheme()
  const page = usePageCommands()
  const listRef = useRef(null)

  useEffect(() => {
    if (!open) return
    setQuery('')
    setActive(0)
    api.get('/api/processes').then(setProcesses).catch(() => setProcesses([]))
  }, [open])

  const commands = useMemo(() => {
    const base = [
      { id: 'new', group: 'Actions', label: 'New process', icon: Plus, keywords: 'create add',
        run: () => navigate('/app/processes/new') },
      { id: 'dashboard', group: 'Go to', label: 'Dashboard', icon: LayoutDashboard, keywords: 'home processes',
        run: () => navigate('/app') },
      { id: 'runs', group: 'Go to', label: 'Runs', icon: ListChecks, keywords: 'history executions',
        run: () => navigate('/app/runs') },
      { id: 'secrets', group: 'Go to', label: 'Secrets', icon: Lock, keywords: 'credentials passwords keys',
        run: () => navigate('/app/secrets') },
      {
        id: 'tour',
        group: 'Actions',
        label: 'Take the guided tour',
        icon: Compass,
        keywords: 'tour help onboarding walkthrough intro getting started learn',
        run: () => startTour(),
      },
      {
        id: 'theme',
        group: 'Actions',
        label: resolved === 'dark' ? 'Switch to light theme' : 'Switch to dark theme',
        icon: resolved === 'dark' ? Sun : Moon,
        keywords: 'theme dark light appearance',
        run: () => setTheme(resolved === 'dark' ? 'light' : 'dark'),
      },
    ]
    // theme and the tour are above: every user sets those for themselves
    if (getUser()?.role === 'admin') {
      base.push({ id: 'settings', group: 'Go to', label: 'Settings', icon: Settings,
        keywords: 'users plugins mail notifications files deployment',
        run: () => navigate('/app/settings') })
    }
    const items = processes.map((process) => ({
      id: `p-${process.id}`,
      group: 'Processes',
      label: process.name,
      hint: process.folder || 'Uncategorized',
      icon: Workflow,
      keywords: process.folder ?? '',
      run: () => navigate(`/app/processes/${process.id}`),
    }))
    // page commands lead: they act on what is already on screen
    return [...page, ...base, ...items]
  }, [page, processes, navigate, resolved, setTheme])

  const matches = useMemo(() => {
    const term = query.trim().toLowerCase()
    if (!term) return commands
    return commands.filter((command) =>
      `${command.label} ${command.hint ?? ''} ${command.keywords ?? ''}`.toLowerCase().includes(term),
    )
  }, [commands, query])

  useEffect(() => {
    setActive(0)
  }, [query])

  useEffect(() => {
    listRef.current?.querySelector('[data-active="true"]')?.scrollIntoView({ block: 'nearest' })
  }, [active, matches])

  if (!open) return null

  const choose = (command) => {
    onClose()
    command?.run()
  }

  const onKeyDown = (event) => {
    if (event.key === 'ArrowDown') {
      event.preventDefault()
      setActive((index) => (index + 1) % Math.max(matches.length, 1))
    } else if (event.key === 'ArrowUp') {
      event.preventDefault()
      setActive((index) => (index - 1 + matches.length) % Math.max(matches.length, 1))
    } else if (event.key === 'Enter') {
      event.preventDefault()
      choose(matches[active])
    } else if (event.key === 'Escape') {
      onClose()
    }
  }

  let lastGroup = null

  return (
    <div
      className="animate-fade fixed inset-0 z-50 flex items-start justify-center bg-overlay p-4 pt-[12vh] backdrop-blur-[2px]"
      onMouseDown={(event) => event.target === event.currentTarget && onClose()}
    >
      <div
        role="dialog"
        aria-modal="true"
        aria-label="Command palette"
        className="animate-zoom flex max-h-[60vh] w-full max-w-xl flex-col overflow-hidden rounded-xl border border-line bg-raised shadow-xl"
      >
        <div className="flex items-center gap-2.5 border-b border-line px-4">
          <Search size={16} className="shrink-0 text-fg-subtle" aria-hidden="true" />
          <input
            autoFocus
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            onKeyDown={onKeyDown}
            placeholder="Search processes or jump to…"
            aria-label="Search processes or jump to a page"
            aria-controls="pe-command-list"
            className="w-full bg-transparent py-3.5 text-sm outline-none placeholder:text-fg-subtle"
          />
          <kbd className="kbd">Esc</kbd>
        </div>

        <div id="pe-command-list" ref={listRef} role="listbox" className="min-h-0 flex-1 overflow-y-auto p-1.5">
          {matches.length === 0 && (
            <p className="px-3 py-8 text-center text-[13px] text-fg-muted">No matches for “{query}”.</p>
          )}
          {matches.map((command, index) => {
            const Icon = command.icon
            const header = command.group !== lastGroup ? command.group : null
            lastGroup = command.group
            return (
              <div key={command.id}>
                {header && (
                  <div className="px-2.5 pb-1 pt-2 text-[10px] font-bold uppercase tracking-wider text-fg-subtle">
                    {header}
                  </div>
                )}
                <button
                  role="option"
                  aria-selected={index === active}
                  data-active={index === active}
                  className={`flex w-full items-center gap-2.5 rounded-md px-2.5 py-2 text-left text-[13px] ${
                    index === active ? 'bg-brand-soft text-brand-text' : 'text-fg hover:bg-surface-2'
                  }`}
                  onMouseEnter={() => setActive(index)}
                  onClick={() => choose(command)}
                >
                  <Icon size={15} className="shrink-0 opacity-70" aria-hidden="true" />
                  <span className="min-w-0 flex-1 truncate">{command.label}</span>
                  {command.hint && <span className="shrink-0 text-[11px] text-fg-subtle">{command.hint}</span>}
                  {index === active && <CornerDownLeft size={13} className="shrink-0 opacity-60" aria-hidden="true" />}
                </button>
              </div>
            )
          })}
        </div>

        <div className="flex items-center gap-3 border-t border-line bg-surface-2 px-4 py-2 text-[11px] text-fg-subtle">
          <span className="flex items-center gap-1">
            <kbd className="kbd">↑</kbd>
            <kbd className="kbd">↓</kbd> navigate
          </span>
          <span className="flex items-center gap-1">
            <kbd className="kbd">↵</kbd> open
          </span>
        </div>
      </div>
    </div>
  )
}
