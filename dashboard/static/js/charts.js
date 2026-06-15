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

function stackedBuySellOption(dates, buySeries, sellSeries) {
  return {
    tooltip: {
      trigger: 'axis',
      axisPointer: { type: 'shadow' },
      formatter(params) {
        const date = params[0]?.axisValue || '';
        const buy = params.find(p => p.seriesName === '主买')?.value ?? 0;
        const sell = params.find(p => p.seriesName === '主卖')?.value ?? 0;
        const total = buy + sell;
        return [
          date,
          `成交额：${formatAmount(total).text}`,
          `主买：${formatAmount(buy).text}`,
          `主卖：${formatAmount(sell).text}`,
        ].join('<br/>');
      },
    },
    legend: {
      data: ['主买', '主卖'],
      textStyle: { color: '#8b9cb3' },
      top: 0,
    },
    grid: { left: 8, right: 16, top: 36, bottom: 28, containLabel: true },
    xAxis: {
      type: 'category',
      data: dates.map(shortDate),
      axisLabel: { color: '#8b9cb3' },
    },
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
    series: [
      {
        name: '主买',
        type: 'bar',
        stack: 'flow',
        emphasis: { focus: 'series' },
        itemStyle: { color: '#ef4444' },
        data: buySeries,
      },
      {
        name: '主卖',
        type: 'bar',
        stack: 'flow',
        emphasis: { focus: 'series' },
        itemStyle: { color: '#22c55e' },
        data: sellSeries,
      },
    ],
  };
}

function disposeChart(chart) {
  if (chart) chart.dispose();
}
