"""Route risk, multi-mode convoy planning (road / drone / mule / air), what-ifs, balancing, winter stocking, KPIs."""
import sys, json, math
from datetime import timedelta, datetime, timezone
from pathlib import Path
import pandas as pd
from sqlalchemy import func
ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
from optimizer import risk as rk, vrp        # noqa: E402
from ml.india import PASSES, ITEM_CATALOG    # noqa: E402
from .. import models as m                   # noqa: E402
from .. import mqtt_bridge                   # noqa: E402
from . import alerts as al                   # noqa: E402

UNIT_KG = {k: v["kg"] for k, v in ITEM_CATALOG.items()}
PRIORITY = ["Medical", "Ammo", "POL", "Ration", "Spares"]
IMPORTANCE = {"Medical": 5, "Ammo": 4, "POL": 3, "Ration": 3, "Spares": 1}
DEADLINE_H = {"sos": 24, "critical": 72, "warning": 168}
PENALTY = {"sos": 500000, "critical": 200000, "warning": 50000}
AIR = dict(cap=2500, speed=400, prep=4, min_vis=3)                          # air maintenance
DRONE = dict(cap=80, speed=60, range=100, prep=1, min_vis=3, max_sorties=8)   # cargo drone, launched from the nearest node
MULE = dict(cap=600, eta=36)                                                # mule / robotic-mule string
COST = {"road": 1.0, "mule": 1.6, "drone": 3.0, "air": 8.0}                 # relative cost index: airlifts are the costly option
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

def locs_by_code(locs):
    return {l.code: l for l in locs.values()}

def routes_summary(s, snow_cm=None):
    locs, segs, weather = environment(s, snow_cm)
    out = []
    for p in sorted(l.code for l in locs.values() if l.type == "post"):
        b = rk.best_route(segs, weather, p)
        out.append({"post": p, "depot": b["frm"], "via": b["via"], "km": b["km"], "eta_h": round(b["eta"], 1),
                    "risk": b["risk"], "why": b["parts"]} if b else {"post": p, "depot": None, "via": None})
    return out

