/* Soundtrack for "Parse · the agentic loop", synthesised in code with an OfflineAudioContext (48 kHz stereo, 30 s).
   120 BPM in D minor. The instruments are the first film's; the arrangement follows this film's sections, and every UI
   sound (a keystroke, a post the scout matched, an agent's request, a kept item, a label, the P1, each workflow step)
   comes from the same cue list as the picture (window.FILM.CUES), so sound and picture cannot drift.
   Deterministic: seeded noise, no Math.random. window.renderAudio() keeps a 16-bit WAV as base64 in window.__wav. */
(() => {
  'use strict';
  const SR = 48000, DUR = 30, BEAT = 0.5, BAR = 2;
  const mtof = (m) => 440 * Math.pow(2, (m - 69) / 12);
  const NOTE = { D2: 38, F2: 41, G2: 43, A2: 45, Bb2: 46, C3: 48, D3: 50, E3: 52, F3: 53, G3: 55, A3: 57, Bb3: 58, C4: 60, Cs4: 61, D4: 62,
    E4: 64, F4: 65, G4: 67, A4: 69, Bb4: 70, C5: 72, D5: 74, E5: 76, F5: 77, G5: 79, A5: 81, C6: 84, D6: 86, E6: 88, F6: 89, G6: 91, A6: 93 };
  const f = (n) => { if (!(n in NOTE)) throw new Error(`audio.js: unknown note ${n}`); return mtof(NOTE[n]); };
  function rng(a) { return () => { a |= 0; a = (a + 0x6D2B79F5) | 0; let r = Math.imul(a ^ (a >>> 15), 1 | a); r = (r + Math.imul(r ^ (r >>> 7), 61 | r)) ^ r; return ((r ^ (r >>> 14)) >>> 0) / 4294967296; }; }

  window.renderAudio = async () => {
    await window.ready;
    const CUES = window.FILM.CUES;
    const ctx = new OfflineAudioContext(2, SR * DUR, SR);
    const R = rng(7);

    // ------------------------------------------------------------ busses
    const out = ctx.createGain(); out.gain.value = 0.9;
    const comp = ctx.createDynamicsCompressor();
    comp.threshold.value = -18; comp.knee.value = 12; comp.ratio.value = 3; comp.attack.value = 0.005; comp.release.value = 0.18;
    out.connect(comp).connect(ctx.destination);
    // a long, dark room: decaying stereo noise impulse
    const ir = ctx.createBuffer(2, SR * 2.8, SR);
    for (let c = 0; c < 2; c++) { const d = ir.getChannelData(c); for (let i = 0; i < d.length; i++) d[i] = (R() * 2 - 1) * Math.pow(1 - i / d.length, 3.2); }
    const verb = ctx.createConvolver(); verb.buffer = ir;
    const verbLp = ctx.createBiquadFilter(); verbLp.type = 'lowpass'; verbLp.frequency.value = 5200;
    const verbOut = ctx.createGain(); verbOut.gain.value = 0.34;
    verb.connect(verbLp).connect(verbOut).connect(out);
    const bus = (g, send = 0) => { const n = ctx.createGain(); n.gain.value = g; n.connect(out); if (send) { const s = ctx.createGain(); s.gain.value = send; n.connect(s).connect(verb); } return n; };
    const padBus = bus(0.24, 0.55), bassBus = bus(0.5), drumBus = bus(0.62, 0.06), uiBus = bus(0.5, 0.22), fxBus = bus(0.42, 0.35);
    // the end: everything rides down over the last half second

    const noise = ctx.createBuffer(1, SR * 2, SR);
    { const d = noise.getChannelData(0); for (let i = 0; i < d.length; i++) d[i] = R() * 2 - 1; }
    const noiseSrc = (t, dur) => { const s = ctx.createBufferSource(); s.buffer = noise; s.loop = true; s.start(t, R() * 1.5); s.stop(t + dur + 0.05); return s; };
    const gainEnv = (t, a, d, peak) => { const g = ctx.createGain(); g.gain.setValueAtTime(0.0001, t); g.gain.linearRampToValueAtTime(peak, t + a); g.gain.exponentialRampToValueAtTime(0.0001, t + a + d); return g; };
    const pan = (v) => { const p = ctx.createStereoPanner(); p.pan.value = v; return p; };

    // ------------------------------------------------------------ instruments
    function kick(t, v = 1) {
      const o = ctx.createOscillator(); o.frequency.setValueAtTime(140, t); o.frequency.exponentialRampToValueAtTime(46, t + 0.11);
      const g = gainEnv(t, 0.003, 0.38, 0.9 * v);
      o.connect(g).connect(drumBus); o.start(t); o.stop(t + 0.5);
      const n = noiseSrc(t, 0.01), hp = ctx.createBiquadFilter(); hp.type = 'highpass'; hp.frequency.value = 3000;
      n.connect(hp).connect(gainEnv(t, 0.001, 0.012, 0.12 * v)).connect(drumBus);
    }
    function hat(t, v = 1, open = false) {
      const n = noiseSrc(t, open ? 0.22 : 0.06), hp = ctx.createBiquadFilter(); hp.type = 'highpass'; hp.frequency.value = 7800;
      n.connect(hp).connect(gainEnv(t, 0.002, open ? 0.2 : 0.045, 0.16 * v)).connect(pan(0.18)).connect(drumBus);
    }
    function clap(t, v = 1) {
      const n = noiseSrc(t, 0.2), bp = ctx.createBiquadFilter(); bp.type = 'bandpass'; bp.frequency.value = 1350; bp.Q.value = 0.9;
      const g = ctx.createGain(); g.gain.setValueAtTime(0.0001, t);
      [0, 0.011, 0.022].forEach((o) => { g.gain.linearRampToValueAtTime(0.32 * v, t + o + 0.001); g.gain.exponentialRampToValueAtTime(0.05 * v, t + o + 0.009); });
      g.gain.exponentialRampToValueAtTime(0.0001, t + 0.19);
      const s = ctx.createGain(); s.gain.value = 0.5;
      n.connect(bp).connect(g).connect(drumBus); g.connect(s).connect(verb);
    }
    function bass(t, note, dur, v = 1) {
      const o = ctx.createOscillator(); o.type = 'sawtooth'; o.frequency.value = f(note);
      const sub = ctx.createOscillator(); sub.type = 'sine'; sub.frequency.value = f(note);
      const lp = ctx.createBiquadFilter(); lp.type = 'lowpass'; lp.Q.value = 2;
      lp.frequency.setValueAtTime(620, t); lp.frequency.exponentialRampToValueAtTime(140, t + Math.min(0.22, dur));
      const g = ctx.createGain(); g.gain.setValueAtTime(0.0001, t); g.gain.linearRampToValueAtTime(0.36 * v, t + 0.006);
      g.gain.exponentialRampToValueAtTime(0.12 * v, t + 0.16); g.gain.exponentialRampToValueAtTime(0.0001, t + dur);
      const sg = ctx.createGain(); sg.gain.value = 0.7;
      o.connect(lp).connect(g); sub.connect(sg).connect(g); g.connect(bassBus);
      o.start(t); sub.start(t); o.stop(t + dur + 0.02); sub.stop(t + dur + 0.02);
    }
    function pad(t0, t1, notes, v = 1, bright = 1) {
      notes.forEach((n, k) => [-7, 6].forEach((cents, j) => {
        const o = ctx.createOscillator(); o.type = 'sawtooth'; o.frequency.value = f(n); o.detune.value = cents + (k - 1) * 2;
        const lp = ctx.createBiquadFilter(); lp.type = 'lowpass'; lp.Q.value = 0.6;
        lp.frequency.setValueAtTime(500 * bright, t0); lp.frequency.linearRampToValueAtTime(1300 * bright, t0 + (t1 - t0) * 0.6); lp.frequency.linearRampToValueAtTime(700 * bright, t1);
        const g = ctx.createGain(); g.gain.setValueAtTime(0.0001, t0); g.gain.linearRampToValueAtTime(0.07 * v, t0 + 0.5);
        g.gain.setValueAtTime(0.07 * v, Math.max(t0 + 0.5, t1 - 0.4)); g.gain.linearRampToValueAtTime(0.0001, t1 + 0.35);
        o.connect(lp).connect(g).connect(pan(j ? 0.35 : -0.35)).connect(padBus); o.start(t0); o.stop(t1 + 0.4);
      }));
    }
    function pluck(t, note, v = 1, p = 0) {
      const o = ctx.createOscillator(); o.type = 'triangle'; o.frequency.value = typeof note === 'number' ? note : f(note);
      const o2 = ctx.createOscillator(); o2.type = 'sawtooth'; o2.frequency.value = o.frequency.value * 2.001;
      const lp = ctx.createBiquadFilter(); lp.type = 'lowpass'; lp.frequency.setValueAtTime(4200, t); lp.frequency.exponentialRampToValueAtTime(380, t + 0.3);
      const g = gainEnv(t, 0.003, 0.42, 0.22 * v), g2 = ctx.createGain(); g2.gain.value = 0.25;
      o.connect(lp); o2.connect(g2).connect(lp); lp.connect(g).connect(pan(p)).connect(uiBus);
      o.start(t); o2.start(t); o.stop(t + 0.5); o2.stop(t + 0.5);
    }
    function blip(t, hz, v = 1, dur = 0.07, p = 0) {
      const o = ctx.createOscillator(); o.type = 'sine'; o.frequency.value = hz;
      o.connect(gainEnv(t, 0.002, dur, 0.16 * v)).connect(pan(p)).connect(uiBus); o.start(t); o.stop(t + dur + 0.05);
    }
    function tick(t, v = 1, hz = 2600, p = 0) {
      const n = noiseSrc(t, 0.012), bp = ctx.createBiquadFilter(); bp.type = 'bandpass'; bp.frequency.value = hz; bp.Q.value = 3;
      n.connect(bp).connect(gainEnv(t, 0.0008, 0.016, 0.34 * v)).connect(pan(p)).connect(uiBus);
    }
    function click(t, v = 1) {
      tick(t, 1.1 * v, 3200);
      const o = ctx.createOscillator(); o.type = 'sine'; o.frequency.setValueAtTime(1900, t); o.frequency.exponentialRampToValueAtTime(900, t + 0.03);
      o.connect(gainEnv(t, 0.001, 0.04, 0.08 * v)).connect(uiBus); o.start(t); o.stop(t + 0.08);
    }
    function key(t, v = 1) { tick(t, 0.55 * v, 4200 + R() * 1400, -0.1 + R() * 0.2); }
    function whoosh(t, v = 1, up = false, dur = 0.42) {
      const n = noiseSrc(t, dur), bp = ctx.createBiquadFilter(); bp.type = 'bandpass'; bp.Q.value = 1.1;
      bp.frequency.setValueAtTime(up ? 500 : 3600, t); bp.frequency.exponentialRampToValueAtTime(up ? 4200 : 420, t + dur);
      const g = ctx.createGain(); g.gain.setValueAtTime(0.0001, t); g.gain.linearRampToValueAtTime(0.3 * v, t + dur * 0.45); g.gain.exponentialRampToValueAtTime(0.0001, t + dur);
      const p = ctx.createStereoPanner(); p.pan.setValueAtTime(-0.5, t); p.pan.linearRampToValueAtTime(0.5, t + dur);
      n.connect(bp).connect(g).connect(p).connect(fxBus);
    }
    function riser(t, dur, v = 1) {
      const n = noiseSrc(t, dur), bp = ctx.createBiquadFilter(); bp.type = 'bandpass'; bp.Q.value = 1.6;
      bp.frequency.setValueAtTime(300, t); bp.frequency.exponentialRampToValueAtTime(5200, t + dur);
      const g = ctx.createGain(); g.gain.setValueAtTime(0.0001, t); g.gain.exponentialRampToValueAtTime(0.32 * v, t + dur); g.gain.linearRampToValueAtTime(0.0001, t + dur + 0.02);
      n.connect(bp).connect(g).connect(fxBus);
      const o = ctx.createOscillator(); o.type = 'sine'; o.frequency.setValueAtTime(220, t); o.frequency.exponentialRampToValueAtTime(880, t + dur);
      const og = ctx.createGain(); og.gain.setValueAtTime(0.0001, t); og.gain.exponentialRampToValueAtTime(0.05 * v, t + dur); og.gain.linearRampToValueAtTime(0.0001, t + dur + 0.02);
      o.connect(og).connect(fxBus); o.start(t); o.stop(t + dur + 0.05);
    }
    function sub(t, v = 1, hz = 55, dur = 1.1) {
      const o = ctx.createOscillator(); o.type = 'sine'; o.frequency.setValueAtTime(hz * 1.9, t); o.frequency.exponentialRampToValueAtTime(hz, t + 0.07);
      o.connect(gainEnv(t, 0.004, dur, 0.75 * v)).connect(bassBus); o.start(t); o.stop(t + dur + 0.1);
    }
    function stab(t, notes, v = 1, dur = 0.5) {
      notes.forEach((n, i) => {
        const o = ctx.createOscillator(); o.type = 'sawtooth'; o.frequency.value = f(n); o.detune.value = (i - 1) * 4;
        const lp = ctx.createBiquadFilter(); lp.type = 'lowpass'; lp.frequency.setValueAtTime(3200, t); lp.frequency.exponentialRampToValueAtTime(600, t + dur);
        o.connect(lp).connect(gainEnv(t, 0.004, dur, 0.06 * v)).connect(fxBus); o.start(t); o.stop(t + dur + 0.05);
      });
    }
    function alarm(t, v = 1) {
      [0, 0.12, 0.24].forEach((o, i) => {
        const s = ctx.createOscillator(); s.type = 'square'; s.frequency.value = i % 2 ? f('F5') : f('A5');
        const lp = ctx.createBiquadFilter(); lp.type = 'lowpass'; lp.frequency.value = 2600;
        s.connect(lp).connect(gainEnv(t + o, 0.003, 0.09, 0.055 * v)).connect(uiBus); s.start(t + o); s.stop(t + o + 0.12);
      });
    }
    function ping(t, v = 1) {
      [[f('A5'), 0.16], [f('E5') * 2, 0.06], [f('D6'), 0.05]].forEach(([hz, a]) => {
        const o = ctx.createOscillator(); o.type = 'sine'; o.frequency.value = hz;
        const g = ctx.createGain(); g.gain.setValueAtTime(0.0001, t); g.gain.linearRampToValueAtTime(a * v, t + 0.004); g.gain.exponentialRampToValueAtTime(0.0001, t + 1.6);
        const s = ctx.createGain(); s.gain.value = 0.6;
        o.connect(g).connect(uiBus); g.connect(s).connect(verb); o.start(t); o.stop(t + 1.7);
      });
    }

    // ------------------------------------------------------------ the bed: one chord per bar
    const CH = { Dm: ['D3', 'F3', 'A3', 'E4'], Bb: ['Bb2', 'D3', 'F3', 'C4'], F: ['F2', 'C3', 'A3', 'E4'], C: ['C3', 'G3', 'E4', 'D4'],
      Gm: ['G2', 'D3', 'Bb3', 'F4'], A: ['A2', 'E3', 'Cs4', 'G4'], Dm9: ['D3', 'A3', 'E4', 'F4'] };
    const ROOT = { Dm: 'D2', Bb: 'Bb2', F: 'F2', C: 'C3', Gm: 'G2', A: 'A2', Dm9: 'D2' };
    //            hook  scout       field agents  signals                        ask                          end
    const prog = ['Dm', 'Dm', 'Bb', 'F', 'C', 'Dm', 'Bb', 'Gm', 'A', 'Dm', 'Bb', 'F', 'C', 'Dm', 'Dm9'];
    prog.forEach((c, b) => {
      const t0 = b * BAR, t1 = t0 + BAR;
      pad(t0, t1, CH[c], b === 0 ? 0.7 : b >= 13 ? 1 : 0.9, b === 0 ? 0.6 : b === 8 ? 1.25 : 1);
      if (b >= 1 && b <= 4) for (let k = 0; k < 8; k++) bass(t0 + k * BEAT / 2, ROOT[c], 0.2, k % 2 ? 0.5 : 0.85);          // agents: eighths
      if (b >= 5 && b <= 7) { bass(t0, ROOT[c], 0.9, 0.85); bass(t0 + 1.0, ROOT[c], 0.7, 0.6); bass(t0 + 1.5, ROOT[c], 0.4, 0.45); }  // signals: half-time
      if (b === 8) bass(t0, ROOT[c], 1.9, 1);
      if (b >= 10 && b <= 13) for (let k = 0; k < 8; k++) bass(t0 + k * BEAT / 2, ROOT[c], 0.2, k % 2 ? 0.5 : 0.8);          // ask
      if (b === 14) bass(t0, ROOT[c], 1.95, 0.9);
    });
    // hook: a clock in the dark
    for (let t = 0.0; t < 2.0; t += BEAT / 2) tick(t, 0.3, 5200, 0.25);
    // scout + field agents (2-10 s): four on the floor, hats open up when the fleet appears
    for (let t = 2.0; t < 10.0; t += BEAT) kick(t, t < 6 ? 0.7 : 0.85);
    for (let t = 2.25; t < 10.0; t += BEAT) hat(t, t < 6 ? 0.6 : 0.85, Math.round(t / BEAT) % 8 === 7);
    for (let t = 6.5; t < 10.0; t += 2 * BEAT) clap(t, 0.7);
    for (let t = 6.0; t < 9.75; t += BEAT / 4) hat(t + BEAT / 8, 0.22);
    // signals (10-16 s): half-time, room to think
    for (let t = 10.0; t < 16.0; t += 2 * BEAT) kick(t, 0.75);
    for (let t = 11.0; t < 16.0; t += BAR) clap(t, 0.65);
    for (let t = 10.25; t < 15.75; t += BEAT) hat(t, 0.45);
    riser(15.0, 1.0, 0.9);                                   // into the P1 on the bar-8 downbeat
    // alert bar (16-18 s): the hit, a breath, then the build into ask
    for (let t = 16.5; t < 18.0; t += BEAT) kick(t, 0.6 + (t - 16.5) * 0.2);
    for (let t = 17.0; t < 18.0; t += BEAT / 4) hat(t, 0.3 + (t - 17) * 0.3);
    // ask (18-28 s): typing over hats, then the groove carries the eleven steps, lighter under the answer
    for (let t = 18.0; t < 20.0; t += BEAT / 2) hat(t + BEAT / 4, 0.35);
    for (let t = 20.0; t < 25.0; t += BEAT) { kick(t, 0.85); hat(t + BEAT / 2, 0.8, Math.round(t / BEAT) % 8 === 7); }
    for (let t = 20.5; t < 25.0; t += 2 * BEAT) clap(t, 0.7);
    for (let t = 25.0; t < 28.0; t += BEAT) { kick(t, 0.55); hat(t + BEAT / 2, 0.5); }
    riser(27.0, 1.0, 0.8);

    // ------------------------------------------------------------ the picture's own events
    const scale = ['D5', 'E5', 'F5', 'G5', 'A5', 'C6', 'D6', 'E6', 'F6', 'G6', 'A6'];
    CUES.forEach(({ t, kind, v }) => {
      switch (kind) {
        case 'drone': sub(t + 0.02, 0.5, 49, 1.8); break;
        case 'wordlow': sub(t, 0.55, 55, 0.9); tick(t, 0.5, 1800); break;
        case 'agents': kick(t, 0.9); sub(t, 0.8, 58, 1.0); pluck(t, 'D5', 1.1, 0.1); pluck(t + 0.004, 'A5', 0.6, -0.1); break;
        case 'fly': whoosh(t - 0.05, 0.6, false, 0.38); break;
        case 'open': stab(t, ['D4', 'A4', 'E5', 'F5'], 0.9, 0.7); whoosh(t - 0.1, 0.5, true, 0.34); break;
        case 'key': key(t, 0.9); break;
        case 'read': tick(t, 0.28, 4200, 0.2); break;
        case 'match': tick(t, 0.5, 3000, 0.25); blip(t, f(scale[v % 5]), 0.25, 0.04, 0.3); break;
        case 'kept': blip(t, f(scale[(v * 3) % 7]), 0.6, 0.07, 0.35); tick(t, 0.6, 2400, 0.3); break;
        case 'step': click(t, 0.5); break;
        case 'pull': whoosh(t, 0.75, false, 0.5); sub(t + 0.3, 0.4, 55, 0.7); break;
        case 'get': tick(t, 0.22, 5600 + (v % 5) * 300, -0.6 + (v % 7) * 0.2); break;
        case 'got': blip(t, f(scale[(v * 5) % 9]), 0.45, 0.06, -0.5 + (v % 5) * 0.25); break;
        case 'err': blip(t, 180, 0.35, 0.09, 0); break;
        case 'done': tick(t, 0.14, 3800, -0.3 + (v % 6) * 0.12); break;
        case 'tilt': whoosh(t - 0.05, 0.8, false, 0.55); break;
        case 'row': tick(t, 0.55, 2200, -0.3); break;
        case 'flag': pluck(t, scale[(v * 2) % 6], 0.7, 0.35); tick(t, 0.5, 1800, 0.35); break;
        case 'pass': blip(t, 220, 0.3, 0.06, 0.35); break;
        case 'merge': whoosh(t - 0.05, 0.6, true, 0.42); sub(t + 0.3, 0.45, 55, 0.8); break;
        case 'fac': pluck(t, ['D5', 'F5', 'A5', 'C6', 'D6', 'F6'][v] || 'D5', 0.6, -0.2 + v * 0.08); break;
        case 'trip': alarm(t, 0.9); break;
        case 'alert': sub(t, 1, 46, 1.6); kick(t, 1); stab(t, ['A3', 'E4', 'Cs4', 'G4'], 1.2, 1.0); ping(t + 0.2, 0.9); break;
        case 'pan': whoosh(t - 0.05, 0.75, false, 0.6); break;
        case 'chip': blip(t, f('A5'), 0.5, 0.08, 0); tick(t, 0.6, 2800); break;
        case 'click': click(t, 1.1); break;
        case 'whoosh': whoosh(t, 0.5, true, 0.4); break;
        case 'agentrun': riser(t, 0.95, 0.45); break;
        case 'node': pluck(t, scale[v % scale.length], 0.75, -0.4 + (v % 5) * 0.2); tick(t, 0.4, 2600); break;
        case 'agentsdone': pluck(t, 'A5', 0.9, 0); blip(t + 0.03, f('D6'), 0.4, 0.06, 0.2); break;
        case 'ai': pluck(t, 'D6', 0.9, 0.2); blip(t + 0.05, f('A6'), 0.35, 0.08, 0.3); break;
        case 'reveal': whoosh(t - 0.05, 0.7, false, 0.62); break;
        case 'page': whoosh(t - 0.04, 0.45, false, 0.34); tick(t + 0.2, 0.5, 2000); break;
        case 'answer': stab(t, ['D4', 'F4', 'A4', 'E5'], 1, 0.9); sub(t, 0.6, 55, 1.2); break;
        case 'cite': tick(t, 0.5, 2400 + v * 90, -0.4 + v * 0.11); break;
        case 'end': sub(t, 1, 46, 1.9); kick(t, 1); whoosh(t - 0.25, 0.6, true, 0.3); break;
        case 'brand': stab(t, ['D4', 'A4', 'E5', 'F5'], 1.2, 1.4); ping(t + 0.1, 0.7); break;
        default: break;
      }
    });
    // the end: everything rides down over the last 0.6 s
    out.gain.setValueAtTime(0.9, 29.35); out.gain.linearRampToValueAtTime(0.0001, 29.98);

    const buf = await ctx.startRendering();
    // 16-bit PCM WAV, base64
    const L = buf.getChannelData(0), Rch = buf.getChannelData(1), n = L.length;
    const bytes = new Uint8Array(44 + n * 4), dv = new DataView(bytes.buffer);
    const w = (o, s) => { for (let i = 0; i < s.length; i++) dv.setUint8(o + i, s.charCodeAt(i)); };
    w(0, 'RIFF'); dv.setUint32(4, 36 + n * 4, true); w(8, 'WAVE'); w(12, 'fmt '); dv.setUint32(16, 16, true); dv.setUint16(20, 1, true);
    dv.setUint16(22, 2, true); dv.setUint32(24, SR, true); dv.setUint32(28, SR * 4, true); dv.setUint16(32, 4, true); dv.setUint16(34, 16, true);
    w(36, 'data'); dv.setUint32(40, n * 4, true);
    let peak = 0;
    for (let i = 0; i < n; i++) {
      const a = Math.max(-1, Math.min(1, L[i])), b = Math.max(-1, Math.min(1, Rch[i]));
      peak = Math.max(peak, Math.abs(L[i]), Math.abs(Rch[i]));
      dv.setInt16(44 + i * 4, a * 32767, true); dv.setInt16(46 + i * 4, b * 32767, true);
    }
    let s = '';
    for (let i = 0; i < bytes.length; i += 0x8000) s += String.fromCharCode.apply(null, bytes.subarray(i, i + 0x8000));
    window.__wav = btoa(s);
    window.__peak = peak;
    return window.__wav.length;
  };
})();
