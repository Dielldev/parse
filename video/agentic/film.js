/* Parse · the agentic loop. 30 s, 1920x1080, 60 fps, 120 BPM (a beat every 0.5 s, a bar every 2 s).
   One continuous camera, every shot made out of the previous one:
     0-2   hook        "Dashboards wait. Agents don't." The word Agents lands on the agent's own badge.
     2-6   scout       the real browser scout on Telegram (captured run, every frame real, speed-ramped).
     6-10  field agents the browser collapses to a tile; 46 site agents run in a waterfall built from their real event log.
     10-18 signals     back-test of the canal window: Qwen3-8B labels, the rights rule, one story, its score, the P1.
     18-28 ask         the question types, eleven real workflow steps run with their real timings, the cited answer.
     28-30 end         the answer folds into the PARSE mark.
   window.seek(t) writes every animated style from t; window.FILM.CUES drives the soundtrack (audio.js). */
(() => {
  'use strict';
  const { clamp, lerp, P, ez, T, spring, rng, monoCubic, $, $$, esc, f2, st, cls, text, html, attr, show, fmt, mk, svgEl,
    split, roll, clipIn, rise, countTo, ulidTime } = window.L;
  const DUR = 30;
  let D = null;
  const CUES = [];
  const cue = (t, kind, v = 1) => CUES.push({ t: +t.toFixed(4), kind, v });
  const SC = [];
  const frame = () => $('#frame');
  function layer(name, z) {
    const el = mk('div', `layer sc-${name}`, null, $('#scenes'));
    el.style.zIndex = z;
    return el;
  }
  function scene(name, t0, t1, z) {
    const s = { name, t0, t1, el: layer(name, z), seek: () => {} };
    SC.push(s);
    return s;
  }
  const rectOf = (el) => { const a = el.getBoundingClientRect(), f = frame().getBoundingClientRect(); return { x: a.left - f.left, y: a.top - f.top, w: a.width, h: a.height }; };
  const ICON = {
    bolt: '<path d="M13 3 5 14h6l-1 7 8-11h-6z"/>', type: '<path d="M5 6V4h14v2M12 4v16M9 20h6"/>',
    send: '<path d="M4 12h15M13 6l6 6-6 6"/>', book: '<path d="M5 4h11a3 3 0 0 1 3 3v13H8a3 3 0 0 1-3-3z"/><path d="M5 17a3 3 0 0 1 3-3h11"/>',
    database: '<ellipse cx="12" cy="6" rx="7" ry="3"/><path d="M5 6v12c0 1.7 3.1 3 7 3s7-1.3 7-3V6M5 12c0 1.7 3.1 3 7 3s7-1.3 7-3"/>',
    globe: '<circle cx="12" cy="12" r="9"/><path d="M3 12h18M12 3c3 3.2 3 14.8 0 18M12 3c-3 3.2-3 14.8 0 18"/>',
    sort: '<path d="M7 4v16M3 16l4 4 4-4M17 20V4M13 8l4-4 4 4"/>', lock: '<rect x="5" y="10" width="14" height="10"/><path d="M8 10V7a4 4 0 0 1 8 0v3"/>',
    spark: '<path d="M12 3v5M12 16v5M3 12h5M16 12h5M6 6l3 3M15 15l3 3M6 18l3-3M15 9l3-3"/>',
    branch: '<circle cx="6" cy="5" r="2"/><circle cx="6" cy="19" r="2"/><circle cx="18" cy="12" r="2"/><path d="M6 7v10M6 12h4a6 6 0 0 0 6 0"/>',
    file: '<path d="M6 3h8l4 4v14H6z"/><path d="M14 3v4h4M9 12h6M9 16h6"/>',
    check: '<path d="m5 12.5 4.5 4.5L19 7"/>', clock: '<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/>',
    lang: '<path d="M4 5h9M8.5 3v2M6 5c.8 3.5 3 6 6 7.5M11 5c-.8 3.5-3 6-6 7.5"/><path d="m12 21 4-9 4 9M13.5 18h5"/>',
    up: '<path d="M12 19V5M5 12l7-7 7 7"/>', shield: '<path d="M12 3 4 6v6c0 4.5 3.4 8.3 8 9 4.6-.7 8-4.5 8-9V6z"/><path d="m8.5 12 2.5 2.5 4.5-4.5"/>',
  };
  const ico = (k) => `<svg viewBox="0 0 24 24" aria-hidden="true">${ICON[k]}</svg>`;
  // the product's classification-strip stars (base.html stars macro)
  const STARS = '<svg class="stars" viewBox="0 0 132 30" aria-hidden="true">' + [[8, 24], [30, 13], [54, 7], [78, 7], [102, 13], [124, 24]].map(([x, y]) =>
    `<path fill="currentColor" transform="translate(${x} ${y})" d="M0-5.5 1.3-1.8 5.2-1.7 2.1.7 3.2 4.5 0 2.2-3.2 4.5-2.1.7-5.2-1.7-1.3-1.8z"/>`).join('') + '</svg>';

  // ================================================================ HUD (persists through the film)
  function buildHud() {
    const h = mk('div', 'hud', null, $('#frame'));
    const scoutAt = ulidTime(D.scout.run_id), agentAt = ulidTime(D.agents.run_id);
    const local = new Intl.DateTimeFormat('en-GB', { timeZone: 'Europe/Belgrade', hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false });
    const utc = new Intl.DateTimeFormat('en-GB', { timeZone: 'UTC', hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false });
    const day = (d) => d.toLocaleDateString('en-GB', { day: '2-digit', month: 'short', year: 'numeric', timeZone: 'UTC' }).toUpperCase();
    const hm = (d) => d.toISOString().slice(11, 16);
    h.innerHTML = `<div class="cbar"><span class="l">${STARS}<span><b>UNCLASSIFIED</b> // OSINT RESEARCH · KOSOVO THEATRE · SQ · SR · EN</span></span>
      <span class="r"><span class="live">LOCAL · READ-ONLY</span><span class="prn"></span><span class="utc"></span></span></div>
      <div class="corners"><i></i><i></i><i></i><i></i></div>
      <div class="readout"><span class="l"><span class="slot sl"></span></span><span class="c"><span class="slot sc"></span></span><span class="r">SECTOR KOS · GRID 34T</span></div>`;
    const chapters = [
      [0, '<b>/0.0</b> — PARSE', 'OSINT EARLY WARNING · KOSOVO', null],
      [2.0, '<b>/01</b> — AGENTS', `<span class="prov">LIVE RUN · ${day(scoutAt)} · ${hm(scoutAt)} UTC · TELEGRAM SCOUT</span>`, '#d0a650'],
      [6.2, '<b>/01</b> — AGENTS', `<span class="prov">LIVE RUN · ${day(agentAt)} · ${hm(agentAt)} UTC · 46 FIELD AGENTS</span>`, '#d0a650'],
      [10.1, '<b>/02</b> — SIGNALS', '<span class="prov">BACK-TEST · 29 NOV 2024 · CANAL WINDOW REPLAYED AS IF LIVE</span>', '#4f7dff'],
      [17.6, '<b>/03</b> — ASK', `<span class="prov">LIVE QUERY · ${day(agentAt)} · ANSWERED IN ${(D.ask.answer.ms / 1000).toFixed(1)} S</span>`, '#ffffff'],
      [28.0, '<b>/0.4</b> — PARSE', '<b>PRISHTINË / PRIŠTINA</b> · 42.6629° N · 21.1655° E', null],
    ];
    const sl = $('.sl', h), sc = $('.sc', h);
    const L = chapters.map(([t, a]) => mk('span', '', a, sl)), C = chapters.map(([t, , b, c]) => { const e = mk('span', '', b, sc); if (c) e.style.setProperty('--c', c); return e; });
    // slot widths: widest text
    requestAnimationFrame(() => {});
    const prn = $('.prn', h), u = $('.utc', h), corners = $$('.corners i', h), cbar = $('.cbar', h), ro = $('.readout', h);
    return (t) => {
      const now = new Date(scoutAt.getTime() - 2000 + t * 1000);
      html(prn, `<b>PRN</b> ${local.format(now)}`); text(u, `${utc.format(now)} UTC`);
      const cp = T(t, 0.02, 0.45);
      st(cbar, { transform: `translateY(${f2((cp - 1) * 44)}px)` });
      corners.forEach((c, i) => { const p = T(t, 0.08 + i * 0.05, 0.55); st(c, { opacity: p.toFixed(3), transform: `scale(${(0.5 + 0.5 * p).toFixed(3)})` }); });
      st(ro, { opacity: T(t, 0.2, 0.5).toFixed(3) });
      // chapter slots: the current label rolls up out, the next rolls in from below
      [[L, sl], [C, sc]].forEach(([arr, slot]) => {
        let wmax = 0; arr.forEach((e) => { wmax = Math.max(wmax, e._w || (e._w = e.getBoundingClientRect().width)); });
        st(slot, { width: `${Math.ceil(wmax) + 2}px` });
        arr.forEach((e, i) => {
          const tin = chapters[i][0], tout = i + 1 < chapters.length ? chapters[i + 1][0] : 99;
          const pi = i === 0 ? 1 : T(t, tin, 0.42, ez.roll), po = T(t, tout - 0.05, 0.3, ez.in);
          st(e, { transform: `${slot === sc ? 'translateX(-50%) ' : ''}translateY(${f2((1 - pi) * 100 - po * 100)}%)`, opacity: (pi * (1 - po)).toFixed(3) });
        });
      });
    };
  }

  // ================================================================ A. hook: "Dashboards wait. Agents don't."
  const BR = { x: 110, y: 140, w: 1180, k: 1180 / 1280 };       // the scout's browser window (frame coords at rest)
  const SCREEN_Y = BR.y + 48;
  const BADGE = { x: BR.x + 14 * BR.k, y: SCREEN_Y + 758 * BR.k, k: BR.k };   // the product's agent badge inside the footage
  function buildHook() {
    const s = scene('hook', 0, 2.6, 6);
    s.el.innerHTML = `<div class="hook"><div class="eyebrow"><span class="rule"></span><span>Parse · OSINT early warning · Kosovo</span></div>
      <div class="big l1">Dashboards wait.</div><div class="big l2"><em>Agents</em> <span class="dn">don’t.</span></div></div>
      <div class="badge-x"><i></i><span>Parse agent · read-only</span></div>`;
    const rule = $('.rule', s.el), eb = split($('.eyebrow span:last-child', s.el));
    const w1 = split($('.l1', s.el)), em = $('.l2 em', s.el), dn = split($('.dn', s.el));
    const emW = split(em);
    const badge = $('.badge-x', s.el), bTxt = split($('.badge-x span', s.el)), bDot = $('.badge-x i', s.el);
    const r0 = rectOf(em);
    // a flying copy of the word, so it can leave the line and travel to the badge
    const fly = mk('div', 'abs', '<em>Agents</em>', s.el);
    st(fly, { left: `${r0.x}px`, top: `${r0.y}px`, font: '300 172px/1.0 var(--sans)', letterSpacing: '-.055em', color: 'var(--gold)', transformOrigin: '0 0', whiteSpace: 'nowrap' });
    $('em', fly).style.fontStyle = 'normal';
    st(badge, { transform: `translate(${f2(BADGE.x)}px, ${f2(BADGE.y)}px) scale(${BADGE.k})` });
    const bw = badge.getBoundingClientRect();
    cue(0.0, 'drone'); cue(0.22, 'wordlow'); cue(1.0, 'agents'); cue(1.72, 'fly'); cue(2.0, 'open');
    s.seek = (t) => {
      st(rule, { transform: `scaleX(${T(t, 0.08, 0.5).toFixed(3)})` });
      roll(eb, t, 0.12, 1.66, { stag: 0.03, dur: 0.55, y: 100, blur: 0, seed: 4 });
      roll(w1, t, 0.2, 1.7, { stag: 0.11, dur: 0.7, seed: 2 });
      w1.forEach((w) => st(w.parentNode, { opacity: (1 - 0.66 * T(t, 0.95, 0.4, ez.io)).toFixed(3) }));
      roll(dn, t, 1.12, 1.72, { stag: 0.08, dur: 0.6, seed: 3 });
      roll(emW, t, 0.98, null, { dur: 0.6, seed: 5 });
      // hand-off: the word leaves its line at 1.72 and lands as the agent badge
      const p = T(t, 1.72, 0.34, ez.cam);
      show(em, t < 1.72); show(fly, t >= 1.72 && p < 0.97);
      if (t >= 1.72) {
        const k = lerp(1, 0.11, p), x = lerp(r0.x, BADGE.x + 22, p), y = lerp(r0.y, BADGE.y - 4, p);
        st(fly, { transform: `translate(${f2(x - r0.x)}px, ${f2(y - r0.y)}px) scale(${k.toFixed(4)})`, opacity: (1 - T(t, 1.9, 0.12, ez.lin)).toFixed(3),
          filter: p > 0.6 ? `blur(${f2((p - 0.6) * 12)}px)` : 'none' });
      }
      // badge: the box opens from its gold edge, the words roll in, then the real footage badge takes over underneath
      const bp = T(t, 1.9, 0.26, ez.snap);
      show(badge, t >= 1.9 && t < 2.62);
      st(badge, { clipPath: `inset(0 ${f2((1 - bp) * 100)}% 0 0)` });
      roll(bTxt, t, 1.98, null, { stag: 0.025, dur: 0.4, y: 100, blur: 0, seed: 7 });
      st(bDot, { opacity: (Math.floor(t * 4) % 2 ? 0.35 : 1).toString() });
    };
  }

  // ================================================================ B. the browser scout (real footage)
  const sc = {};   // shared between B and C: the browser element and its rest geometry
  function buildScout() {
    const s = scene('scout', 1.98, 10.6, 5);
    const S = D.scout;
    const ramp = monoCubic(S.ramp);
    const frames = S.frames;                        // [[t, file], ...] sorted
    const posts = S.posts, steps = S.steps.filter((x) => x.action !== 'launch'), urls = S.urls;
    s.el.innerHTML = `
      <div class="browser"><div class="chrome"><span class="dots"><i></i><i></i><i></i></span>
          <span class="url">${ico('lock')}<span class="u">about:blank</span></span>
          <span class="ctl"><i></i><span class="ctlt">Agent in control</span></span><span class="stop">Stop</span></div>
        <div class="screen"><canvas width="1280" height="800"></canvas><div class="boot"><span class="spin"></span><span>Opening the agent browser…</span></div></div></div>
      <div class="bhud">
        <div class="eyebrow"><span class="rule"></span><span><b>01</b> — Agents · browser scout</span></div>
        <div class="display d1">Reads the web</div><div class="display d2">like a <em>person.</em></div>
        <div class="sub s1">Real Chromium · public pages · never posts</div>
        <div class="counters"><div><b class="n-read">0</b><span>Read</span></div><div class="blue"><b class="n-match">0</b><span>Matched</span></div>
          <div class="gold"><b class="n-kept">0</b><span>Archived · SHA-256</span></div><div><b class="n-time">0.0</b><span>Run time · s</span></div></div>
        <ul class="steps"></ul>
        <div class="speed"><span>Real run ·</span><b class="sp">×1.0</b><span class="bar"><i></i></span><span class="rid">${esc(S.run_id.slice(4, 14))}…</span></div>
      </div>
      <div class="tilecap"></div>`;
    const br = $('.browser', s.el), cv = $('canvas', s.el), ctx = cv.getContext('2d'), boot = $('.boot', s.el);
    const urlEl = $('.u', s.el), ctl = $('.ctl', s.el), ctlT = $('.ctlt', s.el);
    const hud = $('.bhud', s.el), hRule = $('.bhud .rule', s.el), hEb = split($('.bhud .eyebrow span:last-child', s.el));
    const d1 = split($('.d1', s.el)), d2 = split($('.d2', s.el)), s1 = split($('.s1', s.el));
    const cnt = $('.counters', s.el), nRead = $('.n-read', s.el), nMatch = $('.n-match', s.el), nKept = $('.n-kept', s.el), nTime = $('.n-time', s.el);
    const stepsEl = $('.steps', s.el), speed = $('.speed', s.el), spB = $('.sp', s.el), spBar = $('.speed .bar i', s.el);
    const cap = $('.tilecap', s.el);
    const ACT = { goto: 'Open', type: 'Type', read: 'Read', scroll: 'Scroll', done: 'Done' };
    const lis = steps.map((x) => mk('li', '', `<span class="a">${ACT[x.action] || x.action}</span><span>${esc(x.text.replace('(public web preview)', '· public preview'))}</span>`, stepsEl));
    sc.br = br; sc.cap = cap;
    // sha chips for archived posts (first channel, where the camera is close)
    const kept = posts.filter((p) => p.kept && p.sha);
    const chips = kept.map((p) => { const c = mk('div', 'chip-sha', `${ico('lock')}<span>sha256 ${p.sha.slice(0, 12)}…</span>`, s.el); return c; });
    // film time at which the run reaches run-time tau (invert the ramp)
    const filmAt = (tau) => { let lo = S.ramp[0][0], hi = S.ramp[S.ramp.length - 1][0]; for (let i = 0; i < 40; i++) { const m = (lo + hi) / 2; if (ramp(m) < tau) lo = m; else hi = m; } return (lo + hi) / 2; };
    const tEnd = S.ramp[S.ramp.length - 1][0];
    posts.forEach((p, i) => { const ft = filmAt(p.at); if (ft < tEnd) cue(ft, p.kept ? 'kept' : p.matched ? 'match' : 'read', i); });
    steps.forEach((x, i) => { const ft = filmAt(x.at); if (ft > 2.0 && ft < tEnd) cue(ft, 'step', i); });
    // keystrokes: the scout types "Kosovo" (type steps); spread six keys over the typing window
    S.steps.filter((x) => x.action === 'type').forEach((x) => {
      const nx = S.urls.find((u) => u.at > x.at); const a = filmAt(x.at + 0.25), b = filmAt(nx ? nx.at - 0.2 : x.at + 1.2);
      for (let k = 0; k < 6; k++) cue(lerp(a, b, k / 5), 'key', k);
    });
    // footage: load frames on demand (a few decoded at a time), draw the one at run time tau
    const cache = new Map();
    let pending = null, drawn = null;
    const frameIdx = (tau) => { let lo = 0, hi = frames.length - 1; if (tau <= frames[0][0]) return 0; while (lo < hi) { const m = (lo + hi + 1) >> 1; if (frames[m][0] <= tau) lo = m; else hi = m - 1; } return lo; };
    const load = (f) => {
      if (cache.has(f)) return cache.get(f);
      const img = new Image(); img.src = `footage/used/${f}`;
      const pr = img.decode().then(() => img).catch(() => null);
      cache.set(f, pr);
      if (cache.size > 24) cache.delete(cache.keys().next().value);
      return pr;
    };
    // the camera: rest → slow push → pull back into the tile at top-left
    const TILE = { x: 110, y: 142, w: 330 };
    const capRest = { x: TILE.x, y: TILE.y + (48 + 737.5) * (TILE.w / BR.w) + 16 };
    st(cap, { transform: `translate(${capRest.x}px, ${capRest.y}px)` });
    sc.TILE = TILE;
    s.seek = (t) => {
      // the recording is sampled once per output frame (60 fps), so motion-blur sub-samples never blend two different
      // screencast frames into a ghost; the window's own moves still blur
      const tau = Math.max(0, ramp(Math.round(t * 60) / 60));
      // open: the window unfolds from the badge (bottom edge first, then up)
      const p1 = T(t, 1.97, 0.24, ez.snap), p2 = T(t, 2.05, 0.36, ez.cam);
      // camera push and the pull-back into the tile
      const push = T(t, 2.4, 3.2, ez.io) * 0.045;
      const pb = T(t, 5.55, 0.8, ez.cam);
      const k = lerp(1 + push, TILE.w / BR.w, pb);
      const cx = 700, cy = 532;    // push about the browser centre
      const x0 = cx - (cx - BR.x) * (1 + push), y0 = cy - (cy - BR.y) * (1 + push);
      const bx = lerp(x0, TILE.x, pb), by = lerp(y0, TILE.y, pb);
      st(br, { transform: `translate(${f2(bx)}px, ${f2(by)}px) scale(${k.toFixed(5)})`,
        clipPath: p2 >= 1 && p1 >= 1 ? 'none' : `inset(${f2((1 - p2) * 100)}% ${f2((1 - p1) * 100)}% 0 0)` });
      show(br, t >= 1.97);
      // the footage
      const i = frameIdx(tau), f = frames[i][1];
      show(boot, tau < frames[0][0] + 0.15);
      if (drawn !== f) {
        pending = load(f).then((img) => { if (img) { ctx.drawImage(img, 0, 0); drawn = f; } });
      } else pending = null;
      // browser chrome follows the run
      const u = [...urls].reverse().find((x) => x.at <= tau);
      text(urlEl, u ? u.url.replace(/^https:\/\//, '') : 'about:blank');
      const done = tau >= (S.end.at - 1.2);
      cls(ctl, 'off', done); text(ctlT, done ? 'Finished' : 'Agent in control');
      // right HUD: in after the window opens, out on the pull-back
      const hin = 2.32, hout = 5.5;
      show(hud, t < hout + 0.9);
      st(hRule, { transform: `scaleX(${(T(t, hin, 0.5) * (1 - T(t, hout, 0.3, ez.in))).toFixed(3)})` });
      roll(hEb, t, hin + 0.04, hout, { stag: 0.02, dur: 0.5, y: 100, blur: 0, seed: 11 });
      roll(d1, t, hin + 0.1, hout + 0.02, { stag: 0.07, seed: 12 });
      roll(d2, t, hin + 0.22, hout + 0.06, { stag: 0.07, seed: 13 });
      roll(s1, t, hin + 0.36, hout + 0.08, { stag: 0.02, dur: 0.5, y: 100, blur: 0, seed: 14 });
      const cIn = T(t, hin + 0.3, 0.6), cOut = T(t, hout + 0.05, 0.4, ez.in);
      st(cnt, { opacity: (cIn * (1 - cOut)).toFixed(3), transform: `translateY(${f2((1 - cIn) * 24)}px) translateX(${f2(cOut * 80)}px)` });
      const read = posts.filter((p) => p.at <= tau).length, match = posts.filter((p) => p.at <= tau && p.matched).length;
      const keptN = posts.filter((p) => p.at <= tau && p.kept).length;
      text(nRead, String(read)); text(nMatch, String(match)); text(nKept, String(keptN)); text(nTime, tau.toFixed(1));
      // step log: newest on top
      const nOn = steps.filter((x) => x.at <= tau).length;
      lis.forEach((li, j) => {
        const age = nOn - 1 - j;                 // 0 = newest
        const tArr = filmAt(steps[j].at);
        const pIn = spring(t, Math.max(tArr, hin + 0.4), 16, 0.9);
        const y = age * 44 - (1 - clamp(pIn)) * 30;
        show(li, j < nOn && age < 4 && t >= hin + 0.35);
        cls(li, 'on', age === 0);
        st(li, { transform: `translateY(${f2(y)}px)`, opacity: ((age === 0 ? 1 : 0.62 - age * 0.12) * clamp(pIn) * (1 - cOut)).toFixed(3) });
      });
      const sIn = T(t, hin + 0.5, 0.5);
      st(speed, { opacity: (sIn * (1 - cOut)).toFixed(3) });
      const v = ramp.slope(clamp(t, S.ramp[0][0], tEnd - 0.01));
      text(spB, `×${v < 9.95 ? v.toFixed(1) : Math.round(v)}`);
      st(spBar, { width: `${f2(clamp(v / 28) * 100)}%` });
      // sha chips: from the reading area to the Archived counter
      const target = { x: 1360 + 18, y: 142 + 330 };
      kept.forEach((p, j) => {
        const t0 = filmAt(p.at), c = chips[j];
        const q = T(t, t0, 0.62, ez.io);
        const vis = t >= t0 && q < 1 && t0 < 5.5;
        show(c, vis);
        if (vis) {
          const sx = 760, sy = 470 + (j % 3) * 60;
          const x = lerp(sx, target.x, q), y = lerp(sy, target.y, q) - Math.sin(q * Math.PI) * 60;
          st(c, { transform: `translate(${f2(x)}px, ${f2(y)}px) scale(${(1 - 0.25 * q).toFixed(3)})`, opacity: (1 - T(t, t0 + 0.45, 0.17, ez.lin)).toFixed(3) });
        }
      });
      // tile caption once the window is small
      const cp = T(t, 6.2, 0.4);
      show(cap, t >= 6.15);
      // the tile leaves with the field agents when the camera tilts down to signals
      const tilt = T(t, 9.8, 0.62, ez.cam);
      st(s.el, { transform: tilt > 0 ? `translateY(${f2(-tilt * 1080)}px)` : 'none' });
      html(cap, `<b>Telegram scout</b> · ${done ? '<span class="ok">done</span>' : 'reading'}<br>${read} read · ${match} matched · <b>${keptN}</b> archived`);
      st(cap, { opacity: cp.toFixed(3) });
      return pending;
    };
  }

  // ================================================================ C. 46 field agents: a waterfall of the real event log
  function buildAgents() {
    const s = scene('agents', 5.9, 10.7, 4);
    const A = D.agents, lanes = A.lanes, N = lanes.length, E = A.elapsed;
    const U0 = 6.72, U1 = 9.72;                    // film window for the run's 0 → elapsed
    const uAt = (t) => clamp((t - U0) / (U1 - U0)) * E;
    const filmOf = (u) => U0 + (u / E) * (U1 - U0);
    s.el.innerHTML = `
      <div class="wf-head"><div class="eyebrow"><span class="rule"></span><span><b>01</b> — Agents · field agents</span></div>
        <div class="display d1">46 sites. <em>17 seconds.</em></div>
        <div class="sub s1">8 agents in parallel · site search APIs + RSS · registry-gated · robots.txt respected</div></div>
      <div class="wf-get"><div class="g0"></div><div class="g1"></div></div>
      <div class="wf-stats"><div><b class="e">0.0</b><span>Elapsed · s</span></div><div><b class="v">0</b><span>Sources visited / 46</span></div>
        <div class="blue"><b class="k">0</b><span>New items kept</span></div><div class="warn"><b class="x">0</b><span>Need attention</span></div></div>
      <svg class="wf" viewBox="0 0 1920 1080"></svg>`;
    const svg = $('.wf', s.el);
    const head = $('.wf-head', s.el), hRule = $('.rule', head), hEb = split($('.eyebrow span:last-child', head));
    const d1 = split($('.d1', head)), s1 = split($('.s1', head));
    const g0 = $('.g0', s.el), g1 = $('.g1', s.el), stats = $('.wf-stats', s.el);
    const sE = $('.e', s.el), sV = $('.v', s.el), sK = $('.k', s.el), sX = $('.x', s.el);
    // geometry: two columns of 23 lanes
    const COL = [{ x: 110, bx: 352, bw: 560 }, { x: 1000, bx: 1242, bw: 560 }];
    const Y0 = 476, PITCH = 22.6, PX = (c, u) => COL[c].bx + (u / 17.5) * COL[c].bw;
    const g = svgEl('g', {}, svg);
    const axes = [0, 1].map((c) => {
      const ag = svgEl('g', {}, g);
      [0, 5, 10, 15].forEach((u) => {
        svgEl('line', { x1: PX(c, u), x2: PX(c, u), y1: Y0 - 22, y2: Y0 + 23 * PITCH - 6, stroke: 'rgba(255,255,255,.07)', 'stroke-width': 1 }, ag);
        const tx = svgEl('text', { x: PX(c, u) + 4, y: Y0 - 26, class: 'tick' }, ag); tx.textContent = `${u}s`;
      });
      return ag;
    });
    const play = [0, 1].map((c) => svgEl('line', { y1: Y0 - 18, y2: Y0 + 23 * PITCH - 4, stroke: '#d0a650', 'stroke-width': 1.5 }, g));
    const playT = [0, 1].map(() => svgEl('text', { y: Y0 - 44, class: 'tick', fill: '#d0a650' }, g));
    const L = lanes.map((ln, i) => {
      const c = i < 23 ? 0 : 1, row = i % 23, y = Y0 + row * PITCH;
      const lg = svgEl('g', {}, g);
      const base = svgEl('line', { x1: COL[c].bx, x2: COL[c].bx + COL[c].bw, y1: y, y2: y, stroke: 'rgba(255,255,255,.07)', 'stroke-width': 1 }, lg);
      const meth = svgEl('text', { x: COL[c].x, y: y + 4, class: 'meth' }, lg); meth.textContent = ln.method === 'wp-search' ? 'WP' : 'RSS';
      const nm = svgEl('text', { x: COL[c].x + 38, y: y + 5, class: 'name' }, lg); nm.textContent = ln.name.length > 26 ? ln.name.slice(0, 25) + '…' : ln.name;
      const bar = svgEl('rect', { y: y - 4, height: 8, x: PX(c, ln.t0 || 0), width: 0 }, lg);
      const head2 = svgEl('rect', { y: y - 5, height: 10, width: 4 }, lg);
      const end = svgEl('text', { y: y + 4, class: 'end' }, lg);
      const dots = ln.items.map((it) => svgEl('rect', { x: PX(c, it.at) - 3, y: y - 3, width: 6, height: 6, fill: '#ffffff' }, lg));
      const err = ln.state === 'error';
      const why = err ? (/403/.test(ln.note) ? 'HTTP 403' : /unreachable/.test(ln.note) ? 'unreachable' : /slow/.test(ln.note) ? 'too slow' : 'error') : '';
      const label = err ? why : ln.kept ? `+${ln.kept} new` : `0 / ${ln.seen}`;
      const color = err ? '#ec6b6b' : ln.kept ? '#4f7dff' : 'rgba(255,255,255,.30)';
      if (ln.t0 != null) cue(filmOf(ln.t0), 'get', i);
      if (ln.t1 != null) cue(filmOf(ln.t1), err ? 'err' : ln.kept ? 'got' : 'done', i);
      return { ln, c, row, y, lg, nm, meth, bar, head: head2, end, dots, err, label, color };
    });
    const gets = lanes.flatMap((ln) => ln.gets.map((x) => ({ ...x, name: ln.name }))).sort((a, b) => a.at - b.at);
    cue(5.95, 'pull'); cue(9.78, 'tilt');
    s.seek = (t) => {
      const u = uAt(t);
      // heading in, everything out on the tilt to signals
      const hin = 6.02, out = T(t, 9.8, 0.62, ez.cam);
      st(s.el, { transform: out > 0 ? `translateY(${f2(-out * 1080)}px)` : 'none' });
      st(hRule, { transform: `scaleX(${T(t, hin, 0.5).toFixed(3)})` });
      roll(hEb, t, hin + 0.04, null, { stag: 0.02, dur: 0.5, y: 100, blur: 0, seed: 21 });
      roll(d1, t, hin + 0.1, null, { stag: 0.08, seed: 22 });
      roll(s1, t, hin + 0.3, null, { stag: 0.015, dur: 0.5, y: 100, blur: 0, seed: 23 });
      const sIn = T(t, hin + 0.2, 0.6);
      st(stats, { opacity: sIn.toFixed(3), transform: `translateY(${f2((1 - sIn) * 24)}px)` });
      // axes and lanes draw in, top to bottom
      axes.forEach((a, c) => st(a, { opacity: T(t, 6.12 + c * 0.08, 0.5).toFixed(3) }));
      L.forEach((l, i) => {
        const pin = T(t, 6.12 + l.row * 0.012 + l.c * 0.1, 0.5);
        st(l.lg, { opacity: pin.toFixed(3), transform: `translateX(${f2((1 - pin) * -24)}px)` });
        const { ln } = l;
        const started = ln.t0 != null && u >= ln.t0, finished = ln.t1 != null && u >= ln.t1;
        const x0 = PX(l.c, ln.t0 || 0), x1 = PX(l.c, finished ? ln.t1 : Math.max(ln.t0 || 0, u));
        attr(l.bar, 'width', Math.max(started ? 2 : 0, x1 - x0).toFixed(1));
        attr(l.bar, 'fill', finished ? l.color : '#d0a650');
        attr(l.head, 'x', (x1 - 2).toFixed(1)); attr(l.head, 'fill', '#d0a650');
        show(l.head, started && !finished);
        attr(l.nm, 'fill', started ? (finished && !ln.kept && !l.err ? 'rgba(243,243,243,.55)' : '#ffffff') : 'rgba(243,243,243,.38)');
        show(l.end, finished);
        if (finished) {
          attr(l.end, 'x', (x1 + 8).toFixed(1)); attr(l.end, 'fill', l.err ? '#ec6b6b' : ln.kept ? '#9db5ff' : 'rgba(255,255,255,.34)');
          text(l.end, l.label.toUpperCase());
          st(l.end, { opacity: T(t, filmOf(ln.t1), 0.25).toFixed(3) });
        }
        l.dots.forEach((d, j) => show(d, u >= ln.items[j].at));
      });
      // playhead
      const live = t >= U0 - 0.05 && t <= U1 + 0.25;
      play.forEach((p, c) => { const x = PX(c, u); attr(p, 'x1', x.toFixed(1)); attr(p, 'x2', x.toFixed(1)); show(p, live); });
      playT.forEach((p, c) => { attr(p, 'x', (PX(c, u) - 4).toFixed(1)); attr(p, 'text-anchor', 'end'); text(p, c ? `×${(E / (U1 - U0)).toFixed(1)}` : `${u.toFixed(1)} s`); show(p, live); });
      // the newest two requests, as the agents send them
      const sent = gets.filter((x) => x.at <= u);
      const last = sent.slice(-2);
      [g0, g1].forEach((el, j) => {
        const x = last[last.length - 1 - j];
        html(el, x ? `<b>GET</b>${esc(x.url)}` : '');
        st(el, { top: `${j * 23}px`, opacity: (j ? 0.55 : 1) * T(t, 6.55, 0.3) + '' });
      });
      // stats
      const vis = lanes.filter((ln) => ln.t1 != null && u >= ln.t1);
      text(sE, u.toFixed(1)); text(sV, String(vis.length));
      text(sK, String(lanes.reduce((a, ln) => a + ln.items.filter((it) => it.at <= u).length, 0)));
      text(sX, String(vis.filter((ln) => ln.state === 'error').length));
    };
  }

  // ================================================================ D. signals: label, filter, group, score, surface
  // timing (film s): rows 10.5 · Qwen scan 11.3 · noise leaves 12.75 · story merges 13.45 · score 14.0 · tripwire 15.15
  //                  P1 on the downbeat of bar 8 (16.0) · pan to ask 17.45
  const SIG = { rows: 10.5, scan: 11.3, out: 12.75, join: 13.0, merge: 13.45, score: 14.0, trip: 15.15, clear: 15.62, alert: 16.0, leave: 17.45 };
  function buildSignals() {
    const s = scene('signals', 9.75, 18.5, 3);
    const G = D.signals, rows = G.rows, story = G.story, F = G.funnel;
    const hhmm = (iso) => new Date(iso).toISOString().slice(11, 16);
    const LANG = { 'sr-Cyrl': 'SR · CYRL', 'sr-Latn': 'SR · LATN', sq: 'SQ', en: 'EN' };
    const verifyNote = 'corroborated by 6 independent origin groups';     // the replay's own verify step, tier <= 2
    s.el.innerHTML = `
      <div class="sg-head" style="--c:#4f7dff"><div class="eyebrow"><span class="rule"></span><span><b>02</b> — Signals · detect · filter · surface</span></div>
        <div class="display d1">What matters, <em>surfaced.</em></div>
        <div class="sub s1">Canal window · 29 Nov 2024 · 12:00–21:00 UTC · replayed in time order</div></div>
      <div class="funnel">${[[F.posts, 'Posts in'], [F.kosovo, 'About Kosovo'], [F.stories, 'Stories'], [F.traced, 'Traced'], [F.alerts, 'P1 alert']].map(([n, l], i) =>
        `<div class="${i === 4 ? 'hot' : ''}"><i></i><b>${n}</b><span>${l}</span></div>`).join('')}</div>
      <div class="gate"><i></i></div>
      <div class="gate-l eyebrow" style="--c:#4f7dff"><span class="rule"></span><span class="gl"><b>Threat?</b> · Qwen3-8B labeller</span></div>
      <div class="rows"></div>
      <div class="rights">${ico('shield')}<span>Protest, journalism and opposition politics are never a threat on their own</span></div>
      <div class="story-h eyebrow" style="--c:#4f7dff"><span class="rule"></span><span class="sh"><b>Same story</b> · ${esc(story.id)} · ${story.posts} posts · ${story.sources} outlets · Cyrillic + Latin</span></div>
      <div class="bracket"><i class="v"></i>${story.timeline.map(() => '<i class="h"></i>').join('')}</div>
      <div class="story-f"><span class="pill idle">Earliest observed · ${esc(story.origin.source)} ${hhmm(story.origin.when)} UTC</span><span class="pill ok">${esc(story.verdict)}</span><span class="pill idle">Grouped by wording · meaning · names</span></div>
      <div class="tps"></div>
      <div class="trip"><b>Tripwire</b> · T3 + explosive / sabotage term + named critical-infrastructure site <b>→ forces P1</b></div>
      <div class="alertcard"><div class="p1"><i></i><span class="p1t">Alert · priority 1 · TPS ${story.tps}</span></div><div class="big"><em>P1</em> in 73 min.</div>
        <div class="line">From the <b>first post</b> to a <b>priority-1 alert</b> on the replay clock, ${verifyNote}.</div></div>
      <div class="kmapw">${D.kmap}<div class="ring r1"></div><div class="ring r2"></div><div class="ring r3"></div></div>`;
    const head = $('.sg-head', s.el), hRule = $('.rule', head), hEb = split($('.eyebrow span:last-child', head));
    const d1 = split($('.d1', head)), s1 = split($('.s1', head));
    const fun = $$('.funnel > div', s.el), funBar = $$('.funnel i', s.el), funnel = $('.funnel', s.el);
    const gate = $('.gate', s.el), gateDot = $('.gate i', s.el), gl = $('.gate-l', s.el), glRule = $('.rule', gl);
    const rowsEl = $('.rows', s.el), rights = $('.rights', s.el), rightsW = split($('.rights span', s.el));
    const storyH = $('.story-h', s.el), shRule = $('.rule', storyH), shW = split($('.sh', storyH)), storyF = $('.story-f', s.el);
    const bracket = $('.bracket', s.el), bV = $('.bracket .v', s.el), bH = $$('.bracket .h', s.el);
    const tpsEl = $('.tps', s.el), trip = $('.trip', s.el), alertEl = $('.alertcard', s.el);
    const aP1 = $('.p1', alertEl), aBig = split($('.big', alertEl)), aLine = split($('.line', alertEl));
    const kmapw = $('.kmapw', s.el), rings = $$('.ring', kmapw);
    const storyIds = new Set(story.timeline.map((x) => x.id));
    const extra = story.timeline.filter((x) => !rows.some((r) => r.id === x.id)).map((x) => ({ id: x.id, title: x.title, lang: x.lang, source: x.source, tier: x.tier, when: x.t, extra: true }));
    const all = [...rows, ...extra];
    const R = all.map((r) => {
      const el = mk('div', 'row', `<span class="when">${hhmm(r.when)}</span><div><div class="ttl">${esc(r.title)}</div>
        <div class="meta"><span class="src">${esc(r.source)}</span><span class="pill t${r.tier}">T${r.tier}</span><span class="pill idle">${LANG[r.lang] || esc(r.lang)}</span></div></div><span class="scan"></span>`, rowsEl);
      const chips = r.extra ? '' : r.relevant
        ? [...r.labels.map((x) => `<span class="pill bad">${x}</span>`), ...r.narratives.map((x) => `<span class="pill warn">${x}</span>`)].join('')
        : '<span class="pill idle">Not a threat</span>';
      const why = r.extra ? '' : r.relevant ? (r.places.length ? `Places · <b>${esc(r.places.slice(0, 2).join(', '))}</b>` : 'Threat-relevant') : 'No threat label · kept on file';
      const v = mk('div', `verd ${r.relevant ? 'yes' : 'no'}`, `<div class="chips">${chips}</div><div class="why">${why}</div>`, s.el);
      return { r, el, v, scan: $('.scan', el), chips: $$('.pill', v) };
    });
    const ROWY = (i) => 352 + i * 76;
    const N0 = rows.length;
    const tScan = (i) => SIG.scan + i * 0.14;
    R.forEach((x, i) => { if (i < N0) { cue(SIG.rows + i * 0.08, 'row', i); cue(tScan(i) + 0.2, x.r.relevant ? 'flag' : 'pass', i); } });
    cue(SIG.join, 'row', 9); cue(SIG.join + 0.12, 'row', 10); cue(SIG.merge, 'merge'); cue(SIG.trip, 'trip'); cue(SIG.alert, 'alert'); cue(SIG.leave, 'pan');
    // TPS factors: the event's own scores and significance notes
    const FAC = [['severity', 1.0, 'T3 · attack on water / energy infrastructure'], ['velocity', 1.0, '10 posts in the last hour · z = 6.3'],
      ['proximity', 1.0, 'Names Gazivode, Ibar-Lepenac, KEK'], ['coordination', 0.09, '0% near-duplicates · fan-out 3'],
      ['reach', 0.0, 'No audience counts for news sites'], ['offline intent', 0.0, 'No call to gather, block or attack']];
    tpsEl.innerHTML = FAC.map(([k, v, n]) => `<div class="f"><div><span>${k}</span><em>${esc(n)}</em></div><div class="track"><i></i></div><b>${v.toFixed(2)}</b></div>`).join('')
      + `<div class="total"><span>Threat priority score</span><b class="tv">0.0</b><span>× credibility 0.95</span></div>`;
    const facEls = $$('.f', tpsEl), facBars = $$('.track i', tpsEl), tv = $('.tv', tpsEl);
    FAC.forEach((_, i) => cue(SIG.score + 0.1 + i * 0.11, 'fac', i));
    // the map's own canal hotspot: light it, and ring it
    const MAPK = 1.06, MAPX = 1110, MAPY = 318;
    let core = null;
    $$('.hs', kmapw).forEach((h) => { const canal = /canal/i.test(h.textContent); cls(h, 'on', canal); if (canal) core = $('.core', h); else h.style.opacity = '.6'; });
    const cb = core ? core.getBBox() : { x: 238, y: 164, width: 6, height: 6 };
    const PIN = { x: cb.x + cb.width / 2, y: cb.y + cb.height / 2 };
    s.seek = (t) => {
      // camera: tilt in from below (agents leave upwards), pan out to the right into ask
      const tin = T(t, 9.8, 0.62, ez.cam), tout = T(t, SIG.leave, 0.7, ez.cam);
      st(s.el, { transform: `translate(${f2(-tout * 1920)}px, ${f2((1 - tin) * 1080)}px)` });
      st(hRule, { transform: `scaleX(${T(t, 10.2, 0.5).toFixed(3)})` });
      roll(hEb, t, 10.22, null, { stag: 0.02, dur: 0.5, y: 100, blur: 0, seed: 31 });
      roll(d1, t, 10.28, null, { stag: 0.08, seed: 32 });
      roll(s1, t, 10.44, null, { stag: 0.015, dur: 0.5, y: 100, blur: 0, seed: 33 });
      // funnel lights stage by stage
      const lit = [10.35, 11.05, SIG.merge + 0.1, SIG.score, SIG.alert];
      const fIn = T(t, 10.25, 0.6);
      st(funnel, { opacity: fIn.toFixed(3), transform: `translateY(${f2((1 - fIn) * 20)}px)` });
      fun.forEach((c, i) => { cls(c, 'lit', t >= lit[i]); st(funBar[i], { width: `${f2(T(t, lit[i], 0.5) * 100)}%` }); });
      // the gate
      const gIn = T(t, 11.05, 0.5), gOut = T(t, SIG.out, 0.4, ez.in);
      st(gate, { transform: `scaleY(${gIn.toFixed(3)})`, transformOrigin: '50% 0', opacity: (1 - gOut).toFixed(3) });
      st(glRule, { transform: `scaleX(${T(t, 11.1, 0.4).toFixed(3)})` });
      st(gl, { opacity: (T(t, 11.1, 0.4) * (1 - gOut)).toFixed(3) });
      // rows: slide in, get scanned; the noise leaves; the story rows gather and fold into the story card
      R.forEach((x, i) => {
        const isStory = storyIds.has(x.r.id), extraRow = !!x.r.extra;
        const tIn = extraRow ? SIG.join + (i - N0) * 0.12 : SIG.rows + i * 0.08;
        const pin2 = T(t, tIn, 0.5);
        const leave = isStory ? 0 : T(t, SIG.out + (i % 4) * 0.04, 0.4, ez.in);
        const slot = extraRow ? (2 + (i - N0)) : i;
        const order = story.timeline.findIndex((y) => y.id === x.r.id);
        let y = ROWY(slot);
        if (isStory) y = lerp(ROWY(slot), ROWY(order), T(t, SIG.out + 0.15, 0.5, ez.io));
        const m = isStory ? T(t, SIG.merge, 0.5, ez.cam) : 0;
        const sOut = T(t, SIG.clear + Math.max(0, order) * 0.03, 0.4, ez.in);
        show(x.el, t >= tIn && leave < 1 && sOut < 1);
        const dimmed = x.r.relevant === false && t > tScan(i) + 0.35;
        st(x.el, { width: `${f2(lerp(1150, 840, m))}px`,
          transform: `translate(${f2((1 - pin2) * -60 - leave * 120 - sOut * 140)}px, ${f2(y - 352)}px)`,
          opacity: (pin2 * (1 - leave) * (1 - sOut) * (dimmed ? 0.42 : 1)).toFixed(3),
          clipPath: sOut > 0 ? `inset(0 ${f2(sOut * 100)}% 0 0)` : pin2 >= 1 ? 'none' : `inset(0 ${f2((1 - pin2) * 100)}% 0 0)` });
        const sp = T(t, tScan(i), 0.24, ez.io);
        st(x.scan, { width: `${f2((extraRow ? 0 : sp) * 100)}%`, opacity: (1 - T(t, tScan(i) + 0.3, 0.3)).toFixed(3) });
        const vIn = extraRow ? 0 : T(t, tScan(i) + 0.18, 0.4);
        const vOut = T(t, SIG.out + (i % 4) * 0.04, 0.35, ez.in);
        show(x.v, vIn > 0 && vOut < 1);
        st(x.v, { top: `${ROWY(i)}px`, opacity: (vIn * (1 - vOut)).toFixed(3), transform: `translateX(${f2((1 - vIn) * 24 + vOut * 40)}px)` });
        x.chips.forEach((c, j) => { const q = spring(t, tScan(i) + 0.2 + j * 0.05, 18, 0.8); st(c, { transform: `scale(${clamp(0.6 + 0.4 * q, 0, 1.06).toFixed(3)})`, opacity: clamp(q * 1.4).toFixed(3) }); });
      });
      const iScan = R.findIndex((x, i) => i < N0 && t < tScan(i) + 0.24);
      st(gateDot, { top: `${f2((iScan < 0 ? ROWY(N0 - 1) : ROWY(Math.max(0, iScan))) + 30 - 330)}px` });
      // the rights rule, under the heading while the labeller works
      roll(rightsW, t, 12.1, SIG.out + 0.1, { stag: 0.02, dur: 0.5, y: 100, blur: 0, seed: 34 });
      st(rights, { opacity: (T(t, 12.05, 0.3) * (1 - T(t, SIG.out + 0.1, 0.3, ez.in))).toFixed(3) });
      // the story: a heading, a bracket tying the four rows, the trace's own findings underneath
      const hIn = T(t, SIG.merge, 0.45), clr = T(t, SIG.clear, 0.4, ez.in);
      st(shRule, { transform: `scaleX(${(hIn * (1 - clr)).toFixed(3)})` });
      roll(shW, t, SIG.merge + 0.04, SIG.clear, { stag: 0.02, dur: 0.5, y: 100, blur: 0, seed: 37 });
      show(storyH, t >= SIG.merge - 0.05 && clr < 1);
      const bp = T(t, SIG.join + 0.3, 0.45, ez.cam);
      show(bracket, bp > 0 && clr < 1);
      st(bracket, { opacity: (1 - clr).toFixed(3) });
      st(bV, { height: `${f2(bp * (3 * 76 + 2))}px` });
      bH.forEach((h, j) => st(h, { top: `${j * 76}px`, transform: `scaleX(${T(t, SIG.join + 0.4 + j * 0.06, 0.3).toFixed(3)})` }));
      const fIn2 = T(t, SIG.merge + 0.25, 0.45);
      show(storyF, fIn2 > 0 && clr < 1);
      st(storyF, { opacity: (fIn2 * (1 - clr)).toFixed(3), transform: `translate(${f2(110 - clr * 140)}px, ${f2(352 + 4 * 76 + 14 + (1 - fIn2) * 12)}px)` });
      // score panel and tripwire
      const pIn = T(t, SIG.score, 0.5, ez.cam), pOut = T(t, SIG.clear, 0.42, ez.in);
      show(tpsEl, pIn > 0 && pOut < 1);
      st(tpsEl, { transform: `translate(${f2(990 + (1 - pIn) * 60 + pOut * 160)}px, 352px)`, opacity: (pIn * (1 - pOut)).toFixed(3) });
      facEls.forEach((f, i) => { const q = T(t, SIG.score + 0.1 + i * 0.11, 0.45); st(facBars[i], { width: `${f2(q * FAC[i][1] * 100)}%` }); st(f, { opacity: (0.25 + 0.75 * T(t, SIG.score + 0.08 + i * 0.11, 0.25)).toFixed(3) }); });
      text(tv, countTo(t, SIG.score + 0.55, 0.6, 0, story.tps).toFixed(1));
      const trIn = T(t, SIG.trip, 0.3, ez.snap);
      show(trip, trIn > 0 && pOut < 1);
      st(trip, { transform: `translate(${f2(990 + pOut * 160)}px, ${f2(352 + 6 * 46 + 140)}px)`, opacity: (trIn * (1 - pOut)).toFixed(3),
        clipPath: trIn >= 1 ? 'none' : `inset(0 ${f2((1 - trIn) * 100)}% 0 0)` });
      // the alert, on the downbeat; the map slides in under it with the canal lit
      show(alertEl, t >= SIG.alert - 0.05);
      st(alertEl, { transform: 'translate(110px, 420px)' });
      const pp = T(t, SIG.alert, 0.3, ez.snap);
      st(aP1, { clipPath: pp >= 1 ? 'none' : `inset(0 ${f2((1 - pp) * 100)}% 0 0)` });
      roll(aBig, t, SIG.alert + 0.04, null, { stag: 0.07, dur: 0.62, seed: 35 });
      roll(aLine, t, SIG.alert + 0.36, null, { stag: 0.018, dur: 0.5, y: 100, blur: 0, seed: 36 });
      const mIn = T(t, SIG.clear + 0.2, 0.7, ez.cam);
      show(kmapw, mIn > 0);
      st(kmapw, { transform: `translate(${f2(MAPX + (1 - mIn) * 160)}px, ${MAPY}px) scale(${MAPK})`, opacity: mIn.toFixed(3) });
      rings.forEach((r, j) => {
        const t0 = SIG.alert + j * 0.42, ph = clamp((t - t0) / 1.3);
        const rad = 6 + ez.out(ph) * 64;
        show(r, t > t0 && ph < 1);
        st(r, { width: `${f2(rad * 2)}px`, height: `${f2(rad * 2)}px`, transform: `translate(${f2(PIN.x - rad)}px, ${f2(PIN.y - rad)}px)`, opacity: ((1 - ph) * 0.95).toFixed(3) });
      });
      if (core) attr(core, 'r', (3.2 + 2.6 * clamp(spring(t, SIG.alert, 14, 0.6), 0, 1.3)).toFixed(2));
    };
  }

  // ================================================================ E. ask: the question, eleven steps, the cited answer
  const ASK = { enter: SIG.leave, head: 18.0, chip: 18.4, agents: 18.52, type: 18.62, send: 19.74, fold: 19.82, reveal: 24.5, answer: 25.25, out: 28.0 };
  // eleven steps on the eighth-note grid; the camera pages through them in three moves on the beat
  const STEP_T = { trigger: [19.95, 20.25], normalise: [20.25, 20.5], agents: [20.5, 21.5], registry: [21.5, 21.75],
    search: [22.0, 22.5], sources: [22.5, 22.75], rank: [22.75, 23.0], evidence: [23.0, 23.25],
    classify: [23.5, 23.875], spread: [23.875, 24.125], brief: [24.125, 24.375] };
  const PAGES = [[0, 0], [21.75, 1], [23.25, 2]];      // [film time, page]
  const NODE = { w: 330, h: 270, gap: 72, x0: 192, y: 430 };
  function buildAsk() {
    const s = scene('ask', ASK.enter - 0.05, 28.6, 2);
    const A = D.ask, steps = A.steps, ans = A.answer;
    const by = Object.fromEntries(steps.map((x) => [x.id, x]));
    const ORDER = ['trigger', 'normalise', 'agents', 'registry', 'search', 'sources', 'rank', 'evidence', 'classify', 'spread', 'brief'];
    const ICONS = { trigger: 'bolt', normalise: 'type', agents: 'send', registry: 'book', search: 'database', sources: 'globe', rank: 'sort',
      evidence: 'lock', classify: 'spark', spread: 'branch', brief: 'file' };
    const q = A.q;
    s.el.innerHTML = `
      <div class="ask-head"><div class="eyebrow" style="--c:#ffffff"><span class="rule"></span><span><b>03</b> — Ask · every step on the record</span></div>
        <div class="display d1">Ask. It <em style="--c:#ffffff">shows its work.</em></div></div>
      <div class="composer"><div class="q"><span class="typed"></span><span class="caret"></span></div>
        <div class="rowc"><span class="chipc win">${ico('clock')}<span>Any window</span></span><span class="chipc">${ico('lang')}<span>Any language</span></span>
          <span class="sp"></span><span class="tog ag"><i></i>Field agents</span><span class="tog on"><i></i>Citations</span><span class="send">${ico('up')}</span></div></div>
      <div class="flow"></div>
      <div class="answer"></div>
      <div class="cursor"><svg viewBox="0 0 28 34"><path d="M3 2v26.5l7.1-6.6 4.6 10.3 4.6-2-4.6-10.1H25z"/></svg></div>`;
    const head = $('.ask-head', s.el), hRule = $('.rule', head), hEb = split($('.eyebrow span:last-child', head)), d1 = split($('.d1', head));
    const comp = $('.composer', s.el), typed = $('.typed', comp), caret = $('.caret', comp), win = $('.win', comp), winT = $('.win span', comp);
    const ag = $('.tog.ag', comp), send = $('.send', comp), cursor = $('.cursor', s.el);
    const compQ = $('.q', comp), compRow = $('.rowc', comp);
    const flow = $('.flow', s.el), ansEl = $('.answer', s.el);
    const CW = 1240, CX = 340, CY = 430;
    st(comp, { transform: `translate(${CX}px, ${CY}px)` });
    const compH = comp.getBoundingClientRect().height;
    // typing: a person typing fast, seeded jitter
    const r = rng(77), keys = []; let kt = ASK.type;
    for (let i = 0; i < q.length; i++) { keys.push(kt); kt += 0.018 + r() * 0.013 + (q[i] === ' ' ? 0.018 : 0); }
    keys.forEach((k, i) => cue(k, 'key', i));
    cue(ASK.chip, 'chip'); cue(ASK.send, 'click'); cue(ASK.send + 0.1, 'whoosh');
    const ms = (x) => (x.ms >= 1000 ? `${(x.ms / 1000).toFixed(1)} s` : `${x.ms.toFixed(1)} ms`);
    const short = (m) => (m || '').split('/').pop();
    const SUM = {
      trigger: () => `“${esc(q)}”`,
      normalise: () => `<b>${esc(by.normalise.rows[0][1].replace(/, /g, ' · '))}</b>`,
      agents: () => `<b>${esc(by.agents.summary)}</b>`,
      registry: () => `<b>${esc(by.registry.summary)}</b>`,
      search: () => `<b class="cnt">0</b> of <b>${esc(by.search.rows[0][1].split(' ')[0])}</b> signals`,
      sources: () => `<b>${esc(by.sources.summary)}</b>`,
      rank: () => `<b>8 picked from 5 sources</b> · max 2 each`,
      evidence: () => `<b>${esc(by.evidence.summary)}</b>`,
      classify: () => `<b>8 of 8 · attack on infrastructure</b>`,
      spread: () => `<b>${esc(by.spread.summary)}</b>`,
      brief: () => `<b>${esc(by.brief.summary)}</b>`,
    };
    const AI = (x) => (x.id === 'agents' ? ['agent', 'Field agents'] : x.ai && x.ai.state === 'used' ? ['used', `${short(x.ai.model)} · used`] : ['', 'No model']);
    const N = ORDER.map((id, i) => {
      const x = by[id];
      const [aic, ait] = AI(x);
      const el = mk('div', `node ${aic === 'agent' ? 'agent' : aic === 'used' ? 'ai' : ''}`, `<span class="bar"></span>
        <div class="top"><span class="ic">${ico(ICONS[id])}</span><span class="n">${String(i + 1).padStart(2, '0')}</span><span class="st">${ico('check')}</span></div>
        <h4>${esc(x.title)}</h4><div class="s">${esc(x.subtitle || '')}</div><div class="sum">${SUM[id]()}</div><div class="viz"></div>
        <div class="ft"><span class="ms">${ms(x)}</span><span class="ai ${aic}">${esc(ait)}</span></div>`, flow);
      st(el, { left: `${NODE.x0 + i * (NODE.w + NODE.gap)}px`, top: `${NODE.y}px`, height: `${NODE.h}px` });
      return { id, x, el, bar: $('.bar', el), stc: $('.st', el), sum: $('.sum', el), viz: $('.viz', el), ms: $('.ms', el) };
    });
    const vz = Object.fromEntries(N.map((n) => [n.id, n.viz]));
    vz.agents.innerHTML = `<svg viewBox="0 0 290 40" width="290" height="40">${D.agents.lanes.map((ln, i) => `<rect class="mb" x="${(ln.t0 / 17.5 * 280).toFixed(1)}" y="${(i % 23) * 1.7}" width="0" height="1.2" fill="${ln.state === 'error' ? '#ec6b6b' : ln.kept ? '#4f7dff' : 'rgba(255,255,255,.35)'}" data-t0="${ln.t0}" data-t1="${ln.t1}"/>`).join('')}</svg>`;
    vz.sources.innerHTML = `<div class="mini">${by.sources.branches.slice(0, 4).map((b) => `<span class="pill t${b.tier}">${esc(b.name.length > 12 ? b.initials : b.name)} ${b.count}</span>`).join('')}</div>`;
    vz.evidence.innerHTML = by.evidence.items.slice(0, 2).map((it) => `<div class="hashl"><b>✓</b> ${esc(it.sub)}</div>`).join('');
    vz.classify.innerHTML = `<div class="mini">${by.classify.rows.slice(0, 4).map(([k, v]) => `<span class="pill ${k.startsWith('T') ? 'bad' : 'warn'}">${k} ×${v.split(' ')[0]}</span>`).join('')}</div>`;
    vz.spread.innerHTML = `<div class="mini">${by.spread.rows.slice(0, 4).filter(([, v]) => !/^0 /.test(v)).map(([k, v]) => `<span class="pill t${k.slice(-1)}">${k.replace('Tier ', 'T')} · ${v.split(' ')[0]}</span>`).join('')}</div>`;
    vz.registry.innerHTML = `<div class="mini">${by.registry.rows.map(([k, v]) => `<span class="pill t${k.slice(-1)}">${k.replace('Tier ', 'T')} · ${v.split(' ')[0]}</span>`).join('')}</div>`;
    vz.rank.innerHTML = `<div class="mini">${by.rank.items.slice(0, 3).map((it) => `<span class="pill idle">${esc(it.tag)}</span>`).join('')}</div>`;
    vz.normalise.innerHTML = `<div class="mini">${['c↔čć', 's↔š', 'z↔ž', 'e↔ë', 'dj↔đ'].map((x) => `<span class="pill idle" style="text-transform:none">${x}</span>`).join('')}</div>`;
    vz.trigger.innerHTML = `<div class="mini"><span class="pill hot" style="text-transform:none">${esc(A.window)}</span><span class="pill gold">Field agents on</span></div>`;
    vz.brief.innerHTML = `<div class="mini">${[1, 2, 3, 4, 5, 6, 7, 8].map((n) => `<span class="pill idle">/${n}</span>`).join('')}</div>`;
    vz.search.innerHTML = `<svg viewBox="0 0 290 30" width="290" height="30"><rect x="0" y="12" width="290" height="6" fill="rgba(255,255,255,.08)"/><rect class="sbar" x="0" y="12" width="0" height="6" fill="#ffffff"/></svg>`;
    const mbs = $$('.mb', vz.agents), sbar = $('.sbar', vz.search), cnt = $('.cnt', N[4].sum);
    const edges = ORDER.slice(1).map((_, i) => {
      const e = mk('div', 'edge', '<i></i>', flow);
      st(e, { left: `${NODE.x0 + i * (NODE.w + NODE.gap) + NODE.w}px`, top: `${NODE.y + NODE.h / 2}px`, width: `${NODE.gap}px` });
      return { e, dot: $('i', e) };
    });
    ORDER.forEach((id, i) => cue(STEP_T[id][1], id === 'classify' ? 'ai' : id === 'agents' ? 'agentsdone' : 'node', i));
    cue(STEP_T.agents[0] + 0.05, 'agentrun'); PAGES.slice(1).forEach(([pt]) => cue(pt, 'page')); cue(ASK.reveal, 'reveal'); cue(ASK.answer, 'answer');
    // the answer card
    const cites = ans.citations;
    const bullets = ans.bullets.filter((b) => /^(Busiest day|Highest-tier|Languages)/.test(b));
    const hl = (b) => esc(b).replace(/^([^:]+:)/, '$1<b>').replace(/\.$/, '</b>');
    const hashes = Object.fromEntries(by.evidence.items.map((it, i) => [i, it.sub]));
    ansEl.innerHTML = `<div class="lbl"><span>Answer · ${(ans.ms / 1000).toFixed(1)} s end to end</span><span>46 live sources checked</span><span><b>✓</b> 8/8 pages hash-verified</span><span>${esc(short(by.classify.ai.model))} labels · T3 ×8</span></div>
      <h3>${esc(ans.headline)}</h3>
      <ul>${bullets.map((b) => `<li>${hl(b)}</li>`).join('')}</ul>
      <div class="cites">${cites.map((c, i) => `<div class="cite"><div class="tp"><b>${esc(c.source)}</b><span>/${c.n}</span></div><div class="t">${esc(c.title)}</div>
        <div class="ft"><span class="pill t${c.tier}">T${c.tier}</span><span>${esc(c.date)} · ${esc(c.lang)}</span><span class="h">sha256 ${esc((hashes[i] || '').slice(0, 10))} ✓</span></div></div>`).join('')}</div>`;
    const aLbl = $('.lbl', ansEl), aH = split($('h3', ansEl)), aLis = $$('li', ansEl), aCites = $$('.cite', ansEl);
    cites.forEach((_, i) => cue(ASK.answer + 0.4 + i * 0.07, 'cite', i));
    const ANS = { x: 110, y: 252 };
    st(ansEl, { transform: `translate(${ANS.x}px, ${ANS.y}px)` });
    const ansR = ansEl.getBoundingClientRect();
    sc.answer = { x: ANS.x, y: ANS.y, w: ansR.width, h: ansR.height };
    const FLOWW = NODE.x0 + ORDER.length * (NODE.w + NODE.gap) - NODE.gap + NODE.x0;
    const fitK = 1700 / (FLOWW - 2 * NODE.x0);
    const pageX = (t) => { let x = 0; PAGES.forEach(([pt, pg], i) => { if (i) x = lerp(x, pg * 4 * (NODE.w + NODE.gap), T(t, pt, 0.42, ez.cam)); }); return x; };
    s.seek = (t) => {
      const ent = T(t, ASK.enter, 0.7, ez.cam);
      const leave = T(t, ASK.out, 0.36, ez.in);
      st(s.el, { transform: `translateX(${f2((1 - ent) * 1920)}px)` });
      const hOut = ASK.reveal - 0.06;
      st(hRule, { transform: `scaleX(${(T(t, ASK.head - 0.1, 0.5) * (1 - T(t, hOut, 0.3, ez.in))).toFixed(3)})` });
      roll(hEb, t, ASK.head - 0.08, hOut, { stag: 0.02, dur: 0.5, y: 100, blur: 0, seed: 41 });
      roll(d1, t, ASK.head - 0.02, hOut + 0.04, { stag: 0.08, seed: 42 });
      // the composer: the window chip catches the P1's window, the question types, send
      const winOn = t >= ASK.chip;
      cls(win, 'on', winOn); text(winT, winOn ? A.window : 'Any window');
      st(win, { transform: `scale(${(1 + 0.08 * Math.sin(P(t, ASK.chip, 0.3) * Math.PI)).toFixed(3)})` });
      cls(ag, 'on', t >= ASK.agents);
      const nTyped = keys.filter((k) => k <= t).length;
      html(typed, nTyped ? esc(q.slice(0, nTyped)) : '<span class="ph">Ask about an incident, a place or a narrative…</span>');
      st(caret, { opacity: (t < ASK.type || t > ASK.send ? (Math.floor(t * 3) % 2 ? 0 : 1) : 1).toString(), display: t > ASK.send + 0.1 ? 'none' : 'inline-block' });
      cls(send, 'on', nTyped >= q.length);
      // the composer folds into node 01
      const fold = T(t, ASK.fold, 0.5, ez.cam);
      const kx = lerp(1, NODE.w / CW, fold), ky = lerp(1, NODE.h / compH, fold);
      show(comp, fold < 1);
      st(comp, { transform: `translate(${f2(lerp(CX, NODE.x0, fold))}px, ${f2(lerp(CY, NODE.y, fold))}px) scale(${kx.toFixed(4)}, ${ky.toFixed(4)})`,
        opacity: (1 - T(t, ASK.fold + 0.32, 0.16, ez.lin)).toFixed(3) });
      const cOut = (1 - T(t, ASK.fold, 0.14, ez.lin)).toFixed(3);      // only the box folds; its contents step out first
      st(compQ, { opacity: cOut }); st(compRow, { opacity: cOut });
      // cursor: in from the lower right, to send, press
      const a = { x: 1700, y: 1010 }, b = { x: CX + CW - 32 - 24 + 8, y: CY + compH - 22 - 24 + 4 };
      const cp = T(t, 19.08, 0.5, ez.io);
      const press = t > ASK.send - 0.04 && t < ASK.send + 0.1 ? 0.86 : 1;
      show(cursor, t > 19.08 && t < ASK.send + 0.42);
      st(cursor, { transform: `translate(${f2(lerp(a.x, b.x, cp))}px, ${f2(lerp(a.y, b.y, cp) - Math.sin(cp * Math.PI) * 30)}px) scale(${press})`, opacity: (1 - T(t, ASK.send + 0.2, 0.2)).toFixed(3) });
      // the flow: page moves on the beat, then the pull-back that shows the whole record
      const reveal = T(t, ASK.reveal, 0.66, ez.cam);
      const k = lerp(1, fitK, reveal);
      const fx = lerp(-pageX(t), 110 - NODE.x0 * fitK, reveal), fy = lerp(0, 104 - NODE.y * fitK, reveal);
      const dim = T(t, ASK.answer - 0.1, 0.5, ez.io);
      show(flow, t > ASK.send && leave < 1);
      st(flow, { transform: `translate(${f2(fx)}px, ${f2(fy - leave * 200)}px) scale(${k.toFixed(5)})`, opacity: ((1 - 0.6 * dim) * (1 - leave)).toFixed(3) });
      N.forEach((n) => {
        const [t0, t1] = STEP_T[n.id];
        const pIn = T(t, t0 - 0.16, 0.36, ez.cam);
        const active = t >= t0 && t < t1, done = t >= t1;
        const base = 0.2 * T(t, ASK.fold + 0.28, 0.3);
        st(n.el, { opacity: Math.max(base, pIn).toFixed(3), transform: `translateY(${f2((1 - pIn) * 26)}px)` });
        cls(n.el, 'on', active || (done && t < t1 + 0.3));
        st(n.bar, { width: `${f2(clamp((t - t0) / Math.max(0.01, t1 - t0)) * 100)}%`, opacity: done ? (1 - T(t, t1 + 0.2, 0.3)).toFixed(3) : '1' });
        const ck = spring(t, t1, 20, 0.7);
        st(n.stc, { transform: `scale(${clamp(ck, 0, 1.12).toFixed(3)})`, opacity: clamp(ck * 2).toFixed(3) });
        st(n.sum, { opacity: T(t, t0 + 0.04, 0.26).toFixed(3) });
        st(n.viz, { opacity: T(t, t0 + 0.08, 0.26).toFixed(3) });
        if (n.id === 'agents') {      // the real 17.3 s, at ×17
          const u = clamp((t - t0) / (t1 - t0)) * 17.27;
          text(n.ms, done ? ms(n.x) : `${u.toFixed(1)} s`);
          mbs.forEach((m) => { const a0 = +m.dataset.t0, b0 = +m.dataset.t1; attr(m, 'width', (u <= a0 ? 0 : (Math.min(u, b0) - a0) / 17.5 * 280).toFixed(1)); });
        }
      });
      if (cnt) text(cnt, fmt(countTo(t, STEP_T.search[0] + 0.04, 0.4, 0, 486, ez.io)));
      attr(sbar, 'width', (290 * T(t, STEP_T.search[0] + 0.04, 0.4, ez.io) * 486 / 33285 * 12).toFixed(1));
      edges.forEach((e, i) => {
        const id = ORDER[i + 1], a0 = STEP_T[ORDER[i]][1], b0 = STEP_T[id][0];
        const q2 = T(t, a0 - 0.02, Math.max(0.14, b0 - a0 + 0.06), ez.io);
        st(e.e, { background: t >= b0 ? 'rgba(255,255,255,.55)' : 'rgba(255,255,255,.18)', opacity: T(t, ASK.fold + 0.28, 0.3).toFixed(3) });
        show(e.dot, q2 > 0 && q2 < 1);
        st(e.dot, { left: `${f2(q2 * 100)}%`, background: id === 'agents' ? '#d0a650' : id === 'classify' ? '#4f7dff' : '#ffffff' });
      });
      // the answer rises under the record; it leaves by folding into the PARSE mark (scene F)
      const aIn = T(t, ASK.answer, 0.62, ez.cam);
      const sq = T(t, ASK.out, 0.26, ez.in);                // the card folds to its midline: the PARSE mark is drawn out of it
      show(ansEl, aIn > 0 && sq < 1);
      st(ansEl, { transformOrigin: '50% 50%', transform: `translate(${ANS.x}px, ${f2(ANS.y + (1 - aIn) * 70)}px) scaleY(${Math.max(0.004, 1 - sq).toFixed(4)})`,
        opacity: aIn.toFixed(3), clipPath: aIn >= 1 ? 'none' : `inset(0 0 ${f2((1 - aIn) * 100)}% 0)` });
      st(aLbl, { opacity: T(t, ASK.answer + 0.18, 0.4).toFixed(3) });
      roll(aH, t, ASK.answer + 0.18, null, { stag: 0.035, dur: 0.55, seed: 43 });
      aLis.forEach((li, i) => rise(li, t, ASK.answer + 0.4 + i * 0.09, 0.5, 16));
      aCites.forEach((c, i) => { const p = T(t, ASK.answer + 0.5 + i * 0.07, 0.5, ez.cam); st(c, { opacity: p.toFixed(3), transform: `translateY(${f2((1 - p) * 30)}px)` }); });
    };
  }

  // ================================================================ F. end: the answer folds into the PARSE mark
  const LOGO = ['M3 6C9.5 6 10 12 15 12', 'M3 12H21', 'M3 18C9.5 18 10 12 15 12'];
  function buildEnd() {
    const s = scene('end', ASK.out - 0.01, 30.01, 7);
    s.el.innerHTML = `<div class="fold abs"><div class="fold-card abs"></div><div class="fold-line abs"></div></div>
      <svg class="bigmark" viewBox="0 0 1920 1080"><g class="bm">${LOGO.map((d) => `<path d="${d}" pathLength="1"/>`).join('')}</g></svg>
      <div class="endw"><div class="wm">${'PARSE'.split('').map((c) => `<span>${c}</span>`).join('')}</div></div>
      <div class="endsub">Agents <b>search</b><i>·</i>Signals <b>surface</b><i>·</i>Ask <b>answers</b></div>`;
    const bm = $('.bm', s.el), paths = $$('path', bm), wm = $('.endw', s.el), letters = $$('.wm span', s.el), sub = $('.endsub', s.el);
    const card = $('.fold-card', s.el), line = $('.fold-line', s.el);
    const subW = split(sub);
    const K = 8.2, SW = 2;                                   // logo units → px; stroke 2 units, as the product's mark
    const wmW = $('.wm', s.el).getBoundingClientRect().width;
    const total = 18 * K + 48 + wmW, left = 960 - total / 2;
    const MX = left - 3 * K, MY = 520 - 12 * K;
    st(wm, { transform: `translate(${f2(left + 18 * K + 48)}px, ${f2(520 - 64)}px)` });
    const subRect = sub.getBoundingClientRect();
    st(sub, { transform: `translate(${f2(960 - subRect.width / 2)}px, 640px)` });
    st(bm, { transform: `translate(${f2(MX)}px, ${f2(MY)}px) scale(${K})` });
    const mid = { x0: MX + 3 * K, x1: MX + 21 * K, y: MY + 12 * K };
    cue(ASK.out, 'end'); cue(ASK.out + 0.42, 'brand');
    s.seek = (t) => {
      const A = sc.answer, t0 = ASK.out;
      // 1. the answer card squashes to its midline (scene E); 2. a white line takes over at the midline
      const cy = A.y + A.h / 2;
      show(card, false);
      // 2. a white line at the midline shrinks and slides into the mark's middle stroke
      const ln = T(t, t0 + 0.16, 0.34, ez.cam);
      const x0 = lerp(A.x, mid.x0, ln), x1 = lerp(A.x + A.w, mid.x1, ln), y = lerp(cy, mid.y, ln), h = lerp(2, SW * K, ln);
      show(line, t >= t0 + 0.14 && t < t0 + 0.52);
      st(line, { left: `${f2(x0)}px`, width: `${f2(x1 - x0)}px`, top: `${f2(y - h / 2)}px`, height: `${f2(h)}px`, background: '#fff', opacity: T(t, t0 + 0.14, 0.08, ez.lin).toFixed(3) });
      // 3. the mark: middle stroke is already there; the two curves draw out of it
      paths.forEach((p, i) => {
        const pr = i === 1 ? 1 : T(t, t0 + 0.46 + (i ? 0.04 : 0), 0.42, ez.io);
        st(p, { strokeWidth: f2(SW), strokeDasharray: '1 2', strokeDashoffset: (i === 1 ? 0 : (1 - pr)).toFixed(4), visibility: t >= t0 + 0.5 ? 'visible' : 'hidden' });
      });
      letters.forEach((l, i) => {
        const pi = T(t, t0 + 0.5 + i * 0.05, 0.6, ez.roll);
        st(l, { transform: `translateY(${f2((1 - pi) * 60)}%)`, opacity: pi.toFixed(3), filter: pi < 1 ? `blur(${f2((1 - pi) * 8)}px)` : 'none' });
      });
      roll(subW, t, t0 + 0.86, null, { stag: 0.05, dur: 0.55, y: 100, blur: 0, seed: 51 });
      const drift = 1 + T(t, t0 + 0.5, 1.5, ez.lin) * 0.018;
      st(s.el, { transform: `translate(960px, 540px) scale(${drift.toFixed(4)}) translate(-960px, -540px)` });
    };
  }

  // ================================================================ backdrop
  function buildBg() {
    const bg = mk('div', 'bg', '<div class="smoke"></div><div class="dotgrid"></div><div class="vig"></div>', $('#frame'));
    bg.style.zIndex = 0;
    const grain = mk('div', 'grain', null, $('#frame'));
    const smoke = $('.smoke', bg), dots = $('.dotgrid', bg);
    return (t) => {
      const d = t / 20;
      st(smoke, { transform: `translate3d(${f2(-3 * Math.sin(d * 3.1))}%, ${f2(2 * Math.sin(d * 2.3))}%, 0)` });
      const g = Math.floor(t * 30);
      st(grain, { transform: `translate(${(g * 37) % 64}px, ${(g * 53) % 64}px)` });
      // the dot grid travels with the camera's big moves, so the stage reads as one space
      const tiltY = T(t, 9.8, 0.62, ez.cam) * -1080 * 0.06, panX = T(t, SIG.leave, 0.7, ez.cam) * -1920 * 0.06;
      st(dots, { transform: `translate(${f2(panX % 24)}px, ${f2(tiltY % 24)}px)`, opacity: (0.5 - 0.3 * T(t, ASK.out, 0.4)).toFixed(3) });
    };
  }

  // ================================================================ seek / ready
  let hud = null, bgSeek = null;
  async function seek(t) {
    t = clamp(t, 0, DUR - 1e-6);
    bgSeek(t); hud(t);
    const waits = [];
    for (const s of SC) {
      const on = t >= s.t0 && t < s.t1;
      st(s.el, { display: on ? 'block' : 'none' });
      if (on) { const w = s.seek(t); if (w) waits.push(w); }
    }
    if (waits.length) await Promise.all(waits);
    return t;
  }
  window.seek = seek;
  window.FILM = { CUES, DUR };
  window.ready = (async () => {
    D = await (await fetch('data/film.json')).json();
    await document.fonts.load('300 172px "Inter Tight"'); await document.fonts.load('500 24px "Inter Tight"'); await document.fonts.load('400 21px "Inter Tight"');
    await document.fonts.load('600 128px "Inter Tight"'); await document.fonts.load('500 13px "IBM Plex Mono"'); await document.fonts.load('400 13px "IBM Plex Mono"');
    await document.fonts.load('400 21px "Inter Tight"', 'Снажна');
    await document.fonts.ready;
    const ok = ['300 20px "Inter Tight"', '500 20px "IBM Plex Mono"'].every((f) => document.fonts.check(f));
    if (!ok) throw new Error('fonts did not load');
    bgSeek = buildBg();
    hud = buildHud();
    buildHook(); buildScout(); buildAgents(); buildSignals(); buildAsk(); buildEnd();
    CUES.sort((a, b) => a.t - b.t);
    await seek(0);
    return { scenes: SC.map((s) => s.name), cues: CUES.length };
  })();
})();
