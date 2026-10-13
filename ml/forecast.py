"""Demand forecasting (XGBoost quantile models).
Train + evaluate:  python -m ml.forecast        (run from project root, venv active)
"""
import sys
from pathlib import Path
import numpy as np, pandas as pd, joblib, xgboost as xgb

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))
from app.db import engine   # noqa: E402

MODEL_PATH = ROOT / "ml" / "forecast_model.joblib"
METRICS_PATH = ROOT / "ml" / "metrics.json"
H = 14
QS = [0.1, 0.5, 0.9]
ITEM_CODE = {"Ration": 0, "POL": 1, "Ammo": 2, "Medical": 3}
FEATS = ["h", "doy_sin", "doy_cos", "wd", "m7r", "troops", "alt", "item", "snow"]

def load():
    cons = pd.read_sql("SELECT c.date, c.item, c.qty, l.code AS post, l.troop_strength AS troops, l.altitude_m AS alt "
                       "FROM consumption c JOIN locations l ON l.id = c.location_id", engine, parse_dates=["date"])
    wx = pd.read_sql("SELECT w.date, w.snowfall_cm, l.code AS post FROM weather w JOIN locations l ON l.id = w.location_id",
                     engine, parse_dates=["date"])
    return cons, wx

def snow_table(wx, upto=None):
    if upto is not None:
        wx = wx[wx.date <= upto]
    return wx.groupby(["post", wx.date.dt.month]).snowfall_cm.mean().to_dict()

def _frame(td, h, m7, m30, troops, alt, item, post, snow_tab):
    doy = td.dayofyear.values
    return pd.DataFrame({"h": h, "doy_sin": np.sin(2 * np.pi * doy / 365), "doy_cos": np.cos(2 * np.pi * doy / 365),
                         "wd": td.weekday.values, "m7r": m7 / m30, "troops": troops, "alt": alt,
                         "item": ITEM_CODE[item], "snow": [snow_tab.get((post, d.month), 0.0) for d in td]})

def build(cons, snow_tab):
    parts = []
    for (post, item), g in cons.groupby(["post", "item"]):
        g = g.sort_values("date"); y = g.qty.values; dates = pd.DatetimeIndex(g.date); n = len(y)
        m7 = pd.Series(y).rolling(7).mean().values; m30 = pd.Series(y).rolling(30).mean().values
        for h in range(1, H + 1):
            idx = np.arange(29, n - h)
            td = dates[idx + h]
            f = _frame(td, h, m7[idx], m30[idx], g.troops.iloc[0], g.alt.iloc[0], item, post, snow_tab)
            f["y"] = y[idx + h]; f["m30"] = m30[idx]; f["post"] = post; f["item_name"] = item
            f["origin"] = dates[idx]; f["target"] = td; f["oidx"] = idx
            parts.append(f)
    return pd.concat(parts, ignore_index=True)

def fit(df):
    X, t = df[FEATS], df.y / df.m30
    models = {}
    for q in QS:
        m = xgb.XGBRegressor(objective="reg:quantileerror", quantile_alpha=q, n_estimators=250, max_depth=5,
                             learning_rate=0.06, subsample=0.8, colsample_bytree=0.9, n_jobs=-1)
        models[q] = m.fit(X, t)
    return models

def predict(models, X, m30):
    p = np.vstack([models[q].predict(X) * m30 for q in QS])
    return np.sort(p, axis=0)

def evaluate(cons, wx, test_days=60):
    last = cons.date.max(); cutoff = last - pd.Timedelta(days=test_days)
    df = build(cons, snow_table(wx, cutoff))
    train = df[(df.target <= cutoff) & (df.oidx % 2 == 0)]
    test = df[df.origin >= cutoff].copy()
    models = fit(train)
    p10, p50, p90 = predict(models, test[FEATS], test.m30.values)
    test["p10"], test["p50"], test["p90"] = p10, p50, p90
    test["naive"] = test.m30
    ape = lambda a, b: (a - b).abs() / b
    rows = []
    for item, g in test.groupby("item_name"):
        agg = g.groupby(["post", "origin"]).agg(y=("y", "sum"), p=("p50", "sum"), nv=("naive", "sum"))
        rows.append({"item": item,
                     "daily_MAPE_%": 100 * ape(g.p50, g.y).mean(), "naive_daily_MAPE_%": 100 * ape(g.naive, g.y).mean(),
                     "14d_total_MAPE_%": 100 * ape(agg.p, agg.y).mean(),
                     "80%_band_coverage_%": 100 * ((g.y >= g.p10) & (g.y <= g.p90)).mean()})
    res = pd.DataFrame(rows).set_index("item")
    res.loc["ALL"] = [100 * ape(test.p50, test.y).mean(), 100 * ape(test.naive, test.y).mean(),
                      100 * ape(test.groupby(["post", "item_name", "origin"]).p50.sum(), test.groupby(["post", "item_name", "origin"]).y.sum()).mean(),
                      100 * ((test.y >= test.p10) & (test.y <= test.p90)).mean()]
    return res.round(1)

def train_and_save():
    cons, wx = load()
    print(f"Loaded {len(cons)} consumption rows. Evaluating on the last 60 days...\n")
    ev = evaluate(cons, wx)
    print(ev.to_string())
    print("\nTraining final model on all data...")
    st = snow_table(wx)
    df = build(cons, st)
    joblib.dump({"models": fit(df[df.oidx % 2 == 0]), "snow_tab": st}, MODEL_PATH)
    import json, datetime
    METRICS_PATH.write_text(json.dumps({"trained_at": datetime.datetime.now().isoformat(timespec="seconds"), "rows": int(len(cons)),
                                        "metrics": ev.to_dict(orient="index")}))
    print(f"Saved {MODEL_PATH}")

_cache = {}
def bundle():
    if "b" not in _cache:
        _cache["b"] = joblib.load(MODEL_PATH)
    return _cache["b"]

def forecast(post, item, days=14, cons=None):
    days = min(days, H)
    b = bundle(); cons = cons if cons is not None else load()[0]
    g = cons[(cons.post == post) & (cons.item == item)].sort_values("date")
    y = g.qty.values; m7, m30 = y[-7:].mean(), y[-30:].mean()
    td = pd.date_range(g.date.iloc[-1] + pd.Timedelta(days=1), periods=days)
    X = _frame(td, np.arange(1, days + 1), m7, m30, g.troops.iloc[0], g.alt.iloc[0], item, post, b["snow_tab"])
    p10, p50, p90 = predict(b["models"], X[FEATS], m30)
    return pd.DataFrame({"date": td.date, "p10": p10.round(1), "p50": p50.round(1), "p90": p90.round(1)}), float(m7)

if __name__ == "__main__":
    train_and_save()
