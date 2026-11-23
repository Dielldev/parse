/* Parse: 30-second product film. 1920x1080, 60 fps, 120 BPM (a beat every 0.5 s).
   Every frame is a pure function of time: window.seek(t) writes every animated style from t, nothing runs on timers.
   The screens are the product's own DOM and CSS, captured from the running app by tools/capture.py, with real data:
   the canal_2024_11 replay (P1 alert 73 min after the first post) and the Tracer result for the canal blast story. */
(() => {
  'use strict';
  const FPS = 60, DUR = 30;

  // ---------------------------------------------------------------- math
  const clamp = (v, a = 0, b = 1) => (v < a ? a : v > b ? b : v);
  const lerp = (a, b, p) => a + (b - a) * p;
  const P = (t, t0, d) => (d <= 0 ? (t >= t0 ? 1 : 0) : clamp((t - t0) / d));
  function bez(x1, y1, x2, y2) {
    const cx = 3 * x1, bx = 3 * (x2 - x1) - cx, ax = 1 - cx - bx;
    const cy = 3 * y1, by = 3 * (y2 - y1) - cy, ay = 1 - cy - by;
    const X = (s) => ((ax * s + bx) * s + cx) * s, Y = (s) => ((ay * s + by) * s + cy) * s;
    const dX = (s) => (3 * ax * s + 2 * bx) * s + cx;
    return (x) => {
      if (x <= 0) return 0;
      if (x >= 1) return 1;
      let s = x;
      for (let i = 0; i < 8; i++) {
        const e = X(s) - x;
        if (Math.abs(e) < 1e-7) return Y(s);
        const d = dX(s);
        if (Math.abs(d) < 1e-6) break;
        s -= e / d;
      }
      let lo = 0, hi = 1;
      s = x;
      for (let i = 0; i < 40; i++) { if (X(s) < x) lo = s; else hi = s; s = (lo + hi) / 2; }
      return Y(s);
    };
  }
  const ez = {
    out: bez(.16, 1, .3, 1),      // long exponential settle, no overshoot
    roll: bez(.2, .7, .2, 1),     // the product's own word roll (hero .roll-w)
    io: bez(.65, 0, .35, 1),      // symmetric, for things that travel
    cam: bez(.55, 0, .1, 1),      // camera: firm start, long settle
    in: bez(.6, 0, .8, .4),       // exits (the product's w-out)
    lin: (x) => x,
  };
  const T = (t, t0, d, e = ez.out) => e(P(t, t0, d));
  function rng(a) {
    return () => {
      a |= 0; a = (a + 0x6D2B79F5) | 0;
      let r = Math.imul(a ^ (a >>> 15), 1 | a);
      r = (r + Math.imul(r ^ (r >>> 7), 61 | r)) ^ r;
      return ((r ^ (r >>> 14)) >>> 0) / 4294967296;
    };
  }

  // ---------------------------------------------------------------- dom helpers
  const $ = (s, el = document) => el.querySelector(s);
  const $$ = (s, el = document) => [...el.querySelectorAll(s)];
  const esc = (v) => String(v ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  function st(el, o) {
    if (!el) return;
    const c = el._s || (el._s = {});
    for (const k in o) {
      const v = o[k];
      if (c[k] === v) continue;
      c[k] = v;
      if (k.startsWith('--')) el.style.setProperty(k, v);   // custom properties only take effect through setProperty
      else el.style[k] = v;
    }
  }
  function cls(el, name, on) { if (el && el.classList.contains(name) !== !!on) el.classList.toggle(name, !!on); }
  function attr(el, k, v) { v = String(v); if (el && el.getAttribute(k) !== v) el.setAttribute(k, v); }
  function text(el, v) { if (el && el.textContent !== v) el.textContent = v; }
  function html(el, v) { if (el && el._h !== v) { el._h = v; el.innerHTML = v; } }
  const fmt = (n) => Math.round(n).toLocaleString('en-US');
  const f2 = (v) => v.toFixed(2);
  const show = (el, on) => st(el, { visibility: on ? 'visible' : 'hidden' });

  // split an element's text into words for the roll animation (keeps nested markup like <em>)
  function split(el) {
    const out = [];
    const walk = (node) => [...node.childNodes].forEach((n) => {
      if (n.nodeType === 3) {
        const frag = document.createDocumentFragment();
        n.textContent.split(/(\s+)/).forEach((w) => {
          if (!w) return;
          if (/^\s+$/.test(w)) { frag.appendChild(document.createTextNode(' ')); return; }
          const o = document.createElement('span'); o.className = 'kw';
          const i = document.createElement('span'); i.className = 'kwi'; i.textContent = w;
          o.appendChild(i); frag.appendChild(o); out.push(i);
        });
        n.replaceWith(frag);
      } else if (n.nodeType === 1) walk(n);
    });
    walk(el);
    return out;
  }
  // words rise into place (translate + blur, as the product's hero roll), optionally leave upwards
  function roll(ws, t, tin, tout = null, o = {}) {
    const { stag = 0.055, dur = 0.7, y = 72, blur = 8, seed = 1, ostag = 0.022, odur = 0.36 } = o;
    const r = rng(seed);
    let a = tin, b = tout;
    ws.forEach((w) => {
      const pi = T(t, a, dur * (0.88 + r() * 0.3), ez.roll);
      const po = tout == null ? 0 : T(t, b, odur, ez.in);
      const ty = (1 - pi) * y - po * y, op = pi * (1 - po), bl = blur * Math.max(1 - pi, po);
      st(w, { transform: Math.abs(ty) < 0.05 ? 'none' : `translateY(${f2(ty)}%)`, opacity: op.toFixed(3),
        filter: bl < 0.05 ? 'none' : `blur(${f2(bl)}px)` });
      a += stag * (0.7 + r() * 0.6);
      if (b != null) b += ostag;
    });
  }
  // reveal by moving a clip edge. dir names where the edge travels: down = top-to-bottom reveal.
  function clipIn(el, t, t0, d, dir = 'down', e = ez.out) {
    const p = T(t, t0, d, e), q = f2((1 - p) * 100);
    const v = { down: `inset(0 0 ${q}% 0)`, up: `inset(${q}% 0 0 0)`, right: `inset(0 ${q}% 0 0)`, left: `inset(0 0 0 ${q}%)` }[dir];
    st(el, { clipPath: p >= 1 ? 'none' : v });
    return p;
  }
  function rise(el, t, t0, d = 0.6, y = 18, e = ez.out) {
    const p = T(t, t0, d, e);
    st(el, { opacity: p.toFixed(3), transform: p >= 1 ? 'none' : `translateY(${f2((1 - p) * y)}px)` });
    return p;
  }

  // ---------------------------------------------------------------- camera
  // A key says which screen point sits at the frame centre (x, y) and at what scale (s). Scale moves in log space.
  function camAt(keys, t) {
    if (t <= keys[0].t) return keys[0];
    for (let i = 1; i < keys.length; i++) {
      const a = keys[i - 1], b = keys[i];
      if (t < b.t) {
        const p = (b.e || ez.cam)(P(t, a.t, b.t - a.t));
        return { x: lerp(a.x, b.x, p), y: lerp(a.y, b.y, p), s: Math.exp(lerp(Math.log(a.s), Math.log(b.s), p)),
          rx: lerp(a.rx || 0, b.rx || 0, p), ry: lerp(a.ry || 0, b.ry || 0, p) };
      }
    }
    return keys[keys.length - 1];
  }
  function applyCam(screen, rig, v, drift = 0) {
    const s = v.s * (1 + drift);
    st(screen, { transform: `translate(${f2(960 - v.x * s)}px, ${f2(540 - v.y * s)}px) scale(${s.toFixed(5)})` });
    if (rig) st(rig, { transform: (v.rx || v.ry) ? `perspective(2600px) rotateX(${f2(v.rx || 0)}deg) rotateY(${f2(v.ry || 0)}deg)` : 'none' });
  }
  // the camera that puts rect r (screen coords) at width w (or height h), with its anchor (ax, ay) at frame point (fx, fy)
  function fit(r, { w, h, fx = 960, fy = 540, ax = 0.5, ay = 0.5 } = {}) {
    const s = w ? w / r.w : h / r.h;
    return { x: r.x + r.w * ax - (fx - 960) / s, y: r.y + r.h * ay - (fy - 540) / s, s };
  }
  function rel(el, root) {
    const a = el.getBoundingClientRect(), b = root.getBoundingClientRect();
    return { x: a.left - b.left, y: a.top - b.top, w: a.width, h: a.height };
  }
  const toFrame = (cam, x, y, drift = 0) => { const s = cam.s * (1 + drift); return { x: (x - cam.x) * s + 960, y: (y - cam.y) * s + 540 }; };

  // ---------------------------------------------------------------- scenes, cues, cursor
  const SC = [];
  function scene(name, t0, t1, z) {
    const el = document.createElement('section');
    el.className = `sc sc-${name}`;
    el.style.zIndex = z;
    el.style.display = 'block';            // laid out while it is built, so the camera can measure it; seek() hides it after
    $('#scenes').appendChild(el);
    const s = { name, t0, t1, el, seek: () => {} };
    SC.push(s);
    return s;
  }
  const CUES = [];
  const cue = (t, kind, v = 1) => CUES.push({ t: +t.toFixed(4), kind, v });

  const CUR = { x: -100, y: -100, press: 0, on: false };
  // cursor path: keys of {t, x, y}; press windows of [t0, t1]
  function cursorAt(keys, presses, t) {
    if (t < keys[0].t || t > keys[keys.length - 1].t + 0.6) return null;
    let x = keys[0].x, y = keys[0].y;
    for (let i = 1; i < keys.length; i++) {
      const a = keys[i - 1], b = keys[i];
      if (t >= b.t) { x = b.x; y = b.y; continue; }
      if (t > a.t) {
        const p = (b.e || ez.io)(P(t, a.t, b.t - a.t));
        // a slight arc, like a hand
        const mx = (a.x + b.x) / 2 + (b.y - a.y) * 0.08, my = (a.y + b.y) / 2 - (b.x - a.x) * 0.08;
        x = (1 - p) * (1 - p) * a.x + 2 * (1 - p) * p * mx + p * p * b.x;
        y = (1 - p) * (1 - p) * a.y + 2 * (1 - p) * p * my + p * p * b.y;
      }
      break;
    }
    let press = 0;
    presses.forEach(([p0, p1]) => { if (t >= p0 - 0.06 && t <= p1 + 0.1) press = Math.max(press, Math.min(T(t, p0 - 0.06, 0.06, ez.lin), 1 - T(t, p1, 0.1, ez.lin))); });
    return { x, y, press };
  }
  const center = (r) => ({ x: r.left + r.width / 2, y: r.top + r.height / 2 });
  const frameRect = (el) => { const a = el.getBoundingClientRect(), f = $('#frame').getBoundingClientRect(); return { left: a.left - f.left, top: a.top - f.top, width: a.width, height: a.height }; };

  // ---------------------------------------------------------------- data
  const D = {};
  async function load() {
    const names = ['trace', 'trace_dom', 'watch_dom', 'watch_state', 'ask_dom', 'chrome_dom'];
    await Promise.all(names.map(async (n) => { D[n] = await (await fetch(`data/${n}.json`)).json(); }));
  }

  // the product chrome (classification strip + floating nav), with the right tab marked
  function chrome(active) {
    const c = D.chrome_dom;
    const wrap = document.createElement('div');
    wrap.innerHTML = c.classbar + c.nav;
    $$('.nav-links a', wrap).forEach((a) => cls(a, 'on', a.textContent.trim() === active));
    $$('.nav-links a', wrap).forEach((a) => { if (!a.classList.length) a.removeAttribute('class'); });
    return wrap.innerHTML;
  }
  function tickClock(root, t) {
    // the strip's wall clock, ticking through the film from the capture time (02:39 local / 01:39 UTC)
    const sec = 39 * 60 + 12 + Math.floor(t);
    const hms = (h) => `${String(h).padStart(2, '0')}:${String(Math.floor(sec / 60) % 60).padStart(2, '0')}:${String(sec % 60).padStart(2, '0')}`;
    html($('#prn', root), `<b>PRN</b> ${hms(2)}`);
    text($('#utc', root), `${hms(1)} UTC`);
  }

  // ================================================================ 1. OPEN: noise → question → PARSE
  // A story breaks in three scripts at once. Posts land, the question lands, then the posts stream into the three
  // strokes of the Parse mark, which closes into the lockup.
  const LOGO = ['M3 6C9.5 6 10 12 15 12', 'M3 12H21', 'M3 18C9.5 18 10 12 15 12'];
  function buildOpen() {
    const s = scene('open', 0, 4.62, 1);
    const R = D.trace;
    const byKey = (src, start) => R.graph.nodes.find((n) => n.source === src && n.title.startsWith(start));
    const picks = [
      ['Reporteri', 'Shpërthim në Zubin-Potok', 120, 140, 0.96],
      ['Sputnik Srbija', 'Снажна', 650, 104, 1.0],
      ['Klan Kosova', 'Shpërthimi në Zubin Potok: Pamje', 1200, 168, 0.94],
      ['KoSSev', 'Detonacija', 236, 448, 1.02],
      ['Kurir', 'EKSPLOZIJA', 772, 412, 0.98],
      ['Insajderi', 'Shpërthim i fuqishëm', 1330, 470, 1.0],
      ['RT Balkan', 'Експлозија', 520, 726, 0.95],
      ['Nova', 'Prekinuto', 1090, 760, 0.97],
    ].map(([src, start, x, y, k]) => ({ n: byKey(src, start), x, y, k })).filter((p) => p.n);
    const when = (iso) => new Date(iso).toLocaleString('en-GB', { day: '2-digit', month: 'short', hour: '2-digit', minute: '2-digit', timeZone: 'UTC' });
    const nPosts = R.graph.nodes.filter((n) => !n.probe).length, nSrc = new Set(R.graph.nodes.filter((n) => !n.probe).map((n) => n.source_id)).size;

    s.el.innerHTML = `
      <div class="navy"><div class="smoke"></div><div class="vig"></div></div>
      <div class="grain"></div>
      <div class="hudc"><i></i><i></i><i></i><i></i></div>
      <div class="cbar"><span class="l">${D.chrome_dom.classbar.match(/<svg class="stars[\s\S]*?<\/svg>/)[0]}<span><b>UNCLASSIFIED</b> // OSINT RESEARCH · KOSOVO THEATRE · SQ · SR · EN</span></span>
        <span class="r"><span class="live">Replay · canal_2024_11</span><span class="clock">29 Nov 2024 · <b>19:05</b> UTC</span></span></div>
      <div class="posts">${picks.map((p, i) => `<div class="pc cite" data-i="${i}"><div class="top"><span class="src">${esc(p.n.source)}</span><span class="n">${String(i + 1).padStart(2, '0')}</span></div>
        <div class="t">${esc(p.n.title)}</div>
        <div class="foot"><span class="pill t${p.n.tier}">Tier ${p.n.tier}</span><span class="pill idle">${esc(when(p.n.when))}</span><span class="pill idle">${esc(p.n.lang)}</span></div></div>`).join('')}</div>
      <svg class="bigmark" viewBox="0 0 1920 1080"><g class="bm">${LOGO.map((d, i) => `<path class="f${i + 1}" d="${d}" pathLength="1"/>`).join('')}</g></svg>
      <div class="dots">${picks.map(() => '<i class="travel"></i>').join('')}</div>
      <div class="hook"><div class="eyebrow-f">Ibar–Lepenac canal · 29 Nov 2024 · ${nPosts} posts · ${nSrc} outlets · 3 scripts</div>
        <div class="big">Who said it <em>first?</em></div></div>
      <div class="lockup"><div class="wm">${'PARSE'.split('').map((c) => `<span>${c}</span>`).join('')}</div>
        <div class="sub">OSINT early warning · <b>Kosovo</b></div></div>
      <div class="readout"><span><b>/0.1</b> — Parse</span><span><b>Zubin Potok</b> · 42.93° N · 20.72° E</span><span>Sector KOS · Grid 34T</span></div>`;
    const cards = $$('.pc', s.el), dots = $$('.travel', s.el);
    cards.forEach((c, i) => st(c, { left: `${picks[i].x}px`, top: `${picks[i].y}px` }));
    const hook = $('.hook', s.el), eyebrow = $('.eyebrow-f', hook), hookWords = split($('.big', hook));
    const bm = $('.bm', s.el), paths = $$('path', bm), lock = $('.lockup', s.el), letters = $$('.wm span', lock), sub = $('.sub', lock);
    const smoke = $('.smoke', s.el), grain = $('.grain', s.el), hud = $$('.hudc i', s.el), cbar = $('.cbar', s.el), readout = $('.readout', s.el);
    const ro = split(readout);

    // card landing times: an accelerating pile-up into the downbeat at 2.0 s
    const land = [0.42, 0.67, 0.92, 1.12, 1.3, 1.46, 1.6, 1.72];
    land.forEach((t, i) => cue(t, 'card', i));
    cue(2.0, 'hit'); cue(2.62, 'riser'); cue(3.22, 'brand'); cue(3.98, 'swoosh');

    // mark geometry: logo units → frame. Big (k=50, centred) → lockup (k=5)
    const BIG = { k: 50, x: 360, y: -60 }, LOCK = { k: 7.2, x: 0, y: 0 };
    let lockMeasured = false;
    const pathPts = paths.map((p) => ({ el: p, len: p.getTotalLength() }));
    // which stroke each card's dot joins: top, middle or bottom, by where the card sits
    const lane = picks.map((p) => (p.y < 300 ? 0 : p.y < 600 ? 1 : 2));

    s.seek = (t) => {
      // backdrop: the hero's smoke drifting, grain re-seeded every other frame
      const d = t / 24;
      st(smoke, { transform: `translate3d(${f2(-3 * Math.sin(d * 3.1))}%, ${f2(2 * Math.sin(d * 2.3))}%, 0) scale(${(1 + 0.04 * Math.sin(d * 1.7)).toFixed(4)})` });
      const g = Math.floor(t * 30);
      st(grain, { transform: `translate(${(g * 37) % 64}px, ${(g * 53) % 64}px)` });
      // HUD corners draw in, strip drops down
      hud.forEach((c, i) => { const p = T(t, 0.05 + i * 0.05, 0.6); st(c, { opacity: p.toFixed(3), transform: `scale(${(0.4 + 0.6 * p).toFixed(3)})` }); });
      const cp = T(t, 0.08, 0.5);
      st(cbar, { transform: `translateY(${f2((cp - 1) * 48)}px)` });
      roll(ro, t, 0.3, null, { stag: 0.04, dur: 0.6, y: 100, blur: 0, seed: 9 });

      // the story clock follows the cards as they land
      const mins = Math.round(lerp(19 * 60 + 5, 21 * 60 + 21, T(t, 0.4, 1.5, ez.io)));
      const hhmm = `${String(Math.floor(mins / 60)).padStart(2, '0')}:${String(mins % 60).padStart(2, '0')}`;
      html($('.clock', cbar), `29 Nov 2024 · <b>${hhmm}</b> UTC`);

      // cards: land, dim under the question, collapse into dots
      cards.forEach((c, i) => {
        const p = T(t, land[i], 0.55 + (i % 3) * 0.08);
        const dim = T(t, 1.9, 0.5, ez.io);
        const col = T(t, 2.5 + i * 0.025, 0.3, ez.in);
        const drift = (t - land[i]) * (i % 2 ? 7 : -6);
        const k = picks[i].k * (0.94 + 0.06 * p) * (1 - col);
        st(c, { visibility: t >= land[i] && col < 1 ? 'visible' : 'hidden',
          opacity: (p * (1 - 0.7 * dim)).toFixed(3),
          transform: `translate(${f2(drift)}px, ${f2((1 - p) * 26)}px) scale(${k.toFixed(4)})`,
          clipPath: p >= 1 ? 'none' : `inset(0 0 ${f2((1 - p) * 100)}% 0)` });
      });

      // the question
      roll([eyebrow], t, 1.9, 2.55, { y: 60, blur: 0, dur: 0.6 });
      st(eyebrow, { '--rx': T(t, 1.95, 0.5).toFixed(3) });
      roll(hookWords, t, 2.0, 2.58, { stag: 0.07, dur: 0.72, seed: 3 });

      // dots: from each card to its stroke, then along it to the merge point
      const big = BIG;
      const head = T(t, 2.86, 0.42, ez.io);                       // draw head along the strokes
      dots.forEach((dEl, i) => {
        const c = picks[i], cx = c.x + 200, cy = c.y + 70;
        const L = lane[i], pp = pathPts[L];
        const start = pp.el.getPointAtLength(0);
        const sx = start.x * big.k + big.x, sy = start.y * big.k + big.y;
        const fly = T(t, 2.6 + i * 0.03, 0.32, ez.io);
        const order = picks.slice(0, i).filter((_, j) => lane[j] === L).length;
        const ride = clamp(head - order * 0.07, 0, 1);
        let x = lerp(cx, sx, fly), y = lerp(cy, sy, fly);
        if (ride > 0) {
          const q = pp.el.getPointAtLength(pp.len * Math.min(ride, L === 1 ? 0.66 : 1));
          x = q.x * big.k + big.x; y = q.y * big.k + big.y;
        }
        const vis = t >= 2.55 + i * 0.025 && ride < 0.98;
        const sz = 1 - T(t, 3.1, 0.2);
        st(dEl, { visibility: vis ? 'visible' : 'hidden', transform: `translate(${f2(x)}px, ${f2(y)}px) scale(${sz.toFixed(3)})` });
      });

      // the mark: strokes draw behind the dots, then the whole mark closes down into the lockup
      if (!lockMeasured) {
        // lockup: mark glyph (18 units wide) + gap + wordmark, centred on the frame
        const wmW = $('.wm', lock).getBoundingClientRect().width;
        const total = 18 * LOCK.k + 46 + wmW;
        const left = 960 - total / 2;
        LOCK.x = left - 3 * LOCK.k; LOCK.y = 540 - 12 * LOCK.k;
        st(lock, { left: `${f2(left + 18 * LOCK.k + 46)}px`, top: `${f2(540 - 59)}px` });
        lockMeasured = true;
      }
      const shrink = T(t, 3.18, 0.52, ez.cam);
      const k = Math.exp(lerp(Math.log(big.k), Math.log(LOCK.k), shrink));
      const mx = lerp(big.x + 12 * big.k, LOCK.x + 12 * LOCK.k, shrink) - 12 * k;
      const my = lerp(big.y + 12 * big.k, LOCK.y + 12 * LOCK.k, shrink) - 12 * k;
      const sw = lerp(2.5, 2 * LOCK.k, shrink);
      // exit: the middle stroke runs out to the frame edges and becomes the next scene's first hairline
      const ext = T(t, 3.86, 0.36, ez.io);
      st(bm, { transform: `translate(${f2(mx)}px, ${f2(my)}px) scale(${k.toFixed(4)})` });
      paths.forEach((p, i) => {
        const L = i === 1 ? 1 : 0.999;
        const prog = i === 1 ? Math.max(head * 0.72, T(t, 3.0, 0.4, ez.io)) : head;
        const out = i === 1 ? 0 : T(t, 3.82, 0.24, ez.in);
        st(p, { strokeWidth: f2(sw / k), strokeDasharray: `${L} ${L + 1}`, strokeDashoffset: ((1 - prog) * L).toFixed(4),
          opacity: (1 - out).toFixed(3), visibility: t >= 2.84 ? 'visible' : 'hidden' });
      });
      // the middle stroke stretching to the full frame width in the last beat
      if (ext > 0) {
        const p2 = paths[1];
        const x0 = lerp(3, (-mx) / k, ext), x1 = lerp(21, (1920 - mx) / k, ext);
        attr(p2, 'd', `M${x0.toFixed(3)} 12H${x1.toFixed(3)}`);
        st(p2, { strokeWidth: f2(lerp(sw, 2, ext) / k) });
      } else attr(paths[1], 'd', LOGO[1]);

      // wordmark letters rise in after the mark lands, then leave upwards as the stroke runs out
      letters.forEach((l, i) => {
        const pi = T(t, 3.34 + i * 0.045, 0.6, ez.roll), po = T(t, 3.8 + i * 0.02, 0.3, ez.in);
        st(l, { transform: `translateY(${f2((1 - pi) * 60 - po * 60)}%)`, opacity: (pi * (1 - po)).toFixed(3), filter: pi < 1 ? `blur(${f2((1 - pi) * 8)}px)` : 'none' });
      });
      const sp = T(t, 3.5, 0.5), so = T(t, 3.8, 0.25, ez.in);
      st(sub, { opacity: (sp * (1 - so)).toFixed(3), transform: `translateY(${f2((1 - sp) * 14)}px)`, clipPath: `inset(0 ${f2((1 - sp) * 100)}% 0 0)` });
    };
  }

  // ================================================================ 2. WATCH: the automation raises the alert
  function buildWatch() {
    const s = scene('watch', 3.98, 10.4, 2);
    const W = D.watch_dom, S = D.watch_state;
    const alertIdx = Math.max(0, W.stories.findIndex((x) => x.includes('wt-story alert')));
    const stories = W.stories.slice(0, Math.max(alertIdx + 2, 3));
    s.el.innerHTML = `<div class="rig"><div class="screen">${chrome('Watch')}
      <main class="page wrap">${W.header}${W.ctl}${W.pipe}${W.kpis}
        <div class="wt-main"><section aria-label="Stories"><div class="wt-h"><h2 class="sec"><span>Stories</span><i>/${S.totals.stories} · showing ${Math.min(30, S.stories.length)}</i></h2>
          <div class="wt-filter"><button type="button" class="on">All</button><button type="button">Traced</button><button type="button">Alerts</button></div></div>
          <div class="wt-stories">${stories.join('')}</div></section>
          <aside><h2 class="sec"><span>Incoming posts</span><i>/${S.totals.kosovo}</i></h2>${W.feed}
            <h2 class="sec"><span>Activity log</span><i>automation</i></h2>${W.log}</aside></div>
      </main></div></div>
      <svg class="leader"><path/><rect width="7" height="7"/></svg>
      <div class="callout"><i class="tick a"></i><i class="tick b"></i><i class="tick c"></i><i class="tick d"></i>
        <div class="lbl-f">First post → P1 alert</div><div class="num">73<small>min</small></div>
        <div class="line s">Replay of the canal blast window, as if live</div></div>`;
    const scr = $('.screen', s.el), rig = $('.rig', s.el);
    const tline = document.createElement('div'); tline.className = 'hline'; s.el.appendChild(tline);
    const h1 = $('header.ph h1', scr), h1w = split(h1), lead = $('header.ph .lead', scr);
    const stages = $$('.wt-stage', scr), bigs = $$('.wt-big', scr);
    const finalCounts = bigs.map((b) => parseInt(b.textContent.replace(/\D/g, ''), 10) || 0);
    const kpiB = ['#k-posts', '#k-kos', '#k-stories', '#k-traced', '#k-alerts'].map((id) => $(id, scr));
    const kpiFinal = kpiB.map((b) => parseInt(b.textContent.replace(/\D/g, ''), 10) || 0);
    // what this cycle added, from the replay's own log, so the totals tick from the previous cycle's values
    const cyc = S.cycle;
    const logOf = (re) => S.log.find((l) => l.cycle === cyc && re.test(l.text));
    const newStories = +((logOf(/^Group:/)?.text.match(/→ (\d+) new stories/) || [])[1] || 0);
    const kpiFrom = [kpiFinal[0] - finalCounts[0], kpiFinal[1] - finalCounts[1], kpiFinal[2] - newStories, kpiFinal[3] - finalCounts[3], kpiFinal[4] - finalCounts[4]];
    const status = $('#wt-status', scr), prog = $('#wt-progress', scr), progI = $('#wt-progress i', scr);
    const finalStatus = status.innerHTML;
    const toggle = $('#wt-ai', scr), startBtn = $('#wt-start-btn', scr), stopBtn = $('#wt-stop-btn', scr);
    const card = $$('.wt-story', scr)[alertIdx], banner = card && $('.wt-s-alert', card);
    const feed = $$('#wt-feed li', scr), logLis = $$('#wt-log li', scr);
    const callout = $('.callout', s.el), leader = $('.leader path', s.el), leaderDot = $('.leader rect', s.el);
    const calloutWords = split($('.line', callout));
    const numEl = $('.num', callout);

    // measure in screen coordinates
    const R = (el) => rel(el, scr);
    const rRule = R($('header.ph .ph-top', scr)), rCtl = R($('.wt-ctl', scr)), rPipe = R($('.wt-pipe', scr)), rKpi = R($('.wt-kpis', scr));
    const rCard = card ? R(card) : R($('.wt-stories', scr)), rStart = R(startBtn), rTog = R($('.wt-ai', scr));
    const ruleY = rRule.y + rRule.h;
    const s0 = 1920 / 1440;
    const k0 = { t: 3.98, x: 720, y: ruleY + (540 - 250) / s0, s: s0 };
    // the whole control panel, filling the width
    const kCtl = fit({ x: rCtl.x - 24, y: rCtl.y - 30, w: rCtl.w + 48, h: rCtl.h + 60 }, { w: 1920, fy: 470 });
    const sp = 2.08, pipeY = rPipe.y + rPipe.h + 8;
    const kPipeA = { x: rPipe.x + 960 / sp - 30, y: pipeY, s: sp };
    const kPipeB = { x: rPipe.x + rPipe.w - 960 / sp + 30, y: pipeY, s: sp };
    // the alert card on the left two thirds, leaving the right third for the callout
    const kCard = fit(rCard, { w: 1000, fx: 580, fy: 560 });
    const ST = [6.0, 6.5, 7.0, 7.5, 8.0];                     // stage starts, on the beat
    const TOG = 5.24, GO = 5.54, ALERT = 8.5;
    const keys = [
      { ...k0, t: 3.98 },
      { ...k0, t: 4.92, y: k0.y + 12 },
      { ...kCtl, t: 5.32 },
      { ...kCtl, t: 5.62, s: kCtl.s * 1.015, e: ez.io },
      { ...kPipeA, t: 6.02 },
      { ...kPipeB, t: 8.02, e: ez.io },
      { ...kCard, t: 8.6 },
      { ...kCard, t: 9.7, s: kCard.s * 1.035, e: ez.io },
      { ...kCard, t: 10.4, s: kCard.s * 1.45, x: kCard.x + 80, y: kCard.y + 30, e: ez.in },
    ];
    ST.forEach((t, i) => cue(t, i === 4 ? 'alertstage' : 'stage', i));
    cue(TOG, 'click'); cue(GO, 'click'); cue(ALERT, 'alert'); cue(9.95, 'whoosh');
    const stageNames = ['collect', 'filter', 'group', 'trace', 'alert'];
    const startIn = $('#wt-start', scr);
    if (startIn) startIn.value = '2024-11-29T12:00';

    s.seek = (t) => {
      // entrance: the Parse stroke drops to the page's first hairline and the page opens beneath it
      const lineY0 = 540, lineY1 = 250;
      const down = T(t, 3.98, 0.42, ez.cam);
      const lineY = lerp(lineY0, lineY1, down);
      const top = T(t, 4.36, 0.34, ez.cam);
      const clipTop = lerp(lineY, 0, top);
      st(s.el, { clipPath: clipTop < 0.5 ? 'none' : `inset(${f2(Math.max(0, clipTop - 1))}px 0 0 0)` });
      // the white stroke rides the opening edge, then settles into the page's own hairline colour
      st(tline, { top: `${f2(clipTop - 1)}px`, opacity: t < 4.72 && clipTop > 0.5 ? (1 - 0.7 * top).toFixed(3) : '0' });
      const v = camAt(keys, t);
      applyCam(scr, rig, v, 0);
      tickClock(scr, t);

      roll(h1w, t, 4.16, null, { stag: 0.05, dur: 0.66, seed: 5 });
      rise(lead, t, 4.4, 0.7, 14);

      // controls: the analyst switches on Qwen checks and starts the replay
      toggle.checked = t >= TOG + 0.02;
      const running = t >= GO + 0.06;
      startBtn.hidden = running; stopBtn.hidden = !running;
      cls(startBtn, 'f-press', t >= GO - 0.02 && t < GO + 0.06);
      cls(startBtn, 'btn-hover', t >= GO - 0.2 && t < GO + 0.06);
      const si = ST.filter((x) => t >= x).length - 1;
      const stage = si < 0 ? 'collect' : stageNames[si];
      if (!running) {
        cls(status, 'on', false);
        html(status, '<span class="dot"></span>Idle. Choose a mode and start.');
      } else {
        cls(status, 'on', true);
        // while stages run there is no "next cycle in" countdown: that belongs to the wait between cycles
        html(status, finalStatus.replace(/stage <b>[a-z]+<\/b>/, `stage <b>${stage}</b>`).replace(/ · next cycle in \d+s/, ''));
      }
      prog.hidden = !running;
      st(progI, { width: `${f2(lerp(26, 37.5, T(t, GO, 2.9, ez.io)))}%` });

      // pipeline stages light up one per beat, each count rolls to the cycle's real number
      stages.forEach((el, i) => {
        cls(el, 'active', running && si === i && t < 8.45);
        const p = T(t, ST[i], 0.38, ez.out);
        text(bigs[i], fmt(finalCounts[i] * p));
      });
      // totals follow the stage that feeds them
      const feedOf = [0, 1, 2, 3, 4];
      kpiB.forEach((b, i) => { const p = T(t, ST[feedOf[i]] + 0.1, 0.45); text(b, fmt(lerp(kpiFrom[i], kpiFinal[i], p))); });

      // incoming posts stream in while the pipeline runs: the newest eight land at the top, oldest first
      feed.forEach((li, i) => {
        if (i > 7) { st(li, { opacity: '1', transform: 'none' }); return; }
        const p = T(t, 6.1 + (7 - i) * 0.24, 0.5);
        st(li, { opacity: p.toFixed(3), transform: p >= 1 ? 'none' : `translateY(${f2((p - 1) * 18)}px)` });
      });
      logLis.forEach((li, i) => { const p = i > 5 ? 1 : T(t, 6.2 + (5 - i) * 0.36, 0.45); st(li, { opacity: p.toFixed(3) }); });

      // the alert: banner opens on the story card, the card's edge turns red
      if (card) {
        const ap = T(t, ALERT, 0.4, ez.out);
        cls(card, 'alert', t >= ALERT);
        st(banner, { clipPath: ap >= 1 ? 'none' : `inset(0 ${f2((1 - ap) * 100)}% 0 0)`, opacity: t >= ALERT ? '1' : '0' });
        cls(card, 'fresh', false);
      }

      // callout: 73 min, with a leader from the banner
      const C0 = ALERT + 0.3;
      const cIn = T(t, C0, 0.55, ez.out), cOut = T(t, 9.95, 0.3, ez.in);
      show(callout, t >= C0 && cOut < 1);
      if (t >= C0 - 0.1) {
        const br = frameRect(banner || card);
        const cx = 1190, cy = 330;
        st(callout, { left: `${cx}px`, top: `${cy}px`, width: '600px', opacity: (1 - cOut).toFixed(3),
          clipPath: cIn >= 1 ? 'none' : `inset(0 0 ${f2((1 - cIn) * 100)}% 0)`, transform: `translateY(${f2((1 - cIn) * 16 - cOut * 20)}px)` });
        const n = Math.round(73 * T(t, C0 + 0.08, 0.55, ez.out));
        html(numEl, `${n}<small>min</small>`);
        roll(calloutWords, t, C0 + 0.25, null, { stag: 0.03, dur: 0.55, blur: 4, seed: 4 });
        const ax = br.left + br.width, ay = br.top + br.height / 2;
        const lp = T(t, C0 - 0.1, 0.45, ez.io);
        const ex = lerp(ax, cx, lp), ey = lerp(ay, cy + 150, lp);
        attr(leader, 'd', `M${f2(ax)} ${f2(ay)}H${f2(ax + (ex - ax) * 0.5)}L${f2(ex)} ${f2(ey)}`);
        st(leader, { opacity: (1 - cOut).toFixed(3) });
        attr(leaderDot, 'x', f2(ax - 3.5)); attr(leaderDot, 'y', f2(ay - 3.5));
        st(leaderDot, { opacity: (lp * (1 - cOut)).toFixed(3) });
      } else { st(leader, { opacity: '0' }); st(leaderDot, { opacity: '0' }); }

      // cursor: toggle, then start
      const tg = frameRect($('.wt-ai input', scr)), sb = frameRect(running ? stopBtn : startBtn);
      const ck = [
        { t: 4.78, x: 1480, y: 1150 },
        { t: 5.2, x: tg.left + tg.width * 0.5, y: tg.top + tg.height * 0.55 },
        { t: 5.3, x: tg.left + tg.width * 0.5, y: tg.top + tg.height * 0.55 },
        { t: 5.5, x: sb.left + sb.width * 0.42, y: sb.top + sb.height * 0.56 },
        { t: 6.0, x: sb.left + sb.width * 0.42 + 70, y: sb.top + sb.height * 0.56 + 300 },
      ];
      const c = t < 6.1 ? cursorAt(ck, [[TOG - 0.02, TOG + 0.04], [GO - 0.02, GO + 0.05]], t) : null;
      if (c) Object.assign(CUR, c, { on: true });
    };
    s.keys = keys;
  }

  // ================================================================ 3. TRACE: where did it start, who carried it
  const STEP_SUB = {
    seed: 'The post, link, screenshot or text to trace', expand: 'Shared words, links, images and meaning, in any language',
    graph: 'Forward · quote · copy · link · translate', origin: 'Earliest node with no parent, and how sure',
    amplifiers: 'Who passed it on, and how far', discover: 'Upstream sites outside the registry', world: 'Official statements and trigger dates',
    score: 'Speed, origins, platforms, coordination, place', verify: 'One post per origin group; verdict by fixed rules',
    brief: 'What it is, where it began, who carried it',
  };
  function buildTrace() {
    const s = scene('trace', 9.96, 22.42, 3);
    const R = D.trace, TD = D.trace_dom, C = D.chrome_dom;
    const seedText = R.seed.text || (R.steps[0] && R.steps[0].summary) || '';
    const fmtWhen = (iso) => new Date(iso).toLocaleString('en-GB', { day: '2-digit', month: 'short', year: 'numeric', hour: '2-digit', minute: '2-digit', timeZone: 'UTC' });
    const runner = R.origin.reasons.find((x) => /appeared (\d+) min later/.test(x));
    const runnerTxt = runner ? runner.replace(/^.*?post \((.*?)\) appeared (\d+) min later.*$/, '$1 · $2 min later') : '';
    s.el.innerHTML = `<div class="rig"><div class="screen">${chrome('Trace')}
      <main class="page wrap">${C.trace_header}${C.trace_why}${C.trace_input}
        <div class="tr-main" id="tr-main">${TD.rail}<div class="tr-out-wrap">${TD.out}</div></div></main>
      <div class="tr-tip" hidden></div></div></div>
      <div class="sweep"></div>
      <div class="scrim"></div>
      <svg class="leader"><path/><rect width="7" height="7"/></svg>
      <div class="callout co-origin"><i class="tick a"></i><i class="tick b"></i><i class="tick c"></i><i class="tick d"></i>
        <div class="lbl-f" style="--rule:#5cc58a">Earliest observed source</div>
        <div class="line">${esc(R.origin.source)} <span style="color:#a3a6ab">· Tier ${R.origin.tier}</span></div>
        <div class="line s">${esc(fmtWhen(R.origin.when))} UTC</div>
        ${runnerTxt ? `<div class="line s">Next independent post: ${esc(runnerTxt)}</div>` : ''}</div>
      <div class="callout co-rules"><i class="tick a"></i><i class="tick b"></i><i class="tick c"></i><i class="tick d"></i>
        <div class="lbl-f" style="--rule:#8faaf0">The rules · decided by fixed code</div>
        <table class="rules">
          <tr data-v="DEBUNKED"><td><span class="pill bad">DEBUNKED</span></td><td>A Tier-0 source contradicts within its own scope, or the media is recycled from an earlier event.</td></tr>
          <tr data-v="CONFIRMED"><td><span class="pill ok">CONFIRMED</span></td><td>At least one Tier-0 source supports within its own scope, and nothing contradicts.</td></tr>
          <tr data-v="DISPUTED"><td><span class="pill warn">DISPUTED</span></td><td>Both supporting and contradicting evidence exist.</td></tr>
          <tr data-v="CORROBORATED"><td><span class="pill acc">CORROBORATED</span></td><td>At least 2 independent origin groups at Tier ≤ 2 support it.</td></tr>
          <tr data-v="UNVERIFIED"><td><span class="pill idle">UNVERIFIED</span></td><td>Anything else. Lists what is missing as suggested checks.</td></tr>
        </table></div>
      <div class="cap cap-verify"><div class="eyebrow-f" style="--rule:#8faaf0">Step 09 · Is it true?</div><div class="big">A model labels<br>the evidence.<br><span style="color:#a3a6ab">Fixed rules decide<br>the verdict.</span></div></div>`;
    const scr = $('.screen', s.el), rig = $('.rig', s.el);
    const out = $('.tr-out-wrap', scr);
    st(out, { minWidth: '0' });
    const ta = $('#tr-text', scr), go = $('#tr-go', scr), ex = $$('.tr-examples button', scr);
    const exBtn = ex.find((b) => (b.dataset.text || '').startsWith(seedText.slice(0, 12))) || ex[0];
    const h1w = split($('header.ph h1', scr));
    const leadP = $('header.ph .lead', scr), why = $('.tr-why', scr);
    html($('#tr-engine', scr), 'Engine <b>Qwen</b> · checks the claim and writes the brief (billed, ~$0.001)');
    const steps = $$('.tr-step', scr);
    const stepData = Object.fromEntries((R.steps || []).map((x) => [x.id, x]));
    steps.forEach((li) => li.classList.remove('open'));
    const clock = $('#tr-clock', scr);
    const trOut = $('#tr-out', scr) || out.firstElementChild;
    const wait = document.createElement('div');
    wait.className = 'tr-wait';
    wait.textContent = 'Tracing. The first trace of a story embeds its posts on this machine, so it can take up to a minute; repeats are fast.';
    wait.style.display = 'none';
    trOut.prepend(wait);
    const sections = [...trOut.children].filter((x) => x !== wait);
    const brief = $('.tr-brief', trOut), headline = $('.tr-headline', brief), narr = $('.tr-narr', brief);
    const badges = $$('.tr-badges .pill', brief), cols = $$('.tr-cols > div', brief);
    const hw = split(headline);

    // ---- spread graph: the product's SVG, revealed by a playhead that sweeps its time axis
    const svg = $('#tr-svg svg', trOut);
    const nodesEl = $$('.n', svg), edgesEl = $$('path.e', svg), lanes = $$('.lane', svg), laneL = $$('.lane-l', svg);
    const ring = $('.ring', svg), tag = $('.tag-l', svg), seedmark = $('.seedmark', svg);
    // two day labels side by side (a post just before midnight, the next one the day after) overprint each other:
    // keep both day lines, hide the earlier label
    const dayL = $$('.day-l', svg);
    dayL.forEach((d, i) => { const nx = dayL[i + 1]; if (nx && +nx.getAttribute('x') - +d.getAttribute('x') < 46) d.style.display = 'none'; });
    const days = $$('.day, .day-l', svg).filter((d) => d.style.display !== 'none');
    const graphSec = $('#tr-svg', trOut).closest('section');
    const W = +svg.getAttribute('width'), Hh = +svg.getAttribute('height');
    const xOf = (el) => +(el.getAttribute('cx') || (+el.getAttribute('x') + 6));
    const yOf = (el) => +(el.getAttribute('cy') || (+el.getAttribute('y') + 6));
    const lw = Math.min(...nodesEl.map(xOf)) - 14, rw = Math.max(...nodesEl.map(xOf)) + 14;
    const ns = 'http://www.w3.org/2000/svg';
    const defs = document.createElementNS(ns, 'defs');
    defs.innerHTML = `<clipPath id="sweepclip"><rect x="0" y="0" width="0" height="${Hh}"/></clipPath>`;
    svg.prepend(defs);
    const clipRect = $('#sweepclip rect', svg);
    const eg = document.createElementNS(ns, 'g');
    eg.setAttribute('clip-path', 'url(#sweepclip)');
    edgesEl.forEach((e) => eg.appendChild(e));
    svg.insertBefore(eg, svg.querySelector('.n, .ring') || null);
    const playhead = document.createElementNS(ns, 'line');
    playhead.setAttribute('y1', '16'); playhead.setAttribute('y2', String(Hh - 6));
    playhead.setAttribute('stroke', '#f1f1f1'); playhead.setAttribute('stroke-width', '1.2');
    svg.appendChild(playhead);
    const origin = R.origin.signal_id, oEl = nodesEl.find((n) => n.dataset.id === origin);
    const rFinal = nodesEl.map((n) => +n.getAttribute('r') || 0);
    // the longest chain of spread steps in the trace, for the product's hover highlight
    const parentOf = Object.fromEntries(R.graph.edges.map((e, i) => [e.to, i]));
    const lineage = (id) => {
      const ids = new Set([id]), es = new Set(); let c = id, k = 0;
      while (parentOf[c] !== undefined && k++ < 60) { es.add(parentOf[c]); c = R.graph.edges[parentOf[c]].from; ids.add(c); }
      return { ids, es, root: c };
    };
    let best = null;
    R.graph.nodes.forEach((n) => {
      if (n.probe) return;
      const L = lineage(n.id);
      if (!best || L.es.size > best.L.es.size || (L.es.size === best.L.es.size && (n.when || '') > (best.n.when || ''))) best = { n, L };
    });
    const hoverEl = best && nodesEl.find((x) => x.dataset.id === best.n.id);
    const tip = $('.tr-tip', scr);
    if (best) {
      const n = best.n;
      tip.innerHTML = `<span class="lbl">${esc(n.source)} · T${n.tier} · ${esc(n.lang || '?')}</span>${esc(n.title)}<br><span class="mono" style="font-size:11px;color:#b9b9b9">${esc(fmtWhen(n.when))} UTC · reach ${n.reach} · ${best.L.es.size} spread steps back</span>`;
      st(tip, { position: 'absolute' });
    }

    // ---- claim check, the rules, the caption
    const claimSec = [...trOut.querySelectorAll('section')].find((x) => /claim check/i.test(x.textContent.slice(0, 80)));
    const claimRows = claimSec ? $$('tbody tr', claimSec) : [];
    const claimP = claimSec && $('p', claimSec);
    const rules = $('.co-rules', s.el), ruleRows = $$('tr', rules), capV = $('.cap-verify', s.el), scrim = $('.scrim', s.el);
    const capVw = split($('.big', capV)), capVe = $('.eyebrow-f', capV);
    const coO = $('.co-origin', s.el), coOl = $$('.line', coO);
    const leader = $('.leader path', s.el), leaderDot = $('.leader rect', s.el);

    // ---- camera, from measured layout (screen coordinates)
    const Rr = (el) => rel(el, scr);
    const rH = Rr($('header.ph', scr)), rIn = Rr($('.tr-input', scr)), rRail = Rr($('.tr-rail', scr));
    const rBrief = Rr(brief), rHead = Rr($('.tr-brief-h', brief)), rSvg = Rr(svg), rGraph = Rr($('.tr-graph', graphSec));
    const rClaim = claimSec ? Rr(claimSec) : rGraph;
    const rStep = steps.map(Rr);
    const kTop = fit({ x: 60, y: rH.y + 10, w: 1320, h: rIn.y + rIn.h - rH.y }, { w: 1740, fy: 548 });
    const sR = 1.62;
    const railKey = (i) => ({ x: rRail.x + (960 - 130) / sR, y: clamp(rStep[i].y + rStep[i].h / 2, rRail.y + 540 / sR - 40, rRail.y + rRail.h - 540 / sR + 40), s: sR });
    const kBrief = fit({ x: rBrief.x, y: rHead.y, w: rBrief.w, h: rHead.h }, { w: 1720, fy: 520 });
    const oX = oEl ? rSvg.x + xOf(oEl) : rSvg.x + 260, oY = oEl ? rSvg.y + yOf(oEl) : rSvg.y + 60;
    const kOrigin = { x: rSvg.x + 960 / 2.3 - 34, y: rSvg.y + Hh / 2 + 14, s: 2.3 };   // lane names fully in frame
    const kGraph = fit({ x: rGraph.x, y: rGraph.y - 40, w: rGraph.w, h: rGraph.h + 40 }, { w: 1840, fy: 560 });
    const kClaim = fit({ x: rClaim.x, y: rClaim.y, w: rClaim.w, h: 560 }, { w: 1720, fy: 90, ay: 0 });
    const STEP0 = 11.62, STEPD = 0.19, STEP_END = STEP0 + 9 * STEPD + 0.12;
    const BRIEF = 13.5, B0 = 13.95, BD = 0.24;
    const SA0 = 15.72, SA1 = 16.28, SB0 = 16.98, SB1 = 18.0, HOV = 18.12, CL = 19.12, RULES = 20.42;
    const keys = [
      { ...kTop, t: 9.96, s: kTop.s * 0.985 },
      { ...kTop, t: 11.28, e: ez.io },
      { ...railKey(0), t: 11.68 },
      { ...railKey(9), t: STEP_END + 0.1, e: ez.io },
      { ...kBrief, t: BRIEF + 0.4 },
      { ...kBrief, t: 15.2, s: kBrief.s * 1.03, e: ez.io },
      { ...kOrigin, t: 15.68 },
      { ...kOrigin, t: 16.95, s: kOrigin.s * 1.04, e: ez.io },
      { ...kGraph, t: 17.75, e: ez.io },
      { ...kGraph, t: 18.72, s: kGraph.s * 1.03, e: ez.io },
      { ...kClaim, t: CL, e: ez.cam },
      { ...kClaim, t: 22.42, s: kClaim.s * 1.04, e: ez.io },
    ];
    // sound
    cue(10.95, 'click'); cue(BRIEF, 'brief');
    steps.forEach((_, i) => cue(STEP0 + i * STEPD + 0.12, 'step', i));
    badges.forEach((_, i) => cue(B0 + i * BD, 'stamp', i));
    cue(15.45, 'whoosh'); cue(18.75, 'whoosh');
    claimRows.forEach((_, i) => cue(CL + 0.2 + i * 0.17, 'row', i));
    cue(RULES + 0.4, 'verdict');

    // playhead: slow up to the origin, a pause on it, then fast across the spread
    const xO = oEl ? xOf(oEl) : lw + 80;
    const sweepX = (t) => (t < SB0 ? lerp(lw, xO + 30, T(t, SA0, SA1 - SA0, ez.out)) : lerp(xO + 30, rw, T(t, SB0, SB1 - SB0, ez.io)));
    const samples = []; for (let k = 0; k <= 240; k++) { const tt = SA0 + (SB1 - SA0) * k / 240; samples.push([tt, sweepX(tt)]); }
    const nodeT = nodesEl.map((n) => { const x = xOf(n); const hit = samples.find(([, sx]) => sx >= x); return hit ? hit[0] : SB1; });
    const oT = oEl ? nodeT[nodesEl.indexOf(oEl)] : SA1;
    cue(oT + 0.02, 'origin');
    nodeT.forEach((t, i) => { if (i % 4 === 1 && t > oT + 0.2) cue(t, 'node', i); });

    s.seek = (t) => {
      // entrance: a vertical hairline sweeps right to left, the page opens behind it
      const wp = T(t, 9.96, 0.5, ez.cam);
      st(s.el, { clipPath: wp >= 1 ? 'none' : `inset(0 0 0 ${f2((1 - wp) * 100)}%)` });
      st($('.sweep', s.el), { left: `${f2((1 - wp) * 1920)}px`, opacity: wp > 0 && wp < 1 ? '1' : '0' });
      applyCam(scr, rig, camAt(keys, t));
      tickClock(scr, t);
      roll(h1w, t, 10.12, null, { stag: 0.045, dur: 0.62, seed: 7 });
      rise(leadP, t, 10.3, 0.6, 12);
      rise(why, t, 10.42, 0.6, 16);

      // the analyst clicks the canal example: the text lands and the trace starts
      const typed = t >= 11.0;
      if (ta.value !== (typed ? seedText : '')) ta.value = typed ? seedText : '';
      cls(exBtn, 'f-press', t >= 10.93 && t < 11.02);
      st(exBtn, { borderColor: t >= 10.75 && t < 11.3 ? 'var(--line-2)' : '' });
      go.disabled = typed && t < STEP_END;
      st(ta, { clipPath: !typed ? 'none' : `inset(0 ${f2((1 - T(t, 11.0, 0.24, ez.out)) * 100)}% 0 0)` });

      // steps: wait → run (shimmer) → ok, a fifth of a second each, real timings beside them
      steps.forEach((li, i) => {
        const t0 = STEP0 + i * STEPD, d = stepData[li.dataset.step] || {};
        const stt = t >= t0 + 0.12 ? 'ok' : typed && t >= t0 - STEPD + 0.12 ? 'run' : 'wait';
        if (li.dataset.state !== stt) li.dataset.state = stt;
        text($('.tr-sum', li), stt === 'ok' ? (d.summary || '') : STEP_SUB[li.dataset.step] || '');
        text($('.tr-ms', li), stt === 'ok' && d.ms != null ? (d.ms >= 1000 ? (d.ms / 1000).toFixed(1) + 's' : Math.round(d.ms) + 'ms') : '');
        if (stt === 'run') st($('.tr-st b', li), { backgroundPosition: `${f2(-200 * ((t % 1.4) / 1.4))}% 0` });
      });
      text(clock, typed ? `${(((R.ms || 0) / 1000) * T(t, STEP0 - 0.1, STEP_END - STEP0 + 0.1, ez.lin)).toFixed(1)}s` : '');

      // results: the wait box, then the brief as the last step lands
      const done = t >= STEP_END - 0.02;
      st(wait, { display: typed && !done ? 'block' : 'none' });
      sections.forEach((x) => st(x, { visibility: done ? 'visible' : 'hidden' }));
      if (done) {
        clipIn(brief, t, BRIEF, 0.45, 'down');
        roll(hw, t, BRIEF + 0.05, null, { stag: 0.02, dur: 0.55, blur: 5, seed: 11 });
        rise(narr, t, BRIEF + 0.3, 0.6, 10);
        badges.forEach((b, i) => {
          const p = T(t, B0 + i * BD, 0.34, ez.out);
          st(b, { opacity: p.toFixed(3), transform: `scale(${(1.4 - 0.4 * p).toFixed(3)})`, transformOrigin: '0 50%' });
        });
        cols.forEach((c, i) => rise(c, t, BRIEF + 0.5 + i * 0.12, 0.6, 14));
      }

      // graph: lanes draw, the playhead sweeps, nodes land, the origin locks on
      lanes.forEach((l, i) => { const p = T(t, 15.5 + i * 0.012, 0.5); attr(l, 'x2', f2(lerp(+l.getAttribute('x1'), W - 6, p))); });
      laneL.forEach((l, i) => st(l, { opacity: T(t, 15.5 + i * 0.018, 0.4).toFixed(3) }));
      days.forEach((d) => st(d, { opacity: T(t, 15.6, 0.5).toFixed(3) }));
      const px = sweepX(t);
      attr(clipRect, 'width', f2(Math.max(0, px)));
      attr(playhead, 'x1', f2(px)); attr(playhead, 'x2', f2(px));
      st(playhead, { opacity: (T(t, SA0 - 0.1, 0.2) * (1 - T(t, SB1, 0.3))).toFixed(3) });
      nodesEl.forEach((n, i) => {
        const p = T(t, nodeT[i], 0.32, ez.out);
        if (n.tagName === 'circle') attr(n, 'r', f2(rFinal[i] * p));
        else st(n, { opacity: p.toFixed(3) });
      });
      if (ring) {
        const p = T(t, oT, 0.45, ez.out);
        attr(ring, 'r', f2(lerp(30, 10, p)));
        st(ring, { opacity: p.toFixed(3) });
        st(tag, { opacity: T(t, oT + 0.1, 0.3).toFixed(3) });
      }
      if (seedmark) st(seedmark, { opacity: T(t, SB1 - 0.2, 0.3).toFixed(3) });

      // origin callout, to the right of the ring while that side of the graph is still empty
      const cIn = T(t, oT + 0.12, 0.5), cOut = T(t, SB0 - 0.12, 0.24, ez.in);
      show(coO, t >= oT + 0.12 && cOut < 1);
      if (oEl && t >= oT && t < SB0 + 0.2) {
        const o = frameRect(oEl);
        const ax = o.left + o.width / 2, ay = o.top + o.height / 2;
        const bx = 1080, by = 230;
        st(coO, { left: `${bx}px`, top: `${by}px`, width: '700px', opacity: (1 - cOut).toFixed(3),
          clipPath: cIn >= 1 ? 'none' : `inset(0 0 ${f2((1 - cIn) * 100)}% 0)` });
        roll(coOl, t, oT + 0.2, null, { stag: 0.08, dur: 0.5, blur: 4, seed: 12 });
        const lq = T(t, oT + 0.04, 0.4, ez.io);
        const ex2 = lerp(ax + 22, bx, lq), ey2 = lerp(ay, by + 70, lq);
        attr(leader, 'd', `M${f2(ax + 22)} ${f2(ay)}H${f2(ax + 22 + (ex2 - ax - 22) * 0.5)}L${f2(ex2)} ${f2(ey2)}`);
        st(leader, { opacity: (1 - cOut).toFixed(3) });
        attr(leaderDot, 'x', f2(ax + 22 - 3.5)); attr(leaderDot, 'y', f2(ay - 3.5));
        st(leaderDot, { opacity: (lq * (1 - cOut)).toFixed(3) });
      } else { st(leader, { opacity: '0' }); st(leaderDot, { opacity: '0' }); }

      // hover the most-travelled post: its chain of spread steps lights up (the product's own hover)
      const hov = best && t >= HOV + 0.3 && t < 18.78;
      nodesEl.forEach((n) => cls(n, 'dim', hov && !best.L.ids.has(n.dataset.id)));
      edgesEl.forEach((p) => { const on = hov && best.L.es.has(+p.dataset.i); cls(p, 'hl', on); cls(p, 'dim', hov && !on); });
      tip.hidden = !hov;
      if (hov && hoverEl) {
        const sx = rSvg.x + xOf(hoverEl), sy = rSvg.y + yOf(hoverEl);
        const flip = sx > rSvg.x + rSvg.w * 0.6;   // near the right edge the tooltip opens to the left of the post
        st(tip, { left: `${f2(flip ? sx - 16 - 340 : sx + 16)}px`, top: `${f2(sy + 16)}px`, width: '340px', opacity: T(t, HOV + 0.3, 0.2).toFixed(3) });
      }

      // cursor: the example button, then the hover
      let c = null;
      if (t < 11.7) {
        const eb = frameRect(exBtn);
        c = cursorAt([{ t: 10.4, x: 1640, y: 1160 }, { t: 10.88, x: eb.left + eb.width * 0.45, y: eb.top + eb.height * 0.6 },
          { t: 11.5, x: eb.left + 230, y: eb.top + 320 }], [[10.93, 11.0]], t);
      } else if (hoverEl && t >= HOV - 0.35 && t < 19.0) {
        const hr = frameRect(hoverEl), hx = hr.left + hr.width / 2, hy = hr.top + hr.height / 2;
        c = cursorAt([{ t: HOV - 0.35, x: hx + 280, y: hy + 300 }, { t: HOV + 0.28, x: hx + 2, y: hy + 2 }, { t: 18.76, x: hx + 2, y: hy + 2 },
          { t: 18.98, x: hx + 40, y: hy - 160 }], [], t);
      }
      if (c) Object.assign(CUR, c, { on: true });

      // claim check: one post per independent origin group, then the rules decide
      if (claimP) rise(claimP, t, CL + 0.05, 0.4, 8);
      claimRows.forEach((tr, i) => {
        const p = T(t, CL + 0.2 + i * 0.17, 0.42);
        st(tr, { opacity: p.toFixed(3), transform: p >= 1 ? 'none' : `translateX(${f2((1 - p) * -24)}px)` });
      });
      const sp = T(t, RULES, 0.45, ez.out);
      st(scrim, { opacity: (0.93 * sp).toFixed(3), display: t >= RULES ? 'block' : 'none' });
      const rIn = T(t, RULES + 0.1, 0.5), verdict = R.verdict.verdict;
      show(rules, t >= RULES + 0.1);
      st(rules, { left: '1000px', top: '236px', width: '820px', clipPath: rIn >= 1 ? 'none' : `inset(0 0 ${f2((1 - rIn) * 100)}% 0)` });
      ruleRows.forEach((tr, i) => {
        const p = T(t, RULES + 0.2 + i * 0.07, 0.4);
        const on = tr.dataset.v === verdict, lit = T(t, RULES + 0.62, 0.35);
        st(tr, { opacity: (p * (on ? 1 : 1 - 0.62 * lit)).toFixed(3), background: on && lit > 0 ? `rgba(143,170,240,${(0.14 * lit).toFixed(3)})` : 'transparent' });
      });
      show(capV, t >= RULES + 0.2);
      roll([capVe], t, RULES + 0.2, null, { y: 60, blur: 0, dur: 0.5 });
      st(capVe, { '--rx': T(t, RULES + 0.25, 0.5).toFixed(3) });
      roll(capVw, t, RULES + 0.3, null, { stag: 0.05, dur: 0.62, seed: 13 });
    };
  }

  // ================================================================ 4. ASK: query the archive, every step on the record
  function buildAsk() {
    const s = scene('ask', 21.98, 26.42, 4);
    const A = D.ask_dom;
    s.el.innerHTML = `<div class="rig"><div class="screen ask-screen">${chrome('Ask')}${A.deck}
      <section class="thread" style="display:block">${A.turn}</section></div></div>`;
    const scr = $('.screen', s.el), rig = $('.rig', s.el);
    const tline = document.createElement('div'); tline.className = 'hline'; s.el.appendChild(tline);
    st(scr, { background: 'var(--bg-2)' });
    const q = 'What happened at Banjska, and who reported it first?';
    const taEl = $('#q', scr), send = $('#send', scr), card = $('.ops-card', scr);
    const sweep = $('.radar .sweep', scr), blips = $$('.radar .blip', scr);
    const turn = $('.turn', scr), steps = $$('.cs', turn), head = $('.cot-head', turn), bar = $('.cot-bar i', turn);
    const bubble = $('.q-bubble', turn), meta = $('.q-meta', turn), ansH = $('.answer h3', turn);
    const answerRest = $$('.answer > *', turn).filter((x) => x !== ansH);
    const fmap = $('.fmap', turn);
    if (fmap) st(fmap, { display: 'none' });
    st($('.answer', turn), { visibility: 'hidden' });
    const vault = steps.find((x) => /evidence vault/i.test(x.textContent));
    const hl = document.createElement('div'); hl.className = 'hl'; s.el.appendChild(hl);
    const Rr = (el) => rel(el, scr);
    const rCard = Rr(card), rTurn = Rr(turn), rVault = vault ? Rr(vault) : Rr(turn);
    const kCard = fit(rCard, { w: 1700, fy: 520 });
    const sT = 1.58, cx = rTurn.x + rTurn.w / 2;
    const keys = [
      { ...kCard, t: 21.98, s: kCard.s * 0.94, y: kCard.y + 60 },
      { ...kCard, t: 22.5 },
      { ...kCard, t: 23.72, s: kCard.s * 1.04, e: ez.io },
      { x: cx, y: rTurn.y + 540 / sT - 40, s: sT, t: 24.22, e: ez.cam },
      { x: cx, y: rVault.y + rVault.h / 2 - 40, s: sT, t: 25.5, e: ez.io },
      { x: cx, y: rVault.y + rVault.h / 2 - 30, s: sT * 1.04, t: 26.42, e: ez.io },
    ];
    const typeT0 = 22.5, cps = 46;
    const r = rng(21);
    const charT = []; let acc = typeT0;
    for (let i = 0; i < q.length; i++) { charT.push(acc); acc += (1 / cps) * (0.6 + r() * 0.8) + (q[i] === ' ' ? 0.012 : 0); }
    charT.forEach((t, i) => { if (i % 3 === 0) cue(t, 'key', i); });
    cue(23.82, 'click'); cue(23.95, 'whoosh');
    steps.forEach((_, i) => cue(24.25 + i * 0.12, 'step', i));
    cue(25.42, 'stamp');

    s.seek = (t) => {
      const wp = T(t, 21.98, 0.5, ez.cam), edge = (1 - wp) * 1080;
      st(s.el, { clipPath: wp >= 1 ? 'none' : `inset(${f2(Math.max(0, edge - 1))}px 0 0 0)` });
      st(tline, { top: `${f2(edge - 1)}px`, opacity: wp > 0 && wp < 1 ? '1' : '0' });
      applyCam(scr, rig, camAt(keys, t));
      tickClock(scr, t);
      st(sweep, { transform: `rotate(${f2((t * 72) % 360)}deg)`, transformOrigin: '270px 96px' });
      blips.forEach((b, i) => st(b, { opacity: Math.floor((t + i * 0.8) / 1.25) % 2 ? '0.2' : '1' }));
      const n = charT.filter((x) => t >= x).length;
      const val = q.slice(0, n);
      if (taEl.value !== val) taEl.value = val;
      cls(send, 'f-ready', n > 0);
      cls(send, 'f-press', t >= 23.8 && t < 23.88);
      // the turn: question bubble, reasoning steps, answer
      const sent = t >= 23.9;
      rise(bubble, t, 23.95, 0.5, 20); rise(meta, t, 24.05, 0.5, 10);
      rise(head, t, 24.1, 0.5, 10);
      st(bar, { width: `${f2(100 * T(t, 24.2, 1.3, ez.io))}%` });
      steps.forEach((li, i) => { const p = T(t, 24.25 + i * 0.12, 0.42); st(li, { opacity: sent ? p.toFixed(3) : '0', transform: p >= 1 ? 'none' : `translateY(${f2((1 - p) * 14)}px)` }); });
      rise(ansH, t, 25.45, 0.5, 12);
      answerRest.forEach((x, i) => rise(x, t, 25.55 + i * 0.05, 0.5, 10));
      // the evidence vault step: every archived page still matches its SHA-256
      if (vault && t >= 25.42) {
        const v = frameRect(vault), p = T(t, 25.42, 0.4);
        st(hl, { display: 'block', left: `${f2(v.left - 8)}px`, top: `${f2(v.top - 6)}px`, width: `${f2(v.width + 16)}px`, height: `${f2(v.height + 12)}px`,
          clipPath: p >= 1 ? 'none' : `inset(0 ${f2((1 - p) * 100)}% 0 0)` });
      } else st(hl, { display: 'none' });
      // cursor: to the send button
      const sb = frameRect(send);
      const c = cursorAt([{ t: 23.2, x: 1500, y: 1150 }, { t: 23.76, x: sb.left + sb.width * 0.5, y: sb.top + sb.height * 0.55 }, { t: 24.1, x: sb.left + 40, y: sb.top + 260 }], [[23.8, 23.86]], t);
      if (c && t < 24.1) Object.assign(CUR, c, { on: true });
    };
  }

  // ================================================================ 5. END: intelligence on Kosovo
  function buildEnd() {
    const s = scene('end', 25.98, 30.01, 5);
    const A = D.ask_dom;
    const map = A.hero.match(/<svg class="kmap[\s\S]*?<\/svg>/)[0].replace('id="kdots"', 'id="kdots2"').replace('url(#kdots)', 'url(#kdots2)');
    const stars = A.hero.match(/<svg class="stars[\s\S]*?<\/svg>/)[0];
    s.el.innerHTML = `<div class="navy"><div class="smoke"></div><div class="vig"></div></div><div class="grain"></div>
      <div class="hudc"><i></i><i></i><i></i><i></i></div>
      <div class="end-map">${map}</div>
      <div class="end-copy">${stars}
        <div class="eyebrow-f">Open-source early warning</div>
        <div class="h"><span class="intel">Intelligence on</span><span class="roll"><span>Banjska</span><span>the Ibar canal</span><span>Jarinje</span><span>Kosovo.</span></span></div>
        <div class="meta"><div><span>Sources</span><b>108</b></div><div><span>Signals</span><b>33,257</b></div><div><span>Languages</span><b>SQ · SR · EN</b></div></div></div>
      <div class="lockup end-lock"><div class="wm">${'PARSE'.split('').map((c) => `<span>${c}</span>`).join('')}</div><div class="sub">Every step on the record.</div></div>
      <svg class="bigmark"><g class="bm">${LOGO.map((d, i) => `<path class="f${i + 1}" d="${d}" pathLength="1"/>`).join('')}</g></svg>
      <div class="readout"><span><b>/0.1</b> — Ask Parse</span><span><b>Prishtinë / Priština</b> · 42.6629° N · 21.1655° E</span><span>Sector KOS · Grid 34T</span></div>`;
    const smoke = $('.smoke', s.el), grain = $('.grain', s.el), hud = $$('.hudc i', s.el);
    const tline = document.createElement('div'); tline.className = 'sweep'; s.el.appendChild(tline);
    const em = $('.end-map', s.el), kmap = $('.kmap', em);
    st(em, { left: '1060px', top: '150px', width: '700px' });
    const land = $('.k-land', kmap), rivers = $$('.k-river', kmap), cities = $$('.k-cities rect, .k-cities text', kmap);
    const grid = $$('.k-grid > *, .k-nb text, .k-rl, .k-scale, .k-north', kmap);
    const hs = $$('.hs', kmap);
    [land, ...rivers].forEach((p) => p.setAttribute('pathLength', '1'));
    const copy = $('.end-copy', s.el), starsEl = $('.stars', copy), eb = $('.eyebrow-f', copy);
    const intelWords = split($('.intel', copy));
    const rollWs = $$('.roll > span', copy);
    const metaCells = $$('.meta > div', copy), metaBox = $('.meta', copy);
    const lock = $('.end-lock', s.el), letters = $$('.wm span', lock), sub = $('.sub', lock);
    const bm = $('.bm', s.el), paths = $$('path', bm);
    const readout = $('.readout', s.el), ro = split(readout);
    const HOT = ['#4f7dff', '#ff8a2a', '#4f7dff', '#d0a650'];
    const RW = [26.55, 27.15, 27.7, 28.25];          // word changes on the beat
    RW.forEach((t, i) => cue(t, i === 3 ? 'land' : 'roll', i));
    cue(28.95, 'brand'); cue(29.25, 'tail');
    let lockPos = null;

    s.seek = (t) => {
      const wp = T(t, 25.98, 0.55, ez.cam), edge = wp * 1920;
      st(s.el, { clipPath: wp >= 1 ? 'none' : `inset(0 ${f2(Math.max(0, 1920 - edge - 1))}px 0 0)` });
      st(tline, { left: `${f2(edge)}px`, opacity: wp > 0 && wp < 1 ? '1' : '0' });
      const d = t / 24;
      st(smoke, { transform: `translate3d(${f2(-3 * Math.sin(d * 3.1 + 1))}%, ${f2(2 * Math.sin(d * 2.3 + 2))}%, 0) scale(${(1.02 + 0.04 * Math.sin(d * 1.7)).toFixed(4)})` });
      const g = Math.floor(t * 30);
      st(grain, { transform: `translate(${(g * 37) % 64}px, ${(g * 53) % 64}px)` });
      hud.forEach((c, i) => { const p = T(t, 26.1 + i * 0.05, 0.6); st(c, { opacity: p.toFixed(3), transform: `scale(${(0.4 + 0.6 * p).toFixed(3)})` }); });
      roll(ro, t, 26.4, null, { stag: 0.04, dur: 0.6, y: 100, blur: 0, seed: 19 });

      // map: outline and rivers draw, the dot fill and labels come up, flashpoints ping in turn
      const mp = T(t, 26.25, 1.25, ez.io);
      st(land, { strokeDasharray: '1 1', strokeDashoffset: f2(1 - mp), fillOpacity: T(t, 26.9, 0.8).toFixed(3) });
      rivers.forEach((r, i) => st(r, { strokeDasharray: '1 1', strokeDashoffset: f2(1 - T(t, 26.7 + i * 0.15, 0.8, ez.io)) }));
      cities.forEach((c, i) => st(c, { opacity: T(t, 27.0 + (i % 7) * 0.05, 0.5).toFixed(3) }));
      grid.forEach((c) => st(c, { opacity: T(t, 26.3, 0.8).toFixed(3) }));
      const keysOrder = ['banjska', 'canal', 'jarinje', 'prishtina', 'mitrovica', 'gazimestan'];
      hs.forEach((h) => {
        const k = h.dataset.k, i = keysOrder.indexOf(k);
        const t0 = 26.55 + Math.max(0, i) * 0.55, p = T(t, t0, 0.4);
        st(h, { opacity: p.toFixed(3) });
        const active = (k === 'banjska' && t >= RW[0] && t < RW[1]) || (k === 'canal' && t >= RW[1] && t < RW[2]) || (k === 'jarinje' && t >= RW[2] && t < RW[3]) || t >= RW[3];
        cls(h, 'on', active);
        const ring = $('.ring', h);
        const ph = ((t - t0 + i * 0.3) % 2.2) / 2.2;
        const rp = bez(.2, .6, .3, 1)(clamp(ph / 0.8));
        st(ring, { transform: `scale(${(1 + 3.2 * rp).toFixed(3)})`, opacity: active && t > t0 ? (0.9 * (1 - rp)).toFixed(3) : '0', transformBox: 'fill-box', transformOrigin: 'center' });
      });
      st(em, { '--hot': HOT[Math.max(0, RW.filter((x) => t >= x).length - 1)] });

      // copy: stars, eyebrow, "Intelligence on" + the flashpoint word rolling to Kosovo
      const sp = T(t, 26.35, 0.6); st(starsEl, { opacity: sp.toFixed(3), transform: `translateY(${f2((1 - sp) * 12)}px)` });
      roll([eb], t, 26.4, 28.55, { y: 60, blur: 0, dur: 0.5 });
      st(eb, { '--rx': T(t, 26.45, 0.5).toFixed(3), '--rule': HOT[Math.max(0, RW.filter((x) => t >= x).length - 1)] });
      roll(intelWords, t, 26.45, 28.6, { stag: 0.06, dur: 0.66, seed: 23 });
      rollWs.forEach((w, i) => {
        // the next word starts a moment after the last one leaves, so the two never print over each other
        const tin = RW[i] + (i ? 0.12 : 0), tout = RW[i + 1] ?? 28.62;
        const pi = T(t, tin, 0.6, ez.roll), po = T(t, tout, 0.4, ez.in);
        const y = (1 - pi) * 70 - po * 70;
        st(w, { color: HOT[i], transform: `translateY(${f2(y)}%)`, opacity: (pi * (1 - po)).toFixed(3), filter: `blur(${f2(Math.max(1 - pi, po) * 8)}px)`,
          visibility: t >= tin - 0.01 && po < 1 ? 'visible' : 'hidden' });
      });
      const mOut = T(t, 28.6, 0.36, ez.in);
      metaCells.forEach((c, i) => { const p = T(t, 27.0 + i * 0.1, 0.55); st(c, { opacity: (p * (1 - mOut)).toFixed(3), transform: `translateY(${f2((1 - p) * 12 - mOut * 14)}px)` }); });
      st(metaBox, { borderColor: `rgba(255,255,255,${(0.2 * T(t, 26.95, 0.5) * (1 - mOut)).toFixed(3)})` });

      // the lockup takes the copy's place: mark draws, PARSE rises, the line closes the film
      if (!lockPos) {
        const k = 4.6, wmW = $('.wm', lock).getBoundingClientRect().width;
        lockPos = { k, mx: 150 - 3 * k, my: 470 - 12 * k, wx: 150 + 18 * k + 40 };
        st(lock, { left: `${f2(lockPos.wx)}px`, top: `${f2(470 - 59)}px` });
        void wmW;
      }
      const L = lockPos;
      st(bm, { transform: `translate(${f2(L.mx)}px, ${f2(L.my)}px) scale(${L.k})` });
      paths.forEach((p, i) => {
        const pr = T(t, 28.62 + i * 0.06, 0.55, ez.io);
        st(p, { strokeWidth: f2(2), strokeDasharray: '1 2', strokeDashoffset: f2(1 - pr), visibility: t >= 28.6 ? 'visible' : 'hidden' });
      });
      letters.forEach((l, i) => {
        const pi = T(t, 28.72 + i * 0.05, 0.62, ez.roll);
        st(l, { transform: `translateY(${f2((1 - pi) * 60)}%)`, opacity: pi.toFixed(3), filter: pi < 1 ? `blur(${f2((1 - pi) * 8)}px)` : 'none' });
      });
      const sp2 = T(t, 29.0, 0.6);
      st(sub, { opacity: sp2.toFixed(3), clipPath: `inset(0 ${f2((1 - sp2) * 100)}% 0 0)`, top: '150px', font: '300 54px/1.1 var(--sans)', letterSpacing: '-.03em', textTransform: 'none', color: '#fff' });
      // the stats come back under the lockup for the last hold
      const mp2 = T(t, 29.15, 0.5);
      if (t >= 28.95) {
        st(metaBox, { borderColor: `rgba(255,255,255,${(0.2 * mp2).toFixed(3)})`, transform: `translateY(${f2(214)}px)` });
        metaCells.forEach((c, i) => { const p = T(t, 29.15 + i * 0.08, 0.5); st(c, { opacity: p.toFixed(3), transform: `translateY(${f2((1 - p) * 12)}px)` }); });
      } else st(metaBox, { transform: 'none' });
    };
  }

  // ---------------------------------------------------------------- the frame
  function build() {
    document.body.insertAdjacentHTML('afterbegin', D.chrome_dom.sprite);
    buildOpen(); buildWatch(); buildTrace(); buildAsk(); buildEnd();
  }
  // measure every scene once with its screen untransformed, so camera keys are in layout coordinates
  function measureFirst() { SC.forEach((s) => st(s.el, { display: 'block' })); }

  window.seek = (t) => {
    t = clamp(t, 0, DUR - 1e-6);
    CUR.on = false;
    SC.forEach((s) => {
      const on = t >= s.t0 && t < s.t1;
      st(s.el, { display: on ? 'block' : 'none' });
      if (on) s.seek(t);
    });
    const c = $('#cursor');
    st(c, { display: CUR.on ? 'block' : 'none' });
    if (CUR.on) st(c, { transform: `translate(${f2(CUR.x - 4)}px, ${f2(CUR.y - 3)}px) scale(${(1 - 0.14 * CUR.press).toFixed(3)})` });
    if (window.__debug) text(window.__debug, t.toFixed(3));
  };

  async function fontsReady() {
    const faces = ['300 40px "Inter Tight"', '400 40px "Inter Tight"', '500 40px "Inter Tight"', '600 40px "Inter Tight"',
      '400 20px "IBM Plex Mono"', '500 20px "IBM Plex Mono"', '600 20px "IBM Plex Mono"'];
    const sample = 'Aa ëçčćšžđ Снажна експлозија 0123';
    await Promise.all(faces.map((f) => document.fonts.load(f, sample)));
    await document.fonts.ready;
  }

  // a frame rendered without its stylesheets or fonts is worse than no frame: refuse to start
  function assertAssets() {
    const local = [...document.querySelectorAll('link[rel=stylesheet]')].filter((l) => l.href.startsWith(location.origin));
    const bad = local.filter((l) => { try { return !l.sheet || !l.sheet.cssRules.length; } catch (e) { return true; } });
    if (bad.length) throw new Error(`stylesheets not loaded: ${bad.map((l) => l.getAttribute('href')).join(', ')}`);
    const faces = ['300 40px "Inter Tight"', '600 40px "Inter Tight"', '500 20px "IBM Plex Mono"'];
    const missing = faces.filter((f) => !document.fonts.check(f, 'Aa'));
    if (missing.length) throw new Error(`fonts not loaded: ${missing.join(', ')}`);
  }

  window.FILM = { FPS, DUR, CUES };
  window.ready = (async () => {
    await fontsReady();
    assertAssets();
    await load();
    measureFirst();
    build();
    // second pass: fonts for injected text
    await document.fonts.ready;
    window.seek(0);
    if (/debug/.test(location.search)) {
      window.__debug = document.createElement('div');
      window.__debug.style.cssText = 'position:absolute;right:12px;top:60px;z-index:99;font:600 22px var(--mono);color:#0f0;background:#000a;padding:4px 8px';
      $('#frame').appendChild(window.__debug);
    }
    return { fps: FPS, duration: DUR, cues: CUES.length };
  })();
})();
