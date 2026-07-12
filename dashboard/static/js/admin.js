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

const saveSigBtn = document.getElementById('saveSignalSettings');
if (saveSigBtn) {
  saveSigBtn.onclick = async () => {
    try {
      const s = await apiPut('/api/admin/settings', {
        signal_enabled: document.getElementById('signal_enabled').checked,
        signal_poll_interval_sec: Number(document.getElementById('signal_poll_interval_sec').value || 15),
        signal_sched_start: document.getElementById('signal_sched_start').value || '09:25',
        signal_sched_end: document.getElementById('signal_sched_end').value || '09:45',
        signal_window_start: document.getElementById('signal_window_start').value || '09:30',
        signal_window_end: document.getElementById('signal_window_end').value || '09:40',
        signal_pct_threshold: Number(document.getElementById('signal_pct_threshold').value || 9.8),
        signal_engulf_mode: document.getElementById('signal_engulf_mode').value,
        signal_cross_body_ratio: Number(document.getElementById('signal_cross_body_ratio').value || 0.1),
        signal_long_upper_ratio: Number(document.getElementById('signal_long_upper_ratio').value || 1.0),
      });
      applySettings(s);
      alert('信号配置已保存');
    } catch (e) {
      alert(typeof e.message === 'string' ? e.message : '保存失败');
    }
  };
}

function collectTdSettings() {
  return {
    td_enabled: document.getElementById('td_enabled').checked,
    td_time: document.getElementById('td_time').value || '16:45',
    td_history_days: Number(document.getElementById('td_history_days').value || 120),
    td_lookback_days: Number(document.getElementById('td_lookback_days').value || 20),
    td_vol_shrink_ratio: Number(document.getElementById('td_vol_shrink_ratio').value || 0.8),
    td_vol_expand_ratio: Number(document.getElementById('td_vol_expand_ratio').value || 1.2),
    td_shadow_lower_min: Number(document.getElementById('td_shadow_lower_min').value || 0.5),
    td_cross_body_max: Number(document.getElementById('td_cross_body_max').value || 0.15),
    td_vol_price_mode: document.getElementById('td_vol_price_mode').value,
    td_countdown_near_min: Number(document.getElementById('td_countdown_near_min').value || 10),
    td_countdown_near_max: Number(document.getElementById('td_countdown_near_max').value || 13),
    td_countdown_after_setup_days: Number(document.getElementById('td_countdown_after_setup_days').value || 5),
    td_macd_valley_close_pct: Number(document.getElementById('td_macd_valley_close_pct').value || 0.10),
    td_macd_ref_valley_min: Number(document.getElementById('td_macd_ref_valley_min').value || 1),
    td_macd_ref_valley_max: Number(document.getElementById('td_macd_ref_valley_max').value || 3),
    td_stop_loss_pct: Number(document.getElementById('td_stop_loss_pct').value || 0.03),
  };
}

const saveTdBtn = document.getElementById('saveTdSettings');
if (saveTdBtn) {
  saveTdBtn.onclick = async () => {
    try {
      const s = await apiPut('/api/admin/settings', collectTdSettings());
      applySettings(s);
      alert('神奇九转配置已保存');
    } catch (e) {
      alert(typeof e.message === 'string' ? e.message : '保存失败');
    }
  };
}

async function pollTdScan(jobId, el) {
  while (true) {
    const st = await apiGet(`/api/td-sequential/scan/status?job_id=${encodeURIComponent(jobId)}`);
    const job = st.job;
    if (el && job) {
      const p = job.progress || job.status;
      el.textContent = p.startsWith('cache:') ? `扫描中 · 补缓存 ${p.slice(6)}` : `扫描中 · ${p}`;
    }
    if (!st.active) {
      if (job?.status === 'failed') throw new Error(job.error_message || '扫描失败');
      if (el && job) el.textContent = `完成：${job.pick_count ?? 0} 条，扫描日 ${job.trade_date || ''}`;
      return job;
    }
    await new Promise(r => setTimeout(r, 2000));
  }
}

