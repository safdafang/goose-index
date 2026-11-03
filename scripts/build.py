"""Generate README.md, index.json and the static site from packages/ and data/.

Everything this writes is generated: change packages/<id>.toml (or the code
here) and run it again, never edit the outputs.

    python scripts/build.py                 README.md and index.json
    python scripts/build.py --site _site    also the site, ready for GitHub Pages
"""

import argparse
import datetime
import html
import json
import pathlib
import re
import shutil
import sys
import tomllib

import jsonschema

sys.path.insert(0, str(pathlib.Path(__file__).parent))
from validate import load_entries  # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parent.parent
OWNER = "safdafang"
SOURCE = f"https://github.com/{OWNER}/goose-index"
SITE = f"https://{OWNER}.github.io/goose-index/"
UPSTREAM = "https://github.com/aardappel/goose"
INDEX_VERSION = 1

KINDS = {  # order is the listing order inside a category
    "package": ("Package", "Packages"),
    "binding": ("Binding", "Bindings"),
    "tool": ("Tool", "Tools"),
    "editor": ("Editor", "Editors"),
    "app": ("App", "Apps"),
    "fork": ("Fork", "Forks"),
    "learning-resource": ("Learning", "Learning"),
}
OSES = {"linux": "Linux", "macos": "macOS", "windows": "Windows"}
STATUS = {  # label, symbol, sentence
    "pass": ("builds", "✓", "builds and links with the latest Goose release"),
    "check": ("checks only", "◐", "typechecks, but the native build failed"),
    "fail": ("fails", "✕", "could not be fetched, resolved or typechecked"),
    "skip": ("not built", "–", "not built"),
}
esc = html.escape


# ---------------------------------------------------------------- the model

def now_utc():
    return datetime.datetime.now(datetime.timezone.utc)


def load():
    with (ROOT / "schema" / "categories.toml").open("rb") as f:
        cats = tomllib.load(f)["category"]
    meta_doc = read_json(ROOT / "data" / "meta.json") or {"entries": {}}
    compat_doc = read_json(ROOT / "data" / "compat.json")
    entries = []
    for id_, (_, e) in load_entries().items():
        entries.append(model(e, meta_doc["entries"].get(id_), (compat_doc or {}).get("results", {}).get(id_)))
    order = {c["id"]: i for i, c in enumerate(cats)}
    kord = list(KINDS)
    entries.sort(key=lambda x: (order[x["category"]], kord.index(x["kind"]), x["name"].lower()))
    for c in cats:
        c["count"] = sum(1 for x in entries if x["category"] == c["id"])
    return cats, entries, meta_doc, compat_doc


def read_json(p):
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None


def model(e, m, compat):
    """One entry as every output sees it: the hand-written file joined with fetched facts."""
    m = m or {}
    x = {
        "id": e["id"], "name": e["name"], "kind": e["kind"], "category": e["category"],
        "tags": e["tags"], "description": e["description"],
        "repo": e.get("repo"), "url": e.get("url") or e.get("repo"),
        "page": f"{SITE}p/{e['id']}/",
        "available": m.get("exists", True) if e.get("repo") else True,
        "archived": bool(m.get("archived")),
        "latest_tag": m.get("latest_tag"), "tag_count": m.get("tag_count"),
        "default_branch": m.get("default_branch"), "last_commit": m.get("last_commit"),
        "created": m.get("created"), "stars": m.get("stars"),
        "license": e.get("license_override") or m.get("license"),
        "license_source": "entry" if e.get("license_override") else ("github" if m else None),
        "platforms": e["platforms"],
        "native": {"c": e["native"]["c"], "cmake": e["native"]["cmake"],
                   "system_libs": {o: (e["native"].get("system_libs") or {}).get(o, []) for o in OSES},
                   "tools": e["native"].get("tools", [])},
        "upstream_fork": e.get("upstream_fork"),
        "compat": None, "requires": [],
    }
    if e.get("import"):
        imp = e["import"]
        ref = x["latest_tag"] or x["default_branch"] or "main"
        source = imp.get("path") or (e["repo"] or "").removeprefix("https://")
        x["import"] = {
            "name": imp["name"], "source": source, "ref": ref, "pinned": bool(x["latest_tag"]),
            "line": None if imp.get("subdir") else f'import {imp["name"]} from "{source}@{ref}";',
            "modules": imp.get("modules", []), "subdir": imp.get("subdir"),
        }
    else:
        x["import"] = None
    if compat:
        x["compat"] = {o: slim(compat.get(o)) for o in OSES if compat.get(o)}
        reqs = {}
        for r in compat.values():
            for q in r.get("requires", []):
                reqs[q["name"]] = q["source"]
        x["requires"] = [{"name": n, "source": s} for n, s in sorted(reqs.items())]
    return x


