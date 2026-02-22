import React, { useState, useEffect, useRef, useCallback } from 'react';
import axios from 'axios';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import './index.css';
import Settings from './Settings';

const API_BASE_URL = process.env.REACT_APP_API_URL || 'http://localhost:8000';
const WS_BASE_URL = API_BASE_URL.replace(/^http/, 'ws');

// ── Status helpers ─────────────────────────────────────────────────────────────
const STATUS_META = {
  IDLE: { label: 'Idle', color: '#6b7280', emoji: '💤' },
  BUILDING_TEAM: { label: 'Building Team…', color: '#f59e0b', emoji: '🔨' },
  EXECUTING_TASK: { label: 'Executing Task…', color: '#3b82f6', emoji: '⚙️' },
  WAITING_FOR_INPUT: { label: 'Waiting for you', color: '#8b5cf6', emoji: '💬' },
  STOPPING: { label: 'Stopping…', color: '#ef4444', emoji: '🛑' },
  COMPLETED: { label: 'Completed', color: '#10b981', emoji: '✅' },
  ERROR: { label: 'Error', color: '#ef4444', emoji: '❌' },
};

function StatusBadge({ status }) {
  const meta = STATUS_META[status] || STATUS_META.IDLE;
  return (
    <span className="status-badge" style={{ '--badge-color': meta.color }}>
      {meta.emoji} {meta.label}
    </span>
  );
}

// ── Log Renderer ─────────────────────────────────────────────────────────────
const chatRegex = /^([a-zA-Z0-9_-]+) \(to ([a-zA-Z0-9_-]+)\):\s*/;
const userRegex = /^User: /;

function LogRenderer({ log }) {
  let content = log;
  let sender = 'System';
  let receiver = null;
  let type = 'system';

  const chatMatch = log.match(chatRegex);
  if (chatMatch) {
    sender = chatMatch[1];
    receiver = chatMatch[2];
    content = log.replace(chatRegex, '');
    type = sender === 'User_Proxy' ? 'proxy' : 'assistant';
  } else if (log.match(userRegex)) {
    sender = 'You';
    content = log.replace(userRegex, '');
    type = 'user';
  } else if (log.includes('WAITING FOR USER INPUT')) {
    type = 'waiting';
  }

  const avatarMap = { user: '👤', assistant: '🤖', proxy: '🛡️', system: '⚙️', waiting: '💬' };

  return (
    <div className={`message-row ${type}`}>
      <div className={`avatar avatar-${type}`}>{avatarMap[type] || '⚙️'}</div>
      <div className="message-content">
        {type !== 'user' && (
          <div className="sender-name">
            {sender}
            {receiver && <span className="receiver-tag"> → {receiver}</span>}
          </div>
        )}
        {type === 'system' || type === 'waiting' ? (
          <div className="system-text">{content}</div>
        ) : (
          <ReactMarkdown remarkPlugins={[remarkGfm]}>{content}</ReactMarkdown>
        )}
      </div>
    </div>
  );
}

// ── Typing indicator ──────────────────────────────────────────────────────────
function TypingIndicator() {
  return (
    <div className="message-row system typing-row">
      <div className="avatar avatar-system">⚙️</div>
      <div className="message-content">
        <div className="typing-indicator">
          <span /><span /><span />
        </div>
      </div>
    </div>
  );
}

