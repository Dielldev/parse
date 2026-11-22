// Agents page. Two ways to send an agent:
//   social tabs (Telegram, Discord, Reddit, X) → the browser scout: a real browser, mirrored live here;
//   News sites → the bulk field agents (search API / RSS), one per site in parallel.
(() => {
  const $ = (s, el = document) => el.querySelector(s);
  const $$ = (s, el = document) => [...el.querySelectorAll(s)];
  const esc = (t) => String(t ?? '').replace(/[&<>"']/g, c => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[c]));
  const METHODS = window.AG_METHODS || {};
  const SC = window.SC || {scout: [], accounts: {}};
  const PLAT = Object.fromEntries(SC.scout.map(p => [p.kind, p]));
  const qp = new URLSearchParams(location.search);

  let kind = 'telegram';
  let accounts = SC.accounts || {};
  let windowOpen = null;

  // ================================================================ tabs
  const consoleEl = $('#console');
  function pick(k) {
    kind = k;
    $$('.sc-tab').forEach(t => { const on = t.dataset.kind === k; t.classList.toggle('on', on); t.setAttribute('aria-selected', on); });
    consoleEl.dataset.kind = k;
    consoleEl.className = consoleEl.className.replace(/\bb-\S+/g, '').trim() + ' b-' + k;
    const social = k !== 'web';
    $('#sc-form').hidden = !social; $('#news-form').hidden = social;
    if (social) {
      const tab = $(`.sc-tab[data-kind="${k}"]`);
      $('#sc-target').placeholder = tab.dataset.placeholder;
      $('#sc-how').textContent = PLAT[k]?.how || '';
      $$('.sc-sugg[data-kind]').forEach(s => { s.hidden = s.dataset.kind !== k; });
      $('#sc-err').hidden = true;
      drawAccount();
      syncChips();
    }
  }
  $$('.sc-tab').forEach(t => t.addEventListener('click', () => pick(t.dataset.kind)));
  // Where: chips toggle channels in and out of the field ("@a, @b"); "All channels" empties it (registry sweep).
  const parts = () => $('#sc-target').value.split(/[\s,]+/).filter(Boolean);
  function syncChips() {
    const cur = parts().map(x => x.toLowerCase());
    $$(`.sc-sugg[data-kind="${kind}"] .sc-chip`).forEach(c =>
      c.classList.toggle('on', c.dataset.v ? cur.includes(c.dataset.v.toLowerCase()) : !cur.length));
    const topic = $('#sc-topic').value.trim().toLowerCase();
    $$('.sc-topic-chip').forEach(c => c.classList.toggle('on', c.dataset.v.toLowerCase() === topic));
    sendLabel();
  }
  function sendLabel() {
    const n = parts().length, topic = $('#sc-topic').value.trim(), one = parts()[0];
    const where = {
      telegram: n ? (n > 1 ? `${n} channels` : one) : 'all channels',
      reddit: n ? (n > 1 ? `${n} subreddits` : one) : 'all of Reddit',
      x: n ? (n > 1 ? `${n} accounts` : one) : 'all of X',
      discord: 'the channel',
    }[kind];
    if (!where) return;
    const t = topic.length > 22 ? topic.slice(0, 22) + '…' : topic;
    $('#sc-send-label').textContent = topic ? `Search ${where} for “${t}”` : `Read the latest from ${where}`;
  }
  $$('.sc-sugg[data-kind] .sc-chip').forEach(c => c.addEventListener('click', () => {
    const v = c.dataset.v;
    if (!v) $('#sc-target').value = '';
    else if (kind === 'discord') $('#sc-target').value = v;
    else {
      const cur = parts(), i = cur.findIndex(x => x.toLowerCase() === v.toLowerCase());
      if (i >= 0) cur.splice(i, 1); else cur.push(v);
      $('#sc-target').value = cur.join(', ');
    }
    syncChips();
  }));
  $$('.sc-topic-chip').forEach(c => c.addEventListener('click', () => {
    $('#sc-topic').value = c.classList.contains('on') ? '' : c.dataset.v; syncChips(); $('#sc-topic').focus();
  }));
  $('#sc-target').addEventListener('input', syncChips);
  $('#sc-topic').addEventListener('input', syncChips);

  // ================================================================ agent-browser account (log in once, join servers)
  function drawAccount() {
    const box = $('#sc-acct'), p = PLAT[kind];
    const needs = p && (p.login || kind === 'reddit');
    box.hidden = !needs;
    if (!needs) return;
    const a = accounts[kind], ok = a && a.connected;
    box.classList.toggle('ok', !!ok);
    const btn = $('#sc-window');
    if (windowOpen) {
      $('#sc-acct-text').innerHTML = `<b>The agent browser is open on your screen.</b> Log in${kind === 'discord' ? ', join the servers you want watched,' : ''} then press Done.`;
      btn.textContent = 'Done'; btn.classList.add('live'); return;
    }
    btn.classList.remove('live');
    const texts = {
      discord: ok ? `<b>Agent logged in to Discord</b> (checked ${esc(a.at)}). To watch a new server, open the agent browser and join it yourself.`
                  : '<b>Log the agent browser in to Discord once.</b> Use a separate research account: automating a personal account breaks Discord’s rules and can get it banned.',
      x: ok ? `<b>Agent logged in to X</b> (checked ${esc(a.at)}).` : '<b>X shows nothing logged out.</b> Log the agent browser in once, ideally with a research account.',
      reddit: ok ? `<b>Agent logged in to Reddit</b> (checked ${esc(a.at)}).` : 'No login needed. If Reddit blocks the browser, log it in once here.',
    };
    $('#sc-acct-text').innerHTML = texts[kind];
    btn.textContent = ok ? (kind === 'discord' ? 'Open agent browser' : 'Open agent browser') : 'Log in once';
  }
  $('#sc-window').addEventListener('click', async () => {
    if (windowOpen) { await fetch('/api/scout/window-close', {method: 'POST'}); return; }
    const r = await fetch(`/api/scout/window/${kind}`, {method: 'POST'});
    if (!r.ok) { showErr((await r.json()).detail); return; }
    windowOpen = kind; drawAccount(); pollStatus();
  });
  async function pollStatus() {
    try {
      const d = await (await fetch('/api/scout/status')).json();
      accounts = d.accounts || {};
      if (d.window) { windowOpen = d.window; setTimeout(pollStatus, 1200); }
      else { windowOpen = null; refreshAcctPills(); }
    } catch (e) { setTimeout(pollStatus, 2000); }
    drawAccount();
  }
  function refreshAcctPills() {
    $$('.sc-tab-st[data-acct]').forEach(el => {
      const p = PLAT[el.dataset.acct]; if (!p || !p.login) return;
      const ok = accounts[el.dataset.acct]?.connected;
      el.innerHTML = ok ? '<i class="ok"></i>Agent logged in' : '<i class="warn"></i>Log in once';
    });
  }
  if (SC.busy === 'window') pollStatus();

  function showErr(msg) { const e = $('#sc-err'); e.textContent = msg; e.hidden = false; }

  // ================================================================ depth pickers (one per form)
  const depth = {sc: 10, news: 10};
  $$('.ag-depth').forEach(g => {
    const which = g.closest('#news-form') ? 'news' : 'sc';
    $$('button', g).forEach(b => b.addEventListener('click', () => {
      depth[which] = +b.dataset.n;
      $$('button', g).forEach(x => { x.classList.toggle('on', x === b); x.setAttribute('aria-checked', x === b); });
    }));
  });

  // ================================================================ browser scout
  $('#sc-topic').addEventListener('keydown', e => { if (e.key === 'Enter') $('#sc-send').click(); });
  $('#sc-target').addEventListener('keydown', e => { if (e.key === 'Enter') $('#sc-topic').focus(); });
  $('#sc-send').addEventListener('click', async () => {
    const btn = $('#sc-send'); btn.disabled = true; btn.classList.add('busy'); $('#sc-err').hidden = true;
    try {
      const r = await fetch('/api/scout/start', {method: 'POST', headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({platform: kind, target: $('#sc-target').value.trim(), topic: $('#sc-topic').value.trim(),
                              limit: depth.sc, headed: $('#sc-headed').checked})});
      const d = await r.json();
      if (!r.ok) throw new Error(d.detail || r.status);
      watchScout(d.run_id);
    } catch (err) { showErr(err.message); }
    finally { btn.disabled = false; btn.classList.remove('busy'); }
  });

  const AV = ['#2aabee', '#5865f2', '#ff4500', '#2c7a4e', '#b8873a', '#7a6ff0', '#c2410c', '#0e7490'];
  const avColor = (s) => AV[[...String(s || '?')].reduce((a, c) => a + c.charCodeAt(0), 0) % AV.length];
  const initial = (s) => esc(String(s || '?').replace(/^[@u\/]+/, '').charAt(0).toUpperCase() || '?');
  const when = (iso) => { if (!iso) return ''; const d = new Date(iso); return isNaN(d) ? '' :
    d.toLocaleString(undefined, {day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit'}); };
  const EYE = '<svg viewBox="0 0 24 24"><path d="M2 12s4-7 10-7 10 7 10 7-4 7-10 7S2 12 2 12Z"/><circle cx="12" cy="12" r="3"/></svg>';
  const UP = '<svg viewBox="0 0 24 24"><path d="M12 4 4 13h5v7h6v-7h5z"/></svg>', DOWN = '<svg viewBox="0 0 24 24"><path d="M12 20l8-9h-5V4H9v7H4z"/></svg>';

  function flags(p) {
    return (p.matched || p.tags.length) ? `<div class="pc-tags">${p.kept ? '<span class="pc-flag kept">Archived</span>' : (p.matched ? '<span class="pc-flag match">Match</span>' : '')}
      ${p.tags.map(t => `<span class="pc-tag">${esc(t)}</span>`).join('')}</div>` : '';
  }
  function card(p) {
    const link = p.signal_id ? `/signals/${encodeURIComponent(p.signal_id)}` : p.url;
    const a = link ? `<a class="pc-link" href="${esc(link)}" ${p.signal_id ? '' : 'target="_blank" rel="noopener noreferrer"'} aria-label="Open post"></a>` : '';
    const img = p.image && /^https:/.test(p.image) ? `<img class="pc-img" src="${esc(p.image)}" alt="" loading="lazy" referrerpolicy="no-referrer">` : '';
    const txt = `<p class="pc-txt">${esc(p.text)}</p>`;
    const cls = `pc pc-${p.platform} ${p.matched ? 'hit' : ''} ${p.kind === 'comment' ? 'comment' : ''}`;
    if (p.platform === 'telegram') {
      return `<li class="${cls}"><span class="pc-av" style="background:${avColor(p.author)}">${initial(p.author)}</span><div class="pc-b">${a}
        <div class="pc-who">${esc(p.author || 'Channel')}</div>
        ${p.forwarded ? `<div class="pc-fwd">Forwarded from ${esc(String(p.forwarded).replace('https://t.me/', '@'))}</div>` : ''}
        ${txt}${img}<div class="pc-meta">${p.views ? `${EYE} ${esc(p.views)} ·` : ''} ${esc(when(p.time))}</div>${flags(p)}</div></li>`;
    }
    if (p.platform === 'discord') {
      return `<li class="${cls}">${a}<span class="pc-av" style="background:${avColor(p.author)}">${initial(p.author)}</span><div style="min-width:0;flex:1">
        <div class="pc-meta"><b>${esc(p.author || 'member')}</b> ${esc(when(p.time))}</div>${txt}${img}
        ${p.reactions ? `<span class="pc-react">${esc(p.reactions)} reactions</span>` : ''}${flags(p)}</div></li>`;
    }
    if (p.platform === 'reddit') {
      if (p.kind === 'comment') {
        return `<li class="${cls}"><div class="pc-body">${a}<div class="pc-meta"><b>u/${esc(p.author || '[deleted]')}</b> · ${esc(when(p.time))}${p.score ? ` · ${esc(p.score)} pts` : ''}</div>
          ${txt}${flags(p)}</div></li>`;
      }
      return `<li class="${cls}"><div class="pc-vote">${UP}<span>${esc(p.score ?? '•')}</span>${DOWN}</div><div class="pc-body">${a}
        <div class="pc-meta"><b>${esc(p.sub || '')}</b> · u/${esc(p.author || '?')} · ${esc(when(p.time))}</div>
        <div class="pc-title">${esc(p.title || '')}</div>${p.text ? txt : ''}${img}
        <div class="pc-foot">${esc(p.replies ?? 0)} comments</div>${flags(p)}</div></li>`;
    }
    // x
    const m = String(p.metrics || '').replace(/(\d)\s+/g, '$1 ').split(',').slice(0, 4).join(' · ');
    return `<li class="${cls}">${a}<span class="pc-av" style="background:${avColor(p.author)}">${initial(p.name || p.author)}</span><div class="pc-body">
      <div class="pc-who"><b>${esc(p.name || '')}</b> ${esc(p.author || '')} · ${esc(when(p.time))}</div>${txt}${img}
      ${m ? `<div class="pc-foot">${esc(m)}</div>` : ''}${flags(p)}</div></li>`;
  }

  let scoutPoll = null;
  function watchScout(runId) {
    if (scoutPoll) clearTimeout(scoutPoll);
    const live = $('#sc-live'); live.hidden = false;
    $('#sc-live-id').textContent = '/ ' + runId.slice(-8);
    $('#sc-posts').innerHTML = '<li class="sc-posts-empty">Posts show up here as the scout reads them.</li>';
    $('#sc-steps').innerHTML = ''; $('#sc-targets').innerHTML = ''; $('#sc-sum').hidden = true;
    $('#sc-boot').hidden = false; $('#sc-boot-t').textContent = 'Opening the agent browser…';
    $('#sc-ctl').className = 'sc-ctl'; $('#sc-ctl').innerHTML = '<i></i>Agent in control';
    $('#sc-stop').disabled = false; $('#sc-url').textContent = 'about:blank';
    const img = $('#sc-img'); img.removeAttribute('src');
    live.scrollIntoView({behavior: 'smooth', block: 'start'});
    const st = {read: 0, match: 0, kept: 0, t0: performance.now(), done: false, topic: '', platform: kind};
    const timer = setInterval(() => { if (!st.done) $('#sc-t').textContent = Math.round((performance.now() - st.t0) / 1000) + 's'; }, 500);
    const rows = {};
    let after = 0, streaming = false;
    const draw = () => { $('#sc-n-read').textContent = st.read; $('#sc-n-match').textContent = st.match; $('#sc-n-kept').textContent = st.kept; };
    const ICONS = {launch: 'open', goto: 'go', type: 'type', scroll: 'scroll', read: 'read', done: 'done'};

    function step(ev) {
      const li = document.createElement('li'); li.className = 'sc-step';
      li.innerHTML = `<span>${(ev.at || 0).toFixed(1)}s</span><b>${esc(ICONS[ev.action] || ev.action)}</b><span>${esc(ev.text)}</span>`;
      const ol = $('#sc-steps'); ol.prepend(li);
      while (ol.children.length > 7) ol.lastChild.remove();
      if (ev.url) $('#sc-url').textContent = ev.url;
      if (!streaming && ev.action !== 'launch') {  // the browser is up: start the MJPEG mirror
        streaming = true; img.src = `/api/scout/runs/${encodeURIComponent(runId)}/live.mjpg`;
        img.onload = () => { $('#sc-boot').hidden = true; };
        setTimeout(() => { $('#sc-boot').hidden = true; }, 2500);
      }
    }

    function onEvent(ev) {
      if (ev.t === 'start') {
        st.topic = ev.topic; st.platform = ev.platform;
        $('#sc-live-topic').textContent = (PLAT[ev.platform]?.name || ev.platform) + ' · ' +
          (ev.topic ? `looking for “${ev.topic}”` : 'reading the newest posts') + (ev.headed ? ' · browser visible on this screen' : '');
        $('#sc-feed-title').textContent = `What it's reading on ${PLAT[ev.platform]?.name || ''}`;
        for (const t of ev.targets) {
          const li = document.createElement('li'); li.className = 'sc-target queued';
          li.innerHTML = `<span class="ag-sq" aria-hidden="true"></span><b>${esc(t.label)}</b><span>waiting</span>`;
          $('#sc-targets').appendChild(li); rows[t.id] = li;
        }
      } else if (ev.t === 'step') step(ev);
      else if (ev.t === 'url') $('#sc-url').textContent = ev.url;
      else if (ev.t === 'target_info' && rows[ev.target]) {
        $('b', rows[ev.target]).textContent = ev.title + (ev.meta ? ` · ${ev.meta}` : '');
      } else if (ev.t === 'target' && rows[ev.target]) {
        const li = rows[ev.target];
        li.className = 'sc-target ' + ev.state;
        $('span:last-of-type', li).textContent = ev.state === 'visiting' ? 'reading…' : (ev.note || ev.state);
        if (ev.state === 'login' && PLAT[st.platform]) {
          const b = document.createElement('button'); b.className = 'sc-ghost'; b.textContent = 'Log in once';
          b.addEventListener('click', () => { pick(st.platform); $('#console').scrollIntoView({behavior: 'smooth'}); setTimeout(() => $('#sc-window').click(), 400); });
          li.appendChild(b);
        }
      } else if (ev.t === 'post') {
        st.read++; if (ev.matched) st.match++; if (ev.kept) st.kept++;
        $('.sc-posts-empty')?.remove();
        $('#sc-posts').insertAdjacentHTML('afterbegin', card(ev));
        const ol = $('#sc-posts'); while (ol.children.length > 120) ol.lastChild.remove();
        draw();
      } else if (ev.t === 'note') {
        step({action: 'note', text: ev.text, at: ev.at});
      } else if (ev.t === 'end') {
        st.done = true; clearInterval(timer);
        $('#sc-ctl').className = 'sc-ctl off'; $('#sc-ctl').innerHTML = `<i></i>${ev.status === 'stopped' ? 'Stopped' : 'Control returned'}`;
        $('#sc-stop').disabled = true; $('#sc-boot').hidden = true;
        // keep the last frame on screen once the stream ends
        setTimeout(() => { img.src = `/api/scout/runs/${encodeURIComponent(runId)}/frame.jpg?t=${Date.now()}`; }, 300);
        summary(ev, st);
        loadHistory();
      }
    }

    async function poll() {
      try {
        const r = await fetch(`/api/scout/runs/${encodeURIComponent(runId)}?after=${after}`);
        if (r.ok) {
          const d = await r.json();
          d.events.forEach(onEvent); after = d.next;
          if (st.done) return;
        }
      } catch (e) { /* keep trying */ }
      scoutPoll = setTimeout(poll, 400);
    }
    $('#sc-stop').onclick = async () => { $('#sc-stop').disabled = true; await fetch(`/api/scout/runs/${encodeURIComponent(runId)}/stop`, {method: 'POST'}); };
    draw(); poll();
  }
  $('#sc-only').addEventListener('change', e => $('#sc-posts').classList.toggle('only', e.target.checked));

  function summary(ev, st) {
    const box = $('#sc-sum'); box.hidden = false;
    const max = Math.max(1, ...ev.tags.map(t => t[1]));
    const q = st.topic;
    box.innerHTML = `
      <div><h4>Result</h4>
        <p><b>${ev.read} post${ev.read === 1 ? '' : 's'} read, ${ev.matched} matched, ${ev.kept} new archived.</b>
        ${ev.kept ? 'Ask Atlas can cite them now.' : (ev.matched ? 'The matches were already in the archive.' : 'Nothing matched this time.')}</p>
        ${q ? `<a class="ag-btn" href="/?q=${encodeURIComponent(q)}">Ask Atlas about “${esc(q)}” →</a>` : `<a class="ag-btn" href="/signals?platform=${encodeURIComponent(st.platform)}">Open signals →</a>`}</div>
      <div><h4>Framing in what it kept</h4>
        ${ev.tags.length ? ev.tags.map(([t, n]) => `<div class="sc-bar"><span>${esc(t)}</span><i style="width:${Math.round(n / max * 100)}%"></i><em>${n}</em></div>`).join('')
          : '<p>No keyword groups hit.</p>'}</div>
      <div><h4>${ev.forwarded.length ? 'Forwarded from' : 'Most active authors'}</h4>
        ${(ev.forwarded.length ? ev.forwarded : ev.authors).length
          ? `<ol>${(ev.forwarded.length ? ev.forwarded : ev.authors).map(([a, n]) => `<li>${esc(String(a).replace('https://t.me/', '@'))} <span class="muted">· ${n}</span></li>`).join('')}</ol>`
          : '<p>—</p>'}</div>`;
  }

  // ================================================================ news sites: bulk field agents
  const newsBoxes = () => $$('#news-form .ag-chip input[type=checkbox]').filter(b => !b.disabled);
  function refreshNews() {
    const all = newsBoxes(), n = all.filter(b => b.checked).length;
    $('#dispatch-label').textContent = n ? `Dispatch ${n} agent${n === 1 ? '' : 's'}` : 'Choose at least one site';
    $('#dispatch').disabled = !n;
    $('#news-count').textContent = n === all.length ? `all ${n} live sites` : `${n} of ${all.length} live sites`;
  }
  $$('[data-sel]').forEach(b => b.addEventListener('click', () => { newsBoxes().forEach(x => { x.checked = b.dataset.sel === 'ready'; }); refreshNews(); }));
  document.addEventListener('change', e => { if (e.target.matches('.ag-chip input')) refreshNews(); });
  refreshNews();
  $('#topic').addEventListener('keydown', e => { if (e.key === 'Enter') $('#dispatch').click(); });

  let polling = null;
  $('#dispatch').addEventListener('click', async () => {
    const sources = newsBoxes().filter(b => b.checked).map(b => b.value);
    if (!sources.length) return;
    const btn = $('#dispatch'); btn.disabled = true; btn.classList.add('busy');
    try {
      const r = await fetch('/api/agents/dispatch', {method: 'POST', headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({kind: 'web', sources, topic: $('#topic').value.trim(), limit: depth.news})});
      if (!r.ok) throw new Error((await r.json()).detail || r.status);
      watch((await r.json()).run_id);
    } catch (err) { alert('Could not dispatch: ' + err.message); }
    finally { btn.classList.remove('busy'); refreshNews(); }
  });

  function watch(runId) {
    if (polling) clearTimeout(polling);
    const live = $('#live'); live.hidden = false;
    $('#live-id').textContent = '/ ' + runId.slice(-8);
    $('#agents').innerHTML = ''; $('#finds').innerHTML = '<li class="ag-finds-empty">Findings appear here the moment an agent keeps one.</li>';
    $('#after').hidden = true; $('#finds-n').textContent = '';
    live.scrollIntoView({behavior: 'smooth', block: 'start'});
    const st = {total: 0, visited: 0, kept: 0, problems: 0, t0: performance.now(), done: false, topic: ''};
    const timer = setInterval(() => { if (!st.done) $('#st-time').textContent = ((performance.now() - st.t0) / 1000).toFixed(1) + 's'; }, 100);
    const rows = {};
    let after = 0;
    const draw = () => {
      $('#st-visited').textContent = `${st.visited}/${st.total}`;
      $('#st-kept').textContent = st.kept;
      $('#st-problems').textContent = st.problems;
      $('#st-problems').parentElement.classList.toggle('hot', st.problems > 0);
    };
    function onEvent(ev) {
      if (ev.t === 'start') {
        st.total = ev.sources.length; st.topic = ev.topic;
        $('#live-topic').textContent = ev.topic ? `Looking for “${ev.topic}”` + (ev.terms.length ? ` · terms: ${ev.terms.join(', ')}` : '') : 'Newest Kosovo items';
        for (const s of ev.sources) {
          const li = document.createElement('li');
          li.className = 'ag-agent queued';
          li.innerHTML = `<span class="ag-sq" aria-hidden="true"></span>
            <span class="ag-code m-${esc(s.method)}">${esc(METHODS[s.method]?.short || '—')}</span>
            <span class="ag-agent-name">${esc(s.name)}<i>T${s.tier}</i></span>
            <span class="ag-agent-kept"></span><span class="ag-agent-note">waiting</span>`;
          $('#agents').appendChild(li); rows[s.id] = li;
        }
      } else if (ev.t === 'source') {
        const li = rows[ev.source]; if (!li) return;
        li.className = 'ag-agent ' + ev.state;
        if (ev.state === 'visiting') { $('.ag-agent-note', li).textContent = 'connecting…'; return; }
        st.visited++;
        if (['error', 'blocked', 'setup'].includes(ev.state)) st.problems++;
        $('.ag-agent-note', li).textContent = ev.note || ev.state;
        $('.ag-agent-kept', li).textContent = ev.kept ? `+${ev.kept}` : '';
        draw();
      } else if (ev.t === 'note' && ev.source && rows[ev.source]) {
        $('.ag-agent-note', rows[ev.source]).textContent = ev.text;
      } else if (ev.t === 'item') {
        st.kept++;
        $('.ag-finds-empty')?.remove();
        const name = $('.ag-agent-name', rows[ev.source])?.firstChild?.textContent || ev.source;
        const li = document.createElement('li'); li.className = 'ag-find';
        li.innerHTML = `<a href="/signals/${encodeURIComponent(ev.id)}"><span class="ag-find-src">${esc(name)}</span>
          <span class="ag-find-t">${esc(ev.title || '(no title)')}</span><span class="ag-find-m">${esc(ev.date || 'undated')} · ${esc(ev.lang || '?')}</span></a>`;
        $('#finds').prepend(li); $('#finds-n').textContent = '· ' + st.kept;
        draw();
      } else if (ev.t === 'end') {
        st.done = true; clearInterval(timer);
        const q = st.topic, box = $('#after'); box.hidden = false;
        box.innerHTML = `<p><b>${ev.kept ? `${ev.kept} new item${ev.kept === 1 ? '' : 's'} archived.` : 'Nothing new this time.'}</b>
          ${ev.kept ? 'They are already in the archive, so Ask Atlas will use them.' : 'Everything these sources had on the topic was already in the archive, or nothing matched.'}</p>
          ${q ? `<a class="ag-btn" href="/?q=${encodeURIComponent(q)}">Ask Atlas about “${esc(q)}” →</a>` : `<a class="ag-btn" href="/signals">Open signals →</a>`}`;
        loadHistory();
      }
    }
    async function poll() {
      try {
        const r = await fetch(`/api/agents/runs/${encodeURIComponent(runId)}?after=${after}`);
        if (r.ok) { const d = await r.json(); d.events.forEach(onEvent); after = d.next; if (d.status !== 'running' && st.done) return; }
      } catch (e) { /* keep trying */ }
      polling = setTimeout(poll, 600);
    }
    draw(); poll();
  }

  async function loadHistory() {
    try {
      const {runs} = await (await fetch('/api/agents/runs')).json();
      $('#history').innerHTML = '<tr><th>When</th><th>Where</th><th>Topic</th><th>From</th><th class="n">Sources</th><th class="n">Kept</th><th>Status</th></tr>' +
        runs.map(r => `<tr><td class="mono">${esc(r.created)}</td><td>${esc(r.kind_name)}</td><td>${esc(r.topic || '—')}</td>
          <td class="muted">${esc(r.origin)}</td><td class="n">${r.sources}</td><td class="n">${r.kept}</td>
          <td><span class="pill ${r.status === 'done' && !r.problems ? 'ok' : (['done', 'running', 'stopped'].includes(r.status) ? 'warn' : 'bad')}">${esc(r.status)}${r.problems ? ` · ${r.problems} issues` : ''}</span></td></tr>`).join('');
    } catch (e) { /* history is a convenience */ }
  }

  // ================================================================ deep links: ?topic=…, ?dest=…
  if (qp.get('topic')) { $('#sc-topic').value = qp.get('topic'); $('#topic').value = qp.get('topic'); }
  const dest = qp.get('dest');
  pick(dest && $(`.sc-tab[data-kind="${dest}"]`) ? dest : 'telegram');
})();
