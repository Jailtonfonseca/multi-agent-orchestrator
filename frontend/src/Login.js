import React, { useState } from 'react';
import axios from 'axios';
import { useNavigate, Link } from 'react-router-dom';

const API_BASE_URL = 'http://localhost:8000';

function Login() {
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [isRegistering, setIsRegistering] = useState(false);
  const [error, setError] = useState('');
  const navigate = useNavigate();

  const handleSubmit = async (e) => {
    e.preventDefault();
    setError('');

    try {
      if (isRegistering) {
        await axios.post(`${API_BASE_URL}/auth/register`, { username, password });
        // Auto login after register
        const res = await axios.post(`${API_BASE_URL}/auth/login`,
          new URLSearchParams({ username, password }),
          { headers: { 'Content-Type': 'application/x-www-form-urlencoded' } }
        );
        localStorage.setItem('token', res.data.access_token);
      } else {
        const res = await axios.post(`${API_BASE_URL}/auth/login`,
          new URLSearchParams({ username, password }),
          { headers: { 'Content-Type': 'application/x-www-form-urlencoded' } }
        );
        localStorage.setItem('token', res.data.access_token);
      }
      navigate('/');
    } catch (err) {
      setError(err.response?.data?.detail || 'Authentication failed');
    }
  };

  return (
    <div style={{display:'flex', justifyContent:'center', alignItems:'center', height:'100vh', backgroundColor:'#f0f2f5'}}>
      <div className="card" style={{width:'350px'}}>
        <h2 style={{textAlign:'center'}}>{isRegistering ? 'Register' : 'Login'}</h2>
        {error && <div style={{color:'red', marginBottom:'10px', textAlign:'center'}}>{error}</div>}
        <form onSubmit={handleSubmit}>
          <div className="form-group">
            <label>Username</label>
            <input className="form-control" type="text" value={username} onChange={e => setUsername(e.target.value)} required />
          </div>
          <div className="form-group">
            <label>Password</label>
            <input className="form-control" type="password" value={password} onChange={e => setPassword(e.target.value)} required />
          </div>
          <button className="btn" style={{width:'100%'}} type="submit">
            {isRegistering ? 'Sign Up' : 'Sign In'}
          </button>
        </form>
        <div style={{marginTop:'15px', textAlign:'center', fontSize:'0.9rem'}}>
          <span style={{color:'#007bff', cursor:'pointer'}} onClick={() => setIsRegistering(!isRegistering)}>
            {isRegistering ? 'Already have an account? Login' : 'Need an account? Register'}
          </span>
        </div>
      </div>
    </div>
  );
}

export default Login;
