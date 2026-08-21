import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import {
  ReactFlow,
  ReactFlowProvider,
  Background,
  BackgroundVariant,
  Controls,
  MiniMap,
  MarkerType,
  addEdge,
  useNodesState,
  useEdgesState,
  useReactFlow,
} from '@xyflow/react'
import '@xyflow/react/dist/style.css'

import {
  AlertTriangle,
  Check,
  CloudUpload,
  Copy,
  Loader2,
  MoveDown,
  MoveRight,
  Network,
  Play,
  Redo2,
  Save,
  Share2,
  Trash2,
  Undo2,
  Wand2,
} from 'lucide-react'

import { api } from '../api.js'
import { useRegisterCommands } from '../commands.js'
import { layoutGraph, needsLayout, useOrientation } from '../layout.js'
import { useLeaveGuard } from '../tour.js'
import { PluginIcon } from '../pluginMeta.jsx'
import AppShell from '../components/AppShell.jsx'
import ShareDialog from '../components/ShareDialog.jsx'
import NotificationsPanel from '../components/NotificationsPanel.jsx'
import Palette from '../components/Palette.jsx'
import RunPanel from '../components/RunPanel.jsx'
import StepInput from '../components/StepInput.jsx'
import StepNode from '../components/StepNode.jsx'
import StepOutput from '../components/StepOutput.jsx'
import StepPanel from '../components/StepPanel.jsx'
import TriggersPanel from '../components/TriggersPanel.jsx'
import ZoomIndicator from '../components/ZoomIndicator.jsx'
import { useToast } from '../components/Toast.jsx'
import Menu, { MenuItem, MenuLabel, MenuSeparator } from '../components/ui/Menu.jsx'
import { useDialogs } from '../components/ui/Dialogs.jsx'

const nodeTypes = { step: StepNode }
const defaultEdgeOptions = {
  type: 'smoothstep',
  markerEnd: { type: MarkerType.ArrowClosed, width: 16, height: 16 },
}
const TERMINAL = new Set(['succeeded', 'failed', 'cancelled', 'paused'])
const MENU_SIZE = { width: 176, height: 96 }
const DIRECTIONS = [
  { value: 'horizontal', label: 'Left to right', icon: <MoveRight size={15} /> },
  { value: 'vertical', label: 'Top to bottom', icon: <MoveDown size={15} /> },
]
/* React Flow applies these as a CSS `fill` declaration rather than an SVG
   attribute, so the tokens resolve here and the minimap re-themes with the
   rest of the app instead of holding light-mode colours in the dark. */
const MINIMAP_COLORS = {
  succeeded: 'var(--ok-fg)',
  failed: 'var(--bad-fg)',
  running: 'var(--info-fg)',
  paused: 'var(--warn-fg)',
  cancelled: 'var(--alt-fg)',
  skipped: 'var(--line-strong)',
}
let stepCounter = 0

// Step names must stay unique — they double as expression handles. Mirrors the
// server-side naming for cloned processes.
function copyLabel(label, taken) {
  let candidate = `${label} (copy)`
  for (let counter = 2; taken.has(candidate); counter += 1) candidate = `${label} (copy ${counter})`
  return candidate
}

