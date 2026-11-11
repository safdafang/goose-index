"""Generate README.md, index.json and the site from packages/ and data/.

    python scripts/build.py                 README.md and index.json
    python scripts/build.py --site _site    also the site
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
import urllib.parse

import jsonschema

sys.path.insert(0, str(pathlib.Path(__file__).parent))
from entries import ROOT, load_entries  # noqa: E402

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
    """Merge an entry file with its fetched facts."""
    m = m or {}
    repo = m.get("canonical_repo") or e.get("repo")  # where a renamed repository lives now
    x = {
        "id": e["id"], "name": e["name"], "kind": e["kind"], "category": e["category"],
        "tags": e["tags"], "description": e["description"],
        "repo": repo, "url": e.get("url") or repo,
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
        source = imp.get("path") or (repo or "").removeprefix("https://")
        usable = x["available"] and not imp.get("subdir")  # no line to paste for a repository that is gone
        x["import"] = {
            "name": imp["name"], "source": source, "ref": ref, "pinned": bool(x["latest_tag"]),
            "commit": m.get("latest_tag_commit") if x["latest_tag"] else None,
            "line": f'import {imp["name"]} from "{source}@{ref}";' if usable else None,
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
    keep = ("status", "ref", "stage", "detail", "reason", "entry", "goose", "ran_at")
    return {k: r[k] for k in keep if r.get(k)}


def compat_status(x, o):
    return ((x["compat"] or {}).get(o) or {}).get("status")


def older(r, goose):
    """The Goose release a result was made with, when it is not the one the last run tested."""
    g = (r or {}).get("goose")
    return g if g and goose and g != goose and r.get("status") != "skip" else None


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


def md_escape(s):
    return s.replace("|", "\\|").replace("<", "&lt;")


def anchor(title):
    return re.sub(r"[^a-z0-9 -]", "", title.lower()).replace(" ", "-")


def shield(text):
    """Escape text for a static shields.io badge path."""
    return urllib.parse.quote(text.replace("-", "--").replace("_", "__"), safe="")


def write_readme(cats, entries, compat_doc, at, ref_time):
    n = len(entries)
    by_kind = {k: sum(1 for x in entries if x["kind"] == k) for k in KINDS}
    icon = {"pass": "✅", "check": "🟡", "fail": "❌"}
    out = [
        "<!-- Generated by scripts/build.py from packages/ and data/. Do not edit this file:",
        "     change packages/<id>.toml and the bot regenerates it. -->",
        "",
        f'<p align="center"><a href="{SITE}"><img src=".github/assets/banner.png" '
        'alt="Goose Package Index" width="100%"></a></p>',
        "",
        '<p align="center">',
        *(f'  <a href="{SOURCE}/actions/workflows/{w}.yml"><img alt="{w}" '
          f'src="{SOURCE}/actions/workflows/{w}.yml/badge.svg"></a>' for w in ("update", "compat")),
        f'  <a href="#contents"><img alt="{n} entries" src="https://img.shields.io/badge/entries-{n}-5E8C61"></a>',
        *([f'  <a href="{SITE}compat/"><img alt="tested against Goose {compat_doc["goose"]}" '
           f'src="https://img.shields.io/badge/goose-{shield(compat_doc["goose"])}-F28C28"></a>'] if compat_doc else []),
        '  <a href="#licence"><img alt="Licence: MIT and CC0" '
        'src="https://img.shields.io/badge/licence-MIT%20%2B%20CC0-blue"></a>',
        "</p>",
        "",
        f'<p align="center"><b><a href="{SITE}">Search the index</a></b> · '
        f'<a href="{SITE}compat/">Compatibility matrix</a> · '
        f'<a href="{SITE}index.json"><code>index.json</code></a> · '
        '<a href="CONTRIBUTING.md">Add a project</a></p>',
        "",
        f"Libraries, tools, editor plugins, programs and guides for the [Goose programming language]({UPSTREAM}), "
        "found by searching all of GitHub, read by hand, described in our own words and build-tested "
        "against the latest Goose release on Linux, macOS and Windows.",
        "",
        "> [!NOTE]",
        "> **An index, not a registry.** Every entry is a link to its author's own git repository. "
        "Nothing is hosted, mirrored or vendored here. To use a package, paste its `import` line: "
        "Goose fetches it from the source.",
        "",
        "| " + " | ".join(KINDS[k][1] for k in KINDS if by_kind[k]) + " | **Total** |",
        "|" + "--:|" * (sum(1 for k in KINDS if by_kind[k]) + 1),
        "| " + " | ".join(str(by_kind[k]) for k in KINDS if by_kind[k]) + f" | **{n}** |",
        "",
        "## Legend",
        "",
        "| Mark | Meaning |",
        "|---|---|",
        "| ★ | stars on the source repository |",
        "| 🏷 | latest tag; untagged entries pin a branch, which moves |",
        "| ⚠️ | no license file: nobody may reuse the code until the author adds one |",
        "| 🗄 | archived by its author |",
        *(["| ✅ 🟡 ❌ | build status against Goose " + md_escape(compat_doc["goose"]) + ", one mark each for Linux, "
           "macOS and Windows: ✅ builds, 🟡 typechecks only, ❌ fails, ➖ not tested, ⏳ after a mark: that result "
           "is from an earlier Goose release |"] if compat_doc
          else ["| ✅ 🟡 ❌ | build status: not tested yet |"]),
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
                facts.append(f"🏷 {md_escape(x['latest_tag'])}")
            if x["license"] == "none":
                facts.append("⚠️ no license")
            goose = (compat_doc or {}).get("goose")
            st = [icon.get(compat_status(x, o), "") + ("⏳" if older((x["compat"] or {}).get(o), goose) else "")
                  if icon.get(compat_status(x, o)) else "" for o in OSES]
            if any(st):
                facts.append(" ".join(s or "➖" for s in st))
            if facts:
                line += " " + " · ".join(facts)
            out.append(line)
            if x["import"] and x["import"]["line"]:
                out.append(f"  `{x['import']['line']}`")
    out += [
        "",
        "## How the index works",
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
        "",
        "## Contributing",
        "",
        "Adding a project is one file, `packages/<id>.toml`, in a pull request: see "
        "[CONTRIBUTING.md](CONTRIBUTING.md). Wrong description, dead link, or you are the author and want "
        f"your project removed? [Open an issue]({SOURCE}/issues/new/choose). Everyone taking part follows the "
        "[code of conduct](CODE_OF_CONDUCT.md); a listed project that looks malicious is reported as described "
        "in [SECURITY.md](SECURITY.md).",
        "",
        "## Licence",
        "",
        "The code here (`scripts/`, `web/`, `.github/`) is [MIT](LICENSE); the entry data and descriptions "
        "(`packages/`, `data/`, this README and `index.json`) are [CC0 1.0](LICENSE). Listed projects keep "
        "their own licenses. Goose is a project of its own authors; this index is not affiliated with it.",
        "",
        f"<sub>Generated {at}.</sub>",
        "",
    ]
    (ROOT / "README.md").write_text("\n".join(out), encoding="utf-8", newline="\n")


ICON = ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64"><rect width="64" height="64" rx="14" fill="#8DB580"/>'
        '<path d="M32 56L19.8 37.6L8 18.2Q6.6 11 13.8 12.8L24.8 23.4L27.1 6.4Q32 0 36.9 6.4L39.2 23.4L50.2 12.8Q57.4 11 '
        '56 18.2L44.2 37.6Z" fill="#F28C28" stroke="#F28C28" stroke-width="4" stroke-linejoin="round" '
        'transform="translate(32 33) scale(.82) translate(-32 -30)"/></svg>')
CONTRIBUTE = f"{SOURCE}/blob/main/CONTRIBUTING.md"
PER_PAGE = 18


def art(root, name, cls="i", label=""):
    """An image from the sprite. Decorative unless it gets a label."""
    a11y = f'role="img" aria-label="{esc(label)}"' if label else 'aria-hidden="true" focusable="false"'
    title = f"<title>{esc(label)}</title>" if label else ""
    return f'<svg class="{cls}" {a11y}>{title}<use href="{root}assets/img/sprite.svg#{name}"/></svg>'


def packet(root, kind, cls="packet"):
    return art(root, f"k-{kind}", cls, KINDS[kind][0])


def owner(x):
    u = x["repo"] or x["url"] or ""
    parts = u.removeprefix("https://").removeprefix("http://").split("/")
    if parts[0] in ("github.com", "gitlab.com", "codeberg.org") and len(parts) > 1:
        return parts[1]
    return parts[0]


def page(root, title, body, desc="", active=None, cls="", head=""):
    nav = [("", "Index"), ("compat/", "Compatibility"), ("about/", "About")]
    links = "".join(f'<a href="{root}{h}"{" aria-current=page" if active == h else ""}>{t}</a>' for h, t in nav)
    links += f'<a href="{CONTRIBUTE}">Add a project</a>'
    full = "Goose Package Index" if not title else f"{title} · Goose Package Index"
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{esc(full)}</title>
<meta name="description" content="{esc(desc or 'An index of libraries, tools and programs for the Goose programming language.')}">
<meta name="theme-color" content="#8DB580">
<link rel="icon" href="{root}assets/icon.svg" type="image/svg+xml">
<link rel="preload" href="{root}assets/fonts/nunito.woff2" as="font" type="font/woff2" crossorigin>
<link rel="stylesheet" href="{root}assets/style.css">{head}
</head>
<body class="{cls}">
<svg class="defs" aria-hidden="true" focusable="false" width="0" height="0">
<filter id="torn" x="-4%" y="-4%" width="108%" height="108%"><feTurbulence type="fractalNoise" baseFrequency="0.055" numOctaves="4" seed="7"/><feDisplacementMap in="SourceGraphic" scale="9"/></filter>
<filter id="wobble" x="-4%" y="-6%" width="108%" height="112%"><feTurbulence type="fractalNoise" baseFrequency="0.011 0.03" numOctaves="2" seed="3"/><feDisplacementMap in="SourceGraphic" scale="7"/></filter>
<filter id="leafy" x="-6%" y="-6%" width="112%" height="112%"><feTurbulence type="fractalNoise" baseFrequency="0.028" numOctaves="3" seed="11"/><feDisplacementMap in="SourceGraphic" scale="30"/></filter>
</svg>
<a class="skip" href="#main">Skip to content</a>
<header class="top"><div class="wrap top-in">
<a class="plank brand" href="{root}">{art(root, "foot", "logo")}<span>Goose-index</span></a>
<nav class="plank nav" aria-label="Site">{links}</nav>
<a class="plank gh" href="{SOURCE}" aria-label="The index on GitHub" title="The index on GitHub">{art(root, "i-github", "i")}</a>
</div></header>
<main class="wrap" id="main">
{body}
</main>
<footer class="wrap foot"><div class="foot-in paper">
<p>An index of links: every project lives in its author's repository, and nothing is hosted or mirrored here.
Data is regenerated daily from <a href="{SOURCE}/tree/main/packages">packages/</a>, and all of it is in
<a href="{root}index.json">index.json</a>. Not affiliated with the Goose project.</p>
</div></footer>
<script src="{root}assets/app.js" defer></script>
</body>
</html>
"""


