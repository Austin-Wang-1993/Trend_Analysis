async function apiGet(path) {
  const res = await fetch(path);
  if (!res.ok) {
    const err = await res.text();
    throw new Error(err || res.statusText);
  }
  return res.json();
}

async function apiPut(path, body) {
  const headers = { 'Content-Type': 'application/json', ...adminHeaders() };
  const res = await fetch(path, { method: 'PUT', headers, body: JSON.stringify(body) });
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

async function apiPost(path, body) {
  const headers = { 'Content-Type': 'application/json', ...adminHeaders() };
  const res = await fetch(path, { method: 'POST', headers, body: JSON.stringify(body) });
  if (!res.ok) {
    const text = await res.text();
    try {
      const j = JSON.parse(text);
      throw new Error(j.detail || text);
    } catch (e) {
      if (e instanceof Error && e.message !== text) throw e;
      throw new Error(text || res.statusText);
    }
  }
  return res.json();
}

function adminHeaders() {
  const token = localStorage.getItem('adminToken') || '';
  return token ? { 'X-Admin-Token': token } : {};
}

function setAdminToken(token) {
  if (token) localStorage.setItem('adminToken', token);
  else localStorage.removeItem('adminToken');
}
