"""Days-of-Supply + predictive alerts (uses the trained forecast model)."""
import sys, math, time, json
from pathlib import Path
import numpy as np, pandas as pd
ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
from ml import forecast as fc            # noqa: E402
from ml.india import ITEM_CATALOG        # noqa: E402
from .. import models as m               # noqa: E402

_cache = {}

def level(dos):
    return "critical" if dos < 3 else "warning" if dos < 7 else "ok"

def days_of_supply(stock, p50):
    cum = np.cumsum(p50)
    if stock >= cum[-1]:
        return len(p50) + (stock - cum[-1]) / max(p50[-7:].mean(), 1e-6)
    k = int(np.searchsorted(cum, stock)); prev = cum[k - 1] if k else 0
    return k + (stock - prev) / max(p50[k], 1e-6)

def best_route(s, post, snow3):
    best = None
    for r in s.query(m.RoadSegment).filter(m.RoadSegment.to_id == post.id, m.RoadSegment.status == "open"):
        r.risk_score = round(0.4 * snow3 + 0.3 * r.slope + 0.2 * r.visibility_factor, 3)
        cost = r.distance_km * (1 + 3 * r.risk_score)
        if best is None or cost < best[0]:
            best = (cost, r)
    return best[1] if best else None

def route_letter(s, route):
    """Route A = shortest road to the post, Route B = next, ... (same lettering as the dashboard)."""
    segs = s.query(m.RoadSegment).filter(m.RoadSegment.to_id == route.to_id).order_by(m.RoadSegment.distance_km).all()
    return chr(65 + [x.id for x in segs].index(route.id))

def risk_word(r):
    return "low" if r < 0.35 else "medium" if r < 0.55 else "high"

def dos_rows(s, spike=None, ttl=5):
    """Cached read-only table (used by dashboards that refresh often)."""
    key = json.dumps(spike, sort_keys=True)
    hit = _cache.get(key)
    if hit and time.time() - hit[0] < ttl:
        return hit[1]
    rows = refresh_alerts(s, write=False, spike=spike)
    _cache[key] = (time.time(), rows)
    return rows

def refresh_alerts(s, write=True, spike=None):
    """spike = {"pct": 30, "post": "P3" or None}: what-if demand surge applied to the forecast."""
    cons, wx = fc.load()
    posts = {p.code: p for p in s.query(m.Location).filter_by(type="post")}
    depots = {d.id: d for d in s.query(m.Location).filter_by(type="depot")}
    inv = {(l.code, i.item): i.stock for i, l in s.query(m.Inventory, m.Location).join(m.Location, m.Location.id == m.Inventory.location_id).filter(m.Location.type == "post")}
    recent_snow = wx[wx.date > wx.date.max() - pd.Timedelta(days=3)].groupby("post").snowfall_cm.mean()
    if write:
        s.query(m.Alert).filter_by(resolved=False).update({"resolved": True})
    table, order, pending = [], {"critical": 0, "warning": 1, "ok": 2}, []
    for (code, item), stock in inv.items():
        f, m7 = fc.forecast(code, item, 14, cons)
        if spike and spike.get("pct") and spike.get("post") in (None, "", code):
            f = f.copy(); f[["p10", "p50", "p90"]] = f[["p10", "p50", "p90"]] * (1 + spike["pct"] / 100)
        dos = days_of_supply(stock, f.p50.values); lv = level(dos)
        mean = float(f.p50.iloc[:7].mean()); chg = 100 * (mean / m7 - 1) if m7 > 0 else 0.0   # slow-moving items can have a zero last week
        need = max(0, math.ceil(f.p90.iloc[:10].sum() - stock))
        table.append({"post": code, "item": item, "stock": stock, "forecast_per_day": round(mean, 1),
                      "dos": round(dos, 1), "level": lv, "need": need, "fill_pct": int(min(100, 100 * stock / max(mean * 14, 1e-6))),
                      "trend_vs_last_7d_%": round(chg, 1), "method": f.attrs.get("method", "")})
        if lv == "ok" or not write:
            continue
        post = posts[code]
        route = best_route(s, post, min(float(recent_snow.get(code, 0)) / 10, 1))
        label = ITEM_CATALOG[item]["label"]
        trucks = max(1, math.ceil(need * ITEM_CATALOG[item]["kg"] / 5000))
        action = (f"Dispatch {trucks} truck{'s' if trucks > 1 else ''} from {depots[route.from_id].name} via Route {route_letter(s, route)} ({risk_word(route.risk_score)} risk, {route.via})"
                  if route else "No open road route: plan air, drone or mule supply")
        when = f"{round(dos * 24)} hours" if dos < 3 else f"{dos:.1f} days"
        pending.append((order[lv], dos, m.Alert(level=lv, location_id=post.id, message=f"{label} shortfall forecast at {post.name} in {when}",
                      reason=f"Forecast use {mean:.0f}/day ({chg:+.0f}% vs last 7 days), stock {stock:.0f}", action=action)))
    if write:
        for _o, _d, a in sorted(pending, key=lambda x: (x[0], x[1])):      # most urgent first
            s.add(a)
        for r in s.query(m.SupplyRequest).filter(m.SupplyRequest.priority == "sos", m.SupplyRequest.status.in_(("approved", "planned"))):
            p = next(x for x in posts.values() if x.id == r.post_id)
            s.add(m.Alert(level="sos", location_id=p.id, message=f"SOS: {ITEM_CATALOG[r.item]['label']} needed at {p.name}",
                          reason=f"Emergency request by {r.requested_by}: {r.qty:g} {r.item}",
                          action="Commander override: planned as top priority (24 h deadline, air, drone or mule allowed)"))
        s.commit()
    return sorted(table, key=lambda r: (order[r["level"]], r["dos"]))