def compat_badges(x, compact=False, goose=None):
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
        old = older(r, goose)
        if old:
            tip += f". Last tested with Goose {old}"
        text = label[0] if compact else label
        out.append(f'<span class="os s-{s}{" old" if old else ""}" title="{esc(tip)}">{sym} {text}</span>')
    if all("s-skip" in b for b in out):
        return ""
    return '<span class="oses">' + "".join(out) + "</span>"


def license_html(x):
    if x["license"] == "none":
        return '<span class="flag" title="No license file: the code may not be reused until the author adds one">no license</span>'
    if x["license"] == "other":
        return '<span title="A license GitHub cannot name; see the repository">custom license</span>'
    return f"<span>{esc(x['license'])}</span>" if x["license"] else ""


def code_html(line):
    m = re.fullmatch(r'import (\S+) from "(.*)";', line)
    if not m:
        return esc(line)
    return (f'<span class="kw">import</span> {esc(m[1])} <span class="kw">from</span> '
            f'<span class="str">"{esc(m[2])}"</span>;')


def import_block(root, x, big=False):
    imp = x["import"]
    if not imp:
        return ""
    if not x["available"]:
        return '<div class="import note">The repository is unavailable, so there is nothing to import.</div>'
    if not imp["line"]:
        return (f'<div class="import note">Lives in <code>{esc(imp["subdir"])}/</code> of its repository, which Goose '
                f'cannot import by URL yet: copy that folder next to your program and '
                f'<code>import {esc(imp["name"])} from "./{esc(imp["subdir"].rsplit("/", 1)[-1])}";</code></div>')
    warn = "" if imp["pinned"] else ('<p class="unpinned">No tags yet, so this pins a branch: builds can change under you.</p>')
    return (f'<div class="code{" big" if big else ""}"><code>{code_html(imp["line"])}</code>'
            f'<button type="button" class="copy" data-copy="{esc(imp["line"])}">{art(root, "i-clip")}<span>Copy</span></button></div>{warn}')