def slim(r):
    keep = ("status", "ref", "stage", "detail", "reason", "entry")
    return {k: r[k] for k in keep if r.get(k)}


def compat_status(x, o):
    return ((x["compat"] or {}).get(o) or {}).get("status")


def ago(iso, ref):
    if not iso:
        return ""
    d = (ref - datetime.datetime.fromisoformat(iso.replace("Z", "+00:00"))).days
    if d < 1:
        return "today"
    if d < 2:
        return "yesterday"
    if d < 45:
        return f"{d} days ago"
    if d < 540:
        return f"{round(d / 30)} months ago"
    return f"{d / 365:.1f} years ago"


# ---------------------------------------------------------------- index.json

def write_index(cats, entries, meta_doc, compat_doc, at):
    doc = {
        "$schema": f"{SITE}schema/index.schema.json",
        "format": "goose-index",
        "version": INDEX_VERSION,
        "generated_at": at,
        "meta_fetched_at": meta_doc.get("fetched_at"),
        "compat": ({"goose": compat_doc.get("goose"), "ran_at": compat_doc.get("ran_at"),
                    "run_url": compat_doc.get("run_url")} if compat_doc else None),
        "site": SITE, "source": SOURCE,
        "categories": [{"id": c["id"], "title": c["title"], "scope": c["scope"], "count": c["count"]} for c in cats],
        "entries": entries,
    }
    schema = json.loads((ROOT / "schema" / "index.schema.json").read_text(encoding="utf-8"))
    errors = [f"{'/'.join(map(str, e.absolute_path))}: {e.message}"
              for e in jsonschema.Draft202012Validator(schema).iter_errors(doc)]
    if errors:
        sys.exit("index.json does not match schema/index.schema.json:\n  " + "\n  ".join(errors[:20]))
    text = json.dumps(doc, indent=1, ensure_ascii=False) + "\n"
    (ROOT / "index.json").write_text(text, encoding="utf-8", newline="\n")
    return text


# ---------------------------------------------------------------- README.md

def md_escape(s):
    return s.replace("|", "\\|").replace("<", "&lt;")


def anchor(title):
    return re.sub(r"[^a-z0-9 -]", "", title.lower()).replace(" ", "-")


