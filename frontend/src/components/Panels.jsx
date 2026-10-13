import { useState } from 'react';
import { BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, Legend, ResponsiveContainer } from 'recharts';
import { api } from '../api.js';
import { useLoad, useAct } from '../hooks.js';
import { Gauge, Pill, Table, Notice, Err, Kpi, ModeBadge, riskLabel } from './ui.jsx';
import { ITEMS } from './icons.jsx';

export function PostStatus({ code, dos, locs }) {
  const rows = (dos || []).filter((r) => r.post === code);
  const l = (locs || []).find((x) => x.code === code);
  if (!l) return <p className="mu">Select a post on the map.</p>;
  return (
    <div>
      <h3 className="sub">{l.name}</h3>
      <p className="mu">{l.alt} m altitude{l.mule ? ' | mule track available' : ''}</p>
      {ITEMS.map((i) => { const r = rows.find((x) => x.item === i); return r ? <Gauge key={i} item={i} pct={r.fill_pct} dos={r.dos} /> : null; })}
      <p className="mu">Bar = stock vs a full 14-day holding. Right: days of supply.</p>
    </div>
  );
}

export function RouteModes({ post, snow }) {
  const o = useLoad(() => api(`/routes/options/${post}?kg=1500${snow ? `&snow_cm=${snow}` : ''}`), [post, snow]);
  const d = o.data;
  return (
    <div>
      <Err e={o.err} />
      {d && <>
        <h3 className="sub">Road routes to {post}</h3>
        <Table rows={d.routes} cols={[
          { h: 'Route', f: (r) => `${String.fromCharCode(65 + d.routes.indexOf(r))}${r.best ? ' ★' : ''}` },
          { h: 'Via', f: (r) => r.via }, { h: 'From', f: (r) => r.depot_name.replace(' Depot', '') }, { h: 'km', f: (r) => r.km },
          { h: 'ETA h', f: (r) => r.eta_h }, { h: 'Risk', f: (r) => <span className={`risk ${riskLabel(r.risk)}`}>{riskLabel(r.risk)} {Math.round(r.risk * 100)}%</span> },
          { h: 'Status', f: (r) => (r.open ? 'open' : <b className="bad-t">CLOSED{r.pass ? ` (${r.pass})` : ''}</b>) }]} />
        <h3 className="sub">Transport mode (1500 kg, critical)</h3>
        <Table rows={d.modes} cols={[
          { h: 'Mode', f: (o2) => <ModeBadge mode={o2.mode} /> }, { h: 'ETA h', f: (o2) => o2.eta_h ?? '-' }, { h: 'Capacity', f: (o2) => `${o2.capacity_kg} kg x ${o2.units}` },
          { h: 'Why', f: (o2) => o2.reason }, { h: '', f: (o2) => (o2.recommended ? <span className="pill ok">Recommended</span> : !o2.feasible ? <span className="pill warning">Not feasible</span> : '') }]} />
      </>}
    </div>
  );
}

export function EdgeTable({ nodes, onToggle }) {
  return (
    <Table rows={nodes} empty="No edge nodes." cols={[
      { h: 'Node', f: (n) => n.code }, { h: 'Site', f: (n) => n.name }, { h: 'Link', f: (n) => n.link },
      { h: 'State', f: (n) => (n.online ? (n.stale ? <span className="pill warning">No data</span> : <span className="pill ok">Online</span>) : <span className="pill critical">Offline (local cache)</span>) },
      { h: 'Buffered', f: (n) => n.buffered }, { h: 'Battery', f: (n) => `${Math.round(n.battery)}%` }, { h: 'RFID tags', f: (n) => n.rfid_tags },
      ...(onToggle ? [{ h: '', f: (n) => <button onClick={() => onToggle(n)}>{n.online ? 'Cut link' : 'Restore link'}</button> }] : [])]} />
  );
}

export function WeatherTable({ rows }) {
  return <Table rows={rows} empty="No weather data." cols={[
    { h: 'Post', f: (w) => w.name }, { h: 'Date', f: (w) => w.date }, { h: 'Snow today', f: (w) => `${w.snow_cm} cm` }, { h: 'Snow 3 d', f: (w) => `${w.snow_3d_cm} cm` },
    { h: 'Visibility', f: (w) => `${w.vis_km} km` }, { h: 'Temp', f: (w) => `${w.temp_c} C` }]} />;
}

