import { useState } from 'react';
import { BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, Legend, ResponsiveContainer } from 'recharts';
import { api } from '../api.js';
import { useLoad, useAct } from '../hooks.js';
import { Gauge, Pill, Table, Notice, Err, Kpi, ModeBadge, riskLabel } from './ui.jsx';
import { ITEMS, ITEM_LABEL } from './icons.jsx';

const dash = (v) => (v === null || v === undefined ? '-' : v);

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
          { h: 'Route', f: (r) => `${r.label}${r.best ? ' ★' : ''}` },
          { h: 'Via', f: (r) => r.via }, { h: 'From', f: (r) => r.depot_name.replace(' Depot', '') }, { h: 'km', f: (r) => r.km },
          { h: 'ETA h', f: (r) => r.eta_h }, { h: 'Risk', f: (r) => <span className={`risk ${riskLabel(r.risk)}`}>{riskLabel(r.risk)} {Math.round(r.risk * 100)}%</span> },
          { h: 'Status', f: (r) => (r.open ? 'open' : <b className="bad-t">CLOSED{r.pass ? ` (${r.pass})` : ''}</b>) }]} />
        <h3 className="sub">Transport mode for 1500 kg (cheapest that meets the deadline)</h3>
        <Table rows={d.modes} cols={[
          { h: 'Mode', f: (o2) => <ModeBadge mode={o2.mode} /> }, { h: 'ETA h', f: (o2) => dash(o2.eta_h) }, { h: 'Cost index', f: (o2) => o2.cost_index },
          { h: 'Capacity', f: (o2) => `${o2.capacity_kg} kg x ${o2.units}` }, { h: 'Why', f: (o2) => o2.reason },
          { h: '', f: (o2) => (o2.recommended ? <span className="pill ok">Recommended</span> : !o2.feasible ? <span className="pill warning">Not feasible</span> : '') }]} />
      </>}
    </div>
  );
}