def write_readme(cats, entries, compat_doc, at, ref_time):
    n = len(entries)
    by_kind = {k: sum(1 for x in entries if x["kind"] == k) for k in KINDS}
    icon = {"pass": "✅", "check": "🟡", "fail": "❌"}
    out = [
        "<!-- Generated by scripts/build.py from packages/ and data/. Do not edit this file:",
        "     change packages/<id>.toml and the bot regenerates it. -->",
        "",
        "# Goose Package Index",
        "",
        f"Libraries, tools, editor plugins, programs and guides for the [Goose programming language]({UPSTREAM}), "
        "found by searching all of GitHub, read by hand, described in our own words and build-tested "
        "against the latest Goose release on Linux, macOS and Windows.",
        "",
        f"**[Search the index »]({SITE})** · [Compatibility matrix]({SITE}compat/) · "
        f"[`index.json`]({SITE}index.json) for tools · [Add a project](CONTRIBUTING.md)",
        "",
        "> **An index, not a registry.** Every entry is a link to its author's own git repository. "
        "Nothing is hosted, mirrored or vendored here. To use a package, paste its `import` line: "
        "Goose fetches it from the source.",
        "",
        f"{n} entries: " + ", ".join(f"{by_kind[k]} {KINDS[k][1].lower()}" for k in KINDS if by_kind[k]) + ".",
        "",
        "**Legend.** ★ stars · 🏷 latest tag (untagged entries pin a branch, which moves) · "
        "⚠️ no license file (nobody may reuse the code until the author adds one) · 🗄 archived · "
        + (f"build status against Goose {compat_doc['goose']}: ✅ builds, 🟡 typechecks only, ❌ fails "
           "(Linux / macOS / Windows)." if compat_doc else "build status: not tested yet."),
        "",
        "## Contents",
        "",
    ]
    for c in cats:
        if c["count"]:
            out.append(f"- [{c['title']}](#{anchor(c['title'])}) ({c['count']})")
    for c in cats:
        if not c["count"]:
            continue
        out += ["", f"## {c['title']}", "", f"_{c['scope']}_", ""]
        for x in entries:
            if x["category"] != c["id"]:
                continue
            bits = [f"- **[{md_escape(x['name'])}]({x['url']})**"]
            if x["kind"] not in ("package", "app"):
                bits.append(f"_{KINDS[x['kind']][0].lower()}_")
            line = " ".join(bits) + " — " + md_escape(x["description"])
            facts = []
            if not x["available"]:
                facts.append("**repository unavailable**")
            if x["archived"]:
                facts.append("🗄 archived")
            if x["stars"]:
                facts.append(f"★ {x['stars']}")
            if x["latest_tag"]:
                facts.append(f"🏷 {x['latest_tag']}")
            if x["license"] == "none":
                facts.append("⚠️ no license")
            st = [icon.get(compat_status(x, o), "") for o in OSES]
            if any(st):
                facts.append(" ".join(s or "➖" for s in st))
            if facts:
                line += " " + " · ".join(facts)
            out.append(line)
            if x["import"] and x["import"]["line"]:
                out.append(f"  `{x['import']['line']}`")
    out += [
        "",
        "## About this list",
        "",
        "- **How entries were found.** Repository, code and topic search across GitHub, every fork of "
        "`aardappel/goose`, the upstream issues, pull requests and discussions, and the links in the "
        "READMEs of verified Goose projects. Each candidate was kept or dropped by reading its files: "
        "projects that merely share the name (the `pressly/goose` migration tool, the `block/goose` "
        "agent and others) are excluded. The full record, with a reason for every decision, is in "
        "[`discovery/candidates.csv`](discovery/candidates.csv).",
        "- **What updates by itself.** Tags, stars, last commit, archived state and license are fetched "
        "daily; build status is tested weekly. Descriptions and categories change only by pull request.",
        f"- **Data for tools.** [`index.json`](index.json) (also at {SITE}index.json) holds every entry "
        "with its import line, native requirements and build results. Its format is documented in "
        "[docs/index-json.md](docs/index-json.md) and versioned.",
        "- **Licenses.** The code here is MIT; the entry data and descriptions are CC0. Listed projects "
        "keep their own licenses.",
        "",
        f"<sub>Generated {at}.</sub>",
        "",
    ]
    (ROOT / "README.md").write_text("\n".join(out), encoding="utf-8", newline="\n")


# ---------------------------------------------------------------- the site

ICON = ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64"><rect width="64" height="64" rx="14" '
        'fill="#1c1a17"/><path d="M22 46c0-9 6-14 13-14h3c2 0 3-1 3-3v-4c0-4 3-7 7-7s7 3 7 7c0 2-1 3-2 4l-5 '
        '1v6c0 9-7 16-16 16h-6c-2 0-4-2-4-4z" fill="#f4efe6"/><path d="M55 25l7 2-7 2z" fill="#f29f05"/>'
        '<circle cx="48" cy="24" r="1.8" fill="#1c1a17"/></svg>')


