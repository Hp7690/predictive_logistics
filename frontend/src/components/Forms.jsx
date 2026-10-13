import { useState } from 'react';
import { api } from '../api.js';
import { useAct } from '../hooks.js';
import { Notice } from './ui.jsx';
import { ITEMS, ITEM_LABEL } from './icons.jsx';

const ItemSelect = ({ value, onChange }) => (
  <select aria-label="Item" value={value} onChange={(e) => onChange(e.target.value)}>{ITEMS.map((i) => <option key={i} value={i}>{ITEM_LABEL[i]}</option>)}</select>
);

export function RequestForm({ posts, onDone }) {
  const [post, setPost] = useState(posts ? posts[0] : '');
  const [item, setItem] = useState('Ration');
  const [qty, setQty] = useState(200);
  const [priority, setPriority] = useState('normal');
  const [msg, act] = useAct(onDone);
  const send = () => act(() => api('/requests', { method: 'POST', body: { post: posts ? post : undefined, item, qty: Number(qty), priority } }), 'Request sent to planner');
  return (
    <div>
      <div className="row">
        {posts && <select aria-label="Post" value={post} onChange={(e) => setPost(e.target.value)}>{posts.map((p) => <option key={p}>{p}</option>)}</select>}
        <ItemSelect value={item} onChange={setItem} />
        <input aria-label="Quantity" type="number" min="1" value={qty} onChange={(e) => setQty(e.target.value)} style={{ width: 90 }} />
        <select aria-label="Priority" value={priority} onChange={(e) => setPriority(e.target.value)}><option>normal</option><option>high</option></select>
        <button className="primary" onClick={send}>Raise supply request</button>
      </div>
      <Notice msg={msg} />
    </div>
  );
}

export function SosForm({ posts, onDone }) {
  const [post, setPost] = useState(posts ? posts[0] : '');
  const [item, setItem] = useState('Medical');
  const [qty, setQty] = useState(100);
  const [note, setNote] = useState('');
  const [armed, setArmed] = useState(false);
  const [msg, act] = useAct(onDone);
  const send = async () => { await act(() => api('/sos', { method: 'POST', body: { post: posts ? post : undefined, item, qty: Number(qty), note } }), 'SOS sent. Planner and all units alerted.'); setArmed(false); };
  return (
    <div>
      <div className="row">
        {posts && <select aria-label="Post" value={post} onChange={(e) => setPost(e.target.value)}>{posts.map((p) => <option key={p}>{p}</option>)}</select>}
        <ItemSelect value={item} onChange={setItem} />
        <input aria-label="Quantity" type="number" min="1" value={qty} onChange={(e) => setQty(e.target.value)} style={{ width: 90 }} />
        <input aria-label="Note" placeholder="What happened?" value={note} onChange={(e) => setNote(e.target.value)} />
      </div>
      {!armed ? <button className="sos" onClick={() => setArmed(true)}>SOS: emergency supply</button>
        : <div className="row"><b>Confirm SOS? It overrides normal approval.</b><button className="sos" onClick={send}>Yes, send SOS</button><button onClick={() => setArmed(false)}>Cancel</button></div>}
      <Notice msg={msg} />
    </div>
  );
}

export function StockForm({ onDone }) {
  const [item, setItem] = useState('Ration');
  const [delta, setDelta] = useState(100);
  const [reason, setReason] = useState('');
  const [msg, act] = useAct(onDone);
  const send = () => act(() => api('/inventory/update', { method: 'POST', body: { item, delta: Number(delta), reason } }), (r) => `${ITEM_LABEL[r.item]} stock is now ${r.stock}`);
  return (
    <div>
      <div className="row">
        <ItemSelect value={item} onChange={setItem} />
        <input aria-label="Change (+ in, - out)" type="number" value={delta} onChange={(e) => setDelta(e.target.value)} style={{ width: 100 }} />
        <input aria-label="Reason" placeholder="Reason" value={reason} onChange={(e) => setReason(e.target.value)} />
        <button className="primary" onClick={send}>Update stock</button>
      </div>
      <p className="mu">Positive number = stock in, negative = stock out.</p>
      <Notice msg={msg} />
    </div>
  );
}

export function UseForm({ posts, onDone }) {
  const [post, setPost] = useState(posts ? posts[0] : '');
  const [item, setItem] = useState('Ration');
  const [qty, setQty] = useState(0);
  const [msg, act] = useAct(onDone);
  const send = () => act(() => api('/consumption', { method: 'POST', body: { post: posts ? post : undefined, item, qty: Number(qty) } }), 'Logged. Used at the next model retrain.');
  return (
    <div>
      <div className="row">
        {posts && <select aria-label="Post" value={post} onChange={(e) => setPost(e.target.value)}>{posts.map((p) => <option key={p}>{p}</option>)}</select>}
        <ItemSelect value={item} onChange={setItem} />
        <input aria-label="Used today" type="number" min="0" value={qty} onChange={(e) => setQty(e.target.value)} style={{ width: 100 }} />
        <button onClick={send}>Log today's consumption</button>
      </div>
      <p className="mu">Actual use feeds the forecast model (feedback loop).</p>
      <Notice msg={msg} />
    </div>
  );
}
