import asyncio
from contextlib import asynccontextmanager
from datetime import date
from fastapi import FastAPI, HTTPException, Depends, WebSocket, WebSocketDisconnect
from fastapi.security import OAuth2PasswordRequestForm
from pydantic import BaseModel
from sqlalchemy import text
from .db import engine, SessionLocal
from . import models as m
from . import mqtt_bridge
from .auth import (require, current_user, make_token, verify, hash_pw, decode, check_lock, record_fail, clear_fail, ROLES, EXPIRE_MIN)
from .services import alerts as al, planner as pl, mlops, weather_live
from .ws import hub, ALL

ITEMS = ["Ration", "POL", "Ammo", "Medical"]

@asynccontextmanager
async def lifespan(app):
    hub.loop = asyncio.get_running_loop()
    mqtt_bridge.start()
    yield
    mqtt_bridge.stop()

app = FastAPI(title="ASTRA-LOG API (Predictive Logistics & Forward Supply Chain)", lifespan=lifespan)

def _db(fn):
    s = SessionLocal()
    try:
        return fn(s)
    except KeyError as e:
        raise HTTPException(404, str(e))
    except ValueError as e:
        raise HTTPException(400, str(e))
    finally:
        s.close()

def audit(s, user, action):
    s.add(m.AuditLog(username=user, action=action)); s.commit()

def scope(s, u):
    """Post codes this user may see. None = all posts."""
    if u["role"] == "post":
        return {s.get(m.Location, u["loc"]).code}
    if u["role"] == "depot":
        ids = [x.to_id for x in s.query(m.RoadSegment).filter_by(from_id=u["loc"])]
        return {l.code for l in s.query(m.Location).filter(m.Location.id.in_(ids))}
    return None

def spike_of(demand_pct, spike_post):
    return {"pct": demand_pct, "post": spike_post} if demand_pct else None

# ---------- public / auth ----------
@app.get("/health")
def health():
    with engine.connect() as c:
        c.execute(text("SELECT 1"))
        try:
            postgis = c.execute(text("SELECT PostGIS_Version()")).scalar()
        except Exception:
            postgis = None
    return {"status": "ok", "postgis": postgis, "mqtt": mqtt_bridge.connected()}

@app.post("/login")
def login(form: OAuth2PasswordRequestForm = Depends()):
    check_lock(form.username)
    def go(s):
        u = s.query(m.User).filter_by(username=form.username).first()
        if not u or not verify(form.password, u.password_hash):
            record_fail(form.username); audit(s, form.username, "Failed login")
            raise HTTPException(401, "Wrong username or password")
        clear_fail(form.username); audit(s, u.username, "Login")
        return {"access_token": make_token(u), "token_type": "bearer", "role": u.role, "expires_in_min": EXPIRE_MIN}
    return _db(go)

@app.get("/me")
def me(u=Depends(current_user)):
    return {"username": u["sub"], "role": u["role"], "location_id": u["loc"]}

# ---------- forecast / alerts ----------
@app.get("/forecast/{post}/{item}")
def get_forecast(post: str, item: str, days: int = 14, u=Depends(require("planner", "admin", "depot", "post"))):
    from ml import forecast as fc
    def go(s):
        sc = scope(s, u)
        if sc is not None and post not in sc:
            raise HTTPException(403, "You can only view your own posts")
        try:
            f, _ = fc.forecast(post, item, days)
        except Exception as e:
            raise HTTPException(404, f"Forecast failed: {e}")
        return {"post": post, "item": item, "forecast": f.to_dict("records")}
    return _db(go)

@app.get("/dos")
def dos_table(demand_pct: float | None = None, spike_post: str | None = None, u=Depends(require("planner", "admin", "depot", "post"))):
    """demand_pct / spike_post: what-if demand surge."""
    def go(s):
        sc = scope(s, u)
        return [r for r in al.dos_rows(s, spike_of(demand_pct, spike_post)) if sc is None or r["post"] in sc]
    return _db(go)

@app.post("/alerts/refresh")
def alerts_refresh(demand_pct: float | None = None, spike_post: str | None = None, u=Depends(require("planner"))):
    def go(s):
        t = al.refresh_alerts(s, write=True, spike=spike_of(demand_pct, spike_post)); al._cache.clear()
        res = {"created": sum(1 for r in t if r["level"] != "ok"), "critical": sum(1 for r in t if r["level"] == "critical")}
        audit(s, u["sub"], "Refreshed alerts")
        hub.emit("alerts", f"Alerts refreshed: {res['critical']} critical", ["planner", "admin"])
        return res
    return _db(go)

