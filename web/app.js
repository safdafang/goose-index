// Goose Package Index: search, filters and pages over the cards the page already holds,
// and copy buttons. Without JavaScript every page still lists every entry.
(function () {
  "use strict";

  // ------------------------------------------------------------ copy buttons
  document.addEventListener("click", (ev) => {
    const b = ev.target.closest(".copy");
    if (!b || !navigator.clipboard) return;
    const label = b.querySelector("span:not(.sr)");
    const was = label ? label.textContent : "";
    navigator.clipboard.writeText(b.dataset.copy).then(() => {
      b.classList.add("done");
      if (label) label.textContent = "Copied!";
      setTimeout(() => { b.classList.remove("done"); if (label) label.textContent = was; }, 1600);
    }, () => {});
  });

  // ------------------------------------------------------------ compatibility page filter
  const cq = document.getElementById("cq");
  if (cq) cq.addEventListener("input", () => {
    const words = cq.value.toLowerCase().split(/\s+/).filter(Boolean);
    document.querySelectorAll("#matrix tbody tr").forEach((tr) => {
      tr.hidden = !words.every((w) => tr.dataset.text.includes(w));
    });
  });

  // ------------------------------------------------------------ the index
  const list = document.getElementById("cards");
  const q = document.getElementById("q");
  if (!list || !q) return;
  const original = Array.from(list.children);
  const per = +list.dataset.perPage || 18;
  const os = document.getElementById("os");
  const tagged = document.getElementById("tagged");
  const licensed = document.getElementById("licensed");
  const count = document.getElementById("count");
  const empty = document.getElementById("empty");
  const emptyWhat = document.getElementById("empty-what");
  const pager = document.getElementById("pager");
  const board = document.getElementById("index");
  const cats = document.querySelector(".cats");
  let page = 1;

  const radio = (name) => (document.querySelector(`input[name="${name}"]:checked`) || {}).value || "";
  const setRadio = (name, v) => {
    const el = document.querySelector(`input[name="${name}"][value="${CSS.escape(v)}"]`) ||
               document.querySelector(`input[name="${name}"][value=""]`) ||
               document.querySelector(`input[name="${name}"]`);
    if (el) el.checked = true;
  };

  function score(c, words) {
    if (!words.length) return 1;
    let s = 0;
    for (const w of words) {
      if (!c.dataset.text.includes(w)) return 0;
      if (c.dataset.name === w || c.dataset.id === w) s += 12;
      else if (c.dataset.name.includes(w)) s += 6;
      else s += 1;
    }
    return s;
  }

  function apply(push) {
    const words = q.value.toLowerCase().split(/\s+/).filter(Boolean);
    const kind = radio("kind"), cat = radio("cat"), by = radio("sort") || "relevance";
    const shown = [];
    for (const c of original) {
      const d = c.dataset;
      let s = score(c, words);
      if (s && kind && d.kind !== kind) s = 0;
      if (s && cat && d.cat !== cat) s = 0;
      if (s && os.value && d["c-" + os.value] !== "pass") s = 0;
      if (s && tagged.checked && d.tagged !== "1") s = 0;
      if (s && licensed.checked && d.licensed !== "1") s = 0;
      if (c.hidden !== !s) c.hidden = !s;
      if (s) shown.push([s, c]);
    }
    if (by === "relevance" && words.length) shown.sort((a, b) => b[0] - a[0]);
    else if (by === "updated") shown.sort((a, b) => (b[1].dataset.updated || "").localeCompare(a[1].dataset.updated || ""));
    else if (by === "stars") shown.sort((a, b) => b[1].dataset.stars - a[1].dataset.stars);
    else if (by === "name") shown.sort((a, b) => a[1].dataset.name.localeCompare(b[1].dataset.name));
    else shown.sort((a, b) => original.indexOf(a[1]) - original.indexOf(b[1]));

    const pages = Math.max(1, Math.ceil(shown.length / per));
    page = Math.min(Math.max(1, page), pages);
    shown.forEach(([, c], i) => c.classList.toggle("off", i < (page - 1) * per || i >= page * per));
    // Only this page's cards are displayed, so only their order in the DOM matters (it is also the
    // tab order). Move them only when they are out of order: a move is costly, since every moved
    // card's icons are rebuilt. Hidden and off-page cards stay wherever they are.
    const want = shown.slice((page - 1) * per, page * per).map(([, c]) => c);
    const have = Array.prototype.filter.call(list.children, (c) => !c.hidden && !c.classList.contains("off"));
    if (want.some((c, i) => have[i] !== c)) {
      const frag = document.createDocumentFragment();
      want.forEach((c) => frag.appendChild(c));
      list.appendChild(frag);
    }
    stones(pages);

    setText(count, shown.length === original.length ? original.length + " entries" : shown.length + " of " + original.length);
    empty.hidden = shown.length > 0;
    list.hidden = shown.length === 0;
    if (!shown.length) setText(emptyWhat, words.length ? `No entries found for '${q.value.trim()}'` : "No entries match these filters");
    document.body.classList.toggle("searching", words.length > 0);
    if (push) save();
  }

  // writing the same text again still repaints, so skip it
  function setText(el, text) { if (el.textContent !== text) el.textContent = text; }

  let drawn = "";
  function stones(pages) {
    if (drawn === pages + "/" + page) return; // the stones already show this
    drawn = pages + "/" + page;
    pager.hidden = pages < 2;
    pager.textContent = "";
    if (pages < 2) return;
    const want = new Set([1, pages, page - 1, page, page + 1]);
    let last = 0;
    for (let n = 1; n <= pages; n++) {
      if (!want.has(n)) continue;
      if (n - last > 1) { const s = document.createElement("span"); s.textContent = "…"; pager.appendChild(s); }
      const b = document.createElement("button");
      b.type = "button"; b.textContent = n; b.dataset.page = n;
      b.setAttribute("aria-label", "Page " + n);
      if (n === page) b.setAttribute("aria-current", "page");
      pager.appendChild(b);
      last = n;
    }
  }
  pager.addEventListener("click", (ev) => {
    const b = ev.target.closest("button[data-page]");
    if (!b) return;
    page = +b.dataset.page;
    apply(true);
    board.scrollIntoView({ behavior: matchMedia("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth", block: "start" });
  });

  function save() {
    const p = new URLSearchParams();
    if (q.value) p.set("q", q.value);
    const kind = radio("kind"), cat = radio("cat"), by = radio("sort");
    if (kind) p.set("kind", kind);
    if (cat) p.set("cat", cat);
    if (os.value) p.set("os", os.value);
    if (by && by !== "relevance") p.set("sort", by);
    if (tagged.checked) p.set("tagged", "1");
    if (licensed.checked) p.set("licensed", "1");
    if (page > 1) p.set("page", page);
    const s = p.toString();
    history.replaceState(null, "", (s ? "?" + s : location.pathname) + location.hash);
  }

  function load() {
    const p = new URLSearchParams(location.search);
    q.value = p.get("q") || "";
    setRadio("kind", p.get("kind") || "");
    setRadio("cat", p.get("cat") || "");
    setRadio("sort", p.get("sort") || "relevance");
    os.value = p.get("os") || "";
    tagged.checked = p.get("tagged") === "1";
    licensed.checked = p.get("licensed") === "1";
    page = +p.get("page") || 1;
    if (p.get("cat") && cats) cats.open = true;
  }

  document.querySelector(".filters").addEventListener("change", () => { page = 1; apply(true); });
  let t;
  q.addEventListener("input", () => { clearTimeout(t); t = setTimeout(() => { page = 1; apply(true); }, 60); });
  q.form.addEventListener("submit", (ev) => {
    ev.preventDefault();
    page = 1; apply(true);
    board.scrollIntoView({ behavior: "smooth", block: "start" });
  });
  document.addEventListener("keydown", (ev) => {
    if (ev.key === "/" && document.activeElement !== q && !/INPUT|SELECT|TEXTAREA/.test(document.activeElement.tagName)) {
      ev.preventDefault(); q.focus();
    }
  });
  load();
  apply(false);
})();
