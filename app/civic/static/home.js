// Home page: load an example letter into the sheet, pick the office that wrote it, and show
// that office's promise (each office has its own rule, bound to its own key in the gateway).
// "Upload a photo or PDF" is a mock: a .txt file is read in the browser, any other file fills
// in the matching example letter (by file name, else the chosen office's first example).
(function () {
  const textarea = document.getElementById("letter");
  const service = document.querySelector("[data-service]");
  const examples = [...document.querySelectorAll("[data-sample]")];
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

  async function loadExample(button) {
    const response = await fetch(`/samples/${encodeURIComponent(button.dataset.sample)}`);
    if (!response.ok) throw new Error(`sample ${response.status}`);
    textarea.value = await response.text();
    textarea.scrollTop = 0;
    if (button.dataset.sampleService && service.value !== button.dataset.sampleService) {
      service.value = button.dataset.sampleService;
      showPromise(service.value, true);
    }
  }

  examples.forEach((button) => {
    button.addEventListener("click", async () => {
      try { await loadExample(button); } catch (e) { return; }
      examples.forEach((b) => b.setAttribute("aria-pressed", "false"));
      button.setAttribute("aria-pressed", "true");
      if (chosen) window.unmark(chosen.el, chosen.a);
      const subject = button.querySelector(".example-subject");
      chosen = { el: subject, a: window.mark(subject, "chosen") };
    });
  });

  // --- upload (mock) -------------------------------------------------------------------
  const upload = document.querySelector("[data-upload]");
  const input = document.querySelector("[data-upload-input]");
  const note = document.querySelector("[data-upload-note]");
  const sheet = document.querySelector("[data-sheet]");
  const stem = (name) => name.toLowerCase().replace(/\.[^.]+$/, "");

  function exampleFor(file) {
    const name = stem(file.name);
    return examples.find((b) => stem(b.dataset.sample) === name || name.startsWith(b.dataset.sample.slice(0, 3)))
      || examples.find((b) => b.dataset.sampleService === service.value)
      || examples[0];
  }

  upload.addEventListener("click", () => input.click());
  input.addEventListener("change", async () => {
    const file = input.files[0];
    input.value = "";
    if (!file) return;
    note.hidden = false;
    note.textContent = t("home.upload_reading", { file: file.name });
    sheet.classList.add("is-reading");
    upload.disabled = true;
    const reading = new Promise((resolve) => setTimeout(resolve, 1400));
    try {
      if (file.type === "text/plain" || /\.txt$/i.test(file.name)) {
        const text = (await file.text()).slice(0, 20000);
        await reading;
        textarea.value = text;
        note.textContent = t("home.upload_text", { file: file.name });
      } else {
        const example = exampleFor(file);
        if (!example) throw new Error("no example letters");
        await reading;
        await loadExample(example);
        note.textContent = t("home.upload_simulated", { subject: example.querySelector(".example-subject").textContent.trim() });
      }
      textarea.scrollTop = 0;
    } catch (e) {
      note.textContent = t("home.upload_failed");
    }
    sheet.classList.remove("is-reading");
    upload.disabled = false;
  });

  window.addEventListener("load", () => setTimeout(() => showPromise(service.value, true), 400));
})();
