// Submits the single-page registration forms with fetch and shows field-level errors inline.
(function () {
  document.querySelectorAll('form[data-register-form]').forEach(function (form) {
    var banner = form.querySelector('.cems-auth-form-error');
    var button = form.querySelector('button[type=submit]');

    function clearErrors() {
      form.querySelectorAll('.field-error').forEach(function (el) { el.textContent = ''; });
      form.querySelectorAll('.cems-field.has-error').forEach(function (el) { el.classList.remove('has-error'); });
      if (banner) { banner.textContent = ''; banner.classList.remove('show'); }
    }

    function showErrors(errors, fallback) {
      var unplaced = [];
      Object.keys(errors || {}).forEach(function (name) {
        var slot = form.querySelector('[data-error-for="' + name + '"]');
        if (slot) {
          slot.textContent = errors[name];
          slot.closest('.cems-field').classList.add('has-error');
        } else {
          unplaced.push(errors[name]);
        }
      });
      if ((unplaced.length || fallback) && banner) {
        banner.textContent = unplaced.join(' ') || fallback;
        banner.classList.add('show');
      }
      var first = form.querySelector('.has-error input, .has-error select');
      if (first) first.focus();
    }

    form.addEventListener('submit', function (event) {
      event.preventDefault();
      clearErrors();
      var password = form.querySelector('[name=password]');
      var confirm = form.querySelector('[name=confirm_password]');
      if (password && confirm && password.value !== confirm.value) {
        showErrors({ confirm_password: 'Passwords do not match.' });
        return;
      }
      if (!form.reportValidity()) return;
      button.disabled = true;
      var original = button.textContent;
      button.textContent = 'Creating account…';
      fetch(form.action || window.location.href, {
        method: 'POST',
        body: new FormData(form),
        headers: { 'X-Requested-With': 'XMLHttpRequest' },
        credentials: 'same-origin'
      }).then(function (response) {
        return response.json().catch(function () { return {}; }).then(function (data) {
          return { ok: response.ok, data: data, status: response.status };
        });
      }).then(function (result) {
        if (result.ok && result.data.success) {
          window.location.href = result.data.redirect || '/login';
          return;
        }
        var fallback = result.status === 400 && !result.data.errors
          ? 'Your session expired. Please refresh the page and try again.'
          : 'Could not create the account. Please check the form.';
        showErrors(result.data.errors, fallback);
      }).catch(function () {
        showErrors({}, 'Network error. Please try again.');
      }).then(function () {
        button.disabled = false;
        button.textContent = original;
      });
    });
  });
})();
