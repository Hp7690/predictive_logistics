import { createContext, useContext, useState, useEffect, useCallback } from 'react';

export const AuthCtx = createContext(null);
export const useAuth = () => useContext(AuthCtx);

// Loads data now, and again whenever a live (WebSocket) event arrives.
export function useLoad(fn, deps = []) {
  const { tick } = useAuth();
  const [data, setData] = useState(null);
  const [err, setErr] = useState('');
  const load = useCallback(() => fn().then((d) => { setData(d); setErr(''); }).catch((e) => setErr(e.message)), deps);
  useEffect(() => { load(); }, [load, tick]);
  return { data, err, reload: load };
}

// Runs an action, shows success/error text, then refreshes the given loaders.
export function useAct(reloadAll) {
  const [msg, setMsg] = useState(null);
  const act = async (fn, ok = 'Done') => {
    try {
      const r = await fn();
      setMsg({ ok: true, text: typeof ok === 'function' ? ok(r) : ok });
      if (reloadAll) reloadAll();
      return r;
    } catch (e) { setMsg({ ok: false, text: e.message }); }
  };
  return [msg, act];
}
