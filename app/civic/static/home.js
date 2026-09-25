// Home page: load an example letter into the sheet, and draw the promise once.
(function () {
  const textarea = document.getElementById("letter");
  let chosen = null;

  document.querySelectorAll("[data-sample]").forEach((button) => {
    button.addEventListener("click", async () => {
      const response = await fetch(`/samples/${encodeURIComponent(button.dataset.sample)}`);
      if (!response.ok) return;
      textarea.value = await response.text();
      textarea.scrollTop = 0;
      document.querySelectorAll("[data-sample]").forEach((b) => b.setAttribute("aria-pressed", "false"));
      button.setAttribute("aria-pressed", "true");
      if (chosen) window.unmark(chosen.el, chosen.a);
      const subject = button.querySelector(".example-subject");
      chosen = { el: subject, a: window.mark(subject, "chosen") };
    });
  });

  window.addEventListener("load", () => {
    const key = document.querySelector("[data-promise-key]");
    setTimeout(() => window.mark(key, "swiss"), 500);
  });
})();
