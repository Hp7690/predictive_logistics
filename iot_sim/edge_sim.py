"""Edge node simulator: LoRa / satellite gateways at depots and posts publishing stock over MQTT.
Offline-first: when a node's link is down it keeps readings locally and syncs them in a batch when the link returns.

Run (venv active, from the project root):   python -m iot_sim.edge_sim
Options:  --interval 5 (seconds per tick)   --hours 1 (simulated hours per tick)   --chaos (random link outages)
Control:  the dashboard's "link" buttons send astra/control/<LOC> messages; or use --offline P3 to start one node offline."""
import argparse, json, random, sys, time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

class Node:
    def __init__(self, loc, kind, stock, daily):
        self.loc, self.kind, self.stock, self.daily = loc, kind, dict(stock), dict(daily)
        self.online, self.buf, self.battery = True, [], random.uniform(70, 100)

    def tick(self, hours):
        """Advance the node by `hours`; returns the MQTT messages (topic, payload) that actually leave the node."""
        self.battery = max(5, self.battery - 0.01)
        readings = []
        for item, v in self.stock.items():
            if self.kind == "post":
                self.stock[item] = max(0.0, v - self.daily.get(item, 0) / 24 * hours)
            readings.append({"item": item, "stock": round(self.stock[item], 1), "battery": round(self.battery, 1), "ts": time.time()})
        if not self.online:
            self.buf.extend(readings); return []
        msgs = [(f"astra/stock/{self.loc}", r) for r in readings]
        msgs.append((f"astra/heartbeat/{self.loc}", {"online": True, "buffered": 0, "battery": round(self.battery, 1)}))
        return msgs

    def set_online(self, online):
        """Link down: announce once, then buffer. Link up: flush the buffer as a batch."""
        if online == self.online:
            return []
        self.online = online
        if not online:
            return [(f"astra/heartbeat/{self.loc}", {"online": False, "buffered": 0, "battery": round(self.battery, 1)})]
        out, n = [], len(self.buf)
        for i, r in enumerate(self.buf):
            out.append((f"astra/stock/{self.loc}", {**r, "batch": True, "n": n, "last": i == n - 1}))
        self.buf = []
        out.append((f"astra/heartbeat/{self.loc}", {"online": True, "buffered": 0, "battery": round(self.battery, 1)}))
        return out

def load_nodes():
    import pandas as pd
    from app.db import engine
    from sqlalchemy import text
    inv = pd.read_sql("SELECT l.code, l.type, i.item, i.stock FROM inventory i JOIN locations l ON l.id = i.location_id", engine)
    use = pd.read_sql("SELECT l.code, c.item, c.qty FROM consumption c JOIN locations l ON l.id = c.location_id", engine)
    daily = use.groupby(["code", "item"]).qty.apply(lambda s: s.tail(30).mean()).to_dict()
    nodes = {}
    for code, g in inv.groupby("code"):
        stock = dict(zip(g["item"], g["stock"]))
        nodes[code] = Node(code, g["type"].iloc[0], stock, {i: daily.get((code, i), 0) for i in stock})
    return nodes

def main():
    import paho.mqtt.client as mqtt
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default="localhost"); ap.add_argument("--port", type=int, default=1883)
    ap.add_argument("--interval", type=float, default=5); ap.add_argument("--hours", type=float, default=1)
    ap.add_argument("--chaos", action="store_true"); ap.add_argument("--noise", action="store_true", help="inject bad readings to show edge validation"); ap.add_argument("--offline", nargs="*", default=[])
    a = ap.parse_args()
    nodes = load_nodes()
    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
    def send(msgs):
        for t, p in msgs:
            client.publish(t, json.dumps(p))
    def on_message(c, u, msg):
        code = msg.topic.split("/")[-1]
        if code in nodes:
            on = bool(json.loads(msg.payload).get("online", True))
            print(f"[control] {code} link {'UP (syncing buffer)' if on else 'DOWN (buffering locally)'}")
            send(nodes[code].set_online(on))
    def on_adjust(c, u, msg):      # a delivery or manual stock change in the system: keep the node in step
        code = msg.topic.split("/")[-1]; d = json.loads(msg.payload)
        if code in nodes and d.get("item") in nodes[code].stock:
            nodes[code].stock[d["item"]] = float(d["stock"])
    def route(c, u, msg):
        (on_adjust if "/adjust/" in msg.topic else on_message)(c, u, msg)
    client.on_connect = lambda c, u, f, rc, p=None: (c.subscribe("astra/control/#"), c.subscribe("astra/adjust/#"))
    client.on_message = route
    client.connect(a.host, a.port); client.loop_start()
    time.sleep(1)
    for code in a.offline:
        send(nodes[code].set_online(False))
    print(f"Edge simulator running: {len(nodes)} nodes, tick {a.interval}s = {a.hours} simulated hour(s). Ctrl+C to stop.")
    n = 0
    try:
        while True:
            for node in nodes.values():
                send(node.tick(a.hours))
            n += 1
            if a.noise and n % 4 == 0:
                bad = random.choice([x for x in nodes.values() if x.kind == "post" and x.online])
                item = random.choice(list(bad.stock))
                send([(f"astra/stock/{bad.loc}", {"item": item, "stock": random.choice([-50, 99999]), "battery": 50, "ts": time.time()})])
                print(f"[noise] bad {item} reading sent from {bad.loc}")
            if a.chaos and n % 12 == 0:
                node = random.choice([x for x in nodes.values() if x.kind == "post"])
                send(node.set_online(not node.online)); print(f"[chaos] {node.loc} link {'UP' if node.online else 'DOWN'}")
            time.sleep(a.interval)
    except KeyboardInterrupt:
        print("stopped")

if __name__ == "__main__":
    main()
