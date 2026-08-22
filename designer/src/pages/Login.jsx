import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { AlertCircle, Eye, EyeOff, KeyRound, Loader2 } from 'lucide-react'

import { API_BASE, api, engineUrl, setToken, setUser } from '../api.js'
import { brand } from '../brand.js'
import { LogoMark } from '../components/Logo.jsx'
import ThemeToggle from '../components/ThemeToggle.jsx'

const PROVIDER_ICONS = {
  google: (
    <svg width="16" height="16" viewBox="0 0 24 24" aria-hidden="true">
      <path fill="#4285F4" d="M23.5 12.3c0-.9-.1-1.5-.3-2.2H12v4.1h6.5c-.1 1.1-.8 2.7-2.4 3.8l3.7 2.9c2.3-2.1 3.7-5.1 3.7-8.6z" />
      <path fill="#34A853" d="M12 24c3.2 0 6-1.1 7.9-2.9l-3.7-2.9c-1 .7-2.4 1.2-4.2 1.2-3.2 0-6-2.1-6.9-5.1L1.3 17.2C3.3 21.2 7.3 24 12 24z" />
      <path fill="#FBBC05" d="M5.1 14.3c-.2-.7-.4-1.5-.4-2.3s.1-1.6.4-2.3L1.3 6.8C.5 8.4 0 10.1 0 12s.5 3.6 1.3 5.2l3.8-2.9z" />
      <path fill="#EA4335" d="M12 4.7c2.3 0 3.8 1 4.7 1.8l3.4-3.3C18 1.2 15.2 0 12 0 7.3 0 3.3 2.8 1.3 6.8l3.8 2.9c.9-3 3.7-5 6.9-5z" />
    </svg>
  ),
  entra: (
    <svg width="16" height="16" viewBox="0 0 24 24" aria-hidden="true">
      <rect x="1" y="1" width="10" height="10" fill="#F35325" />
      <rect x="13" y="1" width="10" height="10" fill="#81BC06" />
      <rect x="1" y="13" width="10" height="10" fill="#05A6F0" />
      <rect x="13" y="13" width="10" height="10" fill="#FFBA08" />
    </svg>
  ),
}

