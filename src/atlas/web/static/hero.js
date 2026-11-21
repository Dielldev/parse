// Ask hero: every few seconds pick a random flashpoint and a random accent (Kosovo blue or orange).
// The headline word, the map marker and the readout tag all switch together.
(() => {
  const hero = document.querySelector('.hero'), roll = document.getElementById('roll');
  if (!hero || !roll) return;
  const WORDS = [
    ['Banjska', 'banjska'], ['North Mitrovica', 'mitrovica'], ['the Ibar canal', 'canal'],
    ['Jarinje', 'jarinje'], ['Gazimestan', 'gazimestan'], ['Prishtina', 'prishtina'],
  ];
  const COLORS = ['var(--hot-blue)', 'var(--hot-orange)'];
  const tag = document.getElementById('hot-name');
  const marks = [...document.querySelectorAll('.hero .kmap .hs')];
  const still = matchMedia('(prefers-reduced-motion: reduce)').matches;
  const pick = (n, not) => { let i; do { i = Math.floor(Math.random() * n); } while (n > 1 && i === not); return i; };
  let cur = -1;

  function show(i, color, first) {
    const [word, key] = WORDS[i];
    hero.style.setProperty('--hot', color);
    const old = roll.querySelector('.roll-w:not(.out)');
    if (old && !still) { old.classList.remove('in'); old.classList.add('out'); setTimeout(() => old.remove(), 520); } else if (old) old.remove();
    const el = document.createElement('span');
    el.className = 'roll-w' + (first || still ? '' : ' in');
    el.style.setProperty('--c', color);
    el.textContent = word;
    roll.appendChild(el);
    marks.forEach(m => m.classList.toggle('on', m.dataset.k === key));
    if (tag) tag.textContent = (marks.find(m => m.dataset.k === key)?.querySelector('.hn')?.textContent) || word;
    cur = i;
  }

  show(pick(WORDS.length, -1), COLORS[Math.floor(Math.random() * COLORS.length)], true);
  setInterval(() => {
    if (document.hidden || document.body.classList.contains('threaded')) return;
    show(pick(WORDS.length, cur), COLORS[Math.floor(Math.random() * COLORS.length)]);
  }, 3200);
  // Hovering a marker previews it; the cycle carries on afterwards.
  marks.forEach(m => m.addEventListener('mouseenter', () => {
    const i = WORDS.findIndex(w => w[1] === m.dataset.k);
    if (i >= 0 && i !== cur) show(i, getComputedStyle(hero).getPropertyValue('--hot').trim() || COLORS[0]);
  }));
})();
