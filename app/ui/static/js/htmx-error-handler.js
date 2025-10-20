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

  var ALERT_SELECTOR = '[data-role="alert-region"]';
  var HANDLED_FLAG = "__harmonyHtmxErrorHandled";

  var findAlertRegion = function () {
    if (typeof document.querySelector !== "function") {
      return null;
    }
    return document.querySelector(ALERT_SELECTOR);
  };

  var getContentType = function (xhr) {
    if (!xhr) {
      return "";
    }
    if (typeof xhr.getResponseHeader === "function") {
      var header = xhr.getResponseHeader("Content-Type");
      if (header) {
        return header;
      }
      header = xhr.getResponseHeader("content-type");
      if (header) {
        return header;
      }
    }
    if (typeof xhr.contentType === "string") {
      return xhr.contentType;
    }
    if (xhr.headers && typeof xhr.headers === "object") {
      var value = xhr.headers["Content-Type"] || xhr.headers["content-type"];
      if (value) {
        return value;
      }
    }
    return "";
  };

  var isHtmlResponse = function (contentType) {
    if (!contentType) {
      return false;
    }
    var normalised = String(contentType).toLowerCase();
    return (
      normalised.indexOf("text/html") !== -1 ||
      normalised.indexOf("application/xhtml+xml") !== -1
    );
  };

  var renderAlerts = function (html) {
    if (!html) {
      return;
    }
    var region = findAlertRegion();
    if (!region) {
      return;
    }
    region.innerHTML = html;
  };

  var handleHtmxError = function (event) {
    if (!event || !event.detail) {
      return;
    }
    var detail = event.detail;
    if (detail[HANDLED_FLAG]) {
      return;
    }
    detail[HANDLED_FLAG] = true;

    var xhr = detail.xhr;
    if (!xhr) {
      return;
    }

    var status = typeof xhr.status === "number" ? xhr.status : 0;
    if (status < 400) {
      return;
    }

    var responseText = typeof xhr.responseText === "string" ? xhr.responseText : "";
    if (!responseText || responseText.trim() === "") {
      return;
    }

    var contentType = getContentType(xhr);
    if (!isHtmlResponse(contentType)) {
      return;
    }

    renderAlerts(responseText);
  };

  body.addEventListener("htmx:responseError", handleHtmxError);

  root.handleHtmxError = handleHtmxError;
})();
