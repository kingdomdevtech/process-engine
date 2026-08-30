/**
 * The in-app guided tour — an ordered walk around the real interface.
 *
 * The store lives at module level, like the theme, because the tour outlives
 * any one page: it navigates between the dashboard, the editor, the run
 * history and settings, and every page it visits unmounts behind it.
 *
 * A step points at a real element by `anchor`, matched against
 * `[data-tour="<anchor>"]`. Nothing else in the app knows the tour exists —
 * adding a step means adding that one attribute, and a step whose anchor is
 * missing (a narrow window, a collapsed panel) degrades to a centred card
 * rather than breaking the walk.
 *
 * Content is data on purpose: the written walkthrough in docs/guided-tour.html
 * is the long form, and these cards are meant to stay one breath each.
 */
import { useCallback, useEffect, useSyncExternalStore } from 'react'

import { engineUrl, getUser } from './api.js'

const SEEN_KEY = 'pe_tour_seen'
/* Bumping this re-offers the tour once to everyone — for a release that moves
   things around. Leave it alone for copy edits. */
const VERSION = '1'

/** The long-form walkthrough, served by the engine from the docs folder. */
export const TOUR_DOC_URL = engineUrl('/help/guided-tour.html')

export const TOUR_STEPS = [
  {
    id: 'welcome',
    chapter: 'Welcome',
    title: 'Welcome to Process Engine',
    body: 'A process is a graph of steps: each one does a job and hands its result to the next. This is a two-minute walk around the product — the screens, the canvas, and how a process ends up running on its own.',
    hint: 'Arrow keys move through the tour. Esc leaves it at any point.',
    route: '/app',
  },

  {
    id: 'nav',
    chapter: 'Getting around',
    anchor: 'nav',
    placement: 'right',
    title: 'Where things live',
    body: 'Processes is everything you can see — what you built, plus anything shared with you. Runs is every execution across them. Secrets holds the credentials your steps use. Administrators also get Settings, which configures the deployment for everyone.',
  },
  {
    id: 'search',
    chapter: 'Getting around',
    anchor: 'search',
    placement: 'bottom',
    title: 'The fastest way anywhere',
    body: 'Jump to any process by name, and run whatever the open page offers — tidying the canvas, switching theme, or replaying this tour.',
    keys: [['Ctrl', 'K']],
  },
  {
    id: 'account',
    chapter: 'Getting around',
    anchor: 'account',
    placement: 'right',
    title: 'Your account',
    body: 'Theme, the keyboard shortcut list, and sign out. Your role sits under your name: editors design and run processes, admins also manage users.',
  },

  {
    id: 'stats',
    chapter: 'Processes',
    route: '/app',
    anchor: 'stats',
    placement: 'bottom',
    title: 'The state of things',
    body: 'How much exists, how much of it is published rather than draft, and how the recent runs went. A number in the failed tile is the thing to look at first.',
  },
  {
    id: 'processes',
    chapter: 'Processes',
    anchor: 'processes',
    placement: 'top',
    title: 'Your processes, in folders',
    body: 'A folder is just a label on the process — set it in the editor breadcrumb, or with Move… on a card. A card opens the editor; its menu can run, duplicate, move or delete.',
  },
  {
    id: 'new',
    chapter: 'Processes',
    anchor: 'new-process',
    placement: 'bottom',
    title: 'Start a new one',
    body: 'This opens an empty canvas — which is where the next few stops are.',
  },

  {
    id: 'palette',
    chapter: 'Building',
    route: '/app/processes/new',
    stayIf: (path) => path.startsWith('/app/processes/'),
    anchor: 'step-palette',
    placement: 'right',
    title: 'The step palette',
    body: 'Every plugin installed on this server, grouped by category and searchable. Drag one onto the canvas, or click it to drop it into the middle of the view.',
  },
  {
    id: 'canvas',
    chapter: 'Building',
    anchor: 'canvas',
    placement: 'left',
    title: 'The canvas',
    body: 'Drag from a step’s output port to the next step to connect them. A Condition has two ports, true and false: the one that emits nothing skips everything after it, and that is how a process decides.',
  },
  {
    id: 'inspector',
    chapter: 'Building',
    anchor: 'inspector',
    placement: 'left',
    title: 'The inspector',
    body: 'With nothing selected it owns how this process starts: the JSON to test with, its schedule or webhook triggers, and its recent runs.',
  },
  {
    id: 'tabs',
    chapter: 'Building',
    anchor: 'inspector',
    placement: 'left',
    title: 'Select a step and it changes',
    bullets: [
      'Input — the real values reaching this step from the last run.',
      'Config — its settings, as a generated form or as JSON.',
      'Output — test this one step against recorded data.',
    ],
  },
  {
    id: 'expressions',
    chapter: 'Building',
    anchor: 'inspector',
    placement: 'left',
    title: 'Moving data between steps',
    body: 'Any field can hold an expression instead of a fixed value. Press ƒx beside a field to pick one from what is actually available, with sample values from the last run.',
    code: '{{ trigger.name }}\n{{ steps.fetch.output.total }}\n{{ secrets.smtp_password }}',
  },
  {
    id: 'run',
    chapter: 'Building',
    anchor: 'run-draft',
    placement: 'bottom',
    title: 'Run what you can see',
    body: 'Run draft saves, then executes the draft, colouring each node by what happened to it. This is the loop you live in while building.',
    keys: [['Ctrl', 'Enter']],
  },
  {
    id: 'publish',
    chapter: 'Building',
    anchor: 'publish',
    placement: 'bottom',
    title: 'Save is not publish',
    body: 'Save stores the draft. Publish snapshots an immutable, numbered version — and that is what schedules, webhooks and Run now execute. It is refused while the process still has validation issues.',
    keys: [['Ctrl', 'S']],
  },
  {
    id: 'layout',
    chapter: 'Building',
    anchor: 'layout-menu',
    placement: 'bottom',
    title: 'Keeping it readable',
    body: 'Choose whether the canvas reads left to right or top to bottom, and re-lay every step in dependency order with Tidy up. Both are undoable. Arrows always leave the side of a card that faces where they are going, so a step you drag somewhere yourself still reads properly.',
    keys: [['Ctrl', 'Shift', 'L']],
  },
  {
    id: 'history',
    chapter: 'Building',
    anchor: 'history',
    placement: 'bottom',
    title: 'The way back',
    body: 'Undo only lasts as long as this tab. History lists every save, publish, move and sharing change with who made it, and restores any of them onto the canvas as a draft — published versions are left alone, and the restore is recorded too, so you can come straight back.',
  },

  {
    id: 'runs',
    chapter: 'Operating',
    route: '/app/runs',
    anchor: 'run-filters',
    placement: 'bottom',
    title: 'Every run, everywhere',
    body: 'Filter by status or search by run id and process. While anything is still live the list refreshes itself.',
  },
  {
    id: 'run-detail',
    chapter: 'Operating',
    anchor: 'run-list',
    placement: 'top',
    title: 'What a run remembers',
    body: 'Open one for every step it took: status, duration, attempts, input, output per port, error. State is saved after each step — so a run can be paused, resumed and cancelled, and is picked up automatically if the engine restarts mid-flight.',
  },
  {
    id: 'share',
    chapter: 'Operating',
    anchor: 'share',
    placement: 'bottom',
    title: 'Sharing it',
    body: 'A process is yours until you share it. Everyone you add can open, edit and run it — and share it on themselves, so handing work to a colleague never needs an administrator. Administrators see every process regardless.',
  },
  {
    id: 'secrets',
    chapter: 'Operating',
    route: '/app/secrets',
    anchor: 'secrets',
    placement: 'bottom',
    title: 'Secrets',
    body: 'Passwords, API keys and connection strings, encrypted at rest. Store one here and reference it in any step as {{ secrets.name }} — it is resolved at the moment the step runs, so the value never sits inside the process itself.',
  },
  {
    id: 'settings',
    chapter: 'Operating',
    route: '/app/settings',
    anchor: 'settings-tabs',
    placement: 'bottom',
    adminOnly: true,
    title: 'Settings',
    bullets: [
      'Notifications — the mail server run emails are sent through.',
      'Files — the one folder file steps are allowed to touch.',
      'Users — accounts and roles.',
      'Plugins — what is installed, and what each one emits.',
    ],
  },

  {
    id: 'finish',
    chapter: 'Done',
    title: 'That is the tour',
    body: 'Building something small end to end will teach you more than any description: two steps, a test input, Run draft. The written walkthrough goes deeper — expressions, branching, triggers, failure handling and loops, with two worked examples.',
    hint: 'Replay this any time from Ctrl+K → Take the guided tour.',
    doc: true,
  },
]

