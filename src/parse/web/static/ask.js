// Ask Parse copilot: streams /api/ask, shows each step as a large card while it works, then draws the whole run
// as a draggable step map. Every node opens an inspector with the sources it touched, where a model was involved,
// and links to the Parse pages that go deeper.
(() => {
  const $ = (s, el = document) => el.querySelector(s);
  const $$ = (s, el = document) => [...el.querySelectorAll(s)];
  const esc = (t) => String(t ?? '').replace(/[&<>"']/g, c => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[c]));
  const icon = (id, cls = 'ic') => `<svg class="${cls}" viewBox="0 0 24 24"><use href="#i-${id}"/></svg>`;
  const sleep = (ms) => new Promise(r => setTimeout(r, ms));
  const REDUCED = matchMedia('(prefers-reduced-motion: reduce)').matches;
  // Inline (not <use>) so the strokes can be animated while a step runs.
  const MARK = `<svg class="cot-mark" viewBox="0 0 24 24" aria-hidden="true"><path class="f f1" d="M3 6c6.5 0 7 6 12 6"/>
    <path class="f f2" d="M3 12h18"/><path class="f f3" d="M3 18c6.5 0 7-6 12-6"/></svg>`;

  // Step glyphs (24px, stroked).
  const GLYPH = {
    bolt: 'M13 2 4 14h7l-1 8 9-12h-7z',
    type: 'M4 7V4h16v3M9 20h6M12 4v16',
    send: 'M3 11 21 3l-7 18-3-7z',
    book: 'M5 4h11a3 3 0 0 1 3 3v13H8a3 3 0 0 1-3-3zM5 17a3 3 0 0 1 3-3h11',
    database: 'M4 6c0-1.7 3.6-3 8-3s8 1.3 8 3-3.6 3-8 3-8-1.3-8-3zM4 6v12c0 1.7 3.6 3 8 3s8-1.3 8-3V6M4 12c0 1.7 3.6 3 8 3s8-1.3 8-3',
    globe: 'M12 3a9 9 0 1 0 0 18 9 9 0 0 0 0-18zM3 12h18M12 3c2.4 2.6 3.6 5.6 3.6 9s-1.2 6.4-3.6 9c-2.4-2.6-3.6-5.6-3.6-9S9.6 5.6 12 3z',
    sort: 'M7 4v16M3 8l4-4 4 4M17 20V4M13 16l4 4 4-4',
    lock: 'M6 11h12v10H6zM8 11V8a4 4 0 0 1 8 0v3',
    spark: 'M12 3v5M12 16v5M3 12h5M16 12h5M6 6l3 3M15 15l3 3M6 18l3-3M15 9l3-3',
    branch: 'M6 3v18M6 13h5a7 7 0 0 0 7-7V3',
    file: 'M6 3h8l4 4v14H6zM14 3v4h4M9 12h6M9 16h6',
    chip: 'M7 7h10v10H7zM10 3v4M14 3v4M10 17v4M14 17v4M3 10h4M3 14h4M17 10h4M17 14h4',
    check: 'M4 12.5 9 17.5 20 6.5',
  };
  const glyph = (k, cls = 'gi') => `<svg class="${cls}" viewBox="0 0 24 24" aria-hidden="true"><path d="${GLYPH[k] || GLYPH.file}"/></svg>`;
  const ICON_OF = {trigger: 'bolt', normalise: 'type', agents: 'send', registry: 'book', search: 'database', sources: 'globe',
                   rank: 'sort', evidence: 'lock', classify: 'spark', spread: 'branch', brief: 'file'};

  // Per step: the line shown while it runs, and the micro-thoughts that tick past.
  const STEPS = {
    trigger:   ['Reading the question', ['Parsing the question', 'Noting window and language filters']],
    normalise: ['Normalising the wording', ['Folding Cyrillic to Latin', 'Matching č ć · š · ž · ë · đ variants', 'Dropping filler words in SQ · SR · EN']],
    agents:    ['Sending field agents to live sources', ['Dispatching agents to news and official sites', 'Reading site search APIs and RSS feeds', 'Archiving new pages with SHA-256']],
    registry:  ['Checking the source registry', ['Loading the source allow-list', 'Grouping sources by tier']],
    search:    ['Searching the archive', ['Compiling diacritic-aware patterns', 'Scanning titles and full text', 'Counting exact matches']],
    sources:   ['Gathering matches by source', ['Grouping matches by outlet', 'Looking up tier and platform']],
    rank:      ['Ranking and removing duplicates', ['Scoring title and body hits', 'Boosting the busiest window', 'Capping two items per outlet']],
    evidence:  ['Verifying archived evidence', ['Opening archived pages', 'Recomputing SHA-256 fingerprints']],
    classify:  ['Reading threat labels', ['Looking for T1–T10 and N1–N11 labels', 'Checking which model wrote them']],
    spread:    ['Measuring how far it spread', ['Counting independent outlets', 'Weighing source tiers']],
    brief:     ['Writing the brief', ['Dating the first report', 'Finding the busiest day', 'Attaching citations']],
  };
  const ORDER = Object.keys(STEPS);
  const MIN_STEP_MS = 950;    // slow enough to read each card
  const AI_TEXT = {used: 'AI used', available: 'AI stage · not run', none: 'No model'};
  const pad = (n) => String(n).padStart(2, '0');
  // Links come from the archive: only same-site paths and http(s) pages are clickable.
  const safe = (href) => /^(\/(?!\/)|https?:\/\/)/i.test(String(href || '')) ? href : '#';
  const ext = (href) => /^https?:/i.test(href) ? ' target="_blank" rel="noopener noreferrer"' : '';

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
  $$('#suggest button').forEach(b => b.addEventListener('click', () => {
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
  // Arriving from another page ("Ask Parse about …"): ask straight away.
  const preset = new URLSearchParams(location.search).get('q');
  if (preset) { history.replaceState(null, '', location.pathname); ta.value = preset; grow(); setTimeout(() => form.requestSubmit(), 0); }
  ta.focus({preventScroll: true});

  // ---------------------------------------------------------------- shared detail renderers
  const aiBox = (ai) => !ai ? '' : `<div class="ai-box ${ai.state}">${glyph(ai.state === 'none' ? 'check' : 'chip')}
    <div><b>${AI_TEXT[ai.state] || esc(ai.state)}${ai.model ? ` · <span class="mono">${esc(ai.model)}</span>` : ''}</b><p>${esc(ai.what)}</p></div></div>`;
  const kvHTML = (rows) => rows && rows.length ? `<div class="kv">${rows.map(([k, v]) => `<div>${esc(k)}</div><div>${esc(v)}</div>`).join('')}</div>` : '';
  const tableHTML = (t) => t ? `<div class="scroll"><table><tr>${t.cols.map(c => `<th>${esc(c)}</th>`).join('')}</tr>${
    t.rows.map(r => `<tr>${r.map(c => `<td>${esc(c)}</td>`).join('')}</tr>`).join('')}</table></div>` : '';
  const itemsHTML = (items, head = 'Records') => items && items.length ? `<div class="d-h">${esc(head)} · ${items.length}</div>
    <div class="items">${items.map(it => `<a class="it ${esc(it.state || '')}" href="${esc(safe(it.href))}"${ext(it.href)}>
      <span class="it-t">${esc(it.title)}</span><span class="it-s">${esc(it.sub || '')}</span>${it.tag ? `<span class="it-tag">${esc(it.tag)}</span>` : ''}</a>`).join('')}</div>` : '';
  const linksHTML = (links) => links && links.length ? `<div class="d-links">${links.map(l =>
    `<a class="d-link" href="${esc(safe(l.href))}"${ext(l.href)}>${esc(l.label)} ${icon('ne', 'ic sm')}</a>`).join('')}</div>` : '';
  const initials = (name) => (String(name).split(/[\s\-_.()]+/).filter(w => /^[\p{L}\p{N}]/u.test(w)).slice(0, 2).map(w => w[0]).join('') || String(name).slice(0, 2)).toUpperCase();
  // Which sources made it into the answer, and why the others did not.
  const pickRow = (x) => `<a class="pk ${x.picked ? 'in' : 'out'}" href="${esc(safe(x.href))}">
      <span class="pk-i">${esc(initials(x.name))}</span>
      <span class="pk-n"><b>${esc(x.name)}</b><span class="pill t${x.tier}">T${x.tier}</span></span>
      <span class="pk-c">${x.picked ? `${x.picked} of ${x.matched}` : `0 of ${x.matched}`}</span>
      <span class="pk-w">${esc(x.why)}</span></a>`;
  const picksHTML = (p, open = false) => !p || !p.picked ? '' : `<div class="picks">
      <div class="d-h">Picked · ${p.picked.length} of ${p.considered} sources · cut-off ${p.cutoff} pts</div>
      <div class="pk-list">${p.picked.map(pickRow).join('')}</div>
      ${p.skipped.length ? `<details class="pk-more"${open ? ' open' : ''}><summary>Matched but left out · ${p.skipped.length}</summary>
        <div class="pk-list">${p.skipped.slice(0, 40).map(pickRow).join('')}</div>
        ${p.skipped.length > 40 ? `<p class="pk-note">and ${p.skipped.length - 40} more, each below the cut-off.</p>` : ''}</details>` : ''}</div>`;
  const stepDetail = (d) => `${aiBox(d.ai)}${picksHTML(d.picks)}${kvHTML(d.rows)}${tableHTML(d.table)}${itemsHTML(d.items)}${linksHTML(d.links)}`;

  // Text that writes itself in, so a finished step reads as freshly generated.
  function typeInto(el, text, maxMs = 520) {
    if (REDUCED || !text) { el.textContent = text || ''; return; }
    el.textContent = ''; el.classList.add('typing');
    const per = Math.max(1, Math.ceil(text.length / (maxMs / 16)));
    let i = 0;
    const tick = () => { i = Math.min(text.length, i + per); el.textContent = text.slice(0, i);
      if (i < text.length) requestAnimationFrame(tick); else el.classList.remove('typing'); };
    requestAnimationFrame(tick);
  }

  // ---------------------------------------------------------------- one turn
  async function ask(q, windowName, lang, cite, fresh = false) {
    busy = true;
    document.body.classList.add('threaded');
    const turn = document.createElement('article');
    turn.className = 'turn';
    const filt = [windowName, lang].filter(Boolean).join(' · ');
    turn.innerHTML = `
      <div class="q-bubble">${esc(q)}</div><div class="q-meta">${filt ? esc(filt) : 'All windows · all languages'}${fresh ? ' · field agents sent' : ''}</div>
      <section class="cot running" aria-label="Parse reasoning">
        <button type="button" class="cot-head" aria-expanded="true" disabled>${MARK}
          <span class="cot-stage"><span class="cot-line shimmer">Parse is working…</span></span>
          <span class="cot-count"></span><span class="cot-time">0.0s</span>${icon('chev', 'ic cot-chev')}</button>
        <div class="cot-bar" aria-hidden="true"><i></i></div>
        <ol class="cot-steps"></ol>
      </section>
      <div class="answer"></div>
      <section class="fmap" hidden aria-label="Step map"></section>`;
    thread.appendChild(turn);
    turn.scrollIntoView({behavior: 'smooth', block: 'start'});
    const cop = new Copilot(turn, fresh);
    let answer = null;

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

    cop.begin(ORDER[0]);
    for (;;) {
      if (!queue.length) { if (streamDone) break; await new Promise(r => (wake = r)); continue; }
      const ev = queue.shift();
      if (!ev) continue;
      if (ev.type === 'step') {
        await cop.step(ev);
      } else if (ev.type === 'answer') {
        answer = ev;
        await cop.end(ev.ms);
        renderAnswer(turn, ev, cite, () => ask(q, windowName, lang, cite, true));
      } else if (ev.type === 'error') {
        await cop.end(null, ev.message);
        $('.answer', turn).innerHTML = `<div class="err-card">Parse could not finish: ${esc(ev.message)}</div>`;
      }
    }
    await reader;
    if (!cop.ended) await cop.end(null, 'The stream closed before an answer arrived.');
    if (cop.steps.length) cop.map = new FlowMap($('.fmap', turn), cop, answer, q);
    busy = false;
    ta.focus({preventScroll: true});
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
    const picked = a.sources && a.sources.picked.length ? `<section class="ans-picks" style="--i:${a.bullets.length + 1}">
      <div class="cites-h">Sources Parse picked · ${a.sources.picked.length} of ${a.sources.considered}</div>
      <p class="pk-lead">Every matching source was ranked by how strongly its items match the question. These made the answer; open “left out” to see the rest and why.</p>
      ${picksHTML(a.sources)}</section>` : '';
    const cards = (cite && a.citations.length) ? `<div class="cites-h" style="--i:${a.bullets.length + 1}">Cited items · ${a.citations.length}</div>
      <div class="cites" style="--i:${a.bullets.length + 2}">${
      a.citations.map(c => `<a class="cite" href="/signals/${encodeURIComponent(c.id)}">
        <div class="top"><span class="src">${esc(c.source)}</span><span class="n">${c.n}</span></div>
        <div class="t">${esc(c.title)}</div><div class="snip">${esc(c.snippet)}</div>
        <div class="foot"><span class="pill t${c.tier}">Tier ${c.tier}</span><span class="pill idle">${esc(c.date)}</span>
          <span class="pill idle">${esc(c.lang)}</span><span class="pill idle">${esc(c.window)}</span></div></a>`).join('')}</div>` : '';
    $('.answer', turn).innerHTML = `<h3>${esc(a.headline)}</h3>
      ${a.bullets.length ? `<ul style="--i:1">${a.bullets.map(b => `<li>${esc(b)}</li>`).join('')}</ul>` : ''}${
      a.citations?.length ? `<p class="trace-cta" style="--i:1"><a href="/trace?signal=${encodeURIComponent(a.citations[0].id)}">Trace where this story started and who carried it →</a></p>` : ''}${agentsBlock(a)}${picked}${cards}`;
    const go = $('.ag-ask-go', turn);
    if (go) go.addEventListener('click', () => { if (!busy) { go.disabled = true; resend(); } });
  }

  // ---------------------------------------------------------------- the copilot: one big card per step
  class Copilot {
    constructor(turn, fresh) {
      this.fresh = fresh;
      this.root = $('.cot', turn); this.head = $('.cot-head', turn); this.stage = $('.cot-stage', turn);
      this.count = $('.cot-count', turn); this.time = $('.cot-time', turn); this.bar = $('.cot-bar i', turn);
      this.list = $('.cot-steps', turn);
      this.total = ORDER.length - (fresh ? 0 : 1);
      this.steps = []; this.pending = null; this.since = 0; this.t0 = performance.now(); this.map = null; this.ended = false;
      this.clock = setInterval(() => { this.time.textContent = ((performance.now() - this.t0) / 1000).toFixed(1) + 's'; }, 100);
      this.head.addEventListener('click', () => {
        const full = this.root.classList.toggle('expanded');
        this.head.setAttribute('aria-expanded', full);
      });
    }
    say(text, shimmer = true) {
      const old = $('.cot-line:not(.leave)', this.stage);
      if (old) { old.classList.add('leave'); setTimeout(() => old.remove(), 380); }
      const el = document.createElement('span');
      el.className = 'cot-line enter' + (shimmer ? ' shimmer' : '');
      el.textContent = text;
      this.stage.appendChild(el);
    }
    progress() {
      const n = this.steps.length;
      this.count.textContent = `${pad(Math.min(n + 1, this.total))} / ${pad(this.total)}`;
      this.bar.style.width = `${Math.min(100, (n / this.total) * 100)}%`;
    }
    // A pending card: the step is running. Its title shimmers and its micro-thoughts tick past.
    begin(id) {
      const s = STEPS[id] || ['Working', ['Working']];
      this.since = performance.now();
      this.say(`${s[0]}…`);
      this.progress();
      const li = document.createElement('li');
      li.className = 'cs pending';
      li.dataset.id = id;
      li.innerHTML = `<div class="cs-node"><span>${pad(this.steps.length + 1)}</span></div>
        <div class="cs-card"><div class="cs-scan" aria-hidden="true"></div>
          <div class="cs-top"><span class="cs-ic">${glyph(ICON_OF[id])}</span><b class="cs-t shimmer">${esc(s[0])}</b>
            <span class="cs-dots" aria-hidden="true"><i></i><i></i><i></i></span></div>
          <div class="cs-think"></div></div>`;
      this.list.appendChild(li);
      const think = $('.cs-think', li);
      let k = 0;
      const next = () => {
        const line = document.createElement('div');
        line.className = 'th';
        line.innerHTML = `<span class="th-k">›</span><span class="th-t"></span>`;
        think.appendChild(line);
        typeInto($('.th-t', line), s[1][k % s[1].length], 260);
        while (think.children.length > 3) think.firstElementChild.remove();
        k++;
      };
      next();
      li._timer = setInterval(next, 620);
      this.pending = li;
      if (this.list.children.length > 1) li.scrollIntoView({behavior: REDUCED ? 'auto' : 'smooth', block: 'nearest'});
    }
    async step(ev) {
      const wait = MIN_STEP_MS - (performance.now() - this.since);
      if (wait > 0) await sleep(wait);
      let li = this.pending;
      if (!li || li.dataset.id !== ev.id) {   // a step arrived that we did not predict: replace the guess
        if (li) { clearInterval(li._timer); li.remove(); }
        this.begin(ev.id); li = this.pending;
      }
      clearInterval(li._timer);
      this.pending = null;
      this.steps.push(ev);
      this.fill(li, ev);
      const i = ORDER.indexOf(ev.id);
      let next = ORDER[i + 1];
      if (next === 'agents' && !this.fresh) next = ORDER[i + 2];   // agents only run when asked
      if (next && ev.status !== 'error') this.begin(next);
      else this.progress();
    }
    fill(li, d) {
      const n = this.steps.length;
      const ai = d.ai || {state: 'none'};
      li.className = `cs done ${d.status} ai-${ai.state}`;
      const chips = d.picks
        ? d.picks.picked.map(x => `<span class="chip-src picked"><i>${esc(initials(x.name))}</i>${esc(x.name)}<em>T${x.tier} · ${x.picked} picked</em></span>`).join('')
        : (d.branches || []).map(b => `<span class="chip-src"><i>${esc(b.initials)}</i>${esc(b.name)}<em>T${b.tier} · ${b.count}</em></span>`).join('');
      li.innerHTML = `<div class="cs-node"><span>${pad(n)}</span></div>
        <div class="cs-card">
          <button type="button" class="cs-top" aria-expanded="false">
            <span class="cs-ic">${glyph(ICON_OF[d.id])}</span><b class="cs-t">${esc(d.title)}</b>
            <span class="cs-sub">${esc(d.subtitle || '')}</span>
            <span class="ai-tag ${ai.state}">${AI_TEXT[ai.state] || ''}</span>
            <span class="cs-ms">${d.ms} ms</span>${icon('chev', 'ic cs-chev')}</button>
          <div class="cs-sum">${esc(d.summary || '')}</div>
          <p class="cs-ex"></p>
          ${chips ? `<div class="cs-chips">${chips}</div>` : ''}
          <div class="cs-detail">${stepDetail(d)}
            <button type="button" class="cs-map" hidden>Show on the step map →</button></div>
        </div>`;
      typeInto($('.cs-ex', li), d.explain || '');
      const top = $('.cs-top', li);
      top.addEventListener('click', () => { const o = li.classList.toggle('open'); top.setAttribute('aria-expanded', o); });
      $('.cs-map', li).addEventListener('click', () => this.map && this.map.focus(d.id, true));
    }
    async end(ms, error) {
      if (this.ended) return;
      this.ended = true;
      const wait = MIN_STEP_MS * 0.6 - (performance.now() - this.since);
      if (wait > 0) await sleep(wait);
      clearInterval(this.clock);
      if (this.pending) {
        clearInterval(this.pending._timer);
        if (error) {
          this.pending.className = 'cs done error';
          $('.cs-think', this.pending).innerHTML = `<div class="th"><span class="th-k">×</span><span class="th-t">${esc(error)}</span></div>`;
          $('.cs-t', this.pending).classList.remove('shimmer');
        } else this.pending.remove();
        this.pending = null;
      }
      this.root.classList.remove('running');
      this.root.classList.add('done');
      this.head.disabled = false;
      this.head.setAttribute('aria-expanded', 'false');
      this.bar.style.width = '100%';
      const used = this.steps.filter(s => s.ai && s.ai.state === 'used').length;
      const idle = this.steps.filter(s => s.ai && s.ai.state === 'available').length;
      const secs = ((ms ?? (performance.now() - this.t0)) / 1000).toFixed(2);
      this.say(error ? 'Stopped with an error' : `Reasoned through ${this.steps.length} steps · ${
        used ? `AI used in ${used}` : 'no model in the answer'}${idle ? ` · ${idle} AI stage not run` : ''}`, false);
      this.count.textContent = '';
      this.time.textContent = error ? '' : `${secs}s`;
      $$('.cs-map', this.list).forEach(b => (b.hidden = false));
    }
    open(id) {
      const li = $(`.cs[data-id="${CSS.escape(id)}"]`, this.list);
      if (!li) return;
      this.root.classList.add('expanded'); this.head.setAttribute('aria-expanded', 'true');
      li.classList.add('open', 'flash'); setTimeout(() => li.classList.remove('flash'), 1400);
      li.scrollIntoView({behavior: 'smooth', block: 'center'});
    }
  }

  // ---------------------------------------------------------------- the step map: pan, zoom, drag, inspect
  const NW = 216, NH = 66, LANE = 268, ROW = 92, SAT_H = 46, SAT_ROW = 56, TOP = 46;
  const LANES = [
    ['intake', 'Intake', ['trigger', 'normalise', 'agents']],
    ['retrieve', 'Retrieve', ['registry', 'search', 'sources']],
    ['src', 'Sources picked', []],
    ['assess', 'Assess', ['rank', 'evidence', 'classify', 'spread']],
    ['answer', 'Answer', ['brief', 'answer']],
    ['cites', 'Cited records', []],
  ];
  const laneOf = (id) => (LANES.find(l => l[2].includes(id)) || LANES[3])[0];

  class FlowMap {
    constructor(root, cop, answer, q) {
      this.root = root; this.cop = cop; this.answer = answer; this.q = q;
      this.nodes = new Map(); this.edges = []; this.k = 1; this.tx = 0; this.ty = 0;
      const used = cop.steps.filter(s => s.ai?.state === 'used').length;
      const idle = cop.steps.filter(s => s.ai?.state === 'available').length;
      this.term = ((cop.steps.find(s => s.id === 'normalise')?.rows || [])[0]?.[1] || '').split(',')[0].trim();
      const pk = cop.steps.find(s => s.id === 'rank')?.picks;
      const nSrc = pk ? `${pk.picked.length} of ${pk.considered} sources picked` : `${(cop.steps.find(s => s.id === 'sources')?.branches || []).length} top sources`;
      root.hidden = false;
      root.innerHTML = `
        <div class="fm-bar">
          <div class="fm-title"><span class="lbl">Step map</span><b>${cop.steps.length} steps · ${nSrc} · ${answer?.citations?.length || 0} cited</b></div>
          <div class="fm-ai ${used ? 'used' : idle ? 'available' : 'none'}">${glyph('chip')}<span>${
            used ? `AI used in ${used} step${used > 1 ? 's' : ''}` : 'No model wrote or labelled this answer'}${idle ? ` · ${idle} AI stage not run` : ''}</span></div>
          <div class="fm-tools">
            <button type="button" class="fm-btn fm-lens" aria-pressed="false" title="Highlight where AI meets the pipeline">${glyph('spark')}AI lens</button>
            <button type="button" class="fm-btn sq" data-z="-1" aria-label="Zoom out">−</button>
            <button type="button" class="fm-btn sq" data-z="1" aria-label="Zoom in">+</button>
            <button type="button" class="fm-btn fm-fit">Fit</button>
            <button type="button" class="fm-btn fm-full" aria-pressed="false">Expand</button>
          </div>
        </div>
        <div class="fm-view">
          <div class="fm-world"><svg class="fm-edges" width="1" height="1"></svg></div>
          <div class="fm-hint">Drag to pan · drag a node to move it · ${/Mac/.test(navigator.platform) ? '⌘' : 'Ctrl'} + scroll to zoom · click a node to inspect</div>
          <aside class="fm-insp" hidden><button type="button" class="fm-x" aria-label="Close inspector">${icon('x', 'ic')}</button><div class="fm-insp-in"></div></aside>
        </div>`;
      this.view = $('.fm-view', root); this.world = $('.fm-world', root); this.svg = $('.fm-edges', root);
      // Focusing a node must not scroll the clipped viewport; the camera is the only thing that moves.
      this.view.addEventListener('scroll', () => { this.view.scrollLeft = 0; this.view.scrollTop = 0; });
      this.insp = $('.fm-insp', root);
      this.build();
      this.bind();
      requestAnimationFrame(() => { this.fit(false); root.classList.add('in'); });
    }

    addNode(id, kind, x, y, data) {
      const el = document.createElement('button');
      el.type = 'button';
      el.className = `fm-node ${kind}`;
      el.dataset.id = id;
      el.style.setProperty('--d', `${this.nodes.size * 45}ms`);
      el.innerHTML = data.html;
      this.world.appendChild(el);
      const n = {id, kind, x, y, w: data.w || NW, h: data.h || NH, el, data};
      el.style.width = n.w + 'px'; el.style.height = n.h + 'px';
      this.nodes.set(id, n);
      this.place(n);
      return n;
    }
    place(n) { n.el.style.transform = `translate(${n.x}px, ${n.y}px)`; }
    edge(a, b, kind = 'main') { if (this.nodes.has(a) && this.nodes.has(b)) this.edges.push({a, b, kind}); }

    build() {
      const steps = this.cop.steps, laneX = {}, laneRow = {}, a = this.answer;
      const picks = steps.find(s => s.id === 'rank')?.picks;
      const br = picks
        ? [...picks.picked.slice(0, 8), ...picks.skipped.slice().sort((x, y) => y.matched - x.matched).slice(0, 3)]
            .map(x => ({...x, count: x.matched, initials: initials(x.name)}))
        : (steps.find(s => s.id === 'sources')?.branches || []);
      const cites = (a?.citations || []).slice(0, 8);
      // Only lanes that hold something, so a short run does not leave empty columns.
      const has = {src: br.length > 0, answer: !!a, cites: cites.length > 0};
      steps.forEach(s => { has[laneOf(s.id)] = true; });
      const lanes = LANES.filter(l => has[l[0]]);
      lanes.forEach(([key, label], i) => {
        laneX[key] = i * LANE; laneRow[key] = 0;
        const h = document.createElement('div');
        h.className = 'fm-lane'; h.style.transform = `translate(${i * LANE}px, 0)`;
        h.innerHTML = `<span>${pad(i + 1)}</span>${label}`;
        this.world.appendChild(h);
      });
      // Pipeline steps
      steps.forEach((s, i) => {
        const lane = laneOf(s.id), r = laneRow[lane]++;
        const st = s.ai?.state || 'none';
        this.addNode(s.id, `step ${s.status} ai-${st}`, laneX[lane], TOP + r * ROW, {step: s, html: `
          <span class="n-ix">${pad(i + 1)}</span>
          <span class="n-ic">${glyph(ICON_OF[s.id])}</span>
          <span class="n-body"><b>${esc(s.title)}</b><small>${esc(s.summary || '')}</small></span>
          <span class="n-ai ${st}" title="${esc(AI_TEXT[st])}">${st === 'none' ? 'RULE' : 'AI'}</span>`});
      });
      for (let i = 0; i < steps.length - 1; i++) this.edge(steps[i].id, steps[i + 1].id);
      // Answer node
      if (a) {
        const r = laneRow.answer++;
        this.addNode('answer', 'final', laneX.answer, TOP + r * ROW, {answer: a, html: `
          <span class="n-ic">${glyph('check')}</span><span class="n-body"><b>Answer</b><small>${esc(a.headline)}</small></span>`});
        this.edge(steps[steps.length - 1].id, 'answer');
      }
      // Sources searched: fan out from "sources", fan in to "rank"
      br.forEach((b, i) => {
        const id = 'src:' + b.id;
        const y = Math.max(TOP, TOP + 2 * ROW + NH / 2 - (br.length * SAT_ROW - (SAT_ROW - SAT_H)) / 2) + i * SAT_ROW;
        const st = b.picked === undefined ? '' : b.picked ? ' picked' : ' left';
        this.addNode(id, `sat src t${b.tier}${st}`, laneX.src + 14, y, {branch: b, w: NW - 28, h: SAT_H, html: `
          <span class="n-init">${esc(b.initials)}</span>
          <span class="n-body"><b>${esc(b.name)}</b><small>${b.picked === undefined ? `Tier ${b.tier} · ${b.count} matches`
            : b.picked ? `T${b.tier} · picked ${b.picked} of ${b.count}` : `T${b.tier} · left out · ${b.count} matches`}</small></span>
          ${st ? `<span class="n-pk">${b.picked ? 'PICKED' : 'OUT'}</span>` : ''}`});
        this.edge('sources', id, b.picked === 0 ? 'fan dead' : 'fan');
        if (b.picked !== 0) this.edge(id, 'rank', 'fan');
      });
      if (br.length && this.nodes.has('rank')) this.edges = this.edges.filter(e => !(e.a === 'sources' && e.b === 'rank'));
      // Cited records
      cites.forEach((c, i) => {
        const id = 'cite:' + c.n;
        this.addNode(id, `sat ref t${c.tier}`, laneX.cites, TOP + i * SAT_ROW, {cite: c, h: SAT_H, html: `
          <span class="n-init">/${c.n}</span><span class="n-body"><b>${esc(c.title)}</b><small>${esc(c.source)} · ${esc(c.date)}</small></span>`});
        this.edge('answer', id, 'fan');
      });
      // AI layer: a band under the pipeline where every model touch point sits
      const maxY = Math.max(...[...this.nodes.values()].map(n => n.y + n.h));
      const bandY = maxY + 76;
      const band = document.createElement('div');
      band.className = 'fm-band';
      band.style.transform = `translate(-24px, ${bandY - 38}px)`;
      band.style.width = (lanes.length * LANE - (LANE - NW) + 48) + 'px';
      const touches = steps.filter(s => s.ai && s.ai.state !== 'none');
      band.innerHTML = `<span class="lbl">AI layer</span><em>${touches.length ? 'Where a model meets the pipeline' : 'No model touched this answer: every step ran on rules, counts and hashes'}</em>`;
      this.world.insertBefore(band, this.world.firstChild);
      const perLane = {};
      touches.forEach(s => {
        const p = this.nodes.get(s.id), lane = laneOf(s.id), j = (perLane[lane] = (perLane[lane] || 0) + 1) - 1;
        const id = 'ai:' + s.id, model = (s.ai.model || 'model').split('/').pop();
        this.addNode(id, `mdl ${s.ai.state}`, p.x, bandY + j * 76, {step: s, ai: s.ai, html: `
          <span class="n-ic">${glyph('chip')}</span><span class="n-body"><b>${esc(model)}</b>
          <small>${s.ai.state === 'used' ? 'Output used in this answer' : 'Stage exists · not run here'}</small></span>`});
        this.edge(s.id, id, `ai ${s.ai.state}`);
      });
      this.draw();
    }

    port(n, side) {
      return side === 'r' ? [n.x + n.w, n.y + n.h / 2] : side === 'l' ? [n.x, n.y + n.h / 2]
        : side === 'b' ? [n.x + n.w / 2, n.y + n.h] : [n.x + n.w / 2, n.y];
    }
    path(A, B) {
      const vertical = Math.abs((A.x + A.w / 2) - (B.x + B.w / 2)) < Math.min(A.w, B.w) * 0.6;
      if (vertical) {
        const down = B.y > A.y;
        const [x1, y1] = this.port(A, down ? 'b' : 't'), [x2, y2] = this.port(B, down ? 't' : 'b');
        const h = Math.max(14, Math.abs(y2 - y1) / 2) * (down ? 1 : -1);
        return `M${x1} ${y1}C${x1} ${y1 + h} ${x2} ${y2 - h} ${x2} ${y2}`;
      }
      const right = B.x > A.x;
      const [x1, y1] = this.port(A, right ? 'r' : 'l'), [x2, y2] = this.port(B, right ? 'l' : 'r');
      const h = Math.max(36, Math.abs(x2 - x1) / 2) * (right ? 1 : -1);
      return `M${x1} ${y1}C${x1 + h} ${y1} ${x2 - h} ${y2} ${x2} ${y2}`;
    }
    draw() {
      this.svg.innerHTML = this.edges.map((e, i) => {
        const d = this.path(this.nodes.get(e.a), this.nodes.get(e.b));
        return `<g class="fm-e ${e.kind}" data-a="${esc(e.a)}" data-b="${esc(e.b)}" style="--d:${i * 45}ms">
          <path class="e-base" d="${d}" pathLength="1"/><path class="e-flow" d="${d}"/></g>`;
      }).join('');
    }
    redrawEdgesOf(id) {
      $$('.fm-e', this.svg).forEach(g => {
        if (g.dataset.a !== id && g.dataset.b !== id) return;
        const d = this.path(this.nodes.get(g.dataset.a), this.nodes.get(g.dataset.b));
        g.querySelectorAll('path').forEach(p => p.setAttribute('d', d));
      });
    }

    // ---- camera
    apply() { this.world.style.transform = `translate(${this.tx}px, ${this.ty}px) scale(${this.k})`; }
    ease() { this.world.classList.add('ease'); clearTimeout(this._e); this._e = setTimeout(() => this.world.classList.remove('ease'), 420); }
    fit(animate = true) {
      const ns = [...this.nodes.values()];
      const x0 = Math.min(...ns.map(n => n.x)) - 30, y0 = -10;
      const x1 = Math.max(...ns.map(n => n.x + n.w)) + 30, y1 = Math.max(...ns.map(n => n.y + n.h)) + 24;
      const vw = this.view.clientWidth, vh = this.view.clientHeight;
      this.k = Math.max(0.3, Math.min(1, (vw - 32) / (x1 - x0), (vh - 56) / (y1 - y0)));
      this.tx = (vw - (x1 - x0) * this.k) / 2 - x0 * this.k;
      this.ty = Math.max(12, (vh - 28 - (y1 - y0) * this.k) / 2) - y0 * this.k;
      if (animate) this.ease();
      this.apply();
    }
    zoomAt(px, py, factor) {
      const k = Math.max(0.25, Math.min(2.2, this.k * factor));
      this.tx = px - (px - this.tx) * (k / this.k); this.ty = py - (py - this.ty) * (k / this.k); this.k = k;
      this.apply();
    }
    focus(id, scroll = false) {
      const n = this.nodes.get(id);
      if (!n) return;
      if (scroll) this.root.scrollIntoView({behavior: 'smooth', block: 'center'});
      this.select(id);
      const side = innerWidth > 760 ? 360 : 0;
      const vw = this.view.clientWidth - side, vh = this.view.clientHeight - (side ? 0 : this.view.clientHeight * 0.55);
      this.k = Math.max(this.k, 0.85);
      this.tx = vw / 2 - (n.x + n.w / 2) * this.k; this.ty = vh / 2 - (n.y + n.h / 2) * this.k;
      this.ease(); this.apply();
    }

    // ---- interaction
    bind() {
      let pan = null, drag = null;
      this.view.addEventListener('pointerdown', e => {
        if (e.button !== 0 || e.target.closest('.fm-insp')) return;
        const nodeEl = e.target.closest('.fm-node');
        if (nodeEl) {
          const n = this.nodes.get(nodeEl.dataset.id);
          drag = {n, sx: e.clientX, sy: e.clientY, x: n.x, y: n.y, moved: false};
          nodeEl.setPointerCapture(e.pointerId);
          return;
        }
        pan = {sx: e.clientX, sy: e.clientY, tx: this.tx, ty: this.ty};
        this.view.setPointerCapture(e.pointerId);
        this.view.classList.add('panning');
      });
      this.view.addEventListener('pointermove', e => {
        if (drag) {
          const dx = (e.clientX - drag.sx) / this.k, dy = (e.clientY - drag.sy) / this.k;
          if (!drag.moved && Math.hypot(dx, dy) * this.k < 4) return;
          drag.moved = true; drag.n.el.classList.add('dragging');
          drag.n.x = drag.x + dx; drag.n.y = drag.y + dy;
          this.place(drag.n); this.redrawEdgesOf(drag.n.id);
        } else if (pan) {
          this.tx = pan.tx + e.clientX - pan.sx; this.ty = pan.ty + e.clientY - pan.sy; this.apply();
        }
      });
      const up = () => {
        if (drag) {
          drag.n.el.classList.remove('dragging');
          if (!drag.moved) this.select(drag.n.id);
          drag = null;
        }
        if (pan) { pan = null; this.view.classList.remove('panning'); }
      };
      this.view.addEventListener('pointerup', up);
      this.view.addEventListener('pointercancel', up);
      // Keyboard: nodes are buttons, so Enter / Space open the inspector and centre the node.
      this.world.addEventListener('keydown', e => {
        const el = e.target.closest('.fm-node');
        if (el && (e.key === 'Enter' || e.key === ' ')) { e.preventDefault(); this.focus(el.dataset.id); }
      });
      this.view.addEventListener('wheel', e => {
        if (e.target.closest('.fm-insp')) return;
        const full = this.root.classList.contains('full');
        if (!(e.ctrlKey || e.metaKey || full)) return;   // plain scroll keeps scrolling the page
        e.preventDefault();
        const r = this.view.getBoundingClientRect();
        if (e.ctrlKey || e.metaKey) this.zoomAt(e.clientX - r.left, e.clientY - r.top, Math.exp(-e.deltaY * 0.0025));
        else { this.tx -= e.deltaX; this.ty -= e.deltaY; this.apply(); }
      }, {passive: false});
      $$('[data-z]', this.root).forEach(b => b.addEventListener('click', () => {
        this.ease(); this.zoomAt(this.view.clientWidth / 2, this.view.clientHeight / 2, b.dataset.z > 0 ? 1.25 : 0.8);
      }));
      $('.fm-fit', this.root).addEventListener('click', () => this.fit());
      const lens = $('.fm-lens', this.root);
      lens.addEventListener('click', () => {
        const on = this.root.classList.toggle('lens');
        lens.setAttribute('aria-pressed', on);
        const first = on && [...this.nodes.values()].find(n => n.kind.startsWith('mdl'));
        if (first) this.focus(first.id);
      });
      const full = $('.fm-full', this.root);
      full.addEventListener('click', () => {
        const on = this.root.classList.toggle('full');
        full.setAttribute('aria-pressed', on); full.textContent = on ? 'Close' : 'Expand';
        document.body.classList.toggle('fm-locked', on);
        requestAnimationFrame(() => this.fit());
      });
      document.addEventListener('keydown', e => {
        if (e.key !== 'Escape') return;
        if (!this.insp.hidden) this.close();
        else if (this.root.classList.contains('full')) full.click();
      });
      $('.fm-x', this.root).addEventListener('click', () => this.close());
    }
    close() {
      this.insp.hidden = true; this.root.classList.remove('inspecting');
      $$('.fm-node.sel', this.world).forEach(n => n.classList.remove('sel'));
      $$('.fm-e.hot', this.svg).forEach(g => g.classList.remove('hot'));
    }
    select(id) {
      const n = this.nodes.get(id);
      if (!n) return;
      $$('.fm-node.sel', this.world).forEach(x => x.classList.remove('sel'));
      n.el.classList.add('sel');
      $$('.fm-e', this.svg).forEach(g => g.classList.toggle('hot', g.dataset.a === id || g.dataset.b === id));
      this.insp.hidden = false; this.root.classList.add('inspecting');
      const box = $('.fm-insp-in', this.insp);
      box.innerHTML = this.inspect(n);
      box.scrollTop = 0;
      const jump = $('.fm-jump', box);
      if (jump) jump.addEventListener('click', () => this.cop.open(jump.dataset.step));
    }
    inspect(n) {
      const d = n.data;
      if (n.kind.startsWith('mdl')) {
        const s = d.step;
        return `<div class="lbl ins-k">AI touch point · ${esc(s.title)}</div><h4>${esc(d.ai.model || 'Model')}</h4>
          ${aiBox(d.ai)}<p class="ins-ex">${d.ai.state === 'used'
            ? 'Check the records this model touched before relying on them. Every model call is stored with its prompt version and cost on the signal page.'
            : 'Parse never starts a paid model run from Ask. The stage runs from the pipeline with explicit approval, and its outputs then show up here.'}</p>
          ${itemsHTML(s.items, 'Records at this step')}${linksHTML(s.links)}
          <button type="button" class="fm-jump" data-step="${esc(s.id)}">Open the ${esc(s.title)} step →</button>`;
      }
      if (d.step) {
        const s = d.step;
        return `<div class="lbl ins-k">Step ${pad(this.cop.steps.indexOf(s) + 1)} · ${esc(s.subtitle || '')} · ${s.ms} ms</div>
          <h4>${esc(s.title)}</h4><p class="ins-sum">${esc(s.summary || '')}</p>
          ${s.explain ? `<p class="ins-ex">${esc(s.explain)}</p>` : ''}${stepDetail(s)}
          <button type="button" class="fm-jump" data-step="${esc(s.id)}">Open this step in the reasoning →</button>`;
      }
      if (d.branch) {
        const b = d.branch, t = this.term;
        const verdict = b.picked === undefined ? '' : `<div class="ai-box ${b.picked ? 'pick-in' : 'pick-out'}">${glyph(b.picked ? 'check' : 'sort')}
            <div><b>${b.picked ? `Picked · ${b.picked} item${b.picked > 1 ? 's' : ''} in the answer` : 'Left out of the answer'}</b><p>${esc(b.why)}</p></div></div>`;
        return `<div class="lbl ins-k">Source · Tier ${b.tier}${b.tier_name ? ` · ${esc(b.tier_name)}` : ''}</div><h4>${esc(b.name)}</h4>${verdict}
          <div class="kv"><div>matches</div><div>${b.count} in the ranked set</div>${b.best !== undefined ? `<div>best item</div><div>${b.best} pts</div>` : ''}<div>tier</div><div>T${b.tier}</div>
            <div>platform</div><div>${esc(b.platform)}</div><div>language</div><div>${esc(b.lang || '?')}</div></div>
          ${linksHTML([{label: t ? `Its items on “${t}”` : 'Its items', href: `/signals?source=${encodeURIComponent(b.id)}${t ? `&q=${encodeURIComponent(t)}` : ''}`},
                       {label: 'Everything from this source', href: `/signals?source=${encodeURIComponent(b.id)}`},
                       {label: `Tier ${b.tier} sources`, href: `/sources?tier=${b.tier}`},
                       {label: 'Send agents for newer items', href: `/agents?topic=${encodeURIComponent(t || this.q)}`}])}`;
      }
      if (d.cite) {
        const c = d.cite;
        return `<div class="lbl ins-k">Cited record /${c.n} · ${esc(c.date)}</div><h4>${esc(c.title)}</h4>
          <p class="ins-ex">${esc(c.snippet)}</p>
          <div class="kv"><div>source</div><div>${esc(c.source)} · Tier ${c.tier}</div><div>language</div><div>${esc(c.lang)}</div>
            <div>window</div><div>${esc(c.window)}</div></div>
          ${linksHTML([{label: 'Open the signal and its evidence', href: `/signals/${encodeURIComponent(c.id)}`},
                       ...(c.source_id ? [{label: `More from ${c.source}`, href: `/signals?source=${encodeURIComponent(c.source_id)}`}] : []),
                       ...(c.url ? [{label: 'Original page', href: c.url}] : [])])}`;
      }
      if (d.answer) {
        const a = d.answer;
        return `<div class="lbl ins-k">Answer · ${((a.ms || 0) / 1000).toFixed(2)}s</div><h4>${esc(a.headline)}</h4>
          ${a.bullets.length ? `<ul class="ins-ul">${a.bullets.map(b => `<li>${esc(b)}</li>`).join('')}</ul>` : ''}
          ${aiBox({state: 'none', what: 'Built from counts and dates in the matches. No language model wrote this answer.'})}
          ${itemsHTML((a.citations || []).map(c => ({title: c.title, sub: `${c.source} · ${c.date}`, tag: '/' + c.n, href: `/signals/${encodeURIComponent(c.id)}`})), 'Citations')}`;
      }
      return '';
    }
  }
})();
