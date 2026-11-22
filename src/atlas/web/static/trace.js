/* Tracer page: send a seed, draw each Section 10 step as it streams in, then the brief, origin, spread graph,
   amplifiers, score, claim check and discovery queue. Everything from the archive is escaped before it is drawn. */
(() => {
  const $ = (s, el = document) => el.querySelector(s);
  const $$ = (s, el = document) => [...el.querySelectorAll(s)];
  const esc = (v) => String(v ?? '').replace(/[&<>"']/g, c => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[c]));
  const TIER = {0: 'Official / primary', 1: 'Established outlet', 2: 'Specialist OSINT', 3: 'Partisan or unverified'};
  const fmt = (iso) => {
    if (!iso) return 'undated';
    const d = new Date(iso);
    return d.toLocaleString('en-GB', {day: '2-digit', month: 'short', year: 'numeric', hour: '2-digit', minute: '2-digit', timeZone: 'UTC'}) + ' UTC';
  };
  const day = (iso) => iso ? new Date(iso).toLocaleDateString('en-GB', {day: '2-digit', month: 'short', timeZone: 'UTC'}) : '';
  const sigHref = (id) => `/signals/${encodeURIComponent(id)}`;

  const form = $('#tr-form'), main = $('#tr-main'), out = $('#tr-out'), go = $('#tr-go');
  let kind = 'text', image = null;

  // ---------------------------------------------------------------- input tabs
  const setKind = (k) => {
    kind = k;
    $$('.tr-tab').forEach(t => { const on = t.dataset.kind === k; t.classList.toggle('on', on); t.setAttribute('aria-selected', on); });
    $$('.tr-pane').forEach(p => p.classList.toggle('on', p.dataset.kind === k));
  };
  $$('.tr-tab').forEach(t => t.addEventListener('click', () => setKind(t.dataset.kind)));

  const engine = $('#tr-engine');
  const showEngine = () => {
    const e = (window.atlasEngine && window.atlasEngine()) || 'qwen';
    engine.innerHTML = e === 'qwen'
      ? 'Engine <b>Qwen</b> · checks the claim and writes the brief (billed, ~$0.001)'
      : 'Engine <b>Atlas Retrieval</b> · no model calls, $0 (claim not checked)';
  };
  showEngine();
  $$('.model .engine').forEach(r => r.addEventListener('click', () => setTimeout(showEngine, 0)));

  // screenshot: file, drop or paste; shrink large images before sending
  const drop = $('#tr-drop'), file = $('#tr-file'), prev = $('#tr-preview');
  const takeImage = (f) => {
    if (!f || !/^image\/(png|jpeg|webp)$/.test(f.type)) return;
    const img = new Image();
    img.onload = () => {
      const k = Math.min(1, 2000 / Math.max(img.width, img.height));
      const c = document.createElement('canvas');
      c.width = Math.round(img.width * k); c.height = Math.round(img.height * k);
      c.getContext('2d').drawImage(img, 0, 0, c.width, c.height);
      image = c.toDataURL('image/png');
      prev.src = image; prev.hidden = false;
      URL.revokeObjectURL(img.src);
    };
    img.src = URL.createObjectURL(f);
    setKind('image');
  };
  file.addEventListener('change', () => takeImage(file.files[0]));
  drop.addEventListener('keydown', e => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); file.click(); } });
  ['dragenter', 'dragover'].forEach(ev => drop.addEventListener(ev, e => { e.preventDefault(); drop.classList.add('over'); }));
  ['dragleave', 'drop'].forEach(ev => drop.addEventListener(ev, e => { e.preventDefault(); drop.classList.remove('over'); }));
  drop.addEventListener('drop', e => takeImage(e.dataTransfer.files[0]));
  document.addEventListener('paste', e => {
    const it = [...(e.clipboardData?.items || [])].find(i => i.type.startsWith('image/'));
    if (it) { e.preventDefault(); takeImage(it.getAsFile()); }
  });

  $$('.tr-examples button').forEach(b => b.addEventListener('click', () => {
    setKind('text'); $('#tr-text').value = b.dataset.text; form.requestSubmit();
  }));

  // ---------------------------------------------------------------- steps rail
  const resetSteps = () => $$('.tr-step').forEach(li => {
    li.dataset.state = 'wait'; li.classList.remove('open');
    $('.tr-ms', li).textContent = '';
    $('.tr-sum', li).textContent = li.dataset.sub || $('.tr-sum', li).textContent;
    $('.tr-step-b', li).innerHTML = '';
  });
  $$('.tr-step').forEach(li => {
    li.dataset.sub = $('.tr-sum', li).textContent;
    $('.tr-step-h', li).addEventListener('click', () => {
      const o = li.classList.toggle('open'); $('.tr-step-h', li).setAttribute('aria-expanded', o);
    });
  });
  const ORDER = $$('.tr-step').map(li => li.dataset.step);
  const markRunning = (afterId) => {
    const i = afterId ? ORDER.indexOf(afterId) + 1 : 0;
    const li = $(`.tr-step[data-step="${ORDER[i]}"]`);
    if (li && li.dataset.state === 'wait') li.dataset.state = 'run';
  };
  const stepBody = (s) => {
    let h = s.explain ? `<p>${esc(s.explain)}</p>` : '';
    if (s.ocr) h += `<div class="lbl">Text read from the screenshot</div><pre class="tr-ocr">${esc(s.ocr)}</pre>`;
    if (s.rows?.length) h += `<div class="kv">${s.rows.map(([k, v]) => `<div>${esc(k)}</div><div>${esc(v)}</div>`).join('')}</div>`;
    if (s.table?.rows?.length) h += `<div class="panel scroll"><table><thead><tr>${s.table.cols.map(c => `<th>${esc(c)}</th>`).join('')}</tr></thead>
      <tbody>${s.table.rows.map(r => `<tr>${r.map(c => `<td>${esc(c)}</td>`).join('')}</tr>`).join('')}</tbody></table></div>`;
    if (s.ai) {
      const cls = {used: 'acc', available: 'warn', none: 'idle'}[s.ai.state] || 'idle';
      const lab = {used: 'model used', available: 'model available', none: 'no model'}[s.ai.state] || s.ai.state;
      h += `<div class="tr-ai"><span class="pill ${cls}">${lab}</span>${esc(s.ai.what)}</div>`;
    }
    return h;
  };
  const showStep = (s) => {
    let li = $(`.tr-step[data-step="${s.id}"]`);
    if (!li) {   // field agents: an extra step before "expand"
      li = document.createElement('li');
      li.className = 'tr-step'; li.dataset.step = s.id;
      li.innerHTML = `<button type="button" class="tr-step-h" aria-expanded="false"><span class="tr-n mono">01b</span>
        <span class="tr-st"><b>${esc(s.title)}</b><span class="tr-sum"></span></span><span class="tr-ms mono"></span></button><div class="tr-step-b"></div>`;
      $(`.tr-step[data-step="expand"]`).before(li);
      $('.tr-step-h', li).addEventListener('click', () => li.classList.toggle('open'));
    }
    li.dataset.state = s.status === 'ok' ? 'ok' : s.status === 'error' ? 'error' : s.status === 'skip' ? 'skip' : s.status === 'empty' ? 'empty' : 'ok';
    $('.tr-sum', li).textContent = s.summary || '';
    $('.tr-ms', li).textContent = s.ms >= 1000 ? (s.ms / 1000).toFixed(1) + 's' : Math.round(s.ms) + 'ms';
    $('.tr-step-b', li).innerHTML = stepBody(s);
    if (s.id !== 'agents') markRunning(s.id);
  };

  // ---------------------------------------------------------------- run
  let clock = null;
  const startClock = () => {
    const t0 = performance.now(), el = $('#tr-clock');
    clearInterval(clock);
    clock = setInterval(() => { el.textContent = ((performance.now() - t0) / 1000).toFixed(1) + 's'; }, 100);
  };
  const stopClock = () => clearInterval(clock);

  async function trace(body) {
    main.hidden = false; resetSteps(); markRunning(null);
    out.innerHTML = `<div class="tr-wait">Tracing. The first trace of a story embeds its posts on this machine, so it can take up to a minute; repeats are fast.</div>`;
    go.disabled = true; startClock();
    main.scrollIntoView({behavior: 'smooth', block: 'start'});
    try {
      const r = await fetch('/api/trace', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(body)});
      if (!r.ok) throw new Error((await r.json().catch(() => ({}))).detail || `HTTP ${r.status}`);
      const reader = r.body.getReader(), dec = new TextDecoder();
      let buf = '';
      for (;;) {
        const {value, done} = await reader.read();
        if (done) break;
        buf += dec.decode(value, {stream: true});
        let i;
        while ((i = buf.indexOf('\n')) >= 0) {
          const line = buf.slice(0, i).trim(); buf = buf.slice(i + 1);
          if (line) handle(JSON.parse(line));
        }
      }
      if (buf.trim()) handle(JSON.parse(buf));
    } catch (e) {
      out.innerHTML = `<div class="tr-err">${esc(e.message || e)}</div>`;
    } finally {
      go.disabled = false; stopClock();
      $$('.tr-step[data-state=run]').forEach(li => { li.dataset.state = 'wait'; });
    }
  }
  function handle(ev) {
    if (ev.type === 'step') showStep(ev);
    else if (ev.type === 'error') out.innerHTML = `<div class="tr-err">${esc(ev.message)}</div>`;
    else if (ev.type === 'result') {
      render(ev);
      if (ev.event_id) history.replaceState(null, '', `/trace/${encodeURIComponent(ev.event_id)}`);
    }
  }

  form.addEventListener('submit', (e) => {
    e.preventDefault();
    const body = {fresh: $('#tr-fresh').checked};
    if (kind === 'text') { body.text = $('#tr-text').value.trim(); if (!body.text) return $('#tr-text').focus(); }
    if (kind === 'url') { body.url = $('#tr-url').value.trim(); if (!body.url) return $('#tr-url').focus(); }
    if (kind === 'signal') { body.signal_id = $('#tr-signal').value.trim(); if (!body.signal_id) return $('#tr-signal').focus(); }
    if (kind === 'image') { if (!image) return file.click(); body.image = image; }
    trace(body);
  });

  // ---------------------------------------------------------------- result
  const VERDICT_CLS = {CONFIRMED: 'ok', CORROBORATED: 'ok', DISPUTED: 'warn', DEBUNKED: 'bad', UNVERIFIED: 'idle'};
  const list = (xs) => `<ul>${xs.map(x => `<li>${esc(x)}</li>`).join('')}</ul>`;

  function render(R) {
    const g = R.graph, byId = Object.fromEntries(g.nodes.map(n => [n.id, n]));
    const o = R.origin, v = R.verdict, a = R.acceptance, b = R.brief;
    const real = g.nodes.filter(n => !n.probe);
    const nSrc = new Set(real.map(n => n.source_id)).size;
    const edges = [...g.edges].sort((x, y) => (byId[x.to]?.when || '').localeCompare(byId[y.to]?.when || ''));

    let h = `<section class="tr-brief">
      <div class="tr-brief-h"><span class="lbl">What this is about${b.about?.length ? ' · ' + esc(b.about.slice(0, 5).join(' · ')) : ''}</span>
        <p class="tr-headline">${esc(b.headline)}</p>
        <p class="tr-narr">${esc(b.narrative)}</p>
        <div class="tr-badges">
          <span class="pill ${['P1', 'P2'].includes(R.tps.priority) ? 'bad' : R.tps.priority === 'P3' ? 'warn' : 'idle'}">${esc(R.tps.priority)} · TPS ${Math.round(R.tps.tps)}</span>
          <span class="pill ${VERDICT_CLS[v.verdict] || 'idle'}">${esc(v.verdict)}${v.checked ? '' : ' · not checked'}</span>
          <span class="pill acc">Origin confidence ${o.confidence.toFixed(2)}</span>
          <span class="pill">${real.length} posts · ${nSrc} sources · ${R.significance.independent_origins.value} origin groups</span>
          <span class="pill ${a.passes ? 'ok' : 'warn'}" title="MVP acceptance test: a root plus at least 3 nodes and 2 spread steps">${a.passes ? '✓' : '✗'} origin-tracing test</span>
          ${R.trigger ? `<span class="pill warn">Trigger date · ${esc(R.trigger)}</span>` : ''}
        </div></div>
      <div class="tr-cols">
        <div><span class="lbl">What we know</span>${list(b.what_we_know)}</div>
        <div><span class="lbl">What we don't know</span>${list(b.what_we_dont_know)}</div>
        <div><span class="lbl">Suggested checks</span>${list(b.suggested_checks)}</div>
      </div>
      <div class="tr-writer">Written by: ${esc(b.writer)}</div>
    </section>`;

    h += `<section><h3><span>Earliest observed source</span><i>step 04</i></h3>
      <div class="tr-origin"><div>
        <span class="pill t${o.tier}">Tier ${o.tier} · ${esc(TIER[o.tier])}</span> <span class="pill idle">${esc(o.platform)}</span>
        <div class="big">${esc(o.source)}</div>
        <div class="mono muted">${esc(fmt(o.when))}</div>
        <p class="t"><a href="${sigHref(o.signal_id)}">${esc(o.title || '(untitled)')}</a></p>
        ${o.url ? `<p class="t mono muted" style="overflow-wrap:anywhere"><a href="${esc(o.url)}" target="_blank" rel="noopener noreferrer">${esc(o.url)}</a></p>` : ''}
      </div><div>
        <span class="lbl">How far to trust it</span>
        <div class="tr-conf"><div class="bar"><i style="width:${Math.round(o.confidence * 100)}%"></i></div><b>${o.confidence.toFixed(2)}</b></div>
        <ul class="tr-reasons"><li>Starts at 0.90: the earliest post in the trace that came from nothing else in it.</li>${o.reasons.map(r => `<li>${esc(r)}</li>`).join('')}</ul>
        ${o.runner_up && byId[o.runner_up] ? `<p class="muted" style="font-size:12.5px;margin:10px 0 0">Next independent post: <a href="${sigHref(o.runner_up)}">${esc(byId[o.runner_up].source)}</a>, ${esc(fmt(byId[o.runner_up].when))}.</p>` : ''}
      </div></div></section>`;

    h += `<section><h3><span>How it spread</span><i>steps 02–03 · ${g.edges.length} edges</i></h3>
      <div class="tr-graph"><div class="tr-graph-scroll" id="tr-svg"></div>
      <div class="tr-legend">
        ${['copy', 'quote', 'link', 'translate', 'forward'].map(t => `<span><svg viewBox="0 0 26 10"><path class="e ${t}" d="M1 5H25" style="stroke-width:2;opacity:1"/></svg>${t}</span>`).join('')}
        ${[0, 1, 2, 3].map(t => `<span><i style="background:var(${['--acc', '--ok', '--warn', '--bad'][t]})"></i>Tier ${t}</span>`).join('')}
        <span>faded = order within the day unknown</span>
      </div>
      ${seedPath(R, byId)}</div></section>`;

    h += `<section><h3><span>Spread steps, in time order</span><i>${edges.length}</i></h3>
      <div class="panel scroll"><table><thead><tr><th>When</th><th>From</th><th>Edge</th><th>To</th><th>Likeness</th></tr></thead><tbody>
      ${edges.slice(0, 60).map(e => { const f = byId[e.from], t = byId[e.to]; return `<tr>
        <td class="mono">${esc(t.probe ? 'now' : fmt(t.when))}</td>
        <td>${f ? `<a href="${sigHref(f.id)}">${esc(f.source)}</a> <span class="muted">${esc(f.lang || '')}</span>` : esc(e.from)}</td>
        <td><span class="tr-type ${esc(e.type)}">${esc(e.type)}</span>${e.order_uncertain ? ' <span class="muted" title="One side gives a date without a time">?</span>' : ''}</td>
        <td>${t.probe ? esc(t.source) : `<a href="${sigHref(t.id)}">${esc(t.source)}</a> <span class="muted">${esc(t.lang || '')}</span>`}<br><span class="muted">${esc((t.title || '').slice(0, 110))}</span></td>
        <td class="mono">${e.sim.toFixed(2)} · ${esc(e.via)}</td></tr>`; }).join('')}
      </tbody></table>${edges.length > 60 ? `<p>Showing 60 of ${edges.length} edges.</p>` : ''}</div></section>`;

    h += `<div class="tr-two"><section><h3><span>Amplified by</span><i>step 05</i></h3>
      ${R.amplifiers.length ? `<div class="panel scroll"><table><thead><tr><th>Source</th><th>Tier</th><th title="Posts by other sources that descend from this source's posts">Reach</th><th>Posts</th><th title="Earlier traces where this source passed a story on">Before</th></tr></thead><tbody>
        ${R.amplifiers.slice(0, 10).map(x => `<tr><td><a href="${sigHref(x.signal_id)}">${esc(x.source)}</a></td><td><span class="pill t${x.tier}">T${x.tier}</span></td>
        <td class="mono">${x.reach}</td><td class="mono">${x.posts}</td><td class="mono">${x.seen_before}</td></tr>`).join('')}</tbody></table>
        <p>Reach counts later posts by <em>other</em> sources that descend from this source's posts.</p></div>` : '<p class="muted">Only the origin carried it in the archive.</p>'}
      </section>
      <section><h3><span>Threat priority</span><i>step 08 · ${esc(R.tps.priority)}</i></h3>
      <div class="tr-fac">${Object.entries(R.tps.factors).map(([k, x]) => `<div>${esc(k.replace('_', ' '))}</div>
        <div><div class="tr-meter"><i style="width:${Math.round(x * 100)}%"></i></div>${esc(facNote(k, R))}</div>`).join('')}</div>
      <p class="muted" style="font-size:12.5px">${esc(R.tps.explanation)}</p></section></div>`;

    h += `<section><h3><span>Is it true? Claim check</span><i>step 09 · ${esc(v.verdict)}</i></h3>
      <p style="margin:0 0 10px"><span class="pill ${VERDICT_CLS[v.verdict] || 'idle'}">${esc(v.verdict)}</span> ${esc(v.reason)}</p>
      ${v.checks?.length ? `<div class="panel scroll"><table><thead><tr><th>#</th><th>Independent source</th><th>Stance</th><th>Tier-0 scope</th></tr></thead><tbody>
        ${v.checks.map(c => `<tr><td class="mono">${c.n}</td><td><a href="${sigHref(c.signal_id)}">${esc(c.source)}</a> <span class="pill t${c.tier}">T${c.tier}</span><br><span class="muted">${esc(c.title)}</span></td>
        <td>${esc(c.stance)}${c.confidence != null ? ` <span class="mono muted">${c.confidence.toFixed(2)}</span>` : ''}</td>
        <td class="muted">${c.tier === 0 ? (c.in_scope ? 'in scope: ' + esc(c.in_scope) : 'outside its scope (counts as Tier 3)') : '—'}</td></tr>`).join('')}</tbody></table>
        <p>One post per independent origin group, best tier first. Truth and spread are scored apart: an unverified story that spreads fast still ranks high.</p></div>` : ''}
    </section>`;

    h += `<div class="tr-two"><section><h3><span>New upstream sources</span><i>step 06 · discovery queue</i></h3>
      ${R.discovered.length ? `<div class="panel scroll"><table><thead><tr><th>Upstream</th><th>Cited by</th><th>Queue</th></tr></thead><tbody>
        ${R.discovered.map(d => `<tr><td class="mono" style="overflow-wrap:anywhere">${esc(d.url)}</td><td class="mono">${d.cited_by}</td><td>${d.new ? '<span class="pill warn">new · needs approval</span>' : '<span class="pill idle">already queued</span>'}</td></tr>`).join('')}
        </tbody></table><p>Atlas collects nothing from these until a person approves them.</p></div>` : '<p class="muted">Every site the story links to is already in the registry.</p>'}</section>
      <section><h3><span>Official sources</span><i>step 07</i></h3>
      ${R.official.length ? `<div class="panel scroll"><table><tbody>${R.official.map(x => `<tr><td><a href="${sigHref(x.id)}">${esc(x.source)}</a><br><span class="muted">${esc(x.title)}</span></td>
        <td class="mono">${esc(fmt(x.when))}</td><td>${x.in_story ? 'in the story' : 'nearby'}</td></tr>`).join('')}</tbody></table></div>`
        : '<p class="muted">No official (Tier 0) statement on this in the archive.</p>'}
      <p class="muted" style="font-size:12.5px">${R.trigger ? 'Falls in the trigger window for ' + esc(R.trigger) + '.' : 'Not near a trigger-calendar date.'}</p></section></div>`;

    const cost = R.usd ? `$${R.usd.toFixed(5)} in model calls` : '$0 · no billed model calls';
    h += `<div class="tr-foot"><span>${R.event_id ? `Saved as <a href="/trace/${encodeURIComponent(R.event_id)}">${esc(R.event_id)}</a>` : 'Not saved'}</span>
      <span>${(R.ms / 1000).toFixed(1)} s</span><span>${cost}</span><span>Search words: ${esc((R.seed.terms || []).join(', '))}</span></div>`;

    out.innerHTML = h;
    drawGraph($('#tr-svg'), R, byId);
  }

  function facNote(k, R) {
    const s = R.significance;
    return {velocity: s.velocity_z.note, coordination: s.coordination.note, proximity: s.proximity.note,
      severity: R.labels.length ? 'Labels: ' + R.labels.join(', ') : 'No threat labels yet: the classifier has not run on these posts.',
      reach: 'Follower counts are not collected for news sites, so reach is 0 for now.',
      offline_intent: 'Needs the classifier; 0 until it runs.'}[k] || '';
  }

  function seedPath(R, byId) {
    if (!R.seed_path?.length) return '';
    const chain = [...R.seed_path].reverse();
    const nodes = [chain[0].from, ...chain.map(e => e.to)];
    return `<div class="tr-path"><span class="lbl">Your seed came from</span>${nodes.map((id, i) => {
      const n = byId[id]; if (!n) return '';
      const step = i ? `<span class="arr">→ ${esc(chain[i - 1].type)} →</span>` : '';
      return step + (n.probe ? `<b>${esc(n.source)}</b>` : `<a href="${sigHref(id)}" title="${esc(n.title)}">${esc(n.source)} · ${esc(day(n.when))}</a>`);
    }).join('')}</div>`;
  }

  // ---------------------------------------------------------------- spread graph (SVG)
  function drawGraph(host, R, byId) {
    const nodes = [...R.graph.nodes].sort((x, y) => (x.probe - y.probe) || (x.when || '~').localeCompare(y.when || '~'));
    const lanes = [];
    nodes.forEach(n => { const k = n.probe ? '__probe' : n.source_id; if (!lanes.includes(k)) lanes.push(k); });
    const LW = Math.min(190, Math.max(120, host.clientWidth * 0.2)), TOP = 34, ROW = 24, PAD = 18;
    const avail = Math.max(300, host.clientWidth - LW - PAD * 2);
    const step = Math.max(16, Math.min(46, avail / Math.max(nodes.length - 1, 1)));
    const W = LW + PAD * 2 + step * Math.max(nodes.length - 1, 1), H = TOP + lanes.length * ROW + 14;
    const pos = {};
    nodes.forEach((n, i) => { pos[n.id] = {x: LW + PAD + i * step, y: TOP + lanes.indexOf(n.probe ? '__probe' : n.source_id) * ROW + ROW / 2}; });
    const laneName = Object.fromEntries(nodes.map(n => [n.probe ? '__probe' : n.source_id, n]));
    let s = `<svg width="${W}" height="${H}" viewBox="0 0 ${W} ${H}" role="img" aria-label="Spread graph: ${nodes.length} posts across ${lanes.length} sources, earliest on the left">`;
    lanes.forEach((k, i) => {
      const y = TOP + i * ROW + ROW / 2, n = laneName[k];
      const name = n.probe ? n.source : n.source;
      s += `<line class="lane" x1="${LW}" x2="${W - 6}" y1="${y}" y2="${y}"/><text class="lane-l" x="6" y="${y + 3.5}">${esc(name.length > 24 ? name.slice(0, 23) + '…' : name)}${n.probe ? '' : ' · T' + n.tier}</text>`;
    });
    let last = '';
    nodes.forEach(n => {
      const d = n.probe ? 'now' : day(n.when);
      if (d !== last) { const x = pos[n.id].x - step / 2; s += `<line class="day" x1="${x}" x2="${x}" y1="16" y2="${H - 6}"/><text class="day-l" x="${x + 4}" y="12">${esc(d)}</text>`; last = d; }
    });
    R.graph.edges.forEach((e, i) => {
      const a = pos[e.from], b = pos[e.to]; if (!a || !b) return;
      const mx = (a.x + b.x) / 2;
      s += `<path class="e ${esc(e.type)}${e.order_uncertain ? ' unsure' : ''}" data-i="${i}" d="M${a.x} ${a.y} C${mx} ${a.y} ${mx} ${b.y} ${b.x} ${b.y}"/>`;
    });
    nodes.forEach(n => {
      const p = pos[n.id];
      if (n.origin) s += `<circle class="ring" cx="${p.x}" cy="${p.y}" r="10"/><text class="tag-l" x="${p.x - 18}" y="${p.y - 13}">ORIGIN</text>`;
      if (n.seed && !n.probe) s += `<rect class="seedmark" x="${p.x - 9}" y="${p.y - 9}" width="18" height="18"/>`;
      s += n.probe
        ? `<rect class="n probe" data-id="${esc(n.id)}" x="${p.x - 6}" y="${p.y - 6}" width="12" height="12" transform="rotate(45 ${p.x} ${p.y})"/>`
        : `<circle class="n t${n.tier}" data-id="${esc(n.id)}" cx="${p.x}" cy="${p.y}" r="${n.origin ? 7 : 5 + Math.min(n.reach, 6) * .4}"/>`;
    });
    host.innerHTML = s + '</svg>';

    const tip = document.createElement('div'); tip.className = 'tr-tip'; tip.hidden = true; document.body.appendChild(tip);
    const svg = $('svg', host), paths = $$('path.e', svg), parentOf = Object.fromEntries(R.graph.edges.map((e, i) => [e.to, i]));
    const lineage = (id) => { const ids = new Set([id]), es = new Set(); let c = id, k = 0;
      while (parentOf[c] !== undefined && k++ < 60) { es.add(parentOf[c]); c = R.graph.edges[parentOf[c]].from; ids.add(c); } return {ids, es}; };
    $$('.n', svg).forEach(el => {
      const n = byId[el.dataset.id];
      el.addEventListener('mouseenter', (ev) => {
        const {ids, es} = lineage(n.id);
        $$('.n', svg).forEach(x => x.classList.toggle('dim', !ids.has(x.dataset.id)));
        paths.forEach(p => { const on = es.has(+p.dataset.i); p.classList.toggle('hl', on); p.classList.toggle('dim', !on); });
        tip.innerHTML = `<span class="lbl">${esc(n.source)}${n.probe ? '' : ' · T' + n.tier + ' · ' + esc(n.lang || '?')}</span>${esc(n.title)}<br>
          <span class="mono" style="font-size:11px;color:#b9b9b9">${esc(n.probe ? 'your seed' : fmt(n.when))}${n.dated || n.probe ? '' : ' (date only)'} · reach ${n.reach}${n.origin ? ' · ORIGIN' : ''}</span>`;
        tip.hidden = false; move(ev);
      });
      el.addEventListener('mousemove', move);
      el.addEventListener('mouseleave', () => { tip.hidden = true; $$('.dim, .hl', svg).forEach(x => x.classList.remove('dim', 'hl')); });
      if (!n.probe) el.addEventListener('click', () => window.open(sigHref(n.id), '_blank', 'noopener'));
    });
    function move(ev) { tip.style.left = Math.min(ev.clientX + 14, innerWidth - 360) + 'px'; tip.style.top = (ev.clientY + 14) + 'px'; }
    // open with the origin in view
    const ox = Object.values(pos).length && pos[R.origin.signal_id]?.x;
    if (ox && ox > host.clientWidth * 0.6) host.scrollLeft = ox - LW - 40;
  }

  // ---------------------------------------------------------------- saved trace or prefill
  const saved = main.dataset.event;
  if (saved) {
    main.hidden = false; resetSteps();
    fetch(`/api/trace/${encodeURIComponent(saved)}`).then(r => r.json()).then(R => {
      (R.steps || []).forEach(showStep);
      if (R.seed?.kind === 'text' && R.seed.text) $('#tr-text').value = R.seed.text;
      render(R);
    }).catch(e => { out.innerHTML = `<div class="tr-err">${esc(e.message || e)}</div>`; });
  } else {
    const sigPre = $('#tr-signal').value.trim(), urlPre = $('#tr-url').value.trim(), qPre = $('#tr-text').value.trim();
    if (sigPre) { setKind('signal'); form.requestSubmit(); }
    else if (urlPre) { setKind('url'); form.requestSubmit(); }
    else if (qPre) { setKind('text'); form.requestSubmit(); }
  }
})();
