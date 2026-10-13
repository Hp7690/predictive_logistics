import { Icon, ITEM_LABEL } from './icons.jsx';

export const Card = ({ title, children, span = 12, right, tone = '' }) => (
  <section className={`card ${tone}`} style={{ gridColumn: `span ${span}` }}>
    <div className="card-h"><h2>{title}</h2>{right}</div>
    {children}
  </section>
);
const LBL = { critical: 'Critical', warning: 'Warning', ok: 'Normal', sos: 'SOS' };
export const Pill = ({ level }) => <span className={`pill ${level}`}>{LBL[level] || level}</span>;
export const Kpi = ({ value, label, tone = '' }) => <div className={`kpi ${tone}`}><b>{value}</b><span>{label}</span></div>;
export const Notice = ({ msg }) => (msg ? <div className={`notice ${msg.ok ? 'good' : 'bad'}`} role="status">{msg.text}</div> : null);
export const Err = ({ e }) => (e ? <div className="notice bad">{e}</div> : null);
export const Gauge = ({ item, pct, dos }) => {
  const tone = pct < 20 ? 'crit' : pct < 50 ? 'warn' : 'ok';
  return (
    <div className="gauge">
      <span className="g-lbl"><Icon name={item} size={16} /> {ITEM_LABEL[item]}</span>
      <div className="g-bar"><div className={`g-fill ${tone}`} style={{ width: `${pct}%` }} /></div>
      <span className="g-pct">{pct}%</span><span className="g-dos mu">{dos} d</span>
    </div>
  );
};
export function Table({ cols, rows, empty = 'Nothing here yet.' }) {
  if (!rows || !rows.length) return <p className="mu">{empty}</p>;
  return (
    <div className="scroll"><table>
      <thead><tr>{cols.map((c) => <th key={c.h}>{c.h}</th>)}</tr></thead>
      <tbody>{rows.map((r, i) => <tr key={i}>{cols.map((c) => <td key={c.h}>{c.f(r)}</td>)}</tr>)}</tbody>
    </table></div>
  );
}
export const ModeBadge = ({ mode }) => <span className={`mode ${mode}`}><Icon name={{ road: 'Road', air: 'Air', mule: 'Mule' }[mode]} size={14} /> {mode}</span>;
export const stopsText = (c) => c.stops.map((s) => `${s.post} (${s.eta_h} h)`).join(' → ');
export const loadText = (c) => c.stops.map((s) => `${s.post}: ${Object.entries(s.items).map(([k, v]) => `${ITEM_LABEL[k] || k} ${v}`).join(', ')}`).join(' | ');
export const riskLabel = (r) => (r < 0.35 ? 'low' : r < 0.55 ? 'medium' : 'high');
