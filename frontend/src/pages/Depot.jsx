import { api } from '../api.js';
import { useLoad } from '../hooks.js';
import { Card, Pill, Table, Err, Gauge, ModeBadge, stopsText } from '../components/ui.jsx';
import { RequestForm, StockForm, UseForm, SosForm } from '../components/Forms.jsx';
import { EdgeTable, AskPanel } from '../components/Panels.jsx';
import { ITEMS, ITEM_LABEL } from '../components/icons.jsx';

export default function Depot() {
  const inv = useLoad(() => api('/inventory'));
  const dos = useLoad(() => api('/dos'));
  const convoys = useLoad(() => api('/convoys'));
  const reqs = useLoad(() => api('/requests'));
  const nodes = useLoad(() => api('/edge-nodes'));
  const cat = useLoad(() => api('/catalog'));
  const all = () => [inv, dos, convoys, reqs, nodes].forEach((x) => x.reload());
  const mine = (inv.data || []).filter((r) => r.type === 'depot');
  const rows = dos.data || [];
  const posts = [...new Set(rows.map((r) => r.post))];
  return (
    <>
      <Card title={`Depot stock ${mine[0] ? '(' + mine[0].name + ')' : ''}`} span={6}>
        <Err e={inv.err} />
        <Table rows={mine} cols={[{ h: 'Item', f: (r) => ITEM_LABEL[r.item] }, { h: 'Stock', f: (r) => r.stock }, { h: 'Reorder level', f: (r) => r.reorder_level },
          { h: 'Status', f: (r) => <Pill level={r.stock < r.reorder_level ? 'warning' : 'ok'} /> }]} />
      </Card>
      <Card title="Stock in / out" span={6}><StockForm onDone={all} /></Card>
      <Card title="Posts in my area">
        <div className="gauge-grid">
          {posts.map((p) => <div key={p} className="mini"><h3 className="sub">{p}</h3>{ITEMS.map((i) => { const r = rows.find((x) => x.post === p && x.item === i); return r ? <Gauge key={i} item={i} pct={r.fill_pct} dos={r.dos} /> : null; })}</div>)}
        </div>
      </Card>
      <Card title="Raise a supply request" span={6}><RequestForm posts={posts.length ? posts : null} onDone={all} /></Card>
      <Card title="Log actual consumption" span={6}><UseForm posts={posts.length ? posts : null} onDone={all} /></Card>
      <Card title="Emergency (SOS) for a post in my area" tone="sos-card"><SosForm posts={posts.length ? posts : null} onDone={all} /></Card>
      <Card title="Edge node status (offline-first IoT)"><EdgeTable nodes={nodes.data} /></Card>
      <Card title="Ask ASTRA (offline assistant)"><AskPanel examples={['Post fuel next 7 days', 'which posts are critical', 'weather at Leh']} /></Card>
      <Card title="Item catalog (GS1 / RFID ready)" span={6}><Table rows={cat.data} cols={[{ h: 'Item', f: (c) => c.label }, { h: 'GS1 GTIN-14', f: (c) => c.gtin }, { h: 'Unit kg', f: (c) => c.kg }, { h: 'Demand type', f: (c) => (c.cls === 'slow' ? 'slow-moving (Croston/SBA)' : 'regular') }]} /></Card>
      <Card title="Convoys leaving my depot" span={6}>
        <Table rows={convoys.data} empty="No convoys from this depot." cols={[{ h: 'Code', f: (c) => c.code }, { h: 'Mode', f: (c) => <ModeBadge mode={c.mode} /> }, { h: 'Asset', f: (c) => c.vehicle },
          { h: 'Route', f: (c) => stopsText(c) }, { h: 'Load', f: (c) => `${c.load_kg} kg` }, { h: 'Status', f: (c) => c.status }]} />
      </Card>
      <Card title="Requests in my area">
        <Table rows={reqs.data} empty="No requests." cols={[{ h: 'ID', f: (r) => r.id }, { h: 'Post', f: (r) => r.post }, { h: 'Item', f: (r) => ITEM_LABEL[r.item] },
          { h: 'Qty', f: (r) => r.qty }, { h: 'Priority', f: (r) => (r.priority === 'sos' ? <Pill level="sos" /> : r.priority) }, { h: 'Status', f: (r) => r.status }]} />
      </Card>
    </>
  );
}
