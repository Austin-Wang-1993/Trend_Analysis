async function parseJsonResponse(res) {
  const text = await res.text();
  if (!text.trim()) {
    throw new Error(
      `服务器返回空响应 (HTTP ${res.status})。请执行：sudo systemctl restart trend-analysis`
    );
  }
  try {
    return JSON.parse(text);
  } catch (e) {
    throw new Error(`响应非 JSON (HTTP ${res.status}): ${text.slice(0, 200)}`);
  }
}

function apiErrorFromBody(text, statusText) {
  if (!text.trim()) return statusText || '请求失败';
  try {
    const j = JSON.parse(text);
    const d = j.detail;
    if (typeof d === 'string') return d;
    if (Array.isArray(d)) {
      return d
        .map((item) => {
          if (typeof item === 'string') return item;
          if (!item || typeof item !== 'object') return String(item);
          const loc = (item.loc || []).filter((x) => x !== 'body').join('.');
          return loc ? `${loc}: ${item.msg}` : item.msg || JSON.stringify(item);
        })
        .join('\n');
    }
    if (d && typeof d === 'object') {
      return d.msg || JSON.stringify(d);
    }
    return text;
  } catch {
    return text;
  }
}

async function apiGet(path) {
  const res = await fetch(path);
  if (!res.ok) {
    const err = await res.text();
    throw new Error(apiErrorFromBody(err, res.statusText));
  }
  return parseJsonResponse(res);
}

async function apiPut(path, body) {
  const res = await fetch(path, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
  if (!res.ok) {
    const text = await res.text();
    throw new Error(apiErrorFromBody(text, res.statusText));
  }
  return parseJsonResponse(res);
}

async function apiPost(path, body) {
  const res = await fetch(path, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
  if (!res.ok) {
    const text = await res.text();
    throw new Error(apiErrorFromBody(text, res.statusText));
  }
  return parseJsonResponse(res);
}
