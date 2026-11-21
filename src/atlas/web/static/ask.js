// Ask Atlas: streams /api/ask and shows one step at a time as a single shimmering line.
(() => {
  const $ = (s, el = document) => el.querySelector(s);
  const esc = (t) => String(t ?? '').replace(/[&<>"']/g, c => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[c]));
  const icon = (id, cls = 'ic') => `<svg class="${cls}" viewBox="0 0 24 24"><use href="#i-${id}"/></svg>`;
  // Inline (not <use>) so the strokes can be animated while a step runs.
  const MARK = `<svg class="trace-icon" viewBox="0 0 24 24" aria-hidden="true"><path class="f f1" d="M3 6c6.5 0 7 6 12 6"/>
    <path class="f f2" d="M3 12h18"/><path class="f f3" d="M3 18c6.5 0 7-6 12-6"/></svg>`;

  // What the line says while each step runs.
  const STEPS = [
    ['trigger', 'Reading the question'],
    ['normalise', 'Normalising the wording'],
    ['agents', 'Sending field agents to live sources'],
    ['registry', 'Checking the source registry'],
    ['search', 'Searching the archive'],
    ['sources', 'Gathering matches by source'],
    ['rank', 'Ranking and removing duplicates'],
    ['evidence', 'Verifying archived evidence'],
    ['classify', 'Reading threat labels'],
    ['spread', 'Measuring how far it spread'],
    ['brief', 'Writing the brief'],
  ];
  const MIN_STEP_MS = 1100;   // slow enough to read each line
  const sleep = (ms) => new Promise(r => setTimeout(r, ms));

  // ---------------------------------------------------------------- greeting + composer
  const h = new Date().getHours();
  $('#greet').textContent = h < 5 ? 'Working late' : h < 12 ? 'Good morning' : h < 18 ? 'Good afternoon' : 'Good evening';
  const form = $('#composer'), ta = $('#q'), send = $('#send'), thread = $('#thread');
  const grow = () => { ta.style.height = 'auto'; ta.style.height = Math.min(ta.scrollHeight, 220) + 'px'; send.classList.toggle('ready', !!ta.value.trim()); };
  ta.addEventListener('input', grow);
  ta.addEventListener('keydown', e => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); form.requestSubmit(); } });
  for (const id of ['window', 'lang']) {
    const sel = $('#' + id);
    sel.addEventListener('change', () => $('#chip-' + id).classList.toggle('set', !!sel.value));
  }
  document.querySelectorAll('#suggest button').forEach(b => b.addEventListener('click', () => {
    ta.value = b.dataset.q; $('#window').value = b.dataset.window || '';
    $('#window').dispatchEvent(new Event('change')); grow(); form.requestSubmit();
  }));
  let busy = false;
  form.addEventListener('submit', e => {
    e.preventDefault();
    const q = ta.value.trim();
    if (!q || busy) return;
    ta.value = '';
    ask(q, $('#window').value, $('#lang').value, $('#cite').checked, $('#fresh')?.checked);
    grow();
  });
  // Arriving from the Agents page ("Ask Atlas about …"): ask straight away.
  const preset = new URLSearchParams(location.search).get('q');
  if (preset) { history.replaceState(null, '', location.pathname); ta.value = preset; grow(); setTimeout(() => form.requestSubmit(), 0); }  // after Trace is defined
  ta.focus({preventScroll: true});

  // ---------------------------------------------------------------- one turn
  async function ask(q, windowName, lang, cite, fresh = false) {
    busy = true;
    document.body.classList.add('threaded');
    const turn = document.createElement('article');
    turn.className = 'turn';
    const filt = [windowName, lang].filter(Boolean).join(' · ');
    turn.innerHTML = `
      <div class="q-bubble">${esc(q)}</div><div class="q-meta">${filt ? esc(filt) : 'All windows · all languages'}${fresh ? ' · field agents sent' : ''}</div>
      <div class="trace running">
        <button type="button" class="trace-head" aria-expanded="false" disabled>${MARK}
          <span class="trace-stage"></span><span class="trace-time"></span>${icon('chev', 'trace-chev')}</button>
        <ol class="trace-log"></ol>
      </div>
      <div class="answer"></div>`;
    thread.appendChild(turn);
    turn.scrollIntoView({behavior: 'smooth', block: 'start'});
    const trace = new Trace(turn, fresh);

    const queue = []; let streamDone = false, wake = null;
    const push = (ev) => { queue.push(ev); if (wake) { wake(); wake = null; } };
    const reader = (async () => {
      try {
        const r = await fetch('/api/ask', {method: 'POST', headers: {'Content-Type': 'application/json'},
          body: JSON.stringify({q, window: windowName, lang, fresh})});
        if (!r.ok || !r.body) throw new Error(`Server answered ${r.status}`);
        const rd = r.body.getReader(), dec = new TextDecoder(); let buf = '';
        for (;;) {
          const {value, done} = await rd.read();
          if (done) break;
          buf += dec.decode(value, {stream: true});
          let i; while ((i = buf.indexOf('\n')) >= 0) { const line = buf.slice(0, i).trim(); buf = buf.slice(i + 1); if (line) push(JSON.parse(line)); }
        }
      } catch (err) { push({type: 'error', message: err.message}); }
      streamDone = true; push(null);
    })();

    trace.start(STEPS[0][0]);
    for (;;) {
      if (!queue.length) { if (streamDone) break; await new Promise(r => (wake = r)); continue; }
      const ev = queue.shift();
      if (!ev) continue;
      if (ev.type === 'step') {
        await trace.step(ev);
      } else if (ev.type === 'answer') {
        await trace.end(ev.ms);
        renderAnswer(turn, ev, cite, () => ask(q, windowName, lang, cite, true));
      } else if (ev.type === 'error') {
        await trace.end(null, true);
        $('.answer', turn).innerHTML = `<div class="err-card">Atlas could not finish: ${esc(ev.message)}</div>`;
      }
    }
    await reader;
    busy = false;
    ta.focus();
  }

  // Field agents: report what they brought back, or offer to send them for newer reports.
  function agentsBlock(a) {
    const g = a.agents;
    if (!g || !g.topic) return '';
    const open = `<a class="ag-ask-link" href="/agents?topic=${encodeURIComponent(g.topic)}">Choose sources on the Agents page →</a>`;
    if (g.sent) return `<div class="ag-ask" style="--i:${a.bullets.length + 1}"><span class="ag-code m-wp-search">AGT</span>
      <p><b>${g.kept ? `Field agents brought back ${g.kept} new item${g.kept === 1 ? '' : 's'}` : 'Field agents found nothing newer'}</b>
      ${g.kept ? 'and they are included above.' : 'than what was already archived.'}</p>${open}</div>`;
    return `<div class="ag-ask" style="--i:${a.bullets.length + 1}"><span class="ag-code m-wp-search">AGT</span>
      <p><b>Want newer reports?</b> Send agents to the live news and official sources, then answer again.</p>
      <button type="button" class="ag-btn ag-ask-go">Send agents</button>${open}</div>`;
  }

  function renderAnswer(turn, a, cite, resend) {
    const cards = (cite && a.citations.length) ? `<div class="cites-h" style="--i:${a.bullets.length + 1}">Sources · ${a.citations.length}</div>
      <div class="cites" style="--i:${a.bullets.length + 2}">${
      a.citations.map(c => `<a class="cite" href="/signals/${encodeURIComponent(c.id)}">
        <div class="top"><span class="src">${esc(c.source)}</span><span class="n">${c.n}</span></div>
        <div class="t">${esc(c.title)}</div><div class="snip">${esc(c.snippet)}</div>
        <div class="foot"><span class="pill t${c.tier}">Tier ${c.tier}</span><span class="pill idle">${esc(c.date)}</span>
          <span class="pill idle">${esc(c.lang)}</span><span class="pill idle">${esc(c.window)}</span></div></a>`).join('')}</div>` : '';
    $('.answer', turn).innerHTML = `<h3>${esc(a.headline)}</h3>
      ${a.bullets.length ? `<ul style="--i:1">${a.bullets.map(b => `<li>${esc(b)}</li>`).join('')}</ul>` : ''}${agentsBlock(a)}${cards}`;
    const go = $('.ag-ask-go', turn);
    if (go) go.addEventListener('click', () => { if (!busy) { go.disabled = true; resend(); } });
  }

  // ---------------------------------------------------------------- the trace
  class Trace {
    constructor(turn, fresh = false) {
      this.fresh = fresh;
      this.root = $('.trace', turn); this.head = $('.trace-head', turn); this.stage = $('.trace-stage', turn);
      this.time = $('.trace-time', turn); this.log = $('.trace-log', turn);
      this.n = 0; this.t0 = performance.now(); this.since = 0;
      this.head.addEventListener('click', () => {
        const open = this.root.classList.toggle('open');
        this.head.setAttribute('aria-expanded', open);
      });
    }
    // Swap the visible line: the old one drifts up and fades, the new one rises in.
    say(text, shimmer = true) {
      const old = this.stage.querySelector('.trace-line:not(.leave)');
      if (old) { old.classList.remove('enter', 'after'); old.classList.add('leave'); old.addEventListener('animationend', () => old.remove(), {once: true}); setTimeout(() => old.remove(), 600); }
      const el = document.createElement('span');
      el.className = 'trace-line enter' + (old ? ' after' : '') + (shimmer ? ' shimmer' : '');
      el.textContent = text;
      this.stage.appendChild(el);
    }
    start(id) {
      const s = STEPS.find(x => x[0] === id);
      this.since = performance.now();
      this.say((s ? s[1] : 'Working') + '…');
    }
    async step(ev) {
      const wait = MIN_STEP_MS - (performance.now() - this.since);
      if (wait > 0) await sleep(wait);
      this.n++;
      this.addLog(ev);
      const i = STEPS.findIndex(x => x[0] === ev.id);
      let next = STEPS[i + 1];
      if (next && next[0] === 'agents' && !this.fresh) next = STEPS[i + 2];   // agents only run when asked
      if (next && ev.status !== 'error') this.start(next[0]);
    }
    async end(ms, failed) {
      const wait = MIN_STEP_MS * 0.6 - (performance.now() - this.since);
      if (wait > 0) await sleep(wait);
      this.root.classList.remove('running');
      this.root.classList.add('done');
      this.head.disabled = false;
      const secs = ((ms ?? (performance.now() - this.t0)) / 1000).toFixed(2);
      this.say(failed ? 'Stopped with an error' : `Worked through ${this.n} step${this.n === 1 ? '' : 's'}`, false);
      if (!failed) this.time.textContent = `${secs}s`;
    }
    addLog(d) {
      const li = document.createElement('li');
      li.className = `st ${d.status}`;
      const rows = (d.rows || []).map(([k, v]) => `<div>${esc(k)}</div><div>${esc(v)}</div>`).join('');
      const table = d.table ? `<div class="scroll"><table><tr>${d.table.cols.map(c => `<th>${esc(c)}</th>`).join('')}</tr>${
        d.table.rows.map(r => `<tr>${r.map(c => `<td>${esc(c)}</td>`).join('')}</tr>`).join('')}</table></div>` : '';
      li.innerHTML = `<button type="button"><span class="st-t">${esc(d.title)}</span><span class="st-s">${esc(d.summary || '')}</span>
        <span class="st-ms">${d.ms} ms</span></button><div class="st-detail">${rows ? `<div class="kv">${rows}</div>` : ''}${table}</div>`;
      $('button', li).addEventListener('click', () => li.classList.toggle('open'));
      this.log.appendChild(li);
    }
  }
})();
