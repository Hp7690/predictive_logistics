"""MQTT bridge: edge nodes (LoRa / satellite / radio gateways) publish stock readings, the API stores them.
Topics:  astra/stock/<LOC>   astra/heartbeat/<LOC>   (control: astra/control/<LOC> goes the other way)"""
import json, os, threading
from datetime import datetime, timezone
from .db import SessionLocal
from . import models as m
from .ws import hub, ALL

_client, _connected = None, False

def process(s, topic, payload):
    """Handle one message. Returns an event dict (or None). Testable without a broker."""
    parts = topic.split("/")
    if len(parts) != 3 or parts[0] != "astra":
        return None
    kind, code = parts[1], parts[2]
    loc = s.query(m.Location).filter_by(code=code).first()
    node = s.query(m.EdgeNode).filter_by(location_id=loc.id).first() if loc else None
    if not node:
        return None
    was_online, event = bool(node.online), None
    node.last_seen = datetime.now(timezone.utc)
    if "battery" in payload:
        node.battery = float(payload["battery"])
    if kind == "stock":
        row = s.query(m.Inventory).filter_by(location_id=loc.id, item=payload["item"]).first()
        if row:
            row.stock = round(float(payload["stock"]), 1)
        node.online = True
        if payload.get("batch") and payload.get("last"):
            event = {"type": "edge", "message": f"{node.code} ({loc.name}) back online: {payload.get('n', 0)} buffered readings synced"}
            node.buffered = 0
        elif not was_online and not payload.get("batch"):
            event = {"type": "edge", "message": f"{node.code} ({loc.name}) is back online"}
    elif kind == "heartbeat":
        node.online = bool(payload.get("online", True)); node.buffered = int(payload.get("buffered", 0))
        if was_online and not node.online:
            event = {"type": "edge", "message": f"{node.code} ({loc.name}) went offline: working from local cache"}
    s.commit()
    return event

def _on_message(client, userdata, msg):
    s = SessionLocal()
    try:
        ev = process(s, msg.topic, json.loads(msg.payload))
        if ev:
            hub.emit(ev["type"], ev["message"], ["planner", "admin", "depot", "post"])
    except Exception as e:
        print("MQTT message error:", e)
    finally:
        s.close()

def start():
    global _client
    if os.getenv("MQTT_ENABLED", "1") == "0":
        return
    try:
        import paho.mqtt.client as mqtt
        _client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
        def on_connect(c, u, f, rc, props=None):
            global _connected
            _connected = True; c.subscribe([("astra/stock/#", 0), ("astra/heartbeat/#", 0)])
        def on_disconnect(c, u, f, rc, props=None):
            global _connected
            _connected = False
        _client.on_connect, _client.on_disconnect, _client.on_message = on_connect, on_disconnect, _on_message
        _client.connect_async(os.getenv("MQTT_HOST", "localhost"), int(os.getenv("MQTT_PORT", "1883")))
        _client.loop_start()
    except Exception as e:
        print("MQTT disabled:", e)

def stop():
    if _client:
        _client.loop_stop()

def connected():
    return _connected

def publish(topic, payload):
    if _client and _connected:
        _client.publish(topic, json.dumps(payload)); return True
    return False
