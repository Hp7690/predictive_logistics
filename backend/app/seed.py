"""Run from backend folder:  python -m app.seed   (use --reset to wipe and rebuild)"""
import sys, json
from pathlib import Path
import numpy as np
from passlib.hash import bcrypt
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from ml.generate_data import make_data, ITEMS
from ml.india import DEPOTS, POSTS, ROUTES
from .db import Base, engine, SessionLocal
from . import models as m

USERS = [("admin", "admin123", "admin", None), ("planner", "planner123", "planner", None),
         ("transport", "transport123", "transport", None), ("depot", "depot123", "depot", "D1"),
         ("post", "post123", "post", "P1")]

def seed(reset=False):
    if reset:
        Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    s = SessionLocal()
    if s.query(m.Location).count():
        print("Database already seeded. Use --reset to rebuild."); return
    rng = np.random.default_rng(7)
    loc = {}
    for code, name, lat, lon, alt in DEPOTS:
        loc[code] = m.Location(code=code, name=name, type="depot", lat=lat, lon=lon, altitude_m=alt)
    for code, name, lat, lon, alt, tr, mule in POSTS:
        loc[code] = m.Location(code=code, name=name, type="post", lat=lat, lon=lon, altitude_m=alt, troop_strength=tr, mule_ok=mule)
    s.add_all(loc.values()); s.flush()
    for u, pw, role, lc in USERS:
        s.add(m.User(username=u, password_hash=bcrypt.hash(pw), role=role, location_id=loc[lc].id if lc else None))
    # vehicles: 5 per depot
    types = [("Truck 5T", 5000), ("Truck 3T", 3000), ("Tanker", 4000), ("Mule convoy", 800), ("Light vehicle", 1000)]
    n = 0
    for d in ("D1", "D2", "D3"):
        for t, cap in types:
            n += 1
            s.add(m.Vehicle(code=f"TRK-{n:02d}", type=t, capacity_kg=cap, depot_id=loc[d].id,
                            fuel_pct=float(rng.integers(55, 100)), health_pct=float(rng.integers(65, 98))))
    # road segments: real highway corridors from india.py
    for r in ROUTES:
        s.add(m.RoadSegment(from_id=loc[r["depot"]].id, to_id=loc[r["post"]].id, via=r["via"], distance_km=r["km"],
                            altitude_m=loc[r["post"]].altitude_m, slope=r["slope"], visibility_factor=r["vf"],
                            pass_name=r["pass_name"], risk_score=0.0, waypoints=json.dumps(r["wp"])))
    s.flush()
    cons, wx = make_data()
    ids = {c: loc[c].id for c in loc}
    s.bulk_insert_mappings(m.Consumption, [dict(location_id=ids[r.post], item=r.item, date=r.date, qty=r.qty) for r in cons.itertuples()])
    s.bulk_insert_mappings(m.Weather, [dict(location_id=ids[r.post], date=r.date, snowfall_cm=r.snowfall_cm, temp_c=r.temp_c, visibility_km=r.visibility_km) for r in wx.itertuples()])
    # inventory: posts hold ~8-14 days, depots hold ~60 days of total demand
    avg = cons.groupby(["post", "item"]).qty.mean()
    for code in loc:
        for item in ITEMS:
            if loc[code].type == "post":
                daily = avg[(code, item)]; stock = daily * float(rng.uniform(2.5, 14)); reorder = daily * 7
                if code == "P3":   # Post C (Leh): fuel and medical low, rations and ammo fine (matches the dashboard concept)
                    stock = daily * {"POL": 2.0, "Medical": 2.1, "Ration": 11.9, "Ammo": 9.8, "Spares": 8.0}[item]
                # visible surplus and non-moving stock (matches the CAG story: some stock sits idle while other posts run short)
                over = {("P8", "Ration"): 38, ("P8", "POL"): 32, ("P2", "Ammo"): 45, ("P5", "Medical"): 60, ("P7", "Spares"): 160, ("P1", "Spares"): 120}
                if (code, item) in over:
                    stock = daily * over[(code, item)]
            else:
                daily = cons[cons.item == item].groupby("post").qty.mean().sum() / 3; stock = daily * float(rng.uniform(40, 70)); reorder = daily * 20
            s.add(m.Inventory(location_id=ids[code], item=item, stock=round(stock), reorder_level=round(reorder)))
    links = ["LoRa", "Satellite", "Radio"]
    for i, code in enumerate(loc):
        s.add(m.EdgeNode(code="EN-" + code, location_id=ids[code], link=links[i % 3], battery=float(rng.integers(70, 100)),
                         rfid_tags=int(rng.integers(300, 1200))))
    s.add(m.AuditLog(username="system", action="Database seeded with synthetic data"))
    s.commit()
    for t in (m.Location, m.User, m.Vehicle, m.RoadSegment, m.Inventory, m.Consumption, m.Weather, m.EdgeNode):
        print(f"{t.__tablename__:15} {s.query(t).count():>7} rows")

if __name__ == "__main__":
    seed(reset="--reset" in sys.argv)
