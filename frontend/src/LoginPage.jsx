import { useMemo, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import './App.css'

function LoginPage({ onAuthed }) {
  const apiBase = useMemo(() => {
    return (import.meta.env.VITE_API_BASE || '').replace(
      /\/$/,
      '',
    )
  }, [])

  const navigate = useNavigate()

  const [username, setUsername] = useState(
    () => localStorage.getItem('authUsername') || '',
  )
  const [password, setPassword] = useState('')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)

  async function login() {
    setError('')
    setBusy(true)
    try {
      const cleanUsername = username.trim().toLowerCase()
      const body = new URLSearchParams()
      body.set('username', cleanUsername)
      body.set('password', password)

      const resp = await fetch(`${apiBase}/auth/token`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
        body,
      })

      const data = await resp.json().catch(() => null)
      if (!resp.ok) {
        throw new Error(data?.detail || 'Sign in failed')
      }
      if (!data?.access_token) throw new Error('Missing access token')

      localStorage.setItem('authToken', data.access_token)
      localStorage.setItem('authUsername', cleanUsername)
      if (typeof onAuthed === 'function') onAuthed(data.access_token)
      setPassword('')
      navigate('/', { replace: true })
    } catch (e) {
      localStorage.removeItem('authToken')
      setError(e.message)
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="page">
      <header className="topBar" aria-label="Top bar">
        <div className="topLeft">Chat</div>
      </header>

      <main className="main">
        <section className="landing" aria-label="Sign in">
          <h1 className="greeting">Sign in</h1>

          <div className="promptShell" aria-label="Login form">
            <input
              className="authInput"
              placeholder="Username"
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              disabled={busy}
            />
            <input
              className="authInput"
              placeholder="Password"
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === 'Enter') {
                  e.preventDefault()
                  login()
                }
              }}
              disabled={busy}
            />
            <button
              type="button"
              className="authBtn"
              onClick={login}
              disabled={
                busy || !username.trim() || !password.trim()
              }
            >
              {busy ? '…' : 'Sign in'}
            </button>
          </div>

          {error ? (
            <div className="authError" role="status">
              {error}
            </div>
          ) : null}

          <div style={{ marginTop: 12 }}>
            <Link to="/signup">Create an account</Link>
          </div>
        </section>
      </main>
    </div>
  )
}

export default LoginPage