const runTdBtn = document.getElementById('runTdScan');
if (runTdBtn) {
  runTdBtn.onclick = async () => {
    const el = document.getElementById('tdScanResult');
    if (!confirm('将补全缺失缓存并扫描神奇九转，继续？')) return;
    if (el) el.textContent = '提交任务…';
    try {
      const j = await apiPost('/api/admin/td-sequential/scan', {});
      await pollTdScan(j.job_id, el);
    } catch (e) {
      if (el) el.textContent = typeof e.message === 'string' ? e.message : '请求失败';
    }
  };
}

function collectAccumSettings() {
  return {
    accum_enabled: document.getElementById('accum_enabled').checked,
    accum_time: document.getElementById('accum_time').value || '17:00',
    accum_history_days: Number(document.getElementById('accum_history_days').value || 120),
    accum_vol_expand_trigger: Number(document.getElementById('accum_vol_expand_trigger').value || 2.0),
    accum_vol_expand_start: Number(document.getElementById('accum_vol_expand_start').value || 2.0),
    accum_vol_expand_decay: Number(document.getElementById('accum_vol_expand_decay').value || 0.1),
    accum_vol_expand_floor: Number(document.getElementById('accum_vol_expand_floor').value || 1.1),
    accum_vol_expand_max_consecutive_miss: Number(document.getElementById('accum_vol_expand_max_consecutive_miss').value || 3),
    accum_vol_min_days: Number(document.getElementById('accum_vol_min_days').value || 3),
    accum_price_rise_min: Number(document.getElementById('accum_price_rise_min').value || 0.30),
    accum_wash_mult: Number(document.getElementById('accum_wash_mult').value || 1.5),
    accum_vol_shrink_max: Number(document.getElementById('accum_vol_shrink_max').value || 1.1),
    accum_vol_wash_max_over_days: Number(document.getElementById('accum_vol_wash_max_over_days').value || 1),
    accum_vol_wash_max_consecutive_over: Number(document.getElementById('accum_vol_wash_max_consecutive_over').value || 2),
    accum_vol_reset_trigger: Number(document.getElementById('accum_vol_reset_trigger').value || 2.0),
    accum_drawdown_min: Number(document.getElementById('accum_drawdown_min').value || 0.60),
    accum_drawdown_max: Number(document.getElementById('accum_drawdown_max').value || 0.90),
  };
}

const saveAccumBtn = document.getElementById('saveAccumSettings');
if (saveAccumBtn) {
  saveAccumBtn.onclick = async () => {
    try {
      const s = await apiPut('/api/admin/settings', collectAccumSettings());
      applySettings(s);
      alert('量价吸筹配置已保存');
    } catch (e) {
      alert(typeof e.message === 'string' ? e.message : '保存失败');
    }
  };
}

async function pollAccumScan(jobId, el) {
  while (true) {
    const st = await apiGet(`/api/accum-pattern/scan/status?job_id=${encodeURIComponent(jobId)}`);
    const job = st.job;
    if (el && job) {
      const p = job.progress || job.status;
      el.textContent = p.startsWith('cache:') ? `扫描中 · 补缓存 ${p.slice(6)}` : `扫描中 · ${p}`;
    }
    if (!st.active) {
      if (job?.status === 'failed') throw new Error(job.error_message || '扫描失败');
      if (el && job) el.textContent = `完成：${job.pick_count ?? 0} 条，扫描日 ${job.trade_date || ''}`;
      return job;
    }
    await new Promise(r => setTimeout(r, 2000));
  }
}

const runAccumBtn = document.getElementById('runAccumScan');
if (runAccumBtn) {
  runAccumBtn.onclick = async () => {
    const el = document.getElementById('accumScanResult');
    if (!confirm('将补全 qfq 缓存并扫描量价吸筹，继续？')) return;
    if (el) el.textContent = '提交任务…';
    try {
      const j = await apiPost('/api/admin/accum-pattern/scan', {});
      await pollAccumScan(j.job_id, el);
    } catch (e) {
      if (el) el.textContent = typeof e.message === 'string' ? e.message : '请求失败';
    }
  };
}

