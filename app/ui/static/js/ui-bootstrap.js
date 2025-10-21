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
