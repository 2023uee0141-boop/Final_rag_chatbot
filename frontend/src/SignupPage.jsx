import { useMemo, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import './App.css'

function SignupPage({ onAuthed }) {
  const apiBase = useMemo(() => {
    return (import.meta.env.VITE_API_BASE || '').replace(
      /\/$/,
      '',
    )
  }, [])

  const navigate = useNavigate()

  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [confirm, setConfirm] = useState('')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)

  async function signup() {
    setError('')
    if (password !== confirm) {
      setError('Passwords do not match')
      return
    }

    setBusy(true)
    try {
      const cleanUsername = username.trim().toLowerCase()
      const resp = await fetch(`${apiBase}/auth/signup`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ username: cleanUsername, password }),
      })

      const data = await resp.json().catch(() => null)
      if (!resp.ok) {
        throw new Error(data?.detail || 'Sign up failed')
      }

      // Auto-login after signup for a smooth flow.
      const body = new URLSearchParams()
      body.set('username', cleanUsername)
      body.set('password', password)

      const tokenResp = await fetch(`${apiBase}/auth/token`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
        body,
      })

      const tokenData = await tokenResp.json().catch(() => null)
      if (!tokenResp.ok || !tokenData?.access_token) {
        navigate('/login', { replace: true })
        return
      }

      localStorage.setItem('authToken', tokenData.access_token)
      localStorage.setItem('authUsername', cleanUsername)
      if (typeof onAuthed === 'function') onAuthed(tokenData.access_token)
      navigate('/', { replace: true })
    } catch (e) {
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
        <section className="landing" aria-label="Sign up">
          <h1 className="greeting">Create account</h1>

          <div className="promptShell" aria-label="Signup form">
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
              disabled={busy}
            />
            <input
              className="authInput"
              placeholder="Confirm password"
              type="password"
              value={confirm}
              onChange={(e) => setConfirm(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === 'Enter') {
                  e.preventDefault()
                  signup()
                }
              }}
              disabled={busy}
            />
            <button
              type="button"
              className="authBtn"
              onClick={signup}
              disabled={
                busy ||
                !username.trim() ||
                !password.trim() ||
                !confirm.trim()
              }
            >
              {busy ? '…' : 'Sign up'}
            </button>
          </div>

          {error ? (
            <div className="authError" role="status">
              {error}
            </div>
          ) : null}

          <div style={{ marginTop: 12 }}>
            <Link to="/login">Back to sign in</Link>
          </div>
        </section>
      </main>
    </div>
  )
}

export default SignupPage
