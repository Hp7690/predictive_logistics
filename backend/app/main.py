import asyncio, csv, hmac, io, os
from contextlib import asynccontextmanager
from datetime import date
from fastapi import FastAPI, HTTPException, Depends, WebSocket, WebSocketDisconnect, Header
from fastapi.responses import PlainTextResponse
from fastapi.security import OAuth2PasswordRequestForm
from pydantic import BaseModel
from sqlalchemy import text
from .db import engine, SessionLocal
from . import models as m
from . import mqtt_bridge
from .auth import (require, current_user, make_token, verify, hash_pw, decode, check_lock, record_fail, clear_fail, ROLES, EXPIRE_MIN)
from .services import alerts as al, planner as pl, mlops, weather_live, nlp
from ml.india import ITEM_CATALOG
from .ws import hub, ALL

ITEMS = list(ITEM_CATALOG)

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

@app.post("/convoy/{code}/position")
def convoy_position(code: str, progress: float, gps_ok: bool = True, u=Depends(require("transport"))):
    """Transport reports position along the route. gps_ok=false keeps the last known position (LoRa fallback)."""
    def go(s):
        r = pl.set_position(s, code, progress, gps_ok, u["sub"])
        if not gps_ok:
            hub.emit("convoy", f"{code}: GPS lost, showing last known position", ["planner", "admin", "transport"])
        return r
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
        mqtt_bridge.publish(f"astra/adjust/{s.get(m.Location, u['loc']).code}", {"item": body.item, "stock": row.stock})
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
                 "fuel_pct": v.fuel_pct, "health_pct": v.health_pct,
                 "maintenance_risk": "high" if v.health_pct < 70 else "medium" if v.health_pct < 80 else "low"} for v in s.query(m.Vehicle)]
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


# ---------- v10 features: assistant, balancing, winter stocking, priority, catalog ----------
class AskIn(BaseModel):
    q: str

@app.post("/ask")
def ask(body: AskIn, u=Depends(current_user)):
    """Offline plain-language assistant (English / Hinglish). Scoped to what the user may see."""
    def go(s):
        r = nlp.answer(s, body.q, scope(s, u), u["role"])
        audit(s, u["sub"], f"Asked: {body.q[:80]}")
        return r
    return _db(go)

@app.get("/balancing")
def balancing(u=Depends(require("planner", "admin"))):
    """Surplus-to-shortfall transfers and non-moving stock."""
    return _db(pl.balancing)

@app.get("/priority")
def priority(u=Depends(require("planner", "admin"))):
    return _db(pl.priority_ranking)

@app.get("/winter")
def winter(closure_days: int = 45, winter_days: int = 120, early_days: int = 0, u=Depends(require("planner", "admin"))):
    """Advance winter stocking: need vs stock per post and what can move before the passes close."""
    if not (1 <= winter_days <= 240 and 0 <= early_days <= closure_days and closure_days <= 180):
        raise HTTPException(400, "Check the values: closure_days up to 180, early_days not above closure_days, winter_days 1 to 240")
    return _db(lambda s: pl.winter_plan(s, closure_days, winter_days, early_days))

@app.get("/catalog")
def catalog(u=Depends(current_user)):
    return [{"item": k, **v} for k, v in ITEM_CATALOG.items()]

# ---------- integration API for Q-FORCE / Army ERP (API key, plain REST) ----------
def api_key(x_api_key: str | None = Header(None)):
    key = os.getenv("INTEGRATION_API_KEY", "")
    if not key:
        raise HTTPException(503, "Integration API is off. Set INTEGRATION_API_KEY in .env and restart.")
    if not hmac.compare_digest(x_api_key or "", key):
        raise HTTPException(401, "Invalid API key")

INTEGRATION_ENDPOINTS = ["GET /integration/v1/ping", "GET /integration/v1/forecast?post=&item=&days=", "GET /integration/v1/dos", "GET /integration/v1/convoys",
                         "GET /integration/v1/stock", "GET /integration/v1/stock.csv", "POST /integration/v1/stock  {records:[{location,item,stock}]}"]

@app.get("/integration/status")
def integration_status(u=Depends(require("admin"))):
    return {"enabled": bool(os.getenv("INTEGRATION_API_KEY")), "header": "X-API-Key", "endpoints": INTEGRATION_ENDPOINTS}

@app.get("/integration/v1/ping")
def i_ping(_=Depends(api_key)):
    return {"system": "ASTRA-LOG", "ok": True}

@app.get("/integration/v1/forecast")
def i_forecast(post: str, item: str, days: int = 14, _=Depends(api_key)):
    from ml import forecast as fc
    try:
        f, _m = fc.forecast(post, item, days)
    except Exception as e:
        raise HTTPException(404, f"Forecast failed: {e}")
    return {"post": post, "item": item, "method": f.attrs.get("method"), "forecast": f.to_dict("records")}

@app.get("/integration/v1/dos")
def i_dos(_=Depends(api_key)):
    return _db(lambda s: al.dos_rows(s))

@app.get("/integration/v1/convoys")
def i_convoys(_=Depends(api_key)):
    return _db(pl.list_convoys)

def _stock_rows(s):
    return [{"location": l.code, "name": l.name, "item": i.item, "gtin": ITEM_CATALOG[i.item]["gtin"], "stock": i.stock, "reorder_level": i.reorder_level}
            for i, l in s.query(m.Inventory, m.Location).join(m.Location, m.Location.id == m.Inventory.location_id)]

@app.get("/integration/v1/stock")
def i_stock(_=Depends(api_key)):
    return _db(_stock_rows)

@app.get("/integration/v1/stock.csv", response_class=PlainTextResponse)
def i_stock_csv(_=Depends(api_key)):
    rows = _db(_stock_rows); out = io.StringIO()
    w = csv.DictWriter(out, fieldnames=["location", "name", "item", "gtin", "stock", "reorder_level"]); w.writeheader(); w.writerows(rows)
    return out.getvalue()

class StockRec(BaseModel):
    location: str
    item: str
    stock: float

class StockPush(BaseModel):
    records: list[StockRec]

@app.post("/integration/v1/stock")
def i_stock_push(body: StockPush, _=Depends(api_key)):
    """ERP / Q-FORCE pushes current stock. Bad records are skipped and reported, never half-applied silently."""
    def go(s):
        done, skipped = 0, []
        for r in body.records:
            loc = s.query(m.Location).filter_by(code=r.location).first()
            row = s.query(m.Inventory).filter_by(location_id=loc.id, item=r.item).first() if loc else None
            if row is None or r.stock < 0:
                skipped.append(f"{r.location}/{r.item}"); continue
            row.stock = r.stock; done += 1
            mqtt_bridge.publish(f"astra/adjust/{r.location}", {"item": r.item, "stock": r.stock})
        s.commit(); al._cache.clear(); audit(s, "integration:erp", f"Stock push: {done} updated, {len(skipped)} skipped")
        hub.emit("integration", f"ERP stock import: {done} record(s) updated", ["planner", "admin"])
        return {"updated": done, "skipped": skipped}
    return _db(go)
