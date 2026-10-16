"""A small LSTM forecaster written in NumPy (forward + backprop through time + Adam), so no deep-learning install is needed.
Input: last T days of consumption (normalised) with season features. Output: next H days as multipliers of the window mean."""
import numpy as np

class NumpyLSTM:
    def __init__(self, d_in=3, hidden=20, horizon=14, seed=0):
        r = np.random.default_rng(seed); H = hidden; self.H, self.D, self.O = H, d_in, horizon
        s = 1 / np.sqrt(H)
        self.p = {"Wx": r.normal(0, s, (d_in, 4 * H)), "Wh": r.normal(0, s, (H, 4 * H)), "b": np.zeros(4 * H),
                  "Wo": r.normal(0, s, (H, horizon)), "bo": np.zeros(horizon)}
        self.p["b"][H:2 * H] = 1.0            # forget-gate bias
        self._m = {k: np.zeros_like(v) for k, v in self.p.items()}; self._v = {k: np.zeros_like(v) for k, v in self.p.items()}; self._t = 0

    @staticmethod
    def _sig(z):
        return 1 / (1 + np.exp(-np.clip(z, -30, 30)))

    def forward(self, X, cache=False):
        n, T, _ = X.shape; H = self.H; p = self.p
        h = np.zeros((n, H)); c = np.zeros((n, H)); steps = []
        for t in range(T):
            z = X[:, t] @ p["Wx"] + h @ p["Wh"] + p["b"]
            i, f, o, g = self._sig(z[:, :H]), self._sig(z[:, H:2 * H]), self._sig(z[:, 2 * H:3 * H]), np.tanh(z[:, 3 * H:])
            c_prev, h_prev = c, h
            c = f * c + i * g; h = o * np.tanh(c)
            if cache:
                steps.append((X[:, t], h_prev, c_prev, i, f, o, g, c))
        y = h @ p["Wo"] + p["bo"]
        return (y, steps, h) if cache else y

    def loss_grads(self, X, Y):
        y, steps, hT = self.forward(X, cache=True); n = len(X); p = self.p; H = self.H
        d = y - Y; loss = float(np.mean(d ** 2)); dy = 2 * d / d.size
        g = {k: np.zeros_like(v) for k, v in p.items()}
        g["Wo"] = hT.T @ dy; g["bo"] = dy.sum(0)
        dh = dy @ p["Wo"].T; dc = np.zeros((n, H))
        for x, h_prev, c_prev, i, f, o, gg, c in reversed(steps):
            tc = np.tanh(c)
            do = dh * tc; dc = dc + dh * o * (1 - tc ** 2)
            di, dg, df = dc * gg, dc * i, dc * c_prev
            dz = np.concatenate([di * i * (1 - i), df * f * (1 - f), do * o * (1 - o), dg * (1 - gg ** 2)], axis=1)
            g["Wx"] += x.T @ dz; g["Wh"] += h_prev.T @ dz; g["b"] += dz.sum(0)
            dh = dz @ p["Wh"].T; dc = dc * f
        return loss, g

    def _adam(self, g, lr):
        norm = np.sqrt(sum(float((v ** 2).sum()) for v in g.values()))
        if norm > 5:
            g = {k: v * 5 / norm for k, v in g.items()}
        self._t += 1
        for k in self.p:
            self._m[k] = 0.9 * self._m[k] + 0.1 * g[k]; self._v[k] = 0.999 * self._v[k] + 0.001 * g[k] ** 2
            mh, vh = self._m[k] / (1 - 0.9 ** self._t), self._v[k] / (1 - 0.999 ** self._t)
            self.p[k] -= lr * mh / (np.sqrt(vh) + 1e-8)

    def fit(self, X, Y, epochs=12, lr=0.01, batch=64, seed=0):
        r = np.random.default_rng(seed); hist = []
        for _ in range(epochs):
            idx = r.permutation(len(X)); tot = 0
            for s in range(0, len(X), batch):
                b = idx[s:s + batch]; loss, g = self.loss_grads(X[b], Y[b]); self._adam(g, lr); tot += loss * len(b)
            hist.append(tot / len(X))
        return hist

    def predict(self, X):
        return self.forward(X)

    def state(self):
        return {"H": self.H, "D": self.D, "O": self.O, "p": {k: v.copy() for k, v in self.p.items()}}

    @classmethod
    def from_state(cls, s):
        m = cls(s["D"], s["H"], s["O"]); m.p = {k: v.copy() for k, v in s["p"].items()}; return m

def make_windows(y, dates, T=28, H=14, step=1):
    """y: 1-D daily series, dates: DatetimeIndex. Returns X (n,T,3), Y (n,H) (or None if no future), mean, origin indices."""
    doy = dates.dayofyear.values; ang = 2 * np.pi * doy / 365
    feats = np.stack([np.zeros(len(y)), np.sin(ang), np.cos(ang)], axis=1)
    Xs, Ys, ms, oi = [], [], [], []
    for i in range(T - 1, len(y) - H, step):
        w = y[i - T + 1:i + 1]; m = max(w.mean(), 1e-6)
        x = feats[i - T + 1:i + 1].copy(); x[:, 0] = w / m - 1
        Xs.append(x); Ys.append(y[i + 1:i + 1 + H] / m - 1); ms.append(m); oi.append(i)
    return np.array(Xs), np.array(Ys), np.array(ms), np.array(oi)

def last_window(y, dates, T=28):
    w = y[-T:]; m = max(w.mean(), 1e-6)
    doy = dates.dayofyear.values[-T:]; ang = 2 * np.pi * doy / 365
    x = np.stack([w / m - 1, np.sin(ang), np.cos(ang)], axis=1)
    return x[None], m

if __name__ == "__main__":     # gradient check
    r = np.random.default_rng(1); net = NumpyLSTM(3, 5, 4, seed=2)
    X = r.normal(size=(6, 7, 3)); Y = r.normal(size=(6, 4))
    _, g = net.loss_grads(X, Y); worst = 0
    for k, v in net.p.items():
        for _ in range(6):
            ix = tuple(r.integers(0, s) for s in v.shape); old = v[ix]; e = 1e-6
            v[ix] = old + e; lp, _ = net.loss_grads(X, Y); v[ix] = old - e; lm, _ = net.loss_grads(X, Y); v[ix] = old
            num = (lp - lm) / (2 * e); worst = max(worst, abs(num - g[k][ix]) / (abs(num) + abs(g[k][ix]) + 1e-9))
    print("max relative gradient error:", worst)
