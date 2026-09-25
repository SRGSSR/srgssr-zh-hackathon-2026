// Demo controls: break and repair services, and watch what each one received.
(function () {
  const drawer = document.getElementById("demo-drawer");
  const toggle = document.querySelector(".demo-toggle");
  const onDemoPage = document.body.classList.contains("page-demo");
  const MODES = [["up", "Working"], ["down", "Broken"], ["timeout", "Hangs"]];
  const lastCount = {};
  let timer = null;

  function open() {
    drawer.hidden = false;
    requestAnimationFrame(() => drawer.classList.add("is-open"));
    toggle.setAttribute("aria-expanded", "true");
    start();
  }
  function close() {
    drawer.classList.remove("is-open");
    toggle.setAttribute("aria-expanded", "false");
    setTimeout(() => { drawer.hidden = true; }, 280);
    if (!onDemoPage) stop();
    toggle.focus();
  }
  toggle.addEventListener("click", () => (drawer.classList.contains("is-open") ? close() : open()));
  drawer.querySelector(".drawer-close").addEventListener("click", close);
  document.addEventListener("keydown", (e) => { if (e.key === "Escape" && drawer.classList.contains("is-open")) close(); });

  function row(ep) {
    const node = document.createElement("div");
    node.className = `ep ep--${ep.reach || (ep.approved ? "all" : "never")}`;
    node.dataset.id = ep.id;
    node.innerHTML = `
      <div class="ep-name"></div>
      <div class="ep-why"></div>
      <div class="ep-count"><span class="num">0</span><span class="lbl">received</span></div>
      <div class="ep-modes" role="group"></div>`;
    const name = node.querySelector(".ep-name");
    name.textContent = ep.name;
    const kind = document.createElement("span");
    kind.className = `kind kind--${ep.kind}`;
    kind.textContent = ep.kind === "real" ? "real" : "simulated";
    name.append(kind);
    node.querySelector(".ep-why").textContent = ep.why;
    const modes = node.querySelector(".ep-modes");
    modes.setAttribute("aria-label", `State of ${ep.name}`);
    MODES.forEach(([mode, label]) => {
      const b = document.createElement("button");
      b.type = "button";
      b.dataset.mode = mode;
      b.textContent = label;
      b.addEventListener("click", async () => {
        await fetch(`/demo/endpoint/${encodeURIComponent(ep.id)}/${mode}`, { method: "POST" });
        refresh();
      });
      modes.append(b);
    });
    return node;
  }

  function render(container, endpoints) {
    endpoints.forEach((ep) => {
      let node = container.querySelector(`[data-id="${CSS.escape(ep.id)}"]`);
      if (!node) { node = row(ep); container.append(node); }
      const received = ep.state && ep.state.received != null ? ep.state.received : "?";
      const count = node.querySelector(".ep-count");
      const num = count.querySelector(".num");
      if (num.textContent !== String(received)) {
        num.textContent = received;
        if ((container.dataset.seen || "") === "1" && lastCount[ep.id] !== undefined && lastCount[ep.id] !== received) {
          count.classList.remove("bump");
          void count.offsetWidth;
          count.classList.add("bump");
        }
      }
      lastCount[ep.id] = received;
      const mode = ep.state ? ep.state.mode : "unreachable";
      node.querySelectorAll(".ep-modes button").forEach((b) => b.setAttribute("aria-pressed", String(b.dataset.mode === mode)));
    });
    container.dataset.seen = "1";
  }

  async function refresh() {
    try {
      const response = await fetch("/api/endpoints", { cache: "no-store" });
      if (!response.ok) return;
      const endpoints = await response.json();
      document.querySelectorAll("[data-endpoints]").forEach((c) => render(c, endpoints));
    } catch (e) { /* retry on next tick */ }
  }
  function start() { refresh(); clearInterval(timer); timer = setInterval(refresh, 1500); }
  function stop() { clearInterval(timer); }

  document.querySelectorAll("[data-bulk]").forEach((button) => {
    button.addEventListener("click", async () => {
      await fetch(`/demo/${button.dataset.bulk}`, { method: "POST" });
      refresh();
    });
  });

  if (onDemoPage) start();
})();