// ── Main App ──────────────────────────────────────────────────────────────────
function App() {
  const [model, setModel] = useState('openai/gpt-4o');
  const [task, setTask] = useState('');
  const [logs, setLogs] = useState([]);
  const [status, setStatus] = useState('IDLE');
  const [sessionId, setSessionId] = useState(null);
  const [userInput, setUserInput] = useState('');
  const [sessions, setSessions] = useState([]);
  const [loading, setLoading] = useState(false);
  const [showSettings, setShowSettings] = useState(false);
  const [provider, setProvider] = useState('openrouter');
  const [sidebarOpen, setSidebarOpen] = useState(true);
  const [wsConnected, setWsConnected] = useState(false);

  const logContainerRef = useRef(null);
  const wsRef = useRef(null);
  const reconnectTimerRef = useRef(null);

  // ── Persistence ─────────────────────────────────────────────────────────────
  useEffect(() => {
    const savedModel = localStorage.getItem('last_model');
    const savedProvider = localStorage.getItem('last_provider');
    if (savedModel) setModel(savedModel);
    if (savedProvider) setProvider(savedProvider);
  }, []);

  // ── Auto-scroll logs ─────────────────────────────────────────────────────────
  useEffect(() => {
    if (logContainerRef.current) {
      logContainerRef.current.scrollTop = logContainerRef.current.scrollHeight;
    }
  }, [logs]);

  // ── Fetch session list ───────────────────────────────────────────────────────
  const fetchSessions = useCallback(async () => {
    try {
      const res = await axios.get(`${API_BASE_URL}/api/sessions`);
      setSessions(res.data);
    } catch (err) {
      console.error('Failed to fetch sessions:', err);
    }
  }, []);

  useEffect(() => {
    fetchSessions();
    const interval = setInterval(fetchSessions, 15000); // Poll every 15s for status updates
    return () => clearInterval(interval);
  }, [fetchSessions]);

  // ── WebSocket with reconnect ─────────────────────────────────────────────────
  const connectWs = useCallback((sid) => {
    if (wsRef.current) {
      wsRef.current.close();
    }
    clearTimeout(reconnectTimerRef.current);

    const ws = new WebSocket(`${WS_BASE_URL}/ws/${sid}`);
    wsRef.current = ws;

    ws.onopen = () => setWsConnected(true);

    ws.onmessage = (event) => {
      try {
        const message = JSON.parse(event.data);
        if (message.type === 'log') {
          setLogs(prev => [...prev, message.content]);
        } else if (message.type === 'status') {
          setStatus(message.content);
          if (message.content === 'COMPLETED' || message.content === 'ERROR') {
            fetchSessions(); // Refresh sidebar
          }
        } else if (message.type === 'error') {
          setLogs(prev => [...prev, `**SYSTEM ERROR:** ${message.content}`]);
          setStatus('ERROR');
          fetchSessions();
        }
      } catch {
        setLogs(prev => [...prev, event.data]);
      }
    };

    ws.onerror = () => setWsConnected(false);

    ws.onclose = () => {
      setWsConnected(false);
      // Auto-reconnect if task is still running
      if (!['COMPLETED', 'ERROR', 'IDLE'].includes(status)) {
        reconnectTimerRef.current = setTimeout(() => connectWs(sid), 3000);
      }
    };
  }, [fetchSessions, status]);

  useEffect(() => {
    if (!sessionId) return;
    connectWs(sessionId);
    return () => {
      clearTimeout(reconnectTimerRef.current);
      if (wsRef.current) wsRef.current.close();
    };
  }, [sessionId]); // eslint-disable-line react-hooks/exhaustive-deps

  // ── Handlers ─────────────────────────────────────────────────────────────────
  const handleModelChange = (e) => {
    setModel(e.target.value);
    localStorage.setItem('last_model', e.target.value);
  };

  const handleProviderChange = (e) => {
    const val = e.target.value;
    setProvider(val);
    localStorage.setItem('last_provider', val);
    const defaults = {
      openai: 'gpt-4-turbo',
      groq: 'llama3-70b-8192',
      deepseek: 'deepseek-chat',
      openrouter: 'openai/gpt-4o',
    };
    if (defaults[val]) setModel(defaults[val]);
  };

  const loadSession = async (sess) => {
    setSessionId(sess.id);
    setStatus(sess.status);
    setLogs([]);
    setShowSettings(false);
    try {
      const res = await axios.get(`${API_BASE_URL}/api/sessions/${sess.id}/logs`);
      setLogs(res.data.map(l => l.content || l));
    } catch (e) {
      console.error('Failed to load session logs', e);
    }
  };

  const startNewSession = () => {
    setSessionId(null);
    setTask('');
    setLogs([]);
    setStatus('IDLE');
    setShowSettings(false);
    if (wsRef.current) wsRef.current.close();
  };

  const stopTask = async () => {
    if (!sessionId) return;
    try {
      await axios.post(`${API_BASE_URL}/api/stop-task/${sessionId}`);
      setStatus('STOPPING');
    } catch (e) {
      console.error('Failed to stop task', e);
    }
  };

  const handleSubmit = async (e) => {
    e.preventDefault();
    const apiKey = localStorage.getItem(`key_${provider}`);
    const systemMessage = localStorage.getItem('system_message');
    const tavilyKey = localStorage.getItem('key_tavily');

    if (!apiKey) {
      setShowSettings(true);
      return;
    }
    if (!task.trim()) return;

    setLoading(true);
    setLogs([]);
    setStatus('BUILDING_TEAM');

    try {
      const res = await axios.post(`${API_BASE_URL}/api/start-task`, {
        api_key: apiKey, model, task, provider,
        system_message: systemMessage || null,
        tavily_key: tavilyKey || null,
      });
      const newSid = res.data.session_id;
      setSessionId(newSid);
      setSessions(prev => [
        { id: newSid, task, status: 'BUILDING_TEAM', created_at: Date.now() / 1000, model },
        ...prev,
      ]);
    } catch (err) {
      setStatus('ERROR');
      setLogs([`**Failed to start task:** ${err.message}`]);
    } finally {
      setLoading(false);
    }
  };

  const handleSendReply = async () => {
    if (!userInput.trim() || status !== 'WAITING_FOR_INPUT') return;
    const msg = userInput;
    setUserInput('');
    setLogs(prev => [...prev, `User: ${msg}`]);
    try {
      await axios.post(`${API_BASE_URL}/api/reply`, { session_id: sessionId, message: msg });
    } catch (err) {
      console.error('Failed to send reply', err);
      setUserInput(msg);
    }
  };

  const isRunning = ['BUILDING_TEAM', 'EXECUTING_TASK', 'WAITING_FOR_INPUT'].includes(status);

  // ── Render ────────────────────────────────────────────────────────────────────
  return (
    <div className="app-container">
      {/* Sidebar toggle (mobile) */}
      <button
        className="sidebar-toggle"
        onClick={() => setSidebarOpen(v => !v)}
        title="Toggle sidebar"
      >
        {sidebarOpen ? '◀' : '▶'}
      </button>

      {/* Sidebar */}
      <aside className={`sidebar ${sidebarOpen ? 'open' : 'closed'}`}>
        <div className="sidebar-header">
          <button className="new-chat-btn" onClick={startNewSession}>
            ✦ New Task
          </button>
        </div>

        <div className="session-list">
          {sessions.length === 0 && (
            <p className="sidebar-empty">No sessions yet.<br />Start a task! 🚀</p>
          )}
          {sessions.map(sess => (
            <div
              key={sess.id}
              className={`session-item ${sessionId === sess.id ? 'active' : ''}`}
              onClick={() => loadSession(sess)}
            >
              <span className="session-task-name">
                {sess.task ? sess.task.substring(0, 36) : 'New Task'}
                {sess.task && sess.task.length > 36 && '…'}
              </span>
              <span className="session-meta">
                <StatusBadge status={sess.status} />
              </span>
            </div>
          ))}
        </div>

        <div className="settings-area">
          <button className="settings-btn" onClick={() => { setShowSettings(v => !v); setSessionId(null); }}>
            ⚙️ Settings
          </button>
        </div>
      </aside>

      {/* Main Area */}
      <main className="main-content">
        {/* Top Status Bar */}
        {sessionId && (
          <div className="top-bar">
            <span className="top-bar-title">
              {sessions.find(s => s.id === sessionId)?.task?.substring(0, 50) || 'Active Session'}
            </span>
            <div className="top-bar-actions">
              <StatusBadge status={status} />
              {wsConnected && <span className="ws-dot" title="Connected" />}
              {isRunning && (
                <button className="stop-btn" onClick={stopTask}>Stop ✕</button>
              )}
            </div>
          </div>
        )}

        {showSettings ? (
          <div className="settings-panel">
            <Settings onBack={() => setShowSettings(false)} />
          </div>
        ) : !sessionId ? (
          /* ── Welcome Screen ────────────────────────────────────────────── */
          <div className="welcome-screen">
            <div className="welcome-hero">
              <div className="hero-icon">🤖</div>
              <h1>AutoGen Enterprise</h1>
              <p className="hero-subtitle">Describe a task — AI agents will assemble and execute it.</p>
            </div>
            <form className="task-form" onSubmit={handleSubmit}>
              <div className="form-row">
                <div className="form-group">
                  <label>Provider</label>
                  <select className="form-control" value={provider} onChange={handleProviderChange}>
                    <option value="openrouter">OpenRouter</option>
                    <option value="openai">OpenAI</option>
                    <option value="groq">Groq</option>
                    <option value="deepseek">DeepSeek</option>
                  </select>
                </div>
                <div className="form-group" style={{ flex: 2 }}>
                  <label>Model ID</label>
                  <input
                    className="form-control"
                    value={model}
                    onChange={handleModelChange}
                    placeholder="e.g. openai/gpt-4o"
                  />
                </div>
              </div>

              <div className="form-group">
                <label>What should the agent team do?</label>
                <textarea
                  className="form-control task-textarea"
                  rows="4"
                  value={task}
                  onChange={(e) => setTask(e.target.value)}
                  placeholder="e.g. Research the latest AI trends and write a comprehensive report with sources."
                  onKeyDown={(e) => {
                    if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) handleSubmit(e);
                  }}
                />
                <small className="form-hint">Ctrl+Enter to start</small>
              </div>

              {!localStorage.getItem(`key_${provider}`) && (
                <div className="api-key-alert">
                  ⚠️ No API key set for <strong>{provider}</strong>.{' '}
                  <button type="button" onClick={() => setShowSettings(true)}>Configure in Settings →</button>
                </div>
              )}

              <button type="submit" className="btn btn-primary" disabled={loading || !task.trim()}>
                {loading ? <span className="btn-spinner" /> : '🚀 Start Task'}
              </button>
            </form>

            <div className="feature-chips">
              {['🌐 Web Search', '🐍 Code Execution', '💬 Human-in-the-Loop', '📦 Session History'].map(f => (
                <span key={f} className="chip">{f}</span>
              ))}
            </div>
          </div>
        ) : (
          /* ── Chat Interface ─────────────────────────────────────────────── */
          <>
            <div className="chat-area" ref={logContainerRef}>
              {logs.length === 0 && isRunning && <TypingIndicator />}
              {logs.map((log, i) => <LogRenderer key={i} log={log} />)}
              {isRunning && logs.length > 0 && status !== 'WAITING_FOR_INPUT' && <TypingIndicator />}
            </div>

            <div className="input-area">
              {status === 'WAITING_FOR_INPUT' && (
                <div className="input-hint">
                  🟣 The agents need your input to continue.
                </div>
              )}
              <div className="input-container">
                <input
                  className="chat-input"
                  value={userInput}
                  onChange={(e) => setUserInput(e.target.value)}
                  onKeyDown={(e) => e.key === 'Enter' && handleSendReply()}
                  placeholder={
                    status === 'WAITING_FOR_INPUT'
                      ? 'Type your reply and press Enter…'
                      : 'Waiting for agents…'
                  }
                  disabled={status !== 'WAITING_FOR_INPUT'}
                  autoFocus={status === 'WAITING_FOR_INPUT'}
                />
                <button
                  className="send-btn"
                  onClick={handleSendReply}
                  disabled={status !== 'WAITING_FOR_INPUT' || !userInput.trim()}
                >
                  ➤
                </button>
              </div>
            </div>
          </>
        )}
      </main>
    </div>
  );
}

export default App;
