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
  const logContainerRef = useRef(null);

  // Auto-scroll logic
  useEffect(() => {
    if (logContainerRef.current) {
      logContainerRef.current.scrollTop = logContainerRef.current.scrollHeight;
    }
  }, [logs]);

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
        // Only append if it's not a status JSON that failed to parse (unlikely)
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

    setLogs([]);
    setStatus('BUILDING_TEAM');

    try {
      const response = await axios.post(`${API_BASE_URL}/api/start-task`, {
        api_key: apiKey,
        model: model,
        task: task
      });

      setSessionId(response.data.session_id);
    } catch (error) {
      console.error('Error starting task:', error);
      setStatus('ERROR');
      setLogs(prev => [...prev, `Failed to start task: ${error.message}`]);
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
    <div className="container">
      <header className="header">
        <h1>🤖 AutoGen Production App</h1>
        <p>Autonomous Agent Team Builder & Executor</p>
      </header>

      <div className="card">
        <h2>Configuration</h2>
        <div className="form-group">
          <label>OpenRouter API Key</label>
          <input
            type="password"
            className="form-control"
            value={apiKey}
            onChange={(e) => setApiKey(e.target.value)}
            placeholder="sk-or-..."
          />
        </div>

        <div className="form-group">
          <label>Model</label>
          <select
            className="form-control"
            value={model}
            onChange={(e) => setModel(e.target.value)}
          >
            <option value="openai/gpt-4o">GPT-4o (OpenAI)</option>
            <option value="anthropic/claude-3.5-sonnet">Claude 3.5 Sonnet (Anthropic)</option>
            <option value="google/gemini-pro-1.5">Gemini Pro 1.5 (Google)</option>
            <option value="meta-llama/llama-3-70b-instruct">Llama 3 70B (Meta)</option>
          </select>
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
          disabled={status === 'BUILDING_TEAM' || status === 'EXECUTING_TASK' || status === 'WAITING_FOR_INPUT'}
        >
          {status === 'IDLE' || status === 'COMPLETED' || status === 'ERROR' ? 'Build Team & Execute' : 'Processing...'}
        </button>

        <span className={`status-badge ${getStatusClass(status)}`} style={{marginLeft: '15px'}}>
          {status.replace(/_/g, ' ')}
        </span>
      </div>

      <div className="card">
        <h2>Live Execution Logs</h2>
        <div className="terminal-window" ref={logContainerRef}>
          {logs.length === 0 && <div style={{color: '#666', fontStyle: 'italic'}}>Waiting for execution...</div>}
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
      </div>
    </div>
  );
}

export default App;
