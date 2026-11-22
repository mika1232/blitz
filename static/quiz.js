(() => {
  'use strict';

  const $ = (id) => document.getElementById(id);
  const root = $('quiz');
  if (!root) return;

  const MODE = root.dataset.mode;                       // 'count' | 'time'
  const TARGET = parseInt(root.dataset.target, 10);     // questions or seconds
  const TABLES = root.dataset.tables.split(',').map(Number);
  const SAVE_URL = root.dataset.saveUrl;
  const CSRF = document.querySelector('meta[name="csrf-token"]').content;
  const MAX_DIGITS = 3;

  const el = {
    label: $('progress-label'),
    score: $('score-pill'),
    fill: $('bar-fill'),
    stage: $('stage'),
    question: $('question'),
    qa: $('q-a'),
    qb: $('q-b'),
    answer: $('answer-text'),
    feedback: $('feedback'),
    keypad: $('keypad'),
    countdown: $('countdown'),
    countNum: $('count-num'),
  };

  // ---- State -------------------------------------------------------------
  let pool = [];
  let current = null;
  let last = null;
  let typed = '';
  let answered = 0;
  let correct = 0;
  const mistakes = [];
  let running = false;
  let startedAt = 0;
  let timerId = null;

  // ---- Helpers -----------------------------------------------------------
  const fmt = (secs) => `${Math.floor(secs / 60)}:${String(secs % 60).padStart(2, '0')}`;

  function shuffle(a) {
    for (let i = a.length - 1; i > 0; i--) {
      const j = Math.floor(Math.random() * (i + 1));
      [a[i], a[j]] = [a[j], a[i]];
    }
    return a;
  }

  // Every fact from the chosen tables is asked once before any repeats.
  function refill() {
    pool = [];
    for (const t of TABLES) for (let m = 2; m <= 12; m++) pool.push([t, m]);
    shuffle(pool);
  }

  const samePair = (p, q) => q && Math.min(p[0], p[1]) === Math.min(q.a, q.b)
                          && Math.max(p[0], p[1]) === Math.max(q.a, q.b);

  function drawQuestion() {
    if (!pool.length) refill();
    let pair = pool.pop();
    if (pool.length && samePair(pair, last)) {   // avoid asking the same fact twice in a row
      pool.unshift(pair);
      pair = pool.pop();
    }
    let [a, b] = pair;
    if (Math.random() < 0.5) [a, b] = [b, a];
    return { a, b, answer: a * b };
  }

  function replay(node, cls) {
    node.classList.remove(cls);
    void node.offsetWidth;                         // restart the CSS animation
    node.classList.add(cls);
  }

  // ---- Rendering ---------------------------------------------------------
  function renderQuestion() {
    el.qa.textContent = current.a;
    el.qb.textContent = current.b;
    replay(el.question, 'enter');
  }

  function renderAnswer() {
    el.answer.textContent = typed;
  }

  function updateHud() {
    const elapsed = (performance.now() - startedAt) / 1000;
    if (MODE === 'time') {
      const remaining = Math.max(0, TARGET - elapsed);
      el.label.textContent = fmt(Math.ceil(remaining));
      el.label.classList.toggle('urgent', remaining <= 10);
      el.fill.style.width = `${(remaining / TARGET) * 100}%`;
    } else {
      el.label.textContent = `${Math.min(answered + 1, TARGET)} / ${TARGET} · ${fmt(Math.floor(elapsed))}`;
      el.fill.style.width = `${(answered / TARGET) * 100}%`;
    }
  }

  function showFeedback(ok, q) {
    el.feedback.className = `feedback ${ok ? 'good' : 'bad'}`;
    el.feedback.textContent = ok ? '✓ Correct' : `✗ ${q.a} × ${q.b} = ${q.answer}`;
    replay(el.stage, ok ? 'flash-good' : 'flash-bad');
  }

  // ---- Input -------------------------------------------------------------
  function press(digit) {
    if (!running || typed.length >= MAX_DIGITS) return;
    if (typed === '' && digit === '0') return;     // no answer starts with 0
    typed += digit;
    renderAnswer();
  }

  function backspace() {
    if (!running || !typed) return;
    typed = typed.slice(0, -1);
    renderAnswer();
  }

  function submit() {
    if (!running || typed === '') return;
    const given = parseInt(typed, 10);
    const ok = given === current.answer;
    answered++;
    if (ok) correct++;
    else mistakes.push([current.a, current.b, given]);

    showFeedback(ok, current);
    el.score.textContent = correct;
    typed = '';
    renderAnswer();

    if (MODE === 'count' && answered >= TARGET) {
      finish();
      return;
    }
    last = current;
    current = drawQuestion();
    renderQuestion();
    updateHud();
  }

  document.addEventListener('keydown', (e) => {
    if (!running || e.ctrlKey || e.metaKey || e.altKey) return;
    if (/^[0-9]$/.test(e.key)) {
      press(e.key);
    } else if (e.key === 'Backspace') {
      e.preventDefault();
      backspace();
    } else if (e.key === 'Enter') {
      e.preventDefault();                          // don't re-trigger a focused keypad button
      submit();
    }
  });

  el.keypad.addEventListener('mousedown', (e) => e.preventDefault());   // keep focus off the keys
  el.keypad.addEventListener('click', (e) => {
    const btn = e.target.closest('[data-key]');
    if (!btn) return;
    const key = btn.dataset.key;
    if (key === 'back') backspace();
    else if (key === 'go') submit();
    else press(key);
  });

  // ---- Run lifecycle -----------------------------------------------------
  function tick() {
    updateHud();
    if (MODE === 'time' && (performance.now() - startedAt) / 1000 >= TARGET) finish();
  }

  function start() {
    running = true;
    startedAt = performance.now();
    current = drawQuestion();
    renderQuestion();
    renderAnswer();
    updateHud();
    timerId = setInterval(tick, 100);
  }

  function runCountdown(done) {
    const steps = ['3', '2', '1', 'Go!'];
    let i = 0;
    (function next() {
      if (i >= steps.length) {
        el.countdown.hidden = true;
        done();
        return;
      }
      el.countNum.textContent = steps[i];
      replay(el.countNum, 'tick');
      const delay = i === steps.length - 1 ? 450 : 700;
      i++;
      setTimeout(next, delay);
    })();
  }

  function finish() {
    if (!running) return;
    running = false;
    clearInterval(timerId);
    let duration = (performance.now() - startedAt) / 1000;
    if (MODE === 'time') duration = Math.min(duration, TARGET);
    duration = Math.max(0.1, Math.round(duration * 10) / 10);

    root.classList.add('is-finished');
    renderResults(duration);
    saveScore(duration);
  }

  // ---- Results -----------------------------------------------------------
  function setText(id, text) { $(id).textContent = text; }

  function renderResults(duration) {
    const accuracy = answered ? Math.round((correct / answered) * 100) : 0;
    const pace = answered ? (duration / answered).toFixed(1) : '–';

    setText('res-title',
      !answered ? "Time's up!" : accuracy >= 90 ? 'Brilliant!' : accuracy >= 70 ? 'Great work!' : 'Good effort!');

    if (MODE === 'count') {
      setText('res-big', `${correct}/${TARGET}`);
      setText('res-sub', 'correct');
      setText('stat-1-val', `${accuracy}%`);       setText('stat-1-label', 'Accuracy');
      setText('stat-2-val', fmt(Math.round(duration))); setText('stat-2-label', 'Time');
      setText('stat-3-val', `${pace}s`);           setText('stat-3-label', 'Per answer');
    } else {
      setText('res-big', String(correct));
      setText('res-sub', `correct in ${TARGET} seconds`);
      setText('stat-1-val', `${accuracy}%`);       setText('stat-1-label', 'Accuracy');
      setText('stat-2-val', String(answered));     setText('stat-2-label', 'Answered');
      setText('stat-3-val', `${pace}s`);           setText('stat-3-label', 'Per answer');
    }

    if (mistakes.length) {
      const list = $('mistakes-list');
      const seen = new Set();
      mistakes.forEach(([a, b, given]) => {
        const key = `${Math.min(a, b)}x${Math.max(a, b)}`;
        if (seen.has(key)) return;
        seen.add(key);
        const li = document.createElement('li');
        const fact = document.createElement('span');
        fact.textContent = `${a} × ${b} = ${a * b}`;
        const said = document.createElement('span');
        said.className = 'muted';
        said.textContent = `you said ${given}`;
        li.append(fact, said);
        list.append(li);
      });
      $('mistakes').hidden = false;
    }

    $('results').hidden = false;
  }

  function showNote(text, cls) {
    const note = $('pb-note');
    note.textContent = text;
    note.className = `pb-note ${cls || ''}`.trim();
    note.hidden = false;
  }

  function describeBest(best) {
    return MODE === 'count'
      ? `${best.correct}/${best.total} in ${fmt(Math.round(best.duration))}`
      : `${best.correct} correct`;
  }

  async function saveScore(duration) {
    if (!answered) return;
    const payload = {
      mode: MODE,
      target: TARGET,
      tables: TABLES,
      correct,
      total: answered,
      duration,
      mistakes,
    };
    try {
      const res = await fetch(SAVE_URL, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', 'X-CSRF-Token': CSRF },
        body: JSON.stringify(payload),
      });
      if (res.status === 401) {
        showNote("You've been signed out, so this score wasn't saved.", 'warn');
        return;
      }
      if (res.status === 400) {
        showNote("That score looked unusual, so it wasn't saved.", 'warn');
        return;
      }
      if (!res.ok) throw new Error('save failed');
      const data = await res.json();
      if (!data.saved) return;
      if (data.new_best) showNote('New personal best!', 'pb');
      else if (data.previous_best) showNote(`Your best with these settings: ${describeBest(data.previous_best)}`);
      else showNote('First score with these settings. Now try to beat it!');
    } catch (_) {
      showNote("Couldn't save this score. Check your connection.", 'warn');
    }
  }

  // ---- Go ----------------------------------------------------------------
  el.fill.style.width = MODE === 'time' ? '100%' : '0%';
  runCountdown(start);
})();
