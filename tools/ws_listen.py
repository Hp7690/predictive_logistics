"""Live event viewer.  Usage (venv active):  python tools/ws_listen.py transport transport123
Keep it running, then approve/load convoys in Swagger as other users and watch events appear."""
import asyncio, json, sys, urllib.parse, urllib.request
import websockets

user, pw = sys.argv[1], sys.argv[2]
data = urllib.parse.urlencode({"username": user, "password": pw}).encode()
token = json.load(urllib.request.urlopen(urllib.request.Request("http://localhost:8000/login", data=data)))["access_token"]

async def main():
    async with websockets.connect(f"ws://localhost:8000/ws?token={token}") as ws:
        print(f"Connected as {user}. Waiting for live events (Ctrl+C to stop)...")
        async for msg in ws:
            e = json.loads(msg); print(f"[{e['time']}] {e['type']}: {e['message']}")

asyncio.run(main())
