import { api } from '../api.js';
import { useLoad } from '../hooks.js';
import { Card, Pill, Table, Err, Gauge, ModeBadge, stopsText } from '../components/ui.jsx';
import { RequestForm, SosForm, UseForm } from '../components/Forms.jsx';
import { EdgeTable, AskPanel } from '../components/Panels.jsx';
import { ITEMS, ITEM_LABEL } from '../components/icons.jsx';

export default function Post() {
  const dos = useLoad(() => api('/dos'));
  const alerts = useLoad(() => api('/alerts'));
  const convoys = useLoad(() => api('/convoys'));
  const reqs = useLoad(() => api('/requests'));
  const nodes = useLoad(() => api('/edge-nodes'));
  const wx = useLoad(() => api('/weather'));
  const all = () => [dos, alerts, convoys, reqs, nodes, wx].forEach((x) => x.reload());
  const rows = dos.data || [], al = alerts.data || [], w = (wx.data || [])[0];
  return (
    <>
      {al[0] && <section className={`banner ${al[0].level}`} style={{ gridColumn: 'span 12' }}><b>{al[0].level === 'sos' ? 'SOS' : 'ALERT'}</b><span>{al[0].message}</span></section>}
      <Card title="My stock" span={7}>
        <Err e={dos.err} />
        {ITEMS.map((i) => { const r = rows.find((x) => x.item === i); return r ? <Gauge key={i} item={i} pct={r.fill_pct} dos={r.dos} /> : null; })}
        <Table rows={rows} cols={[{ h: 'Item', f: (r) => ITEM_LABEL[r.item] }, { h: 'Stock', f: (r) => r.stock }, { h: 'Forecast/day', f: (r) => r.forecast_per_day },
          { h: 'Days of supply', f: (r) => r.dos }, { h: 'Status', f: (r) => <Pill level={r.level} /> }]} />
      </Card>
      <Card title="Local conditions" span={5}>
        {w ? <p>Snow today <b>{w.snow_cm} cm</b> ({w.snow_3d_cm} cm in 3 days)<br />Visibility <b>{w.vis_km} km</b> | Temperature <b>{w.temp_c} C</b></p> : <p className="mu">No weather data.</p>}
        <h3 className="sub">My alerts</h3>
        {al.length ? al.map((a, i) => <div key={i} className={`alert ${a.level}`}><b>{a.message}</b><small>{a.reason}</small></div>) : <p className="mu">No alerts for your post.</p>}
      </Card>
      <Card title="Emergency (SOS)" tone="sos-card"><SosForm onDone={all} /></Card>
      <Card title="Ask ASTRA (offline assistant)"><AskPanel examples={['mera fuel kitna bacha hai', 'fuel next 7 days', 'weather at my post', 'is Zoji La open']} /></Card>
      <Card title="Request supplies" span={6}><RequestForm onDone={all} /></Card>
      <Card title="Log today's consumption" span={6}><UseForm onDone={all} /></Card>
      <Card title="My edge node (works offline, syncs when the link returns)"><EdgeTable nodes={nodes.data} /></Card>
      <Card title="Incoming convoys">
        <Table rows={convoys.data} empty="No convoys on the way yet." cols={[{ h: 'Code', f: (c) => c.code }, { h: 'Mode', f: (c) => <ModeBadge mode={c.mode} /> }, { h: 'From', f: (c) => c.depot },
          { h: 'Route', f: (c) => stopsText(c) }, { h: 'Status', f: (c) => c.status }]} />
      </Card>
      <Card title="My requests">
        <Table rows={reqs.data} empty="No requests yet." cols={[{ h: 'ID', f: (r) => r.id }, { h: 'Item', f: (r) => ITEM_LABEL[r.item] }, { h: 'Qty', f: (r) => r.qty },
          { h: 'Priority', f: (r) => (r.priority === 'sos' ? <Pill level="sos" /> : r.priority) }, { h: 'Status', f: (r) => r.status }]} />
      </Card>
    </>
  );
}
