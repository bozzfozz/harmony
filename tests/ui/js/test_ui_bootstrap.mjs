import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import vm from "node:vm";
import url from "node:url";

const __dirname = path.dirname(url.fileURLToPath(import.meta.url));
const bootstrapPath = path.resolve(
  __dirname,
  "../../..",
  "app/ui/static/js/ui-bootstrap.js",
);
const bootstrapSource = fs.readFileSync(bootstrapPath, "utf8");

function createBootstrapContext(token = "csrf-token-value", options = {}) {
  const documentListeners = Object.create(null);

  const body = {
    dataset: {
      liveUpdates: "disabled",
      ...(options.bodyDataset || {}),
    },
    addEventListener() {},
    removeEventListener() {},
  };

  const fallbackFragments = options.liveFragments || [];

  const meta = {
    getAttribute(name) {
      if (name === "content") {
        return token;
      }
      return null;
    },
  };

  const document = {
    body,
    addEventListener(type, handler) {
      documentListeners[type] = handler;
    },
    removeEventListener() {},
    querySelector(selector) {
      if (selector === 'meta[name="csrf-token"]') {
        return meta;
      }
      return null;
    },
    querySelectorAll(selector) {
      if (selector === "[data-live-event]") {
        return fallbackFragments;
      }
      return [];
    },
    getElementById() {
      return null;
    },
    createElement() {
      const attributes = Object.create(null);
      return {
        attributes,
        dataset: Object.create(null),
        parentNode: null,
        setAttribute(name, value) {
          attributes[name] = value;
        },
        removeAttribute(name) {
          delete attributes[name];
        },
        appendChild(child) {
          if (child && typeof child === "object") {
            child.parentNode = this;
          }
        },
      };
    },
  };

  const htmx = options.htmx || {};

  const window = {
    document,
    htmx,
    EventSource:
      Object.prototype.hasOwnProperty.call(options, "EventSource")
        ? options.EventSource
        : null,
    addEventListener() {},
    __harmonyPollingController: options.pollingController || null,
  };
  window.window = window;
  window.console = options.console || console;

  const context = {
    window,
    document,
    console: window.console,
    globalThis: window,
    htmx,
  };

  vm.createContext(context);
  vm.runInContext(bootstrapSource, context, { filename: "ui-bootstrap.js" });

  return { body, documentListeners };
}

const token = "secure-csrf-token";
const { body, documentListeners } = createBootstrapContext(token);

assert.equal(body.dataset.csrfToken, token, "body dataset stores CSRF token");

const configHandler = documentListeners["htmx:configRequest"];
assert.equal(typeof configHandler, "function", "configRequest handler registered");

const eventDetail = { headers: {} };
configHandler({ type: "htmx:configRequest", detail: eventDetail });
assert.equal(
  eventDetail.headers["X-CSRF-Token"],
  token,
  "CSRF token header is injected",
);

const downgradeLogs = [];
const htmxProcessCalls = [];
const pollingController = {
  rescanRequested: false,
  _scheduleRescan() {
    this.rescanRequested = true;
  },
};

const fragmentElement = {
  attributes: { "hx-trigger": "revealed" },
  dataset: { liveEvent: "watchlist" },
  getAttribute(name) {
    return this.attributes[name] || null;
  },
  setAttribute(name, value) {
    this.attributes[name] = value;
  },
};

const {
  body: sseBody,
  documentListeners: sseListeners,
} = createBootstrapContext(token, {
  bodyDataset: { liveUpdates: "sse" },
  liveFragments: [fragmentElement],
  htmx: {
    process(element) {
      htmxProcessCalls.push(element);
    },
  },
  pollingController,
  console: {
    info(message, details) {
      downgradeLogs.push({ message, details });
    },
    warn() {},
  },
});

void sseListeners; // ensure eslint-like tools treat as used when linting.

assert.equal(
  sseBody.dataset.liveUpdates,
  "polling",
  "fallback switches body dataset to polling",
);
assert.equal(
  fragmentElement.getAttribute("hx-trigger"),
  "revealed, every 30s",
  "fragment trigger restored to polling interval",
);
assert.equal(
  fragmentElement.dataset.livePollingInterval,
  "30",
  "polling interval stored on fragment dataset",
);
assert.equal(
  htmxProcessCalls.includes(sseBody),
  true,
  "htmx.process invoked for fallback",
);
assert.equal(
  pollingController.rescanRequested,
  true,
  "polling controller rescan requested",
);
assert.equal(downgradeLogs.length > 0, true, "downgrade emits console log");
assert.equal(
  downgradeLogs[0].message,
  "ui.live_updates.fallback",
  "log message uses expected name",
);
assert.equal(
  downgradeLogs[0].details.reason,
  "unsupported",
  "log includes downgrade reason",
);

console.log("ui-bootstrap tests completed");