/* ---- store ---------------------------------------------------------------- */

const listeners = new Set()

let open = false
let index = 0
/* The open page's answer to "would leaving here lose work?" — the tour asks
   before it navigates. Registered by the editor; nobody else needs it. */
let leaveGuard = null

function emit() {
  listeners.forEach((listener) => listener())
}

function subscribe(listener) {
  listeners.add(listener)
  return () => listeners.delete(listener)
}

function snapshot() {
  return `${open ? 1 : 0}:${index}`
}

/**
 * The stops this user can actually be walked through.
 *
 * Computed per call rather than once at import: the module loads before anyone
 * has signed in, so a constant here would capture "no role" and hide the admin
 * stops from admins too.
 */
export function tourSteps() {
  const isAdmin = getUser()?.role === 'admin'
  return TOUR_STEPS.filter((step) => !step.adminOnly || isAdmin)
}

export function tourSeen() {
  try {
    return localStorage.getItem(SEEN_KEY) === VERSION
  } catch {
    return true // private mode: never nag
  }
}

function markSeen() {
  try {
    localStorage.setItem(SEEN_KEY, VERSION)
  } catch {
    /* private mode — the tour just won't be remembered */
  }
}

export function startTour(at = 0) {
  index = Math.max(0, Math.min(at, tourSteps().length - 1))
  open = true
  emit()
}