# ---------- transport mode: road / drone / mule / air, cheapest feasible within the deadline ----------
def mode_options(code, kg, deadline_h, locs, segs, weather):
    lc = locs_by_code(locs); post = lc[code]
    b = rk.best_route(segs, weather, code)
    opts = [{"mode": "road", "feasible": bool(b) and b["eta"] <= deadline_h, "eta_h": round(b["eta"], 1) if b else None, "capacity_kg": 5000,
             "units": max(1, math.ceil(kg / 5000)), "risk": b["risk"] if b else None,
             "reason": f"via {b['via']} from {lc[b['frm']].name}" if b else "All road routes closed"}]
    vis = weather.get(code, (0, 15))[1]
    others = [l for l in locs.values() if l.code != code]
    near = min(others, key=lambda x: vrp.haversine((x.lat, x.lon), (post.lat, post.lon)))
    dk = vrp.haversine((near.lat, near.lon), (post.lat, post.lon)); sorties = max(1, math.ceil(kg / DRONE["cap"]))
    d_ok = dk <= DRONE["range"] and vis >= DRONE["min_vis"] and sorties <= DRONE["max_sorties"]
    why = (f"Cargo drone from {near.name}, {dk:.0f} km, {DRONE['cap']} kg per sortie" if dk <= DRONE["range"] else f"Nearest launch point {near.name} is {dk:.0f} km away (range {DRONE['range']} km)")
    if dk <= DRONE["range"] and sorties > DRONE["max_sorties"]:
        why = f"Load needs {sorties} sorties (limit {DRONE['max_sorties']})"
    elif dk <= DRONE["range"] and vis < DRONE["min_vis"]:
        why += ", visibility too low to fly"
    opts.append({"mode": "drone", "feasible": d_ok, "eta_h": round(dk / DRONE["speed"] + DRONE["prep"], 1) if dk <= DRONE["range"] else None,
                 "capacity_kg": DRONE["cap"], "units": sorties, "risk": 0.2 if d_ok else None, "depot": near.code if near.type == "depot" else None,
                 "launch": near.code, "km": round(dk, 1), "reason": why})
    depots = [l for l in locs.values() if l.type == "depot"]
    d = min(depots, key=lambda x: vrp.haversine((x.lat, x.lon), (post.lat, post.lon)))
    km = vrp.haversine((d.lat, d.lon), (post.lat, post.lon)); air_ok = vis >= AIR["min_vis"]
    opts.append({"mode": "air", "feasible": air_ok, "eta_h": round(km / AIR["speed"] + AIR["prep"], 1), "capacity_kg": AIR["cap"],
                 "units": max(1, math.ceil(kg / AIR["cap"])), "risk": 0.15 if air_ok else 0.8, "depot": d.code, "launch": d.code, "km": round(km, 1),
                 "reason": f"Air maintenance from {d.name}, visibility {vis:.1f} km" + ("" if air_ok else " (below 3 km: grounded)")})
    mule_ok = bool(post.mule_ok)
    opts.append({"mode": "mule", "feasible": mule_ok, "eta_h": MULE["eta"] if mule_ok else None, "capacity_kg": MULE["cap"],
                 "units": max(1, math.ceil(kg / MULE["cap"])), "risk": 0.3 if mule_ok else None, "depot": d.code, "launch": d.code, "km": round(km, 1),
                 "reason": "Mule / robotic-mule string on the last-mile track" if mule_ok else "No mule track at this post"})
    for o in opts:
        o["cost_index"] = COST[o["mode"]]
    ok = [o for o in opts if o["feasible"] and o["eta_h"] is not None and o["eta_h"] <= deadline_h]
    pick = min(ok, key=lambda o: (o["cost_index"], o["eta_h"])) if ok else None
    if not pick:
        feas = [o for o in opts if o["feasible"] and o["eta_h"] is not None]
        pick = min(feas, key=lambda o: o["eta_h"]) if feas else None
    for o in opts:
        o["recommended"] = o is pick
    return opts

def route_options(s, post, kg=1000, urgency="critical", snow_cm=None):
    locs, segs, weather = environment(s, snow_cm)
    if post not in locs_by_code(locs):
        raise KeyError("Unknown post")
    best = rk.best_route(segs, weather, post)
    mine = sorted([sg for sg in segs if sg["to"] == post], key=lambda sg: sg["km"])
    routes = []
    for n, sg in enumerate(mine):
        e = rk.evaluate(sg, weather)
        routes.append({"label": f"Route {chr(65 + n)}", "depot": sg["frm"], "depot_name": locs_by_code(locs)[sg["frm"]].name, "via": sg["via"], "pass": sg["pass_name"],
                       "km": sg["km"], "eta_h": round(e["eta"], 1), "risk": e["risk"], "open": sg["open"], "best": bool(best) and best["id"] == sg["id"]})
    routes.sort(key=lambda r: (not r["open"], r["eta_h"]))
    return {"post": post, "routes": routes, "modes": mode_options(post, kg, DEADLINE_H.get(urgency, 72), locs, segs, weather)}

# ---------- convoy planning ----------
def _save(s, plan, post_id, depot_id, route_id, base, seq):
    code = f"CV-{base + seq:03d}"
    s.add(m.Convoy(code=code, post_id=post_id, depot_id=depot_id, route_id=route_id, load_json=json.dumps(plan),
                   status="proposed", mode=plan["mode"], eta_hours=plan["stops"][-1]["eta_h"]))
    return {"code": code, "status": "proposed", **plan}

