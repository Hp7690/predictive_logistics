import { useState, useEffect, useRef } from 'react';
import { Routes, Route, Navigate } from 'react-router-dom';
import { api, getAuth, setAuth } from './api.js';
import { AuthCtx, useAuth } from './hooks.js';
import Layout from './components/Layout.jsx';
import Login from './pages/Login.jsx';
import Planner from './pages/Planner.jsx';
import Transport from './pages/Transport.jsx';
import Depot from './pages/Depot.jsx';
import Post from './pages/Post.jsx';
import Admin from './pages/Admin.jsx';

function Guard({ role, children }) {
  const { auth } = useAuth();
  if (!auth) return <Navigate to="/login" replace />;
  if (auth.role !== role) return <Navigate to={'/' + auth.role} replace />;
  return <Layout>{children}</Layout>;
}

export default function App() {
  const [auth, setA] = useState(getAuth());
  const [events, setEvents] = useState([]);
  const [tick, setTick] = useState(0);
  const [connected, setConnected] = useState(false);
  const wsRef = useRef(null);

  const login = async (username, password) => {
    const r = await api('/login', { method: 'POST', form: { username, password } });
    const a = { token: r.access_token, role: r.role, username };
    setAuth(a); setA(a);
    return a;
  };
  const logout = () => { setAuth(null); setA(null); setEvents([]); };

  useEffect(() => {
    if (!auth) return undefined;
    let closed = false, timer;
    const connect = () => {
      const proto = window.location.protocol === 'https:' ? 'wss' : 'ws';
      const ws = new WebSocket(`${proto}://${window.location.host}/api/ws?token=${auth.token}`);
      wsRef.current = ws;
      ws.onopen = () => setConnected(true);
      ws.onmessage = (m) => { const e = JSON.parse(m.data); setEvents((p) => [e, ...p].slice(0, 8)); setTick((t) => t + 1); };
      ws.onclose = () => { setConnected(false); if (!closed) timer = setTimeout(connect, 3000); };
    };
    connect();
    return () => { closed = true; clearTimeout(timer); wsRef.current && wsRef.current.close(); };
  }, [auth && auth.token]);

  return (
    <AuthCtx.Provider value={{ auth, login, logout, events, tick, connected }}>
      <Routes>
        <Route path="/login" element={<Login />} />
        <Route path="/planner" element={<Guard role="planner"><Planner /></Guard>} />
        <Route path="/transport" element={<Guard role="transport"><Transport /></Guard>} />
        <Route path="/depot" element={<Guard role="depot"><Depot /></Guard>} />
        <Route path="/post" element={<Guard role="post"><Post /></Guard>} />
        <Route path="/admin" element={<Guard role="admin"><Admin /></Guard>} />
        <Route path="*" element={<Navigate to={auth ? '/' + auth.role : '/login'} replace />} />
      </Routes>
    </AuthCtx.Provider>
  );
}
