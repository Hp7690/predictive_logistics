"""Synthetic data generator. Run alone: python ml/generate_data.py  (writes CSVs to data/)"""
import numpy as np, pandas as pd
from datetime import date, timedelta
from pathlib import Path

ITEMS = {  # per-soldier daily use, winter sensitivity
    "Ration":  (0.45, 0.20),
    "POL":     (0.25, 0.55),
    "Ammo":    (0.06, 0.00),
    "Medical": (0.04, 0.15),
    "Spares":  (0.02, 0.10),     # slow-moving: lumpy / intermittent demand
}
from ml.india import DEPOTS, POSTS   # real India pilot geography

def make_data(days=730, seed=42, end=None):
    rng = np.random.default_rng(seed)
    end = end or date.today() - timedelta(days=1)
    dates = pd.date_range(end=end, periods=days)
    doy = dates.dayofyear.values
    winter = 0.5 * (1 + np.cos(2 * np.pi * (doy - 15) / 365))   # 1 in mid-Jan, 0 in mid-Jul
    w_rows, c_rows = [], []
    for code, name, lat, lon, alt, troops, _mule in POSTS:
        alt_f = alt / 4000
        snow = np.where(winter > 0.45, rng.gamma(1.2, 2.5, days) * winter * alt_f * (rng.random(days) < 0.45), 0.0)
        temp = 22 - 28 * winter - (alt - 3000) / 150 + rng.normal(0, 2.5, days)
        vis = np.clip(12 - snow * 1.4 + rng.normal(0, 1.2, days), 0.3, 15)
        w_rows.append(pd.DataFrame({"post": code, "date": dates.date, "snowfall_cm": snow.round(1),
                                    "temp_c": temp.round(1), "visibility_km": vis.round(1)}))
        ex = np.zeros(days)                                       # exercise / deployment spikes
        for s in rng.choice(days - 10, size=days // 90, replace=False):
            ex[s:s + rng.integers(5, 11)] = 1
        weekend = (dates.weekday.values >= 5) * 0.04
        for item, (per_head, wsens) in ITEMS.items():
            base = troops * per_head
            mult = 1 + wsens * winter + 0.012 * snow - weekend
            mult = mult + ex * (0.6 if item == "Ammo" else 0.2)
            qty = base * mult * (1 + rng.normal(0, 0.06, days))
            if item == "Spares":      # demand arrives in occasional lumps (about 1 day in 10)
                occ = rng.random(days) < 0.10
                qty = np.where(occ, np.round(rng.lognormal(np.log(max(base / 0.10 * 0.8, 1)), 0.45, days)), 0.0)
            c_rows.append(pd.DataFrame({"post": code, "item": item, "date": dates.date, "qty": qty.round(1)}))
    return pd.concat(c_rows, ignore_index=True), pd.concat(w_rows, ignore_index=True)

if __name__ == "__main__":
    cons, wx = make_data()
    out = Path(__file__).resolve().parent.parent / "data"
    out.mkdir(exist_ok=True)
    cons.to_csv(out / "consumption.csv", index=False); wx.to_csv(out / "weather.csv", index=False)
    print(f"consumption.csv: {len(cons)} rows | weather.csv: {len(wx)} rows -> {out}")
