import { useState } from 'react'
import { Navigate, Route, Routes } from 'react-router-dom'
import ChatPage from './ChatPage.jsx'
import LoginPage from './LoginPage.jsx'
import SignupPage from './SignupPage.jsx'

function App() {
  const [token, setToken] = useState(() => localStorage.getItem('authToken') || '')
  const authed = Boolean(token)

  function handleLogout() {
    localStorage.removeItem('authToken')
    localStorage.removeItem('authUsername')
    setToken('')
  }

  return (
    <Routes>
      <Route
        path="/login"
        element={
          authed ? (
            <Navigate to="/" replace />
          ) : (
            <LoginPage onAuthed={(t) => setToken(String(t || ''))} />
          )
        }
      />
      <Route
        path="/signup"
        element={
          authed ? (
            <Navigate to="/" replace />
          ) : (
            <SignupPage onAuthed={(t) => setToken(String(t || ''))} />
          )
        }
      />
      <Route
        path="/"
        element={
          authed ? (
            <ChatPage token={token} onLogout={handleLogout} />
          ) : (
            <Navigate to="/login" replace />
          )
        }
      />
      <Route
        path="*"
        element={<Navigate to={authed ? '/' : '/login'} replace />}
      />
    </Routes>
  )
}

export default App