MODE_LABEL = {"air": ("Air maintenance (IAF)", "sortie(s)"), "drone": ("Cargo drone", "sortie(s)"), "mule": ("Mule / robotic mule", "string(s)")}

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
    for k in dropped:      # roads closed or too slow: urgent light items by drone if possible, the bulk by mule / air (cheapest that meets the deadline)
        d = drops[k]; light, rest, kg_l = {}, {}, 0
        for it, q in d["items"].items():            # items are already in priority order (Medical, Ammo, ...)
            w = q * UNIT_KG[it]
            if not rest and kg_l + w <= DRONE["cap"] * DRONE["max_sorties"]:
                light[it] = q; kg_l += w
            else:
                rest[it] = q
        parts = [light, rest] if light and rest else [d["items"]]
        placed = False
        for part in parts:
            kg = sum(q * UNIT_KG[i] for i, q in part.items())
            opts = mode_options(d["post"], kg, DEADLINE_H[d["priority"]], locs, segs, weather)
            rec = next((o for o in opts if o["recommended"] and o["mode"] != "road"), None)
            if not rec:
                continue
            label, unit = MODE_LABEL[rec["mode"]]
            launch = rec.get("depot") or rec.get("launch") or "D1"
            pc = c2l[d["post"]]
            depot_code = launch if c2l[launch].type == "depot" else min((l for l in locs.values() if l.type == "depot"), key=lambda x: vrp.haversine((x.lat, x.lon), (pc.lat, pc.lon))).code
            plan = {"mode": rec["mode"], "vehicle": f"{rec['mode'].upper()}-x{rec['units']}", "vehicle_type": f"{label}, {rec['units']} {unit}",
                    "capacity_kg": rec["capacity_kg"] * rec["units"], "depot": depot_code,
                    "stops": [{"post": d["post"], "eta_h": rec["eta_h"], "items": part, "kg": kg, "priority": d["priority"],
                               "via": {"air": "Air corridor", "drone": "Drone corridor", "mule": "Mule track"}[rec["mode"]]}],
                    "load_kg": kg, "km": rec["km"], "max_risk": rec["risk"]}
            seq += 1; placed = True
            plans.append(_save(s, plan, pc.id, c2l[depot_code].id, None, base, seq))
        if not placed:
            unserved.append(d["post"])
    served = {st["post"] for p in plans for st in p["stops"]}
    for r in reqs:
        if locs[r.post_id].code in served:
            r.status = "planned"
    s.commit()
    return {"convoys": plans, "unserved_posts": unserved, "posts_needing_supply": len(drops)}

def list_convoys(s):
    return [{**json.loads(c.load_json), "code": c.code, "status": c.status, "mode": c.mode or "road", "note": c.note or "",
             "progress": c.progress or 0, "gps_ok": True if c.gps_ok is None else bool(c.gps_ok),
             "pos_time": str(c.pos_time)[:19] if c.pos_time else None} for c in s.query(m.Convoy).order_by(m.Convoy.id)]

FLOW = {"approved": "proposed", "loaded": "approved", "in_transit": "loaded", "delivered": "in_transit"}

def set_status(s, code, status, user="system"):
    c = s.query(m.Convoy).filter_by(code=code).first()
    if not c:
        raise KeyError("Convoy not found")
    if status != "rejected" and FLOW.get(status) != c.status:
        raise ValueError(f"Cannot move from {c.status} to {status}")
    plan = json.loads(c.load_json); changed = []
    inv = lambda loc_code, item: s.query(m.Inventory).join(m.Location, m.Location.id == m.Inventory.location_id).filter(m.Location.code == loc_code, m.Inventory.item == item).first()
    v = s.query(m.Vehicle).filter_by(code=plan["vehicle"]).first()
    if status == "approved" and v:
        v.status = "assigned"
    if status == "loaded":
        c.progress, c.gps_ok = 0.02, True
        for st in plan["stops"]:
            for item, q in st["items"].items():
                row = inv(plan["depot"], item); row.stock = max(0, row.stock - q); changed.append((plan["depot"], item, row.stock))
    if status == "delivered":
        c.progress = 1.0
        for st in plan["stops"]:
            for item, q in st["items"].items():
                row = inv(st["post"], item); row.stock += q; changed.append((st["post"], item, row.stock))
        if v:
            v.status = "available"
    if status == "rejected" and v:
        v.status = "available"
    c.status = status
    s.add(m.AuditLog(username=user, action=f"Convoy {code} -> {status}"))
    s.commit()
    al._cache.clear()
    for loc, item, stock in changed:      # keep the edge nodes in step with the real stock
        mqtt_bridge.publish(f"astra/adjust/{loc}", {"item": item, "stock": stock})
    return {"code": code, "status": status}

