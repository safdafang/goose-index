// Goose Package Index: search and filters over the cards the page already holds.
// Without JavaScript every page still lists every entry.
(function () {
  "use strict";

  // theme toggle, remembered per browser
  const themeBtn = document.querySelector(".theme");
  if (themeBtn) themeBtn.addEventListener("click", () => {
    const root = document.documentElement;
    const dark = root.dataset.theme ? root.dataset.theme === "dark" : matchMedia("(prefers-color-scheme: dark)").matches;
    root.dataset.theme = dark ? "light" : "dark";
    try { localStorage.setItem("theme", root.dataset.theme); } catch (e) {}
  });

  // copy buttons
  document.addEventListener("click", (ev) => {
    const b = ev.target.closest(".copy");
    if (!b) return;
    const done = () => { b.textContent = "Copied"; b.classList.add("done"); setTimeout(() => { b.textContent = "Copy"; b.classList.remove("done"); }, 1600); };
    if (navigator.clipboard) navigator.clipboard.writeText(b.dataset.copy).then(done, () => {});
  });

  // compatibility page filter
  const cq = document.getElementById("cq");
  if (cq) cq.addEventListener("input", () => {
    const words = cq.value.toLowerCase().split(/\s+/).filter(Boolean);
    document.querySelectorAll("#matrix tbody tr").forEach((tr) => {
      tr.hidden = !words.every((w) => tr.dataset.text.includes(w));
    });
  });

  const list = document.getElementById("cards");
  const q = document.getElementById("q");
  if (!list || !q) return;
  const original = Array.from(list.children);
  const sort = document.getElementById("sort");
  const os = document.getElementById("os");
  const tagged = document.getElementById("tagged");
  const licensed = document.getElementById("licensed");
  const count = document.getElementById("count");
  const empty = document.getElementById("empty");
  const state = { kind: "", cat: "" };

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
    const shown = [];
    for (const c of original) {
      const d = c.dataset;
      let s = score(c, words);
      if (s && state.kind && d.kind !== state.kind) s = 0;
      if (s && state.cat && d.cat !== state.cat) s = 0;
      if (s && os.value && d["c-" + os.value] !== "pass") s = 0;
      if (s && tagged.checked && d.tagged !== "1") s = 0;
      if (s && licensed.checked && d.licensed !== "1") s = 0;
      c.hidden = !s;
      if (s) shown.push([s, c]);
    }
    const by = sort.value;
    if (by === "relevance" && words.length) shown.sort((a, b) => b[0] - a[0]);
    else if (by === "updated") shown.sort((a, b) => (b[1].dataset.updated || "").localeCompare(a[1].dataset.updated || ""));
    else if (by === "stars") shown.sort((a, b) => b[1].dataset.stars - a[1].dataset.stars);
    else if (by === "name") shown.sort((a, b) => a[1].dataset.name.localeCompare(b[1].dataset.name));
    else shown.sort((a, b) => original.indexOf(a[1]) - original.indexOf(b[1]));
    const frag = document.createDocumentFragment();
    shown.forEach(([, c]) => frag.appendChild(c));
    original.filter((c) => c.hidden).forEach((c) => frag.appendChild(c));
    list.appendChild(frag);
    count.textContent = shown.length === original.length ? original.length + " entries" : shown.length + " of " + original.length;
    empty.hidden = shown.length > 0;
    document.querySelectorAll(".chip").forEach((b) => b.classList.toggle("on", b.dataset.kind === state.kind));
    document.querySelectorAll("#cats a").forEach((a) => a.classList.toggle("on", a.dataset.cat === state.cat));
    if (push) save();
  }

  function save() {
    const p = new URLSearchParams();
    if (q.value) p.set("q", q.value);
    if (state.kind) p.set("kind", state.kind);
    if (state.cat) p.set("cat", state.cat);
    if (os.value) p.set("os", os.value);
    if (sort.value !== "relevance") p.set("sort", sort.value);
    if (tagged.checked) p.set("tagged", "1");
    if (licensed.checked) p.set("licensed", "1");
    const s = p.toString();
    history.replaceState(null, "", s ? "?" + s : location.pathname);
  }

  function load() {
    const p = new URLSearchParams(location.search);
    q.value = p.get("q") || "";
    state.kind = p.get("kind") || "";
    state.cat = p.get("cat") || "";
    os.value = p.get("os") || "";
    sort.value = p.get("sort") || "relevance";
    tagged.checked = p.get("tagged") === "1";
    licensed.checked = p.get("licensed") === "1";
  }

  document.querySelectorAll(".chip").forEach((b) => b.addEventListener("click", () => { state.kind = b.dataset.kind; apply(true); }));
  document.querySelectorAll("#cats a").forEach((a) => a.addEventListener("click", (ev) => {
    ev.preventDefault();
    state.cat = a.dataset.cat;
    apply(true);
    list.scrollIntoView({ behavior: "smooth", block: "start" });
  }));
  let t;
  q.addEventListener("input", () => { clearTimeout(t); t = setTimeout(() => apply(true), 60); });
  [sort, os, tagged, licensed].forEach((el) => el.addEventListener("change", () => apply(true)));
  document.addEventListener("keydown", (ev) => {
    if (ev.key === "/" && document.activeElement !== q && !/INPUT|SELECT|TEXTAREA/.test(document.activeElement.tagName)) {
      ev.preventDefault(); q.focus();
    }
  });
  load();
  apply(false);
})();
