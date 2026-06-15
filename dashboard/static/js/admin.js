initNav();

document.getElementById('saveSettings').onclick = async () => {
  const time = document.getElementById('schedule_time').value;
  try {
    const s = await apiPut('/api/admin/settings', {
      schedule_enabled: document.getElementById('schedule_enabled').checked,
      schedule_time: time || '21:35',
      schedule_run_mode: document.getElementById('schedule_run_mode').value,
      schedule_timezone: 'Asia/Shanghai',
    });
    applySettings(s);
    alert('配置已保存');
  } catch (e) {
    alert(typeof e.message === 'string' ? e.message : '保存失败');
  }
};

function applySettings(s) {
  document.getElementById('schedule_enabled').checked = s.schedule_enabled === 'true' || s.schedule_enabled === true;
  const t = (s.schedule_time || '21:35').split(':');
  document.getElementById('schedule_time').value = `${t[0].padStart(2,'0')}:${(t[1]||'0').padStart(2,'0')}`;
  document.getElementById('schedule_run_mode').value = s.schedule_run_mode || 'trading_day';
  document.getElementById('nextRun').textContent =
    `下次: ${s.next_run_at || '—'} | 将执行: ${s.next_run_will_execute !== false ? '是' : '否'}`;
}

async function loadSettings() {
  try {
    applySettings(await apiGet('/api/admin/settings'));
  } catch (e) {
    document.getElementById('nextRun').textContent = '加载配置失败';
    console.error(e);
  }
}

async function refreshFetchPreview() {
  const start = document.getElementById('fetchStart').value;
  const end = document.getElementById('fetchEnd').value;
  const el = document.getElementById('fetchPreview');
  if (!start || !end) {
    el.textContent = '请填写开始与结束日期';
    el.className = 'footnote';
    return;
  }
  try {
    const r = await apiGet(
      `/api/admin/fetch-preview?start=${encodeURIComponent(start)}&end=${encodeURIComponent(end)}`
    );
    if (r.valid) {
      const range = r.start_date === r.end_date ? r.start_date : `${r.start_date} ~ ${r.end_date}`;
      el.textContent = `共 ${r.trading_day_count} 个交易日（${range}）`;
      el.className = 'footnote status-ok';
    } else {
      el.textContent = r.error || '区间无效';
      el.className = 'footnote status-fail';
    }
  } catch {
    el.textContent = '';
  }
}

function scheduleFetchPreview() {
  clearTimeout(previewTimer);
  previewTimer = setTimeout(() => refreshFetchPreview().catch(console.error), 300);
}

document.getElementById('startFetch').onclick = async () => {
  const start = document.getElementById('fetchStart').value;
  const end = document.getElementById('fetchEnd').value;
  if (!start || !end) return alert('请填写开始与结束日期');
  try {
    const r = await apiPost('/api/admin/fetch', { start_date: start, end_date: end });
    alert(`任务已创建: ${r.job_id}（${r.trading_day_count} 个交易日）`);
    pollJobs();
  } catch (e) {
    alert(typeof e.message === 'string' ? e.message : '创建任务失败');
  }
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

function jobStatusClass(status) {
  if (status === 'success') return 'status-ok';
  if (status === 'failed') return 'status-fail';
  if (status === 'cancelled') return 'footnote';
  return 'status-warn';
}

function formatJobDates(j) {
  const end = j.end_date || j.trade_date;
  if (!end || end === j.trade_date) return j.trade_date;
  return `${j.trade_date} ~ ${end}`;
}

async function pollJobs() {
  const jobs = await apiGet('/api/admin/jobs?limit=20');
  const tbody = document.querySelector('#jobs tbody');
  tbody.innerHTML = jobs.map(j => `
    <tr>
      <td style="text-align:left;font-size:0.7rem">${j.job_id.slice(0,8)}…</td>
      <td>${formatJobDates(j)}</td>
      <td>${j.trigger_type}</td>
      <td class="${jobStatusClass(j.status)}">${j.status}${j.progress ? ` (${j.progress})` : ''}${j.error_message ? `<br/><span class="footnote status-fail">${j.error_message}</span>` : ''}</td>
      <td>${j.duration_sec ? j.duration_sec.toFixed(0)+'s' : '—'}</td>
      <td>
        <button data-id="${j.job_id}" class="logBtn secondary">日志</button>
        ${j.status === 'running' || j.status === 'pending'
          ? `<button data-cancel="${j.job_id}" class="secondary">取消</button>` : ''}
        ${j.status === 'failed' ? `<button data-retry="${j.job_id}" class="secondary">重试</button>` : ''}
      </td>
    </tr>`).join('');
  tbody.querySelectorAll('.logBtn').forEach(btn => {
    btn.onclick = async () => {
      const log = await apiGet(`/api/admin/jobs/${btn.dataset.id}/log?tail=200`);
      document.getElementById('logTail').textContent = (log.lines || []).join('\n');
    };
  });
  tbody.querySelectorAll('[data-cancel]').forEach(btn => {
    btn.onclick = async () => {
      if (!confirm('确定取消该任务？')) return;
      try {
        await apiPost(`/api/admin/jobs/${btn.dataset.cancel}/cancel`, {});
        pollJobs();
      } catch (e) { alert(e.message); }
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
document.getElementById('fetchStart').value = today;
document.getElementById('fetchEnd').value = today;
document.getElementById('exportDate').value = today;
document.getElementById('fetchStart').addEventListener('change', scheduleFetchPreview);
document.getElementById('fetchEnd').addEventListener('change', scheduleFetchPreview);

loadSettings().catch(console.error);
loadCalendar().catch(console.error);
refreshFetchPreview().catch(console.error);
pollJobs().catch(console.error);
setInterval(pollJobs, 5000);