def set_position(s, code, progress, gps_ok, user):
    """Transport reports convoy position (0..1 along the route). GPS lost = last known position stays on the map."""
    c = s.query(m.Convoy).filter_by(code=code).first()
    if not c:
        raise KeyError("Convoy not found")
    if c.status not in ("loaded", "in_transit"):
        raise ValueError("Position can be reported only while a convoy is loaded or in transit")
    if not 0 <= progress <= 1:
        raise ValueError("progress must be between 0 and 1")
    if gps_ok:
        c.progress = progress
    c.gps_ok, c.pos_time = gps_ok, datetime.now(timezone.utc)
    s.add(m.AuditLog(username=user, action=f"{code} position {progress:.0%}" + ("" if gps_ok else " (GPS lost: last known position kept, LoRa fallback)")))
    s.commit()
    return {"code": code, "progress": c.progress, "gps_ok": gps_ok}

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
    locs = {l.id: l for l in s.query(m.Location) if l.type == "post"}; out = []
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
                    "stale": age > 120, "age_s": int(age), "buffered": n.buffered or 0, "battery": n.battery, "rfid_tags": n.rfid_tags,
                    "rejected": n.rejected or 0})
    return out

# ---------- inventory balancing: move surplus to predicted shortfalls, flag non-moving stock ----------
SURPLUS_DAYS, NON_MOVING_DAYS = 21, 90

def balancing(s):
    rows = al.dos_rows(s); locs, segs, weather = environment(s); lc = locs_by_code(locs)
    inv = {(l.code, i.item): (i.stock, i.reorder_level) for i, l in s.query(m.Inventory, m.Location).join(m.Location, m.Location.id == m.Inventory.location_id).filter(m.Location.type == "depot")}
    edge = {(e["frm"], e["to"]): e for e in rk.open_edges(segs, weather)}
    surplus = {}; non_moving = []; total_kg = nm_kg = 0.0
    for r in rows:
        kg = UNIT_KG[r["item"]]; total_kg += r["stock"] * kg
        keep = r["forecast_per_day"] * SURPLUS_DAYS
        if r["dos"] > SURPLUS_DAYS and r["stock"] > keep:
            surplus[(r["post"], r["item"])] = r["stock"] - keep
        if r["dos"] > NON_MOVING_DAYS:
            nm_kg += (r["stock"] - keep) * kg
            non_moving.append({"post": r["post"], "item": r["item"], "stock": r["stock"], "dos": r["dos"], "excess_qty": round(r["stock"] - keep), "excess_kg": round((r["stock"] - keep) * kg)})
    transfers, unmet = [], []
    for r in sorted((x for x in rows if x["level"] != "ok" and x["need"] > 0), key=lambda x: x["dos"]):
        need, tgt, item = r["need"], lc[r["post"]], r["item"]
        while need > 0:
            cands = []
            for (pc, it), q in surplus.items():
                if it == item and q > 0.5 and pc != r["post"]:
                    km = vrp.haversine((lc[pc].lat, lc[pc].lon), (tgt.lat, tgt.lon)) * 1.4
                    cands.append((rk.eta_hours(km, 0.3), "post", pc, q, km))
            for d in (l for l in locs.values() if l.type == "depot"):
                e = edge.get((d.code, r["post"])); stock, reorder = inv.get((d.code, item), (0, 0))
                if e and stock - reorder > 0.5 and (d.code, item) not in {(t["from"], t["item"]) for t in transfers if t.get("exhausted")}:
                    cands.append((e["eta"], "depot", d.code, stock - reorder, e["km"]))
            if not cands:
                unmet.append({"post": r["post"], "item": item, "qty": round(need)}); break
            eta, kind, src, avail, km = min(cands)
            q = min(need, avail)
            transfers.append({"item": item, "from": src, "from_name": lc[src].name, "from_type": kind, "to": r["post"], "to_name": tgt.name,
                              "qty": round(q), "kg": round(q * UNIT_KG[item]), "km": round(km), "eta_h": round(eta, 1), "dos_before": r["dos"]})
            if kind == "post":
                surplus[(src, item)] -= q
            else:
                inv[(src, item)] = (inv[(src, item)][0] - q, inv[(src, item)][1])
            need -= q
    return {"transfers": transfers, "unmet": unmet, "non_moving": sorted(non_moving, key=lambda x: -x["excess_kg"]),
            "surplus": [{"post": p, "item": i, "excess_qty": round(q)} for (p, i), q in surplus.items() if q > 0.5],
            "summary": {"transfers": len(transfers), "moved_kg": sum(t["kg"] for t in transfers),
                        "non_moving_pct": round(100 * nm_kg / max(total_kg, 1), 1), "non_moving_lines": len(non_moving)}}

