"""Route risk, multi-mode (road / air / mule) convoy planning, what-ifs, KPIs."""
import sys, json, math
from datetime import timedelta, datetime, timezone
from pathlib import Path
from sqlalchemy import func
ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
from optimizer import risk as rk, vrp        # noqa: E402
from ml.india import PASSES                  # noqa: E402
from .. import models as m                   # noqa: E402
from . import alerts as al                   # noqa: E402

UNIT_KG = {"Ration": 2, "POL": 10, "Ammo": 5, "Medical": 1}
PRIORITY = ["Medical", "Ammo", "POL", "Ration"]
DEADLINE_H = {"sos": 24, "critical": 72, "warning": 168}
PENALTY = {"sos": 500000, "critical": 200000, "warning": 50000}
AIR = dict(cap=2500, speed=400, prep=4, min_vis=3)     # air maintenance: kg per sortie, km/h, prep hours, minimum visibility km
MULE = dict(cap=600, eta=36)                           # mule / porter string: kg, hours from road head
METRICS = ROOT / "ml" / "metrics.json"

def environment(s, snow_cm=None):
    locs = {l.id: l for l in s.query(m.Location)}
    last = s.query(func.max(m.Weather.date)).scalar()
    agg = {}
    for w in s.query(m.Weather).filter(m.Weather.date > last - timedelta(days=3)):
        agg.setdefault(locs[w.location_id].code, []).append((w.snowfall_cm, w.visibility_km))
    weather = {c: (sum(a for a, _ in v) / len(v), sum(b for _, b in v) / len(v)) for c, v in agg.items()}
    if snow_cm is not None:      # scenario: same snowfall everywhere
        weather = {c: (snow_cm, max(0.3, 12 - 1.4 * snow_cm)) for c in weather}
    segs = [dict(id=r.id, frm=locs[r.from_id].code, to=locs[r.to_id].code, via=r.via, km=r.distance_km, slope=r.slope,
                 vf=r.visibility_factor, pass_name=r.pass_name, open=r.status == "open", wp=json.loads(r.waypoints or "[]"))
            for r in s.query(m.RoadSegment)]
    return locs, segs, weather

def routes_summary(s, snow_cm=None):
    locs, segs, weather = environment(s, snow_cm)
    out = []
    for p in sorted(l.code for l in locs.values() if l.type == "post"):
        b = rk.best_route(segs, weather, p)
        out.append({"post": p, "depot": b["frm"], "via": b["via"], "km": b["km"], "eta_h": round(b["eta"], 1),
                    "risk": b["risk"], "why": b["parts"]} if b else {"post": p, "depot": None, "via": None})
    return out

# ---------- transport mode selection: road / air / mule ----------
def mode_options(code, kg, deadline_h, locs, segs, weather):
    post = next(l for l in locs.values() if l.code == code)
    b = rk.best_route(segs, weather, code)
    opts = [{"mode": "road", "feasible": bool(b) and b["eta"] <= deadline_h, "eta_h": round(b["eta"], 1) if b else None,
             "capacity_kg": 5000, "units": max(1, math.ceil(kg / 5000)), "risk": b["risk"] if b else None,
             "reason": f"via {b['via']} from {locs_by_code(locs)[b['frm']].name}" if b else "All road routes closed"}]
    depots = [l for l in locs.values() if l.type == "depot"]
    d = min(depots, key=lambda x: vrp.haversine((x.lat, x.lon), (post.lat, post.lon)))
    km = vrp.haversine((d.lat, d.lon), (post.lat, post.lon))
    vis = weather.get(code, (0, 15))[1]; air_ok = vis >= AIR["min_vis"]
    opts.append({"mode": "air", "feasible": air_ok, "eta_h": round(km / AIR["speed"] + AIR["prep"], 1), "capacity_kg": AIR["cap"],
                 "units": max(1, math.ceil(kg / AIR["cap"])), "risk": 0.15 if air_ok else 0.8, "depot": d.code, "km": round(km, 1),
                 "reason": f"Air maintenance from {d.name}, visibility {vis:.1f} km" + ("" if air_ok else " (below 3 km: grounded)")})
    mule_ok = bool(post.mule_ok)
    opts.append({"mode": "mule", "feasible": mule_ok, "eta_h": MULE["eta"] if mule_ok else None, "capacity_kg": MULE["cap"],
                 "units": max(1, math.ceil(kg / MULE["cap"])), "risk": 0.3 if mule_ok else None, "depot": d.code, "km": round(km, 1),
                 "reason": "Mule/porter string on the last-mile track" if mule_ok else "No mule track at this post"})
    pick = next((o for o in opts if o["feasible"] and o["eta_h"] is not None and o["eta_h"] <= deadline_h), None)
    if not pick:
        feas = [o for o in opts if o["feasible"] and o["eta_h"] is not None]
        pick = min(feas, key=lambda o: o["eta_h"]) if feas else None
    for o in opts:
        o["recommended"] = o is pick
    return opts