export function MlPanel() {
  const st = useLoad(() => api('/ml/status'));
  const [msg, act] = useAct(() => st.reload());
  const d = st.data || {}, rows = Object.entries(d.metrics || {}).map(([k, v]) => ({ item: k, ...v }));
  return (
    <div>
      <div className="row">
        <button className="primary" disabled={d.training} onClick={() => act(() => api('/ml/retrain', { method: 'POST' }), 'Retraining started. This takes 1-2 minutes.')}>{d.training ? 'Training...' : 'Retrain on latest data'}</button>
        <span className="mu">Last trained: {d.trained_at || 'never'}</span>
      </div>
      <Notice msg={msg} /><Err e={st.err || d.error} />
      <Table rows={rows} cols={[{ h: 'Item', f: (r) => r.item }, { h: 'Daily MAPE %', f: (r) => r['daily_MAPE_%'] }, { h: 'Baseline MAPE %', f: (r) => r['naive_daily_MAPE_%'] },
        { h: '14-day total MAPE %', f: (r) => r['14d_total_MAPE_%'] }, { h: '80% band coverage %', f: (r) => r['80%_band_coverage_%'] }]} />
      <p className="mu">Feedback loop: actual consumption logged by posts and depots is added to the data and used at every retrain. Model: XGBoost quantile forecasts.</p>
    </div>
  );
}

export function KpiPanel() {
  const k = useLoad(() => api('/kpis'));
  const d = k.data;
  if (!d) return <Err e={k.err} />;
  const chart = Object.entries(d.targets_pct_of_baseline).map(([name, v]) => ({ name, Current: 100, 'ASTRA-LOG target': v }));
  return (
    <div>
      <div className="kpis">
        <Kpi value={d.critical_lines} label="Critical stock lines" tone="red" /><Kpi value={`${d.stockout_risk_pct}%`} label="Stock-out risk (lines < 3 d)" />
        <Kpi value={d.avg_dos} label="Average days of supply" /><Kpi value={d.mape_pct != null ? `${d.mape_pct}%` : '-'} label="Forecast error (MAPE)" />
        <Kpi value={d.avg_first_stop_eta_h != null ? `${d.avg_first_stop_eta_h} h` : '-'} label="Avg lead time, first stop" />
      </div>
      <ResponsiveContainer width="100%" height={260}>
        <BarChart data={chart}><CartesianGrid strokeDasharray="3 3" stroke="#3a4630" /><XAxis dataKey="name" stroke="#9aa58a" /><YAxis stroke="#9aa58a" /><Tooltip /><Legend />
          <Bar dataKey="Current" fill="#6b705f" /><Bar dataKey="ASTRA-LOG target" fill="#c9b27c" /></BarChart>
      </ResponsiveContainer>
      <p className="mu">Logistics performance, % of today's baseline. Targets are illustrative and to be validated in the pilot via MAPE, stock-out rate and lead time. Left cards are measured live from this system.</p>
    </div>
  );
}

export function Timeline() {
  const steps = [['Demand forecast', 'Daily'], ['Shortfall alert', 'Instant'], ['Route planned', 'Minutes'], ['Convoy dispatched', 'Same day'], ['Delivery logged', 'Automatic']];
  return <div className="timeline">{steps.map(([a, b], i) => <div key={a} className="step"><b>{i + 1}</b><span>{a}</span><small>{b}</small></div>)}</div>;
}

export function RiskWhy({ routes, post }) {
  const r = (routes || []).find((x) => x.post === post);
  if (!r || !r.via) return <p className="mu">No open road route to this post.</p>;
  const t = r.why.score || 1;
  return (
    <div>
      <p><b>{r.via}</b> from {r.depot}: {r.km} km, ETA {r.eta_h} h, risk <b>{Math.round(r.risk * 100)}%</b></p>
      {['snow', 'slope', 'visibility'].map((k) => <div className="xr" key={k}><span>{k}</span><div><div className="bar" style={{ width: `${Math.round((r.why[k] / t) * 100)}%` }} /></div><span>{Math.round((r.why[k] / t) * 100)}%</span></div>)}
      <p className="mu">Risk = 0.4 snow + 0.3 slope + 0.2 visibility. Closed passes are removed. Try a snowfall scenario in Planning.</p>
    </div>
  );
}
