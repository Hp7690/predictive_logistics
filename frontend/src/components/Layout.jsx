import { useAuth } from '../hooks.js';

const NAMES = { admin: 'Super Admin', planner: 'Logistics Planner (HQ)', transport: 'Transport & Movement Control', depot: 'Depot Manager', post: 'Forward Post Commander' };

export default function Layout({ children }) {
  const { auth, logout, events, connected } = useAuth();
  return (
    <>
      <div className="tricolor" aria-hidden="true"><i /><i /><i /></div>
      <div className="classif">RESTRICTED | SIH 2026 PROTOTYPE | SYNTHETIC DATA | NORTHERN SECTOR PILOT</div>
      <header className="top">
        <div className="brand"><b>ASTRA-LOG</b><span>Predictive Logistics & Forward Supply Chain | Indian Army</span></div>
        <div className="who"><span className="role">{NAMES[auth.role]}</span><span className="mu">{auth.username}</span></div>
        <span className={`live ${connected ? 'on' : ''}`}>{connected ? 'LIVE' : 'OFFLINE'}</span>
        <button className="ghost" onClick={logout}>Log out</button>
      </header>
      <main className="grid">
        {children}
        <section className="card" style={{ gridColumn: 'span 12' }}>
          <div className="card-h"><h2>Live events</h2></div>
          {events.length ? <ul className="events">{events.map((e, i) => <li key={i} className={e.type}><b>{e.time}</b> {e.message}</li>)}</ul>
            : <p className="mu">No events yet. Actions by other users, SOS calls and edge-node link changes appear here instantly.</p>}
        </section>
      </main>
    </>
  );
}
