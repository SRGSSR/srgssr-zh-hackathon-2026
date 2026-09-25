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
        const p = tParts("journey.not_sent_to", { name: c.name, reason: c.reason });
        item.append(p.before, el("span", "x", p.mark), p.after);
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
  const TITLE_KEYS = {
    queued: "job.title.reading",
    running: "job.title.reading",
    waiting: "job.title.waiting",
    done: "job.title.done",
    failed: "job.title.failed",
    cancelled: "job.title.cancelled",
    expired: "job.title.expired",
  };
  const title = (status) => (TITLE_KEYS[status] ? t(TITLE_KEYS[status]) : t("job.page_title"));

  // The sentence under the title: where the letter went, with its key phrase underlined.
  function promiseFor(receipt, status, service) {
    const ruled = receipt.ruled_out.length;
    const ruledText = ruled ? " " + (ruled === 1 ? t("job.ruled_one") : t("job.ruled_many", { n: ruled })) : "";
    const fallback = receipt.fallbacks_blocked.length
      ? " " + t("job.fallback_blocked", { where: tJoin(receipt.fallbacks_blocked[0].places) })
      : "";
    const withRest = (p, extra) => ({ lead: p.before, key: p.mark, rest: p.after + extra });
    if (!receipt.sent_to.length) {
      return status === "waiting" ? withRest(tParts("job.not_sent_yet"), ruledText + fallback) : { lead: "", key: "", rest: "" };
    }
    if (receipt.all_swiss) return withRest(tParts("job.went_swiss"), ruledText + fallback);
    const agreed = receipt.consented || [];
    const within = receipt.places.filter((p) => !agreed.includes(p));
    if (agreed.length) {
      const text = within.length
        ? t("job.went_consent", { where: tJoin(within), agreed: tJoin(agreed) })
        : t("job.went_consent_only", { agreed: tJoin(agreed) });
      return { lead: text + ruledText, key: "", rest: "" };
    }
    return withRest(tParts("job.went_within", { where: tJoin(within), allows: service.allows }), ruledText + fallback);
  }

  // A new attempt after a wait is still part of the wait, for the resident.
  const shownStatus = (job) => (job.status === "running" && (job.runs || 0) >= 2 ? "waiting" : job.status);

  function renderHeader(data) {
    const status = shownStatus(data.job);
    root.dataset.status = status;
    $("[data-title]").textContent = title(status);
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
    const heading = $("[data-pending-title]");
    const text = $("[data-pending-text]");
    actions.hidden = status !== "waiting";
    const offer = $("[data-consent-offer]");
    const canAsk = (data.job.consent_options || []).includes("US") && !data.job.consent;
    offer.hidden = !(status === "waiting" && canAsk);
    if (status === "waiting") {
      heading.textContent = data.service.allowed.includes("EU") ? t("job.wait_title_eu") : t("job.wait_title_ch");
      const tick = () => {
        const s = nextAt ? Math.max(0, Math.round(nextAt - Date.now() / 1000)) : 0;
        text.textContent = `${t("job.wait_text")} ${s > 0 ? t("common.next_try", { n: s }) : t("job.trying_now")}`;
      };
      tick();
      countdown = setInterval(tick, 1000);
    } else if (status === "queued" || status === "running") {
      heading.textContent = t("job.pending_title");
      text.textContent = t("job.pending_text");
    } else {
      heading.textContent = title(status);
      text.textContent = reason || "";
    }
  }

  function formatDate(iso, lang) {
    const d = new Date(`${iso}T12:00:00`);
    if (Number.isNaN(d.getTime())) return iso;
    const locale = { gsw: "de-CH", de: "de-CH", fr: "fr-CH", it: "it-CH", rm: "rm-CH" }[lang] || lang;
    try { return new Intl.DateTimeFormat(locale, { day: "numeric", month: "long", year: "numeric" }).format(d); }
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
      offer.querySelector("p").textContent = t("job.consent_error");
    }
    poll();
  });

  const copy = $("[data-copy]");
  copy.addEventListener("click", async () => {
    try {
      await navigator.clipboard.writeText($("[data-reply]").textContent);
      copy.textContent = t("job.copied");
      setTimeout(() => { copy.textContent = t("job.copy"); }, 2000);
    } catch (e) { copy.textContent = t("job.copy_manual"); }
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