function collectTrainTrackSettings() {
  return {
    train_track_enabled: document.getElementById('train_track_enabled').checked,
    train_track_time: document.getElementById('train_track_time').value || '16:30',
    train_track_default_limit: Number(document.getElementById('train_track_default_limit').value || 20),
    train_track_rps_sum_min: Number(document.getElementById('train_track_rps_sum_min').value || 185),
    train_track_near_high_250_min: Number(document.getElementById('train_track_near_high_250_min').value || 0.8),
    train_track_drawdown_20_max: Number(document.getElementById('train_track_drawdown_20_max').value || 0.25),
    train_track_turnover_max: Number(document.getElementById('train_track_turnover_max').value || 10),
    train_track_recent_20d_pct_max: Number(document.getElementById('train_track_recent_20d_pct_max').value || 30),
    train_track_ma_touch_band_pct: Number(document.getElementById('train_track_ma_touch_band_pct').value || 2),
    train_track_count_ma250_30_min: Number(document.getElementById('train_track_count_ma250_30_min').value || 25),
    train_track_count_ma200_30_min: Number(document.getElementById('train_track_count_ma200_30_min').value || 25),
    train_track_count_ma20_10_min: Number(document.getElementById('train_track_count_ma20_10_min').value || 9),
    train_track_count_ma10_4_min: Number(document.getElementById('train_track_count_ma10_4_min').value || 3),
    train_track_count_ma20_4_min: Number(document.getElementById('train_track_count_ma20_4_min').value || 3),
    train_track_ma_rise_days: Number(document.getElementById('train_track_ma_rise_days').value || 5),
    train_track_history_days: Number(document.getElementById('train_track_history_days').value || 250),
  };
}

const saveTtBtn = document.getElementById('saveTrainTrackSettings');
if (saveTtBtn) {
  saveTtBtn.onclick = async () => {
    try {
      const s = await apiPut('/api/admin/settings', collectTrainTrackSettings());
      applySettings(s);
      alert('火车轨配置已保存');
    } catch (e) {
      alert(typeof e.message === 'string' ? e.message : '保存失败');
    }
  };
}

const presetTtBtn = document.getElementById('applyTrainTrackPreset');
if (presetTtBtn) {
  presetTtBtn.onclick = async () => {
    if (!confirm('将填入宽松预设（RPS和170、近20日涨<40% 等）并保存，继续？')) return;
    document.getElementById('train_track_rps_sum_min').value = '170';
    document.getElementById('train_track_recent_20d_pct_max').value = '40';
    document.getElementById('train_track_drawdown_20_max').value = '0.35';
    document.getElementById('train_track_near_high_250_min').value = '0.75';
    document.getElementById('train_track_count_ma250_30_min').value = '20';
    document.getElementById('train_track_count_ma200_30_min').value = '20';
    try {
      const s = await apiPut('/api/admin/settings', collectTrainTrackSettings());
      applySettings(s);
      alert('宽松预设已保存，请到火车轨页点「立即重算」');
    } catch (e) {
      alert(typeof e.message === 'string' ? e.message : '保存失败');
    }
  };
}

function formatTrainTrackProgress(job) {
  if (!job) return '';
  const p = job.progress || '';
  if (p.startsWith('cache:')) return `补缓存 ${p.slice(6)} 日`;
  if (p === 'compute') return '计算 RPS/SXHCG…';
  if (p === 'done') return '完成';
  if (job.status === 'running') return '运行中…';
  return p;
}

