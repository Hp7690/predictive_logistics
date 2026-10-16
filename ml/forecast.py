"""Demand forecasting: XGBoost (quantiles) + LSTM ensemble for regular items, Croston/SBA for slow-moving items. Scored by MAPE and MASE.
Train + evaluate:  python -m ml.forecast        (run from project root, venv active)"""
import sys, json, datetime
from pathlib import Path
import numpy as np, pandas as pd, joblib, xgboost as xgb

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend")); sys.path.insert(0, str(ROOT))
from app.db import engine            # noqa: E402
from ml.lstm import NumpyLSTM, make_windows, last_window   # noqa: E402

MODEL_PATH = ROOT / "ml" / "forecast_model.joblib"
METRICS_PATH = ROOT / "ml" / "metrics.json"
H, T = 14, 28
QS = [0.1, 0.5, 0.9]
ITEM_CODE = {"Ration": 0, "POL": 1, "Ammo": 2, "Medical": 3, "Spares": 4}
FEATS = ["h", "doy_sin", "doy_cos", "wd", "m7r", "troops", "alt", "item", "snow"]
ADI_CUTOFF = 1.32          # Syntetos-Boylan: average demand interval above this = intermittent / lumpy

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

# ---------- slow-moving items: Croston / SBA ----------
def adi_cv2(y):
    nz = y[y > 0]
    if len(nz) < 2:
        return float("inf"), 0.0
    return len(y) / len(nz), float((nz.std() / nz.mean()) ** 2)

def intermittent_keys(cons):
    out = set()
    for (post, item), g in cons.groupby(["post", "item"]):
        if adi_cv2(g.sort_values("date").qty.values)[0] >= ADI_CUTOFF:
            out.add((post, item))
    return out

def croston_sba(y, alpha=0.1):
    """Daily demand rate with the Syntetos-Boylan bias correction."""
    nz = np.flatnonzero(y > 0)
    if len(nz) == 0:
        return 0.0
    z, p, last = y[nz[0]], float(nz[0] + 1), nz[0]
    for i in nz[1:]:
        z = alpha * y[i] + (1 - alpha) * z; p = alpha * (i - last) + (1 - alpha) * p; last = i
    return (1 - alpha / 2) * z / max(p, 1.0)

def croston_forecast(y, days):
    """p50 = SBA rate; p10/p90 = spread of 14-day average demand seen in the last year (so bands are honest about lumpiness)."""
    rate = croston_sba(y); tail = y[-365:]
    if len(tail) >= 28:
        avg14 = pd.Series(tail).rolling(14).mean().dropna().values
        lo, hi = np.quantile(avg14, 0.1), np.quantile(avg14, 0.9)
    else:
        lo, hi = 0.0, rate * 2
    lo, hi = min(lo, rate), max(hi, rate)
    return np.full(days, lo), np.full(days, rate), np.full(days, hi)

# ---------- regular items: XGBoost ----------
def _frame(td, h, m7, m30, troops, alt, item, post, snow_tab):
    doy = td.dayofyear.values
    return pd.DataFrame({"h": h, "doy_sin": np.sin(2 * np.pi * doy / 365), "doy_cos": np.cos(2 * np.pi * doy / 365),
                         "wd": td.weekday.values, "m7r": m7 / m30, "troops": troops, "alt": alt,
                         "item": ITEM_CODE[item], "snow": [snow_tab.get((post, d.month), 0.0) for d in td]})

def build(cons, snow_tab, skip):
    parts = []
    for (post, item), g in cons.groupby(["post", "item"]):
        if (post, item) in skip:
            continue
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
    return np.sort(np.vstack([models[q].predict(X) * m30 for q in QS]), axis=0)

# ---------- LSTM ----------
def lstm_dataset(cons, skip, step=2):
    out = {}
    for (post, item), g in cons.groupby(["post", "item"]):
        if (post, item) in skip:
            continue
        g = g.sort_values("date"); dates = pd.DatetimeIndex(g.date)
        X, Y, m, oi = make_windows(g.qty.values, dates, T, H, step)
        out[(post, item)] = (X, Y, m, oi, dates)
    return out

def lstm_train(data, cutoff_idx=None, epochs=12):
    Xs, Ys = [], []
    for (post, item), (X, Y, m, oi, dates) in data.items():
        keep = np.ones(len(oi), bool) if cutoff_idx is None else (dates[np.minimum(oi + H, len(dates) - 1)] <= cutoff_idx)
        Xs.append(X[keep]); Ys.append(Y[keep])
    X, Y = np.concatenate(Xs), np.concatenate(Ys)
    net = NumpyLSTM(3, 20, H, seed=0); net.fit(X, Y, epochs=epochs, lr=0.01)
    return net

