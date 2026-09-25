// The letter page: polls /api/jobs/<id>/journey and updates the page in place.
// Only new stops of the journey are animated; deadlines are marked once, by hand.
(function () {
  const root = document.querySelector("[data-job]");
  if (!root) return;
  const id = root.dataset.job;
  const $ = (selector) => root.querySelector(selector);
  const journey = $("[data-journey]");
  const TERMINAL = ["done", "failed", "cancelled", "expired"];
  const seen = new Set();
  let firstRender = true;
  let answerShown = false;
  let promiseMark = null;
  let promiseText = "";
  let countdown = null;

  const el = (tag, cls, text) => {
    const node = document.createElement(tag);
    if (cls) node.className = cls;
    if (text != null) node.textContent = text;
    return node;
  };

  // --- technical details switch (remembered per browser) ---------------------------
  const techToggle = $("[data-tech-toggle]");
  try { techToggle.checked = localStorage.getItem("show-tech") === "1"; } catch (e) { /* storage blocked */ }
  const applyTech = () => {
    journey.dataset.tech = techToggle.checked ? "on" : "off";
    try { localStorage.setItem("show-tech", techToggle.checked ? "1" : "0"); } catch (e) { /* storage blocked */ }
  };
  techToggle.addEventListener("change", applyTech);
  applyTech();

  // --- journey ---------------------------------------------------------------------
  function stopNode(stop) {
    const li = el("li", `stop stop--${stop.kind}`);
    li.dataset.key = stop.key;
    li.append(el("span", "stop-dot"));
    const body = el("div", "stop-body");
    body.append(el("p", "stop-title", stop.title));
    if (stop.text) body.append(el("p", "stop-text", stop.text));
    if (stop.crossed && stop.crossed.length) {
      const list = el("ul", "stop-crossed");
      stop.crossed.forEach((c) => {
        const item = el("li");
        item.append("Not sent to ", el("span", "x", c.name), `, because ${c.reason}.`);
        list.append(item);
      });
      body.append(list);
    }
    if (stop.tech) body.append(el("p", "stop-tech", stop.tech));
    li.append(body, el("time", "stop-time", stop.time));
    return li;
  }

  const nodes = new Map();
  function renderJourney(stops, status) {
    const keys = new Set(stops.map((s) => s.key));
    nodes.forEach((li, key) => { if (!keys.has(key)) { li.remove(); nodes.delete(key); seen.delete(key); } });
    stops.forEach((stop) => {
      const li = nodes.get(stop.key);
      if (li && li.dataset.text !== (stop.text || "")) {
        li.dataset.text = stop.text || "";
        const text = li.querySelector(".stop-text") || li.querySelector(".stop-body").appendChild(el("p", "stop-text"));
        text.textContent = stop.text;
      }
    });
    stops.filter((s) => !seen.has(s.key)).forEach((stop, i) => {
      seen.add(stop.key);
      const li = stopNode(stop);
      li.dataset.text = stop.text || "";
      nodes.set(stop.key, li);
      const delay = firstRender ? Math.min(i, 14) * 80 : 0;
      li.style.setProperty("--delay", `${delay}ms`);
      li.classList.add("is-new");
      journey.append(li);
      setTimeout(() => li.classList.remove("is-new"), delay + 700);
      setTimeout(() => li.querySelectorAll(".x").forEach((x) => window.mark(x, "crossed")), delay + 420);
    });
    journey.querySelectorAll(".is-live").forEach((n) => n.classList.remove("is-live"));
    const last = journey.lastElementChild;
    if (status === "waiting" && last && last.classList.contains("stop--waiting")) last.classList.add("is-live");
    firstRender = false;
  }

  // --- header ------------------------------------------------------------------------
  const TITLES = {
    queued: "Reading your letter",
    running: "Reading your letter",
    waiting: "Your letter is waiting, safely",
    done: "Here is what your letter says",
    failed: "This did not work",
    cancelled: "You cancelled this letter",
    expired: "No Swiss service answered in time",
  };

  function promiseFor(receipt, status, service) {
    const ruled = receipt.ruled_out.length;
    const others = ruled === 1 ? "One other service was" : `${ruled} other services were`;
    const ruledText = ruled ? ` ${others} ruled out before anything was sent.` : "";
    const fallback = receipt.fallbacks_blocked.length
      ? ` That includes a backup model in ${receipt.fallbacks_blocked[0].places.join(" and ")}.`
      : "";
    if (!receipt.sent_to.length) {
      return status === "waiting"
        ? { lead: "It has not been sent anywhere yet. ", key: "It stays in Switzerland", rest: ` until a Swiss service can answer.${ruledText}${fallback}` }
        : { lead: "", key: "", rest: "" };
    }
    if (receipt.all_swiss) return { lead: "It went ", key: "only to services in Switzerland", rest: `.${ruledText}${fallback}` };
    const agreed = receipt.consented || [];
    const within = receipt.places.filter((p) => !agreed.includes(p));
    const withinText = within.length ? `services in ${within.join(" and ")}` : "";
    if (agreed.length) {
      return {
        lead: withinText ? `It went to ${withinText} and, because you agreed, ` : "Because you agreed, it went ",
        key: "", rest: `to a service in ${agreed.join(" and ")}.${ruledText}`,
      };
    }
    return { lead: "It went ", key: `only to ${withinText}`, rest: `, as ${service.owner_s} rule allows.${ruledText}${fallback}` };
  }

  // A new attempt after a wait is still part of the wait, for the resident.
  const shownStatus = (job) => (job.status === "running" && (job.runs || 0) >= 2 ? "waiting" : job.status);

  function renderHeader(data) {
    const status = shownStatus(data.job);
    root.dataset.status = status;
    $("[data-title]").textContent = TITLES[status] || "Your letter";
    const p = promiseFor(data.receipt, status, data.service);
    const text = p.lead + p.key + p.rest;
    if (text === promiseText) return;
    promiseText = text;
    const target = $("[data-promise]");
    if (promiseMark) window.unmark(promiseMark.el, promiseMark.a);
    target.textContent = p.lead;
    if (p.key) {
      const key = el("span", "swiss", p.key);
      target.append(key);
      promiseMark = { el: key, a: null };
      setTimeout(() => { promiseMark.a = window.mark(key, "swiss"); }, 300);
    }
    target.append(p.rest);
  }

  // --- left column -------------------------------------------------------------------
  function renderPending(data) {
    const { status_reason: reason, next_retry_at: nextAt } = data.job;
    const status = shownStatus(data.job);
    const pending = $("[data-pending]");
    const actions = $("[data-pending-actions]");
    clearInterval(countdown);
    if (status === "done") { pending.hidden = true; return; }
    pending.hidden = false;
    const title = $("[data-pending-title]");
    const text = $("[data-pending-text]");
    actions.hidden = status !== "waiting";
    const offer = $("[data-consent-offer]");
    const canAsk = (data.job.consent_options || []).includes("US") && !data.job.consent;
    offer.hidden = !(status === "waiting" && canAsk);
    if (status === "waiting") {
      title.textContent = data.service.allowed.includes("EU") ? "No service in Switzerland or the EU can answer right now." : "No Swiss service can answer right now.";
      const tick = () => {
        const s = nextAt ? Math.max(0, Math.round(nextAt - Date.now() / 1000)) : 0;
        text.textContent = `Your letter stays here and is not sent anywhere else. ${s > 0 ? `Next try in ${s} seconds.` : "Trying again now."}`;
      };
      tick();
      countdown = setInterval(tick, 1000);
    } else if (status === "queued" || status === "running") {
      title.textContent = "We are reading your letter with you.";
      text.textContent = "This usually takes less than a minute.";
    } else {
      title.textContent = TITLES[status];
      text.textContent = reason || "";
    }
  }

  function formatDate(iso, lang) {
    const d = new Date(`${iso}T12:00:00`);
    if (Number.isNaN(d.getTime())) return iso;
    try { return new Intl.DateTimeFormat(lang, { day: "numeric", month: "long", year: "numeric" }).format(d); }
    catch (e) { return iso; }
  }

  function renderAnswer(data) {
    const result = data.job.result;
    if (!result || answerShown) return;
    answerShown = true;
    const lang = data.job.language || "en";
    $("[data-simulated]").hidden = data.served_by_kind !== "simulated";
    $("[data-summary]").textContent = result.summary;
    const list = $("[data-actions]");
    const marks = [];
    result.actions.forEach((a) => {
      const li = el("li");
      li.append(el("span", "what", a.action));
      if (a.deadline) {
        const by = el("span", "by");
        const date = el("span", "date", formatDate(a.deadline, lang));
        by.append(date);
        li.append(by);
        marks.push([date, "deadline"]);
      }
      list.append(li);
    });
    $("[data-reply]").textContent = result.draft_reply;
    $("[data-answer]").hidden = false;
    setTimeout(() => window.markGroup(marks), 350);
  }

  // --- controls ----------------------------------------------------------------------
  root.querySelectorAll("[data-action]").forEach((button) => {
    button.addEventListener("click", async () => {
      button.disabled = true;
      await fetch(`/api/jobs/${id}/${button.dataset.action}`, { method: "POST" });
      button.disabled = false;
      poll();
    });
  });
  // --- consent: only offered when this office's rule allows it, and only while waiting ----
  const dialog = $("[data-consent-dialog]");
  const check = $("[data-consent-check]");
  const agree = $("[data-consent-agree]");
  $("[data-consent-open]").addEventListener("click", () => {
    check.checked = false;
    agree.disabled = true;
    dialog.showModal();
  });
  check.addEventListener("change", () => { agree.disabled = !check.checked; });
  dialog.addEventListener("close", async () => {
    if (dialog.returnValue !== "agree" || !check.checked) return;
    const statement = [...dialog.querySelectorAll("h2, li, .consent-check")].map((n) => n.textContent.trim()).join(" | ");
    const response = await fetch(`/api/jobs/${id}/consent`, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ jurisdictions: ["US"], statement }),
    });
    if (!response.ok) {
      const offer = $("[data-consent-offer]");
      offer.querySelector("p").textContent = "Your choice could not be recorded, so nothing was sent. The letter keeps waiting.";
    }
    poll();
  });

  const copy = $("[data-copy]");
  copy.addEventListener("click", async () => {
    try {
      await navigator.clipboard.writeText($("[data-reply]").textContent);
      copy.textContent = "Copied";
      setTimeout(() => { copy.textContent = "Copy the reply"; }, 2000);
    } catch (e) { copy.textContent = "Select the text to copy it"; }
  });

  // --- polling -----------------------------------------------------------------------
  let timer = null;
  async function poll() {
    clearTimeout(timer);
    try {
      const response = await fetch(`/api/jobs/${id}/journey`, { cache: "no-store" });
      if (response.ok) {
        const data = await response.json();
        renderHeader(data);
        renderPending(data);
        renderAnswer(data);
        renderJourney(data.stops, data.job.status);
      }
    } catch (e) { /* keep polling */ }
    timer = setTimeout(poll, TERMINAL.includes(root.dataset.status) ? 5000 : 1000);
  }
  poll();
})();
