import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { ListChecks, RefreshCw, Search, X } from 'lucide-react'

import { api } from '../api.js'
import { absoluteTime, durationBetween, relativeTime, shortId } from '../format.js'
import AppShell from '../components/AppShell.jsx'
import EmptyState from '../components/EmptyState.jsx'
import RunPanel from '../components/RunPanel.jsx'
import { useToast } from '../components/Toast.jsx'
import StatusBadge from '../components/ui/StatusBadge.jsx'

const FILTERS = [
  { key: 'all', label: 'All' },
  { key: 'running', label: 'Running' },
  { key: 'succeeded', label: 'Succeeded' },
  { key: 'failed', label: 'Failed' },
  { key: 'paused', label: 'Paused' },
  { key: 'cancelled', label: 'Cancelled' },
]

const PAGE = 40
const LIVE = new Set(['running', 'paused'])

export default function RunsPage() {
  const [params, setParams] = useSearchParams()
  const [processes, setProcesses] = useState([])
  const [runs, setRuns] = useState(null)
  const [filter, setFilter] = useState('all')
  const [query, setQuery] = useState('')
  const [limit, setLimit] = useState(PAGE)
  const [selected, setSelected] = useState(null)
  const [refreshing, setRefreshing] = useState(false)
  const toast = useToast()
  const focusedRun = params.get('run')
  const timer = useRef(null)

  const load = useCallback(
    async (quiet = false) => {
      if (!quiet) setRefreshing(true)
      try {
        const list = await api.get('/api/processes')
        setProcesses(list)
        const all = await Promise.all(
          list.map((process) =>
            api.get(`/api/processes/${process.id}/runs`).then(
              (entries) => entries.map((entry) => ({ ...entry, process_name: process.name })),
              () => [],
            ),
          ),
        )
        setRuns(all.flat().sort((a, b) => b.created_at.localeCompare(a.created_at)))
      } catch (error) {
        if (!quiet) toast.error(String(error.message))
        setRuns((current) => current ?? [])
      } finally {
        setRefreshing(false)
      }
    },
    [toast],
  )

  useEffect(() => {
    load()
  }, [load])

  const open = useCallback(
    async (runId) => {
      try {
        setSelected(await api.get(`/api/runs/${runId}`))
      } catch (error) {
        toast.error(String(error.message))
      }
    },
    [toast],
  )

  useEffect(() => {
    if (focusedRun) open(focusedRun)
  }, [focusedRun, open])

  const hasLive = (runs ?? []).some((run) => LIVE.has(run.status))

  /* A run in flight changes on its own, so the list follows it — but only
     while something is actually live, never as a permanent background poll. */
  useEffect(() => {
    clearInterval(timer.current)
    if (!hasLive) return undefined
    timer.current = setInterval(() => {
      load(true)
      if (selected && LIVE.has(selected.status)) open(selected.id)
    }, 3000)
    return () => clearInterval(timer.current)
  }, [hasLive, load, open, selected])

  const control = async (runId, action) => {
    try {
      await api.post(`/api/runs/${runId}/${action}`)
      toast.ok(`Run ${action === 'resume' ? 'resumed' : 'cancelled'}`)
      load(true)
      open(runId)
    } catch (error) {
      toast.error(String(error.message))
    }
  }

  const counts = useMemo(() => {
    const tally = { all: (runs ?? []).length }
    for (const run of runs ?? []) tally[run.status] = (tally[run.status] ?? 0) + 1
    return tally
  }, [runs])

  const visible = useMemo(() => {
    const term = query.trim().toLowerCase()
    return (runs ?? []).filter((run) => {
      const byStatus = filter === 'all' || run.status === filter
      const byTerm =
        !term || run.id.toLowerCase().includes(term) || (run.process_name ?? '').toLowerCase().includes(term)
      return byStatus && byTerm
    })
  }, [runs, filter, query])

  const close = () => {
    setSelected(null)
    setParams({}, { replace: true })
  }

  return (
    <AppShell
      title="Runs"
      actions={
        <button className="btn" onClick={() => load()} disabled={refreshing}>
          <RefreshCw size={15} className={refreshing ? 'animate-spin-slow' : ''} />
          Refresh
        </button>
      }
    >
      <div className="mb-4 flex flex-wrap items-end justify-between gap-3">
        <div>
          <h2 className="text-xl font-bold">Run history</h2>
          <p className="text-[13px] text-fg-muted">
            Every execution across {processes.length} process{processes.length === 1 ? '' : 'es'}.
            {hasLive && (
              <span className="ml-1.5 inline-flex items-center gap-1 text-info-fg">
                <span className="size-1.5 animate-pulse rounded-full bg-info-fg" aria-hidden="true" />
                live — refreshing
              </span>
            )}
          </p>
        </div>
        <div className="relative min-w-56">
          <Search
            size={15}
            className="pointer-events-none absolute left-2.5 top-1/2 -translate-y-1/2 text-fg-subtle"
            aria-hidden="true"
          />
          <input
            className="input pl-8"
            placeholder="Search run id or process…"
            aria-label="Search runs"
            value={query}
            onChange={(event) => setQuery(event.target.value)}
          />
        </div>
      </div>

      <div
        className="tab-list mb-4 flex-wrap"
        role="tablist"
        aria-label="Filter runs by status"
        data-tour="run-filters"
      >
        {FILTERS.map((option) => (
          <button
            key={option.key}
            role="tab"
            aria-selected={filter === option.key}
            className={`tab flex items-center gap-1.5 ${filter === option.key ? 'is-active' : ''}`}
            onClick={() => {
              setFilter(option.key)
              setLimit(PAGE)
            }}
          >
            {option.label}
            <span className="tabular text-[10px] text-fg-subtle">{counts[option.key] ?? 0}</span>
          </button>
        ))}
      </div>

      <div
        className={`grid items-start gap-4 ${selected ? 'xl:grid-cols-[1fr_380px]' : ''}`}
        data-tour="run-list"
      >
        {runs === null ? (
          <div className="space-y-2">
            {[0, 1, 2, 3, 4].map((index) => (
              <div key={index} className="skeleton h-11" />
            ))}
          </div>
        ) : visible.length === 0 ? (
          <EmptyState
            icon={ListChecks}
            title={query || filter !== 'all' ? 'No matching runs' : 'No runs yet'}
            action={
              (query || filter !== 'all') && (
                <button
                  className="btn btn-sm"
                  onClick={() => {
                    setQuery('')
                    setFilter('all')
                  }}
                >
                  Clear filters
                </button>
              )
            }
          >
            {query || filter !== 'all'
              ? 'Nothing here matches the current filters.'
              : 'Run a process and its history will appear here.'}
          </EmptyState>
        ) : (
          <div className="card overflow-hidden">
            <div className="max-h-[calc(100vh-19rem)] overflow-auto">
              <table className="table">
                <thead>
                  <tr>
                    <th className="w-28">Run</th>
                    <th>Process</th>
                    <th className="w-36">Status</th>
                    <th className="w-24">Duration</th>
                    <th className="w-32">Started</th>
                    <th className="w-24" />
                  </tr>
                </thead>
                <tbody>
                  {visible.slice(0, limit).map((run) => (
                    <tr
                      key={run.id}
                      className={`is-clickable ${selected?.id === run.id ? 'is-selected' : ''}`}
                      onClick={() => {
                        setParams({ run: run.id }, { replace: true })
                        open(run.id)
                      }}
                    >
                      <td>
                        <code className="code" title={run.id}>
                          {shortId(run.id)}
                        </code>
                      </td>
                      <td className="max-w-0 truncate font-medium">{run.process_name}</td>
                      <td>
                        <StatusBadge status={run.status} />
                      </td>
                      <td className="tabular text-fg-muted">
                        {durationBetween(run.started_at, run.finished_at) || '—'}
                      </td>
                      <td className="text-fg-muted" title={absoluteTime(run.created_at)}>
                        {relativeTime(run.created_at)}
                      </td>
                      <td onClick={(event) => event.stopPropagation()}>
                        {run.status === 'paused' && (
                          <button className="btn btn-sm" onClick={() => control(run.id, 'resume')}>
                            Resume
                          </button>
                        )}
                        {run.status === 'running' && (
                          <button className="btn btn-sm btn-danger" onClick={() => control(run.id, 'cancel')}>
                            Cancel
                          </button>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            {visible.length > limit && (
              <div className="border-t border-line p-2 text-center">
                <button className="btn btn-sm" onClick={() => setLimit((value) => value + PAGE)}>
                  Show {Math.min(PAGE, visible.length - limit)} more of {visible.length}
                </button>
              </div>
            )}
          </div>
        )}

        {selected && (
          <aside className="card sticky top-0 max-h-[calc(100vh-8rem)] overflow-y-auto p-4">
            <div className="mb-3 flex items-center justify-between gap-2">
              <h3 className="text-sm font-semibold">Run detail</h3>
              <button className="btn btn-ghost btn-icon btn-sm" onClick={close} aria-label="Close run detail">
                <X size={15} />
              </button>
            </div>
            <RunPanel
              run={selected}
              onResume={(id) => control(id, 'resume')}
              onCancel={(id) => control(id, 'cancel')}
              onRefresh={open}
            />
          </aside>
        )}
      </div>
    </AppShell>
  )
}