export default function Login({ initialError = '' }) {
  const [mode, setMode] = useState('password')
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [tokenValue, setTokenValue] = useState('')
  const [reveal, setReveal] = useState(false)
  const [providers, setProviders] = useState([])
  const [unreachable, setUnreachable] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(initialError)
  const navigate = useNavigate()

  // Which providers to offer is the engine's answer, so this probe doubles as a
  // reachability check — and it must, because when the designer is deployed
  // apart from the engine a wrong VITE_API_BASE looks exactly like "SSO is not
  // configured": no buttons, no explanation, until a sign-in finally fails. A
  // rejection with no HTTP status never reached the engine at all.
  useEffect(() => {
    api
      .get('/api/auth/sso')
      .then((list) => {
        setProviders(list)
        setUnreachable(false)
      })
      .catch((err) => {
        setProviders([])
        setUnreachable(err.status === undefined)
      })
  }, [])

  const submit = async (event) => {
    event.preventDefault()
    setError('')
    setBusy(true)
    try {
      if (mode === 'password') {
        const session = await api.post('/api/auth/login', { username: username.trim(), password })
        setToken(session.token)
        setUser({ username: session.username, role: session.role })
      } else {
        setToken(tokenValue.trim())
        const me = await api.get('/api/auth/me')
        setUser({ username: me.name, role: me.role })
      }
      navigate('/app')
    } catch (err) {
      setToken('')
      setError(
        err.status === 401
          ? 'Those credentials were not accepted.'
          : `Cannot reach the API (${err.message}).`,
      )
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="aurora grid min-h-full place-items-center px-4 py-10">
      <div className="fixed right-4 top-4">
        <ThemeToggle />
      </div>

      <div className="animate-rise w-full max-w-[26rem]">
        <div className="card p-8 shadow-xl">
          <LogoMark size={44} id="login" />
          <h1 className="mt-4 text-xl font-bold tracking-[-0.015em]">Sign in to {brand.name}</h1>
          <p className="mt-1 text-[13px] text-fg-muted">Design and run your processes.</p>

          {providers.length > 0 && (
            <div className="mt-6 space-y-2">
              {providers.map((provider) => (
                <button
                  key={provider.key}
                  type="button"
                  className="btn w-full"
                  onClick={() => {
                    window.location.href = engineUrl(`/api/auth/sso/${provider.key}/login`)
                  }}
                >
                  {PROVIDER_ICONS[provider.key]} Continue with {provider.name}
                </button>
              ))}
              <div className="divider-text py-2">or</div>
            </div>
          )}

          {unreachable && (
            <p
              role="alert"
              className="mt-5 flex items-start gap-2 rounded-md border border-warn-fg/30 bg-warn-bg px-3 py-2 text-xs text-warn-fg"
            >
              <AlertCircle size={14} className="mt-px shrink-0" aria-hidden="true" />
              <span>
                Cannot reach the engine{API_BASE ? ' at ' : ''}
                {API_BASE && <code className="code">{API_BASE}</code>}. Sign-in options cannot be loaded until it
                answers.
              </span>
            </p>
          )}

          {/* role="alert" so the failure is announced, not just shown */}
          {error && (
            <p
              role="alert"
              className="mt-5 flex items-start gap-2 rounded-md border border-bad-fg/30 bg-bad-bg px-3 py-2 text-xs text-bad-fg"
            >
              <AlertCircle size={14} className="mt-px shrink-0" aria-hidden="true" />
              <span>{error}</span>
            </p>
          )}

          <form onSubmit={submit} className={providers.length > 0 ? 'mt-4' : 'mt-6'}>
            {mode === 'password' ? (
              <>
                <div className="mb-3">
                  <label className="label mb-1.5" htmlFor="pe-username">
                    Username
                  </label>
                  <input
                    id="pe-username"
                    className="input"
                    autoFocus
                    autoComplete="username"
                    value={username}
                    onChange={(event) => setUsername(event.target.value)}
                  />
                </div>
                <div className="mb-4">
                  <label className="label mb-1.5" htmlFor="pe-password">
                    Password
                  </label>
                  <div className="relative">
                    <input
                      id="pe-password"
                      className="input pr-10"
                      type={reveal ? 'text' : 'password'}
                      autoComplete="current-password"
                      value={password}
                      onChange={(event) => setPassword(event.target.value)}
                    />
                    <button
                      type="button"
                      className="btn btn-ghost btn-icon btn-sm absolute right-1 top-1/2 -translate-y-1/2"
                      onClick={() => setReveal((value) => !value)}
                      aria-label={reveal ? 'Hide password' : 'Show password'}
                      title={reveal ? 'Hide password' : 'Show password'}
                    >
                      {reveal ? <EyeOff size={15} /> : <Eye size={15} />}
                    </button>
                  </div>
                </div>
              </>
            ) : (
              <div className="mb-4">
                <label className="label mb-1.5" htmlFor="pe-token">
                  API token
                </label>
                <input
                  id="pe-token"
                  className="input font-mono text-xs"
                  type="password"
                  autoFocus
                  autoComplete="off"
                  spellCheck={false}
                  value={tokenValue}
                  onChange={(event) => setTokenValue(event.target.value)}
                />
              </div>
            )}

            <button className="btn btn-primary w-full" type="submit" disabled={busy}>
              {busy && <Loader2 size={15} className="animate-spin-slow" />}
              {busy ? 'Signing in…' : 'Sign in'}
            </button>
          </form>

          <div className="mt-4 text-center">
            <button
              type="button"
              className="link inline-flex items-center gap-1.5 text-xs"
              onClick={() => {
                setMode(mode === 'password' ? 'token' : 'password')
                setError('')
              }}
            >
              <KeyRound size={13} />
              {mode === 'password' ? 'Use an API token instead' : 'Use username & password'}
            </button>
          </div>
        </div>

        <details className="mt-4 rounded-lg border border-line bg-surface-2 px-4 py-3">
          <summary className="cursor-pointer text-xs font-semibold text-fg-muted">
            First time signing in?
          </summary>
          <p className="hint mt-2">
            Use the API token (<code className="code">PROCESS_ENGINE_AUTH_TOKEN</code>, or the server&apos;s{' '}
            <code className="code">.process_engine_auth</code> file), then add users under Settings. The Google and
            Microsoft buttons appear once the <code className="code">PROCESS_ENGINE_OIDC_*</code> variables are set.
          </p>
        </details>
      </div>
    </div>
  )
}
