(function () {
  'use strict';

  var meta = document.querySelector('meta[name="csrf-token"]');
  if (!meta) {
    return;
  }

  var token = meta.getAttribute('content');
  if (!token) {
    return;
  }

  var body = document.body;
  if (!body) {
    return;
  }

  body.dataset.csrfToken = token;

  document.addEventListener('htmx:configRequest', function (event) {
    var detail = event.detail;
    if (!detail || !detail.headers) {
      return;
    }

    detail.headers['X-CSRF-Token'] = token;
  });
})();
