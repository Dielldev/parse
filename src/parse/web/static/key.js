// Bring-your-own-key for the public demo.
// The Featherless key lives only in this tab's sessionStorage. It is attached (as the X-Featherless-Key header) to
// the few same-origin requests that run a model, and to nothing else: not other API calls, not other origins.
(() => {
  const STORE = 'parse-fl-key';
  const SHAPE = /^[A-Za-z0-9._-]{16,200}$/;
  const MODEL_CALL = /^\/api\/(trace|key\/check|signals\/[^/]+\/model\/[a-z]+)$/;

  const read = () => { try { return sessionStorage.getItem(STORE) || ''; } catch (e) { return ''; } };
  const write = (v) => { try { v ? sessionStorage.setItem(STORE, v) : sessionStorage.removeItem(STORE); return true; } catch (e) { return false; } };

  window.parseKey = read;
  window.parseEngine = () => (read() ? 'qwen' : 'retrieval');   // trace.js reads this to describe what will run

  const nativeFetch = window.fetch.bind(window);
  window.fetch = (input, init) => {
    try {
      const key = read();
      const url = new URL(typeof input === 'string' || input instanceof URL ? input : input.url, location.href);
      if (key && url.origin === location.origin && MODEL_CALL.test(url.pathname)) {
        const headers = new Headers((init && init.headers) || (input instanceof Request ? input.headers : undefined));
        headers.set('X-Featherless-Key', key);
        init = Object.assign({}, init, {headers});
      }
    } catch (e) { /* fall through: send the request without a key */ }
    return nativeFetch(input, init);
  };

  document.addEventListener('DOMContentLoaded', () => {
    const input = document.getElementById('key-input'), save = document.getElementById('key-save'),
      clear = document.getElementById('key-clear'), msg = document.getElementById('key-msg'),
      dot = document.getElementById('key-dot'), label = document.getElementById('key-label');
    if (!input) return;
    const paint = () => {
      const has = !!read();
      dot.classList.toggle('on', has);
      label.textContent = has ? 'Key added' : 'Add your key';
      clear.hidden = !has;
      input.placeholder = has ? '•••••••••••• (saved for this tab)' : 'paste your Featherless key';
    };
    const say = (t, cls) => { msg.textContent = t; msg.className = 'key-msg ' + (cls || ''); };
    save.addEventListener('click', async () => {
      const v = input.value.trim();
      if (!SHAPE.test(v)) { say('That does not look like a Featherless key (16 to 200 letters, digits, . _ -).', 'err'); return; }
      if (!write(v)) { say('This browser blocks session storage, so the key cannot be kept.', 'err'); return; }
      input.value = '';
      say('Checking the key with one tiny request…');
      save.disabled = true;
      try {
        const r = await fetch('/api/key/check', {method: 'POST'});
        const d = await r.json().catch(() => ({}));
        if (!r.ok) { write(''); say(d.detail || `Check failed (${r.status}).`, 'err'); }
        else say('Key works. It stays in this tab only.', 'ok');
      } catch (e) { write(''); say('Could not reach the server.', 'err'); }
      save.disabled = false;
      paint();
    });
    clear.addEventListener('click', () => { write(''); input.value = ''; say('Key removed from this tab.', 'ok'); paint(); });
    input.addEventListener('keydown', (e) => { if (e.key === 'Enter') { e.preventDefault(); save.click(); } });
    paint();
  });
})();
