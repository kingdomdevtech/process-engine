import { BaseEdge, EdgeLabelRenderer, Position, getSmoothStepPath, useInternalNode } from '@xyflow/react'

/**
 * An arrow that leaves whichever border of the card faces the step it points at.
 *
 * Which side a connection starts from is a question about where the two cards
 * are, not about which way the canvas happens to be laid out — so it is answered
 * here, per edge, from the geometry React Flow has already measured. That is
 * what lets one canvas be wired both ways at once: a step dropped below its
 * source is joined bottom-to-top, and the same step dragged round to the right
 * is joined side-to-side, with nothing to switch and nothing stored.
 *
 * The canvas orientation in `layout.js` therefore only decides where *Tidy up
 * steps* puts things. It no longer decides where the arrows attach, and a hand
 * placed step is not left with an arrow doubling back to an anchor on the wrong
 * face of the card.
 */

/** A card's rectangle in flow coordinates, with its centre. */
function box(node) {
  const width = node.measured?.width ?? node.width ?? 190
  const height = node.measured?.height ?? node.height ?? 72
  const { x, y } = node.internals.positionAbsolute
  return { x, y, width, height, cx: x + width / 2, cy: y + height / 2 }
}

/** A point `lane` of the way along one side of `at` (0 = start, 1 = end). */
function anchor(at, side, lane) {
  if (side === Position.Left) return { x: at.x, y: at.y + at.height * lane }
  if (side === Position.Right) return { x: at.x + at.width, y: at.y + at.height * lane }
  if (side === Position.Top) return { x: at.x + at.width * lane, y: at.y }
  return { x: at.x + at.width * lane, y: at.y + at.height }
}

/**
 * The two borders that face each other.
 *
 * Judged against the cards' own size rather than on raw distance, so "beside"
 * and "below" mean which border the line between the two centres actually
 * crosses: two wide cards a little apart read as side by side, which is what
 * they look like.
 */
export function facingSides(source, target) {
  const dx = target.cx - source.cx
  const dy = target.cy - source.cy
  const spanX = (source.width + target.width) / 2 || 1
  const spanY = (source.height + target.height) / 2 || 1
  if (Math.abs(dx) / spanX >= Math.abs(dy) / spanY) {
    return dx >= 0 ? [Position.Right, Position.Left] : [Position.Left, Position.Right]
  }
  return dy >= 0 ? [Position.Bottom, Position.Top] : [Position.Top, Position.Bottom]
}

export default function FloatingEdge({
  id,
  source,
  target,
  sourceHandleId,
  markerEnd,
  style,
  label,
  interactionWidth,
}) {
  const sourceNode = useInternalNode(source)
  const targetNode = useInternalNode(target)
  if (!sourceNode || !targetNode) return null

  const from = box(sourceNode)
  const to = box(targetNode)
  const [sourcePosition, targetPosition] = facingSides(from, to)

  /* A step with more than one output port (a Condition's true/false) spreads
     its arrows along the facing border in port order, so the two branches stay
     tellable apart wherever the cards happen to sit. */
  const ports = sourceNode.data?.outputs?.length ? sourceNode.data.outputs : ['main']
  const index = Math.max(0, ports.indexOf(sourceHandleId ?? 'main'))
  const lane = (index + 1) / (ports.length + 1)

  const start = anchor(from, sourcePosition, lane)
  const end = anchor(to, targetPosition, 0.5)
  const [path, labelX, labelY] = getSmoothStepPath({
    sourceX: start.x,
    sourceY: start.y,
    sourcePosition,
    targetX: end.x,
    targetY: end.y,
    targetPosition,
    borderRadius: 10,
  })

  return (
    <>
      <BaseEdge id={id} path={path} markerEnd={markerEnd} style={style} interactionWidth={interactionWidth} />
      {label && (
        <EdgeLabelRenderer>
          <div
            className="pe-edge-label nodrag nopan"
            style={{ transform: `translate(-50%, -50%) translate(${labelX}px, ${labelY}px)` }}
          >
            {label}
          </div>
        </EdgeLabelRenderer>
      )}
    </>
  )
}
