"""WebSocket hub: pushes live events to connected users, filtered by role."""
import asyncio
from datetime import datetime

class Hub:
    def __init__(self):
        self.conns, self.loop = [], None

    async def connect(self, ws, user):
        await ws.accept(); self.conns.append((ws, user))

    def drop(self, ws):
        self.conns = [c for c in self.conns if c[0] is not ws]

    async def _send(self, event):
        roles = event.pop("roles")
        for ws, u in list(self.conns):
            if u["role"] in roles:
                try:
                    await ws.send_json(event)
                except Exception:
                    self.drop(ws)

    def emit(self, type_, message, roles, **data):
        """Safe to call from normal (sync) endpoints."""
        if self.loop:
            ev = {"type": type_, "message": message, "time": datetime.now().strftime("%H:%M:%S"), "roles": list(roles), **data}
            asyncio.run_coroutine_threadsafe(self._send(ev), self.loop)

hub = Hub()
ALL = ["admin", "planner", "transport", "depot", "post"]