def page(root, title, body, desc="", active=""):
    nav = [("", "Browse"), ("compat/", "Compatibility"), ("about/", "About")]
    links = "".join(f'<a href="{root}{h}"{" aria-current=page" if active == h else ""}>{t}</a>' for h, t in nav)
    full = "Goose Package Index" if not title else f"{title} · Goose Package Index"
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{esc(full)}</title>
<meta name="description" content="{esc(desc or 'An index of libraries, tools and programs for the Goose programming language.')}">
<link rel="icon" href="{root}assets/icon.svg" type="image/svg+xml">
<link rel="stylesheet" href="{root}assets/style.css">
<script>try{{const t=localStorage.getItem("theme");if(t)document.documentElement.dataset.theme=t}}catch(e){{}}</script>
</head>
<body>
<header class="top"><div class="wrap top-in">
<a class="brand" href="{root}"><img src="{root}assets/icon.svg" alt="" width="28" height="28"><span>Goose Package Index</span></a>
<nav>{links}<a href="{root}index.json">index.json</a><a href="{SOURCE}">GitHub</a>
<button class="theme" type="button" aria-label="Switch light and dark theme" title="Theme">◐</button></nav>
</div></header>
<main class="wrap">
{body}
</main>
<footer class="wrap foot">
<p>An index of links: every project lives in its author's repository, and nothing is hosted or mirrored here.
Data is regenerated daily from <a href="{SOURCE}/tree/main/packages">packages/</a>. Not affiliated with the Goose project.</p>
</footer>
<script src="{root}assets/app.js" defer></script>
</body>
</html>
"""


def compat_badges(x, compact=False):
    if not x["compat"]:
        return ""
    out = []
    for o, label in OSES.items():
        r = x["compat"].get(o)
        s = (r or {}).get("status")
        if not s:
            continue
        lab, sym, sentence = STATUS[s]
        tip = f"{label}: {sentence}" + (f" ({r.get('reason')})" if s == "skip" and r.get("reason") else "")
        text = label[0] if compact else label
        out.append(f'<span class="os s-{s}" title="{esc(tip)}">{sym} {text}</span>')
    if all("s-skip" in b for b in out):
        return ""
    return '<span class="oses">' + "".join(out) + "</span>"


def license_html(x):
    if x["license"] == "none":
        return '<span class="flag" title="No license file: the code may not be reused until the author adds one">no license</span>'
    if x["license"] == "other":
        return '<span title="A license GitHub cannot name; see the repository">custom license</span>'
    return f"<span>{esc(x['license'])}</span>" if x["license"] else ""


def import_block(x, big=False):
    imp = x["import"]
    if not imp:
        return ""
    if not imp["line"]:
        return (f'<div class="import note">Lives in <code>{esc(imp["subdir"])}/</code> of its repository, which Goose '
                f'cannot import by URL yet: copy that folder next to your program and '
                f'<code>import {esc(imp["name"])} from "./{esc(imp["subdir"].rsplit("/", 1)[-1])}";</code></div>')
    warn = "" if imp["pinned"] else (' <span class="unpinned" title="No tags yet: a branch moves, so builds can '
                                     'change under you">untagged</span>')
    return (f'<div class="import{" big" if big else ""}"><code>{esc(imp["line"])}</code>'
            f'<button type="button" class="copy" data-copy="{esc(imp["line"])}">Copy</button>{warn}</div>')


def card(x, root, cats_by_id, ref_time):
    text = " ".join([x["name"], x["id"], x["description"], " ".join(x["tags"]), x["kind"],
                     cats_by_id[x["category"]]["title"], (x["import"] or {}).get("name") or ""]).lower()
    data = {
        "id": x["id"], "kind": x["kind"], "cat": x["category"], "text": text, "name": x["name"].lower(),
        "stars": x["stars"] or 0, "updated": x["last_commit"] or "", "tagged": int(bool(x["latest_tag"])),
        "licensed": int(x["license"] not in ("none", None)),
        **{f"c-{o}": compat_status(x, o) or "" for o in OSES},
        "claims": " ".join(x["platforms"]),
    }
    attrs = " ".join(f'data-{k}="{esc(str(v))}"' for k, v in data.items())
    facts = []
    if not x["available"]:
        facts.append('<span class="flag">repository unavailable</span>')
    if x["archived"]:
        facts.append('<span class="flag soft">archived</span>')
    if x["stars"]:
        facts.append(f'<span title="GitHub stars">★ {x["stars"]}</span>')
    if x["latest_tag"]:
        facts.append(f'<span class="tag" title="Latest tag">{esc(x["latest_tag"])}</span>')
    if x["last_commit"]:
        facts.append(f'<span title="Last commit {esc(x["last_commit"][:10])}">updated {ago(x["last_commit"], ref_time)}</span>')
    lic = license_html(x)
    if lic:
        facts.append(lic)
    cat = cats_by_id[x["category"]]
    return f"""<li class="card" {attrs}>
<div class="card-head"><a class="card-title" href="{root}p/{x['id']}/">{esc(x['name'])}</a>
<span class="kind k-{x['kind']}">{KINDS[x['kind']][0]}</span>
<a class="cat" href="{root}c/{cat['id']}/">{esc(cat['title'])}</a></div>
<p class="desc">{esc(x['description'])}</p>
{import_block(x)}
<div class="facts">{''.join(facts)}{compat_badges(x, compact=True)}</div>
</li>"""


def home(cats, entries, ref_time, compat_doc):
    root = ""
    cats_by_id = {c["id"]: c for c in cats}
    n_pkg = sum(1 for x in entries if x["kind"] in ("package", "binding"))
    kinds = "".join(f'<button type="button" class="chip" data-kind="{k}">{v[1]} '
                    f'<span>{sum(1 for x in entries if x["kind"] == k)}</span></button>'
                    for k, v in KINDS.items())
    side = "".join(f'<li><a href="c/{c["id"]}/" data-cat="{c["id"]}">{esc(c["title"])}<span>{c["count"]}</span></a></li>'
                   for c in cats if c["count"])
    tested = f"tested against Goose {esc(compat_doc['goose'])}" if compat_doc else "build tests run weekly"
    body = f"""<section class="hero">