@app.get("/alerts")
def alerts_list(u=Depends(require("planner", "admin", "depot", "post"))):
    def go(s):
        sc = scope(s, u); codes = {l.id: l.code for l in s.query(m.Location)}
        rows = [a for a in s.query(m.Alert).filter_by(resolved=False) if sc is None or codes.get(a.location_id) in sc]
        rows.sort(key=lambda a: {"sos": 0, "critical": 1, "warning": 2}.get(a.level, 3))
        return [{"level": a.level, "post": codes.get(a.location_id), "message": a.message, "reason": a.reason, "action": a.action} for a in rows]
    return _db(go)

# ---------- routes / modes / planning ----------
@app.get("/routes")
def routes(snow_cm: float | None = None, u=Depends(require("planner", "transport", "admin"))):
    return _db(lambda s: pl.routes_summary(s, snow_cm))

@app.get("/routes/options/{post}")
def route_options(post: str, kg: float = 1000, urgency: str = "critical", snow_cm: float | None = None, u=Depends(require("planner", "transport", "admin"))):
    """All road routes to a post (open and closed) plus road / air / mule mode advice."""
    return _db(lambda s: pl.route_options(s, post, kg, urgency, snow_cm))

@app.post("/plan/generate")
def plan_generate(snow_cm: float | None = None, demand_pct: float | None = None, spike_post: str | None = None, u=Depends(require("planner"))):
    def go(s):
        r = pl.generate_plan(s, snow_cm, spike_of(demand_pct, spike_post)); al._cache.clear()
        audit(s, u["sub"], f"Generated plan: {len(r['convoys'])} convoys")
        hub.emit("plan", f"{len(r['convoys'])} convoy(s) proposed, awaiting approval", ["planner", "admin"])
        return r
    return _db(go)

@app.get("/convoys")
def convoys(u=Depends(require("planner", "admin", "transport", "depot", "post"))):
    def go(s):
        rows, role = pl.list_convoys(s), u["role"]
        if role == "transport":
            return [c for c in rows if c["status"] in ("approved", "loaded", "in_transit", "delivered", "held")]
        if role == "depot":
            return [c for c in rows if c["depot"] == s.get(m.Location, u["loc"]).code]
        if role == "post":
            own = s.get(m.Location, u["loc"]).code
            return [c for c in rows if c["status"] != "proposed" and any(st["post"] == own for st in c["stops"])]
        return rows
    return _db(go)

@app.post("/convoy/{code}/status")
def convoy_status(code: str, status: str, u=Depends(current_user)):
    """approved/rejected: planner only. loaded/in_transit/delivered: transport only."""
    need = "planner" if status in ("approved", "rejected") else "transport"
    if u["role"] != need:
        raise HTTPException(403, f"Only '{need}' can set status '{status}'")
    def go(s):
        r = pl.set_status(s, code, status, u["sub"])
        hub.emit("convoy", f"Convoy {code} is now {status.replace('_', ' ')}", ALL, code=code, status=status)
        return r
    return _db(go)

class OverrideIn(BaseModel):
    action: str              # hold | release
    note: str = ""

@app.post("/convoy/{code}/override")
def convoy_override(code: str, body: OverrideIn, u=Depends(require("planner"))):
    """Commander manual override: hold or release a convoy."""
    def go(s):
        r = pl.override(s, code, body.action, body.note, u["sub"])
        hub.emit("convoy", f"Commander override: {code} {body.action} ({body.note or 'no note'})", ALL)
        return r
    return _db(go)

@app.post("/whatif/pass")
def whatif_pass(pass_name: str, closed: bool = True, snow_cm: float | None = None, u=Depends(require("planner"))):
    def go(s):
        r = pl.set_pass(s, pass_name, closed, snow_cm, u["sub"])
        hub.emit("route", f"{pass_name} {'closed' if closed else 'reopened'}: {len(r['route_changes'])} route(s) changed", ["planner", "admin", "transport"])
        return r
    return _db(go)

# ---------- supply requests / SOS ----------
class RequestIn(BaseModel):
    post: str | None = None
    item: str
    qty: float
    priority: str = "normal"      # normal | high

def _post_code(s, u, body_post):
    sc = scope(s, u)
    code = s.get(m.Location, u["loc"]).code if u["role"] == "post" else body_post
    if code not in sc:
        raise HTTPException(403, "Post is not in your area")
    return code

@app.post("/requests")
def create_request(body: RequestIn, u=Depends(require("post", "depot"))):
    def go(s):
        if body.item not in ITEMS or body.qty <= 0 or body.priority not in ("normal", "high"):
            raise ValueError("Invalid item, qty or priority")
        code = _post_code(s, u, body.post)
        loc = s.query(m.Location).filter_by(code=code).first()
        r = m.SupplyRequest(post_id=loc.id, item=body.item, qty=body.qty, priority=body.priority, requested_by=u["sub"])
        s.add(r); s.commit()
        audit(s, u["sub"], f"Supply request: {body.qty:g} {body.item} for {code}")
        hub.emit("request", f"New supply request: {body.qty:g} {body.item} for {loc.name}", ["planner", "admin"])
        return {"id": r.id, "status": r.status}
    return _db(go)

