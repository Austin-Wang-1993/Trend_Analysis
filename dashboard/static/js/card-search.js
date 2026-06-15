/**
 * 卡片列页面搜索：按日期今→远、列内上→下定位，滚动 + 文字高亮。
 */
function createCardSearch(opts) {
  const {
    inputEl,
    countEl,
    prevBtn,
    nextBtn,
    boardEl,
    boardOuter,
    viewportEl,
    syncHorizontalScroll,
    getMatchText,
    nameSelector = '.sector-name',
    onSearchActive,
    onClearCrossHighlight,
  } = opts;

  let results = [];
  let currentIndex = -1;
  let query = '';
  let debounceTimer = null;

  function isActive() {
    return query.trim().length > 0;
  }

  function escapeRegex(s) {
    return String(s).replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
  }

  function notifyActive(active) {
    if (onSearchActive) onSearchActive(active);
  }

  function clearHighlights() {
    boardEl.querySelectorAll('.sector-card').forEach(card => {
      card.classList.remove('search-match', 'search-current');
      const nameEl = card.querySelector(nameSelector);
      if (nameEl && nameEl.dataset.originalText != null) {
        nameEl.textContent = nameEl.dataset.originalText;
        delete nameEl.dataset.originalText;
      }
    });
  }

  function applyMark(nameEl, q) {
    const raw = nameEl.dataset.originalText || nameEl.textContent;
    nameEl.dataset.originalText = raw;
    const re = new RegExp(`(${escapeRegex(q)})`, 'gi');
    nameEl.innerHTML = raw.replace(re, '<mark class="search-mark">$1</mark>');
  }

  function buildResults() {
    const q = query.trim().toLowerCase();
    if (!q) return [];
    const list = [];
    boardEl.querySelectorAll('.sector-column').forEach(col => {
      col.querySelectorAll('.sector-card').forEach(card => {
        if (getMatchText(card).toLowerCase().includes(q)) list.push(card);
      });
    });
    return list;
  }

  function updateCountText() {
    if (!results.length) {
      countEl.textContent = query.trim() ? '找到 0 个' : '';
      return;
    }
    countEl.textContent = `找到 ${results.length} 个 · ${currentIndex + 1}/${results.length}`;
  }

  function scrollToCard(card) {
    const col = card.closest('.sector-column');
    if (col && boardOuter) {
      const colLeft = col.offsetLeft;
      const colRight = colLeft + col.offsetWidth;
      const viewLeft = boardOuter.scrollLeft;
      const viewRight = viewLeft + boardOuter.clientWidth;
      if (colLeft < viewLeft) {
        boardOuter.scrollLeft = Math.max(0, colLeft - 12);
      } else if (colRight > viewRight) {
        boardOuter.scrollLeft = Math.max(0, colRight - boardOuter.clientWidth + 12);
      }
      if (syncHorizontalScroll) syncHorizontalScroll();
    }
    if (!viewportEl) return;
    requestAnimationFrame(() => {
      const vRect = viewportEl.getBoundingClientRect();
      const cRect = card.getBoundingClientRect();
      const pad = 16;
      if (cRect.top < vRect.top + pad) {
        viewportEl.scrollTop += cRect.top - vRect.top - pad;
      } else if (cRect.bottom > vRect.bottom - pad) {
        viewportEl.scrollTop += cRect.bottom - vRect.bottom + pad;
      }
    });
  }

  function goTo(index) {
    if (!results.length) return;
    currentIndex = ((index % results.length) + results.length) % results.length;
    boardEl.querySelectorAll('.sector-card.search-current').forEach(c => c.classList.remove('search-current'));
    const card = results[currentIndex];
    card.classList.add('search-current');
    scrollToCard(card);
    updateCountText();
  }

  function runSearch() {
    clearHighlights();
    results = buildResults();
    prevBtn.disabled = nextBtn.disabled = results.length === 0;
    updateCountText();

    if (!results.length) {
      currentIndex = -1;
      notifyActive(isActive());
      return;
    }

    const q = query.trim();
    results.forEach(card => {
      card.classList.add('search-match');
      const nameEl = card.querySelector(nameSelector);
      if (nameEl) applyMark(nameEl, q);
    });

    if (currentIndex < 0 || currentIndex >= results.length) currentIndex = 0;
    goTo(currentIndex);
    notifyActive(true);
  }

  function resetSearch() {
    query = inputEl.value;
    currentIndex = -1;
    clearHighlights();
    results = [];
    prevBtn.disabled = nextBtn.disabled = true;
    countEl.textContent = '';
    notifyActive(false);
  }

  function onInput() {
    query = inputEl.value;
    currentIndex = -1;
    clearTimeout(debounceTimer);
    debounceTimer = setTimeout(() => {
      if (!query.trim()) {
        resetSearch();
        return;
      }
      if (onClearCrossHighlight) onClearCrossHighlight();
      runSearch();
    }, 200);
  }

  inputEl.addEventListener('input', onInput);
  prevBtn.addEventListener('click', () => {
    if (results.length) goTo(currentIndex - 1);
  });
  nextBtn.addEventListener('click', () => {
    if (results.length) goTo(currentIndex + 1);
  });
  inputEl.addEventListener('keydown', (e) => {
    if (e.key !== 'Enter') return;
    e.preventDefault();
    if (!results.length) return;
    goTo(e.shiftKey ? currentIndex - 1 : currentIndex + 1);
  });

  prevBtn.disabled = nextBtn.disabled = true;

  return {
    isActive,
    onBoardRendered() {
      if (!query.trim()) return;
      if (onClearCrossHighlight) onClearCrossHighlight();
      currentIndex = -1;
      runSearch();
    },
  };
}