<h1>Every Goose project we could find, in one place.</h1>
<p class="lede">{len(entries)} libraries, tools, editor plugins, programs and guides for the
<a href="{UPSTREAM}">Goose programming language</a>: {n_pkg} importable packages, each with the line to paste,
the native libraries it needs, and whether it builds, {tested}.</p>
</section>
<section class="finder" aria-label="Search and filter">
<div class="search"><input id="q" type="search" placeholder="Search names, descriptions, tags…  (press /)" autocomplete="off" aria-label="Search">
<select id="sort" aria-label="Sort"><option value="relevance">Best match</option><option value="updated">Recently updated</option><option value="stars">Most stars</option><option value="name">Name</option></select></div>
<div class="chips"><button type="button" class="chip on" data-kind="">All <span>{len(entries)}</span></button>{kinds}</div>
<div class="toggles">
<label>Builds on <select id="os"><option value="">any OS</option><option value="linux">Linux</option><option value="macos">macOS</option><option value="windows">Windows</option></select></label>
<label><input type="checkbox" id="tagged"> tagged releases only</label>
<label><input type="checkbox" id="licensed"> has a license</label>
<span id="count" aria-live="polite"></span></div>
</section>
<div class="layout">
<aside class="side"><h2>Categories</h2><ul id="cats"><li><a href="./" data-cat="" class="on">All categories<span>{len(entries)}</span></a></li>{side}</ul></aside>
<section><ol class="cards" id="cards">
{''.join(card(x, root, cats_by_id, ref_time) for x in entries)}
</ol><p class="empty" id="empty" hidden>Nothing matches. Try fewer words, or <a href="{SOURCE}/blob/main/CONTRIBUTING.md">add the project you were looking for</a>.</p></section>
</div>"""
    return page(root, "", body, active="")


def category_page(c, cats, entries, ref_time):
    root = "../../"
    cats_by_id = {k["id"]: k for k in cats}
    items = [x for x in entries if x["category"] == c["id"]]
    body = f"""<p class="crumbs"><a href="{root}">All entries</a> / {esc(c['title'])}</p>