class SosIn(BaseModel):
    post: str | None = None
    item: str = "Medical"
    qty: float = 100
    note: str = ""

@app.post("/sos")
def sos(body: SosIn, u=Depends(require("post", "depot"))):
    """Emergency override: skips approval, planned first with a 24 h deadline, air or mule allowed."""
    def go(s):
        if body.item not in ITEMS or body.qty <= 0:
            raise ValueError("Invalid item or qty")
        code = _post_code(s, u, body.post)
        loc = s.query(m.Location).filter_by(code=code).first()
        r = m.SupplyRequest(post_id=loc.id, item=body.item, qty=body.qty, priority="sos", status="approved", requested_by=u["sub"])
        s.add(r); s.commit()
        audit(s, u["sub"], f"SOS: {body.qty:g} {body.item} for {code} {body.note}")
        al.refresh_alerts(s, write=True); al._cache.clear()
        hub.emit("sos", f"SOS from {loc.name}: {body.qty:g} {body.item}. {body.note}", ALL)
        return {"id": r.id, "status": "approved", "note": "SOS override active. Planner can press Generate AI plan now."}
    return _db(go)

@app.get("/requests")
def list_requests(u=Depends(require("planner", "admin", "post", "depot"))):
    def go(s):
        sc = scope(s, u); codes = {l.id: l.code for l in s.query(m.Location)}
        return [{"id": r.id, "post": codes[r.post_id], "item": r.item, "qty": r.qty, "priority": r.priority,
                 "status": r.status, "by": r.requested_by}
                for r in s.query(m.SupplyRequest).order_by(m.SupplyRequest.id.desc()) if sc is None or codes[r.post_id] in sc]
    return _db(go)

@app.post("/requests/{rid}/decision")
def decide_request(rid: int, approve: bool, u=Depends(require("planner"))):
    def go(s):
        r = s.get(m.SupplyRequest, rid)
        if not r or r.status != "pending":
            raise ValueError("Request not found or already decided")
        r.status = "approved" if approve else "rejected"; s.commit()
        audit(s, u["sub"], f"Request {rid} {r.status}")
        hub.emit("request", f"Your request #{rid} was {r.status}", ["post", "depot"])
        return {"id": rid, "status": r.status}
    return _db(go)

# ---------- stock, consumption (feeds retraining) ----------
class StockIn(BaseModel):
    item: str
    delta: float
    reason: str = ""

@app.post("/inventory/update")
def inventory_update(body: StockIn, u=Depends(require("depot"))):
    def go(s):
        row = s.query(m.Inventory).filter_by(location_id=u["loc"], item=body.item).first()
        if not row:
            raise KeyError("Item not found in your depot")
        if row.stock + body.delta < 0:
            raise ValueError("Stock cannot go below zero")
        row.stock += body.delta; s.commit(); al._cache.clear()
        audit(s, u["sub"], f"Stock {body.delta:+g} {body.item} ({body.reason or 'no reason'})")
        return {"item": body.item, "stock": row.stock}
    return _db(go)

class UseIn(BaseModel):
    post: str | None = None
    item: str
    qty: float

@app.post("/consumption")
def log_consumption(body: UseIn, u=Depends(require("post", "depot"))):
    """Record today's actual consumption. It becomes training data for the next retrain."""
    def go(s):
        if body.item not in ITEMS or body.qty < 0:
            raise ValueError("Invalid item or qty")
        code = _post_code(s, u, body.post)
        loc = s.query(m.Location).filter_by(code=code).first()
        row = s.query(m.Consumption).filter_by(location_id=loc.id, item=body.item, date=date.today()).first() \
            or m.Consumption(location_id=loc.id, item=body.item, date=date.today())
        row.qty = body.qty; s.add(row); s.commit()
        audit(s, u["sub"], f"Logged consumption {body.qty:g} {body.item} at {code}")
        return {"logged": True, "note": "Used at the next model retrain"}
    return _db(go)

# ---------- dashboards data ----------
@app.get("/map")
def map_view(u=Depends(current_user)):
    return _db(pl.map_data)

@app.get("/inventory")
def inventory(u=Depends(require("planner", "admin", "depot", "post"))):
    def go(s):
        sc, rows = scope(s, u), []
        q = s.query(m.Inventory, m.Location).join(m.Location, m.Location.id == m.Inventory.location_id)
        for inv, l in q:
            ok = sc is None or (l.type == "post" and l.code in sc) or (l.type == "depot" and l.id == u["loc"])
            if ok:
                rows.append({"location": l.code, "name": l.name, "type": l.type, "item": inv.item, "stock": inv.stock, "reorder_level": inv.reorder_level})
        return rows
    return _db(go)

