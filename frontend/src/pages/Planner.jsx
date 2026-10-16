import { useState } from 'react';
import { ComposedChart, Area, Line, XAxis, YAxis, CartesianGrid, Tooltip, ReferenceLine, ResponsiveContainer } from 'recharts';
import { api } from '../api.js';
import { useLoad, useAct } from '../hooks.js';
import { Card, Kpi, Pill, Table, Notice, Err, ModeBadge, stopsText, loadText } from '../components/ui.jsx';
import MapView from '../components/MapView.jsx';
import { PostStatus, RouteModes, EdgeTable, WeatherTable, MlPanel, KpiPanel, Timeline, RiskWhy, AskPanel, BalancingPanel, PriorityPanel, WinterPanel } from '../components/Panels.jsx';
import { ITEMS, ITEM_LABEL } from '../components/icons.jsx';

const TABS = [['command', 'Command'], ['planning', 'Planning & what-if'], ['inventory', 'Inventory & balancing'], ['winter', 'Winter stocking'], ['intel', 'Weather & edge nodes'], ['analytics', 'Analytics & AI']];

export default function Planner() {
  const [tab, setTab] = useState('command');
  const [post, setPost] = useState('P3');
  const [item, setItem] = useState('POL');
  const [snow, setSnow] = useState('');
  const [spike, setSpike] = useState('');
  const [spikePost, setSpikePost] = useState('');
  const [wi, setWi] = useState(null);
  const q = (extra = '') => { const p = []; if (snow) p.push(`snow_cm=${snow}`); if (spike) p.push(`demand_pct=${spike}`); if (spike && spikePost) p.push(`spike_post=${spikePost}`); return p.length || extra ? '?' + [...p, extra].filter(Boolean).join('&') : ''; };
  const dos = useLoad(() => api('/dos' + q()), [spike, spikePost]);
  const alerts = useLoad(() => api('/alerts'));
  const map = useLoad(() => api('/map'));
  const wx = useLoad(() => api('/weather'));
  const convoys = useLoad(() => api('/convoys'));
  const reqs = useLoad(() => api('/requests'));
  const routes = useLoad(() => api('/routes' + (snow ? `?snow_cm=${snow}` : '')), [snow]);
  const nodes = useLoad(() => api('/edge-nodes'));
  const fc = useLoad(() => api(`/forecast/${post}/${item}`), [post, item]);
  const all = () => [dos, alerts, map, wx, convoys, reqs, routes, nodes, fc].forEach((x) => x.reload());
  const [msg, act] = useAct(all);

  const rows = dos.data || [], cv = convoys.data || [], locs = (map.data && map.data.locations) || [];
  const posts = [...new Set(rows.map((r) => r.post))];
  const al = alerts.data || [];
  const top = al[0];
  const stock = (rows.find((r) => r.post === post && r.item === item) || {}).stock || 0;
  let c10 = 0, c50 = 0, c90 = 0;
  const chart = ((fc.data && fc.data.forecast) || []).map((d, i) => {
    c10 += d.p10; c50 += d.p50; c90 += d.p90;
    return { day: i + 1, mid: Math.max(0, Math.round(stock - c50)), band: [Math.max(0, Math.round(stock - c90)), Math.max(0, Math.round(stock - c10))] };
  });
  const passes = [...new Set(((map.data && map.data.segments) || []).filter((s) => s.pass_name).map((s) => s.pass_name))].sort();
  const closed = (p) => ((map.data && map.data.segments) || []).some((s) => s.pass_name === p && !s.open);

  const togglePass = async (p) => {
    const r = await act(() => api(`/whatif/pass?pass_name=${encodeURIComponent(p)}&closed=${!closed(p)}${snow ? `&snow_cm=${snow}` : ''}`, { method: 'POST' }),
      (x) => `${p} ${closed(p) ? 'reopened' : 'closed'}: ${x.route_changes.length} route(s) changed`);
    if (r) setWi(r);
  };
  const cvActions = (c) => (
    <div className="row">
      {c.status === 'proposed' && <>
        <button className="primary" onClick={() => act(() => api(`/convoy/${c.code}/status?status=approved`, { method: 'POST' }), `${c.code} approved`)}>Approve</button>
        <button className="danger" onClick={() => act(() => api(`/convoy/${c.code}/status?status=rejected`, { method: 'POST' }), `${c.code} rejected`)}>Reject</button></>}
      {['proposed', 'approved', 'loaded', 'in_transit'].includes(c.status) && <button onClick={() => act(() => api(`/convoy/${c.code}/override`, { method: 'POST', body: { action: 'hold', note: 'Commander hold' } }), `${c.code} on hold`)}>Hold</button>}
      {c.status === 'held' && <button className="primary" onClick={() => act(() => api(`/convoy/${c.code}/override`, { method: 'POST', body: { action: 'release', note: 'Cleared' } }), `${c.code} released`)}>Release</button>}
    </div>);

  return (
    <>
      <div className="tabs" style={{ gridColumn: 'span 12' }} role="tablist">
        {TABS.map(([k, t]) => <button key={k} role="tab" aria-selected={tab === k} className={tab === k ? 'on' : ''} onClick={() => setTab(k)}>{t}</button>)}
      </div>
      <Notice msg={msg} />

      {tab === 'command' && <>
        <section className={`banner ${top ? top.level : 'ok'}`} style={{ gridColumn: 'span 12' }}>
          <b>{top ? (top.level === 'sos' ? 'SOS' : 'ALERT') : 'ALL CLEAR'}</b>
          <span>{top ? `${top.message}. Suggested: ${top.action}` : 'No shortages predicted. Press "Refresh alerts" in Planning to recompute.'}</span>
        </section>
        <Card title="Command overview">
          <div className="kpis">
            <Kpi value={rows.filter((r) => r.level === 'critical').length} label="Critical stock lines" tone="red" />
            <Kpi value={rows.filter((r) => r.level === 'warning').length} label="Warning stock lines" tone="amber" />
            <Kpi value={cv.filter((c) => c.status === 'proposed').length} label="Awaiting approval" />
            <Kpi value={cv.filter((c) => ['loaded', 'in_transit'].includes(c.status)).length} label="Convoys moving" />
            <Kpi value={(reqs.data || []).filter((r) => r.status === 'pending').length} label="Pending requests" />
            <Kpi value={(nodes.data || []).filter((n) => !n.online).length} label="Edge nodes offline" tone="amber" />
          </div>
          <Err e={dos.err || map.err} />
        </Card>
        <Card title="Ask ASTRA (offline assistant, English or Hinglish)"><AskPanel /></Card>
        <Card title="Route map (GIS), Northern sector" span={8}><MapView map={map.data} dos={rows} convoys={cv} weather={wx.data || []} selected={post} onSelect={setPost} height={500} /></Card>
        <Card title="Selected post" span={4}><PostStatus code={post} dos={rows} locs={locs} /></Card>
        <Card title={`Route and mode options: ${post}`} span={7}><RouteModes post={post} snow={snow} /></Card>
        <Card title="Predicted shortages" span={5}>
          <div className="scroll tall">
            {al.length ? al.map((a, i) => <div key={i} className={`alert ${a.level}`}><b>{a.message}</b> <Pill level={a.level} /><small>Reason: {a.reason}</small><small>Action: {a.action}</small></div>)
              : <p className="mu">No alerts yet. Press "Refresh alerts" in Planning.</p>}
          </div>
        </Card>
      </>}

      {tab === 'planning' && <>
        <Card title="Scenario controls (what-if simulation)">
          <div className="row">
            <button onClick={() => act(() => api('/alerts/refresh' + q(), { method: 'POST' }), (r) => `${r.created} alerts created (${r.critical} critical)`)}>Refresh alerts</button>
            <button className="primary" onClick={() => act(() => api('/plan/generate' + q(), { method: 'POST' }), (r) => `${r.convoys.length} convoy(s) proposed for ${r.posts_needing_supply} post(s)${r.unserved_posts.length ? `. Unserved: ${r.unserved_posts.join(', ')}` : ''}`)}>Generate AI plan</button>
          </div>
          <div className="row">
            <label>Snowfall (cm) <input type="number" min="0" value={snow} onChange={(e) => setSnow(e.target.value)} style={{ width: 80 }} placeholder="live" /></label>
            <label>Demand spike (%) <input type="number" min="0" value={spike} onChange={(e) => setSpike(e.target.value)} style={{ width: 80 }} placeholder="0" /></label>
            <label>at <select aria-label="Spike post" value={spikePost} onChange={(e) => setSpikePost(e.target.value)}><option value="">all posts</option>{posts.map((p) => <option key={p}>{p}</option>)}</select></label>
          </div>
          <div className="row"><span className="mu">Quick scenarios:</span>
            <button onClick={() => { setSnow('8'); setSpike(''); setSpikePost(''); }}>Heavy snowfall (8 cm)</button>
            <button onClick={() => { setSnow(''); setSpike('80'); setSpikePost(post); }}>HADR surge: +80% demand at {post}</button>
            <button onClick={() => { setSnow(''); setSpike(''); setSpikePost(''); }}>Reset scenario</button></div>
          <div className="row"><span className="mu">Road closures:</span>
            {passes.map((p) => <button key={p} className={closed(p) ? 'danger' : ''} onClick={() => togglePass(p)}>{closed(p) ? 'Reopen' : 'Close'} {p}</button>)}</div>
          {wi && wi.route_changes.length > 0 && <Table rows={wi.route_changes} cols={[
            { h: 'Post', f: (r) => r.post },
            { h: 'Before', f: (r) => `${r.before.via} from ${r.before.depot}, ${r.before.eta_h} h, risk ${Math.round(r.before.risk * 100)}%` },
            { h: 'After', f: (r) => (r.after.via ? `${r.after.via} from ${r.after.depot}, ${r.after.eta_h} h, risk ${Math.round(r.after.risk * 100)}%` : 'No road route: air or mule') }]} />}
          <p className="mu">Close both Zoji La and Baralacha La, then Generate AI plan: posts with no road switch to air maintenance or mule.</p>
        </Card>
        <Card title="Convoy plan">
          <Table rows={cv} empty='No convoys yet. Press "Generate AI plan".' cols={[
            { h: 'Code', f: (c) => c.code }, { h: 'Mode', f: (c) => <ModeBadge mode={c.mode} /> }, { h: 'Asset', f: (c) => `${c.vehicle} (${c.load_kg}/${c.capacity_kg} kg)` },
            { h: 'From', f: (c) => c.depot }, { h: 'Route', f: (c) => stopsText(c) }, { h: 'Load', f: (c) => loadText(c) },
            { h: 'Risk', f: (c) => `${Math.round(c.max_risk * 100)}%` }, { h: 'Status', f: (c) => <>{c.status}{c.status === 'held' ? ` (${c.note.split('|')[1] || 'hold'})` : ''}</> }, { h: '', f: cvActions }]} />
        </Card>
        <Card title="Supply requests and SOS">
          <Table rows={reqs.data} empty="No requests." cols={[
            { h: 'ID', f: (r) => r.id }, { h: 'Post', f: (r) => r.post }, { h: 'Item', f: (r) => ITEM_LABEL[r.item] }, { h: 'Qty', f: (r) => r.qty },
            { h: 'Priority', f: (r) => (r.priority === 'sos' ? <Pill level="sos" /> : r.priority) }, { h: 'By', f: (r) => r.by }, { h: 'Status', f: (r) => r.status },
            { h: '', f: (r) => r.status === 'pending' && <div className="row"><button className="primary" onClick={() => act(() => api(`/requests/${r.id}/decision?approve=true`, { method: 'POST' }), `Request ${r.id} approved`)}>Approve</button>
              <button className="danger" onClick={() => act(() => api(`/requests/${r.id}/decision?approve=false`, { method: 'POST' }), `Request ${r.id} rejected`)}>Reject</button></div> }]} />
        </Card>
        <Card title="Projected stock (14 days, 80% band)" right={
          <div className="row"><select aria-label="Post" value={post} onChange={(e) => setPost(e.target.value)}>{posts.map((p) => <option key={p}>{p}</option>)}</select>
            <select aria-label="Item" value={item} onChange={(e) => setItem(e.target.value)}>{ITEMS.map((i) => <option key={i} value={i}>{ITEM_LABEL[i]}</option>)}</select></div>}>
          <Err e={fc.err} />
          <ResponsiveContainer width="100%" height={250}>
            <ComposedChart data={chart}><CartesianGrid strokeDasharray="3 3" stroke="#3a4630" /><XAxis dataKey="day" stroke="#9aa58a" /><YAxis stroke="#9aa58a" /><Tooltip />
              <Area dataKey="band" stroke="none" fill="#c9b27c" fillOpacity={0.25} /><Line dataKey="mid" stroke="#c9b27c" strokeWidth={2.5} dot={false} />
              <ReferenceLine y={0} stroke="#d2493a" strokeDasharray="4 3" /></ComposedChart>
          </ResponsiveContainer>
          <p className="mu">Current stock {stock}. Where the band touches zero, the post can run out.</p>
        </Card>
      </>}

      {tab === 'inventory' && <>
        <Card title="Surplus-to-shortfall balancing and non-moving stock"><BalancingPanel /></Card>
        <Card title="Priority ranking of scarce items" span={5}><PriorityPanel /></Card>
        <Card title="Days of supply (all posts)" span={7}>
          <div className="scroll tall"><Table rows={rows} cols={[
            { h: 'Post', f: (r) => r.post }, { h: 'Item', f: (r) => ITEM_LABEL[r.item] }, { h: 'Stock', f: (r) => r.stock }, { h: 'Forecast/day', f: (r) => r.forecast_per_day },
            { h: 'Days of supply', f: (r) => r.dos }, { h: 'Status', f: (r) => <Pill level={r.level} /> }]} /></div>
        </Card>
      </>}

      {tab === 'winter' && <Card title="Advance winter stocking planner (snow-closure what-if)"><WinterPanel /></Card>}

      {tab === 'intel' && <>
        <Card title="Weather at forward posts (IMD feed plug-in point)" right={<button onClick={() => act(() => api('/weather/sync', { method: 'POST' }), (r) => `Live weather updated for ${r.updated} posts`)}>Pull live weather</button>}>
          <WeatherTable rows={wx.data} />
          <p className="mu">Prototype uses the free Open-Meteo service; the IMD feed replaces it in the same function. Route risk uses the latest values.</p>
        </Card>
        <Card title="Edge nodes (offline-first IoT: RFID, GPS, LoRa)">
          <EdgeTable nodes={nodes.data} onToggle={(n) => act(() => api(`/edge-nodes/${n.code}/link?online=${!n.online}`, { method: 'POST' }), `${n.code} link ${n.online ? 'cut: node keeps working offline' : 'restored: syncing'}`)} />
          <p className="mu">Run <code>python -m iot_sim.edge_sim</code> to stream readings over MQTT. Cut a link: the node buffers readings locally and syncs them when the link returns.</p>
        </Card>
      </>}

      {tab === 'analytics' && <>
        <Card title="Impact: current vs ASTRA-LOG target"><KpiPanel /></Card>
        <Card title="Forecast model and feedback loop" span={7}><MlPanel /></Card>
        <Card title={`Why this route risk? (${post})`} span={5}>
          <div className="row"><select aria-label="Post" value={post} onChange={(e) => setPost(e.target.value)}>{posts.map((p) => <option key={p}>{p}</option>)}</select></div>
          <RiskWhy routes={routes.data} post={post} />
        </Card>
        <Card title="Demand-to-delivery timeline"><Timeline /></Card>
      </>}
    </>
  );
}
