/** 全站顶栏导航（唯一实现；各页须引入本文件，勿在 charts.js 等处重复定义）。 */
function initNav(active) {
  const path = location.pathname.replace(/\/$/, '') || '/';
  const links = [
    ['/', '概览'],
    ['/sectors-table.html', '板块表格'],
    ['/sectors-charts.html', '板块图表'],
    ['/stock-list.html', '股票清单'],
    ['/etf-table.html', 'ETF 表格'],
    ['/admin.html', '管理'],
  ];
  const nav = document.querySelector('nav');
  if (!nav) return;
  nav.innerHTML = links
    .map(([href, label]) => {
      const isActive = path === href || (path.endsWith('index.html') && href === '/');
      return `<a href="${href}"${isActive ? ' class="active"' : ''}>${label}</a>`;
    })
    .join('');
}