def locs_by_code(locs):
    return {l.code: l for l in locs.values()}

def route_options(s, post, kg=1000, urgency="critical", snow_cm=None):
    locs, segs, weather = environment(s, snow_cm)
    if post not in locs_by_code(locs):
        raise KeyError("Unknown post")
    best = rk.best_route(segs, weather, post)
    routes = []
    for sg in segs:
        if sg["to"] != post:
            continue
        e = rk.evaluate(sg, weather)
        routes.append({"depot": sg["frm"], "depot_name": locs_by_code(locs)[sg["frm"]].name, "via": sg["via"], "pass": sg["pass_name"],
                       "km": sg["km"], "eta_h": round(e["eta"], 1), "risk": e["risk"], "open": sg["open"],
                       "best": bool(best) and best["id"] == sg["id"]})
    routes.sort(key=lambda r: (not r["open"], r["eta_h"]))
    return {"post": post, "routes": routes, "modes": mode_options(post, kg, DEADLINE_H.get(urgency, 72), locs, segs, weather)}

# ---------- convoy planning ----------
def _save(s, plan, post_id, depot_id, route_id, base, seq):
    code = f"CV-{base + seq:03d}"
    s.add(m.Convoy(code=code, post_id=post_id, depot_id=depot_id, route_id=route_id, load_json=json.dumps(plan),
                   status="proposed", mode=plan["mode"], eta_hours=plan["stops"][-1]["eta_h"]))
    return {"code": code, "status": "proposed", **plan}

def generate_plan(s, snow_cm=None, spike=None):
    locs, segs, weather = environment(s, snow_cm)
    c2l = locs_by_code(locs)
    table = [r for r in al.refresh_alerts(s, write=False, spike=spike) if r["level"] != "ok" and r["need"] > 0]
    by_post = {}
    for r in table:
        by_post.setdefault(r["post"], []).append(r)
    reqs = s.query(m.SupplyRequest).filter_by(status="approved").all()
    for r in reqs:      # approved requests and SOS overrides join the plan
        rows = by_post.setdefault(locs[r.post_id].code, [])
        lvl = "sos" if r.priority == "sos" else "critical" if r.priority == "high" else "warning"
        ex = next((x for x in rows if x["item"] == r.item), None)
        if ex:
            ex["need"] = max(ex["need"], int(r.qty)); ex["level"] = lvl if lvl == "sos" or ex["level"] == "warning" else ex["level"]
        else:
            rows.append({"post": locs[r.post_id].code, "item": r.item, "need": int(r.qty), "level": lvl})
    drops = []
    for post, rows in by_post.items():
        prio = "sos" if any(r["level"] == "sos" for r in rows) else "critical" if any(r["level"] == "critical" for r in rows) else "warning"
        items = {r["item"]: r["need"] for r in sorted(rows, key=lambda r: PRIORITY.index(r["item"]))}
        drops.append({"post": post, "items": items, "kg": sum(q * UNIT_KG[i] for i, q in items.items()), "priority": prio,
                      "deadline_min": DEADLINE_H[prio] * 60, "penalty": PENALTY[prio]})
    vehicles = [{"code": v.code, "type": v.type, "depot": locs[v.depot_id].code, "cap": v.capacity_kg}
                for v in s.query(m.Vehicle).filter(m.Vehicle.status == "available", m.Vehicle.health_pct >= 70)]
    depots = sorted(l.code for l in locs.values() if l.type == "depot")
    edge = {(e["frm"], e["to"]): e for e in rk.open_edges(segs, weather)}
    coords = {c: (l.lat, l.lon) for c, l in c2l.items()}
    s.query(m.Convoy).filter_by(status="proposed").delete()
    base = max([int(c.code.split("-")[1]) for c in s.query(m.Convoy)] or [0]); seq = 0
    routes, dropped = vrp.solve(depots, vehicles, drops, edge, coords) if drops else ([], [])
    plans, unserved = [], []
    for r in routes:
        veh, depot = r["vehicle"], r["vehicle"]["depot"]; stops, risks, first = [], [], None
        for st in r["stops"]:
            d = drops[st["drop"]]; e = edge.get((depot, d["post"])); risks.append(e["risk"] if e else 0)
            first = first or e
            stops.append({"post": d["post"], "eta_h": round(st["arrive_min"] / 60, 1), "items": d["items"], "kg": d["kg"],
                          "priority": d["priority"], "via": e["via"] if e else None})
        plan = {"mode": "road", "vehicle": veh["code"], "vehicle_type": veh["type"], "capacity_kg": veh["cap"], "depot": depot,
                "stops": stops, "load_kg": sum(x["kg"] for x in stops), "km": r["km"], "max_risk": max(risks)}
        seq += 1
        plans.append(_save(s, plan, c2l[stops[0]["post"]].id, c2l[depot].id, first["id"] if first else None, base, seq))
    for k in dropped:      # roads closed or too slow: try air maintenance, then mule/porter
        d = drops[k]; opts = mode_options(d["post"], d["kg"], DEADLINE_H[d["priority"]], locs, segs, weather)
        rec = next((o for o in opts if o["recommended"] and o["mode"] != "road"), None)
        if not rec:
            unserved.append(d["post"]); continue
        label = "Air maintenance (IAF)" if rec["mode"] == "air" else "Mule / porter string"
        plan = {"mode": rec["mode"], "vehicle": f"{rec['mode'].upper()}-x{rec['units']}", "vehicle_type": f"{label}, {rec['units']} {'sortie(s)' if rec['mode'] == 'air' else 'string(s)'}",
                "capacity_kg": rec["capacity_kg"] * rec["units"], "depot": rec["depot"],
                "stops": [{"post": d["post"], "eta_h": rec["eta_h"], "items": d["items"], "kg": d["kg"], "priority": d["priority"],
                           "via": "Air corridor" if rec["mode"] == "air" else "Mule track"}],
                "load_kg": d["kg"], "km": rec["km"], "max_risk": rec["risk"]}
        seq += 1
        plans.append(_save(s, plan, c2l[d["post"]].id, c2l[rec["depot"]].id, None, base, seq))
    served = {st["post"] for p in plans for st in p["stops"]}
    for r in reqs:
        if locs[r.post_id].code in served:
            r.status = "planned"
    s.commit()
    return {"convoys": plans, "unserved_posts": unserved, "posts_needing_supply": len(drops)}

