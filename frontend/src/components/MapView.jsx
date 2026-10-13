import { MapContainer, TileLayer, LayersControl, LayerGroup, Polyline, CircleMarker, Circle, Marker, Tooltip } from 'react-leaflet';
import L from 'leaflet';
import 'leaflet/dist/leaflet.css';

const COL = { critical: '#d2493a', warning: '#e0a526', ok: '#7fb069' };
const depotIcon = L.divIcon({ className: 'depot-icon', html: '<div></div>', iconSize: [16, 16] });
const moveIcon = (txt) => L.divIcon({ className: 'move-icon', html: `<div>${txt}</div>`, iconSize: [22, 22] });
const short = (n) => (n.match(/\((.*?)\)/) || [null, n])[1];

function along(pts, f) {
  if (!pts || pts.length < 2) return pts && pts[0];
  const d = pts.slice(1).map((p, i) => Math.hypot(p[0] - pts[i][0], p[1] - pts[i][1]));
  let t = f * d.reduce((a, b) => a + b, 0);
  for (let i = 0; i < d.length; i++) {
    if (t <= d[i] || i === d.length - 1) { const k = Math.min(1, t / (d[i] || 1)); return [pts[i][0] + (pts[i + 1][0] - pts[i][0]) * k, pts[i][1] + (pts[i + 1][1] - pts[i][1]) * k]; }
    t -= d[i];
  }
  return pts[0];
}

export default function MapView({ map, dos = [], convoys = [], weather = [], selected, onSelect, height = 480 }) {
  if (!map) return <p className="mu">Loading map...</p>;
  const loc = Object.fromEntries(map.locations.map((l) => [l.code, l]));
  const bounds = L.latLngBounds(map.locations.map((l) => [l.lat, l.lon]));
  const level = (code) => {
    const r = dos.filter((d) => d.post === code);
    return r.some((d) => d.level === 'critical') ? 'critical' : r.some((d) => d.level === 'warning') ? 'warning' : 'ok';
  };
  const moving = convoys.filter((c) => ['loaded', 'in_transit'].includes(c.status));
  const routeColor = (s) => (s.risk < 0.35 ? '#7fb069' : s.risk < 0.55 ? '#e0a526' : '#d2493a');
  return (
    <>
      <MapContainer bounds={bounds} boundsOptions={{ padding: [30, 30] }} scrollWheelZoom style={{ height, width: '100%' }} className="leaflet-box">
        <LayersControl position="topright">
          <LayersControl.BaseLayer checked name="Street (OSM)"><TileLayer attribution="&copy; OpenStreetMap contributors" url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png" /></LayersControl.BaseLayer>
          <LayersControl.BaseLayer name="Terrain (OpenTopoMap)"><TileLayer attribution="&copy; OpenTopoMap, OSM contributors" url="https://{s}.tile.opentopomap.org/{z}/{x}/{y}.png" /></LayersControl.BaseLayer>
          <LayersControl.Overlay checked name="Routes">
            <LayerGroup>
              {map.segments.map((s, i) => (
                <Polyline key={i} positions={s.wp} pathOptions={!s.open ? { color: '#d2493a', weight: 3, dashArray: '8 8' } : s.best ? { color: routeColor(s), weight: 5 } : { color: '#555', weight: 2, opacity: 0.55 }}>
                  <Tooltip sticky>{s.via} | {s.km} km | ETA {s.eta_h} h | risk {Math.round(s.risk * 100)}%{!s.open ? ' | CLOSED' : s.best ? ' | recommended' : ''}</Tooltip>
                </Polyline>
              ))}
            </LayerGroup>
          </LayersControl.Overlay>
          <LayersControl.Overlay checked name="Passes">
            <LayerGroup>
              {map.passes.map((p) => (
                <CircleMarker key={p.name} center={[p.lat, p.lon]} radius={7} pathOptions={{ color: p.open ? '#c9b27c' : '#d2493a', fillColor: p.open ? '#c9b27c' : '#d2493a', fillOpacity: 0.9 }}>
                  <Tooltip permanent direction="top" className="pass-tip">{p.name}{p.open ? '' : ' CLOSED'}</Tooltip>
                </CircleMarker>
              ))}
            </LayerGroup>
          </LayersControl.Overlay>
          <LayersControl.Overlay name="Weather (snow)">
            <LayerGroup>
              {weather.filter((w) => loc[w.post]).map((w) => (
                <Circle key={w.post} center={[loc[w.post].lat, loc[w.post].lon]} radius={9000 + w.snow_3d_cm * 3000} pathOptions={{ color: '#6aa7c9', fillColor: '#6aa7c9', fillOpacity: 0.25, weight: 1 }}>
                  <Tooltip>{w.name}: snow {w.snow_cm} cm today ({w.snow_3d_cm} cm in 3 d), visibility {w.vis_km} km, {w.temp_c} C</Tooltip>
                </Circle>
              ))}
            </LayerGroup>
          </LayersControl.Overlay>
          <LayersControl.Overlay checked name="Convoys">
            <LayerGroup>
              {moving.map((c) => {
                const st = c.stops[0], f = c.status === 'loaded' ? 0.06 : 0.5, d = loc[c.depot], p = loc[st.post];
                if (!d || !p) return null;
                const seg = map.segments.find((s) => s.from === c.depot && s.to === st.post);
                const pts = c.mode === 'road' && seg ? seg.wp : [[d.lat, d.lon], [p.lat, p.lon]];
                return (
                  <LayerGroup key={c.code}>
                    {c.mode !== 'road' && <Polyline positions={pts} pathOptions={{ color: '#6aa7c9', weight: 3, dashArray: '2 8' }} />}
                    <Marker position={along(pts, f)} icon={moveIcon(c.mode === 'air' ? '✈' : c.mode === 'mule' ? 'M' : '▶')}><Tooltip>{c.code} ({c.mode}) to {st.post}, {c.status.replace('_', ' ')}</Tooltip></Marker>
                  </LayerGroup>
                );
              })}
            </LayerGroup>
          </LayersControl.Overlay>
        </LayersControl>
        {map.locations.filter((l) => l.type === 'depot').map((l) => (
          <Marker key={l.code} position={[l.lat, l.lon]} icon={depotIcon}><Tooltip permanent direction="bottom" className="depot-tip">{short(l.name).replace(' Depot', '')}</Tooltip></Marker>
        ))}
        {map.locations.filter((l) => l.type === 'post').map((l) => (
          <CircleMarker key={l.code} center={[l.lat, l.lon]} radius={selected === l.code ? 13 : 10}
            pathOptions={{ color: selected === l.code ? '#fff' : '#12160f', weight: selected === l.code ? 3 : 2, fillColor: COL[level(l.code)], fillOpacity: 0.95 }}
            eventHandlers={{ click: () => onSelect && onSelect(l.code) }}>
            <Tooltip permanent direction="right" className="post-tip">{short(l.name)}</Tooltip>
          </CircleMarker>
        ))}
      </MapContainer>
      <p className="mu">Square = depot, circle = forward post (colour = days of supply), line colour = route risk, dashed red = closed pass, ▶ / ✈ / M = convoy by road / air / mule. Layers: top-right.</p>
    </>
  );
}
