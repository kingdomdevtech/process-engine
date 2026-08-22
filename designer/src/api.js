let token = localStorage.getItem('pe_token') || ''

/* Where the engine lives. Empty means same origin (the dev proxy, or a
   single-origin build served by the engine itself); set VITE_API_BASE at
   build time to point a separately deployed designer at the engine. */
export const API_BASE = (import.meta.env.VITE_API_BASE || '').replace(/\/$/, '')

/** Absolute engine URL for a root-relative path (`/api/...`, `/help/...`). */
export function engineUrl(path) {
  return `${API_BASE}${path}`
}

export function setToken(value) {
  token = value
  if (value) localStorage.setItem('pe_token', value)
  else localStorage.removeItem('pe_token')
}

export function hasToken() {
  return Boolean(token)
}

export function setUser(user) {
  if (user) localStorage.setItem('pe_user', JSON.stringify(user))
  else localStorage.removeItem('pe_user')
}

export function getUser() {
  try {
    return JSON.parse(localStorage.getItem('pe_user')) ?? null
  } catch {
    return null
  }
}

export function clearSession() {
  setToken('')
  setUser(null)
}

async function request(path, options = {}) {
  const headers = { ...(options.headers || {}) }
  let body
  if (options.body !== undefined) {
    headers['Content-Type'] = 'application/json'
    body = JSON.stringify(options.body)
  }
  if (token) headers.Authorization = `Bearer ${token}`
  const response = await fetch(engineUrl(path), { method: options.method || 'GET', headers, body })
  const data = await response.json().catch(() => null)
  if (!response.ok) {
    const detail = data?.detail
    const message =
      (detail && detail.issues && detail.issues.join('; ')) ||
      (typeof detail === 'string' ? detail : `HTTP ${response.status}`)
    const error = new Error(message)
    error.status = response.status
    error.data = data
    throw error
  }
  return data
}

export const api = {
  get: (path) => request(path),
  post: (path, body) => request(path, { method: 'POST', body: body ?? {} }),
  put: (path, body) => request(path, { method: 'PUT', body }),
  del: (path) => request(path, { method: 'DELETE' }),
}
