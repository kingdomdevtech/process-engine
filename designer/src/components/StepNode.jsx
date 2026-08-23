import { useEffect } from 'react'
import { Handle, Position, useUpdateNodeInternals } from '@xyflow/react'
import { AlertTriangle } from 'lucide-react'
import { PluginIcon } from '../pluginMeta.jsx'
import { useOrientation } from '../layout.js'
import { STATUS } from './ui/StatusBadge.jsx'

/* Run status is drawn on the node border, so progress is readable while
   zoomed out past the point where labels resolve. */
const STATUS_RING = {
  succeeded: 'border-ok-fg',
  failed: 'border-bad-fg',
  running: 'border-info-fg',
  paused: 'border-warn-fg',
  skipped: 'border-line-strong opacity-60',
  pending: 'border-line',
}

/* Named ports carry meaning: error routes are red, boolean branches read
   true/false. Anything else falls back to neutral. */
const PORT_TONE = {
  error: 'text-bad-fg',
  false: 'text-warn-fg',
  true: 'text-ok-fg',
}

export default function StepNode({ id, data }) {
  const { isVertical } = useOrientation()
  const updateNodeInternals = useUpdateNodeInternals()
  const outputs = data.outputs?.length ? data.outputs : ['main']
  const issues = data.issues ?? []
  const status = data.status
  const meta = STATUS[status]
  const StatusIcon = meta?.icon

  /* React Flow measures each handle once and caches where it sits, so moving
     them from the sides to the top and bottom has to be announced — otherwise
     the edges keep meeting the card at its old anchors. */
  useEffect(() => {
    updateNodeInternals(id)
  }, [id, isVertical, updateNodeInternals])

  return (
    <div
      className={`step-card relative min-w-[190px] rounded-lg border-2 bg-surface shadow-sm transition-shadow ${
        STATUS_RING[status] ?? 'border-line'
      } ${status === 'running' ? 'is-running' : ''}`}
      onClick={(event) => {
        event.stopPropagation()
        data.onSelect?.(id)
      }}
    >
      {issues.length > 0 && (
        <span
          className="absolute -right-2 -top-2 z-10 flex size-5 items-center justify-center rounded-full bg-bad-fg text-[10px] font-bold text-white shadow-sm"
          title={issues.join('\n')}
          aria-label={`${issues.length} configuration issue${issues.length === 1 ? '' : 's'}`}
        >
          <AlertTriangle size={11} />
        </span>
      )}

      <Handle type="target" position={isVertical ? Position.Top : Position.Left} id="main" />

      <div className="flex items-start gap-2 px-2.5 pb-1.5 pt-2.5">
        <PluginIcon plugin={data.manifest ?? { key: data.plugin }} size={14} className="mt-px size-7" />
        <div className="min-w-0 flex-1">
          <div className="truncate text-[13px] font-semibold leading-tight" title={data.label}>
            {data.label}
          </div>
          <div className="truncate font-mono text-[10px] text-fg-subtle" title={data.plugin}>
            {data.plugin}
          </div>
        </div>
      </div>

      {/* Ports line up along whichever edge the connections leave from: stacked
          down the right in a horizontal canvas, side by side along the bottom
          in a vertical one. */}
      <div className={`border-t border-line/70 py-1 ${isVertical ? 'flex justify-around gap-1 px-1' : ''}`}>
        {outputs.map((port) => (
          <div
            key={port}
            className={`relative py-[3px] font-mono text-[10px] ${
              isVertical ? 'px-1.5 text-center' : 'px-2.5 text-right'
            } ${PORT_TONE[port] ?? 'text-fg-subtle'}`}
          >
            {port}
            <Handle
              type="source"
              position={isVertical ? Position.Bottom : Position.Right}
              id={port}
              style={isVertical ? { left: '50%' } : { top: '50%' }}
            />
          </div>
        ))}
      </div>

      {status && (
        <div
          className={`absolute ${
            isVertical ? '-top-2.5' : '-bottom-2.5' /* the bottom edge belongs to the ports when vertical */
          } left-2 flex items-center gap-1 rounded-full px-1.5 py-px text-[9px] font-bold uppercase tracking-wide shadow-sm badge-${status}`}
        >
          {StatusIcon && <StatusIcon size={9} className={status === 'running' ? 'animate-spin-slow' : ''} />}
          {status}
        </div>
      )}
    </div>
  )
}