def list_convoys(s):
    return [{**json.loads(c.load_json), "code": c.code, "status": c.status, "mode": c.mode or "road", "note": c.note or ""}
            for c in s.query(m.Convoy).order_by(m.Convoy.id)]

FLOW = {"approved": "proposed", "loaded": "approved", "in_transit": "loaded", "delivered": "in_transit"}

def set_status(s, code, status, user="system"):
    c = s.query(m.Convoy).filter_by(code=code).first()
    if not c:
        raise KeyError("Convoy not found")
    if status != "rejected" and FLOW.get(status) != c.status:
        raise ValueError(f"Cannot move from {c.status} to {status}")
    plan = json.loads(c.load_json)
    inv = lambda loc_code, item: s.query(m.Inventory).join(m.Location, m.Location.id == m.Inventory.location_id).filter(m.Location.code == loc_code, m.Inventory.item == item).first()
    v = s.query(m.Vehicle).filter_by(code=plan["vehicle"]).first()
    if status == "approved" and v:
        v.status = "assigned"
    if status == "loaded":
        for st in plan["stops"]:
            for item, q in st["items"].items():
                row = inv(plan["depot"], item); row.stock = max(0, row.stock - q)
    if status == "delivered":
        for st in plan["stops"]:
            for item, q in st["items"].items():
                row = inv(st["post"], item); row.stock += q
        if v:
            v.status = "available"
    if status == "rejected" and v:
        v.status = "available"
    c.status = status
    s.add(m.AuditLog(username=user, action=f"Convoy {code} -> {status}"))
    s.commit()
    al._cache.clear()
    return {"code": code, "status": status}

def override(s, code, action, note, user):
    """Commander manual override: hold a convoy or release it again."""
    c = s.query(m.Convoy).filter_by(code=code).first()
    if not c:
        raise KeyError("Convoy not found")
    if action == "hold":
        if c.status in ("delivered", "rejected", "held"):
            raise ValueError(f"Cannot hold a convoy that is {c.status}")
        c.note = f"prev:{c.status}|{note}"; c.status = "held"
    elif action == "release":
        if c.status != "held":
            raise ValueError("Convoy is not on hold")
        c.status = (c.note or "prev:approved").split("|")[0][5:]; c.note = f"released: {note}"
    else:
        raise ValueError("action must be hold or release")
    s.add(m.AuditLog(username=user, action=f"Override {action} {code}: {note}"))
    s.commit()
    return {"code": code, "status": c.status}