<h1>{esc(c['title'])}</h1>
<p class="lede">{esc(c['scope'])} {len(items)} {'entry' if len(items) == 1 else 'entries'}.</p>
<ol class="cards">{''.join(card(x, root, cats_by_id, ref_time) for x in items)}</ol>"""
    return page(root, c["title"], body, desc=c["scope"])


def entry_page(x, cats, entries, ref_time, compat_doc):
    root = "../../"
    cat = next(c for c in cats if c["id"] == x["category"])
    rows = []

    def row(k, v):
        if v:
            rows.append(f"<tr><th>{k}</th><td>{v}</td></tr>")

    row("Kind", KINDS[x["kind"]][0])
    row("Category", f'<a href="{root}c/{cat["id"]}/">{esc(cat["title"])}</a>')
    if x["repo"]:
        row("Repository", f'<a href="{esc(x["repo"])}">{esc(x["repo"].removeprefix("https://"))}</a>')
    elif x["url"]:
        row("Link", f'<a href="{esc(x["url"])}">{esc(x["url"])}</a>')
    if x["repo"] and not x["available"]:
        row("Status", '<span class="flag">The repository is gone or private.</span>')
    if x["archived"]:
        row("Status", '<span class="flag soft">Archived by its author: read-only, no further changes.</span>')
    row("Latest tag", esc(x["latest_tag"] or "") + (f' <span class="muted">of {x["tag_count"]}</span>' if (x["tag_count"] or 0) > 1 else "")
        if x["latest_tag"] else ('<span class="unpinned">untagged</span>' if x["repo"] else ""))
    row("Default branch", esc(x["default_branch"] or ""))
    if x["last_commit"]:
        row("Last commit", f'{x["last_commit"][:10]} <span class="muted">({ago(x["last_commit"], ref_time)})</span>')
    if x["created"]:
        row("Created", x["created"][:10])
    if x["stars"] is not None and x["repo"]:
        row("Stars", str(x["stars"]))
    row("License", license_html(x) + (' <span class="muted">(stated by the project; GitHub does not detect it)</span>'
                                      if x["license_source"] == "entry" else ""))
    row("Platforms claimed", ", ".join(OSES[p] for p in x["platforms"]) or ('<span class="muted">not stated</span>' if x["kind"] not in ("learning-resource", "editor") else ""))
    if x["upstream_fork"]:
        row("Adds", esc(x["upstream_fork"]))
    if x["tags"]:
        row("Tags", " ".join(f'<span class="tagword">{esc(t)}</span>' for t in x["tags"]))

    native = []
    nat = x["native"]
    if nat["c"] or nat["cmake"]:
        native.append("<p>" + " and ".join(s for s, on in (("Compiles C sources", nat["c"]), ("builds a CMake project", nat["cmake"])) if on)
                      + ", so a C compiler" + (" and CMake" if nat["cmake"] else "") + " must be installed.</p>")
    cmds = {"linux": "sudo apt install ", "macos": "brew install ", "windows": ""}
    for o, label in OSES.items():
        libs = nat["system_libs"][o]
        if libs:
            native.append(f'<p class="libs"><b>{label}</b> <code>{esc(cmds[o] + " ".join(libs))}</code></p>')
    if nat["tools"]:
        native.append(f'<p>Also runs: {", ".join(f"<code>{esc(t)}</code>" for t in nat["tools"])}.</p>')
    if x["requires"]:
        known = {(e["import"] or {}).get("source", "").lower(): e for e in entries if e["import"]}
        lis = []
        for q in x["requires"]:
            src = q["source"].rsplit("@", 1)[0].lower()
            hit = known.get(src)
            name = f'<a href="{root}p/{hit["id"]}/">{esc(q["name"])}</a>' if hit else esc(q["name"])
            lis.append(f"<li>{name} <code>{esc(q['source'])}</code></li>")
        native.append("<p>Requires these packages (found by the build test; declare them in your root file too):</p><ul>"
                      + "".join(lis) + "</ul>")

    compat_html = ""
    if x["compat"]:
        trs = []
        for o, label in OSES.items():
            r = x["compat"].get(o)
            if not r:
                continue
            s = r["status"]
            note = r.get("detail") or r.get("reason") or STATUS[s][2]
            trs.append(f'<tr><th>{label}</th><td><span class="os s-{s}">{STATUS[s][1]} {STATUS[s][0]}</span></td>'
                       f'<td class="muted">{esc(r.get("ref") or "")}{" · " + esc(r["entry"]) if r.get("entry") else ""}</td>'
                       f'<td>{esc(note)}</td></tr>')
        when = f' Last run {compat_doc["ran_at"][:10]}' + (f', <a href="{compat_doc["run_url"]}">logs</a>' if compat_doc.get("run_url") else "") + "." if compat_doc else ""
        compat_html = (f'<h2>Builds with Goose {esc(compat_doc["goose"]) if compat_doc else ""}</h2>'
                       f'<table class="compat-one">{"".join(trs)}</table><p class="muted small">'
                       f'Checked by importing it into an empty program, or by building the program, on GitHub\'s runners.{when}</p>')
    elif x["repo"] and compat_doc:
        compat_html = '<h2>Builds</h2><p class="muted">Not tested yet.</p>'

    similar = [e for e in entries if e["category"] == x["category"] and e["id"] != x["id"]][:6]
    sim = ""
    if similar:
        sim = '<h2>Also in ' + esc(cat["title"]) + '</h2><ul class="similar">' + "".join(
            f'<li><a href="{root}p/{e["id"]}/">{esc(e["name"])}</a> <span class="muted">{esc(e["description"][:110])}{"…" if len(e["description"]) > 110 else ""}</span></li>'
            for e in similar) + "</ul>"

    edit = f"{SOURCE}/edit/main/packages/{x['id']}.toml"
    body = f"""<p class="crumbs"><a href="{root}">All entries</a> / <a href="{root}c/{cat['id']}/">{esc(cat['title'])}</a></p>
