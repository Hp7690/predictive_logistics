import { api } from '../api.js';
import { useLoad, useAct } from '../hooks.js';
import { Card, Table, Notice, Err, ModeBadge, stopsText } from '../components/ui.jsx';
import MapView from '../components/MapView.jsx';
import { WeatherTable } from '../components/Panels.jsx';
import { ITEM_LABEL } from '../components/icons.jsx';

const NEXT = { approved: 'loaded', loaded: 'in_transit', in_transit: 'delivered' };

export default function Transport() {
  const convoys = useLoad(() => api('/convoys'));
  const map = useLoad(() => api('/map'));
  const veh = useLoad(() => api('/vehicles'));
  const wx = useLoad(() => api('/weather'));
  const [msg, act] = useAct(() => [convoys, map, veh, wx].forEach((x) => x.reload()));
  const list = convoys.data || [];
  return (
    <>
      <Card title="My convoys">
        <Notice msg={msg} /><Err e={convoys.err} />
        {list.length ? list.map((c) => (
          <div className={`convoy ${c.status}`} key={c.code}>
            <div className="row between"><b>{c.code}: {c.vehicle} <span className="mu">({c.vehicle_type})</span></b><span><ModeBadge mode={c.mode} /> <span className={`pill st-${c.status}`}>{c.status.replace('_', ' ')}</span></span></div>
            <p>From <b>{c.depot}</b> | {stopsText(c)} | {c.km} km | max route risk {Math.round(c.max_risk * 100)}%</p>
            {c.status === 'held' && <div className="notice bad">Held by commander: {(c.note || '').split('|')[1] || 'awaiting clearance'}. Do not move.</div>}
            <Table rows={c.stops} cols={[{ h: 'Stop', f: (s) => s.post }, { h: 'Via', f: (s) => s.via }, { h: 'ETA (h)', f: (s) => s.eta_h },
              { h: 'Priority', f: (s) => s.priority }, { h: 'Load', f: (s) => Object.entries(s.items).map(([k, v]) => `${ITEM_LABEL[k]} ${v}`).join(', ') }]} />
            {NEXT[c.status] && <button className="primary" onClick={() => act(() => api(`/convoy/${c.code}/status?status=${NEXT[c.status]}`, { method: 'POST' }), `${c.code} marked ${NEXT[c.status].replace('_', ' ')}`)}>Mark {NEXT[c.status].replace('_', ' ')}</button>}
          </div>
        )) : <p className="mu">No approved convoys yet. When the planner approves one, it appears here instantly.</p>}
      </Card>
      <Card title="Route map" span={8}><MapView map={map.data} convoys={list} weather={wx.data || []} height={440} /></Card>
      <Card title="Vehicles" span={4}>
        <div className="scroll tall"><Table rows={veh.data} cols={[{ h: 'Code', f: (v) => v.code }, { h: 'Type', f: (v) => v.type }, { h: 'Depot', f: (v) => v.depot },
          { h: 'Status', f: (v) => v.status }, { h: 'Fuel', f: (v) => `${v.fuel_pct}%` }, { h: 'Health', f: (v) => `${v.health_pct}%` }]} /></div>
      </Card>
      <Card title="Route conditions (weather)"><WeatherTable rows={wx.data} /></Card>
    </>
  );
}
