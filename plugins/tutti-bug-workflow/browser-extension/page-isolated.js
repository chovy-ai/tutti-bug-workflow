// Isolated-world relay between the page script (private MessageChannel) and the
// extension background (runtime port). Reconnects when the service worker restarts.
(() => {
  const MARK = "__tuttiWebBridge";
  let pagePort = null;
  let background = null;
  let lastTools = [];

  function connectBackground() {
    background = chrome.runtime.connect({ name: "tutti-page" });
    background.onMessage.addListener((message) => pagePort?.postMessage(message));
    background.onDisconnect.addListener(() => {
      background = null;
      setTimeout(connectBackground, 1000);
    });
    background.postMessage({ type: "tools", tools: lastTools });
  }

  function toBackground(message) {
    if (message?.type === "tools") lastTools = message.tools;
    try {
      background?.postMessage(message);
    } catch {
      // Port died between checks; onDisconnect reconnects and resends tools.
    }
  }

  window.addEventListener("message", (event) => {
    if (event.source !== window) return;
    const mark = event.data?.[MARK];
    if (mark === "main-ready" && !pagePort) {
      window.postMessage({ [MARK]: "ready" }, location.origin);
    } else if (mark === "port" && !pagePort && event.ports[0]) {
      pagePort = event.ports[0];
      pagePort.onmessage = (portEvent) => toBackground(portEvent.data);
    }
  });
  window.postMessage({ [MARK]: "ready" }, location.origin);

  connectBackground();
  // Keeps the service worker (and its native host connection) awake while a Tutti page is open.
  setInterval(() => toBackground({ type: "ping" }), 20000);
})();
