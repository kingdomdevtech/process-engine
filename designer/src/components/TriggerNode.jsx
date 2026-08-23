import { useEffect } from 'react'
import { Handle, Position, useUpdateNodeInternals } from '@xyflow/react'
import { Zap } from 'lucide-react'

export default function TriggerNode({ id, data }) {
  const updateNodeInternals = useUpdateNodeInternals()

  useEffect(() => {
    updateNodeInternals(id)
  }, [id, updateNodeInternals])

  return (
    <div
      className="step-card relative min-w-[190px] rounded-lg border-2 border-line bg-surface shadow-sm"
      onClick={(event) => {
        event.stopPropagation()
        data.onSelect?.(id)
      }}
    >
      <Handle type="source" position={Position.Right} id="main" />

      <div className="flex items-start gap-2 px-2.5 pb-1.5 pt-2.5">
        <div className="grid size-7 place-items-center rounded-md bg-info-bg text-info-fg">
          <Zap size={14} />
        </div>
        <div className="min-w-0 flex-1">
          <div className="truncate text-[13px] font-semibold leading-tight" title={data.label}>
            {data.label}
          </div>
          <div className="truncate font-mono text-[10px] text-fg-subtle">trigger</div>
        </div>
      </div>

      <div className="border-t border-line/70 py-1 px-2.5">
        <div className="font-mono text-[10px] text-fg-subtle">config</div>
      </div>
    </div>
  )
}
