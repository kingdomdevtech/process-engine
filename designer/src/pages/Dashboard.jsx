import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import {
  CheckCircle2,
  ChevronDown,
  ChevronRight,
  Compass,
  Copy,
  FolderClosed,
  FolderOpen,
  LayoutGrid,
  MoreHorizontal,
  Play,
  Plus,
  Rows3,
  Search,
  Share2,
  Trash2,
  Workflow,
  XCircle,
} from 'lucide-react'

import { api, getUser } from '../api.js'
import { relativeTime, absoluteTime, shortId } from '../format.js'
import { startTour } from '../tour.js'
import AppShell from '../components/AppShell.jsx'
import EmptyState from '../components/EmptyState.jsx'
import ShareDialog from '../components/ShareDialog.jsx'
import { useToast } from '../components/Toast.jsx'
import Menu, { MenuItem, MenuSeparator } from '../components/ui/Menu.jsx'
import StatusBadge from '../components/ui/StatusBadge.jsx'
import { useDialogs } from '../components/ui/Dialogs.jsx'

const UNCATEGORIZED = 'Uncategorized'
const COLLAPSED_KEY = 'pe_collapsed_folders'
const VIEW_KEY = 'pe_process_view'

function loadCollapsed() {
  try {
    return new Set(JSON.parse(localStorage.getItem(COLLAPSED_KEY)) ?? [])
  } catch {
    return new Set()
  }
}

/** A headline number with the icon that identifies it elsewhere in the app. */
function Stat({ label, value, icon: Icon, tint = 'text-fg-subtle bg-surface-2', hint }) {
  return (
    <div className="card flex items-center gap-3 p-4">
      <span className={`grid size-9 shrink-0 place-items-center rounded-lg ${tint}`} aria-hidden="true">
        <Icon size={17} />
      </span>
      <div className="min-w-0">
        <div className="text-[11px] font-semibold uppercase tracking-[0.05em] text-fg-subtle">{label}</div>
        <div className="tabular text-xl font-bold leading-tight">{value}</div>
      </div>
      {hint && <span className="ml-auto shrink-0 text-[11px] text-fg-subtle">{hint}</span>}
    </div>
  )
}

