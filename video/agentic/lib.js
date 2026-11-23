/* Motion helpers for the agentic-loop film. Every function is a pure function of time t: the film never runs timers,
   CSS animations or carried state, so window.seek(t) can jump anywhere and render the same frame every time. */
(() => {
  'use strict';
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
      let lo = 0, hi = 1; s = x;
      for (let i = 0; i < 40; i++) { if (X(s) < x) lo = s; else hi = s; s = (lo + hi) / 2; }
      return Y(s);
    };
  }
  const ez = {
    out: bez(0.16, 1, 0.3, 1),      // long exponential settle, no overshoot
    roll: bez(0.2, 0.7, 0.2, 1),    // the product's word roll
    io: bez(0.65, 0, 0.35, 1),      // symmetric, for things that travel
    cam: bez(0.55, 0, 0.1, 1),      // camera: firm start, long settle
    in: bez(0.6, 0, 0.8, 0.4),      // exits
    snap: bez(0.3, 0, 0, 1),        // quick departure, hard settle
    lin: (x) => x,
  };
  const T = (t, t0, d, e = ez.out) => e(P(t, t0, d));
  // closed-form critically-damped-ish spring step (tiny overshoot at most): 0 -> 1 from t0
  function spring(t, t0, k = 14, z = 0.86) {
    if (t <= t0) return 0;
    const x = t - t0, w = k, wd = w * Math.sqrt(1 - z * z);
    return 1 - Math.exp(-z * w * x) * (Math.cos(wd * x) + (z * w / wd) * Math.sin(wd * x));
  }
  function rng(a) {
    return () => {
      a |= 0; a = (a + 0x6D2B79F5) | 0;
      let r = Math.imul(a ^ (a >>> 15), 1 | a);
      r = (r + Math.imul(r ^ (r >>> 7), 61 | r)) ^ r;
      return ((r ^ (r >>> 14)) >>> 0) / 4294967296;
    };
  }
  // monotone cubic (Fritsch–Carlson) through [x, y] keys: used for the footage speed ramp
  function monoCubic(keys) {
    const xs = keys.map((k) => k[0]), ys = keys.map((k) => k[1]), n = keys.length;
    const d = []; for (let i = 0; i < n - 1; i++) d.push((ys[i + 1] - ys[i]) / (xs[i + 1] - xs[i]));
    const m = [d[0]];
    for (let i = 1; i < n - 1; i++) m.push(d[i - 1] * d[i] <= 0 ? 0 : 3 * (d[i - 1] + d[i]) / ((2 * d[i] + d[i - 1]) / d[i - 1] + (d[i] + 2 * d[i - 1]) / d[i]));
    m.push(d[n - 2]);
    const f = (x) => {
      if (x <= xs[0]) return ys[0];
      if (x >= xs[n - 1]) return ys[n - 1];
      let i = 0; while (i < n - 2 && x >= xs[i + 1]) i++;
      const h = xs[i + 1] - xs[i], s = (x - xs[i]) / h;
      const h00 = 2 * s ** 3 - 3 * s ** 2 + 1, h10 = s ** 3 - 2 * s ** 2 + s, h01 = -2 * s ** 3 + 3 * s ** 2, h11 = s ** 3 - s ** 2;
      return h00 * ys[i] + h10 * h * m[i] + h01 * ys[i + 1] + h11 * h * m[i + 1];
    };
    f.slope = (x) => (f(x + 0.004) - f(x - 0.004)) / 0.008;
    return f;
  }

  // ---------------------------------------------------------------- DOM
  const $ = (s, el = document) => el.querySelector(s);
  const $$ = (s, el = document) => [...el.querySelectorAll(s)];
  const esc = (v) => String(v ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  const f2 = (v) => (Math.abs(v) < 0.005 ? '0' : v.toFixed(2));
  function st(el, o) {
    if (!el) return;
    const c = el._s || (el._s = {});
    for (const k in o) {
      const v = o[k];
      if (c[k] === v) continue;
      c[k] = v;
      if (k.startsWith('--')) el.style.setProperty(k, v);
      else el.style[k] = v;
    }
  }
  const cls = (el, name, on) => { if (el && el.classList.contains(name) !== !!on) el.classList.toggle(name, !!on); };
  const text = (el, v) => { if (el && el.textContent !== v) el.textContent = v; };
  const html = (el, v) => { if (el && el._h !== v) { el._h = v; el.innerHTML = v; } };
  const attr = (el, k, v) => { v = String(v); if (el && el.getAttribute(k) !== v) el.setAttribute(k, v); };
  const show = (el, on) => st(el, { visibility: on ? 'visible' : 'hidden' });
  const fmt = (n) => Math.round(n).toLocaleString('en-US');
  const mk = (tag, cl, h, parent) => { const e = document.createElement(tag); if (cl) e.className = cl; if (h != null) e.innerHTML = h; if (parent) parent.appendChild(e); return e; };
  const svgEl = (tag, a = {}, parent) => { const e = document.createElementNS('http://www.w3.org/2000/svg', tag); for (const k in a) e.setAttribute(k, a[k]); if (parent) parent.appendChild(e); return e; };

  // split an element's text into word spans for the roll (keeps nested markup like <em>)
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
  // words rise into place (translate + blur), optionally leave upwards
  function roll(ws, t, tin, tout = null, o = {}) {
    const { stag = 0.05, dur = 0.66, y = 74, blur = 8, seed = 1, ostag = 0.02, odur = 0.34 } = o;
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
  // reveal by moving a clip edge: down = top-to-bottom reveal
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
  // number roll for counters: integer that eases from a to b
  const countTo = (t, t0, d, a, b, e = ez.out) => a + (b - a) * T(t, t0, d, e);
  // decode a ULID's timestamp (first 10 chars, Crockford base32) → Date
  function ulidTime(id) {
    const A = '0123456789ABCDEFGHJKMNPQRSTVWXYZ';
    const s = id.replace(/^[a-z]+_/, '').slice(0, 10);
    let ms = 0; for (const ch of s) ms = ms * 32 + A.indexOf(ch);
    return new Date(ms);
  }

  window.L = { clamp, lerp, P, bez, ez, T, spring, rng, monoCubic, $, $$, esc, f2, st, cls, text, html, attr, show, fmt, mk, svgEl,
    split, roll, clipIn, rise, countTo, ulidTime };
})();