async function pollTrainTrackScan(jobId, el) {
  while (true) {
    const st = await apiGet(`/api/train-track/scan/status?job_id=${encodeURIComponent(jobId)}`);
    const job = st.job;
    if (el && job) el.textContent = `扫描中 · ${formatTrainTrackProgress(job)}`;
    if (!st.active) {
      if (job?.status === 'failed') throw new Error(job.error_message || '扫描失败');
      if (el && job) {
        el.textContent = job.progress && job.progress !== 'done'
          ? `已结束：${formatTrainTrackProgress(job)}`
          : `完成：${job.pick_count ?? 0} 条，扫描日 ${job.trade_date || ''}`;
      }
      return job;
    }
    await new Promise(r => setTimeout(r, 2000));
  }
}

const runTtBtn = document.getElementById('runTrainTrackScan');
if (runTtBtn) {
  runTtBtn.onclick = async () => {
    const el = document.getElementById('trainTrackScanResult');
    if (!confirm('将补全缺失缓存并扫描；日常手动补数也会写入火车轨缓存，继续？')) return;
    if (el) el.textContent = '提交任务…';
    try {
      const j = await apiPost('/api/admin/train-track/scan', {});
      await pollTrainTrackScan(j.job_id, el);
    } catch (e) {
      if (el) el.textContent = typeof e.message === 'string' ? e.message : '请求失败';
    }
  };
}

