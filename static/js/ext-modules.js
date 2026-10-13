// Registration-deadline countdowns, wishlist toggles and the floating campus chatbot.
(function () {
  'use strict';
  var meta = document.querySelector('meta[name="csrf-token"]');
  var csrf = meta ? meta.getAttribute('content') : '';

  // ---- Countdown -------------------------------------------------------
  function pad(n) { return n < 10 ? '0' + n : String(n); }
  function tickCountdowns() {
    document.querySelectorAll('[data-deadline]').forEach(function (el) {
      var target = Date.parse(el.getAttribute('data-deadline'));
      if (isNaN(target)) return;
      var diff = target - Date.now();
      el.classList.remove('closed', 'safe');
      if (diff <= 0) { el.textContent = 'Registration closed'; el.classList.add('closed'); return; }
      var d = Math.floor(diff / 86400000), h = Math.floor(diff % 86400000 / 3600000),
          m = Math.floor(diff % 3600000 / 60000), s = Math.floor(diff % 60000 / 1000);
      el.textContent = (d > 0 ? d + 'd ' : '') + pad(h) + 'h ' + pad(m) + 'm ' + pad(s) + 's left to register';
      if (d >= 7) el.classList.add('safe');
    });
  }
  if (document.querySelector('[data-deadline]')) { tickCountdowns(); setInterval(tickCountdowns, 1000); }

  // ---- Confirm dialogs for destructive forms ---------------------------
  document.addEventListener('submit', function (e) {
    var msg = e.target && e.target.getAttribute && e.target.getAttribute('data-confirm');
    if (msg && !window.confirm(msg)) e.preventDefault();
  });

  // ---- Copy-to-clipboard buttons ---------------------------------------
  document.addEventListener('click', function (e) {
    var btn = e.target.closest && e.target.closest('[data-copy]');
    if (!btn || !navigator.clipboard) return;
    navigator.clipboard.writeText(btn.getAttribute('data-copy')).then(function () {
      var old = btn.textContent; btn.textContent = 'Copied!'; setTimeout(function () { btn.textContent = old; }, 1200);
    });
  });

  // ---- Floating chatbot -----------------------------------------------
  var root = document.getElementById('xm-chat');
  if (!root) return;
  var toggle = document.getElementById('xm-chat-toggle');
  var body = root.querySelector('.xm-chat-body');
  var form = root.querySelector('form');
  var input = form.querySelector('input');
  var suggestBox = root.querySelector('.xm-chat-suggest');
  var greeted = false;

  function add(text, who, links) {
    var div = document.createElement('div');
    div.className = 'xm-msg ' + who;
    div.textContent = text;              // text only — never HTML
    (links || []).forEach(function (l) {
      if (!l.url || l.url.charAt(0) !== '/') return;   // same-site links only
      var a = document.createElement('a');
      a.href = l.url; a.textContent = l.label;
      div.appendChild(a);
    });
    body.appendChild(div);
    body.scrollTop = body.scrollHeight;
    return div;
  }
  function suggestions(list) {
    suggestBox.textContent = '';
    (list || []).slice(0, 4).forEach(function (text) {
      var b = document.createElement('button');
      b.type = 'button'; b.textContent = text;
      b.addEventListener('click', function () { send(text); });
      suggestBox.appendChild(b);
    });
  }
  function send(text) {
    text = (text || '').trim();
    if (!text) return;
    add(text, 'me');
    input.value = '';
    var typing = add('…', 'bot');
    fetch(root.getAttribute('data-endpoint'), {
      method: 'POST', credentials: 'same-origin',
      headers: { 'Content-Type': 'application/json', 'X-CSRFToken': csrf, 'X-Requested-With': 'XMLHttpRequest' },
      body: JSON.stringify({ message: text })
    }).then(function (r) { return r.json(); }).then(function (data) {
      typing.remove();
      if (!data.success) { add(data.error || data.message || 'Something went wrong.', 'bot'); return; }
      var links = data.links || [];
      if (data.ask_community) links = links.concat([{ label: 'Post this to the community', url: root.getAttribute('data-community') + '?ask=' + encodeURIComponent(text.slice(0, 200)) }]);
      add(data.reply, 'bot', links);
      suggestions(data.suggestions);
    }).catch(function () { typing.remove(); add('I could not reach the server. Please try again.', 'bot'); });
  }
  function open() {
    root.classList.add('open');
    if (!greeted) {
      greeted = true;
      add('Hi! Ask me about events, deadlines, teams, waitlists, certificates, attendance or points.', 'bot');
      suggestions(JSON.parse(root.getAttribute('data-suggestions') || '[]'));
    }
    input.focus();
  }
  toggle.addEventListener('click', function () { root.classList.contains('open') ? root.classList.remove('open') : open(); });
  root.querySelector('.xm-chat-head button').addEventListener('click', function () { root.classList.remove('open'); });
  form.addEventListener('submit', function (e) { e.preventDefault(); send(input.value); });
})();
