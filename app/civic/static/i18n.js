// The page's strings for the scripts, rendered by the server into #i18n (see app/civic/i18n.py).
(function () {
  let strings = {};
  try { strings = JSON.parse(document.getElementById("i18n").textContent); } catch (e) { /* show keys */ }

  // t("common.next_try", { n: 3 }) -> "Next try in 3 seconds."
  window.t = function (key, values) {
    const s = strings[key] != null ? strings[key] : key;
    return values ? s.replace(/\{(\w+)\}/g, (m, name) => (values[name] != null ? values[name] : m)) : s;
  };
  // "a [[b]] c" -> { before: "a ", mark: "b", after: " c" }
  window.tParts = function (key, values) {
    const s = window.t(key, values);
    const open = s.indexOf("[["), close = s.indexOf("]]", open);
    if (open < 0 || close < 0) return { before: s, mark: "", after: "" };
    return { before: s.slice(0, open), mark: s.slice(open + 2, close), after: s.slice(close + 2) };
  };
  window.tJoin = function (items) {
    const list = items.filter(Boolean);
    return list.length < 2 ? list.join("") : list.slice(0, -1).join(", ") + window.t("common.and") + list[list.length - 1];
  };
})();
