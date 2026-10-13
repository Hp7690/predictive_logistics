from datetime import datetime, timezone
from sqlalchemy import Column, Integer, String, Float, Date, DateTime, ForeignKey, Boolean, Text, Index
from .db import Base

def now():
    return datetime.now(timezone.utc)

class Location(Base):          # depots and forward posts
    __tablename__ = "locations"
    id = Column(Integer, primary_key=True)
    code = Column(String(10), unique=True, nullable=False)
    name = Column(String(60), nullable=False)
    type = Column(String(10), nullable=False)       # depot | post
    lat = Column(Float); lon = Column(Float)
    altitude_m = Column(Integer)
    troop_strength = Column(Integer, default=0)
    mule_ok = Column(Boolean, default=False)

class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True)
    username = Column(String(40), unique=True, nullable=False)
    password_hash = Column(String(120), nullable=False)
    role = Column(String(20), nullable=False)       # admin | planner | transport | depot | post
    location_id = Column(Integer, ForeignKey("locations.id"), nullable=True)

class Inventory(Base):
    __tablename__ = "inventory"
    id = Column(Integer, primary_key=True)
    location_id = Column(Integer, ForeignKey("locations.id"), nullable=False)
    item = Column(String(20), nullable=False)
    stock = Column(Float, nullable=False)
    reorder_level = Column(Float, nullable=False)
    updated_at = Column(DateTime(timezone=True), default=now)

class Consumption(Base):
    __tablename__ = "consumption"
    id = Column(Integer, primary_key=True)
    location_id = Column(Integer, ForeignKey("locations.id"), nullable=False)
    item = Column(String(20), nullable=False)
    date = Column(Date, nullable=False)
    qty = Column(Float, nullable=False)
    __table_args__ = (Index("ix_cons_loc_item_date", "location_id", "item", "date"),)

class Weather(Base):
    __tablename__ = "weather"
    id = Column(Integer, primary_key=True)
    location_id = Column(Integer, ForeignKey("locations.id"), nullable=False)
    date = Column(Date, nullable=False)
    snowfall_cm = Column(Float); temp_c = Column(Float); visibility_km = Column(Float)
    __table_args__ = (Index("ix_weather_loc_date", "location_id", "date"),)

class Vehicle(Base):
    __tablename__ = "vehicles"
    id = Column(Integer, primary_key=True)
    code = Column(String(12), unique=True)
    type = Column(String(20))
    capacity_kg = Column(Integer)
    status = Column(String(15), default="available")  # available | assigned | maintenance
    depot_id = Column(Integer, ForeignKey("locations.id"))
    fuel_pct = Column(Float); health_pct = Column(Float)

class RoadSegment(Base):
    __tablename__ = "road_segments"
    id = Column(Integer, primary_key=True)
    from_id = Column(Integer, ForeignKey("locations.id"))
    to_id = Column(Integer, ForeignKey("locations.id"))
    via = Column(String(80))
    distance_km = Column(Float); altitude_m = Column(Integer)
    slope = Column(Float); visibility_factor = Column(Float)   # 0..1
    pass_name = Column(String(20), nullable=True)
    status = Column(String(10), default="open")                # open | closed
    risk_score = Column(Float, default=0)
    waypoints = Column(Text, default="[]")      # JSON [[lat, lon], ...]

class SupplyRequest(Base):
    __tablename__ = "requests"
    id = Column(Integer, primary_key=True)
    post_id = Column(Integer, ForeignKey("locations.id"))
    item = Column(String(20)); qty = Column(Float)
    priority = Column(String(10), default="normal")
    status = Column(String(15), default="pending")
    requested_by = Column(String(40))
    created_at = Column(DateTime(timezone=True), default=now)

class Convoy(Base):
    __tablename__ = "convoys"
    id = Column(Integer, primary_key=True)
    code = Column(String(12), unique=True)
    post_id = Column(Integer, ForeignKey("locations.id"))
    depot_id = Column(Integer, ForeignKey("locations.id"))
    route_id = Column(Integer, ForeignKey("road_segments.id"))
    load_json = Column(Text)
    status = Column(String(15), default="proposed")
    eta_hours = Column(Float)
    mode = Column(String(10), default="road")   # road | air | mule
    note = Column(Text, default="")
    created_at = Column(DateTime(timezone=True), default=now)

class Alert(Base):
    __tablename__ = "alerts"
    id = Column(Integer, primary_key=True)
    level = Column(String(10))
    message = Column(Text); reason = Column(Text); action = Column(Text)
    location_id = Column(Integer, ForeignKey("locations.id"), nullable=True)
    resolved = Column(Boolean, default=False)
    created_at = Column(DateTime(timezone=True), default=now)

class AuditLog(Base):
    __tablename__ = "audit_log"
    id = Column(Integer, primary_key=True)
    username = Column(String(40)); action = Column(Text)
    created_at = Column(DateTime(timezone=True), default=now)


class EdgeNode(Base):          # offline-first edge node at a depot / post (LoRa, satellite or radio link)
    __tablename__ = "edge_nodes"
    id = Column(Integer, primary_key=True)
    code = Column(String(12), unique=True)
    location_id = Column(Integer, ForeignKey("locations.id"))
    link = Column(String(12))                   # LoRa | Satellite | Radio
    online = Column(Boolean, default=True)
    last_seen = Column(DateTime(timezone=True), default=now)
    buffered = Column(Integer, default=0)       # readings stored on the node while offline
    battery = Column(Float, default=100)
    rfid_tags = Column(Integer, default=0)
