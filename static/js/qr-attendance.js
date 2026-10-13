// Live countdown, attendance count and roster for the faculty QR session page.
// Display only: the server re-checks expiry on every attendance submission.
(function () {
  'use strict';
  var root = document.getElementById('qa-root');
  if (!root) return;
  var timer = document.getElementById('qa-timer'), statusEl = document.getElementById('qa-status');
  var overlay = document.getElementById('qa-overlay'), closeBtn = document.getElementById('qa-close-btn');
  var countEl = document.getElementById('qa-count'), rowsEl = document.getElementById('qa-rows');
  var filter = document.getElementById('qa-filter');
  var status = root.dataset.status, deadline = Date.now() + parseInt(root.dataset.seconds || '0', 10) * 1000;

  function pad(n) { return n < 10 ? '0' + n : String(n); }
  function setStatus(s) {
    status = s;
    statusEl.textContent = s.charAt(0).toUpperCase() + s.slice(1);
    statusEl.className = 'qa-status ' + s;
    var dead = s !== 'active';
    overlay.hidden = !dead;
    overlay.textContent = s === 'closed' ? 'Session closed' : 'Session expired';
    if (closeBtn) closeBtn.hidden = dead;
    if (dead) timer.textContent = '00:00';
  }
  function tick() {
    if (status !== 'active') return;
    var left = Math.max(Math.ceil((deadline - Date.now()) / 1000), 0);
    timer.textContent = pad(Math.floor(left / 60)) + ':' + pad(left % 60);
    timer.classList.toggle('low', left <= 60);
    if (left === 0) poll();
  }
  function cell(text) { var td = document.createElement('td'); td.textContent = text; return td; }
  function render(rows) {
    rowsEl.textContent = '';
    if (!rows.length) {
      var tr = document.createElement('tr'), td = cell('No matching check-ins.');
      td.colSpan = 4; td.style.cssText = 'text-align:center;padding:24px'; tr.appendChild(td); rowsEl.appendChild(tr);
      return;
    }
    rows.forEach(function (r) {
      var tr = document.createElement('tr');
      tr.appendChild(cell(r.name)); tr.appendChild(cell(r.roll_no || '—'));
      var st = document.createElement('td'), b = document.createElement('span');
      b.className = 'qa-status active'; b.textContent = 'Present'; st.appendChild(b); tr.appendChild(st);
      tr.appendChild(cell(r.checked_in_label)); rowsEl.appendChild(tr);
    });
  }
  function poll() {
    var url = root.dataset.statusUrl + '?q=' + encodeURIComponent(filter ? filter.value : '');
    fetch(url, { credentials: 'same-origin', headers: { 'X-Requested-With': 'XMLHttpRequest' } })
      .then(function (r) { return r.json(); }).then(function (d) {
        countEl.textContent = d.count;
        deadline = Date.now() + d.seconds_left * 1000;   // re-sync with the server clock
        if (d.status !== status) setStatus(d.status);
        render(d.rows);
      }).catch(function () {});
  }
  setStatus(status); if (status === 'active') tick();
  setInterval(tick, 1000); setInterval(poll, 5000);
  if (filter) filter.addEventListener('input', poll);
})();
