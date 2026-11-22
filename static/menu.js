(() => {
  'use strict';

  const root = document.getElementById('setup');
  if (!root) return;

  const ALL = root.dataset.tables.split(',').map(Number);
  const RANGES = {
    count: root.dataset.countRange.split(',').map(Number),
    time: root.dataset.timeRange.split(',').map(Number),
  };
  const STORE_KEY = 'timesblitz.setup.v1';

  const modeBtns = root.querySelectorAll('[data-mode]');
  const groups = {
    count: root.querySelector('#amounts-count'),
    time: root.querySelector('#amounts-time'),
  };
  const customs = {
    count: root.querySelector('#custom-count'),
    time: root.querySelector('#custom-time'),
  };
  const amountLabel = root.querySelector('#amount-label');
  const tableBtns = root.querySelectorAll('[data-table]');
  const toggleAll = root.querySelector('#toggle-all');
  const summary = root.querySelector('#summary');
  const startBtn = root.querySelector('#start');

  const presets = {
    count: [...groups.count.querySelectorAll('[data-n]')].map((b) => Number(b.dataset.n)),
    time: [...groups.time.querySelectorAll('[data-n]')].map((b) => Number(b.dataset.n)),
  };

  const inRange = (mode, v) => Number.isFinite(v) && v >= RANGES[mode][0] && v <= RANGES[mode][1];

  function load() {
    const state = { mode: 'count', n: { count: 20, time: 60 }, tables: ALL.slice() };
    try {
      const saved = JSON.parse(localStorage.getItem(STORE_KEY) || 'null');
      if (saved) {
        if (saved.mode === 'count' || saved.mode === 'time') state.mode = saved.mode;
        for (const m of ['count', 'time']) {
          const v = Math.round(Number(saved.n && saved.n[m]));
          if (inRange(m, v)) state.n[m] = v;
        }
        if (Array.isArray(saved.tables)) {
          const t = saved.tables.map(Number).filter((x) => ALL.includes(x));
          if (t.length) state.tables = [...new Set(t)].sort((a, b) => a - b);
        }
      }
    } catch (_) { /* ignore corrupt storage */ }
    return state;
  }

  function save() {
    try { localStorage.setItem(STORE_KEY, JSON.stringify(state)); } catch (_) { /* private mode */ }
  }

  function tablesLabel(tables) {
    const nums = [...tables].sort((a, b) => a - b);
    const parts = [];
    let start = nums[0];
    let prev = nums[0];
    for (const n of [...nums.slice(1), null]) {
      if (n !== null && n === prev + 1) { prev = n; continue; }
      parts.push(start === prev ? String(start) : `${start}–${prev}`);
      start = prev = n;
    }
    return parts.join(', ');
  }

  function amountText(mode, n) {
    if (mode === 'count') return `${n} question${n === 1 ? '' : 's'}`;
    if (n < 60) return `${n} seconds`;
    const m = Math.floor(n / 60);
    const s = n % 60;
    return s === 0 ? `${m} minute${m === 1 ? '' : 's'}` : `${m} min ${s} s`;
  }

  function render() {
    const { mode } = state;

    modeBtns.forEach((b) => b.setAttribute('aria-pressed', String(b.dataset.mode === mode)));
    groups.count.hidden = mode !== 'count';
    groups.time.hidden = mode !== 'time';
    amountLabel.textContent = mode === 'count' ? 'How many questions?' : 'How long?';

    const n = state.n[mode];
    groups[mode].querySelectorAll('[data-n]').forEach((b) =>
      b.setAttribute('aria-pressed', String(Number(b.dataset.n) === n)));

    const custom = customs[mode];
    const isCustom = !presets[mode].includes(n);
    custom.parentElement.classList.toggle('active', isCustom);
    if (isCustom && document.activeElement !== custom) custom.value = n;
    if (!isCustom && document.activeElement !== custom) custom.value = '';

    tableBtns.forEach((b) =>
      b.setAttribute('aria-pressed', String(state.tables.includes(Number(b.dataset.table)))));
    toggleAll.textContent = state.tables.length === ALL.length ? 'Clear all' : 'Select all';

    if (state.tables.length === 0) {
      summary.textContent = 'Pick at least one times table.';
      startBtn.disabled = true;
    } else {
      const tablesText = state.tables.length === ALL.length
        ? 'all tables'
        : `tables ${tablesLabel(state.tables)}`;
      summary.textContent = `${amountText(mode, n)} · ${tablesText}`;
      startBtn.disabled = false;
    }
  }

  const state = load();

  modeBtns.forEach((b) => b.addEventListener('click', () => {
    state.mode = b.dataset.mode;
    save(); render();
  }));

  Object.entries(groups).forEach(([mode, group]) => {
    group.querySelectorAll('[data-n]').forEach((b) => b.addEventListener('click', () => {
      state.n[mode] = Number(b.dataset.n);
      customs[mode].value = '';
      save(); render();
    }));
  });

  Object.entries(customs).forEach(([mode, input]) => {
    input.addEventListener('input', () => {
      const v = Math.round(Number(input.value));
      if (input.value !== '' && inRange(mode, v)) {
        state.n[mode] = v;
        save(); render();
      }
    });
    input.addEventListener('change', () => {
      // Clamp anything out of range once the player is done typing.
      const v = Math.round(Number(input.value));
      if (input.value !== '' && Number.isFinite(v)) {
        state.n[mode] = Math.min(RANGES[mode][1], Math.max(RANGES[mode][0], v));
        save();
      }
      input.blur();
      render();
    });
  });

  tableBtns.forEach((b) => b.addEventListener('click', () => {
    const t = Number(b.dataset.table);
    state.tables = state.tables.includes(t)
      ? state.tables.filter((x) => x !== t)
      : [...state.tables, t].sort((a, c) => a - c);
    save(); render();
  }));

  toggleAll.addEventListener('click', () => {
    state.tables = state.tables.length === ALL.length ? [] : ALL.slice();
    save(); render();
  });

  startBtn.addEventListener('click', () => {
    if (state.tables.length === 0) return;
    const params = new URLSearchParams({
      mode: state.mode,
      n: String(state.n[state.mode]),
      tables: state.tables.join(','),
    });
    window.location.href = `${root.dataset.quizUrl}?${params}`;
  });

  render();
})();