def priority_ranking(s, top=12):
    """Rank scarce items: importance x troops depending on it / days left."""
    rows = al.dos_rows(s); lc = {l.code: l for l in s.query(m.Location)}
    out = []
    for r in rows:
        if r["level"] == "ok":
            continue
        troops = lc[r["post"]].troop_strength or 0
        score = IMPORTANCE[r["item"]] * (troops / 100) / max(r["dos"], 0.5)
        out.append({"post": r["post"], "name": lc[r["post"]].name, "item": r["item"], "dos": r["dos"], "troops": troops, "level": r["level"], "score": round(score, 2)})
    out.sort(key=lambda x: -x["score"])
    return [{**o, "rank": i + 1} for i, o in enumerate(out[:top])]

# ---------- advance winter stocking ----------
def winter_plan(s, closure_days=45, winter_days=120, early_days=0):
    """Winter need per post (history of Dec-Mar use) versus stock, and what the road fleet can still move before the passes close."""
    from ml import forecast as fc
    cons, _ = fc.load(); cons = cons[cons.date.dt.month.isin([12, 1, 2, 3])]
    wd = cons.groupby(["post", "item"]).qty.mean().to_dict()
    locs, segs, weather = environment(s); lc = locs_by_code(locs)
    stock = {(l.code, i.item): i.stock for i, l in s.query(m.Inventory, m.Location).join(m.Location, m.Location.id == m.Inventory.location_id).filter(m.Location.type == "post")}
    veh = {}
    for v in s.query(m.Vehicle).filter(m.Vehicle.health_pct >= 70):
        veh[locs[v.depot_id].code] = veh.get(locs[v.depot_id].code, 0) + v.capacity_kg
    posts = []
    for p in sorted(l.code for l in locs.values() if l.type == "post"):
        b = rk.best_route(segs, weather, p)
        items, need_kg, stock_kg, gap_kg = [], 0.0, 0.0, 0.0
        for it in UNIT_KG:
            need = wd.get((p, it), 0) * winter_days; have = stock.get((p, it), 0); gap = max(0.0, need - have)
            need_kg += need * UNIT_KG[it]; stock_kg += min(have, need) * UNIT_KG[it]; gap_kg += gap * UNIT_KG[it]
            items.append({"item": it, "winter_need": round(need), "stock": round(have), "gap": round(gap)})
        posts.append({"post": p, "name": lc[p].name, "depot": b["frm"] if b else None, "via": b["via"] if b else None, "eta_h": round(b["eta"], 1) if b else None,
                      "need_t": round(need_kg / 1000, 1), "stock_t": round(stock_kg / 1000, 1), "gap_t": round(gap_kg / 1000, 1),
                      "trucks": math.ceil(gap_kg / 5000) if gap_kg else 0, "items": items, "_gap": gap_kg})

    def run(days_left):
        by_depot = {}
        for p in posts:
            if p["depot"]:
                by_depot.setdefault(p["depot"], []).append(p)
        moved = 0.0; fill = {}
        for d, ps in by_depot.items():
            gap = sum(x["_gap"] for x in ps); rt = max(sum(2 * x["eta_h"] / 24 + 1 for x in ps) / len(ps), 1)
            cap = veh.get(d, 0) * (max(days_left, 0) / rt)
            f = min(1.0, cap / gap) if gap else 1.0
            for x in ps:
                fill[x["post"]] = f
            moved += min(cap, gap)
        total = sum(p["_gap"] for p in posts)
        return fill, moved, total
    fill, moved, total = run(closure_days - early_days)
    _, moved0, _ = run(closure_days)
    weeks = max(closure_days - early_days, 0) / 7
    for p in posts:
        f = fill.get(p["post"], 0.0); p["deliverable_pct"] = round(100 * f); p["shortfall_t"] = round(p["gap_t"] * (1 - f), 1)
        p["weekly_t"] = round(p["gap_t"] / weeks, 1) if weeks else None; del p["_gap"]
    return {"params": {"closure_days": closure_days, "winter_days": winter_days, "early_days": early_days, "weeks_left": round(weeks, 1)},
            "summary": {"need_t": round(sum(p["need_t"] for p in posts), 1), "stock_t": round(sum(p["stock_t"] for p in posts), 1),
                        "gap_t": round(total / 1000, 1), "deliverable_t": round(moved / 1000, 1),
                        "feasible_pct": round(100 * moved / total) if total else 100,
                        "feasible_pct_normal_closure": round(100 * moved0 / total) if total else 100,
                        "shortfall_t": round((total - moved) / 1000, 1)}, "posts": posts}

