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

  var ACTION_BUTTON_SELECTOR = '[data-role="dashboard-action-button"]';

  var matchesSelector = function (element, selector) {
    if (!element || !selector) {
      return false;
    }
    if (typeof element.matches === 'function') {
      return element.matches(selector);
    }
    var legacyMatches = element.msMatchesSelector || element.webkitMatchesSelector;
    if (typeof legacyMatches === 'function') {
      return legacyMatches.call(element, selector);
    }
    return false;
  };

  var setButtonBusy = function (button, busy) {
    if (!button) {
      return;
    }
    if (busy) {
      button.setAttribute('aria-busy', 'true');
      button.setAttribute('disabled', 'disabled');
    } else {
      button.removeAttribute('aria-busy');
      button.removeAttribute('disabled');
    }
  };

  var applySwap = function (button, attribute) {
    if (!button) {
      return;
    }
    var value = button.getAttribute(attribute);
    if (value) {
      button.setAttribute('hx-swap', value);
    }
  };

  var addBodyListener = function (eventName, handler, options) {
    if (typeof body.addEventListener === 'function') {
      body.addEventListener(eventName, handler, options);
    }
  };

  var WATCHLIST_CREATE_FORM_SELECTOR = '#watchlist-create-form';
  var WATCHLIST_PAUSE_BUTTON_SELECTOR = 'button[data-test^="watchlist-pause-"]';
  var WATCHLIST_RESUME_INPUT_NAME = 'resume_at';
  var WATCHLIST_RESUME_TEMP_ATTR = 'data-watchlist-resume-temp';
  var DATETIME_LOCAL_PATTERN =
    /^(\d{4}-\d{2}-\d{2})T(\d{2}:\d{2})(?::(\d{2})(\.\d{1,6})?)?$/;

  var padTwo = function (value) {
    var stringValue = String(Math.abs(value));
    if (stringValue.length >= 2) {
      return stringValue.slice(-2);
    }
    return (value < 0 ? '0' + stringValue : '0' + stringValue).slice(-2);
  };

  var toIsoWithOffset = function (value) {
    if (typeof value !== 'string' || !value) {
      return null;
    }

    var match = value.match(DATETIME_LOCAL_PATTERN);
    if (!match) {
      return null;
    }

    var datePart = match[1];
    var timePart = match[2];
    if (match[3]) {
      timePart += ':' + match[3];
    }
    if (match[4]) {
      timePart += match[4];
    }

    var timePieces = match[2].split(':');
    var year = parseInt(datePart.slice(0, 4), 10);
    var month = parseInt(datePart.slice(5, 7), 10) - 1;
    var day = parseInt(datePart.slice(8, 10), 10);
    var hour = parseInt(timePieces[0], 10);
    var minute = parseInt(timePieces[1], 10);
    var second = match[3] ? parseInt(match[3], 10) : 0;
    var millisecond = 0;
    if (match[4]) {
      var fraction = match[4].slice(1, 4);
      while (fraction.length < 3) {
        fraction += '0';
      }
      millisecond = parseInt(fraction, 10);
      if (isNaN(millisecond)) {
        millisecond = 0;
      }
    }

    var localDate = new Date(
      year,
      month,
      day,
      hour,
      minute,
      isNaN(second) ? 0 : second,
      millisecond
    );
    if (isNaN(localDate.getTime())) {
      return null;
    }

    var offsetMinutes = -localDate.getTimezoneOffset();
    var sign = offsetMinutes >= 0 ? '+' : '-';
    var absoluteOffset = Math.abs(offsetMinutes);
    var hoursOffset = padTwo(Math.floor(absoluteOffset / 60));
    var minutesOffset = padTwo(absoluteOffset % 60);
    return datePart + 'T' + timePart + sign + hoursOffset + ':' + minutesOffset;
  };

  var shouldNormaliseWatchlistForm = function (form, submitEvent) {
    if (!form) {
      return false;
    }
    if (matchesSelector(form, WATCHLIST_CREATE_FORM_SELECTOR)) {
      return true;
    }
    if (submitEvent && submitEvent.submitter && submitEvent.submitter.getAttribute) {
      var submitTestId = submitEvent.submitter.getAttribute('data-test');
      if (submitTestId && submitTestId.indexOf('watchlist-pause-') === 0) {
        return true;
      }
    }
    return Boolean(form.querySelector(WATCHLIST_PAUSE_BUTTON_SELECTOR));
  };

  var cleanupWatchlistResumeAt = function (form) {
    if (!form) {
      return;
    }

    var resumeInput = form.querySelector(
      'input[data-watchlist-resume-original-name]'
    );
    if (resumeInput && resumeInput.dataset) {
      var originalName = resumeInput.dataset.watchlistResumeOriginalName;
      if (originalName && resumeInput.name !== originalName) {
        resumeInput.name = originalName;
      }
      delete resumeInput.dataset.watchlistResumeOriginalName;
    }

    var tempInputs = form.querySelectorAll('input[' + WATCHLIST_RESUME_TEMP_ATTR + ']');
    tempInputs.forEach(function (element) {
      if (element && element.parentNode) {
        element.parentNode.removeChild(element);
      }
    });

    if (form.dataset) {
      delete form.dataset.watchlistResumePrepared;
    }
  };

  var prepareWatchlistResumeAt = function (form, submitEvent) {
    if (!shouldNormaliseWatchlistForm(form, submitEvent)) {
      return;
    }

    cleanupWatchlistResumeAt(form);

    var resumeInput = form.querySelector('input[name="' + WATCHLIST_RESUME_INPUT_NAME + '"]');
    if (!resumeInput) {
      return;
    }

    var value = resumeInput.value;
    if (typeof value !== 'string' || !value) {
      return;
    }

    var isoValue = toIsoWithOffset(value);
    if (!isoValue) {
      return;
    }

    var originalName = resumeInput.getAttribute('name');
    if (!originalName) {
      return;
    }

    if (resumeInput.dataset) {
      resumeInput.dataset.watchlistResumeOriginalName = originalName;
    }
    resumeInput.removeAttribute('name');

    var hiddenInput = document.createElement('input');
    hiddenInput.setAttribute('type', 'hidden');
    hiddenInput.setAttribute('name', originalName);
    hiddenInput.setAttribute('value', isoValue);
    hiddenInput.setAttribute(WATCHLIST_RESUME_TEMP_ATTR, 'true');
    form.appendChild(hiddenInput);

    if (form.dataset) {
      form.dataset.watchlistResumePrepared = 'true';
    }
  };

  var resolveOwningForm = function (element) {
    if (!element) {
      return null;
    }
    if (element.tagName === 'FORM') {
      return element;
    }
    if (typeof element.closest === 'function') {
      return element.closest('form');
    }
    return null;
  };

  var handleWatchlistCleanup = function (event) {
    var detail = event.detail;
    if (!detail) {
      return;
    }

    var form = resolveOwningForm(detail.elt);
    if (!form) {
      return;
    }

    if (form.dataset && form.dataset.watchlistResumePrepared !== 'true') {
      var hasTemp = form.querySelector('input[' + WATCHLIST_RESUME_TEMP_ATTR + ']');
      if (!hasTemp && !matchesSelector(form, WATCHLIST_CREATE_FORM_SELECTOR)) {
        return;
      }
    }

    cleanupWatchlistResumeAt(form);
  };

  addBodyListener(
    'submit',
    function (event) {
      var target = event.target;
      if (!target || target.tagName !== 'FORM') {
        return;
      }
      prepareWatchlistResumeAt(target, event);
    },
    true
  );

  addBodyListener('htmx:afterRequest', handleWatchlistCleanup);
  addBodyListener('htmx:sendError', handleWatchlistCleanup);
  addBodyListener('htmx:responseError', handleWatchlistCleanup);

  addBodyListener('htmx:configRequest', function (event) {
    var detail = event.detail;
    if (!detail || !detail.parameters) {
      return;
    }

    var form = resolveOwningForm(detail.elt);
    if (!shouldNormaliseWatchlistForm(form)) {
      return;
    }

    var reasonInput = null;
    if (form) {
      reasonInput = form.querySelector('input[name="pause_reason"]');
      if (!reasonInput) {
        reasonInput = form.querySelector('input[name="reason"]');
      }
    }

    if (reasonInput && typeof reasonInput.name === 'string') {
      var reasonValue = '';
      if (typeof reasonInput.value === 'string') {
        reasonValue = reasonInput.value.trim();
      }
      if (reasonValue) {
        detail.parameters[reasonInput.name] = reasonValue;
      } else {
        delete detail.parameters[reasonInput.name];
      }
    }

    var resumeParameterName = WATCHLIST_RESUME_INPUT_NAME;
    var preparedResume = form
      ? form.querySelector('input[' + WATCHLIST_RESUME_TEMP_ATTR + ']')
      : null;

    if (preparedResume && preparedResume.name) {
      resumeParameterName = preparedResume.name;
      if (typeof preparedResume.value === 'string' && preparedResume.value) {
        detail.parameters[resumeParameterName] = preparedResume.value;
      } else {
        delete detail.parameters[resumeParameterName];
      }
      return;
    }

    if (!form) {
      delete detail.parameters[resumeParameterName];
      return;
    }

    var resumeInput = form.querySelector(
      'input[name="' + WATCHLIST_RESUME_INPUT_NAME + '"]'
    );
    if (resumeInput && typeof resumeInput.value === 'string') {
      var resumeValue = resumeInput.value.trim();
      if (resumeValue) {
        detail.parameters[resumeInput.name || resumeParameterName] = resumeValue;
      } else {
        delete detail.parameters[resumeInput.name || resumeParameterName];
      }
    } else {
      delete detail.parameters[resumeParameterName];
    }
  });

  addBodyListener('htmx:beforeRequest', function (event) {
    var detail = event.detail;
    if (!detail) {
      return;
    }
    var element = detail.elt;
    if (!matchesSelector(element, ACTION_BUTTON_SELECTOR)) {
      return;
    }
    applySwap(element, 'data-success-swap');
    setButtonBusy(element, true);
  });

  addBodyListener('htmx:afterRequest', function (event) {
    var detail = event.detail;
    if (!detail) {
      return;
    }
    var element = detail.elt;
    if (!matchesSelector(element, ACTION_BUTTON_SELECTOR)) {
      return;
    }
    setButtonBusy(element, false);
    applySwap(element, 'data-success-swap');
  });

  addBodyListener('htmx:beforeSwap', function (event) {
    var detail = event.detail;
    if (!detail) {
      return;
    }
    var element = detail.elt;
    if (!matchesSelector(element, ACTION_BUTTON_SELECTOR)) {
      return;
    }
    if (detail.isError) {
      applySwap(element, 'data-error-swap');
    } else {
      applySwap(element, 'data-success-swap');
    }
  });

  var initSpotifyFreeIngestDropzone = function () {
    var dropzone = document.getElementById('spotify-free-ingest-dropzone');
    if (!dropzone) {
      return;
    }

    var form = document.getElementById('spotify-free-ingest-upload-form');
    var fileInput = document.getElementById('ingest_file');
    if (!form || !fileInput) {
      return;
    }

    var statusElement = dropzone.querySelector('[data-role="status"]');
    var defaultMessage = dropzone.getAttribute('data-default-message') || '';
    var selectedMessage = dropzone.getAttribute('data-selected-message') || defaultMessage;
    var uploadingMessage = dropzone.getAttribute('data-uploading-message') || defaultMessage;
    var busyMessage = dropzone.getAttribute('data-busy-message') || uploadingMessage;
    var multipleMessage = dropzone.getAttribute('data-multiple-message') || defaultMessage;
    var errorMessage = dropzone.getAttribute('data-error-message') || multipleMessage;
    var isSubmitting = false;

    var formatMessage = function (template, fileName) {
      if (!template) {
        return '';
      }
      var resolved = template;
      var safeName = fileName ? String(fileName) : '';
      if (safeName) {
        resolved = resolved.replace(/__FILENAME__/g, '“' + safeName + '”');
      } else {
        resolved = resolved.replace(/__FILENAME__/g, '');
      }
      return resolved;
    };

    var setBusy = function (busy) {
      if (busy) {
        dropzone.setAttribute('aria-busy', 'true');
      } else {
        dropzone.removeAttribute('aria-busy');
      }
    };

    var setStatus = function (state, message, fileName) {
      var text = formatMessage(message, fileName);
      dropzone.classList.remove('is-error', 'has-file', 'is-uploading');
      if (state === 'error') {
        dropzone.classList.add('is-error');
      } else if (state === 'file') {
        dropzone.classList.add('has-file');
      } else if (state === 'uploading') {
        dropzone.classList.add('is-uploading');
      }
      if (statusElement) {
        statusElement.textContent = text;
      }
      setBusy(state === 'uploading');
    };

    var reset = function () {
      isSubmitting = false;
      setBusy(false);
      dropzone.classList.remove('is-dragover');
      dropzone.classList.remove('has-file');
      dropzone.classList.remove('is-uploading');
      dropzone.classList.remove('is-error');
      if (typeof fileInput.value === 'string') {
        fileInput.value = '';
      }
      setStatus(null, defaultMessage);
    };

    setStatus(null, defaultMessage);

    dropzone.addEventListener('dragenter', function (event) {
      event.preventDefault();
      dropzone.classList.add('is-dragover');
    });

    dropzone.addEventListener('dragover', function (event) {
      event.preventDefault();
      dropzone.classList.add('is-dragover');
    });

    dropzone.addEventListener('dragleave', function (event) {
      var related = event.relatedTarget;
      if (!related || !dropzone.contains(related)) {
        dropzone.classList.remove('is-dragover');
      }
    });

    var assignFiles = function (files) {
      if (!files || files.length === 0) {
        reset();
        return;
      }
      if (files.length > 1) {
        setStatus('error', multipleMessage);
        return;
      }
      var file = files[0];
      try {
        var transfer = new DataTransfer();
        transfer.items.add(file);
        fileInput.files = transfer.files;
      } catch (err) {
        try {
          fileInput.files = files;
        } catch (assignError) {
          setStatus('error', errorMessage);
          return;
        }
      }
      isSubmitting = true;
      setStatus('uploading', uploadingMessage, file ? file.name : '');
      if (typeof form.requestSubmit === 'function') {
        form.requestSubmit();
      } else {
        form.submit();
      }
    };

    dropzone.addEventListener('drop', function (event) {
      event.preventDefault();
      dropzone.classList.remove('is-dragover');
      if (isSubmitting) {
        setStatus('uploading', busyMessage);
        return;
      }
      var dataTransfer = event.dataTransfer;
      assignFiles(dataTransfer && dataTransfer.files ? dataTransfer.files : null);
    });

    dropzone.addEventListener('click', function () {
      if (isSubmitting) {
        setStatus('uploading', busyMessage);
        return;
      }
      fileInput.click();
    });

    dropzone.addEventListener('keydown', function (event) {
      if (event.key === 'Enter' || event.key === ' ') {
        event.preventDefault();
        if (isSubmitting) {
          setStatus('uploading', busyMessage);
          return;
        }
        fileInput.click();
      }
    });

    fileInput.addEventListener('change', function () {
      if (isSubmitting) {
        return;
      }
      var files = fileInput.files;
      if (!files || files.length === 0) {
        setStatus(null, defaultMessage);
        return;
      }
      if (files.length > 1) {
        setStatus('error', multipleMessage);
        return;
      }
      var file = files[0];
      setStatus('file', selectedMessage, file ? file.name : '');
    });

    form.addEventListener('htmx:beforeRequest', function (event) {
      if (event.target !== form) {
        return;
      }
      isSubmitting = true;
      setBusy(true);
    });

    form.addEventListener('htmx:afterSwap', function (event) {
      if (event.target !== form) {
        return;
      }
      reset();
    });

    form.addEventListener('htmx:afterRequest', function (event) {
      if (event.target !== form) {
        return;
      }
      isSubmitting = false;
      setBusy(false);
    });

    form.addEventListener('htmx:responseError', function (event) {
      if (event.target !== form) {
        return;
      }
      isSubmitting = false;
      setBusy(false);
      setStatus('error', errorMessage);
    });
  };

  initSpotifyFreeIngestDropzone();

  if (body.dataset.liveUpdates !== 'sse') {
    return;
  }

  var sourceUrl = body.dataset.liveSource || '/ui/events';
  var hasDowngradedToPolling = false;

  var POLLING_INTERVAL_DEFAULTS = {
    downloads: 15,
    jobs: 15,
    watchlist: 30,
    activity: 60,
  };

  var parseIntervalSeconds = function (value) {
    if (value === undefined || value === null || value === '') {
      return null;
    }
    var numeric = Number(value);
    if (!isFinite(numeric) || !(numeric > 0)) {
      return null;
    }
    return numeric;
  };

  var ensurePollingTrigger = function (element, intervalSeconds) {
    if (!element || !(intervalSeconds > 0)) {
      return;
    }
    var trigger = element.getAttribute('hx-trigger');
    if (typeof trigger !== 'string') {
      trigger = '';
    }
    if (/\bevery\s+/i.test(trigger)) {
      return;
    }
    var parts = trigger.split(',');
    var cleaned = [];
    for (var i = 0; i < parts.length; i += 1) {
      var part = parts[i];
      if (part && part.trim()) {
        cleaned.push(part.trim());
      }
    }
    if (!cleaned.length) {
      cleaned.push('load');
    }
    cleaned.push('every ' + String(Math.round(intervalSeconds)) + 's');
    element.setAttribute('hx-trigger', cleaned.join(', '));
  };

  var downgradeToPolling = function (reason) {
    if (hasDowngradedToPolling) {
      return;
    }
    hasDowngradedToPolling = true;

    if (body && body.dataset) {
      body.dataset.liveUpdates = 'polling';
    }

    var fragments = [];
    if (document && typeof document.querySelectorAll === 'function') {
      fragments = document.querySelectorAll('[data-live-event]') || [];
    }

    for (var i = 0; i < fragments.length; i += 1) {
      var fragment = fragments[i];
      if (!fragment || !fragment.dataset) {
        continue;
      }
      var dataset = fragment.dataset;
      var interval = parseIntervalSeconds(dataset.livePollingInterval);
      if (interval === null) {
        var eventName = dataset.liveEvent || '';
        if (eventName && Object.prototype.hasOwnProperty.call(POLLING_INTERVAL_DEFAULTS, eventName)) {
          interval = POLLING_INTERVAL_DEFAULTS[eventName];
        }
      }
      if (interval === null) {
        continue;
      }
      dataset.livePollingInterval = String(Math.round(interval));
      ensurePollingTrigger(fragment, interval);
    }

    var htmxInstance = window.htmx;
    if (htmxInstance && typeof htmxInstance.process === 'function') {
      htmxInstance.process(body || document);
    }

    var controller = window.__harmonyPollingController;
    if (controller && typeof controller._scheduleRescan === 'function') {
      try {
        controller._scheduleRescan();
      } catch (controllerError) {
        console.warn('ui.live_updates.polling_rescan_failed', controllerError);
      }
    }

    if (typeof window.dispatchEvent === 'function' && typeof window.CustomEvent === 'function') {
      try {
        window.dispatchEvent(
          new window.CustomEvent('harmony:live-updates:fallback', {
            detail: { reason: reason || 'unknown', mode: 'polling' },
          })
        );
      } catch (eventError) {
        console.warn('ui.live_updates.fallback_event_failed', eventError);
      }
    }

    if (console && typeof console.info === 'function') {
      console.info('ui.live_updates.fallback', { reason: reason || 'unknown', mode: 'polling' });
    }
  };

  var EventSourceConstructor = window.EventSource;
  if (!EventSourceConstructor) {
    downgradeToPolling('unsupported');
    return;
  }

  var eventSource;

  var POLL_INTERVALS_BY_EVENT = {
    downloads: 15,
    jobs: 15,
    watchlist: 30,
    activity: 60,
  };

  var liveFragmentMeta = Object.create(null);
  var pollingFallbacks = Object.create(null);

  var toPlainObject = function (dataset) {
    if (!dataset) {
      return {};
    }
    var result = {};
    Object.keys(dataset).forEach(function (key) {
      result[key] = dataset[key];
    });
    return result;
  };

  var registerLiveFragment = function (element) {
    if (!element || !element.id) {
      return;
    }
    var meta = {
      id: element.id,
      hxGet: element.getAttribute('hx-get') || null,
      hxTarget: element.getAttribute('hx-target') || null,
      hxSwap: element.getAttribute('hx-swap') || null,
      hxTrigger: element.getAttribute('hx-trigger') || null,
      hxOn: element.getAttribute('hx-on') || null,
      classList: element.className ? element.className.split(/\s+/) : [],
      role: element.getAttribute('role') || null,
      ariaLive: element.getAttribute('aria-live') || null,
      ariaLabelledby: element.getAttribute('aria-labelledby') || null,
      dataFragment: element.getAttribute('data-fragment') || null,
      eventName:
        element.dataset && element.dataset.liveEvent
          ? element.dataset.liveEvent
          : null,
    };
    liveFragmentMeta[element.id] = meta;
    if (pollingFallbacks[element.id]) {
      var fallback = pollingFallbacks[element.id];
      fallback.hxGet = meta.hxGet;
      fallback.hxTarget = meta.hxTarget;
      fallback.hxSwap = meta.hxSwap || fallback.hxSwap;
      fallback.hxOn = meta.hxOn;
      fallback.hxTrigger = meta.hxTrigger || fallback.hxTrigger;
      fallback.classList = meta.classList;
      fallback.role = meta.role;
      fallback.ariaLive = meta.ariaLive;
      fallback.ariaLabelledby = meta.ariaLabelledby;
      fallback.dataFragment = meta.dataFragment;
      if (meta.eventName) {
        fallback.eventName = meta.eventName;
      }
    }
  };

  var registerExistingLiveFragments = function () {
    var nodes = document.querySelectorAll('[data-live-event]');
    for (var i = 0; i < nodes.length; i += 1) {
      registerLiveFragment(nodes[i]);
    }
  };

  var normalizeTriggerParts = function (trigger) {
    if (!trigger) {
      return [];
    }
    return trigger
      .split(',')
      .map(function (part) {
        return part.trim();
      })
      .filter(function (part) {
        return part.length > 0;
      });
  };

  var applyPollingAttributes = function (element, fallback) {
    if (!element || !fallback) {
      return;
    }
    if (fallback.role) {
      element.setAttribute('role', fallback.role);
    }
    if (fallback.ariaLive) {
      element.setAttribute('aria-live', fallback.ariaLive);
    }
    if (fallback.ariaLabelledby) {
      element.setAttribute('aria-labelledby', fallback.ariaLabelledby);
    }
    if (fallback.dataFragment) {
      element.setAttribute('data-fragment', fallback.dataFragment);
    }
    if (fallback.classList && fallback.classList.length) {
      for (var i = 0; i < fallback.classList.length; i += 1) {
        var cls = fallback.classList[i];
        if (cls) {
          element.classList.add(cls);
        }
      }
    }
    if (fallback.hxGet) {
      element.setAttribute('hx-get', fallback.hxGet);
    }
    if (fallback.hxTarget) {
      element.setAttribute('hx-target', fallback.hxTarget);
    }
    if (fallback.hxSwap) {
      element.setAttribute('hx-swap', fallback.hxSwap);
    }
    if (fallback.hxOn) {
      element.setAttribute('hx-on', fallback.hxOn);
    }
    var triggerParts = normalizeTriggerParts(fallback.hxTrigger);
    var pollPart = 'every ' + fallback.interval + 's';
    var replaced = false;
    for (var j = 0; j < triggerParts.length; j += 1) {
      if (triggerParts[j].indexOf('every ') === 0) {
        triggerParts[j] = pollPart;
        replaced = true;
        break;
      }
    }
    if (!replaced) {
      if (!triggerParts.length) {
        triggerParts.push('load');
      }
      triggerParts.push(pollPart);
    }
    element.setAttribute('hx-trigger', triggerParts.join(', '));
    if (element.dataset) {
      element.dataset.liveMode = 'polling';
    }
  };

  var ensurePollingFallback = function (fragmentId, eventName) {
    if (!fragmentId) {
      return null;
    }
    if (pollingFallbacks[fragmentId]) {
      return pollingFallbacks[fragmentId];
    }
    var meta = liveFragmentMeta[fragmentId];
    if (!meta) {
      return null;
    }
    var resolvedEvent = eventName || meta.eventName;
    if (!resolvedEvent) {
      return null;
    }
    var interval = POLL_INTERVALS_BY_EVENT[resolvedEvent];
    if (!interval) {
      return null;
    }
    var fallback = {
      interval: interval,
      eventName: resolvedEvent,
      hxGet: meta.hxGet,
      hxTarget: meta.hxTarget,
      hxSwap: meta.hxSwap,
      hxOn: meta.hxOn,
      hxTrigger: meta.hxTrigger,
      classList: meta.classList,
      role: meta.role,
      ariaLive: meta.ariaLive,
      ariaLabelledby: meta.ariaLabelledby,
      dataFragment: meta.dataFragment,
    };
    if (!fallback.hxTarget && fragmentId) {
      fallback.hxTarget = '#' + fragmentId;
    }
    if (!fallback.hxSwap) {
      fallback.hxSwap = 'outerHTML';
    }
    if (!fallback.hxTrigger) {
      fallback.hxTrigger = 'load';
    }
    pollingFallbacks[fragmentId] = fallback;
    return fallback;
  };

  var downgradeFragmentToPolling = function (
    element,
    fragmentId,
    eventName,
    expectedAttributes
  ) {
    if (!element || !fragmentId) {
      return;
    }
    var fallback = ensurePollingFallback(fragmentId, eventName);
    if (!fallback) {
      console.warn(
        'ui.events.fragment_downgrade_missing_meta',
        fragmentId,
        eventName
      );
      return;
    }
    applyPollingAttributes(element, fallback);
    element.removeAttribute('data-live-event');
    if (element.dataset && element.dataset.liveEvent) {
      delete element.dataset.liveEvent;
    }
    console.warn('ui.events.fragment_downgraded', {
      fragment: fragmentId,
      event: fallback.eventName || eventName,
      interval: fallback.interval,
      expected: expectedAttributes,
      actual: toPlainObject(element.dataset),
    });
    if (window.htmx && typeof window.htmx.trigger === 'function') {
      window.htmx.trigger(element, 'load');
    }
  };

  var handleHtmxAfterSwap = function (event) {
    var detail = event.detail || {};
    var candidates = [];
    if (detail.target) {
      candidates.push(detail.target);
    }
    if (detail.target && detail.target.querySelectorAll) {
      var descendants = detail.target.querySelectorAll('[id]');
      for (var i = 0; i < descendants.length; i += 1) {
        candidates.push(descendants[i]);
      }
    }
    for (var j = 0; j < candidates.length; j += 1) {
      var node = candidates[j];
      if (!node || !node.id) {
        continue;
      }
      if (node.dataset && node.dataset.liveEvent) {
        registerLiveFragment(node);
      }
      var fallback = pollingFallbacks[node.id];
      if (fallback && (!node.dataset || node.dataset.liveMode !== 'polling')) {
        applyPollingAttributes(node, fallback);
      }
    }
  };

  var initialiseLiveFragments = function () {
    registerExistingLiveFragments();
  };

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', initialiseLiveFragments, {
      once: true,
    });
  } else {
    initialiseLiveFragments();
  }
  document.addEventListener('htmx:afterSwap', handleHtmxAfterSwap);

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

    if (element.dataset && element.dataset.liveMode === 'polling') {
      return;
    }

    if (!shouldApplyUpdate(element, payload.data_attributes)) {
      console.warn('ui.events.fragment_mismatch', {
        fragment: fragmentId,
        event: eventName,
        currentEvent: element.dataset ? element.dataset.liveEvent : null,
        expected: payload.data_attributes || {},
        actual: toPlainObject(element.dataset),
      });
      downgradeFragmentToPolling(
        element,
        fragmentId,
        eventName || (element.dataset ? element.dataset.liveEvent : null),
        payload.data_attributes || {}
      );
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
    downgradeToPolling('connection_failed');
    return;
  }

  eventSource.addEventListener('fragment', onFragmentEvent);

  eventSource.addEventListener('error', function () {
    // Allow the browser to handle reconnection; no-op for transient errors.
  });

  window.addEventListener('beforeunload', closeSource);
})();
