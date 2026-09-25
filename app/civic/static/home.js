// Home page: load an example letter into the sheet, pick the office that wrote it, and show
// that office's promise (each office has its own rule, bound to its own key in the gateway).
(function () {
  const textarea = document.getElementById("letter");
  const service = document.querySelector("[data-service]");
  let chosen = null;
  let promiseMark = null;

  function showPromise(key, animate) {
    document.querySelectorAll("[data-promise-for]").forEach((p) => { p.hidden = p.dataset.promiseFor !== key; });
    if (promiseMark) window.unmark(promiseMark.el, promiseMark.a);
    const phrase = document.querySelector(`[data-promise-for="${key}"] [data-promise-key]`);
    if (!phrase) return;
    promiseMark = { el: phrase, a: null };
    setTimeout(() => { promiseMark.a = window.mark(phrase, "swiss", animate ? {} : { animate: false }); }, animate ? 250 : 0);
  }

  service.addEventListener("change", () => showPromise(service.value, true));

  document.querySelectorAll("[data-sample]").forEach((button) => {
    button.addEventListener("click", async () => {
      const response = await fetch(`/samples/${encodeURIComponent(button.dataset.sample)}`);
      if (!response.ok) return;
      textarea.value = await response.text();
      textarea.scrollTop = 0;
      if (button.dataset.sampleService && service.value !== button.dataset.sampleService) {
        service.value = button.dataset.sampleService;
        showPromise(service.value, true);
      }
      document.querySelectorAll("[data-sample]").forEach((b) => b.setAttribute("aria-pressed", "false"));
      button.setAttribute("aria-pressed", "true");
      if (chosen) window.unmark(chosen.el, chosen.a);
      const subject = button.querySelector(".example-subject");
      chosen = { el: subject, a: window.mark(subject, "chosen") };
    });
  });

  window.addEventListener("load", () => setTimeout(() => showPromise(service.value, true), 400));
})();
