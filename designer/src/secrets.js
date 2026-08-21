import { useEffect, useState } from 'react'
import { api } from './api.js'

/**
 * The names of the stored secrets, shared by every password field on screen.
 *
 * Only names ever leave the API — values are write-only and encrypted at rest —
 * so this list is safe to hold in memory and cheap to reuse. It is fetched once
 * per session; `refreshSecretNames()` re-reads it after the settings page adds
 * or removes one.
 */
let cache = null
let inFlight = null
const listeners = new Set()

function load() {
  if (cache) return Promise.resolve(cache)
  if (!inFlight) {
    inFlight = api
      .get('/api/secrets')
      .then((names) => (Array.isArray(names) ? names : []))
      .catch(() => []) // an editor without permission to list secrets still types the expression by hand
      .then((names) => {
        cache = names
        inFlight = null
        listeners.forEach((notify) => notify(names))
        return names
      })
  }
  return inFlight
}

export function refreshSecretNames() {
  cache = null
  inFlight = null
  load()
}

export function useSecretNames() {
  const [names, setNames] = useState(cache ?? [])

  useEffect(() => {
    let live = true
    listeners.add(setNames)
    load().then((loaded) => {
      if (live) setNames(loaded)
    })
    return () => {
      live = false
      listeners.delete(setNames)
    }
  }, [])

  return names
}

/** `{{ secrets.smtp_password }}` → `smtp_password`, or null for a literal value. */
export function secretReference(value) {
  const match = typeof value === 'string' && value.match(/^\s*\{\{\s*secrets\.([A-Za-z0-9_.-]+)\s*\}\}\s*$/)
  return match ? match[1] : null
}

export const secretExpression = (name) => `{{ secrets.${name} }}`