function EditorInner() {
  const { processId: routeId } = useParams()
  const isNew = !routeId || routeId === 'new'
  const navigate = useNavigate()
  const toast = useToast()
  const dialogs = useDialogs()

  const [plugins, setPlugins] = useState([])
  const [processes, setProcesses] = useState([])
  const [processId, setProcessId] = useState(isNew ? null : routeId)
  const [processName, setProcessName] = useState('Untitled process')
  const [folder, setFolder] = useState('')
  const [triggers, setTriggers] = useState([])
  const [notifications, setNotifications] = useState({})
  const [createdBy, setCreatedBy] = useState('') // server-owned; shown, never sent
  const [sharedWith, setSharedWith] = useState([]) // ditto — changed only via /share
  const [shareOpen, setShareOpen] = useState(false)
  const [runs, setRuns] = useState([])
  const [runView, setRunView] = useState(null)
  const [serverIssues, setServerIssues] = useState({ byStep: {}, general: [] })
  const [triggerInput, setTriggerInput] = useState('{}')
  const [dirty, setDirty] = useState(false)
  const [saving, setSaving] = useState(false)
  const [running, setRunning] = useState(false)
  const [paletteHidden, setPaletteHidden] = useState(false)
  const [nodes, setNodes, onNodesChange] = useNodesState([])
  const [edges, setEdges, onEdgesChange] = useEdgesState([])
  const [selectedId, setSelectedId] = useState(null)
  const [inspectorTab, setInspectorTab] = useState('config')
  const [menu, setMenu] = useState(null) // right-click menu: { nodeId, label, x, y }
  const { orientation, isVertical, setOrientation } = useOrientation()
  const { screenToFlowPosition, deleteElements, getViewport, fitView } = useReactFlow()
  const pollTimer = useRef(null)
  const history = useRef({ past: [], future: [] })
  const [historyDepth, setHistoryDepth] = useState({ past: 0, future: 0 })

  const pluginByKey = useMemo(() => Object.fromEntries(plugins.map((p) => [p.key, p])), [plugins])

  const guard = useCallback(
    async (fn) => {
      try {
        return await fn()
      } catch (error) {
        if (error.status === 401) navigate('/login')
        else toast.error(String(error.message))
        return undefined
      }
    },
    [navigate, toast],
  )

  useEffect(() => {
    guard(() => api.get('/api/plugins')).then((list) => list && setPlugins(list))
    guard(() => api.get('/api/processes')).then((list) => list && setProcesses(list))
    return () => clearInterval(pollTimer.current)
  }, [guard])

  // ---- undo / redo (canvas structure) --------------------------------------------

  const serialize = useCallback(() => JSON.stringify({ nodes, edges }), [nodes, edges])
  // mirrored into state so the toolbar buttons can disable themselves
  const syncDepth = useCallback(
    () => setHistoryDepth({ past: history.current.past.length, future: history.current.future.length }),
    [],
  )
  const record = useCallback(() => {
    history.current.past.push(serialize())
    if (history.current.past.length > 60) history.current.past.shift()
    history.current.future = []
    syncDepth()
  }, [serialize, syncDepth])
  const restore = useCallback(
    (snapshot) => {
      const parsed = JSON.parse(snapshot)
      setNodes(parsed.nodes)
      setEdges(parsed.edges)
    },
    [setNodes, setEdges],
  )
  const undo = useCallback(() => {
    if (!history.current.past.length) return
    history.current.future.push(serialize())
    restore(history.current.past.pop())
    setDirty(true)
    syncDepth()
  }, [serialize, restore, syncDepth])
  const redo = useCallback(() => {
    if (!history.current.future.length) return
    history.current.past.push(serialize())
    restore(history.current.future.pop())
    setDirty(true)
    syncDepth()
  }, [serialize, restore, syncDepth])

  // ---- canvas mutations ----------------------------------------------------------

  const onConnect = useCallback(
    (params) => {
      record()
      setDirty(true)
      const label = params.sourceHandle && params.sourceHandle !== 'main' ? params.sourceHandle : undefined
      setEdges((eds) => addEdge({ ...params, label }, eds))
    },
    [record, setEdges],
  )

  const onDragOver = useCallback((event) => {
    event.preventDefault()
    event.dataTransfer.dropEffect = 'move'
  }, [])

  const addStep = useCallback(
    (key, position) => {
      const plugin = pluginByKey[key]
      if (!plugin) return
      record()
      setDirty(true)
      stepCounter += 1
      setNodes((nds) =>
        nds.concat({
          id: `${key}_${Date.now().toString(36)}_${stepCounter}`,
          type: 'step',
          position,
          data: {
            label: `${plugin.name} ${stepCounter}`,
            plugin: key,
            config: {},
            outputs: plugin.outputs.map((port) => port.name),
          },
        }),
      )
    },
    [pluginByKey, record, setNodes],
  )

  const onDrop = useCallback(
    (event) => {
      event.preventDefault()
      const key = event.dataTransfer.getData('application/x-plugin')
      addStep(key, screenToFlowPosition({ x: event.clientX, y: event.clientY }))
    },
    [addStep, screenToFlowPosition],
  )

  /* Dragging is not operable by keyboard, so clicking a palette item drops the
     step into the middle of the current view instead. Same result, two routes. */
  const addToCentre = useCallback(
    (key) => {
      const { x, y, zoom } = getViewport()
      addStep(key, {
        x: (window.innerWidth / 2 - x) / zoom - 95,
        y: (window.innerHeight / 2 - y) / zoom - 40,
      })
    },
    [addStep, getViewport],
  )

  // ---- layout ----------------------------------------------------------------------

  /* Re-position every step in dependency order. Undoable like any other canvas
     change, and the viewport follows so the result is on screen rather than
     somewhere off to the side. */
  const arrange = useCallback(
    (direction) => {
      if (!nodes.length) return false
      record()
      setDirty(true)
      const positions = layoutGraph(
        nodes.map((node) => node.id),
        edges,
        direction,
      )
      setNodes((nds) => nds.map((node) => ({ ...node, position: positions.get(node.id) ?? node.position })))
      window.requestAnimationFrame(() => fitView({ duration: 250, padding: 0.2 }))
      return true
    },
    [nodes, edges, record, setNodes, fitView],
  )

  const tidy = useCallback(() => {
    if (arrange(orientation)) toast.ok('Steps repositioned', { action: { label: 'Undo', onClick: undo } })
    else toast.info('Nothing to arrange yet — add a step first')
  }, [arrange, orientation, toast, undo])

  /* Flipping the canvas without moving anything reads as broken: every edge
     would leave the bottom of one card and climb back up to the top of the
     next. So the flip re-arranges too — Ctrl+Z puts the old positions back. */
  const setDirection = useCallback(
    (next) => {
      if (next === orientation) return
      setOrientation(next)
      arrange(next)
    },
    [orientation, setOrientation, arrange],
  )

  /* Contributed to the Ctrl+K palette for as long as the editor is open. Every
     canvas callback is rebuilt as the graph changes — once per frame while a
     step is being dragged — so the commands reach the current handlers through
     a ref rather than re-registering themselves that often. */
  const handlers = useRef({ tidy, setDirection, openShare: () => setShareOpen(true) })
  useEffect(() => {
    handlers.current = { tidy, setDirection, openShare: () => setShareOpen(true) }
  }, [tidy, setDirection])

  const commands = useMemo(
    () => [
      {
        id: 'tidy',
        group: 'Canvas',
        label: 'Tidy up steps',
        icon: Wand2,
        hint: 'Ctrl Shift L',
        keywords: 'layout arrange auto position align order',
        run: () => handlers.current.tidy(),
      },
      {
        id: 'share',
        group: 'Process',
        label: 'Share this process',
        icon: Share2,
        keywords: 'share people access permission collaborate invite',
        run: () => handlers.current.openShare(),
      },
      {
        id: 'orientation',
        group: 'Canvas',
        label: isVertical ? 'Lay the canvas out left to right' : 'Lay the canvas out top to bottom',
        icon: isVertical ? MoveRight : MoveDown,
        keywords: 'orientation direction vertical horizontal rotate flip',
        run: () => handlers.current.setDirection(isVertical ? 'horizontal' : 'vertical'),
      },
    ],
    [isVertical],
  )
  useRegisterCommands(commands)

  // ---- step context menu (right-click) -------------------------------------------

  const closeMenu = useCallback(() => setMenu(null), [])

  const openMenu = useCallback((event, node) => {
    event.preventDefault()
    setMenu({
      nodeId: node.id,
      label: node.data.label,
      // keep the menu inside the viewport when the step sits near an edge
      x: Math.min(event.clientX, window.innerWidth - MENU_SIZE.width - 8),
      y: Math.min(event.clientY, window.innerHeight - MENU_SIZE.height - 8),
    })
  }, [])

  useEffect(() => {
    if (!menu) return undefined
    const onKey = (event) => event.key === 'Escape' && closeMenu()
    window.addEventListener('click', closeMenu)
    window.addEventListener('resize', closeMenu)
    window.addEventListener('keydown', onKey)
    return () => {
      window.removeEventListener('click', closeMenu)
      window.removeEventListener('resize', closeMenu)
      window.removeEventListener('keydown', onKey)
    }
  }, [menu, closeMenu])

  const cloneStep = useCallback(
    (nodeId) => {
      const source = nodes.find((n) => n.id === nodeId)
      if (!source) return
      record()
      setDirty(true)
      stepCounter += 1
      const id = `${source.data.plugin}_${Date.now().toString(36)}_${stepCounter}`
      const label = copyLabel(source.data.label, new Set(nodes.map((n) => n.data.label)))
      setNodes((nds) =>
        nds.concat({
          id,
          type: 'step',
          position: { x: source.position.x + 36, y: source.position.y + 36 },
          data: {
            label,
            plugin: source.data.plugin,
            config: structuredClone(source.data.config ?? {}),
            outputs: source.data.outputs,
          },
        }),
      )
      setSelectedId(id) // connections are not copied — wire the copy up yourself
    },
    [nodes, record, setNodes],
  )

  const deleteStep = useCallback(
    (nodeId) => {
      deleteElements({ nodes: [{ id: nodeId }] }) // onBeforeDelete records undo + marks dirty
      setSelectedId((current) => (current === nodeId ? null : current))
    },
    [deleteElements],
  )

  // ---- config editing --------------------------------------------------------------

  const setNodeData = useCallback(
    (nodeId, patch) => {
      setDirty(true)
      setNodes((nds) => nds.map((n) => (n.id === nodeId ? { ...n, data: { ...n.data, ...patch(n.data) } } : n)))
    },
    [setNodes],
  )
  const onRename = useCallback((nodeId, label) => setNodeData(nodeId, () => ({ label })), [setNodeData])
  const onConfigField = useCallback(
    (nodeId, field, value) =>
      setNodeData(nodeId, (data) => {
        const config = { ...(data.config ?? {}) }
        if (value === undefined) delete config[field]
        else config[field] = value
        return { config }
      }),
    [setNodeData],
  )
  const onConfigJson = useCallback((nodeId, config) => setNodeData(nodeId, () => ({ config })), [setNodeData])

  // ---- definition <-> canvas -------------------------------------------------------

  const toDefinition = useCallback(
    () => ({
      name: processName,
      folder,
      triggers,
      notifications,
      steps: nodes.map((n) => ({
        id: n.id,
        name: n.data.label,
        plugin: n.data.plugin,
        config: n.data.config ?? {},
        position: { x: n.position.x, y: n.position.y },
      })),
      connections: edges.map((e) => ({
        source: e.source,
        source_port: e.sourceHandle || 'main',
        target: e.target,
        target_port: e.targetHandle || 'main',
      })),
    }),
    [processName, folder, triggers, notifications, nodes, edges],
  )

  const refreshRuns = useCallback(
    (id) => guard(() => api.get(`/api/processes/${id}/runs`)).then((list) => list && setRuns(list)),
    [guard],
  )

  const loadProcess = useCallback(
    async (id) => {
      const definition = await guard(() => api.get(`/api/processes/${id}`))
      if (!definition) return
      setProcessId(definition.id)
      setProcessName(definition.name)
      setFolder(definition.folder ?? '')
      setTriggers(definition.triggers ?? [])
      setNotifications(definition.notifications ?? {})
      setCreatedBy(definition.created_by ?? '')
      setSharedWith(definition.shared_with ?? [])
      /* A definition with no arrangement of its own gets one on open, in
         whichever direction this browser reads processes. Nothing is written
         back: the layout is deterministic, so it is the same on every open
         until someone moves a step and saves. */
      const layout = needsLayout(definition.steps)
        ? layoutGraph(
            definition.steps.map((step) => step.id),
            definition.connections,
            orientation,
          )
        : null
      setNodes(
        definition.steps.map((step) => ({
          id: step.id,
          type: 'step',
          position: layout?.get(step.id) ?? { x: step.position?.x ?? 0, y: step.position?.y ?? 0 },
          data: {
            label: step.name || step.id,
            plugin: step.plugin,
            config: step.config ?? {},
            outputs: (pluginByKey[step.plugin]?.outputs ?? [{ name: 'main' }]).map((p) => p.name),
          },
        })),
      )
      setEdges(
        definition.connections.map((conn) => ({
          id: conn.id,
          source: conn.source,
          target: conn.target,
          sourceHandle: conn.source_port,
          targetHandle: conn.target_port,
          label: conn.source_port !== 'main' ? conn.source_port : undefined,
        })),
      )
      setRunView(null)
      setSelectedId(null)
      setServerIssues({ byStep: {}, general: [] })
      history.current = { past: [], future: [] }
      syncDepth()
      setDirty(false)
      refreshRuns(definition.id)
    },
    [guard, pluginByKey, orientation, setNodes, setEdges, refreshRuns, syncDepth],
  )

  // load once the plugin manifests are in (needed to map output ports)
  const loadedRef = useRef(false)
  useEffect(() => {
    if (!isNew && plugins.length && !loadedRef.current) {
      loadedRef.current = true
      loadProcess(routeId)
    }
  }, [isNew, plugins.length, routeId, loadProcess])

  // ---- server actions ---------------------------------------------------------------

  /* Process-level problems surface in a banner over the canvas rather than a
     toast: they persist until fixed, and a toast that names a missing
     connection is gone before you can act on it. */
  const applyServerIssues = useCallback((detailed) => {
    const byStep = {}
    const general = []
    for (const entry of detailed ?? []) {
      if (entry.step_id) (byStep[entry.step_id] = byStep[entry.step_id] ?? []).push(entry.message)
      else general.push(entry.message)
    }
    setServerIssues({ byStep, general })
  }, [])

  const save = useCallback(async () => {
    setSaving(true)
    try {
      const definition = toDefinition()
      const saved = await guard(() =>
        processId ? api.put(`/api/processes/${processId}`, definition) : api.post('/api/processes', definition),
      )
      if (!saved) return null
      if (!processId) {
        setProcessId(saved.id)
        window.history.replaceState(null, '', `/app/processes/${saved.id}`)
        guard(() => api.get('/api/processes')).then((list) => list && setProcesses(list))
      }
      const validation = await guard(() => api.post(`/api/processes/${saved.id}/validate`))
      if (validation) applyServerIssues(validation.detailed)
      setDirty(false)
      return saved.id
    } finally {
      setSaving(false)
    }
  }, [toDefinition, processId, guard, applyServerIssues])

  const publish = useCallback(async () => {
    const id = await save()
    if (!id) return
    const published = await guard(() => api.post(`/api/processes/${id}/publish`))
    if (published) {
      toast.ok(`Published version ${published.version}`, {
        action: { label: 'View runs', onClick: () => navigate('/app/runs') },
      })
    }
  }, [save, guard, toast, navigate])

  const pollRun = useCallback(
    (id) => {
      clearInterval(pollTimer.current)
      pollTimer.current = setInterval(async () => {
        const run = await guard(() => api.get(`/api/runs/${id}`))
        if (!run) {
          clearInterval(pollTimer.current)
          return
        }
        setRunView(run)
        if (TERMINAL.has(run.status)) {
          clearInterval(pollTimer.current)
          if (processId) refreshRuns(processId)
        }
      }, 700)
    },
    [guard, processId, refreshRuns],
  )

  const runDraft = useCallback(async () => {
    setRunning(true)
    try {
      const id = await save()
      if (!id) return
      let trigger = null
      try {
        trigger = JSON.parse(triggerInput)
      } catch {
        /* run without trigger input */
      }
      const run = await guard(() => api.post(`/api/processes/${id}/run`, { draft: true, trigger_input: trigger }))
      if (run) {
        setRunView(run)
        setSelectedId(null) // reveal the run timeline in the inspector
        refreshRuns(id)
        if (run.status === 'succeeded') toast.ok('Run succeeded')
        else if (run.status === 'failed') toast.error(run.error || 'Run failed')
      }
    } finally {
      setRunning(false)
    }
  }, [save, triggerInput, guard, refreshRuns, toast])

  const viewRun = useCallback(
    (id) => guard(() => api.get(`/api/runs/${id}`)).then((run) => run && setRunView(run)),
    [guard],
  )
  const resumeRun = useCallback(
    (id) => guard(() => api.post(`/api/runs/${id}/resume`)).then((ok) => ok && pollRun(id)),
    [guard, pollRun],
  )
  const cancelRun = useCallback(
    (id) => guard(() => api.post(`/api/runs/${id}/cancel`)).then(() => processId && refreshRuns(processId)),
    [guard, processId, refreshRuns],
  )

  // ---- shortcuts and the unsaved-work guard -------------------------------------------

  useEffect(() => {
    const onKey = (event) => {
      const target = event.target
      const inField =
        target instanceof HTMLElement &&
        (['INPUT', 'TEXTAREA', 'SELECT'].includes(target.tagName) || target.isContentEditable)
      const meta = event.ctrlKey || event.metaKey

      // Save and run stay available while typing in a config field.
      if (meta && event.key === 'Enter') {
        event.preventDefault()
        runDraft()
        return
      }
      if (meta && event.key.toLowerCase() === 's') {
        event.preventDefault()
        save()
        return
      }
      if (inField) return
      if (meta && event.shiftKey && event.key.toLowerCase() === 'l') {
        event.preventDefault()
        tidy()
      } else if (meta && event.key.toLowerCase() === 'z') {
        event.preventDefault()
        if (event.shiftKey) redo()
        else undo()
      } else if (meta && event.key.toLowerCase() === 'y') {
        event.preventDefault()
        redo()
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [undo, redo, save, runDraft, tidy])

  /* The guided tour walks between screens on its own; this is how it knows
     that walking away from here would cost something. */
  useLeaveGuard(dirty)

  /* A closed tab takes the unsaved graph with it, and only the browser's own
     prompt can interrupt that. */
  useEffect(() => {
    if (!dirty) return undefined
    const onBeforeUnload = (event) => {
      event.preventDefault()
      event.returnValue = ''
    }
    window.addEventListener('beforeunload', onBeforeUnload)
    return () => window.removeEventListener('beforeunload', onBeforeUnload)
  }, [dirty])

  const leave = async (to) => {
    if (dirty) {
      const ok = await dialogs.confirm({
        title: 'Leave with unsaved changes?',
        body: 'Canvas edits made since the last save will be discarded.',
        confirmLabel: 'Discard and leave',
        tone: 'danger',
      })
      if (!ok) return
    }
    navigate(to)
  }

  // ---- derived view state ----------------------------------------------------------------

  const clientIssues = useMemo(() => {
    const issues = {}
    for (const node of nodes) {
      const schema = pluginByKey[node.data.plugin]?.config_schema
      const missing = (schema?.required ?? []).filter((field) => {
        const value = (node.data.config ?? {})[field]
        return value === undefined || value === null || value === ''
      })
      // name the field as its form label, not as the key underneath it
      if (missing.length) {
        issues[node.id] = missing.map(
          (field) => `“${schema?.properties?.[field]?.title || field}” is required`,
        )
      }
    }
    return issues
  }, [nodes, pluginByKey])

  const runStatusByStep = useMemo(
    () => Object.fromEntries((runView?.step_runs ?? []).map((r) => [r.step_id, r.status])),
    [runView],
  )

  const decoratedNodes = useMemo(
    () =>
      nodes.map((node) => ({
        ...node,
        data: {
          ...node.data,
          manifest: pluginByKey[node.data.plugin],
          status: runStatusByStep[node.id],
          issues: [...(clientIssues[node.id] ?? []), ...(serverIssues.byStep[node.id] ?? [])],
        },
      })),
    [nodes, pluginByKey, runStatusByStep, clientIssues, serverIssues],
  )

  /* Edges leaving a step that is running animate, so where the run has reached
     is visible on the canvas without reading the timeline. */
  const decoratedEdges = useMemo(
    () =>
      edges.map((edge) => ({
        ...edge,
        className: runStatusByStep[edge.source] === 'running' ? 'is-active' : undefined,
      })),
    [edges, runStatusByStep],
  )

  const selectedNode = nodes.find((n) => n.id === selectedId) ?? null
  const selectedPlugin = selectedNode ? pluginByKey[selectedNode.data.plugin] : null
  const selectedIssues = selectedNode
    ? [...(clientIssues[selectedNode.id] ?? []), ...(serverIssues.byStep[selectedNode.id] ?? [])]
    : []

  const issueCount = useMemo(
    () =>
      Object.values(clientIssues).reduce((total, list) => total + list.length, 0) +
      Object.values(serverIssues.byStep).reduce((total, list) => total + list.length, 0),
    [clientIssues, serverIssues],
  )

  const knownFolders = useMemo(
    () => [...new Set(processes.map((process) => process.folder || '').filter(Boolean))].sort(),
    [processes],
  )

  const saveState = saving ? 'saving' : dirty ? 'dirty' : 'saved'

  const breadcrumb = (
    <>
      <Link
        to="/app"
        className="shrink-0 text-fg-muted hover:text-fg"
        onClick={(event) => {
          event.preventDefault()
          leave('/app')
        }}
      >
        Processes
      </Link>
      <span className="text-fg-subtle">/</span>
      <input
        className="input w-28 border-transparent bg-transparent px-1.5 py-1 text-[13px] shadow-none hover:border-line"
        list="pe-folders"
        placeholder="folder"
        aria-label="Folder"
        value={folder}
        onChange={(event) => {
          setFolder(event.target.value)
          setDirty(true)
        }}
      />
      <datalist id="pe-folders">
        {knownFolders.map((name) => (
          <option key={name} value={name} />
        ))}
      </datalist>
      <span className="text-fg-subtle">/</span>
      <input
        className="input w-44 border-transparent bg-transparent px-1.5 py-1 text-[13px] font-semibold text-fg shadow-none hover:border-line"
        aria-label="Process name"
        value={processName}
        onChange={(event) => {
          setProcessName(event.target.value)
          setDirty(true)
        }}
      />
      {/* Save state is a persistent indicator, not a toast: it answers "is my
          work safe?" at any moment without having to try saving again. */}
      <span
        className="ml-1 flex shrink-0 items-center gap-1 text-[11px] text-fg-subtle"
        aria-live="polite"
        title={saveState === 'dirty' ? 'Unsaved changes' : saveState === 'saving' ? 'Saving…' : 'All changes saved'}
      >
        {saveState === 'saving' && <Loader2 size={12} className="animate-spin-slow" />}
        {saveState === 'dirty' && <span className="size-1.5 rounded-full bg-warn-fg" aria-hidden="true" />}
        {saveState === 'saved' && <Check size={12} className="text-ok-fg" aria-hidden="true" />}
        <span className="max-lg:hidden">
          {saveState === 'saving' ? 'Saving…' : saveState === 'dirty' ? 'Unsaved' : 'Saved'}
        </span>
      </span>
    </>
  )

  const actions = (
    <>
      <div className="flex items-center gap-0.5 max-md:hidden">
        <button
          className="btn btn-ghost btn-icon"
          onClick={undo}
          disabled={historyDepth.past === 0}
          title="Undo (Ctrl+Z)"
          aria-label="Undo"
        >
          <Undo2 size={15} />
        </button>
        <button
          className="btn btn-ghost btn-icon"
          onClick={redo}
          disabled={historyDepth.future === 0}
          title="Redo (Ctrl+Shift+Z)"
          aria-label="Redo"
        >
          <Redo2 size={15} />
        </button>
      </div>
      {/* Which way the canvas reads, and the one command that applies it to
          every step at once. */}
      <Menu
        label="Canvas layout"
        trigger={
          <span className="btn btn-ghost btn-icon" title="Canvas layout" data-tour="layout-menu">
            <Network size={15} className={isVertical ? '' : '-rotate-90'} />
          </span>
        }
      >
        <MenuLabel>Direction</MenuLabel>
        {DIRECTIONS.map((item) => (
          <MenuItem
            key={item.value}
            icon={item.icon}
            onClick={() => setDirection(item.value)}
            aria-checked={orientation === item.value}
            className={orientation === item.value ? 'bg-surface-2 font-semibold' : ''}
          >
            {item.label}
          </MenuItem>
        ))}
        <MenuSeparator />
        <MenuItem icon={<Wand2 size={15} />} onClick={tidy} title="Ctrl+Shift+L">
          Tidy up steps
        </MenuItem>
      </Menu>
      <button
        className="btn"
        onClick={() => setShareOpen(true)}
        disabled={!processId}
        title={processId ? 'Share this process with other people' : 'Save it first, then it can be shared'}
        data-tour="share"
      >
        <Share2 size={15} />
        <span className="max-lg:hidden">
          Share{sharedWith.length > 0 && <span className="ml-1 text-fg-subtle">{sharedWith.length}</span>}
        </span>
      </button>
      <button className="btn" onClick={save} disabled={saving} title="Save (Ctrl+S)">
        <Save size={15} />
        <span className="max-lg:hidden">Save</span>
      </button>
      <button
        className="btn"
        onClick={publish}
        title="Save, then snapshot an immutable version"
        data-tour="publish"
      >
        <CloudUpload size={15} />
        <span className="max-lg:hidden">Publish</span>
      </button>
      <button
        className="btn btn-primary"
        onClick={runDraft}
        disabled={running}
        title="Run draft (Ctrl+Enter)"
        data-tour="run-draft"
      >
        {running ? <Loader2 size={15} className="animate-spin-slow" /> : <Play size={15} />}
        Run draft
      </button>
    </>
  )

  return (
    <AppShell breadcrumb={breadcrumb} actions={actions} bare>
      <div className="flex min-h-0 flex-1">
        <Palette
          plugins={plugins}
          onAdd={addToCentre}
          collapsed={paletteHidden}
          onToggle={() => setPaletteHidden((hidden) => !hidden)}
        />

        <div className="relative min-w-0 flex-1" onDrop={onDrop} onDragOver={onDragOver} data-tour="canvas">
          {serverIssues.general.length > 0 && (
            <div
              role="alert"
              className="absolute inset-x-3 top-3 z-10 flex items-start gap-2 rounded-lg border border-bad-fg/30 bg-bad-bg px-3 py-2 text-xs text-bad-fg shadow-md"
            >
              <AlertTriangle size={14} className="mt-px shrink-0" aria-hidden="true" />
              <div className="min-w-0">
                <strong className="font-semibold">This process cannot run yet</strong>
                <ul className="mt-0.5 list-inside list-disc">
                  {serverIssues.general.map((message) => (
                    <li key={message}>{message}</li>
                  ))}
                </ul>
              </div>
            </div>
          )}

          <ReactFlow
            nodes={decoratedNodes}
            edges={decoratedEdges}
            nodeTypes={nodeTypes}
            defaultEdgeOptions={defaultEdgeOptions}
            onNodesChange={onNodesChange}
            onEdgesChange={onEdgesChange}
            onConnect={onConnect}
            onNodeClick={(_, node) => setSelectedId(node.id)}
            onPaneClick={() => setSelectedId(null)}
            onNodeContextMenu={openMenu}
            onPaneContextMenu={(event) => {
              event.preventDefault()
              closeMenu()
            }}
            onMoveStart={closeMenu}
            onNodeDragStart={record}
            onBeforeDelete={() => {
              record()
              setDirty(true)
              return true
            }}
            deleteKeyCode={['Delete', 'Backspace']}
            fitView
            snapToGrid
            snapGrid={[12, 12]}
            proOptions={{ hideAttribution: true }}
          >
            <Background variant={BackgroundVariant.Dots} gap={16} size={1} />
            <Controls showInteractive={false} />
            <MiniMap
              pannable
              zoomable
              nodeColor={(node) => MINIMAP_COLORS[node.data?.status] ?? 'var(--line-strong)'}
              maskColor="transparent"
            />
          </ReactFlow>

          {/* Beside the zoom controls: their 15px panel margin, then their 28px
              width, then a gap. Outside <ReactFlow> so only the badge repaints
              while the canvas is panned. */}
          <div className="pointer-events-none absolute bottom-3.75 left-12.75 z-10">
            <ZoomIndicator />
          </div>

          {nodes.length === 0 && (
            <div className="pointer-events-none absolute inset-0 grid place-items-center">
              <div className="max-w-xs rounded-xl border border-dashed border-line bg-surface/90 p-5 text-center shadow-sm backdrop-blur">
                <p className="text-sm font-semibold">Start with a step</p>
                <p className="mt-1 text-[13px] text-fg-muted">
                  Drag one from the palette, or click it to drop it here. Connect steps to control what runs next.
                </p>
              </div>
            </div>
          )}

          {menu && (
            <div
              role="menu"
              aria-label={`Actions for ${menu.label}`}
              className="animate-zoom fixed z-40 rounded-lg border border-line bg-raised p-1 shadow-lg"
              style={{ top: menu.y, left: menu.x, width: MENU_SIZE.width }}
              onClick={(event) => event.stopPropagation()}
              onContextMenu={(event) => event.preventDefault()}
            >
              <MenuLabel className="truncate" title={menu.label}>
                {menu.label}
              </MenuLabel>
              <MenuItem
                autoFocus
                icon={<Copy size={15} />}
                onClick={() => {
                  cloneStep(menu.nodeId)
                  closeMenu()
                }}
              >
                Duplicate
              </MenuItem>
              <MenuItem
                danger
                icon={<Trash2 size={15} />}
                onClick={() => {
                  deleteStep(menu.nodeId)
                  closeMenu()
                }}
              >
                Delete
              </MenuItem>
            </div>
          )}
        </div>

        <aside
          className="flex w-[360px] shrink-0 flex-col overflow-y-auto border-l border-line bg-surface max-xl:w-[320px] max-lg:hidden"
          data-tour="inspector"
        >
          {selectedNode ? (
            <>
              <div className="flex items-start gap-2.5 border-b border-line px-4 py-3">
                <PluginIcon
                  plugin={selectedPlugin ?? { key: selectedNode.data.plugin }}
                  size={15}
                  className="mt-px size-8"
                />
                <div className="min-w-0 flex-1">
                  <div className="truncate text-[13px] font-semibold">{selectedNode.data.label}</div>
                  <div className="truncate font-mono text-[10px] text-fg-subtle">{selectedNode.data.plugin}</div>
                </div>
                <button
                  className="btn btn-ghost btn-icon btn-sm"
                  onClick={() => cloneStep(selectedNode.id)}
                  title="Duplicate step"
                  aria-label="Duplicate step"
                >
                  <Copy size={14} />
                </button>
                <button
                  className="btn btn-ghost btn-icon btn-sm text-fg-subtle hover:text-bad-fg"
                  onClick={() => deleteStep(selectedNode.id)}
                  title="Delete step"
                  aria-label="Delete step"
                >
                  <Trash2 size={14} />
                </button>
              </div>

              <div className="border-b border-line px-4 py-2.5">
                <div className="tab-list w-full" role="tablist" aria-label="Step detail">
                  {['input', 'config', 'output'].map((tab) => (
                    <button
                      key={tab}
                      role="tab"
                      aria-selected={inspectorTab === tab}
                      className={`tab flex-1 capitalize ${inspectorTab === tab ? 'is-active' : ''}`}
                      onClick={() => setInspectorTab(tab)}
                    >
                      {tab}
                    </button>
                  ))}
                </div>
              </div>

              {inspectorTab === 'input' && (
                <StepInput
                  key={selectedNode.id}
                  processId={processId}
                  stepId={selectedNode.id}
                  fields={Object.keys(selectedPlugin?.config_schema?.properties ?? {})}
                  onAssign={(field, expression) => {
                    onConfigField(selectedNode.id, field, expression)
                    toast.ok(`Assigned to “${field}”`)
                  }}
                />
              )}
              {inspectorTab === 'config' && (
                <StepPanel
                  node={selectedNode}
                  plugin={selectedPlugin}
                  processes={processes}
                  processId={processId}
                  issues={selectedIssues}
                  onRename={onRename}
                  onConfigField={onConfigField}
                  onConfigJson={onConfigJson}
                />
              )}
              {inspectorTab === 'output' && (
                <StepOutput
                  key={selectedNode.id}
                  processId={processId}
                  stepId={selectedNode.id}
                  stepLabel={selectedNode.data.label}
                  onBeforeRun={save}
                />
              )}
            </>
          ) : (
            <>
              <TriggersPanel
                processId={processId}
                triggers={triggers}
                onChange={(next) => {
                  setTriggers(next)
                  setDirty(true)
                }}
                triggerInput={triggerInput}
                onTriggerInput={setTriggerInput}
                runs={runs}
                issueCount={issueCount}
                onViewRun={viewRun}
                onResumeRun={resumeRun}
                onCancelRun={cancelRun}
              >
                <NotificationsPanel
                  notifications={notifications}
                  createdBy={createdBy}
                  onChange={(next) => {
                    setNotifications(next)
                    setDirty(true)
                  }}
                />
              </TriggersPanel>
              {runView && (
                <div className="panel">
                  <div className="panel-title">Run detail</div>
                  <RunPanel run={runView} onResume={resumeRun} onCancel={cancelRun} onRefresh={viewRun} />
                </div>
              )}
            </>
          )}
        </aside>
      </div>

      <ShareDialog
        process={{ id: processId, name: processName, created_by: createdBy, shared_with: sharedWith }}
        open={shareOpen}
        onClose={() => setShareOpen(false)}
        onSaved={(saved) => setSharedWith(saved.shared_with ?? [])}
      />
    </AppShell>
  )
}

export default function Editor() {
  return (
    <ReactFlowProvider>
      <EditorInner />
    </ReactFlowProvider>
  )
}
