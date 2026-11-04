// Goose Package Index: search, filters and pages over the cards the page already holds,
// copy buttons, the to-do notes and the goose. Without JavaScript every page still lists every entry.
(function () {
  "use strict";

  // ------------------------------------------------------------ to-do notes
  // Items tick themselves off as you do them (copy a line, open a repository, honk); the list is
  // remembered per browser, so a done thing stays done on every page.
  const KEY = "goose-index-todo";
  let done = {};
  try { done = JSON.parse(localStorage.getItem(KEY) || "{}") || {}; } catch (e) {}
  function paint() {
    document.querySelectorAll(".todo-item").forEach((b) => {
      const on = b.hasAttribute("data-auto") || !!done[b.dataset.todo];
      b.classList.toggle("done", on);
      b.setAttribute("aria-pressed", String(on));
    });
  }
  function tick(key, on) {
    done[key] = on === undefined ? true : on;
    try { localStorage.setItem(KEY, JSON.stringify(done)); } catch (e) {}
    paint();
  }
  paint();

  // ------------------------------------------------------------ the goose
  let audio;
  function honkSound() {
    try {
      const A = window.AudioContext || window.webkitAudioContext;
      if (!A) return;
      audio = audio || new A();
      const t = audio.currentTime;
      const out = audio.createGain();
      out.gain.setValueAtTime(0.0001, t);
      out.gain.exponentialRampToValueAtTime(0.22, t + 0.03);
      out.gain.exponentialRampToValueAtTime(0.0001, t + 0.34);
      const band = audio.createBiquadFilter();
      band.type = "bandpass"; band.frequency.value = 1150; band.Q.value = 2.2;
      band.connect(out); out.connect(audio.destination);
      [["sawtooth", 1], ["square", 1.012]].forEach(([type, k]) => {
        const o = audio.createOscillator();
        o.type = type;
        o.frequency.setValueAtTime(430 * k, t);
        o.frequency.exponentialRampToValueAtTime(330 * k, t + 0.3);
        o.connect(band); o.start(t); o.stop(t + 0.36);
      });
    } catch (e) {}
  }
  document.addEventListener("click", (ev) => {
    const g = ev.target.closest(".goose");
    if (!g) return;
    g.classList.remove("honking");
    void g.offsetWidth; // restart the animation
    g.classList.add("honking");
    setTimeout(() => g.classList.remove("honking"), 600);
    honkSound();
    tick("honk");
  });

  // ------------------------------------------------------------ copy buttons and links that tick items
  document.addEventListener("click", (ev) => {
    const item = ev.target.closest(".todo-item");
    if (item && !item.hasAttribute("data-auto")) tick(item.dataset.todo, !done[item.dataset.todo]);
    const hit = ev.target.closest("[data-todo-hit]");
    if (hit) tick(hit.dataset.todoHit);
    const b = ev.target.closest(".copy");
    if (!b || !navigator.clipboard) return;
    const label = b.querySelector("span:not(.sr)");
    const was = label ? label.textContent : "";
    navigator.clipboard.writeText(b.dataset.copy).then(() => {
      b.classList.add("done");
      if (label) label.textContent = "Copied!";
      tick("copy");
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
      c.hidden = !s;
      if (s) shown.push([s, c]);
    }
    if (by === "relevance" && words.length) shown.sort((a, b) => b[0] - a[0]);
    else if (by === "updated") shown.sort((a, b) => (b[1].dataset.updated || "").localeCompare(a[1].dataset.updated || ""));
    else if (by === "stars") shown.sort((a, b) => b[1].dataset.stars - a[1].dataset.stars);
    else if (by === "name") shown.sort((a, b) => a[1].dataset.name.localeCompare(b[1].dataset.name));
    else shown.sort((a, b) => original.indexOf(a[1]) - original.indexOf(b[1]));

    const pages = Math.max(1, Math.ceil(shown.length / per));
    page = Math.min(Math.max(1, page), pages);
    const frag = document.createDocumentFragment();
    shown.forEach(([, c], i) => {
      c.classList.toggle("off", i < (page - 1) * per || i >= page * per);
      frag.appendChild(c);
    });
    original.filter((c) => c.hidden).forEach((c) => frag.appendChild(c));
    list.appendChild(frag);
    stones(pages);

    count.textContent = shown.length === original.length ? original.length + " entries" : shown.length + " of " + original.length;
    empty.hidden = shown.length > 0;
    list.hidden = shown.length === 0;
    if (!shown.length) emptyWhat.textContent = words.length ? `No entries found for '${q.value.trim()}'` : "No entries match these filters";
    document.body.classList.toggle("searching", words.length > 0);
    if (push) save();
  }

  function stones(pages) {
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