export function EdgeTable({ nodes, onToggle }) {
  return (
    <Table rows={nodes} empty="No edge nodes." cols={[
      { h: 'Node', f: (n) => n.code }, { h: 'Site', f: (n) => n.name }, { h: 'Link', f: (n) => n.link },
      { h: 'State', f: (n) => (n.online ? (n.stale ? <span className="pill warning">No data</span> : <span className="pill ok">Online</span>) : <span className="pill critical">Offline (local cache)</span>) },
      { h: 'Buffered', f: (n) => n.buffered }, { h: 'Rejected', f: (n) => n.rejected }, { h: 'Battery', f: (n) => `${Math.round(n.battery)}%` }, { h: 'RFID tags', f: (n) => n.rfid_tags },
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
        <button className="primary" disabled={d.training} onClick={() => act(() => api('/ml/retrain', { method: 'POST' }), 'Retraining started. This takes 2-4 minutes.')}>{d.training ? 'Training...' : 'Retrain on latest data'}</button>
        <span className="mu">Last trained: {d.trained_at || 'never'}</span>
      </div>
      <Notice msg={msg} /><Err e={st.err || d.error} />
      <Table rows={rows} cols={[{ h: 'Item', f: (r) => ITEM_LABEL[r.item] || r.item }, { h: 'Method', f: (r) => r.method },
        { h: 'Daily MAPE %', f: (r) => dash(r['daily_MAPE_%']) }, { h: 'Baseline MAPE %', f: (r) => dash(r['naive_daily_MAPE_%']) },
        { h: 'MASE', f: (r) => dash(r.MASE) }, { h: 'Baseline MASE', f: (r) => dash(r.naive_MASE) },
        { h: '14-day total error %', f: (r) => dash(r['14d_total_MAPE_%']) }, { h: '80% band coverage %', f: (r) => dash(r['80%_band_coverage_%']) }]} />
      <p className="mu">XGBoost + LSTM ensemble for regular items, Croston / SBA for slow-moving items (vehicle spares). MASE below 1 beats a naive forecast. Slow-moving error is a weighted error because MAPE is undefined when demand is zero. Actual consumption logged by posts and depots is used at every retrain.</p>
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
        <Kpi value={d.mase != null ? d.mase : '-'} label="MASE (below 1 beats naive)" />
        <Kpi value={d.avg_first_stop_eta_h != null ? `${d.avg_first_stop_eta_h} h` : '-'} label="Avg lead time, first stop" />
        <Kpi value={`${d.non_moving_pct}%`} label="Non-moving stock" tone="amber" />
        <Kpi value={d.utilisation_pct != null ? `${d.utilisation_pct}%` : '-'} label="Road convoy load utilisation" />
      </div>
      <ResponsiveContainer width="100%" height={260}>
        <BarChart data={chart}><CartesianGrid strokeDasharray="3 3" stroke="#3a4630" /><XAxis dataKey="name" stroke="#9aa58a" /><YAxis stroke="#9aa58a" /><Tooltip /><Legend />
          <Bar dataKey="Current" fill="#6b705f" /><Bar dataKey="ASTRA-LOG target" fill="#c9b27c" /></BarChart>
      </ResponsiveContainer>
      <p className="mu">Logistics performance, % of today's baseline. Targets are illustrative and to be validated in the pilot (MAPE / MASE, stock-out rate, lead time). The cards are measured live from this system.</p>
    </div>
  );
}

export function Timeline() {
  const steps = [['Demand forecast', 'Daily'], ['Shortfall alert', 'Instant'], ['Route planned', 'Minutes'], ['Convoy / drone sent', 'Same day'], ['Delivery logged', 'Automatic']];
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

// ---------- offline plain-language assistant ----------
const EXAMPLES = ['Post C ka fuel agle 7 din ka', 'which posts are critical', 'is Zoji La open', 'weather at Leh', 'where is CV-001'];
export function AskPanel({ examples = EXAMPLES }) {
  const [q, setQ] = useState('');
  const [res, setRes] = useState(null);
  const [err, setErr] = useState('');
  const go = async (text) => {
    const query = (text ?? q).trim(); if (!query) return;
    setQ(query); setErr('');
    try { setRes(await api('/ask', { method: 'POST', body: { q: query } })); } catch (e) { setErr(e.message); }
  };
  return (
    <div>
      <div className="row">
        <input aria-label="Ask ASTRA" style={{ flex: 1, minWidth: 220 }} placeholder="Ask in plain language, English or Hinglish" value={q} onChange={(e) => setQ(e.target.value)} onKeyDown={(e) => e.key === 'Enter' && go()} />
        <button className="primary" onClick={() => go()}>Ask</button>
      </div>
      <div className="row">{examples.map((x) => <button key={x} className="chip" onClick={() => go(x)}>{x}</button>)}</div>
      <Err e={err} />
      {res && <div className="answer"><b>{res.answer}</b></div>}
      <p className="mu">Offline assistant: rules and fuzzy matching run on the server itself, no internet and no outside model.</p>
    </div>
  );
}

// ---------- inventory balancing ----------
export function BalancingPanel() {
  const b = useLoad(() => api('/balancing'));
  const d = b.data;
  if (!d) return <Err e={b.err} />;
  return (
    <div>
      <div className="kpis">
        <Kpi value={d.summary.transfers} label="Suggested transfers" /><Kpi value={`${d.summary.moved_kg} kg`} label="Moved from surplus to shortfall" />
        <Kpi value={`${d.summary.non_moving_pct}%`} label="Non-moving stock" tone="amber" /><Kpi value={d.unmet.length} label="Shortfalls with no source" tone={d.unmet.length ? 'red' : ''} />
      </div>
      <h3 className="sub">Move surplus to predicted shortfalls</h3>
      <div className="scroll tall"><Table rows={d.transfers} empty="No transfers needed." cols={[
        { h: 'Item', f: (t) => ITEM_LABEL[t.item] }, { h: 'From', f: (t) => `${t.from_name} (${t.from_type})` }, { h: 'To', f: (t) => t.to_name }, { h: 'Qty', f: (t) => t.qty },
        { h: 'kg', f: (t) => t.kg }, { h: 'km', f: (t) => t.km }, { h: 'ETA h', f: (t) => t.eta_h }, { h: 'Days left before', f: (t) => t.dos_before }]} /></div>
      <h3 className="sub">Non-moving stock (more than 90 days of supply)</h3>
      <Table rows={d.non_moving} empty="No non-moving lines." cols={[{ h: 'Post', f: (x) => x.post }, { h: 'Item', f: (x) => ITEM_LABEL[x.item] }, { h: 'Stock', f: (x) => x.stock },
        { h: 'Days of supply', f: (x) => x.dos }, { h: 'Excess kg', f: (x) => x.excess_kg }]} />
      <p className="mu">Demand-driven stocking: stock above 21 days of forecast use counts as surplus and is offered to posts predicted to run short, nearest first, posts before depots.</p>
    </div>
  );
}

export function PriorityPanel() {
  const p = useLoad(() => api('/priority'));
  return (
    <div>
      <Err e={p.err} />
      <Table rows={p.data} empty="No scarce items." cols={[{ h: '#', f: (r) => r.rank }, { h: 'Post', f: (r) => r.name }, { h: 'Item', f: (r) => ITEM_LABEL[r.item] },
        { h: 'Days left', f: (r) => r.dos }, { h: 'Troops', f: (r) => r.troops }, { h: 'Status', f: (r) => <Pill level={r.level} /> }, { h: 'Score', f: (r) => r.score }]} />
      <p className="mu">Scarce items ranked by importance (medical and ammunition first) x troops depending on the post / days left.</p>
    </div>
  );
}

// ---------- advance winter stocking ----------
export function WinterPanel() {
  const [cd, setCd] = useState(45), [wd, setWd] = useState(120), [ed, setEd] = useState(0);
  const n = (v) => Number(v) || 0;
  const w = useLoad(() => api(`/winter?closure_days=${n(cd)}&winter_days=${n(wd)}&early_days=${Math.min(n(ed), n(cd))}`), [cd, wd, ed]);
  const d = w.data, s = d && d.summary;
  const chart = d ? d.posts.map((p) => ({ name: p.name.replace('Post ', ''), 'Winter need (t)': p.need_t, 'In stock (t)': p.stock_t, 'Gap (t)': p.gap_t })) : [];
  return (
    <div>
      <div className="row">
        <label>Passes close in (days) <input type="number" min="1" max="180" value={cd} onChange={(e) => setCd(e.target.value)} style={{ width: 80 }} /></label>
        <label>Winter length (days) <input type="number" min="1" max="240" value={wd} onChange={(e) => setWd(e.target.value)} style={{ width: 80 }} /></label>
        <label>What-if: closes earlier by (days) <input type="number" min="0" value={ed} onChange={(e) => setEd(e.target.value)} style={{ width: 80 }} /></label>
        <button onClick={() => setEd(20)}>Passes close 20 days early</button><button onClick={() => setEd(0)}>Reset</button>
      </div>
      <Err e={w.err} />
      {s && <>
        <div className="kpis">
          <Kpi value={`${s.need_t} t`} label="Winter need, all posts" /><Kpi value={`${s.stock_t} t`} label="Already in stock" /><Kpi value={`${s.gap_t} t`} label="To pre-position" tone="amber" />
          <Kpi value={`${s.feasible_pct}%`} label={`Road fleet can move before closure (${d.params.weeks_left} weeks)`} tone={s.feasible_pct < 70 ? 'red' : ''} />
          <Kpi value={`${s.shortfall_t} t`} label="Needs air / drone or earlier start" tone={s.shortfall_t > 0 ? 'red' : ''} />
        </div>
        {d.params.early_days > 0 && <div className="notice bad">If the passes close {d.params.early_days} days early, feasibility drops from {s.feasible_pct_normal_closure}% to {s.feasible_pct}%.</div>}
        <ResponsiveContainer width="100%" height={260}>
          <BarChart data={chart}><CartesianGrid strokeDasharray="3 3" stroke="#3a4630" /><XAxis dataKey="name" stroke="#9aa58a" /><YAxis stroke="#9aa58a" /><Tooltip /><Legend />
            <Bar dataKey="Winter need (t)" fill="#6b705f" /><Bar dataKey="In stock (t)" fill="#7fb069" /><Bar dataKey="Gap (t)" fill="#e0a526" /></BarChart>
        </ResponsiveContainer>
        <Table rows={d.posts} cols={[{ h: 'Post', f: (p) => p.name }, { h: 'Route', f: (p) => `${p.via || 'no road'} (${p.eta_h ?? '-'} h)` }, { h: 'Need t', f: (p) => p.need_t },
          { h: 'Stock t', f: (p) => p.stock_t }, { h: 'Gap t', f: (p) => p.gap_t }, { h: 'Trucks', f: (p) => p.trucks }, { h: 'Weekly t', f: (p) => dash(p.weekly_t) },
          { h: 'Can deliver', f: (p) => `${p.deliverable_pct}%` }, { h: 'Shortfall t', f: (p) => p.shortfall_t }]} />
      </>}
      <p className="mu">Winter need = average daily use in Dec to Mar x winter length. The planner phases the gap week by week and checks what the road fleet can move before the passes close. Closing a pass in Planning changes the routes used here.</p>
    </div>
  );
}

// ---------- Q-FORCE / ERP integration ----------
export function IntegrationPanel() {
  const i = useLoad(() => api('/integration/status'));
  const d = i.data;
  return (
    <div>
      <Err e={i.err} />
      {d && <>
        <p>Status: {d.enabled ? <span className="pill ok">Enabled</span> : <span className="pill warning">Off: set INTEGRATION_API_KEY in .env</span>} Send the key in the <code>{d.header}</code> header.</p>
        <ul className="events">{d.endpoints.map((e) => <li key={e}><code>{e}</code></li>)}</ul>
        <p className="mu">Plain REST / JSON / CSV, so ASTRA-LOG can sit beside Q-FORCE or an Army ERP as a predictive layer: it reads stock and movements, and returns forecasts and alerts. Q-FORCE interfaces are not public, so no vendor-specific adapter is claimed.</p>
      </>}
    </div>
  );
}

// ---------- GPS position report (transport) ----------
export function PositionForm({ convoy, onDone }) {
  const [p, setP] = useState(Math.round((convoy.progress || 0) * 100));
  const [msg, act] = useAct(onDone);
  const send = (ok) => act(() => api(`/convoy/${convoy.code}/position?progress=${p / 100}&gps_ok=${ok}`, { method: 'POST' }), ok ? `${convoy.code} position updated` : `${convoy.code}: GPS lost, last known position kept, LoRa fallback`);
  return (
    <div className="row">
      <label>Progress <input type="range" min="0" max="100" value={p} onChange={(e) => setP(Number(e.target.value))} /> {p}%</label>
      <button onClick={() => send(true)}>Report GPS position</button>
      <button className="danger" onClick={() => send(false)}>GPS lost</button>
      {convoy.gps_ok === false && <span className="pill warning">Last known position</span>}
      <Notice msg={msg} />
    </div>
  );
}