def card(x, root, cats_by_id, ref_time, goose=None, off=False):
    text = " ".join([x["name"], x["id"], x["description"], " ".join(x["tags"]), x["kind"], owner(x),
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
    if x["repo"]:
        facts.append(f'<span title="GitHub stars">{art(root, "i-star", "i star")}{x["stars"] or 0}</span>')
    if x["last_commit"]:
        facts.append(f'<span title="Last commit {esc(x["last_commit"][:10])}">{art(root, "i-calendar", "i")}{ago(x["last_commit"], ref_time)}</span>')
    if x["latest_tag"]:
        facts.append(f'<span class="tag" title="Latest tag">{art(root, "i-tag", "i")}{esc(x["latest_tag"])}</span>')
    if x["license"] == "none":
        facts.append(license_html(x))
    tags = "".join(f'<span class="sprout">{esc(t)}</span>' for t in x["tags"][:2])
    copy = ""
    if x["import"] and x["import"]["line"]:
        copy = (f'<button type="button" class="copy pinbtn" data-copy="{esc(x["import"]["line"])}" '
                f'title="Copy: {esc(x["import"]["line"])}">{art(root, "i-clip")}<span class="sr">Copy the import line</span></button>')
    cat = cats_by_id[x["category"]]
    return f"""<li class="card{' off' if off else ''}" {attrs}>
<a class="card-pic" href="{root}p/{x['id']}/" tabindex="-1">{packet(root, x['kind'])}</a>
<div class="card-body">
<a class="card-title" href="{root}p/{x['id']}/">{esc(x['name'])}</a>
<span class="by">by {esc(owner(x))} · <a href="{root}c/{cat['id']}/" title="{esc(cat['title'])}">{KINDS[x['kind']][0].lower()}</a></span>
<p class="desc">{esc(x['description'])}</p>
{f'<div class="sprouts">{tags}</div>' if tags else ''}
<div class="facts">{''.join(facts)}{compat_badges(x, compact=True, goose=goose)}</div>
</div>{copy}
</li>"""


def mini(x, root):
    tags = "".join(f'<span class="sprout">{esc(t)}</span>' for t in x["tags"][:2])
    stars = f'<span class="stars">{art(root, "i-star", "i star")}{x["stars"] or 0}</span>' if x["repo"] else ""
    return (f'<li class="mini">{art(root, "pin", "pin")}<a class="mini-pic" href="{root}p/{x["id"]}/" tabindex="-1">{packet(root, x["kind"])}</a>'
            f'<div><a class="card-title" href="{root}p/{x["id"]}/">{esc(x["name"])}</a>'
            f'<p class="desc">{esc(x["description"])}</p><div class="mini-foot"><span class="sprouts">{tags}</span>{stars}</div></div></li>')


def empty_state(root):
    return f"""<div class="empty" id="empty" hidden>
<p class="empty-sign plank"><span id="empty-what">No entries found</span></p>
<p class="empty-hint">Try another word, or add the project you were looking for.</p>
<a class="btn" href="{CONTRIBUTE}">Add a project {art(root, "foot", "i")}</a>
</div>"""


def radio(name, value, text, count=None, checked=False):
    n = f'<span class="n">{count}</span>' if count is not None else ""
    return (f'<label class="opt"><input type="radio" name="{name}" value="{value}"{" checked" if checked else ""}>'
            f'<span class="box"></span><span class="t">{text}</span>{n}</label>')


def home(cats, entries, ref_time, compat_doc):
    root = ""
    cats_by_id = {c["id"]: c for c in cats}
    authors = len({owner(x) for x in entries if x["repo"]})
    kinds = radio("kind", "", "Anything", len(entries), True) + "".join(
        radio("kind", k, v[1], sum(1 for x in entries if x["kind"] == k)) for k, v in KINDS.items())
    catr = radio("cat", "", "Every category", len(entries), True) + "".join(
        radio("cat", c["id"], esc(c["title"]), c["count"]) for c in cats if c["count"])
    sorts = "".join(radio("sort", v, t, checked=(v == "relevance")) for v, t in
                    (("relevance", "Best match"), ("updated", "Recently updated"), ("stars", "Stars"), ("name", "Name")))
    tested = f"whether it builds with Goose {esc(compat_doc['goose'])}" if compat_doc else "build tests run weekly"
    fresh = sorted((x for x in entries if x["created"] and x["available"]), key=lambda x: x["created"], reverse=True)[:3]
    body = f"""<section class="hero">
<div class="hero-text">
<h1><span class="strip">Every Goose project.</span><br><span class="strip">Stolen into one place.</span></h1>
<p class="sub"><span class="strip">The community index of projects written in Goose.</span></p>
<form class="sign" role="search" action="./#index"><span class="post l"></span><span class="post r"></span>
<label class="sr" for="q">Search the index</label>
<input id="q" name="q" type="search" placeholder="Search packages…" autocomplete="off">
<button type="submit" class="sign-go" aria-label="Search">{art(root, "i-search")}</button>
</form>
<p class="hint paper">Each entry links to its author's repository, with the import line to paste and {tested}. Press <kbd>/</kbd> to search.</p>
</div>
</section>
<div class="planters">
<div class="planter"><div class="planter-box"><p class="planter-label plank">{art(root, "i-box")}{len(entries)} entries</p></div></div>
<div class="planter"><div class="planter-box"><p class="planter-label plank">{art(root, "i-people")}{authors} authors</p></div></div>
<div class="planter"><div class="planter-box"><p class="planter-label plank">{art(root, "i-clock")}Updated daily</p></div></div>
</div>
<section class="paper panel fresh" id="fresh"><h2 class="rule">Freshly planted</h2>
<ul class="minis">{''.join(mini(x, root) for x in fresh)}</ul></section>
<section class="yard" id="index" aria-label="All entries">
<aside class="note paper filters">{art(root, "pin", "pin")}
<h2 class="hand">Filter</h2>
<p class="hand count" id="count" aria-live="polite">{len(entries)} entries</p>
<fieldset><legend class="hand">Kind:</legend>{kinds}</fieldset>
<fieldset><legend class="hand">Sort by:</legend>{sorts}</fieldset>
<fieldset><legend class="hand">Builds on:</legend>
<select id="os" aria-label="Builds on"><option value="">any OS</option><option value="linux">Linux</option><option value="macos">macOS</option><option value="windows">Windows</option></select></fieldset>
<fieldset><legend class="hand">Only:</legend>
<label class="opt"><input type="checkbox" id="tagged"><span class="box"></span><span class="t">tagged releases</span></label>
<label class="opt"><input type="checkbox" id="licensed"><span class="box"></span><span class="t">has a license</span></label></fieldset>
<details class="cats"><summary class="hand">Category:</summary><fieldset>{catr}</fieldset></details>
</aside>
<div class="board-wrap">
<div class="board"><ol class="cards" id="cards" data-per-page="{PER_PAGE}">
{''.join(card(x, root, cats_by_id, ref_time, (compat_doc or {}).get("goose"), off=i >= PER_PAGE) for i, x in enumerate(entries))}
</ol>{empty_state(root)}</div>
<nav class="stones" id="pager" aria-label="Pages" hidden></nav>
</div>
</section>"""
    return page(root, "", body, active="", cls="home", head="\n<noscript><style>.card.off { display: flex; }</style></noscript>")


def category_page(c, cats, entries, ref_time, compat_doc):
    root = "../../"
    cats_by_id = {k["id"]: k for k in cats}
    items = [x for x in entries if x["category"] == c["id"]]
    body = f"""<p class="crumbs"><span class="strip"><a href="{root}">All entries</a> / {esc(c['title'])}</span></p>
<h1><span class="strip">{esc(c['title'])}</span></h1>
<p class="sub"><span class="strip">{esc(c['scope'])} {len(items)} {'entry' if len(items) == 1 else 'entries'}.</span></p>
<div class="board-wrap solo">
<div class="board"><ol class="cards">{''.join(card(x, root, cats_by_id, ref_time, (compat_doc or {}).get("goose")) for x in items)}</ol></div></div>"""
    return page(root, c["title"], body, desc=c["scope"], cls="category")


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
        row("Status", '<span class="flag">The repository is gone, private, or replaced by a different one.</span>')
    if x["archived"]:
        row("Status", '<span class="flag soft">Archived by its author: read-only, no further changes.</span>')
    row("Latest tag", esc(x["latest_tag"] or "") + (f' <span class="muted">of {x["tag_count"]}</span>' if (x["tag_count"] or 0) > 1 else "")
        if x["latest_tag"] else ('<span class="flag warn">untagged</span>' if x["repo"] else ""))
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
        native.append("<p>Requires these packages (found by the build test; declare them in your root file too):</p><ul class=\"reqs\">"
                      + "".join(lis) + "</ul>")
    native_html = ""
    if native:
        native_html = "<h2>Needs</h2>" + "".join(native)
    elif x["import"]:
        native_html = '<h2>Needs</h2><p class="muted">Pure Goose: nothing to install besides Goose.</p>'

    compat_html = ""
    if x["compat"]:
        trs = []
        for o, label in OSES.items():
            r = x["compat"].get(o)
            if not r:
                continue
            s = r["status"]
            note = r.get("detail") or r.get("reason") or STATUS[s][2]
            old = older(r, (compat_doc or {}).get("goose"))
            trs.append(f'<tr><th>{label}</th><td><span class="os s-{s}{" old" if old else ""}">{STATUS[s][1]} {STATUS[s][0]}</span></td>'
                       f'<td class="muted">{esc(r.get("ref") or "")}{" · " + esc(r["entry"]) if r.get("entry") else ""}'
                       f'{" · last tested with Goose " + esc(old) if old else ""}</td>'
                       f'<td class="note">{esc(note)}</td></tr>')
        when = f' Last run {esc(compat_doc["ran_at"][:10])}' + (f', <a href="{esc(compat_doc["run_url"])}">logs</a>' if compat_doc.get("run_url") else "") + "." if compat_doc else ""
        compat_html = (f'<h2>Builds with Goose {esc(compat_doc["goose"]) if compat_doc else ""}</h2>'
                       f'<div class="scroll"><table class="compat-one">{"".join(trs)}</table></div><p class="muted small">'
                       f'Checked by importing it into an empty program, or by building the program, on GitHub\'s runners.{when}</p>')
    elif x["repo"] and compat_doc:
        compat_html = '<h2>Builds</h2><p class="muted">Not tested yet.</p>'

    use_html = ""
    if x["import"]:
        mods = (f'<p class="muted small">Other modules: {", ".join(f"<code>import {esc(m)};</code>" for m in x["import"]["modules"])}</p>'
                if x["import"]["modules"] else "")
        use_html = f'<h2>Use it</h2>{import_block(root, x, big=True)}{mods}'

    signs = []
    if x["repo"]:
        signs.append(f'<li title="GitHub stars">{art(root, "i-star", "i")}{x["stars"] or 0}</li>')
    if x["latest_tag"]:
        signs.append(f'<li title="Latest tag">{art(root, "i-tag", "i")}{esc(x["latest_tag"])}</li>')
    elif x["repo"]:
        signs.append(f'<li title="No tags yet">{art(root, "i-tag", "i")}untagged</li>')
    if x["last_commit"]:
        signs.append(f'<li title="Last commit {x["last_commit"][:10]}">{art(root, "i-clock", "i")}{ago(x["last_commit"], ref_time)}</li>')
    if x["license"]:
        lic = {"none": "no license", "other": "custom"}.get(x["license"], x["license"])
        signs.append(f'<li title="License">{art(root, "i-scale", "i")}{esc(lic)}</li>')

    link = x["repo"] or x["url"]
    on_gh = (link or "").startswith("https://github.com/")
    buttons = ""
    if link:
        buttons += (f'<a class="btn" href="{esc(link)}">{art(root, "i-github" if on_gh else "i-house", "i")}'
                    f'{"View on GitHub" if on_gh else "Open the site"}</a>')
    if x["import"] and x["import"]["line"]:
        buttons += (f'<button type="button" class="btn ghost copy" data-copy="{esc(x["import"]["line"])}">'
                    f'{art(root, "i-clip", "i")}<span>Copy import</span></button>')

    tags = "".join(f'<a class="sprout" href="{root}?q={esc(t)}#index">{art(root, "i-sprout", "i")}{esc(t)}</a>' for t in x["tags"])
    similar = [e for e in entries if e["category"] == x["category"] and e["id"] != x["id"]][:4]
    sim = ""
    if similar:
        sim = (f'<div class="paper side-note"><h2>Also in {esc(cat["title"])}</h2><ul class="similar">' + "".join(
            f'<li><a href="{root}p/{e["id"]}/">{packet(root, e["kind"], "packet sm")}<span><b>{esc(e["name"])}</b>'
            f'<span class="muted">{esc(e["description"][:70])}{"…" if len(e["description"]) > 70 else ""}</span></span></a></li>'
            for e in similar) + "</ul></div>")
    edit = f"{SOURCE}/edit/main/packages/{x['id']}.toml"
    body = f"""<p class="crumbs"><span class="strip"><a href="{root}">All entries</a> / <a href="{root}c/{cat['id']}/">{esc(cat['title'])}</a></span></p>
<article class="entry">
<div class="entry-main">
<header class="paper entry-head">
{packet(root, x['kind'], "packet lg")}
<div class="entry-title"><h1>{esc(x['name'])}</h1><p class="by">by {esc(owner(x))} · {KINDS[x['kind']][0].lower()}</p>
<p class="lede">{esc(x['description'])}</p></div>
<div class="entry-btns">{buttons}</div>
</header>
{f'<ul class="signs">{"".join(signs)}</ul>' if signs else ''}
<div class="sheet-wrap">
<section class="paper sheet">{art(root, "pin", "pin")}
{use_html}
{compat_html}
{native_html}
<h2>Facts</h2><div class="scroll"><table class="facts-t">{''.join(rows)}</table></div>
<p class="small muted edit">Something wrong here? <a href="{edit}">Edit this entry</a> or <a href="{SOURCE}/issues/new?title={esc(x['id'])}">open an issue</a>. {art(root, "foot", "i foot-mark")}</p>
</section></div>
</div>
<aside class="entry-side">
{f'<div class="paper side-note"><h2>Tags</h2><div class="sprouts big">{tags}</div></div>' if tags else ''}
{sim}
</aside>
</article>"""
    return page(root, x["name"], body, desc=x["description"], cls="entry-page")


def compat_page(cats, entries, compat_doc):
    root = "../"
    tested = [x for x in entries if x["compat"] and any(r["status"] != "skip" for r in x["compat"].values())]
    if not compat_doc:
        body = """<h1><span class="strip">Compatibility</span></h1><p class="sub"><span class="strip">The first build test has not run yet. It builds every package
and program against the latest Goose release on Linux, macOS and Windows, weekly.</span></p>"""
        return page(root, "Compatibility", body, active="compat/", cls="compat")
    counts = {o: {s: 0 for s in STATUS} for o in OSES}
    for x in entries:
        for o in OSES:
            s = compat_status(x, o)
            if s:
                counts[o][s] += 1
    summ = "".join(f'<li><b>{label}</b>' + "".join(
        f'<span class="os s-{s}">{STATUS[s][1]} {counts[o][s]} {STATUS[s][0]}</span>' for s in ("pass", "check", "fail"))
        + "</li>" for o, label in OSES.items())
    rows = []
    for x in tested:
        cells = []
        for o in OSES:
            r = (x["compat"] or {}).get(o) or {}
            s = r.get("status")
            if s:
                tip = r.get("detail") or r.get("reason") or STATUS[s][2]
                old = older(r, compat_doc.get("goose"))
                if old:
                    tip = f"Last tested with Goose {old}. {tip}"
                cells.append(f'<td class="c"><span class="dot s-{s}{" old" if old else ""}" title="{esc(tip)}">{STATUS[s][1]}</span></td>')
            else:
                cells.append('<td class="c"></td>')
        claims = "".join(OSES[p][0] for p in x["platforms"])
        ref = next((r.get("ref") for r in x["compat"].values() if r.get("ref")), "")
        rows.append(f'<tr data-text="{esc((x["name"] + " " + x["id"]).lower())}"><td class="nm">{packet(root, x["kind"], "packet xs")}<a href="{root}p/{x["id"]}/">{esc(x["name"])}</a></td>'
                    f'<td class="muted">{esc(ref)}</td>'
                    f'{"".join(cells)}<td class="muted" title="Platforms the author claims">{claims}</td></tr>')
    run = f' (<a href="{esc(compat_doc["run_url"])}">run logs</a>)' if compat_doc.get("run_url") else ""
    body = f"""<h1><span class="strip">Compatibility</span></h1>
<p class="sub"><span class="strip">Every package and program with a buildable entry point, built against Goose {esc(compat_doc['goose'])}
on GitHub's Linux, macOS and Windows runners on {esc((compat_doc.get('ran_at') or '')[:10])}{run}.</span>
<span class="strip">A package is imported into an empty program, its requirements added as the compiler asks for them, then built.</span></p>
<ul class="signs os-signs">{summ}</ul>
<section class="paper sheet matrix-sheet">{art(root, "pin", "pin")}
<p class="legend"><span class="os s-pass">✓ builds</span> <span class="os s-check">◐ typechecks, native build failed</span>
<span class="os s-fail">✕ fails to fetch or typecheck</span> <span class="os s-skip">– not built</span>
<span class="os s-pass old">faded</span> <span class="muted">a result from an earlier Goose release · hover a mark for the first error</span></p>
<div class="sign small-sign"><label class="sr" for="cq">Filter by name</label><input id="cq" type="search" placeholder="Filter by name…" autocomplete="off">{art(root, "i-search")}</div>
<div class="scroll"><table class="matrix" id="matrix"><thead><tr><th>Entry</th><th>Ref</th><th>Linux</th><th>macOS</th><th>Windows</th><th title="Platforms the author claims">Claims</th></tr></thead>
<tbody>{''.join(rows)}</tbody></table></div>
</section>"""
    return page(root, "Compatibility", body, desc="Which Goose packages build on Linux, macOS and Windows.", active="compat/", cls="compat")


def about_page(entries):
    root = "../"
    cand = ROOT / "discovery" / "candidates.csv"
    n_cand = sum(1 for _ in cand.open(encoding="utf-8")) - 1 if cand.exists() else 0
    body = f"""<div class="about">
<article class="paper sheet prose">{art(root, "pin", "pin")}
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
<a href="{CONTRIBUTE}">contributing guide</a> has a template. Checks run on the pull request,
including a build test of the new entry.</p>
<h2>For tools</h2>
<p><a href="{root}index.json"><code>index.json</code></a> holds every entry with its import line, native requirements,
the packages it requires and its build results. The format is <a href="{SOURCE}/blob/main/docs/index-json.md">documented</a>,
versioned and described by a <a href="{root}schema/index.schema.json">JSON Schema</a>; package managers such as barn can read it directly.</p>
<h2>Licenses</h2>
<p>The index's code is MIT licensed and its data, descriptions included, is CC0. Each listed project has its own
license; entries without one are flagged, because without a license nobody may legally reuse that code.</p>
<p class="muted">Not affiliated with the Goose project or its authors.</p>
</article>
</div>"""
    return page(root, "About", body, active="about/", cls="about-page")


def not_found():
    root = "/goose-index/"  # same origin on Pages, which sprite <use> needs
    body = f"""<section class="lost">
<div class="paper lost-sign">{art(root, "pin", "pin")}<h1>The goose took this page.</h1></div>
<p class="lost-hint"><span class="strip">Nothing lives at this address, or it waddled off.</span></p>
<a class="btn" href="{SITE}">Back to the index {art(root, "foot", "i")}</a>
</section>"""
    return page(root, "Not found", body, cls="lost-page")


def write_site(out, cats, entries, compat_doc, index_text, ref_time):
    out = pathlib.Path(out)
    if out.exists():
        shutil.rmtree(out)
    shutil.copytree(ROOT / "web", out / "assets")
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
            w(f"c/{c['id']}/index.html", category_page(c, cats, entries, ref_time, compat_doc))
    for x in entries:
        w(f"p/{x['id']}/index.html", entry_page(x, cats, entries, ref_time, compat_doc))
    w("404.html", not_found())
    return sum(1 for _ in out.rglob("*.html"))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--site", help="also write the static site to this directory")
    a = ap.parse_args()
    cats, entries, meta_doc, compat_doc = load()
    ref_time = now_utc()
    # from the data, not the clock, so a rebuild with no new data changes nothing
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
