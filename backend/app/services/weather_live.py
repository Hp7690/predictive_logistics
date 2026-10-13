"""Live weather pull. Prototype uses the free Open-Meteo API; the IMD feed plugs in at fetch()."""
import json, urllib.request, urllib.parse
from datetime import date
from .. import models as m

def fetch(lat, lon):
    q = urllib.parse.urlencode({"latitude": lat, "longitude": lon, "daily": "snowfall_sum,temperature_2m_mean",
                                "hourly": "visibility", "timezone": "Asia/Kolkata", "forecast_days": 1})
    with urllib.request.urlopen("https://api.open-meteo.com/v1/forecast?" + q, timeout=8) as r:
        d = json.load(r)
    vis = [v for v in d["hourly"]["visibility"][:24] if v is not None]
    return {"snow": float(d["daily"]["snowfall_sum"][0] or 0), "temp": float(d["daily"]["temperature_2m_mean"][0] or 0),
            "vis": min(15.0, (sum(vis) / len(vis) / 1000) if vis else 15.0)}

def sync(s):
    """Fetch today's weather for every post and store it; route risk then uses it automatically."""
    n, failed = 0, []
    for l in s.query(m.Location).filter_by(type="post"):
        try:
            w = fetch(l.lat, l.lon)
        except Exception as e:
            failed.append(f"{l.code}: {e}"); continue
        row = s.query(m.Weather).filter_by(location_id=l.id, date=date.today()).first() or m.Weather(location_id=l.id, date=date.today())
        row.snowfall_cm, row.temp_c, row.visibility_km = round(w["snow"], 1), round(w["temp"], 1), round(w["vis"], 1)
        s.add(row); n += 1
    s.commit()
    return {"updated": n, "failed": failed}