def kpis(s):
    rows = al.dos_rows(s); conv = list_convoys(s); bal = balancing(s)
    mm = json.loads(METRICS.read_text()) if METRICS.exists() else {}
    allm = (mm.get("metrics") or {}).get("ALL", {})
    active = [c for c in conv if c["status"] in ("proposed", "approved", "loaded", "in_transit")]
    lead = [c["stops"][0]["eta_h"] for c in active]
    road = [c for c in conv if c["mode"] == "road" and c["capacity_kg"]]
    return {"lines": len(rows), "critical_lines": sum(r["level"] == "critical" for r in rows), "warning_lines": sum(r["level"] == "warning" for r in rows),
            "avg_dos": round(sum(r["dos"] for r in rows) / max(len(rows), 1), 1),
            "stockout_risk_pct": round(100 * sum(r["level"] == "critical" for r in rows) / max(len(rows), 1), 1),
            "mape_pct": allm.get("daily_MAPE_%"), "naive_mape_pct": allm.get("naive_daily_MAPE_%"), "mase": allm.get("MASE"), "naive_mase": allm.get("naive_MASE"),
            "band_coverage_pct": allm.get("80%_band_coverage_%"),
            "avg_first_stop_eta_h": round(sum(lead) / len(lead), 1) if lead else None,
            "non_moving_pct": bal["summary"]["non_moving_pct"], "balancing_moved_kg": bal["summary"]["moved_kg"],
            "utilisation_pct": round(100 * sum(c["load_kg"] for c in road) / sum(c["capacity_kg"] for c in road)) if road else None,
            "convoys": {st: sum(c["status"] == st for c in conv) for st in ("proposed", "approved", "loaded", "in_transit", "delivered", "held")},
            "modes": {md: sum(c["mode"] == md for c in conv) for md in ("road", "drone", "mule", "air")},
            "targets_pct_of_baseline": {"Response time": 55, "Planning effort": 50, "Wastage": 65, "Delivery delay": 70, "Stock-outs": 40}}
