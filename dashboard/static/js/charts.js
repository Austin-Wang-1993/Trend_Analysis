function initNav(active) {
  const links = [
    ['/', '概览'],
    ['/sectors-table.html', '板块表格'],
    ['/sectors-charts.html', '板块图表'],
    ['/etf-table.html', 'ETF 表格'],
    ['/etf-charts.html', 'ETF 图表'],
    ['/admin.html', '管理'],
  ];
  const nav = document.querySelector('nav');
  if (!nav) return;
  nav.innerHTML = links
    .map(([href, label]) => {
      const cls = (active === href || (active === 'index' && href === '/')) ? ' class="active"' : '';
      return `<a href="${href}"${cls}>${label}</a>`;
    })
    .join('');
}

function barChartOption(title, dates, series, color) {
  return {
    title: { text: title, textStyle: { color: '#e7ecf3', fontSize: 14 } },
    tooltip: {
      trigger: 'axis',
      formatter(params) {
        const p = params[0];
        return `${p.name}<br/>${formatAmount(p.value).text}`;
      },
    },
    grid: { left: 8, right: 16, top: 40, bottom: 28, containLabel: true },
    xAxis: { type: 'category', data: dates.map(shortDate), axisLabel: { color: '#8b9cb3' } },
    yAxis: {
      type: 'value',
      axisLabel: {
        color: '#8b9cb3',
        margin: 8,
        formatter(v) {
          const f = formatAmount(v);
          if (f.unit === '元') return String(v);
          return `${f.value.toFixed(f.value >= 100 ? 0 : 1)}${f.unit}`;
        },
      },
    },
    series: [{ type: 'bar', data: series, itemStyle: { color: color || '#3b82f6' } }],
  };
}

function renderBar(el, option) {
  const chart = echarts.init(el);
  chart.setOption(option);
  window.addEventListener('resize', () => chart.resize());
  return chart;
}

function disposeChart(chart) {
  if (chart) chart.dispose();
}
