function formatAmount(yuan) {
  if (yuan == null || isNaN(yuan)) return { value: 0, unit: '元', text: '—' };
  const abs = Math.abs(yuan);
  if (abs >= 1e8) return { value: yuan / 1e8, unit: '亿', text: `${(yuan / 1e8).toFixed(2)} 亿` };
  if (abs >= 1e7) return { value: yuan / 1e7, unit: '千万', text: `${(yuan / 1e7).toFixed(2)} 千万` };
  if (abs >= 1e4) return { value: yuan / 1e4, unit: '万', text: `${(yuan / 1e4).toFixed(2)} 万` };
  return { value: yuan, unit: '元', text: `${yuan.toFixed(0)} 元` };
}

function formatPct(v) {
  if (v == null || isNaN(v)) return '—';
  return `${(v * 100).toFixed(2)}%`;
}

function formatSectorName(name) {
  if (!name) return '';
  return String(name)
    .replace(/^A股-申万行业-/, '')
    .replace(/^A股-申万二级-/, '');
}

function shortDate(iso) {
  if (!iso) return '';
  const p = iso.split('-');
  return p.length >= 3 ? `${p[1]}-${p[2]}` : iso;
}
