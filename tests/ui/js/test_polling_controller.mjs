import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import vm from "node:vm";
import url from "node:url";

const __dirname = path.dirname(url.fileURLToPath(import.meta.url));
const controllerPath = path.resolve(__dirname, "../../..", "app/ui/static/js/polling-controller.js");
const controllerSource = fs.readFileSync(controllerPath, "utf8");

function createElement(initialTrigger) {
  const attributes = Object.create(null);
  attributes["hx-trigger"] = initialTrigger;
  return {
    _attributes: attributes,
    getAttribute(name) {
      return this._attributes[name] ?? null;
    },
    setAttribute(name, value) {
      this._attributes[name] = value;
    },
  };
}

function runController(initialTrigger = "load, every 15s") {
  const listeners = Object.create(null);
  const element = createElement(initialTrigger);

  const body = {
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
    querySelectorAll(selector) {
      if (selector === "[hx-trigger]") {
        return [element];
      }
      return [];
    },
  };

  const htmx = {
    processCalls: [],
    process(elt) {
      this.processCalls.push(elt);
    },
  };

  function immediateTimeout(fn) {
    if (typeof fn === "function") {
      fn();
    }
    return 0;
  }

  const window = {
    document,
    htmx,
    setTimeout: immediateTimeout,
    requestAnimationFrame: null,
  };
  window.window = window;

  const context = {
    window,
    document,
    console,
    globalThis: window,
    setTimeout: immediateTimeout,
    clearTimeout() {},
  };

  vm.createContext(context);
  vm.runInContext(controllerSource, context, { filename: "polling-controller.js" });

  return { window, element, listeners, htmx };
}

function dispatch(listeners, type, detail = {}) {
  const handler = listeners[type];
  if (typeof handler === "function") {
    handler({ type, detail });
  }
}

// Tests
const { element, listeners, htmx } = runController("load, every 15s");
assert.equal(element.getAttribute("hx-trigger"), "load, every 15s", "initial trigger is preserved");

const afterRequest = listeners["htmx:afterRequest"];
assert.equal(typeof afterRequest, "function", "afterRequest handler is registered");

const sendError = listeners["htmx:sendError"];
assert.equal(typeof sendError, "function", "sendError handler is registered");

dispatch(listeners, "htmx:afterRequest", { elt: element, successful: false });
assert.equal(element.getAttribute("hx-trigger"), "load, every 30s", "first failure doubles the interval");
assert.equal(htmx.processCalls.length, 1, "htmx.process is invoked after interval update");

dispatch(listeners, "htmx:afterRequest", { elt: element, successful: false });
assert.equal(element.getAttribute("hx-trigger"), "load, every 60s", "second failure doubles again");

dispatch(listeners, "htmx:afterRequest", { elt: element, successful: true });
assert.equal(element.getAttribute("hx-trigger"), "load, every 15s", "success resets to the base interval");
assert.equal(htmx.processCalls.length, 3, "htmx.process is invoked on each interval change");

dispatch(listeners, "htmx:sendError", { elt: element });
assert.equal(element.getAttribute("hx-trigger"), "load, every 30s", "network error triggers backoff");

dispatch(listeners, "htmx:afterRequest", { elt: element, successful: false });
dispatch(listeners, "htmx:afterRequest", { elt: element, successful: false });
dispatch(listeners, "htmx:afterRequest", { elt: element, successful: false });
dispatch(listeners, "htmx:afterRequest", { elt: element, successful: false });
assert.equal(
  element.getAttribute("hx-trigger"),
  "load, every 300s",
  "interval is capped at five minutes",
);

dispatch(listeners, "htmx:afterRequest", { elt: element, successful: true });
assert.equal(element.getAttribute("hx-trigger"), "load, every 15s", "success after cap resets the trigger");

console.log("polling-controller tests completed");
