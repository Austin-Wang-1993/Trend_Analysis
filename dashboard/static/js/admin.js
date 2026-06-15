initNav();

document.getElementById('adminToken').value = localStorage.getItem('adminToken') || '';
document.getElementById('saveToken').onclick = () => {
  setAdminToken(document.getElementById('adminToken').value.trim());
  alert('已保存');
  loadSettings();
};

async function loadSettings() {
  const s = await apiGet('/api/admin/settings');
  document.getElementById('schedule_enabled').checked = s.schedule_enabled === 'true' || s.schedule_enabled === true;
  const t = (s.schedule_time || '21:35').split(':');
  document.getElementById('schedule_time').value = `${t[0].padStart(2,'0')}:${(t[1]||'0').padStart(2,'0')}`;
  document.getElementById('schedule_run_mode').value = s.schedule_run_mode || 'trading_day';
  document.getElementById('nextRun').textContent =
    `下次: ${s.next_run_at || '—'} | 将执行: ${s.next_run_will_execute !== false ? '是' : '否'}`;
}

document.getElementById('saveSettings').onclick = async () => {
  const time = document.getElementById('schedule_time').value;
  await apiPut('/api/admin/settings', {
    schedule_enabled: document.getElementById('schedule_enabled').checked,
    schedule_time: time || '21:35',
    schedule_run_mode: document.getElementById('schedule_run_mode').value,
    schedule_timezone: 'Asia/Shanghai',
  });
  await loadSettings();
  alert('配置已保存');
};

document.getElementById('startFetch').onclick = async () => {
  const d = document.getElementById('fetchDate').value;
  if (!d) return alert('请选择日期');
  try {
    const r = await apiPost('/api/admin/fetch', { trade_date: d });
    alert(`任务已创建: ${r.job_id}`);
    pollJobs();
  } catch (e) { alert(e.message); }
};

document.getElementById('exportZip').onclick = () => {
  const d = document.getElementById('exportDate').value;
  if (!d) return alert('请选择日期');
  window.location = `/api/admin/export/${d}`;
};

document.getElementById('syncCal').onclick = async () => {
  const y = new Date().getFullYear();
  await apiPost('/api/admin/calendar/sync-db', { start: `${y}-01-01`, end: `${y}-12-31` });
  alert('交易日历已同步');
};

async function loadCalendar() {
  const data = await apiGet('/api/admin/calendar');
  document.getElementById('calendar').innerHTML = (data.dates || []).slice(0, 30).map(d =>
    `<div>${d.trade_date} — ${d.completeness} | 股 ${d.stock_count} | ETF ${d.etf_count}</div>`
  ).join('') || '暂无数据';
}

async function pollJobs() {
  const jobs = await apiGet('/api/admin/jobs?limit=20');
  const tbody = document.querySelector('#jobs tbody');
  tbody.innerHTML = jobs.map(j => `
    <tr>
      <td style="text-align:left;font-size:0.7rem">${j.job_id.slice(0,8)}…</td>
      <td>${j.trade_date}</td>
      <td>${j.trigger_type}</td>
      <td class="${j.status==='success'?'status-ok':j.status==='failed'?'status-fail':'status-warn'}">${j.status}</td>
      <td>${j.duration_sec ? j.duration_sec.toFixed(0)+'s' : '—'}</td>
      <td><button data-id="${j.job_id}" class="logBtn secondary">日志</button>
          ${j.status==='failed'?`<button data-retry="${j.job_id}" class="secondary">重试</button>`:''}</td>
    </tr>`).join('');
  tbody.querySelectorAll('.logBtn').forEach(btn => {
    btn.onclick = async () => {
      const log = await apiGet(`/api/admin/jobs/${btn.dataset.id}/log?tail=200`);
      document.getElementById('logTail').textContent = (log.lines || []).join('\n');
    };
  });
  tbody.querySelectorAll('[data-retry]').forEach(btn => {
    btn.onclick = async () => {
      await apiPost(`/api/admin/jobs/${btn.dataset.retry}/retry`, {});
      pollJobs();
    };
  });
}

const today = new Date().toISOString().slice(0, 10);
document.getElementById('fetchDate').value = today;
document.getElementById('exportDate').value = today;

loadSettings().catch(console.error);
loadCalendar().catch(console.error);
pollJobs().catch(console.error);
setInterval(pollJobs, 5000);
