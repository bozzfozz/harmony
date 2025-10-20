import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import vm from "node:vm";
import url from "node:url";

const __dirname = path.dirname(url.fileURLToPath(import.meta.url));
const helperPath = path.resolve(__dirname, "../../..", "app/ui/static/js/htmx-error-handler.js");
const helperSource = fs.readFileSync(helperPath, "utf8");

const ALERT_SELECTOR = '[data-role="alert-region"]';

function createDom() {
  const listeners = Object.create(null);
  const alertRegion = { innerHTML: "", dataset: {} };

  const body = {
    dataset: {},
    addEventListener(type, handler) {
      listeners[type] = handler;
    },
    dispatchEvent(event) {
      const handler = listeners[event.type];
      if (handler) {
        handler(event);
      }
    },
  };

  const document = {
    body,
    querySelector(selector) {
      if (selector === ALERT_SELECTOR) {
        return alertRegion;
      }
      return null;
    },
  };

  return { document, alertRegion, listeners };
}

function createContext() {
  const { document, alertRegion, listeners } = createDom();
  const window = { document };
  const context = {
    window,
    document,
    console,
    globalThis: null,
    __listeners: listeners,
  };
  window.window = window;
  context.globalThis = window;
  return { context, alertRegion };
}

function runHelper() {
  const { context, alertRegion } = createContext();
  vm.createContext(context);
  vm.runInContext(helperSource, context, { filename: "htmx-error-handler.js" });
  return { context, alertRegion };
}

class FakeXhr {
  constructor(status, responseText, contentType) {
    this.status = status;
    this.responseText = responseText;
    this._contentType = contentType;
  }

  getResponseHeader(name) {
    if (!name) {
      return "";
    }
    const normalised = String(name).toLowerCase();
    if (normalised === "content-type") {
      return this._contentType;
    }
    return "";
  }
}

function makeEvent(status, responseText, contentType) {
  return {
    type: "htmx:responseError",
    detail: {
      xhr: new FakeXhr(status, responseText, contentType),
    },
  };
}

function dispatch(context, event) {
  const handler = context.__listeners[event.type];
  if (handler) {
    handler(event);
  }
}

// Tests

const { context: context1, alertRegion: region1 } = runHelper();
assert.equal(typeof context1.window.handleHtmxError, "function", "global handler is registered");

const eventHtml = makeEvent(500, '<div class="alerts">Error</div>', "text/html; charset=utf-8");
dispatch(context1, eventHtml);
assert.equal(region1.innerHTML, '<div class="alerts">Error</div>', "html response populates alert region");
assert.equal(eventHtml.detail.__harmonyHtmxErrorHandled, true, "event is marked as handled");

const { context: context2, alertRegion: region2 } = runHelper();
const eventJson = makeEvent(500, '{"error":"fail"}', "application/json");
dispatch(context2, eventJson);
assert.equal(region2.innerHTML, "", "non-html responses are ignored");

const { context: context3, alertRegion: region3 } = runHelper();
const eventHandled = makeEvent(503, '<div class="alerts">Retry</div>', "text/html");
context3.window.handleHtmxError(eventHandled);
dispatch(context3, eventHandled);
assert.equal(region3.innerHTML, '<div class="alerts">Retry</div>', "handler only runs once");

console.log("htmx-error-handler tests completed");