function applySettings(s) {
  document.getElementById('schedule_enabled').checked = s.schedule_enabled === 'true' || s.schedule_enabled === true;
  const t = (s.schedule_time || '21:35').split(':');
  document.getElementById('schedule_time').value = `${t[0].padStart(2,'0')}:${(t[1]||'0').padStart(2,'0')}`;
  document.getElementById('schedule_run_mode').value = s.schedule_run_mode || 'trading_day';
  document.getElementById('nextRun').textContent =
    `下次: ${s.next_run_at || '—'} | 将执行: ${s.next_run_will_execute !== false ? '是' : '否'}`;
  const sigOn = document.getElementById('signal_enabled');
  if (sigOn) {
    sigOn.checked = s.signal_enabled === 'true' || s.signal_enabled === true;
    document.getElementById('signal_poll_interval_sec').value = s.signal_poll_interval_sec || '15';
    setTimeInput('signal_sched_start', s.signal_sched_start || '09:25');
    setTimeInput('signal_sched_end', s.signal_sched_end || '09:45');
    setTimeInput('signal_window_start', s.signal_window_start || '09:30');
    setTimeInput('signal_window_end', s.signal_window_end || '09:40');
    document.getElementById('signal_pct_threshold').value = s.signal_pct_threshold || '9.8';
    document.getElementById('signal_engulf_mode').value = s.signal_engulf_mode || 'high';
    document.getElementById('signal_cross_body_ratio').value = s.signal_cross_body_ratio || '0.1';
    document.getElementById('signal_long_upper_ratio').value = s.signal_long_upper_ratio || '1.0';
  }
  const ttOn = document.getElementById('train_track_enabled');
  if (ttOn) {
    ttOn.checked = s.train_track_enabled === 'true' || s.train_track_enabled === true;
    setTimeInput('train_track_time', s.train_track_time || '16:30');
    document.getElementById('train_track_default_limit').value = s.train_track_default_limit || '20';
    document.getElementById('train_track_rps_sum_min').value = s.train_track_rps_sum_min || '185';
    document.getElementById('train_track_near_high_250_min').value = s.train_track_near_high_250_min || '0.8';
    document.getElementById('train_track_drawdown_20_max').value = s.train_track_drawdown_20_max || '0.25';
    document.getElementById('train_track_turnover_max').value = s.train_track_turnover_max || '10';
    document.getElementById('train_track_recent_20d_pct_max').value = s.train_track_recent_20d_pct_max || '30';
    document.getElementById('train_track_ma_touch_band_pct').value = s.train_track_ma_touch_band_pct || '2';
    document.getElementById('train_track_count_ma250_30_min').value = s.train_track_count_ma250_30_min || '25';
    document.getElementById('train_track_count_ma200_30_min').value = s.train_track_count_ma200_30_min || '25';
    document.getElementById('train_track_count_ma20_10_min').value = s.train_track_count_ma20_10_min || '9';
    document.getElementById('train_track_count_ma10_4_min').value = s.train_track_count_ma10_4_min || '3';
    document.getElementById('train_track_count_ma20_4_min').value = s.train_track_count_ma20_4_min || '3';
    document.getElementById('train_track_ma_rise_days').value = s.train_track_ma_rise_days || '5';
    document.getElementById('train_track_history_days').value = s.train_track_history_days || '250';
  }
  const tdOn = document.getElementById('td_enabled');
  if (tdOn) {
    tdOn.checked = s.td_enabled === 'true' || s.td_enabled === true;
    setTimeInput('td_time', s.td_time || '16:45');
    document.getElementById('td_history_days').value = s.td_history_days || '120';
    document.getElementById('td_lookback_days').value = s.td_lookback_days || '20';
    document.getElementById('td_vol_shrink_ratio').value = s.td_vol_shrink_ratio || '0.8';
    document.getElementById('td_vol_expand_ratio').value = s.td_vol_expand_ratio || '1.2';
    document.getElementById('td_shadow_lower_min').value = s.td_shadow_lower_min || '0.5';
    document.getElementById('td_cross_body_max').value = s.td_cross_body_max || '0.15';
    document.getElementById('td_vol_price_mode').value = s.td_vol_price_mode || 'or';
    document.getElementById('td_countdown_near_min').value = s.td_countdown_near_min || '10';
    document.getElementById('td_countdown_near_max').value = s.td_countdown_near_max || '13';
    document.getElementById('td_countdown_after_setup_days').value = s.td_countdown_after_setup_days || '5';
    document.getElementById('td_macd_valley_close_pct').value = s.td_macd_valley_close_pct || '0.10';
    document.getElementById('td_macd_ref_valley_min').value = s.td_macd_ref_valley_min || '1';
    document.getElementById('td_macd_ref_valley_max').value = s.td_macd_ref_valley_max || '3';
    document.getElementById('td_stop_loss_pct').value = s.td_stop_loss_pct || '0.03';
  }
  const accumOn = document.getElementById('accum_enabled');
  if (accumOn) {
    accumOn.checked = s.accum_enabled === 'true' || s.accum_enabled === true;
    setTimeInput('accum_time', s.accum_time || '17:00');
    document.getElementById('accum_history_days').value = s.accum_history_days || '120';
    document.getElementById('accum_vol_expand_trigger').value = s.accum_vol_expand_trigger || '2.0';
    document.getElementById('accum_vol_expand_start').value = s.accum_vol_expand_start || '2.0';
    document.getElementById('accum_vol_expand_decay').value = s.accum_vol_expand_decay || '0.1';
    document.getElementById('accum_vol_expand_floor').value = s.accum_vol_expand_floor || '1.1';
    document.getElementById('accum_vol_expand_max_consecutive_miss').value = s.accum_vol_expand_max_consecutive_miss || '3';
    document.getElementById('accum_vol_min_days').value = s.accum_vol_min_days || '3';
    document.getElementById('accum_price_rise_min').value = s.accum_price_rise_min || '0.30';
    document.getElementById('accum_wash_mult').value = s.accum_wash_mult || '1.5';
    document.getElementById('accum_vol_shrink_max').value = s.accum_vol_shrink_max || '1.1';
    document.getElementById('accum_vol_wash_max_over_days').value = s.accum_vol_wash_max_over_days || '1';
    document.getElementById('accum_vol_wash_max_consecutive_over').value = s.accum_vol_wash_max_consecutive_over || '2';
    document.getElementById('accum_vol_reset_trigger').value = s.accum_vol_reset_trigger || '2.0';
    document.getElementById('accum_drawdown_min').value = s.accum_drawdown_min || '0.60';
    document.getElementById('accum_drawdown_max').value = s.accum_drawdown_max || '0.90';
  }
}

function setTimeInput(id, hhmm) {
  const [h, m] = (hhmm || '00:00').split(':');
  document.getElementById(id).value = `${h.padStart(2,'0')}:${(m||'0').padStart(2,'0')}`;
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
