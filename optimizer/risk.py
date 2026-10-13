"""Route risk model. risk = 0.4*snow + 0.3*slope + 0.2*visibility (+0.1 closure => closed roads are removed)."""
SPEED = 30  # km/h baseline in mountain terrain
DRIVE_H, HALT_H = 10, 8   # max driving hours per day, then an overnight halt

def eta_hours(km, risk):
    drive = km / (SPEED * (1 - 0.5 * risk))
    return drive + int(drive // DRIVE_H) * HALT_H

def components(seg, snow_cm, vis_km):
    sn = min(snow_cm / 10, 1)
    vis = 0.5 * seg["vf"] + 0.5 * (1 - min(vis_km, 15) / 15)
    parts = {"snow": 0.4 * sn, "slope": 0.3 * seg["slope"], "visibility": 0.2 * vis}
    parts["score"] = sum(parts.values())
    return parts

def evaluate(seg, weather):
    snow, vis = weather.get(seg["to"], (0.0, 15.0))
    c = components(seg, snow, vis)
    risk = round(c["score"], 3)
    return {**seg, "risk": risk, "parts": {k: round(v, 3) for k, v in c.items()},
            "cost": seg["km"] * (1 + 3 * risk), "eta": eta_hours(seg["km"], risk)}

def open_edges(segs, weather):
    return [evaluate(s, weather) for s in segs if s["open"]]

def best_route(segs, weather, post, depot=None):
    c = [e for e in open_edges(segs, weather) if e["to"] == post and (depot is None or e["frm"] == depot)]
    return min(c, key=lambda e: e["cost"]) if c else None
