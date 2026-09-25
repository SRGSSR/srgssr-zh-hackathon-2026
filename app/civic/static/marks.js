// Hand-drawn marks (rough-notation), shared by the pages. One place for the style of the "pen".
(function () {
  const reduce = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  const css = getComputedStyle(document.documentElement);
  const color = (name) => css.getPropertyValue(name).trim();

  const styles = {
    deadline: () => ({ type: "highlight", color: color("--marker"), multiline: true, iterations: 1, animationDuration: 700 }),
    crossed: () => ({ type: "strike-through", color: color("--cross"), strokeWidth: 2, iterations: 1, animationDuration: 450 }),
    swiss: () => ({ type: "underline", color: color("--swiss"), strokeWidth: 2.5, iterations: 1, padding: 2, multiline: true, animationDuration: 600 }),
    chosen: () => ({ type: "bracket", color: color("--pen"), brackets: ["left"], strokeWidth: 2, padding: [2, 8], animationDuration: 400 }),
  };

  // mark(element, "deadline" | "crossed" | "swiss" | "chosen") -> annotation or null
  window.mark = function (el, style, opts) {
    if (!el || !window.RoughNotation || el.dataset.marked) return null;
    el.dataset.marked = "1";
    const a = window.RoughNotation.annotate(el, { ...styles[style](), animate: !reduce, ...(opts || {}) });
    a.show();
    return a;
  };
  window.unmark = function (el, annotation) {
    if (annotation) annotation.remove();
    if (el) delete el.dataset.marked;
  };
  window.markGroup = function (items) {
    if (!window.RoughNotation || !items.length) return;
    const list = items.filter(([el]) => el && !el.dataset.marked).map(([el, style]) => {
      el.dataset.marked = "1";
      return window.RoughNotation.annotate(el, { ...styles[style](), animate: !reduce });
    });
    if (list.length) window.RoughNotation.annotationGroup(list).show();
  };
})();
