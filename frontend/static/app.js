import { h } from "preact";
import { render } from "preact";
import { useEffect, useState } from "preact/hooks";

const LIVE_ENDPOINT = "/live";

function fetchStatus(signal) {
  return fetch(LIVE_ENDPOINT, { signal })
    .then(async (response) => {
      if (!response.ok) {
        const text = await response.text();
        throw new Error(`Unexpected status ${response.status}: ${text}`);
      }
      return response.json();
    })
    .catch((error) => {
      throw new Error(`Failed to load service status: ${error.message}`);
    });
}

function App() {
  const [status, setStatus] = useState({ state: "loading" });

  useEffect(() => {
    const controller = new AbortController();
    fetchStatus(controller.signal)
      .then((payload) => {
        setStatus({ state: "ready", payload });
      })
      .catch((error) => {
        setStatus({ state: "error", message: error.message });
      });

    return () => controller.abort();
  }, []);

  if (status.state === "loading") {
    return h("main", { class: "app" }, h("p", null, "Loading Harmony…"));
  }

  if (status.state === "error") {
    return h(
      "main",
      { class: "app app--error" },
      h("h1", null, "Harmony"),
      h("p", null, status.message),
      h(
        "button",
        {
          type: "button",
          class: "reload-button",
          onClick: () => window.location.reload(),
        },
        "Retry"
      )
    );
  }

  return h(
    "main",
    { class: "app" },
    h("header", { class: "app__header" }, h("h1", null, "Harmony")),
    h(
      "section",
      { class: "app__section" },
      h("h2", null, "Service Status"),
      h(
        "dl",
        { class: "status-list" },
        h("div", null, h("dt", null, "State"), h("dd", null, status.payload.status)),
        h(
          "div",
          null,
          h("dt", null, "Version"),
          h("dd", null, status.payload.version || "unknown")
        )
      )
    ),
    h(
      "footer",
      { class: "app__footer" },
      h("p", null, "This frontend is served without a build step.")
    )
  );
}

const root = document.getElementById("root");
if (!root) {
  throw new Error("Root element not found");
}

render(h(App, null), root);
