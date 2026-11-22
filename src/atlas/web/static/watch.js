/* Watch dashboard: start/stop the automation, then poll its state and draw the pipeline, stories, feed and log.
   All text from the archive is escaped. */
(() => {
  const $ = (s, el = document) => el.querySelector(s);
  const $$ = (s, el = document) => [...el.querySelectorAll(s)];
  const esc = (v) => String(v ?? '').replace(/[&<>"']/g, c => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[c]));
  const t = (iso, withDay = true) => iso ? new Date(iso).toLocaleString('en-GB', withDay
    ? {day: '2-digit', month: 'short', hour: '2-digit', minute: '2-digit', timeZone: 'UTC'}
    : {hour: '2-digit', minute: '2-digit', timeZone: 'UTC'}) : '—';
  const PR = {P1: 'bad', P2: 'bad', P3: 'warn', P4: 'idle'};
  const VD = {CONFIRMED: 'ok', CORROBORATED: 'ok', DISPUTED: 'warn', DEBUNKED: 'bad', UNVERIFIED: 'idle'};
  const LANG = (l) => !l ? 'x' : l.startsWith('sr') ? 'sr' : ['sq', 'en', 'ru'].includes(l) ? l : 'x';

  let mode = 'replay', filter = 'all', state = null;
  const open = new Set(), seen = new Set(), feedSeen = new Set();

  // ---------------------------------------------------------------- controls
  const setMode = (m) => {
    mode = m;
    $$('.wt-mode').forEach(b => { const on = b.dataset.mode === m; b.classList.toggle('on', on); b.setAttribute('aria-checked', on); });
    $$('.wt-f[data-for]').forEach(f => { f.hidden = f.dataset.for !== m; });
  };
  $$('.wt-mode').forEach(b => b.addEventListener('click', () => !state?.running && setMode(b.dataset.mode)));
  const win = $('#wt-window'), startIn = $('#wt-start');
  const fillStart = () => {
    const o = win.selectedOptions[0];
    startIn.min = o.dataset.start + 'T00:00'; startIn.max = o.dataset.end + 'T23:00';
    // the canal blast happened on the evening of 29 Nov: start there by default so the story arrives quickly
    startIn.value = win.value === 'canal_2024_11' ? '2024-11-29T12:00' : o.dataset.start + 'T00:00';
  };
  win.addEventListener('change', fillStart); fillStart();

  $('#wt-start-btn').addEventListener('click', async () => {
    const body = {mode, ai: $('#wt-ai').checked};
    if (mode === 'replay') Object.assign(body, {window: win.value, start_at: startIn.value, step_min: $('#wt-step').value});
    const r = await fetch('/api/watch/start', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(body)});
    if (!r.ok) { $('#wt-status').textContent = (await r.json().catch(() => ({}))).detail || `HTTP ${r.status}`; return; }
    open.clear(); seen.clear(); feedSeen.clear();
    draw(await r.json());
  });
  $('#wt-stop-btn').addEventListener('click', async () => draw(await (await fetch('/api/watch/stop', {method: 'POST'})).json()));
  $$('.wt-filter button').forEach(b => b.addEventListener('click', () => {
    filter = b.dataset.f; $$('.wt-filter button').forEach(x => x.classList.toggle('on', x === b)); if (state) drawStories(state);
  }));

  // ---------------------------------------------------------------- drawing
  function draw(s) {
    state = s;
    $('#wt-start-btn').hidden = s.running; $('#wt-stop-btn').hidden = !s.running;
    $$('.wt-ctl select, .wt-ctl input').forEach(x => { x.disabled = s.running; });
    if (s.running && s.mode) setMode(s.mode);
    const st = $('#wt-status');
    st.classList.toggle('on', s.running);
    if (!s.mode) st.innerHTML = '<span class="dot"></span>Idle. Choose a mode and start.';
    else {
      const what = s.mode === 'replay' ? `Replay <b>${esc(s.window)}</b> · clock <b>${esc(t(s.clock))} UTC</b> · ${s.step_min / 60} h per tick`
        : `Live accounts · last round <b>${esc(t(s.last_cycle_at))} UTC</b>`;
      const nxt = s.running && s.stage === 'wait' && s.next_cycle_at ? ` · next cycle in ${Math.max(0, Math.round((new Date(s.next_cycle_at) - Date.now()) / 1000))}s` : '';
      st.innerHTML = `<span class="dot"></span><b>${s.running ? 'RUNNING' : s.finished ? 'FINISHED' : 'STOPPED'}</b> · cycle ${s.cycle} · ${what}${s.running ? ' · stage <b>' + esc(s.stage) + '</b>' : ''}${nxt}${s.ai ? ' · Qwen labels & claim checks on' : ' · no model calls'}${s.error ? ' · last error: ' + esc(s.error) : ''}`;
    }
    const pg = $('#wt-progress');
    pg.hidden = s.mode !== 'replay';
    if (s.mode === 'replay' && s.end && s.started_at) {
      const a = new Date(startIn.value + 'Z').getTime(), b = new Date(s.end).getTime(), c = new Date(s.clock).getTime();
      $('i', pg).style.width = Math.max(0, Math.min(100, (c - a) / (b - a) * 100)) + '%';
    }
    $$('.wt-stage').forEach(x => x.classList.toggle('active', s.running && x.dataset.stage === s.stage));
    Object.entries(s.stage_counts || {}).forEach(([k, v]) => { $(`[data-c="${k}"]`).textContent = v; });
    const T = s.totals;
    $('#k-posts').textContent = T.posts.toLocaleString(); $('#k-kos').textContent = T.kosovo.toLocaleString();
    $('#k-stories').textContent = T.stories; $('#k-traced').textContent = T.traced_stories;
    $('#k-traces').textContent = T.traces ? `${T.traces} trace runs` : ''; $('#k-alerts').textContent = T.alerts;
    drawStories(s); drawFeed(s); drawLog(s);
  }

  function spark(st) {
    const pts = st.timeline.filter(p => p.t);
    if (!pts.length) return '';
    const a = new Date(pts[0].t).getTime(), b = Math.max(new Date(pts[pts.length - 1].t).getTime(), a + 1);
    const W = 600, H = 30;
    const dots = pts.map(p => { const x = 6 + (new Date(p.t).getTime() - a) / (b - a) * (W - 12);
      return `<circle class="d l-${LANG(p.lang)}" cx="${x.toFixed(1)}" cy="${H / 2}" r="${p.tier <= 1 ? 4.5 : 3.5}"><title>${esc(p.source)} · ${esc(t(p.t))} · ${esc(p.title)}</title></circle>`; }).join('');
    return `<svg class="wt-spark" viewBox="0 0 ${W} ${H}" preserveAspectRatio="none" aria-label="Posts over time, coloured by language"><line class="ax" x1="0" x2="${W}" y1="${H / 2}" y2="${H / 2}"/>${dots}</svg>`;
  }

  function storyHTML(st) {
    const o = st.origin, langs = Object.entries(st.langs).map(([l, n]) => `<span><i class="l-${LANG(l)}" style="background:var(${{sq: '--acc', sr: '--bad', en: '--ok', ru: '--warn', x: '--muted'}[LANG(l)]})"></i>${esc(l)} ${n}</span>`).join('');
    const al = st.alert ? `<div class="wt-s-alert"><b>ALERT ${esc(st.alert.priority)}</b> raised at ${esc(t(st.alert.at))} UTC${st.alert.minutes_after_first != null ? `, ${st.alert.minutes_after_first} min after the first post` : ''}${st.first_mainstream ? ` · first Tier 0–1 report: ${esc(st.first_mainstream.source)} ${esc(t(st.first_mainstream.t))}` : ''}</div>` : '';
    return `<div class="wt-s-h">
      <div class="wt-s-top"><span class="sid">${esc(st.id)}</span>
        ${st.priority ? `<span class="pill ${PR[st.priority]}">${esc(st.priority)} · TPS ${Math.round(st.tps)}</span>` : '<span class="pill idle">watching</span>'}
        ${st.verdict ? `<span class="pill ${VD[st.verdict]}">${esc(st.verdict)}${st.verdict_checked ? '' : ' · not checked'}</span>` : ''}
        ${st.traced ? `<span class="pill acc">traced ×${st.traces}</span>` : `<span class="pill idle">needs ${st.sources < 2 ? 'a 2nd account' : 'more posts'} to trace</span>`}
        ${st.acceptance ? `<span class="pill ${st.acceptance.passes ? 'ok' : 'idle'}">${st.acceptance.passes ? '✓' : '✗'} origin test</span>` : ''}
      </div>
      <div class="wt-s-t">${esc(st.title)}</div>
      <div class="wt-s-meta"><span><b>${st.posts}</b> posts</span><span><b>${st.sources}</b> accounts</span>
        ${st.traced ? `<span><b>${st.graph_posts}</b> in the trace · <b>${st.edges}</b> spread steps</span>` : ''}
        <span>${esc(t(st.first))} → ${esc(t(st.last))} UTC</span><span class="wt-langs">${langs}</span></div>
      ${o && o.source ? `<p class="wt-s-origin"><span class="lbl">Earliest observed</span><a href="/signals/${encodeURIComponent(o.signal_id)}"><b>${esc(o.source)}</b></a> (T${o.tier}) · ${esc(t(o.when))} UTC · confidence ${(o.confidence || 0).toFixed(2)}${st.amplifiers.length ? ` <span class="lbl" style="margin-left:10px">Amplified by</span>${esc(st.amplifiers.join(', '))}` : ''}</p>` : `<p class="wt-s-origin muted">Accounts so far: ${esc(st.accounts.join(', '))}</p>`}
      ${al}${spark(st)}
    </div>
    <ol class="wt-steps">${st.steps.map(x => `<li class="st-${esc(x.status)}"><span class="tr-n mono">${String(x.n || '').padStart(2, '0')}</span><b>${esc(x.title)}</b><span class="s">${esc(x.summary)}</span><span class="ms">${x.ms >= 1000 ? (x.ms / 1000).toFixed(1) + 's' : Math.round(x.ms || 0) + 'ms'}</span></li>`).join('')}</ol>
    <div class="wt-s-act">${st.traced ? `<button type="button" class="tg" aria-expanded="${open.has(st.id)}">${open.has(st.id) ? 'Hide' : 'Show'} tracing steps</button>
      <a href="/trace/${encodeURIComponent(st.event_id)}">Open full trace →</a>` : ''}<span class="muted">${st.traced ? 'last traced on ' + st.traced_posts + ' posts' : 'grouping'}</span></div>`;
  }

  function drawStories(s) {
    const box = $('#wt-stories');
    let xs = s.stories;
    if (filter === 'traced') xs = xs.filter(x => x.traced);
    if (filter === 'alert') xs = xs.filter(x => x.alert);
    // the board shows stories that matter: traced ones first, then the biggest still-forming ones
    xs = xs.filter(x => x.traced || x.posts >= 2).slice(0, 30);
    $('#wt-sn').textContent = `/${s.totals.stories} · showing ${xs.length}`;
    if (!xs.length) {
      box.innerHTML = `<div class="tr-wait">${s.mode ? 'No story with two or more posts yet.' : 'No stories yet. Start the watcher: stories appear here as posts come in, and each one is traced as it grows.'}</div>`;
      return;
    }
    const sig = JSON.stringify(xs.map(x => [x.id, x.posts, x.traces, x.priority, !!x.alert, open.has(x.id)]));
    if (box.dataset.sig === sig) return;   // nothing changed: keep the DOM (and the reader's place) as it is
    box.dataset.sig = sig;
    box.innerHTML = xs.map(st => `<article class="wt-story${st.alert ? ' alert' : ''}${open.has(st.id) ? ' open' : ''}${seen.has(st.id + st.traces) ? '' : ' fresh'}" data-id="${esc(st.id)}">${storyHTML(st)}</article>`).join('');
    xs.forEach(st => seen.add(st.id + st.traces));
    $$('.wt-story .tg', box).forEach(b => b.addEventListener('click', () => {
      const el = b.closest('.wt-story'), id = el.dataset.id;
      open.has(id) ? open.delete(id) : open.add(id);
      el.classList.toggle('open', open.has(id)); b.textContent = (open.has(id) ? 'Hide' : 'Show') + ' tracing steps';
      b.setAttribute('aria-expanded', open.has(id)); box.dataset.sig = '';
    }));
  }

  function drawFeed(s) {
    const f = $('#wt-feed');
    $('#wt-fn').textContent = `/${s.totals.kosovo}`;
    if (!s.feed.length) return;
    const sig = s.feed.map(x => x.id).join();
    if (f.dataset.sig === sig) return;
    f.dataset.sig = sig;
    f.innerHTML = s.feed.slice(0, 50).map(p => `<li class="${feedSeen.has(p.id) ? '' : 'new'}"><div class="m"><b>${esc(p.source)}</b><span>T${p.tier}</span><span>${esc(p.lang || '?')}</span><span>${esc(t(p.t))}</span><span class="to">→ ${esc(p.story)}</span></div>
      <a href="/signals/${encodeURIComponent(p.id)}">${esc(p.title)}</a></li>`).join('');
    s.feed.forEach(p => feedSeen.add(p.id));
  }

  function drawLog(s) {
    $('#wt-log').innerHTML = s.log.map(l => `<li class="${esc(l.kind)}"><span class="m">#${l.cycle} ${esc(t(l.clock || l.at))}</span>${esc(l.text)}</li>`).join('')
      || '<li class="muted">Nothing yet.</li>';
  }

  // ---------------------------------------------------------------- accounts
  let allAcc = false;
  $('#wt-acc-more').addEventListener('click', () => { allAcc = !allAcc; loadAccounts(); });
  async function loadAccounts() {
    const acc = await (await fetch('/api/watch/accounts')).json();
    const live = acc.filter(a => a.live);
    $('#k-acc').textContent = live.length; $('#k-acc-s').textContent = `of ${acc.length} in the registry`;
    $('#wt-live-n').textContent = `${live.length} live accounts (news, official, mirror); Telegram and X are later phases`;
    $('#wt-an').textContent = `/${acc.length} · ${live.length} live`;
    acc.sort((a, b) => (b.session_kosovo - a.session_kosovo) || (b.live - a.live) || a.tier - b.tier);
    const shown = allAcc ? acc : acc.slice(0, 15);
    $('#wt-acc-more').textContent = allAcc ? 'Show fewer' : `Show all ${acc.length} accounts`;
    $('#wt-acc tbody').innerHTML = shown.map(a => `<tr class="${a.live ? '' : 'off'}"><td>${a.archived ? `<a href="/signals?source=${encodeURIComponent(a.id)}">${esc(a.name)}</a>` : esc(a.name)}${a.bias ? `<br><span class="muted" style="font-size:11.5px">${esc(a.bias)}</span>` : ''}</td>
      <td>${esc(a.platform)}</td><td><span class="pill t${a.tier}">T${a.tier}</span></td>
      <td>${a.live ? '<span class="pill ok">watched live</span>' : `<span class="pill idle">${esc(a.status)}</span>`}</td>
      <td class="mono">${a.session_posts ? `${a.session_kosovo} / ${a.session_posts}` : '—'}</td><td class="mono">${a.archived.toLocaleString()}</td>
      <td class="mono">${esc(a.last_post ? t(a.last_post) : '—')}</td></tr>`).join('');
  }

  async function poll() {
    try { draw(await (await fetch('/api/watch/state')).json()); } catch (e) { /* server restarting: try again */ }
    setTimeout(poll, state?.running ? 1500 : 4000);
  }
  let n = 0;
  const accLoop = async () => { try { await loadAccounts(); } catch (e) {} setTimeout(accLoop, state?.running ? 8000 : 30000); n++; };
  poll(); accLoop();
})();
