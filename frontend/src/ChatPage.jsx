import { useEffect, useMemo, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import './App.css'

function ChatPage({ token, onLogout }) {
  const apiBase = useMemo(() => {
    return (import.meta.env.VITE_API_BASE || 'http://localhost:8000').replace(
      /\/$/,
      '',
    )
  }, [])

  const navigate = useNavigate()

  const [sessionId, setSessionId] = useState('')
  const [pdfName, setPdfName] = useState('')
  const [searchMode, setSearchMode] = useState('web')
  const [messages, setMessages] = useState([])
  const [input, setInput] = useState('')
  const [isBusy, setIsBusy] = useState(false)
  const [historySessions, setHistorySessions] = useState([])
  const [historyBusy, setHistoryBusy] = useState(false)
  const [historyError, setHistoryError] = useState('')
  const [sidebarOpen, setSidebarOpen] = useState(true)

  const fileInputRef = useRef(null)
  const messagesEndRef = useRef(null)

  const ideas = [
    {
      title: 'Summarize this PDF',
      prompt: 'Summarize the PDF in 6 bullet points.',
    },
    {
      title: 'Key takeaways',
      prompt: 'What are the 10 key takeaways? Provide short explanations.',
    },
    {
      title: 'Generate questions',
      prompt: 'Generate 8 study questions and answer them from the document.',
    },
    {
      title: 'Explain like I’m new',
      prompt: 'Explain the main concepts like I’m a beginner.',
    },
  ]

  function authHeaders(extra = {}) {
    if (!token) return extra
    return { ...extra, Authorization: `Bearer ${token}` }
  }

  async function refreshHistory() {
    if (!token) return
    setHistoryBusy(true)
    setHistoryError('')
    try {
      const resp = await fetch(`${apiBase}/history`, {
        headers: authHeaders(),
      })
      if (!resp.ok) {
        if (resp.status === 401) {
          logout()
          throw new Error('Unauthorized')
        }
        const text = await resp.text().catch(() => '')
        throw new Error(text || 'Failed to load history')
      }
      const data = await resp.json()
      setHistorySessions(Array.isArray(data?.sessions) ? data.sessions : [])
    } catch (err) {
      setHistoryError(err.message)
    } finally {
      setHistoryBusy(false)
    }
  }

  async function loadHistorySession(id) {
    if (!id || isBusy) return
    setIsBusy(true)
    try {
      const resp = await fetch(`${apiBase}/history/${id}`, {
        headers: authHeaders(),
      })
      if (!resp.ok) {
        if (resp.status === 401) {
          logout()
          throw new Error('Unauthorized')
        }
        const text = await resp.text().catch(() => '')
        throw new Error(text || 'Failed to load session')
      }
      const data = await resp.json()
      const items = Array.isArray(data?.messages) ? data.messages : []
      setMessages(
        items.map((m) => ({
          role: m.role,
          content: m.content,
          search_mode: m.search_mode,
        })),
      )
      setSessionId(id)
      const lastPdf = [...items]
        .reverse()
        .find((m) => m.pdf_name)?.pdf_name
      setPdfName(lastPdf || '')
      const lastMode = [...items]
        .reverse()
        .find((m) => m.search_mode)?.search_mode
      if (lastMode) setSearchMode(lastMode)
    } catch (err) {
      setMessages((prev) => [
        ...prev,
        { role: 'assistant', content: `Error: ${err.message}` },
      ])
    } finally {
      setIsBusy(false)
    }
  }

  function logout() {
    if (typeof onLogout === 'function') onLogout()
    navigate('/login', { replace: true })
  }

  async function ensureSession() {
    if (sessionId) return sessionId
    const resp = await fetch(`${apiBase}/session`, {
      method: 'POST',
      headers: authHeaders(),
    })
    if (!resp.ok) {
      if (resp.status === 401) {
        logout()
        throw new Error('Unauthorized')
      }
      const text = await resp.text().catch(() => '')
      throw new Error(text || 'Failed to create session')
    }
    const data = await resp.json()
    setSessionId(data.session_id)
    refreshHistory()
    return data.session_id
  }

  async function handleUploadClick() {
    fileInputRef.current?.click()
  }

  function startNewChat() {
    setSessionId('')
    setPdfName('')
    setSearchMode('web')
    setMessages([])
    setInput('')
  }

  async function handleFileChange(e) {
    const file = e.target.files?.[0]
    e.target.value = ''
    if (!file) return

    setIsBusy(true)
    try {
      const form = new FormData()
      form.append('file', file)

      const resp = await fetch(`${apiBase}/upload`, {
        method: 'POST',
        headers: authHeaders(),
        body: form,
      })

      if (!resp.ok) {
        if (resp.status === 401) {
          logout()
          throw new Error('Unauthorized')
        }
        const detail = await resp.text().catch(() => '')
        throw new Error(detail || 'Upload failed')
      }

      const data = await resp.json()
      setSessionId(data.session_id)
      setPdfName(data.pdf_name)
      setSearchMode('pdf')
      setMessages([
        {
          role: 'assistant',
          content: `Loaded ${data.pdf_name}. Ask me anything about it.`,
        },
      ])
      refreshHistory()
    } catch (err) {
      setMessages((prev) => [
        ...prev,
        { role: 'assistant', content: `Error: ${err.message}` },
      ])
    } finally {
      setIsBusy(false)
    }
  }

  async function sendMessage(text) {
    const trimmed = text.trim()
    if (!trimmed || isBusy) return

    setInput('')
    setIsBusy(true)

    const userMsg = { role: 'user', content: trimmed }
    setMessages((prev) => [...prev, userMsg])

    try {
      const sid = await ensureSession()

      const resp = await fetch(`${apiBase}/chat`, {
        method: 'POST',
        headers: authHeaders({ 'Content-Type': 'application/json' }),
        body: JSON.stringify({
          session_id: sid,
          message: trimmed,
          search_mode: searchMode,
        }),
      })

      if (!resp.ok) {
        if (resp.status === 401) {
          logout()
          throw new Error('Unauthorized')
        }
        const detail = await resp.text().catch(() => '')
        throw new Error(detail || 'Request failed')
      }

      const data = await resp.json()
      setMessages((prev) => [
        ...prev,
        {
          role: 'assistant',
          content: data.answer,
          sources: Array.isArray(data.sources) ? data.sources : [],
          search_mode: data.search_mode,
        },
      ])
      refreshHistory()
    } catch (err) {
      setMessages((prev) => [
        ...prev,
        { role: 'assistant', content: `Error: ${err.message}` },
      ])
    } finally {
      setIsBusy(false)
    }
  }

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages.length])

  useEffect(() => {
    refreshHistory()
    // refreshHistory intentionally reads the latest local component state.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [token])

  const isEmpty = messages.length === 0

  function formatHistoryTime(value) {
    if (!value) return ''
    const d = new Date(value)
    if (Number.isNaN(d.getTime())) return ''
    return d.toLocaleDateString(undefined, {
      month: 'short',
      day: 'numeric',
    })
  }

  function renderAssistant(content) {
    const normalized = String(content || '')
      .replaceAll('<br>', '\n')
      .replaceAll('<br/>', '\n')
      .replaceAll('<br />', '\n')

    return (
      <ReactMarkdown remarkPlugins={[remarkGfm]}>{normalized}</ReactMarkdown>
    )
  }

  function renderSources(sources) {
    const items = Array.isArray(sources) ? sources : []
    const cleaned = items
      .map((s) => ({ title: s?.title || s?.link || '', link: s?.link || '' }))
      .filter((s) => s.link)
      .slice(0, 4)

    if (cleaned.length === 0) return null
    return (
      <div className="sources" aria-label="Sources">
        <div className="sourcesLabel">Sources</div>
        <ul className="sourcesList">
          {cleaned.map((s) => (
            <li key={s.link}>
              <a href={s.link} target="_blank" rel="noreferrer">
                {s.title || s.link}
              </a>
            </li>
          ))}
        </ul>
      </div>
    )
  }

  const userInitial = (localStorage.getItem('authUsername') || 'U')
    .trim()
    .charAt(0)
    .toUpperCase()

  return (
    <div className={`appShell ${sidebarOpen ? '' : 'sidebarClosed'}`}>
      <aside className="gptSidebar" aria-label="Sidebar">
        <div className="sidebarTop">
          <div className="brandMark" aria-hidden="true">
            ✺
          </div>
          <button
            type="button"
            className="sidebarToggle"
            onClick={() => setSidebarOpen(false)}
            aria-label="Close sidebar"
            title="Close sidebar"
          >
            ◧
          </button>
        </div>

        <div className="sidebarSection grow">
          <div className="historyHeaderRow">
            <div className="sidebarSectionTitle">Recents</div>
            <button
              type="button"
              className="miniIconBtn"
              onClick={refreshHistory}
              disabled={historyBusy}
              aria-label="Refresh history"
              title="Refresh history"
            >
              {historyBusy ? '…' : '↻'}
            </button>
          </div>

          {historyError ? (
            <div className="sidebarEmpty">{historyError}</div>
          ) : null}

          <div className="recentList" role="list">
            {historySessions.length === 0 && !historyBusy ? (
              <div className="sidebarEmpty">No chats yet.</div>
            ) : null}
            {historySessions.map((s) => (
              <button
                type="button"
                key={s.session_id}
                className={`recentItem ${
                  sessionId === s.session_id ? 'active' : ''
                }`}
                onClick={() => loadHistorySession(s.session_id)}
              >
                <span className="recentTitle">
                  {s.pdf_name ||
                    (s.last_search_mode === 'web' ? 'Web chat' : 'Chat')}
                </span>
                <span className="recentDate">{formatHistoryTime(s.last_at)}</span>
              </button>
            ))}
          </div>
        </div>

        <button type="button" className="profileRow" onClick={logout}>
          <span className="avatar">{userInitial || 'U'}</span>
          <span className="profileText">
            <span>{localStorage.getItem('authUsername') || 'User'}</span>
            <span>Sign out</span>
          </span>
        </button>
      </aside>

      <main className="gptMain">
        <header className="gptHeader" aria-label="Top bar">
          {!sidebarOpen ? (
            <button
              type="button"
              className="sidebarToggle floating"
              onClick={() => setSidebarOpen(true)}
              aria-label="Open sidebar"
              title="Open sidebar"
            >
              ◨
            </button>
          ) : null}

          <div className="appTitle">ChatGPT</div>

          <div className="segmented" role="tablist" aria-label="Work or Web">
            <button
              type="button"
              className={`segBtn ${searchMode === 'pdf' ? 'active' : ''}`}
              onClick={() => setSearchMode('pdf')}
              disabled={!pdfName}
              title={pdfName ? 'Work (PDF)' : 'Upload a PDF to enable Work mode'}
            >
              Work
            </button>
            <button
              type="button"
              className={`segBtn ${searchMode === 'web' ? 'active' : ''}`}
              onClick={() => setSearchMode('web')}
            >
              Web
            </button>
          </div>

          <button type="button" className="newChatBtn" onClick={startNewChat}>
            New chat
          </button>
        </header>

        <section className="content">
            {isEmpty ? (
              <>
                <section className="landing" aria-label="Landing">
                  <h1 className="greeting">What&apos;s on the agenda today?</h1>
                  <div className="promptShell" aria-label="Message composer">
                    <input
                      ref={fileInputRef}
                      type="file"
                      accept="application/pdf"
                      className="hiddenFile"
                      onChange={handleFileChange}
                    />

                    <button
                      type="button"
                      className="iconBtn"
                      onClick={handleUploadClick}
                      disabled={isBusy}
                      aria-label="Upload PDF"
                      title="Upload PDF"
                    >
                      +
                    </button>

                    <input
                      className="promptInput"
                      placeholder="Message Copilot"
                      value={input}
                      onChange={(e) => setInput(e.target.value)}
                      onKeyDown={(e) => {
                        if (e.key === 'Enter') {
                          e.preventDefault()
                          sendMessage(input)
                        }
                      }}
                      disabled={isBusy}
                    />

                    <button
                      type="button"
                      className="iconBtn ghost"
                      disabled
                      aria-label="Microphone"
                      title="Microphone"
                    >
                      <span aria-hidden="true">⌕</span>
                    </button>

                    <button
                      type="button"
                      className="sendBtn"
                      onClick={() => sendMessage(input)}
                      disabled={isBusy || !input.trim()}
                      aria-label="Send"
                      title="Send"
                    >
                      {isBusy ? '…' : '↑'}
                    </button>
                  </div>
                </section>

                <section className="ideas" aria-label="Ideas to try">
                  <h2 className="ideasTitle">Ideas to try</h2>
                  <div className="ideasGrid">
                    {ideas.map((idea) => (
                      <button
                        type="button"
                        key={idea.title}
                        className="ideaCard"
                        onClick={() => {
                          setInput(idea.prompt)
                        }}
                        disabled={isBusy}
                      >
                        <div className="ideaText">
                          <div className="ideaHeading">{idea.title}</div>
                          <div className="ideaPrompt">{idea.prompt}</div>
                        </div>
                      </button>
                    ))}
                  </div>
                </section>
              </>
            ) : (
              <section className="chatView" aria-label="Chat">
                <div className="chatTimeline" role="log" aria-live="polite">
                  {messages.map((m, idx) => (
                    <div
                      key={`${m.role}-${idx}`}
                      className={`bubble ${m.role === 'user' ? 'user' : 'assistant'}`}
                    >
                      {m.role === 'assistant' ? (
                        <>
                          {renderAssistant(m.content)}
                          {m.search_mode === 'web' ? renderSources(m.sources) : null}
                        </>
                      ) : (
                        m.content
                      )}
                    </div>
                  ))}
                  <div ref={messagesEndRef} />
                </div>

                <div className="composerDock" aria-label="Message composer">
                  <div className="promptShell">
                    <input
                      ref={fileInputRef}
                      type="file"
                      accept="application/pdf"
                      className="hiddenFile"
                      onChange={handleFileChange}
                    />

                    <button
                      type="button"
                      className="iconBtn"
                      onClick={handleUploadClick}
                      disabled={isBusy}
                      aria-label="Upload PDF"
                      title="Upload PDF"
                    >
                      +
                    </button>

                    <input
                      className="promptInput"
                      placeholder="Message Copilot"
                      value={input}
                      onChange={(e) => setInput(e.target.value)}
                      onKeyDown={(e) => {
                        if (e.key === 'Enter') {
                          e.preventDefault()
                          sendMessage(input)
                        }
                      }}
                      disabled={isBusy}
                    />

                    <button
                      type="button"
                      className="iconBtn ghost"
                      disabled
                      aria-label="Microphone"
                      title="Microphone"
                    >
                      <span aria-hidden="true">⌕</span>
                    </button>

                    <button
                      type="button"
                      className="sendBtn"
                      onClick={() => sendMessage(input)}
                      disabled={isBusy || !input.trim()}
                      aria-label="Send"
                      title="Send"
                    >
                      {isBusy ? '…' : '↑'}
                    </button>
                  </div>
                </div>
              </section>
            )}
        </section>
      </main>
    </div>
  )
}

export default ChatPage
