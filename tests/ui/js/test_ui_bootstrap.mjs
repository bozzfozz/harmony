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

function createBootstrapContext(token = "csrf-token-value") {
  const documentListeners = Object.create(null);

  const body = {
    dataset: {
      liveUpdates: "disabled",
    },
    addEventListener() {},
    removeEventListener() {},
  };

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
    querySelectorAll() {
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

  const htmx = {};

  const window = {
    document,
    htmx,
    EventSource: null,
    addEventListener() {},
  };
  window.window = window;

  const context = {
    window,
    document,
    console,
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

console.log("ui-bootstrap tests completed");
