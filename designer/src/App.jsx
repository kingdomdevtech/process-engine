import { useState } from 'react'
import { BrowserRouter, Navigate, Route, Routes, useLocation } from 'react-router-dom'

import { getUser, hasToken, setToken, setUser } from './api.js'
import { ToastProvider } from './components/Toast.jsx'
import { DialogProvider } from './components/ui/Dialogs.jsx'
import Dashboard from './pages/Dashboard.jsx'
import Editor from './pages/Editor.jsx'
import Login from './pages/Login.jsx'
import RunsPage from './pages/RunsPage.jsx'
import SecretsPage from './pages/Secrets.jsx'
import Settings from './pages/Settings.jsx'

/** The SSO callback hands the session back in the URL fragment. */
function consumeSsoFragment() {
  const hash = new URLSearchParams(window.location.hash.slice(1))
  const session = hash.get('sso')
  const error = hash.get('sso_error') ?? ''
  if (session) {
    setToken(session)
    setUser({ username: hash.get('user'), role: hash.get('role') })
  }
  if (session || error) window.history.replaceState(null, '', window.location.pathname)
  return { viaSso: Boolean(session), error }
}

function RequireAuth({ children }) {
  const location = useLocation()
  if (!hasToken()) return <Navigate to="/login" replace state={{ from: location.pathname }} />
  return children
}

/** Settings is deployment-wide, so an editor typing the URL is sent home
    rather than shown a page they cannot use. The API enforces this too — this
    only saves them the dead end. */
function RequireAdmin({ children }) {
  if (getUser()?.role !== 'admin') return <Navigate to="/app" replace />
  return children
}

export default function App() {
  const [sso] = useState(consumeSsoFragment)

  return (
    <BrowserRouter>
      <ToastProvider>
        <DialogProvider>
          <Routes>
            {/* The app is the product; the root is just a doorway into it.
                RequireAuth bounces anyone without a session on to /login. */}
            <Route path="/" element={<Navigate to="/app" replace />} />
            <Route path="/login" element={<Login initialError={sso.error} />} />
            <Route
              path="/app"
              element={
                <RequireAuth>
                  <Dashboard />
                </RequireAuth>
              }
            />
            <Route
              path="/app/processes/:processId"
              element={
                <RequireAuth>
                  <Editor />
                </RequireAuth>
              }
            />
            <Route
              path="/app/runs"
              element={
                <RequireAuth>
                  <RunsPage />
                </RequireAuth>
              }
            />
            <Route
              path="/app/secrets"
              element={
                <RequireAuth>
                  <SecretsPage />
                </RequireAuth>
              }
            />
            <Route
              path="/app/settings"
              element={
                <RequireAuth>
                  <RequireAdmin>
                    <Settings />
                  </RequireAdmin>
                </RequireAuth>
              }
            />
            <Route path="*" element={<Navigate to="/" replace />} />
          </Routes>
        </DialogProvider>
      </ToastProvider>
    </BrowserRouter>
  )
}
