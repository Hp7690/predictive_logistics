import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useAuth } from '../hooks.js';

const DEMO = [['planner', 'HQ planner'], ['transport', 'Movement control'], ['depot', 'Depot'], ['post', 'Forward post'], ['admin', 'Admin']];

export default function Login() {
  const { login } = useAuth();
  const nav = useNavigate();
  const [u, setU] = useState('');
  const [p, setP] = useState('');
  const [err, setErr] = useState('');
  const [busy, setBusy] = useState(false);
  const go = async (e) => {
    e.preventDefault(); setBusy(true); setErr('');
    try { const a = await login(u.trim(), p); nav('/' + a.role); } catch (x) { setErr(x.message); }
    setBusy(false);
  };
  return (
    <div className="login-wrap">
      <div className="tricolor" aria-hidden="true"><i /><i /><i /></div>
      <form className="card login" onSubmit={go}>
        <h1 className="logo">ASTRA-LOG</h1>
        <p className="tag">Predictive Logistics & Forward Supply Chain</p>
        <p className="mu">Indian Army | AI + GIS + IoT | Team VisionGuard 2.0 | SIH26251</p>
        <label>Username<input value={u} onChange={(e) => setU(e.target.value)} autoComplete="username" /></label>
        <label>Password<input type="password" value={p} onChange={(e) => setP(e.target.value)} autoComplete="current-password" /></label>
        <button className="primary" disabled={busy}>{busy ? 'Signing in...' : 'Sign in'}</button>
        {err && <div className="notice bad" role="alert">{err}</div>}
        <p className="mu">Demo accounts (click to fill):</p>
        <div className="row">{DEMO.map(([d, t]) => <button type="button" key={d} onClick={() => { setU(d); setP(d + '123'); }} title={t}>{d}</button>)}</div>
        <p className="mu">Restricted prototype. All data is synthetic.</p>
      </form>
    </div>
  );
}
