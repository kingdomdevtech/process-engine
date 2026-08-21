import { useReactFlow, useViewport } from '@xyflow/react'

/**
 * The canvas zoom level, beside the zoom controls.
 *
 * Zooming with a trackpad is easy to do by accident, and "why are the steps
 * suddenly tiny" has no answer on screen without this. Clicking it goes back
 * to 100%.
 *
 * It reads the viewport in its own component on purpose: `useViewport()`
 * re-renders on every frame of a pan or zoom, and calling it up in the editor
 * would drag the whole canvas and inspector along with it.
 */
export default function ZoomIndicator() {
  const { zoom } = useViewport()
  const { zoomTo } = useReactFlow()
  const percent = Math.round(zoom * 100)

  return (
    <button
      type="button"
      className="pointer-events-auto h-7 rounded-lg border border-line bg-surface px-2 text-[11px] font-semibold text-fg-muted tabular-nums shadow-md transition-colors hover:bg-surface-2 hover:text-fg"
      title="Reset zoom to 100%"
      aria-label={`Canvas zoom ${percent}%. Activate to reset to 100%.`}
      onClick={() => zoomTo(1, { duration: 200 })}
    >
      {percent}%
    </button>
  )
}