@app.get("/vehicles")
def vehicles(u=Depends(require("planner", "admin", "transport"))):
    def go(s):
        codes = {l.id: l.code for l in s.query(m.Location)}
        return [{"code": v.code, "type": v.type, "capacity_kg": v.capacity_kg, "status": v.status, "depot": codes[v.depot_id],
                 "fuel_pct": v.fuel_pct, "health_pct": v.health_pct} for v in s.query(m.Vehicle)]
    return _db(go)

@app.get("/weather")
def weather(u=Depends(require("planner", "admin", "transport", "depot", "post"))):
    def go(s):
        sc = scope(s, u)
        return [w for w in pl.weather_rows(s) if sc is None or w["post"] in sc]
    return _db(go)

@app.post("/weather/sync")
def weather_sync(u=Depends(require("planner", "admin"))):
    """Pull today's live weather (Open-Meteo in the prototype; IMD feed plugs in the same place)."""
    def go(s):
        r = weather_live.sync(s)
        if r["updated"] == 0:
            raise HTTPException(502, "Weather service not reachable: " + "; ".join(r["failed"][:1]))
        audit(s, u["sub"], f"Weather sync: {r['updated']} posts")
        hub.emit("weather", f"Live weather updated for {r['updated']} posts", ["planner", "admin", "transport"])
        return r
    return _db(go)

@app.get("/edge-nodes")
def edge_nodes(u=Depends(require("planner", "admin", "depot", "post"))):
    return _db(lambda s: pl.edge_nodes(s, scope(s, u), u["loc"]))

@app.post("/edge-nodes/{code}/link")
def edge_link(code: str, online: bool, u=Depends(require("planner", "admin"))):
    """Demo control: take a node's link down (it keeps working offline) or bring it back (it syncs)."""
    def go(s):
        n = s.query(m.EdgeNode).filter_by(code=code).first()
        if not n:
            raise KeyError("Edge node not found")
        sent = mqtt_bridge.publish(f"astra/control/{code.replace('EN-', '')}", {"online": online})
        if not online:
            n.online = False
        elif not sent:
            n.online = True; n.buffered = 0
        s.commit(); audit(s, u["sub"], f"Edge node {code} link {'up' if online else 'down'}")
        hub.emit("edge", f"{code} link {'restored' if online else 'cut (offline mode)'}", ["planner", "admin", "depot", "post"])
        return {"code": code, "online": n.online, "via_mqtt": sent}
    return _db(go)

@app.get("/kpis")
def kpis(u=Depends(require("planner", "admin"))):
    return _db(pl.kpis)

@app.get("/ml/status")
def ml_status(u=Depends(require("planner", "admin"))):
    return mlops.status()

@app.post("/ml/retrain")
def ml_retrain(u=Depends(require("planner", "admin"))):
    def go(s):
        r = mlops.retrain(); audit(s, u["sub"], "Started model retrain")
        return r
    return _db(go)

# ---------- admin ----------
@app.get("/audit")
def audit_log(limit: int = 50, u=Depends(require("admin"))):
    return _db(lambda s: [{"time": str(a.created_at)[:19], "user": a.username, "action": a.action}
                          for a in s.query(m.AuditLog).order_by(m.AuditLog.id.desc()).limit(min(limit, 500))])

@app.get("/users")
def users(u=Depends(require("admin"))):
    return _db(lambda s: [{"username": x.username, "role": x.role, "location_id": x.location_id} for x in s.query(m.User)])

class UserIn(BaseModel):
    username: str
    password: str
    role: str
    location_code: str | None = None

@app.post("/users")
def create_user(body: UserIn, u=Depends(require("admin"))):
    def go(s):
        if body.role not in ROLES or len(body.password) < 8:
            raise ValueError("Invalid role or password shorter than 8 characters")
        if s.query(m.User).filter_by(username=body.username).first():
            raise ValueError("Username already exists")
        loc = s.query(m.Location).filter_by(code=body.location_code).first() if body.location_code else None
        s.add(m.User(username=body.username, password_hash=hash_pw(body.password), role=body.role, location_id=loc.id if loc else None))
        s.commit(); audit(s, u["sub"], f"Created user {body.username} ({body.role})")
        return {"created": body.username}
    return _db(go)

# ---------- live updates ----------
@app.websocket("/ws")
async def live(websocket: WebSocket, token: str):
    try:
        user = decode(token)
    except Exception:
        await websocket.close(code=4401); return
    await hub.connect(websocket, user)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        hub.drop(websocket)
