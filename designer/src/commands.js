import { useEffect, useSyncExternalStore } from 'react'

/**
 * Commands the open page contributes to the Ctrl+K palette.
 *
 * The palette lives in the shell, above the router, so it cannot reach into a
 * page for the things only that page can do. A page registers them here while
 * it is mounted and they disappear with it — "Tidy up steps" is offered in the
 * editor and nowhere else, without the palette knowing an editor exists.
 */
const NONE = []
const listeners = new Set()

let registered = NONE

function emit() {
  listeners.forEach((listener) => listener())
}

/** Publish `commands` (memoise the array) for as long as the caller is mounted. */
export function useRegisterCommands(commands) {
  useEffect(() => {
    registered = commands
    emit()
    return () => {
      if (registered !== commands) return // a page that mounted after this one owns the list now
      registered = NONE
      emit()
    }
  }, [commands])
}

function subscribe(listener) {
  listeners.add(listener)
  return () => listeners.delete(listener)
}

export function usePageCommands() {
  return useSyncExternalStore(subscribe, () => registered, () => NONE)
}
