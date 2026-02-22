import React, { useState, useEffect } from 'react';

function Settings({ onBack }) {
  const [keys, setKeys] = useState({
    openrouter: '',
    openai: '',
    groq: '',
    anthropic: '',
    deepseek: '',
    gemini: ''
  });

  const [systemMessage, setSystemMessage] = useState('');

  useEffect(() => {
    // Load from localStorage
    setKeys({
      openrouter: localStorage.getItem('key_openrouter') || '',
      openai: localStorage.getItem('key_openai') || '',
      groq: localStorage.getItem('key_groq') || '',
      anthropic: localStorage.getItem('key_anthropic') || '',
      deepseek: localStorage.getItem('key_deepseek') || '',
      gemini: localStorage.getItem('key_gemini') || ''
    });
    setSystemMessage(localStorage.getItem('system_message') || '');
  }, []);

  const handleChange = (provider, value) => {
    setKeys(prev => ({ ...prev, [provider]: value }));
    localStorage.setItem(`key_${provider}`, value);
  };

  const handleSystemMessageChange = (e) => {
    const val = e.target.value;
    setSystemMessage(val);
    localStorage.setItem('system_message', val);
  };

  return (
    <div className="card">
      <div style={{display:'flex', justifyContent:'space-between', alignItems:'center'}}>
        <h2>⚙️ Settings</h2>
        <button className="btn" style={{backgroundColor: '#6c757d', padding: '5px 10px'}} onClick={onBack}>Close</button>
      </div>

      <h3>Global Instructions</h3>
      <div className="form-group">
        <label>System Prompt (Applied to all agents)</label>
        <textarea
          className="form-control"
          rows="3"
          value={systemMessage}
          onChange={handleSystemMessageChange}
          placeholder="e.g. Always answer in Portuguese. Be concise."
        />
      </div>

      <h3>API Keys</h3>

      <div className="form-group">
        <label>OpenRouter</label>
        <input
          type="password"
          className="form-control"
          value={keys.openrouter}
          onChange={(e) => handleChange('openrouter', e.target.value)}
          placeholder="sk-or-..."
        />
      </div>

      <div className="form-group">
        <label>OpenAI</label>
        <input
          type="password"
          className="form-control"
          value={keys.openai}
          onChange={(e) => handleChange('openai', e.target.value)}
          placeholder="sk-..."
        />
      </div>

      <div className="form-group">
        <label>Groq</label>
        <input
          type="password"
          className="form-control"
          value={keys.groq}
          onChange={(e) => handleChange('groq', e.target.value)}
          placeholder="gsk_..."
        />
      </div>

      <div className="form-group">
        <label>DeepSeek</label>
        <input
          type="password"
          className="form-control"
          value={keys.deepseek}
          onChange={(e) => handleChange('deepseek', e.target.value)}
          placeholder="sk-..."
        />
      </div>

      {/* Note: Anthropic and Gemini often require specific client libs or proxies.
          For now, we store them, but backend support depends on implementation. */}

      {/*
      <div className="form-group">
        <label>Anthropic (Claude)</label>
        <input
          type="password"
          className="form-control"
          value={keys.anthropic}
          onChange={(e) => handleChange('anthropic', e.target.value)}
          placeholder="sk-ant-..."
        />
      </div>
       */}

      <div style={{marginTop: '20px', color: '#666', fontSize: '0.9rem'}}>
        Keys are stored locally in your browser.
      </div>
    </div>
  );
}

export default Settings;