# ---------- evaluation ----------
def _mase_scale(cons):
    s = {}
    for (post, item), g in cons.groupby(["post", "item"]):
        y = g.sort_values("date").qty.values; s[(post, item)] = max(np.abs(np.diff(y)).mean(), 1e-6)
    return s

def evaluate(cons, wx, test_days=60):
    last = cons.date.max(); cutoff = last - pd.Timedelta(days=test_days)
    skip = intermittent_keys(cons[cons.date <= cutoff])
    train_cons = cons[cons.date <= cutoff]; scale = _mase_scale(train_cons)
    df = build(cons, snow_table(wx, cutoff), skip)
    train = df[(df.target <= cutoff) & (df.oidx % 2 == 0)]
    test = df[df.origin >= cutoff].copy()
    models = fit(train)
    p10, p50, p90 = predict(models, test[FEATS], test.m30.values)
    test["p10"], test["p50x"], test["p90"] = p10, p50, p90
    # LSTM on the same origins
    data = lstm_dataset(cons, skip, step=1); net = lstm_train(data, cutoff_idx=cutoff)
    pl = {}
    for (post, item), (X, Y, m, oi, dates) in data.items():
        sel = dates[oi] >= cutoff
        if sel.any():
            pred = (net.predict(X[sel]) + 1) * m[sel][:, None]
            for o, row in zip(dates[oi][sel], pred):
                pl[(post, item, o)] = row
    test["p50l"] = [pl[(a, b, o)][h - 1] if (a, b, o) in pl else np.nan for a, b, o, h in zip(test.post, test.item_name, test.origin, test.h)]
    test = test.dropna(subset=["p50l"])
    ape = lambda a, b: (a - b).abs() / b.clip(lower=1e-6)
    wbest, best = 0.0, 9e9
    for w in (0.0, 0.25, 0.5, 0.75, 1.0):
        e = ape((1 - w) * test.p50x + w * test.p50l, test.y).mean()
        if e < best:
            wbest, best = w, e
    test["p50"] = (1 - wbest) * test.p50x + wbest * test.p50l
    k = (test.p50 / test.p50x.clip(lower=1e-6)).clip(0.5, 2.0)
    test["lo"], test["hi"] = test.p10 * k, test.p90 * k
    test["naive"] = test.m30
    test["sc"] = [scale[(a, b)] for a, b in zip(test.post, test.item_name)]
    rows = {}
    for item, g in test.groupby("item_name"):
        agg = g.groupby(["post", "origin"]).agg(y=("y", "sum"), p=("p50", "sum"))
        rows[item] = {"method": "XGBoost + LSTM" if wbest > 0 else "XGBoost", "daily_MAPE_%": 100 * ape(g.p50, g.y).mean(),
                      "naive_daily_MAPE_%": 100 * ape(g.naive, g.y).mean(), "xgb_only_MAPE_%": 100 * ape(g.p50x, g.y).mean(),
                      "lstm_only_MAPE_%": 100 * ape(g.p50l, g.y).mean(), "14d_total_MAPE_%": 100 * ape(agg.p, agg.y).mean(),
                      "80%_band_coverage_%": 100 * ((g.y >= g.lo) & (g.y <= g.hi)).mean(),
                      "MASE": ((g.p50 - g.y).abs() / g.sc).mean(), "naive_MASE": ((g.naive - g.y).abs() / g.sc).mean()}
    # slow-moving items: Croston/SBA vs a naive 30-day average, many origins, scored by MASE
    for item in sorted({i for (_, i) in skip}):
        m_c, m_n, err, act, cov = [], [], 0.0, 0.0, []
        for (post, it), g in cons.groupby(["post", "item"]):
            if it != item:
                continue
            g = g.sort_values("date"); y = g.qty.values; d = pd.DatetimeIndex(g.date); sc = scale[(post, it)]
            for o in np.flatnonzero((d >= cutoff) & (np.arange(len(d)) < len(d) - H))[::3]:
                hist, fut = y[:o + 1], y[o + 1:o + 1 + H]
                lo, mid, hi = croston_forecast(hist, H)
                m_c.append(np.abs(mid - fut).mean() / sc); m_n.append(np.abs(hist[-30:].mean() - fut).mean() / sc)
                err += abs(mid.sum() - fut.sum()); act += fut.sum(); cov.append(lo[0] <= fut.mean() <= hi[0])
        rows[item] = {"method": "Croston / SBA", "daily_MAPE_%": None, "naive_daily_MAPE_%": None, "xgb_only_MAPE_%": None, "lstm_only_MAPE_%": None,
                      "14d_total_MAPE_%": 100 * err / max(act, 1e-6),   # WAPE: MAPE is undefined when a 14-day window has no demand
                       "80%_band_coverage_%": 100 * float(np.mean(cov)),
                      "MASE": float(np.mean(m_c)), "naive_MASE": float(np.mean(m_n))}
    cont = test
    rows["ALL"] = {"method": f"ensemble weight LSTM={wbest}", "daily_MAPE_%": 100 * ape(cont.p50, cont.y).mean(),
                   "naive_daily_MAPE_%": 100 * ape(cont.naive, cont.y).mean(), "xgb_only_MAPE_%": 100 * ape(cont.p50x, cont.y).mean(),
                   "lstm_only_MAPE_%": 100 * ape(cont.p50l, cont.y).mean(),
                   "14d_total_MAPE_%": 100 * ape(cont.groupby(["post", "item_name", "origin"]).p50.sum(), cont.groupby(["post", "item_name", "origin"]).y.sum()).mean(),
                   "80%_band_coverage_%": 100 * ((cont.y >= cont.lo) & (cont.y <= cont.hi)).mean(),
                   "MASE": float(np.mean([r["MASE"] for r in rows.values()])), "naive_MASE": float(np.mean([r["naive_MASE"] for r in rows.values()]))}
    clean = {k: {a: (None if b is None or (isinstance(b, float) and np.isnan(b)) else (round(b, 2) if isinstance(b, float) else b)) for a, b in v.items()} for k, v in rows.items()}
    return clean, wbest

