import React, { useState, useEffect, useRef } from 'react';
import axios from 'axios';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { useNavigate } from 'react-router-dom';
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
  const [provider, setProvider] = useState('openrouter');

  const logContainerRef = useRef(null);
  const navigate = useNavigate();

  // Axios interceptor for Auth
  useEffect(() => {
    const token = localStorage.getItem('token');
    if (token) {
      axios.defaults.headers.common['Authorization'] = `Bearer ${token}`;
    } else {
      navigate('/login');
    }
  }, [navigate]);

  useEffect(() => {
    const savedModel = localStorage.getItem('last_model');
    const savedProvider = localStorage.getItem('last_provider');
    if (savedModel) setModel(savedModel);
    if (savedProvider) setProvider(savedProvider);
  }, []);

  const handleModelChange = (e) => {
    const val = e.target.value;
    setModel(val);
    localStorage.setItem('last_model', val);
  };

  const handleProviderChange = (e) => {
    const val = e.target.value;
    setProvider(val);
    localStorage.setItem('last_provider', val);
    if (val === 'openai') setModel('gpt-4-turbo');
    if (val === 'groq') setModel('llama3-70b-8192');
    if (val === 'deepseek') setModel('deepseek-chat');
    if (val === 'openrouter') setModel('openai/gpt-4o');
  };

  useEffect(() => {
    if (logContainerRef.current) {
      logContainerRef.current.scrollTop = logContainerRef.current.scrollHeight;
    }
  }, [logs]);

  const fetchSessions = async () => {
    try {
      const response = await axios.get(`${API_BASE_URL}/api/sessions`);
      setSessions(response.data);
    } catch (error) {
      if (error.response?.status === 401) navigate('/login');
      console.error('Failed to fetch sessions:', error);
    }
  };

  useEffect(() => {
    fetchSessions();
  }, []);

  const loadSession = async (session) => {
    setSessionId(session.id);
    setStatus(session.status);
    setLogs([]);
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

  const stopTask = async () => {
    if (!sessionId) return;
    try {
      await axios.post(`${API_BASE_URL}/api/stop-task/${sessionId}`);
      setStatus('STOPPING'); // Optimistic
    } catch (e) {
      console.error("Failed to stop", e);
    }
  };

  const logout = () => {
    localStorage.removeItem('token');
    navigate('/login');
  };

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
          setLogs(prev => [...prev, `**ERROR:** ${message.content}`]);
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
    const apiKey = localStorage.getItem(`key_${provider}`);
    const systemMessage = localStorage.getItem('system_message');
    const tavilyKey = localStorage.getItem('key_tavily');

    if (!apiKey) {
      alert(`Please set your API Key for ${provider} in Settings first.`);
      setShowSettings(true);
      return;
    }

    if (!task) return;

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
        tavily_key: tavilyKey
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
      setLogs(prev => [...prev, `**Failed to start task:** ${error.message}`]);
    } finally {
      setLoading(false);
    }
  };

  const handleSendReply = async () => {
    if (!userInput.trim()) return;
    const currentInput = userInput;
    setLogs(prev => [...prev, `\n**You:** ${currentInput}\n`]);
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
      <div className="sidebar">
        <div className="sidebar-header">
          <span>History</span>
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
        </div>
        <div style={{borderTop:'1px solid #333', padding:'10px'}}>
            <button className="settings-btn" onClick={() => setShowSettings(!showSettings)} style={{width:'100%', margin:'0 0 10px 0'}}>
            ⚙️ Settings
            </button>
            <button className="settings-btn" onClick={logout} style={{width:'100%', margin:'0', border:'1px solid #d9534f', color:'#d9534f'}}>
            Logout
            </button>
        </div>
      </div>

      <div className="main-content">
        <header className="header" style={{display:'flex', justifyContent:'space-between', alignItems:'center'}}>
          <div style={{flex:1}}></div>
          <div style={{flex:2}}>
            <h1>🤖 AutoGen Enterprise</h1>
            <p>Autonomous Agent Team Builder</p>
          </div>
          <div style={{flex:1}}></div>
        </header>

        {showSettings ? (
          <Settings onBack={() => setShowSettings(false)} />
        ) : (
          <>
            {(!sessionId) && (
              <div className="card">
                <h2>New Task</h2>
                <div className="form-group">
                  <label>Provider & Model</label>
                  <div style={{display:'flex', gap:'10px'}}>
                    <select className="form-control" value={provider} onChange={handleProviderChange} style={{flex:1}}>
                        <option value="openrouter">OpenRouter</option>
                        <option value="openai">OpenAI</option>
                        <option value="groq">Groq</option>
                        <option value="deepseek">DeepSeek</option>
                    </select>
                    <input type="text" className="form-control" value={model} onChange={handleModelChange} style={{flex:2}} placeholder="Model ID"/>
                  </div>
                </div>
                <div className="form-group">
                  <label>Task</label>
                  <textarea className="form-control" rows="4" value={task} onChange={(e) => setTask(e.target.value)} placeholder="Describe the task..."/>
                </div>
                <button className="btn" onClick={handleSubmit} disabled={loading}>{loading ? 'Starting...' : 'Launch Team'}</button>
              </div>
            )}

            {sessionId && (
              <div className="card" style={{height: '80vh', display: 'flex', flexDirection: 'column'}}>
                <div style={{display:'flex', justifyContent:'space-between', alignItems:'center', marginBottom: '10px'}}>
                  <div style={{display:'flex', alignItems:'center'}}>
                      <h2 style={{margin:0, marginRight:'10px'}}>Log Stream</h2>
                      <span className={`status-badge ${getStatusClass(status)}`}>{status.replace(/_/g, ' ')}</span>
                  </div>
                  {(status === 'EXECUTING_TASK' || status === 'BUILDING_TEAM') && (
                      <button onClick={stopTask} style={{backgroundColor:'#d9534f', color:'white', border:'none', padding:'5px 10px', borderRadius:'4px', cursor:'pointer'}}>Stop Task</button>
                  )}
                </div>

                <div className="terminal-window" ref={logContainerRef} style={{flex:1, overflowY:'auto'}}>
                  {logs.length === 0 && <div style={{color: '#666', fontStyle: 'italic'}}>Waiting for logs...</div>}
                  {logs.map((log, index) => (
                    <div key={index} className="log-entry" style={{borderBottom:'1px solid #333', paddingBottom:'5px', marginBottom:'5px'}}>
                        <ReactMarkdown remarkPlugins={[remarkGfm]}>{log}</ReactMarkdown>
                    </div>
                  ))}
                </div>

                {status === 'WAITING_FOR_INPUT' && (
                  <div style={{marginTop: '15px', borderTop: '1px solid #eee', paddingTop: '15px'}}>
                    <label style={{display: 'block', marginBottom: '5px', fontWeight: 'bold', color: '#d9534f'}}>🔴 Input Required:</label>
                    <div style={{display: 'flex', gap: '10px'}}>
                      <input type="text" className="form-control" value={userInput} onChange={(e) => setUserInput(e.target.value)} onKeyPress={(e) => e.key === 'Enter' && handleSendReply()} autoFocus />
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
