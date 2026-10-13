const BASE = '/api';
export const getAuth = () => { try { return JSON.parse(localStorage.getItem('auth')); } catch { return null; } };
export const setAuth = (a) => (a ? localStorage.setItem('auth', JSON.stringify(a)) : localStorage.removeItem('auth'));

export async function api(path, { method = 'GET', body, form } = {}) {
  const a = getAuth();
  const headers = {};
  if (a) headers.Authorization = 'Bearer ' + a.token;
  let payload;
  if (form) payload = new URLSearchParams(form);
  else if (body) { headers['Content-Type'] = 'application/json'; payload = JSON.stringify(body); }
  const res = await fetch(BASE + path, { method, headers, body: payload });
  if (res.status === 401 && a) { setAuth(null); window.location.href = '/login'; throw new Error('Session expired, please log in again'); }
  const data = await res.json().catch(() => null);
  if (!res.ok) {
    const d = data && data.detail;
    throw new Error(typeof d === 'string' ? d : Array.isArray(d) ? d.map((x) => x.msg).join(', ') : 'Request failed');
  }
  return data;
}