def set_pass(s, pass_name, closed, snow_cm=None, user="system"):
    before = {r["post"]: r for r in routes_summary(s, snow_cm)}
    n = s.query(m.RoadSegment).filter_by(pass_name=pass_name).update({"status": "closed" if closed else "open"})
    s.commit()
    after = {r["post"]: r for r in routes_summary(s, snow_cm)}
    changes = [{"post": p, "before": before[p], "after": after[p]} for p in before
               if (before[p].get("via"), before[p].get("depot")) != (after[p].get("via"), after[p].get("depot"))]
    replanned = generate_plan(s, snow_cm) if s.query(m.Convoy).filter_by(status="proposed").count() else None
    s.add(m.AuditLog(username=user, action=f"{pass_name} {'closed' if closed else 'reopened'}"))
    s.commit()
    return {"segments_changed": n, "route_changes": changes, "replanned": replanned}

def map_data(s):
    locs, segs, weather = environment(s)
    best = {}
    for p in (l.code for l in locs.values() if l.type == "post"):
        b = rk.best_route(segs, weather, p)
        if b:
            best[b["id"]] = True
    out = []
    for sg in segs:
        e = rk.evaluate(sg, weather)
        out.append({"from": sg["frm"], "to": sg["to"], "via": sg["via"], "pass_name": sg["pass_name"], "open": sg["open"],
                    "risk": e["risk"], "km": sg["km"], "eta_h": round(e["eta"], 1), "best": bool(best.get(sg["id"])), "wp": sg["wp"]})
    passes = [{"name": n, "lat": c[0], "lon": c[1], "open": not any(x["pass_name"] == n and not x["open"] for x in segs)} for n, c in PASSES.items()]
    return {"locations": [{"code": l.code, "name": l.name, "type": l.type, "lat": l.lat, "lon": l.lon, "alt": l.altitude_m, "mule": bool(l.mule_ok)} for l in locs.values()],
            "segments": out, "passes": passes}

def weather_rows(s):
    locs = {l.id: l for l in s.query(m.Location) if l.type == "post"}
    last = s.query(func.max(m.Weather.date)).scalar(); out = []
    for lid, l in locs.items():
        rows = s.query(m.Weather).filter(m.Weather.location_id == lid).order_by(m.Weather.date.desc()).limit(3).all()
        if rows:
            r = rows[0]
            out.append({"post": l.code, "name": l.name, "date": str(r.date), "snow_cm": r.snowfall_cm, "temp_c": r.temp_c, "vis_km": r.visibility_km,
                        "snow_3d_cm": round(sum(x.snowfall_cm for x in rows), 1)})
    return out

def edge_nodes(s, scope_codes=None, own_loc=None):
    locs = {l.id: l for l in s.query(m.Location)}; now = datetime.now(timezone.utc); out = []
    for n in s.query(m.EdgeNode):
        l = locs[n.location_id]
        if scope_codes is not None and l.code not in scope_codes and l.id != own_loc:
            continue
        seen = n.last_seen if n.last_seen.tzinfo else n.last_seen.replace(tzinfo=timezone.utc)
        age = (now - seen).total_seconds()
        out.append({"code": n.code, "location": l.code, "name": l.name, "type": l.type, "link": n.link, "online": bool(n.online),
                    "stale": age > 120, "age_s": int(age), "buffered": n.buffered or 0, "battery": n.battery, "rfid_tags": n.rfid_tags})
    return out

def kpis(s):
    rows = al.dos_rows(s); conv = list_convoys(s)
    mm = json.loads(METRICS.read_text()) if METRICS.exists() else {}
    allm = (mm.get("metrics") or {}).get("ALL", {})
    active = [c for c in conv if c["status"] in ("proposed", "approved", "loaded", "in_transit")]
    lead = [c["stops"][0]["eta_h"] for c in active]
    return {"lines": len(rows), "critical_lines": sum(r["level"] == "critical" for r in rows), "warning_lines": sum(r["level"] == "warning" for r in rows),
            "avg_dos": round(sum(r["dos"] for r in rows) / max(len(rows), 1), 1),
            "stockout_risk_pct": round(100 * sum(r["level"] == "critical" for r in rows) / max(len(rows), 1), 1),
            "mape_pct": allm.get("daily_MAPE_%"), "naive_mape_pct": allm.get("naive_daily_MAPE_%"), "band_coverage_pct": allm.get("80%_band_coverage_%"),
            "avg_first_stop_eta_h": round(sum(lead) / len(lead), 1) if lead else None,
            "convoys": {st: sum(c["status"] == st for c in conv) for st in ("proposed", "approved", "loaded", "in_transit", "delivered", "held")},
            "modes": {md: sum(c["mode"] == md for c in conv) for md in ("road", "air", "mule")},
            "targets_pct_of_baseline": {"Response time": 55, "Planning effort": 50, "Wastage": 65, "Delivery delay": 70, "Stock-outs": 40}}
