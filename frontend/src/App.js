import React, { useState, useEffect, useRef } from 'react';
import axios from 'axios';
import './index.css';

const API_BASE_URL = 'http://localhost:8000';

function App() {
  const [apiKey, setApiKey] = useState('');
  const [model, setModel] = useState('openai/gpt-4o');
  const [task, setTask] = useState('');
  const [logs, setLogs] = useState([]);
  const [status, setStatus] = useState('IDLE');
  const [sessionId, setSessionId] = useState(null);
  const [userInput, setUserInput] = useState('');
  const [sessions, setSessions] = useState([]);
  const [loading, setLoading] = useState(false);
  const logContainerRef = useRef(null);

  // Load API Key and Model from localStorage on mount
  useEffect(() => {
    const savedApiKey = localStorage.getItem('openRouterApiKey');
    const savedModel = localStorage.getItem('openRouterModel');
    if (savedApiKey) setApiKey(savedApiKey);
    if (savedModel) setModel(savedModel);
  }, []);

  // Save on change
  const handleApiKeyChange = (e) => {
    const val = e.target.value;
    setApiKey(val);
    localStorage.setItem('openRouterApiKey', val);
  };

  const handleModelChange = (e) => {
    const val = e.target.value;
    setModel(val);
    localStorage.setItem('openRouterModel', val);
  };

  // Auto-scroll logic
  useEffect(() => {
    if (logContainerRef.current) {
      logContainerRef.current.scrollTop = logContainerRef.current.scrollHeight;
    }
  }, [logs]);

  // Fetch Sessions
  const fetchSessions = async () => {
    try {
      const response = await axios.get(`${API_BASE_URL}/api/sessions`);
      setSessions(response.data);
    } catch (error) {
      console.error('Failed to fetch sessions:', error);
    }
  };

  useEffect(() => {
    fetchSessions();
  }, []);

  // Load Session Logic
  const loadSession = async (session) => {
    setSessionId(session.id);
    setStatus(session.status);
    setLogs([]); // Clear previous logs first

    try {
      const logRes = await axios.get(`${API_BASE_URL}/api/sessions/${session.id}/logs`);
      // Parse logs - they are stored as JSON strings in Redis list
      const parsedLogs = logRes.data.map(l => {
         return l.content || l;
      });
      setLogs(parsedLogs);
    } catch (e) {
      console.error("Failed to load logs", e);
    }
  };

  const startNewSession = () => {
    setSessionId(null);
    setTask('');
    setLogs([]);
    setStatus('IDLE');
  };

  // WebSocket Connection
  useEffect(() => {
    if (!sessionId) return;

    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    const ws = new WebSocket(`${protocol}//localhost:8000/ws/${sessionId}`);

    ws.onopen = () => {
      console.log('Connected to log stream');
    };

    ws.onmessage = (event) => {
      try {
        const message = JSON.parse(event.data);
        if (message.type === 'log') {
          setLogs(prev => [...prev, message.content]);
        } else if (message.type === 'status') {
          setStatus(message.content);
        } else if (message.type === 'error') {
          setLogs(prev => [...prev, `ERROR: ${message.content}`]);
          setStatus('ERROR');
        }
      } catch (e) {
        // Fallback
        setLogs(prev => [...prev, event.data]);
      }
    };

    ws.onclose = () => {
      console.log('Disconnected from log stream');
    };

    return () => {
      ws.close();
    };
  }, [sessionId]);

  const handleSubmit = async (e) => {
    e.preventDefault();
    if (!apiKey || !task) {
      alert('Please fill in all fields');
      return;
    }

    setLoading(true);
    setLogs([]);
    setStatus('BUILDING_TEAM');

    try {
      const response = await axios.post(`${API_BASE_URL}/api/start-task`, {
        api_key: apiKey,
        model: model,
        task: task
      });

      const newSid = response.data.session_id;
      setSessionId(newSid);

      // Add to session list optimistically
      setSessions(prev => [{
          id: newSid,
          task: task,
          status: 'BUILDING_TEAM',
          created_at: Date.now() / 1000
      }, ...prev]);

    } catch (error) {
      console.error('Error starting task:', error);
      setStatus('ERROR');
      setLogs(prev => [...prev, `Failed to start task: ${error.message}`]);
    } finally {
      setLoading(false);
    }
  };

  const handleSendReply = async () => {
    if (!userInput.trim()) return;

    const currentInput = userInput;
    // Optimistic UI update
    setLogs(prev => [...prev, `\nYou: ${currentInput}\n`]);
    setUserInput('');

    try {
      await axios.post(`${API_BASE_URL}/api/reply`, {
        session_id: sessionId,
        message: currentInput
      });
    } catch (error) {
      console.error('Error sending reply:', error);
      alert('Failed to send reply');
      setUserInput(currentInput);
    }
  };

  const getStatusClass = (status) => {
    switch (status) {
      case 'IDLE': return 'status-idle';
      case 'BUILDING_TEAM': return 'status-building';
      case 'EXECUTING_TASK': return 'status-executing';
      case 'WAITING_FOR_INPUT': return 'status-waiting';
      case 'COMPLETED': return 'status-completed';
      case 'ERROR': return 'status-error';
      default: return 'status-idle';
    }
  };

  return (
    <div className="app-container">
      {/* Sidebar */}
      <div className="sidebar">
        <div className="sidebar-header">
          <span>Sessions</span>
          <button className="new-chat-btn" onClick={startNewSession} style={{width:'auto', padding:'4px 8px', fontSize:'0.8rem', marginLeft:'10px'}}>+</button>
        </div>
        <div className="session-list">
          {sessions.map(sess => (
            <div
              key={sess.id}
              className={`session-item ${sessionId === sess.id ? 'active' : ''}`}
              onClick={() => loadSession(sess)}
            >
              <div style={{fontWeight: 'bold'}}>{sess.task ? sess.task.substring(0, 25) + (sess.task.length > 25 ? '...' : '') : "New Task"}</div>
              <div className="session-time">
                {new Date(sess.created_at * 1000).toLocaleString()}
              </div>
            </div>
          ))}
          {sessions.length === 0 && <div style={{padding:'10px', color:'#666', fontSize:'0.8rem'}}>No history yet.</div>}
        </div>
      </div>

      {/* Main Content */}
      <div className="main-content">
        <header className="header">
          <h1>🤖 AutoGen Production App</h1>
          <p>Autonomous Agent Team Builder & Executor</p>
        </header>

        {/* Configuration Form - Only show if not viewing a running session history or creating new */}
        {(!sessionId) && (
          <div className="card">
            <h2>New Task Configuration</h2>
            <div className="form-group">
              <label>OpenRouter API Key</label>
              <input
                type="password"
                className="form-control"
                value={apiKey}
                onChange={handleApiKeyChange}
                placeholder="sk-or-..."
              />
            </div>

            <div className="form-group">
              <label>Model (OpenRouter ID)</label>
              <input
                type="text"
                className="form-control"
                value={model}
                onChange={handleModelChange}
                placeholder="e.g. openai/gpt-4o or anthropic/claude-3.5-sonnet"
              />
            </div>

            <div className="form-group">
              <label>Task Description</label>
              <textarea
                className="form-control"
                rows="4"
                value={task}
                onChange={(e) => setTask(e.target.value)}
                placeholder="Describe the complex task you want the agent team to solve..."
              />
            </div>

            <button
              className="btn"
              onClick={handleSubmit}
              disabled={loading}
            >
              {loading ? 'Starting...' : 'Build Team & Execute'}
            </button>
          </div>
        )}

        {/* Live Logs - Show if session active */}
        {sessionId && (
          <div className="card">
            <div style={{display:'flex', justifyContent:'space-between', alignItems:'center', marginBottom: '10px'}}>
              <h2>Execution Logs</h2>
              <span className={`status-badge ${getStatusClass(status)}`}>
                {status.replace(/_/g, ' ')}
              </span>
            </div>

            <div className="terminal-window" ref={logContainerRef}>
              {logs.length === 0 && <div style={{color: '#666', fontStyle: 'italic'}}>Waiting for logs...</div>}
              {logs.map((log, index) => (
                <div key={index} className="log-entry">{log}</div>
              ))}
            </div>

            {/* Interaction Area */}
            {status === 'WAITING_FOR_INPUT' && (
              <div style={{marginTop: '15px', borderTop: '1px solid #eee', paddingTop: '15px'}}>
                <label style={{display: 'block', marginBottom: '5px', fontWeight: 'bold', color: '#d9534f'}}>
                  🔴 The agents are waiting for your input:
                </label>
                <div style={{display: 'flex', gap: '10px'}}>
                  <input
                    type="text"
                    className="form-control"
                    value={userInput}
                    onChange={(e) => setUserInput(e.target.value)}
                    onKeyPress={(e) => e.key === 'Enter' && handleSendReply()}
                    placeholder="Type your response here..."
                    autoFocus
                  />
                  <button className="btn" onClick={handleSendReply}>Send</button>
                </div>
              </div>
            )}

            {status === 'COMPLETED' && (
                <div style={{marginTop: '10px', textAlign: 'center'}}>
                    <button className="btn" onClick={startNewSession}>Start New Task</button>
                </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
}

export default App;
