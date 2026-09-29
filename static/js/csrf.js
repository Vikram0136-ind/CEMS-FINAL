// Adds the CSRF token to every POST form and turns logout links into POST requests.
(function () {
  const meta = document.querySelector('meta[name="csrf-token"]');
  const token = meta ? meta.getAttribute('content') : '';

  function addToken(form) {
    if (!token || (form.method || '').toLowerCase() !== 'post') return;
    if (form.querySelector('input[name="csrf_token"]')) return;
    const input = document.createElement('input');
    input.type = 'hidden';
    input.name = 'csrf_token';
    input.value = token;
    form.appendChild(input);
  }

  function init() {
    document.querySelectorAll('form').forEach(addToken);
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init);
  else init();

  document.addEventListener('submit', function (e) {
    if (e.target && e.target.tagName === 'FORM') addToken(e.target);
  }, true);

  document.addEventListener('click', function (e) {
    const link = e.target.closest && e.target.closest('a[data-logout]');
    if (!link) return;
    e.preventDefault();
    const form = document.createElement('form');
    form.method = 'post';
    form.action = link.href;
    document.body.appendChild(form);
    addToken(form);
    form.submit();
  });
})();
