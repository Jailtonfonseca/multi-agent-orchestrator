import React, { useState, useEffect, useRef } from 'react';
import axios from 'axios';
import './index.css';
import Settings from './Settings';

const API_BASE_URL = 'http://localhost:8000';

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

  // New State for Provider
  const [provider, setProvider] = useState('openrouter');

  const logContainerRef = useRef(null);

  // Load defaults from localStorage
  useEffect(() => {
    const savedModel = localStorage.getItem('last_model');
    const savedProvider = localStorage.getItem('last_provider');
    if (savedModel) setModel(savedModel);
    if (savedProvider) setProvider(savedProvider);
  }, []);

  // Save on change
  const handleModelChange = (e) => {
    const val = e.target.value;
    setModel(val);
    localStorage.setItem('last_model', val);
  };

  const handleProviderChange = (e) => {
    const val = e.target.value;
    setProvider(val);
    localStorage.setItem('last_provider', val);

    // Suggest default models based on provider
    if (val === 'openai') setModel('gpt-4-turbo');
    if (val === 'groq') setModel('llama3-70b-8192');
    if (val === 'deepseek') setModel('deepseek-chat');
    if (val === 'openrouter') setModel('openai/gpt-4o');
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
    setShowSettings(false);

    try {
      const logRes = await axios.get(`${API_BASE_URL}/api/sessions/${session.id}/logs`);
      const parsedLogs = logRes.data.map(l => l.content || l);
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
    setShowSettings(false);
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

    // Get API Key from localStorage based on provider
    const apiKey = localStorage.getItem(`key_${provider}`);
    const systemMessage = localStorage.getItem('system_message');
    const tavilyKey = localStorage.getItem('key_tavily'); // Retrieve Tavily Key

    if (!apiKey) {
      alert(`Please set your API Key for ${provider} in Settings first.`);
      setShowSettings(true);
      return;
    }

    if (!task) {
      alert('Please describe a task.');
      return;
    }

    setLoading(true);
    setLogs([]);
    setStatus('BUILDING_TEAM');

    try {
      const response = await axios.post(`${API_BASE_URL}/api/start-task`, {
        api_key: apiKey,
        model: model,
        task: task,
        provider: provider,
        system_message: systemMessage,
        tavily_key: tavilyKey // Pass Tavily key
      });

      const newSid = response.data.session_id;
      setSessionId(newSid);

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

        {/* Settings Button at Bottom */}
        <button className="settings-btn" onClick={() => setShowSettings(!showSettings)}>
          ⚙️ Settings
        </button>
      </div>

      {/* Main Content */}
      <div className="main-content">
        <header className="header">
          <h1>🤖 AutoGen Production App</h1>
          <p>Autonomous Agent Team Builder & Executor</p>
        </header>

        {/* If Settings is active, show Settings Component */}
        {showSettings ? (
          <Settings onBack={() => setShowSettings(false)} />
        ) : (
          <>
            {/* Configuration Form - Only show if not viewing a running session history or creating new */}
            {(!sessionId) && (
              <div className="card">
                <h2>New Task Configuration</h2>

                <div className="form-group">
                  <label>LLM Provider</label>
                  <select
                    className="form-control"
                    value={provider}
                    onChange={handleProviderChange}
                  >
                    <option value="openrouter">OpenRouter (Supports all models)</option>
                    <option value="openai">OpenAI (Official)</option>
                    <option value="groq">Groq (Fast Inference)</option>
                    <option value="deepseek">DeepSeek (Official)</option>
                  </select>
                </div>

                <div className="form-group">
                  <label>Model ID / Name</label>
                  <input
                    type="text"
                    className="form-control"
                    value={model}
                    onChange={handleModelChange}
                    placeholder={provider === 'openrouter' ? "e.g. openai/gpt-4o" : "e.g. gpt-4-turbo"}
                  />
                  <small style={{color:'#666'}}>
                    {provider === 'openrouter' && "Use full ID like 'openai/gpt-4o' or 'anthropic/claude-3-opus'."}
                    {provider === 'openai' && "e.g. 'gpt-4o', 'gpt-4-turbo', 'gpt-3.5-turbo'."}
                    {provider === 'groq' && "e.g. 'llama3-70b-8192', 'mixtral-8x7b-32768'."}
                    {provider === 'deepseek' && "e.g. 'deepseek-chat', 'deepseek-coder'."}
                  </small>
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
          </>
        )}
      </div>
    </div>
  );
}

export default App;
