import React, { useState, useEffect, useRef } from 'react';
import axios from 'axios';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import './index.css';
import Settings from './Settings';

const API_BASE_URL = 'http://localhost:8000';

function LogRenderer({ log }) {
  // Regex to detect "Sender (to Receiver): Content"
  // Handles multiline content by matching the start
  const chatRegex = /^([a-zA-Z0-9_-]+) \(to ([a-zA-Z0-9_-]+)\):\s*/;
  const userRegex = /^User: /;

  let content = log;
  let sender = 'System';
  let receiver = null;
  let type = 'system'; // system, assistant, user

  const chatMatch = log.match(chatRegex);
  if (chatMatch) {
    sender = chatMatch[1];
    receiver = chatMatch[2];
    content = log.replace(chatRegex, '');
    type = 'assistant';
    if (sender === 'User_Proxy') type = 'user'; // Or treat User_Proxy as system/assistant depending on context
  } else if (log.match(userRegex)) {
    sender = 'You';
    content = log.replace(userRegex, '');
    type = 'user';
  } else if (log.includes("TERMINATE")) {
    type = 'system';
  }

  // Hide internal status messages unless verbose?
  // For now, render everything but styled differently

  return (
    <div className={`message-row ${type}`}>
      <div className={`avatar ${type === 'user' ? 'user' : type === 'assistant' ? 'ai' : 'sys'}`}>
        {type === 'user' ? '👤' : type === 'assistant' ? '🤖' : '⚙️'}
      </div>
      <div className="message-content">
        {type !== 'user' && <div className="sender-name">{sender} {receiver && <span style={{fontWeight:'normal', color:'#8e8ea0'}}>to {receiver}</span>}</div>}
        {type === 'system' ? (
           <div className="system-text">{content}</div>
        ) : (
           <ReactMarkdown remarkPlugins={[remarkGfm]}>{content}</ReactMarkdown>
        )}
      </div>
    </div>
  );
}

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

  // ... (Keep existing localStorage logic) ...
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
      setStatus('STOPPING');
    } catch (e) {
      console.error("Failed to stop", e);
    }
  };

  useEffect(() => {
    if (!sessionId) return;
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    const ws = new WebSocket(`${protocol}//localhost:8000/ws/${sessionId}`);

    ws.onmessage = (event) => {
      try {
        const message = JSON.parse(event.data);
        if (message.type === 'log') {
          setLogs(prev => [...prev, message.content]);
        } else if (message.type === 'status') {
          setStatus(message.content);
        } else if (message.type === 'error') {
          setLogs(prev => [...prev, `**SYSTEM ERROR:** ${message.content}`]);
          setStatus('ERROR');
        }
      } catch (e) {
        setLogs(prev => [...prev, event.data]);
      }
    };
    return () => ws.close();
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
        api_key: apiKey, model, task, provider, system_message: systemMessage, tavily_key: tavilyKey
      });
      const newSid = response.data.session_id;
      setSessionId(newSid);
      setSessions(prev => [{id: newSid, task, status: 'BUILDING_TEAM', created_at: Date.now()/1000}, ...prev]);
    } catch (error) {
      setStatus('ERROR');
      setLogs(prev => [...prev, `**Failed to start task:** ${error.message}`]);
    } finally {
      setLoading(false);
    }
  };

  const handleSendReply = async () => {
    if (!userInput.trim()) return;
    const currentInput = userInput;
    setLogs(prev => [...prev, `User: ${currentInput}`]); // Standardize format for parser
    setUserInput('');
    try {
      await axios.post(`${API_BASE_URL}/api/reply`, { session_id: sessionId, message: currentInput });
    } catch (error) {
      alert('Failed to send reply');
      setUserInput(currentInput);
    }
  };

  return (
    <div className="app-container">
      {/* Sidebar */}
      <div className="sidebar">
        <div className="sidebar-header">
          <button className="new-chat-btn" onClick={startNewSession}>New chat</button>
        </div>
        <div className="session-list">
          {sessions.map(sess => (
            <div key={sess.id} className={`session-item ${sessionId === sess.id ? 'active' : ''}`} onClick={() => loadSession(sess)}>
              <span style={{flex:1}}>{sess.task ? sess.task.substring(0, 30) : "New Task"}</span>
            </div>
          ))}
        </div>
        <div className="settings-area">
            <button className="settings-btn" onClick={() => setShowSettings(!showSettings)}>⚙️ Settings</button>
        </div>
      </div>

      {/* Main Area */}
      <div className="main-content">
        {status !== 'IDLE' && status !== 'COMPLETED' && status !== 'ERROR' && (
            <div className="status-bar">{status.replace(/_/g, ' ')}...</div>
        )}

        {showSettings ? (
          <div style={{padding:'20px', flex:1, overflowY:'auto'}}>
             <Settings onBack={() => setShowSettings(false)} />
          </div>
        ) : !sessionId ? (
          /* Welcome Screen */
          <div className="welcome-screen">
            <h1>AutoBuilder</h1>
            <div className="card-container">
              <div className="form-group">
                <label>Provider & Model</label>
                <div style={{display:'flex', gap:'10px'}}>
                  <select className="form-control" value={provider} onChange={handleProviderChange} style={{flex:1}}>
                      <option value="openrouter">OpenRouter</option>
                      <option value="openai">OpenAI</option>
                      <option value="groq">Groq</option>
                      <option value="deepseek">DeepSeek</option>
                  </select>
                  <input className="form-control" value={model} onChange={handleModelChange} style={{flex:1}} placeholder="Model ID"/>
                </div>
              </div>
              <div className="form-group">
                <label>What do you want to build?</label>
                <textarea className="form-control" rows="3" value={task} onChange={(e) => setTask(e.target.value)} placeholder="e.g. Create a snake game in python..."/>
              </div>
              <button className="btn" onClick={handleSubmit} disabled={loading} style={{width:'100%'}}>
                {loading ? 'Thinking...' : 'Start'}
              </button>
            </div>
          </div>
        ) : (
          /* Chat Interface */
          <>
            <div className="chat-area" ref={logContainerRef}>
                {logs.map((log, index) => <LogRenderer key={index} log={log} />)}
            </div>

            <div className="input-area">
                <div className="input-container">
                    <input
                        className="chat-input"
                        value={userInput}
                        onChange={(e) => setUserInput(e.target.value)}
                        onKeyPress={(e) => e.key === 'Enter' && handleSendReply()}
                        placeholder={status === 'WAITING_FOR_INPUT' ? "Type your reply..." : "Waiting for agents..."}
                        disabled={status !== 'WAITING_FOR_INPUT'}
                    />
                    <button className="send-btn" onClick={handleSendReply} disabled={status !== 'WAITING_FOR_INPUT'}>➤</button>
                </div>
                {(status === 'EXECUTING_TASK' || status === 'BUILDING_TEAM') && (
                    <div style={{textAlign:'center', marginTop:'10px'}}>
                        <button onClick={stopTask} style={{background:'none', border:'none', color:'#ef4444', cursor:'pointer', fontSize:'0.8rem'}}>Stop generating</button>
                    </div>
                )}
            </div>
          </>
        )}
      </div>
    </div>
  );
}

export default App;