/** Leaving marks the tour as seen either way: skipping it is an answer. */
export function stopTour() {
  if (!open) return
  open = false
  markSeen()
  emit()
}

export function goToStep(next) {
  if (!open) return
  if (next < 0 || next >= tourSteps().length) {
    stopTour()
    return
  }
  index = next
  emit()
}

export function useTour() {
  const value = useSyncExternalStore(subscribe, snapshot, () => '0:0')
  const [isOpen, at] = value.split(':')
  const current = Number(at)
  return {
    open: isOpen === '1',
    index: current,
    step: tourSteps()[current],
    count: tourSteps().length,
    goTo: goToStep,
    stop: stopTour,
  }
}

/**
 * Tell the tour that leaving this page would discard work — the editor does,
 * while its canvas is dirty, so a tour started mid-edit asks before it walks
 * away instead of silently throwing the graph out.
 */
export function useLeaveGuard(isDirty) {
  const guard = useCallback(() => isDirty, [isDirty])
  useEffect(() => {
    leaveGuard = guard
    return () => {
      if (leaveGuard === guard) leaveGuard = null
    }
  }, [guard])
}

export function wouldLoseWork() {
  try {
    return Boolean(leaveGuard?.())
  } catch {
    return false
  }
}

/** Where a step wants to be shown, or null if here is already fine. */
export function routeFor(step, pathname) {
  if (!step?.route) return null
  if (step.route === pathname) return null
  if (step.stayIf?.(pathname)) return null
  return step.route
}
