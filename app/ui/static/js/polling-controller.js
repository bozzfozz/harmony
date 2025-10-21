(function () {
  "use strict";

  var root = typeof window !== "undefined" ? window : null;
  if (!root && typeof globalThis !== "undefined") {
    root = globalThis;
  }
  if (!root) {
    return;
  }

  var document = root.document;
  if (!document) {
    return;
  }

  var body = document.body;
  if (!body || typeof body.addEventListener !== "function") {
    return;
  }

  var MAX_INTERVAL_SECONDS = 300; // 5 minutes

  function trim(value) {
    if (typeof value !== "string") {
      return "";
    }
    if (typeof value.trim === "function") {
      return value.trim();
    }
    return value.replace(/^\s+|\s+$/g, "");
  }

  function isPollingTriggerPart(part) {
    if (!part) {
      return false;
    }
    var normalised = trim(part).toLowerCase();
    return normalised.indexOf("every") === 0;
  }

  function parseInterval(part) {
    var match = /every\s+([0-9]+(?:\.[0-9]+)?)\s*(ms|s)?/i.exec(part);
    if (!match) {
      return null;
    }
    var value = Number(match[1]);
    if (!(value >= 0)) {
      return null;
    }
    var unit = match[2] ? match[2].toLowerCase() : "s";
    var seconds;
    if (unit === "ms") {
      seconds = value / 1000;
    } else {
      seconds = value;
      unit = "s";
    }
    return { seconds: seconds, unit: unit };
  }

  function formatInterval(intervalSeconds, unit) {
    if (!(intervalSeconds >= 0)) {
      return null;
    }
    if (unit === "ms") {
      var millis = Math.max(0, Math.round(intervalSeconds * 1000));
      return "every " + String(millis) + "ms";
    }
    var seconds = Math.max(0, Math.round(intervalSeconds));
    if (seconds < 1) {
      seconds = 1;
    }
    return "every " + String(seconds) + "s";
  }

  function cloneArrayLike(items) {
    if (!items) {
      return [];
    }
    if (Array.isArray(items)) {
      return items.slice();
    }
    if (typeof items.length === "number") {
      var copy = [];
      for (var index = 0; index < items.length; index += 1) {
        copy.push(items[index]);
      }
      return copy;
    }
    return [];
  }

  function PollingController(options) {
    this.document = document;
    this.body = body;
    this.htmx = options && options.htmx ? options.htmx : root.htmx;
    this.maxIntervalSeconds = MAX_INTERVAL_SECONDS;
    this._states = new WeakMap();
    this._rescanScheduled = false;
    this._init();
  }

  PollingController.prototype._init = function () {
    this._rescan();
    var self = this;
    this.body.addEventListener("htmx:afterRequest", function (event) {
      self._handleAfterRequest(event);
    });
    this.body.addEventListener("htmx:sendError", function (event) {
      self._handleFailureEvent(event);
    });
    this.body.addEventListener("htmx:afterSwap", function () {
      self._scheduleRescan();
    });
  };

  PollingController.prototype._scheduleRescan = function () {
    if (this._rescanScheduled) {
      return;
    }
    this._rescanScheduled = true;
    var self = this;
    var schedule = typeof root.requestAnimationFrame === "function" ? root.requestAnimationFrame : function (fn) {
      return root.setTimeout(fn, 16);
    };
    schedule(function () {
      self._rescanScheduled = false;
      self._rescan();
    });
  };

  PollingController.prototype._rescan = function () {
    if (!this.document || typeof this.document.querySelectorAll !== "function") {
      return;
    }
    var elements = this.document.querySelectorAll("[hx-trigger]");
    var list = cloneArrayLike(elements);
    for (var i = 0; i < list.length; i += 1) {
      this._registerElement(list[i]);
    }
  };

  PollingController.prototype._registerElement = function (element) {
    if (!element || typeof element.getAttribute !== "function") {
      return;
    }
    if (this._states.has(element)) {
      return;
    }
    var trigger = element.getAttribute("hx-trigger");
    if (!trigger || typeof trigger !== "string") {
      return;
    }
    var parts = trigger.split(",");
    var pollingIndex = -1;
    for (var i = 0; i < parts.length; i += 1) {
      if (isPollingTriggerPart(parts[i])) {
        pollingIndex = i;
        break;
      }
    }
    if (pollingIndex === -1) {
      return;
    }
    var interval = parseInterval(parts[pollingIndex]);
    if (!interval || !(interval.seconds > 0)) {
      return;
    }
    var state = {
      element: element,
      originalTrigger: trigger,
      pollingIndex: pollingIndex,
      parts: parts,
      unit: interval.unit,
      baseSeconds: interval.seconds,
      currentSeconds: interval.seconds,
      failureCount: 0,
    };
    this._states.set(element, state);
  };

  PollingController.prototype._getState = function (element) {
    if (!element) {
      return null;
    }
    var state = this._states.get(element);
    if (state) {
      return state;
    }
    this._registerElement(element);
    return this._states.get(element) || null;
  };

  PollingController.prototype._handleAfterRequest = function (event) {
    if (!event || !event.detail) {
      return;
    }
    var detail = event.detail;
    var element = detail.elt;
    var state = this._getState(element);
    if (!state) {
      return;
    }
    if (detail.successful) {
      this._handleSuccess(state);
      return;
    }
    this._handleFailure(state);
  };

  PollingController.prototype._handleFailureEvent = function (event) {
    if (!event || !event.detail) {
      return;
    }
    var element = event.detail.elt;
    var state = this._getState(element);
    if (!state) {
      return;
    }
    this._handleFailure(state);
  };

  PollingController.prototype._handleSuccess = function (state) {
    if (!state) {
      return;
    }
    state.failureCount = 0;
    state.currentSeconds = state.baseSeconds;
    this._applyInterval(state, state.baseSeconds, true);
  };

  PollingController.prototype._handleFailure = function (state) {
    if (!state) {
      return;
    }
    state.failureCount += 1;
    var factor = Math.pow(2, state.failureCount);
    var nextSeconds = state.baseSeconds * factor;
    if (nextSeconds > this.maxIntervalSeconds) {
      nextSeconds = this.maxIntervalSeconds;
    }
    if (nextSeconds === state.currentSeconds) {
      return;
    }
    state.currentSeconds = nextSeconds;
    this._applyInterval(state, nextSeconds, false);
  };

  PollingController.prototype._applyInterval = function (state, intervalSeconds, reset) {
    if (!state || !state.element) {
      return;
    }
    var trigger;
    if (reset) {
      trigger = state.originalTrigger;
    } else {
      var parts = cloneArrayLike(state.parts);
      if (state.pollingIndex < 0 || state.pollingIndex >= parts.length) {
        return;
      }
      var updated = formatInterval(intervalSeconds, state.unit);
      if (!updated) {
        return;
      }
      parts[state.pollingIndex] = " " + updated;
      trigger = parts.join(",");
    }
    if (state.element.getAttribute("hx-trigger") === trigger) {
      return;
    }
    state.element.setAttribute("hx-trigger", trigger);
    if (this.htmx && typeof this.htmx.process === "function") {
      this.htmx.process(state.element);
    }
  };

  var controller = new PollingController({ htmx: root.htmx });
  root.HarmonyPollingController = PollingController;
  root.__harmonyPollingController = controller;
})();
