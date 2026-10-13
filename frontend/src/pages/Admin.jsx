import { useState } from 'react';
import { api } from '../api.js';
import { useLoad, useAct } from '../hooks.js';
import { Card, Table, Notice, Err, Kpi } from '../components/ui.jsx';
import { EdgeTable, MlPanel } from '../components/Panels.jsx';

export default function Admin() {
  const users = useLoad(() => api('/users'));
  const log = useLoad(() => api('/audit?limit=100'));
  const health = useLoad(() => api('/health'));
  const nodes = useLoad(() => api('/edge-nodes'));
  const [f, setF] = useState({ username: '', password: '', role: 'planner', location_code: '' });
  const [msg, act] = useAct(() => [users, log].forEach((x) => x.reload()));
  const set = (k) => (e) => setF({ ...f, [k]: e.target.value });
  const h = health.data;
  return (
    <>
      <Card title="System health">
        <div className="kpis"><Kpi value={h ? h.status : '...'} label="API" /><Kpi value={h && h.postgis ? 'on' : 'off'} label="PostGIS" />
          <Kpi value={h && h.mqtt ? 'on' : 'off'} label="MQTT broker" /><Kpi value={(users.data || []).length} label="Users" /></div>
      </Card>
      <Card title="Users" span={6}>
        <Err e={users.err} />
        <Table rows={users.data} cols={[{ h: 'Username', f: (u) => u.username }, { h: 'Role', f: (u) => u.role }, { h: 'Location', f: (u) => u.location_id || '-' }]} />
      </Card>
      <Card title="Create user" span={6}>
        <div className="row">
          <input aria-label="Username" placeholder="Username" value={f.username} onChange={set('username')} />
          <input aria-label="Password" type="password" placeholder="Password (8+ chars)" value={f.password} onChange={set('password')} />
          <select aria-label="Role" value={f.role} onChange={set('role')}>{['admin', 'planner', 'transport', 'depot', 'post'].map((r) => <option key={r}>{r}</option>)}</select>
          <input aria-label="Location code" placeholder="Location (D1, P1...)" value={f.location_code} onChange={set('location_code')} style={{ width: 130 }} />
          <button className="primary" onClick={() => act(() => api('/users', { method: 'POST', body: { ...f, location_code: f.location_code || null } }), 'User created')}>Create</button>
        </div>
        <Notice msg={msg} />
      </Card>
      <Card title="Forecast model"><MlPanel /></Card>
      <Card title="Edge nodes"><EdgeTable nodes={nodes.data} /></Card>
      <Card title="Audit log (latest 100)" right={<button onClick={log.reload}>Refresh</button>}>
        <div className="scroll tall"><Table rows={log.data} cols={[{ h: 'Time', f: (a) => a.time }, { h: 'User', f: (a) => a.user }, { h: 'Action', f: (a) => a.action }]} /></div>
      </Card>
    </>
  );
}
