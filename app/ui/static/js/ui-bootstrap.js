(function () {
  'use strict';

  var body = document.body;
  if (!body) {
    return;
  }

  var meta = document.querySelector('meta[name="csrf-token"]');
  if (meta) {
    var token = meta.getAttribute('content');
    if (token) {
      body.dataset.csrfToken = token;

      document.addEventListener('htmx:configRequest', function (event) {
        var detail = event.detail;
        if (!detail || !detail.headers) {
          return;
        }

        detail.headers['X-CSRF-Token'] = token;
      });
    }
  }

  if (body.dataset.liveUpdates !== 'sse') {
    return;
  }

  var sourceUrl = body.dataset.liveSource || '/ui/events';
  var EventSourceConstructor = window.EventSource;
  if (!EventSourceConstructor) {
    return;
  }

  var eventSource;

  var closeSource = function () {
    if (eventSource) {
      eventSource.close();
    }
  };

  var safeString = function (value) {
    if (value === undefined || value === null) {
      return '';
    }
    return String(value);
  };

  var shouldApplyUpdate = function (element, expected) {
    if (!expected) {
      return true;
    }
    var dataset = element.dataset || {};
    var keys = Object.keys(expected);
    for (var i = 0; i < keys.length; i += 1) {
      var key = keys[i];
      var expectedValue = safeString(expected[key]);
      var current = dataset[key];
      if (current !== undefined && current !== '' && current !== expectedValue) {
        return false;
      }
    }
    return true;
  };

  var applyFragmentUpdate = function (payload) {
    if (!payload || typeof payload !== 'object') {
      return;
    }
    var fragmentId = payload.fragment_id;
    if (!fragmentId) {
      return;
    }
    var element = document.getElementById(fragmentId);
    if (!element) {
      return;
    }

    var eventName = payload.event;
    if (eventName) {
      var expectedEvent = element.dataset ? element.dataset.liveEvent : null;
      if (expectedEvent && expectedEvent !== eventName) {
        return;
      }
    }

    if (!shouldApplyUpdate(element, payload.data_attributes)) {
      return;
    }

    if (typeof payload.html === 'string') {
      element.outerHTML = payload.html;
    }
  };

  var onFragmentEvent = function (event) {
    if (!event || !event.data) {
      return;
    }
    var payload;
    try {
      payload = JSON.parse(event.data);
    } catch (err) {
      console.warn('ui.events.parse_error', err);
      return;
    }
    applyFragmentUpdate(payload);
  };

  try {
    eventSource = new EventSourceConstructor(sourceUrl);
  } catch (error) {
    console.warn('ui.events.connection_failed', error);
    return;
  }

  eventSource.addEventListener('fragment', onFragmentEvent);

  eventSource.addEventListener('error', function () {
    // Allow the browser to handle reconnection; no-op for transient errors.
  });

  window.addEventListener('beforeunload', closeSource);
})();
