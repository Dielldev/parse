// Ask Atlas: streams /api/ask and draws each step as a node on an n8n-style canvas.
(() => {
  const $ = (s, el = document) => el.querySelector(s);
  const esc = (t) => String(t ?? '').replace(/[&<>"']/g, c => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[c]));
  const icon = (id, cls = '') => `<svg class="${cls}" viewBox="0 0 24 24"><use href="#i-${id}"/></svg>`;

  const MAIN = [
    {id: 'trigger', title: 'Question', icon: 'bolt', cls: 'trigger'},
    {id: 'normalise', title: 'Normalise', icon: 'type'},
    {id: 'registry', title: 'Source registry', icon: 'book'},
    {id: 'search', title: 'Search corpus', icon: 'database'},
    {id: 'sources', title: 'Sources', icon: 'globe', branch: true},
    {id: 'rank', title: 'Rank & dedupe', icon: 'sort'},
    {id: 'evidence', title: 'Evidence vault', icon: 'lock'},
    {id: 'classify', title: 'Threat labels', icon: 'spark'},
    {id: 'spread', title: 'Source spread', icon: 'branch'},
    {id: 'brief', title: 'Write brief', icon: 'file', cls: 'out'},
  ];
  const PLATFORM = {news: 'rss', official: 'landmark', telegram: 'send', x: 'x', mirror: 'copy', facebook: 'users', reddit: 'users'};
  const W_NODE = 100, W_SRC = 150, GAP = 28, PAD = 28, ROW = 60, MIN_STEP_MS = 420;
  const initials = (n) => (n.split(/[\s\-_.]+/).filter(p => p && /\w/.test(p[0])).slice(0, 2).map(p => p[0]).join('') || n.slice(0, 2)).toUpperCase();
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
    ask(q, $('#window').value, $('#lang').value, $('#cite').checked);
    grow();
  });
  ta.focus();

  // ---------------------------------------------------------------- one turn = one workflow
  async function ask(q, windowName, lang, cite) {
    busy = true;
    document.body.classList.add('threaded');
    const turn = document.createElement('article');
    turn.className = 'turn';
    const filt = [windowName, lang].filter(Boolean).join(' · ');
    turn.innerHTML = `
      <div class="q-bubble">${esc(q)}</div><div class="q-meta">${filt ? esc(filt) : 'All windows · all languages'}</div>
      <div class="a-head"><div class="orb sm busy"></div><b>Atlas</b><span class="status">Starting workflow…</span>
        <button type="button" class="toggle-flow">${icon('chev', 'ic sm')}<span>Hide steps</span></button></div>
      <div class="flowcard"><div class="canvas-scroll"><div class="sizer"><div class="canvas"><svg class="edges"></svg></div></div></div>
        <div class="inspector"></div></div>
      <div class="answer"></div>`;
    thread.appendChild(turn);
    turn.scrollIntoView({behavior: 'smooth', block: 'start'});
    const flow = new Flow(turn);
    $('.toggle-flow', turn).onclick = () => {
      turn.classList.toggle('collapsed');
      $('.toggle-flow span', turn).textContent = turn.classList.contains('collapsed') ? 'Show steps' : 'Hide steps';
    };

    const queue = []; let streamDone = false, wake = null;
    const push = (ev) => { queue.push(ev); if (wake) { wake(); wake = null; } };
    const reader = (async () => {
      try {
        const r = await fetch('/api/ask', {method: 'POST', headers: {'Content-Type': 'application/json'},
          body: JSON.stringify({q, window: windowName, lang})});
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

    flow.run('trigger');
    for (;;) {
      if (!queue.length) { if (streamDone) break; await new Promise(r => (wake = r)); continue; }
      const ev = queue.shift();
      if (!ev) continue;
      if (ev.type === 'step') {
        await flow.finish(ev);
      } else if (ev.type === 'answer') {
        flow.end(ev.ms);
        renderAnswer(turn, ev, cite);
      } else if (ev.type === 'error') {
        flow.end(null, true);
        $('.answer', turn).innerHTML = `<div class="err-card">Atlas could not finish: ${esc(ev.message)}</div>`;
      }
    }
    await reader;
    $('.orb.sm', turn).classList.remove('busy');
    busy = false;
    ta.focus();
  }

  function renderAnswer(turn, a, cite) {
    const cards = (cite && a.citations.length) ? `<div class="cites-h">Sources · ${a.citations.length}</div><div class="cites">${
      a.citations.map(c => `<a class="cite" href="/signals/${encodeURIComponent(c.id)}">
        <div class="top"><span class="logo-mono tier${c.tier}">${esc(initials(c.source))}</span><span class="src">${esc(c.source)}</span><span class="n">${c.n}</span></div>
        <div class="t">${esc(c.title)}</div><div class="snip">${esc(c.snippet)}</div>
        <div class="foot"><span class="pill t${c.tier}">Tier ${c.tier}</span><span class="pill idle">${esc(c.date)}</span>
          <span class="pill idle">${esc(c.lang)}</span><span class="pill idle">${esc(c.window)}</span></div></a>`).join('')}</div>` : '';
    $('.answer', turn).innerHTML = `<h3>${esc(a.headline)}</h3>
      ${a.bullets.length ? `<ul>${a.bullets.map(b => `<li>${esc(b)}</li>`).join('')}</ul>` : ''}${cards}`;
  }

  // ---------------------------------------------------------------- the canvas
  class Flow {
    constructor(turn) {
      this.turn = turn; this.scroll = $('.canvas-scroll', turn); this.sizer = $('.sizer', turn);
      this.canvas = $('.canvas', turn); this.svg = $('svg.edges', turn); this.insp = $('.inspector', turn);
      this.status = $('.status', turn);
      this.state = {}; this.data = {}; this.branches = [null, null, null];
      this.userPicked = false; this.done = 0; this.runStart = 0; this.selected = null;
      this.nodes = {};
      for (const m of MAIN) if (!m.branch) this.nodes[m.id] = this.makeNode(m);
      this.insp.innerHTML = '<div class="muted" style="font-size:13px">Click any node to see what it returned.</div>';
      this.layout();
      this.ro = new ResizeObserver(() => this.fit()); this.ro.observe(this.scroll);
    }
    makeNode(m) {
      const el = document.createElement('div');
      el.className = `node ${m.cls || ''}`;
      el.innerHTML = `<div class="tile k-${m.icon}">${icon(m.icon)}<span class="badge"></span><span class="spin"></span></div>
        <div class="nm">${esc(m.title)}</div><div class="sm">&nbsp;</div>`;
      el.addEventListener('click', () => { this.userPicked = true; this.select(m.id); });
      this.canvas.appendChild(el);
      return el;
    }
    makeBranch(b, i) {
      const el = document.createElement('div');
      el.className = 'node src' + (b ? '' : ' ph');
      el.innerHTML = b
        ? `<div class="tile"><span class="logo-mono tier${b.tier}">${esc(b.initials)}</span><span class="plat">${icon(PLATFORM[b.platform] || 'globe')}</span><span class="badge"></span></div>
           <div class="txt"><div class="nm">${esc(b.name)}</div><div class="sm">${b.count} match${b.count === 1 ? '' : 'es'} · T${b.tier}</div></div>`
        : `<div class="tile"><span class="logo-mono tier-ph"></span><span class="spin"></span></div><div class="txt"><div class="nm muted">Source ${i + 1}</div><div class="sm">waiting</div></div>`;
      el.addEventListener('click', () => { this.userPicked = true; this.select('sources'); });
      this.canvas.appendChild(el);
      return el;
    }
    layout() {
      this.canvas.querySelectorAll('.node.src').forEach(n => n.remove());
      this.srcEls = this.branches.map((b, i) => this.makeBranch(b, i));
      const n = this.srcEls.length;
      this.H = Math.max(200, n * ROW + 70);
      const cy = Math.round(this.H / 2) - 8;
      let x = PAD; this.pos = {};
      for (const m of MAIN) {
        if (m.branch) {
          const top0 = cy - (n * ROW) / 2;
          this.srcPos = this.srcEls.map((el, i) => {
            const y = top0 + i * ROW + ROW / 2;
            el.style.left = x + 'px'; el.style.top = (y - 24) + 'px';
            return {l: x, r: x + W_SRC, y};
          });
          x += W_SRC + GAP;
        } else {
          const el = this.nodes[m.id];
          el.style.left = x + 'px'; el.style.top = (cy - 30) + 'px';
          this.pos[m.id] = {l: x + (W_NODE - 60) / 2, r: x + (W_NODE + 60) / 2, y: cy};
          x += W_NODE + GAP;
        }
      }
      this.W = x - GAP + PAD;
      this.canvas.style.width = this.W + 'px'; this.canvas.style.height = this.H + 'px';
      this.svg.setAttribute('width', this.W); this.svg.setAttribute('height', this.H);
      for (const [id, st] of Object.entries(this.state)) this.paint(id, st);
      this.fit(); this.edges();
    }
    fit() {
      const cw = this.scroll.clientWidth || this.W;
      const s = Math.max(0.82, Math.min(1, cw / this.W));
      this.canvas.style.transform = `scale(${s})`;
      this.sizer.style.width = this.W * s + 'px'; this.sizer.style.height = this.H * s + 'px';
      this.scale = s;
    }
    edges() {
      const st = (id) => this.state[id];
      const kind = (a, b) => st(b) === 'run' ? 'live' : (st(b) && st(b) !== 'run') ? (st(b) === 'skip' ? 'skip' : 'done') : '';
      const curve = (p, q) => { const dx = Math.max(30, (q.x - p.x) / 2); return `M${p.x},${p.y} C${p.x + dx},${p.y} ${q.x - dx},${q.y} ${q.x},${q.y}`; };
      const out = [], labels = [];
      const ids = MAIN.map(m => m.id);
      for (let i = 0; i < ids.length - 1; i++) {
        const a = ids[i], b = ids[i + 1];
        if (b === 'sources') {
          for (const sp of this.srcPos) out.push(`<path class="${kind(a, 'sources')}" d="${curve({x: this.pos[a].r + 4, y: this.pos[a].y}, {x: sp.l - 4, y: sp.y})}"/>`);
        } else if (a === 'sources') {
          for (const sp of this.srcPos) out.push(`<path class="${kind('sources', b)}" d="${curve({x: sp.r + 4, y: sp.y}, {x: this.pos[b].l - 4, y: this.pos[b].y})}"/>`);
        } else {
          const p = {x: this.pos[a].r + 4, y: this.pos[a].y}, q = {x: this.pos[b].l - 4, y: this.pos[b].y};
          out.push(`<path class="${kind(a, b)}" d="${curve(p, q)}"/>`);
          const lbl = this.edgeLabel(a);
          if (lbl && st(b) && st(b) !== 'run') {
            const mx = (p.x + q.x) / 2, w = lbl.length * 6 + 10;
            labels.push(`<rect class="lbl" x="${mx - w / 2}" y="${p.y - 22}" width="${w}" height="15" rx="4"/><text x="${mx}" y="${p.y - 11}" text-anchor="middle">${esc(lbl)}</text>`);
          }
        }
      }
      this.svg.innerHTML = out.join('') + labels.join('');
    }
    edgeLabel(id) {
      const d = this.data[id]; if (!d) return '';
      if (id === 'registry') return d.summary.split(' ')[0] + ' sources';
      if (id === 'rank') { const k = (d.rows.find(r => r[0] === 'kept') || [])[1]; return k ? `${k} items` : ''; }
      return '';
    }
    nodeEls(id) { return id === 'sources' ? this.srcEls : [this.nodes[id]]; }
    paint(id, st) {
      for (const el of this.nodeEls(id)) {
        if (!el) continue;
        el.classList.remove('run', 'on', 'ok', 'skip', 'warn', 'empty', 'error');
        if (st === 'run') el.classList.add('run'); else if (st) el.classList.add('on', st);
        const badge = el.querySelector('.badge');
        if (badge) badge.innerHTML = icon(st === 'ok' ? 'check' : st === 'skip' ? 'minus' : 'alert');
      }
    }
    run(id) { this.state[id] = 'run'; this.runStart = performance.now(); this.paint(id, 'run'); this.edges(); this.follow(id); this.setStatus(); }
    async finish(ev) {
      if (this.state[ev.id] !== 'run') this.run(ev.id);
      const wait = MIN_STEP_MS - (performance.now() - this.runStart);
      if (wait > 0) await sleep(wait);
      this.data[ev.id] = ev; this.state[ev.id] = ev.status; this.done++;
      if (ev.id === 'sources') { this.branches = ev.branches.length ? ev.branches : [null]; this.layout(); }
      else {
        const el = this.nodes[ev.id];
        el.querySelector('.sm').textContent = ev.summary || '';
        el.title = ev.summary || '';
      }
      this.paint(ev.id, ev.status);
      if (!this.userPicked) this.select(ev.id);
      const next = MAIN[MAIN.findIndex(m => m.id === ev.id) + 1];
      if (next && ev.status !== 'error') this.run(next.id); else this.edges();
    }
    follow(id) {
      const p = id === 'sources' ? this.srcPos[0] : this.pos[id];
      if (!p || this.scroll.scrollWidth <= this.scroll.clientWidth) return;
      this.scroll.scrollTo({left: Math.max(0, p.l * this.scale - this.scroll.clientWidth / 2), behavior: 'smooth'});
    }
    setStatus(text) { this.status.textContent = text || `Running step ${Math.min(this.done + 1, MAIN.length)} of ${MAIN.length}…`; }
    end(ms, failed) {
      for (const [id, st] of Object.entries(this.state)) if (st === 'run') { delete this.state[id]; this.paint(id, null); }
      this.edges();
      this.scroll.scrollTo({left: 0, behavior: 'smooth'});
      this.setStatus(failed ? 'Stopped with an error' : `Done · ${this.done} steps · ${(ms / 1000).toFixed(2)}s`);
    }
    select(id) {
      const d = this.data[id];
      if (!d) return;
      this.selected = id;
      this.canvas.querySelectorAll('.node.sel').forEach(n => n.classList.remove('sel'));
      for (const el of this.nodeEls(id)) el && el.classList.add('sel');
      const m = MAIN.find(x => x.id === id);
      const rows = (d.rows || []).map(([k, v]) => `<div>${esc(k)}</div><div>${esc(v)}</div>`).join('');
      const table = d.table ? `<div class="scroll" style="border:1px solid var(--line);border-radius:10px"><table><tr>${d.table.cols.map(c => `<th>${esc(c)}</th>`).join('')}</tr>${
        d.table.rows.map(r => `<tr>${r.map(c => `<td>${esc(c)}</td>`).join('')}</tr>`).join('')}</table></div>` : '';
      const label = {ok: 'success', skip: 'skipped', warn: 'check', empty: 'no data', error: 'error'}[d.status] || d.status;
      this.insp.innerHTML = `<div class="ih"><span class="tile-mini k-${m.icon}">${icon(m.icon)}</span>
          <div><b>${esc(d.title)}</b> <span class="muted" style="font-size:12.5px">· ${esc(d.subtitle || '')}</span></div>
          <div class="meta"><span class="stat ${d.status}">${label}</span><span>${d.ms} ms</span></div></div>
        <div class="out-tabs">Output</div>${rows ? `<div class="kv">${rows}</div>` : ''}${table}`;
    }
  }
})();