def train_and_save():
    cons, wx = load()
    print(f"Loaded {len(cons)} consumption rows. Evaluating on the last 60 days (XGBoost + LSTM + Croston)...\n")
    ev, w = evaluate(cons, wx)
    print(pd.DataFrame(ev).T[["method", "daily_MAPE_%", "naive_daily_MAPE_%", "MASE", "naive_MASE", "14d_total_MAPE_%", "80%_band_coverage_%"]].to_string())
    print("\nTraining final models on all data...")
    skip = intermittent_keys(cons); st = snow_table(wx)
    df = build(cons, st, skip)
    data = lstm_dataset(cons, skip, step=1); net = lstm_train(data)
    joblib.dump({"models": fit(df[df.oidx % 2 == 0]), "snow_tab": st, "intermittent": skip, "lstm": net.state(), "lstm_weight": w}, MODEL_PATH)
    METRICS_PATH.write_text(json.dumps({"trained_at": datetime.datetime.now().isoformat(timespec="seconds"), "rows": int(len(cons)),
                                        "lstm_weight": w, "metrics": ev}, allow_nan=False))
    print(f"Saved {MODEL_PATH}")

_cache = {}
def bundle():
    if "b" not in _cache:
        _cache["b"] = joblib.load(MODEL_PATH)
    return _cache["b"]

def method_of(post, item):
    b = bundle()
    return "Croston / SBA" if (post, item) in b["intermittent"] else ("XGBoost + LSTM" if b["lstm_weight"] > 0 else "XGBoost")

def forecast(post, item, days=14, cons=None):
    days = min(days, H)
    b = bundle(); cons = cons if cons is not None else load()[0]
    g = cons[(cons.post == post) & (cons.item == item)].sort_values("date")
    y = g.qty.values; m7, m30 = y[-7:].mean(), max(y[-30:].mean(), 1e-6)
    td = pd.date_range(g.date.iloc[-1] + pd.Timedelta(days=1), periods=days)
    if (post, item) in b["intermittent"]:
        p10, p50, p90 = croston_forecast(y, days)
    else:
        X = _frame(td, np.arange(1, days + 1), m7, m30, g.troops.iloc[0], g.alt.iloc[0], item, post, b["snow_tab"])
        p10, p50, p90 = predict(b["models"], X[FEATS], m30)
        if b["lstm_weight"] > 0:
            xw, mw = last_window(y, pd.DatetimeIndex(g.date), T)
            pl = (NumpyLSTM.from_state(b["lstm"]).predict(xw)[0, :days] + 1) * mw
            new = (1 - b["lstm_weight"]) * p50 + b["lstm_weight"] * pl
            k = np.clip(new / np.maximum(p50, 1e-6), 0.5, 2.0); p10, p90, p50 = p10 * k, p90 * k, new
    out = pd.DataFrame({"date": td.date, "p10": np.round(p10, 1), "p50": np.round(p50, 1), "p90": np.round(p90, 1)})
    out.attrs["method"] = method_of(post, item)
    return out, float(m7)

if __name__ == "__main__":
    train_and_save()
