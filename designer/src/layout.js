import { useSyncExternalStore } from 'react'

/**
 * Canvas orientation, and the graph layout that follows from it.
 *
 * Which way a process reads is a personal preference: some people see a
 * flowchart running left to right, others a checklist running top to bottom.
 * It is deliberately *not* part of the definition — `position` is the only
 * designer-owned data a ProcessDefinition carries, and an orientation baked
 * into the document would decide for everyone who opens it. So it sits beside
 * the theme instead: one setting per browser, applied to every process.
 *
 * It decides where *Tidy up steps* puts things, and nothing else. Which border
 * of a card an arrow leaves from is worked out per edge from where the two
 * cards actually are (`FloatingEdge.jsx`), so one canvas can be wired left to
 * right and top to bottom at the same time and a hand-placed step is never left
 * with an arrow doubling back to the wrong face of it.
 */
const KEY = 'pe_canvas_dir'
const DIRECTIONS = ['horizontal', 'vertical']

/* Spacing along the flow axis (rank) and across it (lane). A step card is far
   wider than it is tall, so the two orientations need opposite proportions. */
const SPACING = {
  horizontal: { rank: 280, lane: 130 },
  vertical: { rank: 180, lane: 250 },
}

const listeners = new Set()

let direction = read()

function read() {
  try {
    const stored = localStorage.getItem(KEY)
    return DIRECTIONS.includes(stored) ? stored : 'horizontal'
  } catch {
    return 'horizontal'
  }
}

export function setOrientation(next) {
  direction = DIRECTIONS.includes(next) ? next : 'horizontal'
  try {
    localStorage.setItem(KEY, direction)
  } catch {
    /* private mode — the orientation just won't persist */
  }
  listeners.forEach((listener) => listener())
}

function subscribe(listener) {
  listeners.add(listener)
  return () => listeners.delete(listener)
}

export function useOrientation() {
  const current = useSyncExternalStore(subscribe, () => direction, () => 'horizontal')
  return { orientation: current, isVertical: current === 'vertical', setOrientation }
}

/**
 * True when a graph carries no arrangement of its own.
 *
 * `position` is designer-owned, so a process built by the API, an import or a
 * test has every step at (0,0) — they land in one pile and fitView zooms into
 * it. Those get laid out on open; anything the user has arranged is left alone.
 */
export function needsLayout(steps) {
  return !steps.some((step) => step.position?.x || step.position?.y)
}

/**
 * Grid positions for a graph, in dependency order.
 *
 * Rank is the longest path from a root, so a step always sits downstream of
 * everything feeding it. Lane is its slot across that rank, ordered by the
 * average lane of its parents: a chain stays a straight line, and the branches
 * of a condition fan out in the order their ports are drawn rather than in
 * whatever order the steps happen to be stored.
 *
 * Deterministic on purpose — the same graph lays out the same way every time,
 * whether that is the fallback on open or an explicit tidy-up.
 */
export function layoutGraph(ids, edges, orientation = direction) {
  // one relaxation pass per node is enough for a DAG, and the bound keeps a
  // malformed cycle from spinning
  const rank = new Map(ids.map((id) => [id, 0]))
  for (let pass = 0; pass < ids.length; pass += 1) {
    let moved = false
    for (const edge of edges) {
      if (!rank.has(edge.source) || !rank.has(edge.target)) continue
      const next = rank.get(edge.source) + 1
      if (next > rank.get(edge.target)) {
        rank.set(edge.target, next)
        moved = true
      }
    }
    if (!moved) break
  }

  const parents = new Map(ids.map((id) => [id, []]))
  for (const edge of edges) parents.get(edge.target)?.push(edge.source)

  const gap = SPACING[orientation] ?? SPACING.horizontal
  const lane = new Map()
  const positions = new Map()

  // rank by rank, so a step's parents always have a lane by the time it needs one
  for (const step of [...new Set(ids.map((id) => rank.get(id)))].sort((a, b) => a - b)) {
    const members = ids
      .filter((id) => rank.get(id) === step)
      .map((id, index) => {
        const feeds = parents.get(id).map((parent) => lane.get(parent)).filter((slot) => slot !== undefined)
        const centre = feeds.length ? feeds.reduce((total, slot) => total + slot, 0) / feeds.length : 0
        return { id, index, centre }
      })
    members.sort((a, b) => a.centre - b.centre || a.index - b.index)

    members.forEach((member, slot) => {
      lane.set(member.id, slot)
      positions.set(
        member.id,
        orientation === 'vertical'
          ? { x: slot * gap.lane, y: step * gap.rank }
          : { x: step * gap.rank, y: slot * gap.lane },
      )
    })
  }

  return positions
}