<article class="entry">
<h1>{esc(x['name'])} <span class="kind k-{x['kind']}">{KINDS[x['kind']][0]}</span></h1>
<p class="lede">{esc(x['description'])}</p>
{import_block(x, big=True)}
{f'<p class="muted small">Other modules: {", ".join(f"<code>import {esc(m)};</code>" for m in x["import"]["modules"])}</p>' if x["import"] and x["import"]["modules"] else ""}
<div class="cols">
<div><h2>Facts</h2><table class="facts-t">{''.join(rows)}</table></div>
<div>{'<h2>Native requirements</h2>' + ''.join(native) if native else '<h2>Native requirements</h2><p class="muted">Pure Goose: nothing to install besides Goose.</p>' if x['import'] else ''}
{compat_html}</div>
</div>
{sim}
<p class="small muted">Something wrong here? <a href="{edit}">Edit this entry</a> or <a href="{SOURCE}/issues/new?title={esc(x['id'])}">open an issue</a>.</p>
</article>"""
    return page(root, x["name"], body, desc=x["description"])


def compat_page(cats, entries, compat_doc):
    root = "../"
    tested = [x for x in entries if x["compat"] and any(r["status"] != "skip" for r in x["compat"].values())]
    if not compat_doc:
        body = """<h1>Compatibility</h1><p class="lede">The first build test has not run yet. It builds every package
and program against the latest Goose release on Linux, macOS and Windows, weekly.</p>"""
        return page(root, "Compatibility", body, active="compat/")
    counts = {o: {s: 0 for s in STATUS} for o in OSES}
    for x in entries:
        for o in OSES:
            s = compat_status(x, o)
            if s:
                counts[o][s] += 1
    summ = "".join(f'<div class="stat"><b>{label}</b>' + "".join(
        f'<span class="os s-{s}">{STATUS[s][1]} {counts[o][s]} {STATUS[s][0]}</span>' for s in ("pass", "check", "fail"))
        + "</div>" for o, label in OSES.items())
    rows = []
    for x in tested:
        cells = []
        for o in OSES:
            r = (x["compat"] or {}).get(o) or {}
            s = r.get("status")
            if s:
                tip = r.get("detail") or r.get("reason") or STATUS[s][2]
                cells.append(f'<td class="c s-{s}" title="{esc(tip)}">{STATUS[s][1]}</td>')
            else:
                cells.append('<td class="c"></td>')
        claims = "".join(OSES[p][0] for p in x["platforms"])
        ref = next((r.get("ref") for r in x["compat"].values() if r.get("ref")), "")
        rows.append(f'<tr data-text="{esc((x["name"] + " " + x["id"]).lower())}"><td><a href="{root}p/{x["id"]}/">{esc(x["name"])}</a>'
                    f' <span class="kind k-{x["kind"]}">{KINDS[x["kind"]][0]}</span></td><td class="muted">{esc(ref)}</td>'
                    f'{"".join(cells)}<td class="muted" title="Platforms the author claims">{claims}</td></tr>')
    run = f' (<a href="{compat_doc["run_url"]}">run logs</a>)' if compat_doc.get("run_url") else ""
    body = f"""<h1>Compatibility</h1>
<p class="lede">Every package and program with a buildable entry point, built against Goose {esc(compat_doc['goose'])}
on GitHub's Linux, macOS and Windows runners on {esc((compat_doc.get('ran_at') or '')[:10])}{run}.
A package is imported into an empty program, its requirements added as the compiler asks for them, then built.</p>
<div class="stats">{summ}</div>
<p class="legend"><span class="os s-pass">✓ builds</span> <span class="os s-check">◐ typechecks, native build failed</span>
<span class="os s-fail">✕ fails to fetch or typecheck</span> <span class="os s-skip">– not built</span> · hover a cell for the first error</p>
<input id="cq" type="search" placeholder="Filter by name…" aria-label="Filter">
<table class="matrix" id="matrix"><thead><tr><th>Entry</th><th>Ref</th><th>Linux</th><th>macOS</th><th>Windows</th><th title="Platforms the author claims">Claims</th></tr></thead>
<tbody>{''.join(rows)}</tbody></table>"""
    return page(root, "Compatibility", body, desc="Which Goose packages build on Linux, macOS and Windows.", active="compat/")


def about_page(entries):
    root = "../"
    cand = ROOT / "discovery" / "candidates.csv"
    n_cand = sum(1 for _ in cand.open(encoding="utf-8")) - 1 if cand.exists() else 0
    body = f"""<article class="prose">
