import { useSyncExternalStore } from 'react'

/**
 * Theme store — three modes, one of which defers to the OS.
 *
 * `system` is the default because an operating-system preference is a real
 * signal, but it stays overridable: on a shared workstation the OS setting is
 * often not the person's. The chosen mode is persisted and re-applied before
 * first paint by the inline script in index.html, so there is no light flash
 * on load.
 */
const KEY = 'pe_theme'
const MODES = ['light', 'dark', 'system']

const media = window.matchMedia('(prefers-color-scheme: dark)')
const listeners = new Set()

let mode = read()

function read() {
  try {
    const stored = localStorage.getItem(KEY)
    return MODES.includes(stored) ? stored : 'system'
  } catch {
    return 'system'
  }
}

function resolve(value = mode) {
  return value === 'system' ? (media.matches ? 'dark' : 'light') : value
}

function apply() {
  document.documentElement.classList.toggle('dark', resolve() === 'dark')
}

function emit() {
  listeners.forEach((listener) => listener())
}

/* Following the OS means reacting to it changing while the app is open. */
media.addEventListener('change', () => {
  if (mode === 'system') {
    apply()
    emit()
  }
})

export function setTheme(next) {
  mode = MODES.includes(next) ? next : 'system'
  try {
    localStorage.setItem(KEY, mode)
  } catch {
    /* private mode — the theme just won't persist */
  }
  apply()
  emit()
}

function subscribe(listener) {
  listeners.add(listener)
  return () => listeners.delete(listener)
}

/* The snapshot carries the resolved theme too, so a change in the OS
   preference re-renders even though the mode ('system') is unchanged. */
function snapshot() {
  return `${mode}:${resolve()}`
}

export function useTheme() {
  const [current, active] = useSyncExternalStore(subscribe, snapshot, () => 'system:light').split(':')
  return { mode: current, resolved: active, setTheme }
}

apply()