export default function Dashboard() {
  const [processes, setProcesses] = useState(null)
  const [runs, setRuns] = useState([])
  const [query, setQuery] = useState('')
  const [folderFilter, setFolderFilter] = useState('')
  const [collapsed, setCollapsed] = useState(loadCollapsed)
  const [view, setView] = useState(() => localStorage.getItem(VIEW_KEY) ?? 'grid')
  const navigate = useNavigate()
  const toast = useToast()
  const dialogs = useDialogs()
  const searchRef = useRef(null)
  const [sharing, setSharing] = useState(null)
  const me = getUser()?.username

  const load = useCallback(async () => {
    try {
      const list = await api.get('/api/processes')
      setProcesses(list)
      const recent = await Promise.all(
        list.slice(0, 8).map((process) =>
          api.get(`/api/processes/${process.id}/runs`).then(
            (entries) => entries.map((entry) => ({ ...entry, process_name: process.name })),
            () => [],
          ),
        ),
      )
      setRuns(recent.flat().sort((a, b) => b.created_at.localeCompare(a.created_at)))
    } catch (error) {
      toast.error(String(error.message))
      setProcesses([])
    }
  }, [toast])

  useEffect(() => {
    load()
  }, [load])

  /* "/" focuses search — the convention in every list-heavy admin tool. */
  useEffect(() => {
    const onKeyDown = (event) => {
      if (event.key !== '/' || event.ctrlKey || event.metaKey) return
      const target = event.target
      if (target instanceof HTMLElement && ['INPUT', 'TEXTAREA', 'SELECT'].includes(target.tagName)) return
      event.preventDefault()
      searchRef.current?.focus()
    }
    window.addEventListener('keydown', onKeyDown)
    return () => window.removeEventListener('keydown', onKeyDown)
  }, [])

  const setViewMode = (next) => {
    setView(next)
    localStorage.setItem(VIEW_KEY, next)
  }

  const toggleFolder = (folder) => {
    setCollapsed((current) => {
      const next = new Set(current)
      if (next.has(folder)) next.delete(folder)
      else next.add(folder)
      localStorage.setItem(COLLAPSED_KEY, JSON.stringify([...next]))
      return next
    })
  }

  const act = (promise, okMessage) =>
    promise
      .then(() => {
        if (okMessage) toast.ok(okMessage)
        load()
      })
      .catch((error) => toast.error(String(error.message)))

  const remove = async (process) => {
    const ok = await dialogs.confirm({
      title: `Delete “${process.name}”?`,
      body: 'This removes the process and every published version of it. Run history for those versions is deleted with them. This cannot be undone.',
      confirmLabel: 'Delete process',
      tone: 'danger',
    })
    if (ok) act(api.del(`/api/processes/${process.id}`), `Deleted ${process.name}`)
  }

  const move = async (process) => {
    const next = await dialogs.prompt({
      title: `Move “${process.name}”`,
      label: 'Folder',
      placeholder: UNCATEGORIZED,
      defaultValue: process.folder ?? '',
      options: allFolders.filter(Boolean),
      hint: `Leave blank to move it to ${UNCATEGORIZED}.`,
      confirmLabel: 'Move',
    })
    if (next !== null) act(api.put(`/api/processes/${process.id}/folder`, { folder: next }), 'Moved')
  }

  const duplicate = async (process) => {
    try {
      const clone = await api.post(`/api/processes/${process.id}/clone`)
      // the copy is an unpublished draft; the server disables its triggers so it
      // cannot take over the original's schedule or webhook
      const note = clone.triggers.length ? ' — its triggers are disabled' : ''
      toast.ok(`Created “${clone.name}”${note}`, {
        action: { label: 'Open', onClick: () => navigate(`/app/processes/${clone.id}`) },
      })
      load()
    } catch (error) {
      toast.error(String(error.message))
    }
  }

  const runNow = async (process) => {
    const ok = await dialogs.confirm({
      title: `Run “${process.name}” now?`,
      body: `This executes published version ${process.latest_version} immediately, with all of its side effects.`,
      confirmLabel: 'Run now',
    })
    if (!ok) return
    try {
      const run = await api.post(`/api/processes/${process.id}/run`, {})
      toast.ok(`Run ${shortId(run.id)} ${run.status}`, {
        action: { label: 'View run', onClick: () => navigate(`/app/runs?run=${run.id}`) },
      })
      load()
    } catch (error) {
      toast.error(String(error.message))
    }
  }

  const folders = useMemo(() => {
    const term = query.trim().toLowerCase()
    const matching = (processes ?? []).filter((process) => {
      const inFolder = !folderFilter || (process.folder || '') === folderFilter
      const matches =
        !term ||
        process.name.toLowerCase().includes(term) ||
        (process.folder || '').toLowerCase().includes(term)
      return inFolder && matches
    })
    const grouped = new Map()
    for (const process of matching) {
      const key = process.folder || UNCATEGORIZED
      grouped.set(key, [...(grouped.get(key) ?? []), process])
    }
    // named folders alphabetically, Uncategorized last
    return [...grouped.entries()].sort(([a], [b]) => {
      if (a === UNCATEGORIZED) return 1
      if (b === UNCATEGORIZED) return -1
      return a.localeCompare(b)
    })
  }, [processes, query, folderFilter])

  const allFolders = useMemo(() => {
    const set = new Set((processes ?? []).map((process) => process.folder || ''))
    return [...set].sort((a, b) => (a === '' ? 1 : b === '' ? -1 : a.localeCompare(b)))
  }, [processes])

  const succeeded = runs.filter((run) => run.status === 'succeeded').length
  const failed = runs.filter((run) => run.status === 'failed').length
  const published = (processes ?? []).filter((process) => process.latest_version > 0).length

  const rowMenu = (process) => (
    <Menu
      label={`Actions for ${process.name}`}
      trigger={
        <span className="btn btn-ghost btn-icon btn-sm" aria-hidden="true">
          <MoreHorizontal size={15} />
        </span>
      }
    >
      <MenuItem icon={<Workflow size={15} />} onClick={() => navigate(`/app/processes/${process.id}`)}>
        Open in designer
      </MenuItem>
      <MenuItem
        icon={<Play size={15} />}
        disabled={!process.latest_version}
        onClick={() => runNow(process)}
      >
        {process.latest_version ? 'Run now' : 'Run now — publish first'}
      </MenuItem>
      <MenuItem icon={<Copy size={15} />} onClick={() => duplicate(process)}>
        Duplicate
      </MenuItem>
      <MenuItem icon={<FolderClosed size={15} />} onClick={() => move(process)}>
        Move to folder…
      </MenuItem>
      <MenuItem icon={<Share2 size={15} />} onClick={() => setSharing(process)}>
        Share…
      </MenuItem>
      <MenuSeparator />
      <MenuItem icon={<Trash2 size={15} />} danger onClick={() => remove(process)}>
        Delete
      </MenuItem>
    </Menu>
  )

  /** Whether this row is shared, and which way round — "shared with me" and
      "I shared this" are different facts and a reader wants to tell them apart. */
  const sharingBadge = (process) => {
    const shared = process.shared_with ?? []
    if (process.created_by && process.created_by !== me) {
      return (
        <span className="badge gap-1" title={`Shared with you by ${process.created_by}`}>
          <Share2 size={10} aria-hidden="true" />
          from {process.created_by}
        </span>
      )
    }
    if (shared.length === 0) return null
    return (
      <span className="badge gap-1" title={`Shared with ${shared.join(', ')}`}>
        <Share2 size={10} aria-hidden="true" />
        shared with {shared.length}
      </span>
    )
  }

  const versionBadge = (process) =>
    process.latest_version ? (
      <span className="badge badge-succeeded badge-dot">v{process.latest_version}</span>
    ) : (
      <span className="badge badge-dot">Draft</span>
    )

  const renderCard = (process) => (
    <article
      key={process.id}
      className="card card-interactive group flex flex-col gap-2.5 p-4"
      role="button"
      tabIndex={0}
      onClick={() => navigate(`/app/processes/${process.id}`)}
      onKeyDown={(event) => {
        if (event.key === 'Enter' || event.key === ' ') {
          event.preventDefault()
          navigate(`/app/processes/${process.id}`)
        }
      }}
    >
      <div className="flex items-start gap-2">
        <span className="grid size-8 shrink-0 place-items-center rounded-lg bg-brand-soft text-brand-text" aria-hidden="true">
          <Workflow size={16} />
        </span>
        <h3 className="min-w-0 flex-1 truncate pt-1 text-sm font-semibold" title={process.name}>
          {process.name}
        </h3>
        <span onClick={(event) => event.stopPropagation()}>{rowMenu(process)}</span>
      </div>
      <div className="flex flex-wrap items-center gap-2">
        {versionBadge(process)}
        {sharingBadge(process)}
        <span className="text-[11px] text-fg-subtle" title={absoluteTime(process.updated_at)}>
          edited {relativeTime(process.updated_at)}
        </span>
      </div>
    </article>
  )

  const renderTable = (items) => (
    <div className="card overflow-hidden">
      <table className="table">
        <thead>
          <tr>
            <th>Process</th>
            <th className="w-32">Version</th>
            <th className="w-40">Last edited</th>
            <th className="w-12" />
          </tr>
        </thead>
        <tbody>
          {items.map((process) => (
            <tr
              key={process.id}
              className="is-clickable"
              onClick={() => navigate(`/app/processes/${process.id}`)}
            >
              <td>
                <div className="flex items-center gap-2.5">
                  <span className="grid size-7 shrink-0 place-items-center rounded-md bg-brand-soft text-brand-text" aria-hidden="true">
                    <Workflow size={14} />
                  </span>
                  <span className="truncate font-medium">{process.name}</span>
                </div>
              </td>
              <td className="whitespace-nowrap">
                {versionBadge(process)} {sharingBadge(process)}
              </td>
              <td className="text-fg-muted" title={absoluteTime(process.updated_at)}>
                {relativeTime(process.updated_at)}
              </td>
              <td onClick={(event) => event.stopPropagation()}>{rowMenu(process)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )

  return (
    <AppShell
      title="Processes"
      actions={
        <button
          className="btn btn-primary"
          onClick={() => navigate('/app/processes/new')}
          data-tour="new-process"
        >
          <Plus size={15} />
          New process
        </button>
      }
    >
      <div className="mb-5">
        <h2 className="text-xl font-bold">Your processes</h2>
        <p className="text-[13px] text-fg-muted">Design, publish and run automations.</p>
      </div>

      <div className="mb-6 grid grid-cols-2 gap-3 xl:grid-cols-4" data-tour="stats">
        <Stat label="Processes" value={processes?.length ?? '—'} icon={Workflow} tint="text-brand-text bg-brand-soft" />
        <Stat
          label="Published"
          value={published}
          icon={CheckCircle2}
          tint="text-ok-fg bg-ok-bg"
          hint={processes?.length ? `${processes.length - published} draft` : undefined}
        />
        <Stat label="Recent succeeded" value={succeeded} icon={CheckCircle2} tint="text-ok-fg bg-ok-bg" />
        <Stat
          label="Recent failed"
          value={failed}
          icon={XCircle}
          tint={failed ? 'text-bad-fg bg-bad-bg' : 'text-fg-subtle bg-surface-2'}
        />
      </div>

      {processes !== null && processes.length > 0 && (
        <div className="mb-4 flex flex-wrap items-center gap-2">
          <div className="relative min-w-56 flex-1 max-w-sm">
            <Search
              size={15}
              className="pointer-events-none absolute left-2.5 top-1/2 -translate-y-1/2 text-fg-subtle"
              aria-hidden="true"
            />
            <input
              ref={searchRef}
              className="input pl-8"
              placeholder="Search processes and folders…"
              aria-label="Search processes and folders"
              value={query}
              onChange={(event) => setQuery(event.target.value)}
            />
            {!query && (
              <kbd className="kbd pointer-events-none absolute right-2 top-1/2 -translate-y-1/2">/</kbd>
            )}
          </div>

          <select
            className="select w-auto min-w-40"
            aria-label="Filter by folder"
            value={folderFilter}
            onChange={(event) => setFolderFilter(event.target.value)}
          >
            <option value="">All folders</option>
            {allFolders.map((folder) => (
              <option key={folder || '_none'} value={folder}>
                {folder || UNCATEGORIZED}
              </option>
            ))}
          </select>

          <div className="tab-list ml-auto" role="group" aria-label="Layout">
            <button
              className={`tab flex items-center gap-1.5 ${view === 'grid' ? 'is-active' : ''}`}
              aria-pressed={view === 'grid'}
              onClick={() => setViewMode('grid')}
            >
              <LayoutGrid size={13} /> Grid
            </button>
            <button
              className={`tab flex items-center gap-1.5 ${view === 'list' ? 'is-active' : ''}`}
              aria-pressed={view === 'list'}
              onClick={() => setViewMode('list')}
            >
              <Rows3 size={13} /> List
            </button>
          </div>
        </div>
      )}

      <div data-tour="processes">
        {processes === null ? (
          <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
            {[0, 1, 2].map((index) => (
              <div className="skeleton h-24" key={index} />
            ))}
          </div>
        ) : processes.length === 0 ? (
          <EmptyState
            icon={Workflow}
            title="No processes yet"
            action={
              <>
                <button className="btn btn-primary" onClick={() => navigate('/app/processes/new')}>
                  <Plus size={15} />
                  Create your first process
                </button>
                {/* The other way in for someone who has never seen this product. */}
                <button className="btn" onClick={() => startTour()}>
                  <Compass size={15} />
                  Take the guided tour
                </button>
              </>
            }
          >
            A process is a graph of steps. Drag plugins onto the canvas, wire them together, and publish when it works.
          </EmptyState>
        ) : folders.length === 0 ? (
          <EmptyState icon={Search} title="Nothing matches" compact
            action={
              <button className="btn btn-sm" onClick={() => { setQuery(''); setFolderFilter('') }}>
                Clear filters
              </button>
            }
          >
            No process matches “{query}”{folderFilter && ` in ${folderFilter || UNCATEGORIZED}`}.
          </EmptyState>
        ) : (
          folders.map(([folder, items]) => {
            const isCollapsed = collapsed.has(folder)
            return (
              <section className="mb-6" key={folder}>
                <button
                  className="mb-2.5 flex w-full items-center gap-2 border-b border-line pb-2 text-left hover:text-brand-text"
                  onClick={() => toggleFolder(folder)}
                  aria-expanded={!isCollapsed}
                >
                  {isCollapsed ? <ChevronRight size={14} className="text-fg-subtle" /> : <ChevronDown size={14} className="text-fg-subtle" />}
                  {isCollapsed ? <FolderClosed size={15} className="text-fg-subtle" /> : <FolderOpen size={15} className="text-brand-text" />}
                  <strong className="text-[13px]">{folder}</strong>
                  <span className="badge">{items.length}</span>
                </button>
                {!isCollapsed &&
                  (view === 'grid' ? (
                    <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">{items.map(renderCard)}</div>
                  ) : (
                    renderTable(items)
                  ))}
              </section>
            )
          })
        )}
      </div>

      {runs.length > 0 && (
        <section className="mt-8">
          <div className="mb-2.5 flex items-center justify-between gap-3">
            <h3 className="section-label mb-0">Recent activity</h3>
            <button className="link text-xs" onClick={() => navigate('/app/runs')}>
              View all runs
            </button>
          </div>
          <div className="card overflow-hidden">
            <table className="table">
              <thead>
                <tr>
                  <th className="w-28">Run</th>
                  <th>Process</th>
                  <th className="w-36">Status</th>
                  <th className="w-32">Started</th>
                </tr>
              </thead>
              <tbody>
                {runs.slice(0, 8).map((run) => (
                  <tr
                    key={run.id}
                    className="is-clickable"
                    onClick={() => navigate(`/app/runs?run=${run.id}`)}
                  >
                    <td>
                      <code className="code" title={run.id}>
                        {shortId(run.id)}
                      </code>
                    </td>
                    <td className="truncate">{run.process_name}</td>
                    <td>
                      <StatusBadge status={run.status} />
                    </td>
                    <td className="text-fg-muted" title={absoluteTime(run.created_at)}>
                      {relativeTime(run.created_at)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      )}
      <ShareDialog
        process={sharing}
        open={Boolean(sharing)}
        onClose={() => setSharing(null)}
        onSaved={load}
      />
    </AppShell>
  )
}