<h1>About the index</h1>
<p class="lede">A searchable list of what people are building with and for <a href="{UPSTREAM}">Goose</a>,
the memory-safe systems language with no heap. Goose has no package registry on purpose: a package is a git
repository and an <code>import</code> line. This index only makes those repositories findable.</p>
<h2>An index, not a registry</h2>
<p>Every entry links to its author's own repository. Nothing is hosted, mirrored or vendored here, and nothing is
published through it: authors keep full control of their code and their releases. The import lines are built from
each project's latest git tag.</p>
<h2>How the list was made</h2>
<p>{n_cand} candidate repositories were collected from GitHub repository, code and topic search, every fork of
<code>aardappel/goose</code>, the upstream issues, pull requests and discussions, and the links in the READMEs of
verified Goose projects. Each was kept or dropped by reading its files, not its name: the many unrelated projects
called goose (a Go database migration tool, an AI agent, other small languages) are excluded.
<a href="{SOURCE}/blob/main/discovery/candidates.csv">The full record</a> gives a reason for every decision.
{len(entries)} entries made it in. Descriptions are written for this index rather than copied, and a check rejects
any that repeats the project's own wording.</p>
<h2>What updates by itself</h2>
<ul><li>Daily: latest tag, default branch, last commit, stars, archived state and detected license, from GitHub.</li>
<li>Weekly: the <a href="{root}compat/">build test</a> on Linux, macOS and Windows against the latest Goose release.</li>
<li>By pull request only: what an entry is, its description, category and native requirements.</li></ul>
<h2>Add or fix an entry</h2>
<p>Add a file <code>packages/&lt;owner&gt;-&lt;repo&gt;.toml</code> in a pull request; the
<a href="{SOURCE}/blob/main/CONTRIBUTING.md">contributing guide</a> has a template. Checks run on the pull request,
including a build test of the new entry.</p>
<h2>For tools</h2>
<p><a href="{root}index.json"><code>index.json</code></a> holds every entry with its import line, native requirements,
the packages it requires and its build results. The format is <a href="{SOURCE}/blob/main/docs/index-json.md">documented</a>,
versioned and described by a <a href="{root}schema/index.schema.json">JSON Schema</a>; package managers such as barn can read it directly.</p>
<h2>Licenses</h2>
<p>The index's code is MIT licensed and its data, descriptions included, is CC0. Each listed project has its own
license; entries without one are flagged, because without a license nobody may legally reuse that code.</p>
<p class="muted">Not affiliated with the Goose project or its authors.</p>
</article>"""
    return page(root, "About", body, active="about/")


def write_site(out, cats, entries, compat_doc, index_text, ref_time):
    out = pathlib.Path(out)
    if out.exists():
        shutil.rmtree(out)
    (out / "assets").mkdir(parents=True)
    for f in (ROOT / "web").iterdir():
        shutil.copy(f, out / "assets" / f.name)
    (out / "assets" / "icon.svg").write_text(ICON, encoding="utf-8")
    (out / "schema").mkdir()
    for f in (ROOT / "schema").glob("*.json"):
        shutil.copy(f, out / "schema" / f.name)
    w = lambda rel, text: (out / rel).parent.mkdir(parents=True, exist_ok=True) or (out / rel).write_text(text, encoding="utf-8", newline="\n")
    w("index.html", home(cats, entries, ref_time, compat_doc))
    w("index.json", index_text)
    w(".nojekyll", "")
    w("compat/index.html", compat_page(cats, entries, compat_doc))
    w("about/index.html", about_page(entries))
    for c in cats:
        if c["count"]:
            w(f"c/{c['id']}/index.html", category_page(c, cats, entries, ref_time))
    for x in entries:
        w(f"p/{x['id']}/index.html", entry_page(x, cats, entries, ref_time, compat_doc))
    w("404.html", page(SITE, "Not found", '<h1>Not here</h1><p class="lede">That page does not exist. '
                       f'<a href="{SITE}">Search the index</a>.</p>'))
    return sum(1 for _ in out.rglob("*.html"))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--site", help="also write the static site to this directory")
    a = ap.parse_args()
    cats, entries, meta_doc, compat_doc = load()
    ref_time = now_utc()
    # one timestamp for everything, taken from the data rather than the clock, so a
    # rebuild with no new data leaves README.md and index.json byte for byte the same
    stamps = [s for s in (meta_doc.get("fetched_at"), (compat_doc or {}).get("ran_at")) if s]
    at = max(stamps) if stamps else ref_time.strftime("%Y-%m-%dT%H:%M:%SZ")
    index_text = write_index(cats, entries, meta_doc, compat_doc, at)
    write_readme(cats, entries, compat_doc, at, ref_time)
    msg = f"{len(entries)} entries: README.md, index.json"
    if a.site:
        msg += f", {write_site(a.site, cats, entries, compat_doc, index_text, ref_time)} pages in {a.site}"
    print(msg)


if __name__ == "__main__":
    main()
