"""Look for Goose projects that appeared since the last look, and draft their entries for a person.

    python scripts/scout.py --report scout.md [--json scout.json] [--since 2026-11-20]
                            [--sources repos,topics,code,forks,tracker] [--dry-run]

The weekly workflow (.github/workflows/scout.yml) runs this and opens an issue with the report.
It reuses the first discovery's searches (discover.py), its file checks (verify.py) and its
mechanical exclusions (triage.py), but only for what is new:

- repository and topic search limited to repositories pushed since the last run, code search for
  Goose source, new forks of aardappel/goose and the upstream issues, pull requests and
  discussions updated since the last run, then one round of the links in the READMEs of the
  Goose projects found;
- a repository already in packages/ is never reported; one decided in discovery/candidates.csv or
  reported by an earlier run is not reported again. An exclusion that can stop being true (an empty
  repository, one with no Goose source yet, a fork with no commits of its own) is looked at again
  when a search finds the repository again, at most every RECHECK_DAYS days.

What it decides is recorded in discovery/scouted.json. Delete a repository's record there to
have it looked at again. The report lists every candidate a person has to judge, each with its
evidence and a draft packages/<id>.toml whose kind, category, tags and description need filling
in. The --json output holds the same records for a later step, such as a model writing them.
"""

import argparse
import concurrent.futures as cf
import csv
import datetime
import json
import os
import pathlib
import re
import sys

sys.path.insert(0, str(pathlib.Path(__file__).parent))
import ghapi  # noqa: E402
import verify  # noqa: E402
from discover import CODE_QUERIES, REPO_QUERIES, TOPICS, add, links_in  # noqa: E402
from entries import ROOT, load_entries, load_meta  # noqa: E402
from triage import auto_reason, goose_sidecars  # noqa: E402

STATE = ROOT / "discovery" / "scouted.json"
CANDIDATES = ROOT / "discovery" / "candidates.csv"
FIRST_DISCOVERY = "2026-11-03"  # when candidates.csv was decided
RECHECK_DAYS = 28
RECHECKABLE = ("no .goose files", "fork of aardappel/goose with no commits", "empty repository",
               "not found", "inspect failed")
SOURCES = ("repos", "topics", "code", "forks", "tracker")
SELF = "safdafang/goose-index"  # this repository, which has the Goose topics too; GITHUB_REPOSITORY wins in Actions
INCIDENTAL_FILES, INCIDENTAL_OF = 3, 300  # up to this many .goose files among at least this many files
# Reading a repository takes 2-10 REST calls, and the workflow's token has 1,000 an hour. A run reads
# at most this many and queues the rest for the next run, so a backlog drains over a few weeks.
MAX_INSPECT = 250
# Sources in the order their finds turn out to be Goose projects; name search is mostly namesakes.
PRIORITY = ("topic", "code-search", "upstream", "readme-of", "fork-of", "repo-search")


def priority(sources):
    return min((i for i, p in enumerate(PRIORITY) for s in sources if s.startswith(p)), default=len(PRIORITY))
DETAILED = 40  # candidates shown with their evidence and draft; the rest as one line each
BODY_LIMIT = 60000  # GitHub refuses an issue body over 65536 characters
OSES = {"linux": r"\blinux\b|ubuntu|debian", "macos": r"\bmac ?os\b|\bosx\b|darwin|homebrew",
        "windows": r"\bwindows\b|msvc|win64"}
GENERIC_TOPICS = {"goose", "goose-lang", "goose-language", "gooselang", "goose-programming-language",
                  "goosel-lang", "goose-package", "goose-library", "programming-language", "systems-programming"}


def today():
    return datetime.datetime.now(datetime.timezone.utc).date()


def days_since(iso):
    return (today() - datetime.date.fromisoformat(iso[:10])).days


def github_key(url):
    m = re.match(r"https://github\.com/([^/]+/[^/]+)", url or "")
    return m.group(1).lower() if m else None


# ---- what is already known ---------------------------------------------------------------------

def in_index():
    """Repositories the index lists, at the address in the entry file and the one it moved to."""
    meta, out = load_meta(), set()
    for id_, (_, e) in load_entries().items():
        for url in (e.get("repo"), (meta.get(id_) or {}).get("canonical_repo")):
            if github_key(url):
                out.add(github_key(url))
    return out


def decided():
    """{repo: (decision, reason, checked)} from candidates.csv, then from earlier scout runs."""
    out = {}
    if CANDIDATES.exists():
        with CANDIDATES.open(encoding="utf-8", newline="") as f:
            for row in csv.DictReader(f):
                key = github_key(row["url"])
                if key:
                    out[key] = (row["decision"], row["why"], FIRST_DISCOVERY)
    for key, r in load_state()["repos"].items():
        out[key] = (r["decision"], r.get("reason", ""), r["checked"])
    return out


def load_state():
    if STATE.exists():
        return json.loads(STATE.read_text(encoding="utf-8"))
    return {"version": 1, "last_run": None, "repos": {}}


def worth_a_look(key, index, known):
    if key in index:
        return False
    prev = known.get(key)
    if prev is None:
        return True
    decision, reason, checked = prev
    return (decision == "excluded" and reason.startswith(RECHECKABLE) and days_since(checked) >= RECHECK_DAYS)


# ---- looking -----------------------------------------------------------------------------------

def collect(since, sources, failed):
    found, forks = {}, {}

    def searches(kind, queries):
        for label, q in queries:
            try:
                items = ghapi.search(kind, q)
            except RuntimeError as ex:
                failed.append(f"{label}: {ex}"[:300])
                continue
            print(f"{label}: {len(items)}", flush=True)
            for it in items:
                add(found, it["repository"]["full_name"] if kind == "code" else it["full_name"], label)

    if "repos" in sources:
        searches("repositories", [(f"repo-search:{q}", f"{q} pushed:>={since}") for q in REPO_QUERIES])
    if "topics" in sources:
        searches("repositories", [(f"topic:{t}", f"topic:{t} pushed:>={since}") for t in TOPICS])
    if "code" in sources:
        # code search has no date filter: everything it finds is checked against what is known
        searches("code", [(f"code-search:{q}", q) for q in CODE_QUERIES])
    if "forks" in sources:
        try:
            new_forks(found, forks, since)
        except RuntimeError as ex:
            failed.append(f"forks: {ex}"[:300])
    if "tracker" in sources:
        try:
            tracker(found, since)
        except RuntimeError as ex:
            failed.append(f"upstream tracker: {ex}"[:300])
    found.pop("_done", None)
    return found, forks


def new_forks(found, forks, since):
    """Forks of aardappel/goose created or pushed since the last run (forks list newest first)."""
    page = 1
    while True:
        batch = ghapi.rest("repos/aardappel/goose/forks", {"sort": "newest", "per_page": 100, "page": page}) or []
        for f in batch:
            if f["pushed_at"] >= since or f["created_at"] >= since:
                add(found, f["full_name"], "fork-of-aardappel/goose")
                if f["pushed_at"] <= f["created_at"]:
                    # never pushed to since it was made: nothing of its own to compare
                    forks[f["full_name"].lower()] = {"ahead_by": 0, "default_branch": f["default_branch"],
                                                     "recent_commits": []}
        if len(batch) < 100:
            break
        page += 1
    print(f"forks: {sum(1 for c in found.values() if 'fork-of-aardappel/goose' in c['sources'])} pushed or made since {since}")


def fork_detail(full, branch):
    try:
        cmp = ghapi.rest(f"repos/aardappel/goose/compare/master...{full.split('/')[0]}:{branch}")
    except RuntimeError as ex:
        # unknown is not "no commits": the fork goes to a person rather than being excluded
        return {"ahead_by": f"unknown ({str(ex)[:80]})", "default_branch": branch, "recent_commits": []}
    return {"ahead_by": cmp["ahead_by"] if cmp else None, "default_branch": branch,
            "recent_commits": [c["commit"]["message"].split("\n")[0] for c in (cmp or {}).get("commits", [])][-15:]}


DISCUSSIONS = """query { repository(owner: "aardappel", name: "goose") {
  discussions(first: 50, orderBy: {field: UPDATED_AT, direction: DESC}) {
    nodes { number updatedAt body comments(last: 50) { nodes { body replies(last: 20) { nodes { body } } } } } } } }"""


def tracker(found, since):
    """Repositories linked from upstream issues, pull requests, comments and discussions updated since."""
    texts = []
    for it in ghapi.paginate("repos/aardappel/goose/issues", {"state": "all", "since": since}):
        texts.append((f"upstream-{'pr' if 'pull_request' in it else 'issue'}#{it['number']}", it.get("body") or ""))
    for path in ("issues/comments", "pulls/comments"):
        for c in ghapi.paginate(f"repos/aardappel/goose/{path}", {"since": since}):
            num = (c.get("issue_url") or c.get("pull_request_url") or "").rsplit("/", 1)[-1]
            texts.append((f"upstream-comment#{num}", c.get("body") or ""))
    res = ghapi.graphql(DISCUSSIONS) or {}
    for n in (((res.get("data") or {}).get("repository") or {}).get("discussions") or {}).get("nodes", []):
        if n["updatedAt"] < since:
            break
        src = f"upstream-discussion#{n['number']}"
        texts.append((src, n["body"] or ""))
        for c in n["comments"]["nodes"]:
            texts += [(src, c["body"] or "")] + [(src, r["body"] or "") for r in c["replies"]["nodes"]]
    print(f"upstream texts updated since {since}: {len(texts)}")
    for src, text in texts:
        for repo in links_in(text):
            add(found, repo, src)


def inspect(names, forks):
    """verify.py's signals for each name, with the commits of any fork of aardappel/goose filled in."""
    signals = {n.lower(): s for n, s in verify.run(names, forks).items()}
    todo = {}
    for s in signals.values():
        meta = s.get("meta") or {}
        full = meta.get("nameWithOwner", "")
        if "fork_of_goose" in s and full.lower() not in forks:
            todo[full] = (meta.get("defaultBranchRef") or {}).get("name") or "master"
    with cf.ThreadPoolExecutor(6) as ex:
        for full, d in zip(todo, ex.map(fork_detail, todo, todo.values())):
            forks[full.lower()] = d
    for s in signals.values():
        if "fork_of_goose" in s:
            s["fork_of_goose"] = forks.get(s["meta"]["nameWithOwner"].lower(), {})
    return signals


def is_goose_project(s):
    return any(c["goose"] for c in s.get("goose_checked", []))


def incidental(s):
    """A big project with a Goose file or two (a syntax sample, a benchmark port) is not a Goose project."""
    n, total = s.get("n_goose", 0), s.get("n_files", 0)
    if s.get("fork_of_goose") is None and 0 < n <= INCIDENTAL_FILES and total >= INCIDENTAL_OF:
        return f"only incidental Goose code: {n} of {total} files"
    return None


# ---- drafting ----------------------------------------------------------------------------------

def entry_id(full):
    return re.sub(r"[^a-z0-9]+", "-", full.lower()).strip("-")


def draft(s, sources):
    """A record for the report and the JSON: the facts, a guessed draft entry, and why it guessed so."""
    m = s["meta"]
    full = m["nameWithOwner"]
    readme = s.get("readme_head") or ""
    side = goose_sidecars(s)
    repo_name = full.split("/", 1)[1]
    imports = re.findall(r'import (\w+) from "[^"]*/' + re.escape(repo_name) + r'(?:@[^"]*)?"', readme, re.I)
    # a library's root file names its namespace; a program's has `fn main`
    heads = [c for c in s.get("goose_checked", []) if c.get("goose")]
    spaces = [m.group(1) for c in heads for m in [re.search(r"^\s*namespace (\w+);", c.get("head", ""), re.M)] if m]
    mains = [c["path"] for c in heads if re.search(r"^\s*(export\s+)?fn main\s*\(", c.get("head", ""), re.M)]
    guesses = []
    if s.get("fork_of_goose") is not None:
        kind, category = "fork", "compilers-and-runtimes"
        guesses.append(f"a fork of aardappel/goose {s['fork_of_goose'].get('ahead_by')} commits ahead")
    elif imports:
        kind, category = "package", ""
        guesses.append(f"the README imports it as `{imports[0]}`")
    elif spaces and not mains:
        kind, category = "package", ""
        imports = spaces
        guesses.append(f"its root Goose file declares `namespace {spaces[0]};` and has no `fn main`")
    elif s.get("n_goose"):
        kind, category = "app", ""
        guesses.append(f"`fn main` in `{mains[0]}`" if mains else "Goose source with no namespace or import line")
    else:
        kind, category = ("editor", "editor-support") if s.get("has_package_json") else ("tool", "")
        guesses.append("no Goose source: " + ("an editor extension?" if s.get("has_package_json") else "a tool or a guide?"))
    plats = [o for o, pat in OSES.items() if re.search(pat, readme, re.I)]
    keys = {k for kv in side.values() for k in kv}
    topics = [t["topic"]["name"] for t in (m.get("repositoryTopics") or {}).get("nodes", [])]
    tags = [t for t in topics if t not in GENERIC_TOPICS and re.fullmatch(r"[a-z0-9][a-z0-9+.-]{0,29}", t)][:10]
    installs = sorted({re.sub(r"\s+", " ", l).strip()[:140] for l in readme.splitlines()
                       if re.search(r"\b(apt(-get)? install|brew install|vcpkg install)\b", l)})[:4]
    entry = {
        "id": entry_id(full), "name": m["nameWithOwner"].split("/", 1)[1], "kind": kind, "category": category,
        "tags": tags, "repo": f"https://github.com/{full}", "description": "", "platforms": plats,
        "import": {"name": imports[0]} if kind in ("package", "binding") and imports else None,
        "native": {"c": any(k.startswith("c_sources") for k in keys), "cmake": "cmake_target" in keys},
    }
    return {
        "repo": full, "url": f"https://github.com/{full}", "stars": m.get("stargazerCount"),
        "created": (m.get("createdAt") or "")[:10], "pushed": (m.get("pushedAt") or "")[:10],
        "license": (m.get("licenseInfo") or {}).get("spdxId"), "archived": m.get("isArchived"),
        "upstream_description": m.get("description"), "topics": topics,
        "goose_files": s.get("n_goose", 0), "files": s.get("n_files", 0),
        "goose_checked": [{k: c[k] for k in ("path", "goose", "strong", "weak")} for c in s.get("goose_checked", [])],
        "sidecars": side, "installs": installs, "fork": s.get("fork_of_goose"),
        "readme_excerpt": readme_text(readme, 700), "found_by": sources,
        "guesses": guesses, "draft": entry,
    }


def readme_text(text, n):
    text = re.sub(r"<[^>]+>|!\[[^\]]*\]\([^)]*\)", " ", text or "")
    return re.sub(r"\s+", " ", text).strip()[:n]


def toml_draft(e):
    q = json.dumps  # a JSON string is a valid TOML basic string
    lines = [f"id = {q(e['id'])}", f"name = {q(e['name'])}",
             f"kind = {q(e['kind'])}            # guess: package | binding | tool | editor | app | fork | learning-resource",
             f"category = {q(e['category'])}" + ("" if e["category"] else "              # one id from schema/categories.toml"),
             f"tags = {json.dumps(e['tags'])}", f"repo = {q(e['repo'])}",
             'description = ""         # one or two sentences in your own words',
             f"platforms = {json.dumps(e['platforms'])}" + ("   # from the README's wording: check" if e["platforms"] else "")]
    if e["import"]:
        lines += ["", "[import]", f"name = {q(e['import']['name'])}"]
    lines += ["", "[native]", f"c = {str(e['native']['c']).lower()}", f"cmake = {str(e['native']['cmake']).lower()}"]
    return "\n".join(lines)


# ---- the report --------------------------------------------------------------------------------

def code(text, limit=300):
    """Untrusted text as inline code: no markdown, links or @mentions get rendered from it."""
    text = re.sub(r"\s+", " ", str(text or "")).replace("`", "'").strip()[:limit]
    return f"`{text}`" if text else ""


def block(text, lang=""):
    return f"~~~~{lang}\n{str(text).replace('~~~~', '~ ~ ~ ~')}\n~~~~"


SOURCE_NAMES = (("repo-search", "repository search"), ("topic", "topic"), ("code-search", "code search"),
                ("fork-of", "fork"), ("upstream", "upstream tracker"), ("readme-of", "README link"))


def found_by(sources):
    names = [n for prefix, n in SOURCE_NAMES if any(s.startswith(prefix) for s in sources)]
    return ", ".join(names) or "?"


def line(r):
    bits = [f"★{r['stars']}", f"created {r['created']}", r["license"] or "no license",
            f"{r['goose_files']} .goose files", f"found by {found_by(r['found_by'])}"]
    if r["archived"]:
        bits.insert(0, "archived")
    return f"- [ ] **[{r['repo']}]({r['url']})** · " + " · ".join(bits)


def detail(r):
    out = [line(r)]
    if r["upstream_description"]:
        out.append(f"  {code(r['upstream_description'])}")
    ev = []
    for c in r["goose_checked"]:
        ev.append(f"`{c['path'].replace('`', '')}` {'reads as Goose' if c['goose'] else 'does not read as Goose'}")
    if r["sidecars"]:
        ev.append("sidecars " + ", ".join(f"`{p.replace('`', '')}`" for p in r["sidecars"]))
    if r["fork"]:
        commits = "; ".join(r["fork"].get("recent_commits", [])[-5:])
        ev.append(f"{r['fork'].get('ahead_by')} commits ahead: {code(commits, 400)}")
    body = [f"Evidence: {'; '.join(ev) or 'none read'}.", f"Guess: {'; '.join(r['guesses'])}."]
    if r["installs"]:
        body.append("README install lines: " + " ".join(code(i) for i in r["installs"]))
    body += ["", f"Draft `packages/{r['draft']['id']}.toml`:", "", block(toml_draft(r["draft"]), "toml")]
    if r["readme_excerpt"]:
        body += ["", "README, start:", "", block(r["readme_excerpt"], "text")]
    out += ["  <details><summary>Evidence and a draft entry</summary>", "", *body, "", "  </details>"]
    return "\n".join(out)


def report(records, since, failed, rechecked, queued=0):
    head = [
        f"Repositories with Goose evidence found since {since} that are in neither `packages/` nor "
        "`discovery/candidates.csv`, and were not reported before. Each has a draft entry: fill in `kind`, "
        "`category`, `tags` and `description` (in your own words), check `platforms` and `[native]`, and open "
        "a pull request with the file. For one that does not belong, do nothing: it will not be reported again.",
        "",
        f"Found by `scripts/scout.py`, run by the weekly scout workflow. {len(records)} to judge"
        + (f"; {rechecked} earlier exclusions looked at again" if rechecked else "") + "."
        + (f" {queued} more finds wait to be read: the next run starts with them." if queued else ""),
    ]
    if failed:
        head += ["", f"Some searches failed, so this list may be short ({len(failed)}):", ""]
        head += [f"- {code(f, 200)}" for f in failed[:10]]
    out, size = head + [""], 0
    for i, r in enumerate(records):
        part = detail(r) if i < DETAILED else line(r)
        size += len(part) + 1
        if size > BODY_LIMIT - 2000:
            out.append(f"\n…and {len(records) - i} more: see the `scout` artifact of the run.")
            break
        out.append(part)
    return "\n".join(out) + "\n"


# ---- main --------------------------------------------------------------------------------------

def main():
    ap = argparse.ArgumentParser(description="Look for Goose projects that appeared since the last look.")
    ap.add_argument("--report", required=True, help="markdown file for the issue; written only when there is something to judge")
    ap.add_argument("--json", help="also write the candidates as JSON here")
    ap.add_argument("--since", help="YYYY-MM-DD; default: two days before the last run, so runs overlap")
    ap.add_argument("--sources", default=",".join(SOURCES), help=f"comma-separated: {','.join(SOURCES)}")
    ap.add_argument("--dry-run", action="store_true", help="do not record anything in discovery/scouted.json")
    a = ap.parse_args()
    sources = {s.strip() for s in a.sources.split(",") if s.strip()}
    if sources - set(SOURCES):
        sys.exit(f"unknown sources: {sorted(sources - set(SOURCES))}")
    state = load_state()
    last = state.get("last_run") or FIRST_DISCOVERY
    since = a.since or (datetime.date.fromisoformat(last[:10]) - datetime.timedelta(days=2)).isoformat()

    failed = []
    found, forks = collect(since, sources, failed)
    index, known = in_index(), decided()
    # what an earlier run found but had no budget left to read comes first
    for key, c in state.get("pending", {}).items():
        e = found.setdefault(key, {"name": c["name"], "sources": []})
        e["sources"] += [x for x in c["sources"] if x not in e["sources"]]
    due = [k for k in found if worth_a_look(k, index, known)]
    due.sort(key=lambda k: (k not in state.get("pending", {}), priority(found[k]["sources"]), k))
    todo, queued = due[:MAX_INSPECT], due[MAX_INSPECT:]
    rechecked = sum(1 for k in todo if k in known)
    print(f"{len(found)} found, {len(due)} new or due for another look"
          + (f"; reading {len(todo)} now, {len(queued)} queued for the next run" if queued else ""), flush=True)
    signals = inspect([found[k]["name"] for k in todo], forks) if todo else {}

    # one round of README links from the Goose projects just found, as the first discovery did
    linked = {}
    for s in signals.values():
        if is_goose_project(s):
            for link in s.get("readme_links", []):
                if link.lower() not in found and worth_a_look(link.lower(), index, known):
                    add(linked, link, f"readme-of:{s['meta']['nameWithOwner']}")
    if linked:
        print(f"{len(linked)} more linked from their READMEs", flush=True)
        signals.update(inspect([c["name"] for c in linked.values()], forks))
        found.update(linked)

    stamp = today().isoformat()
    own = os.environ.get("GITHUB_REPOSITORY", SELF).lower()
    records = {}
    for key, s in sorted(signals.items()):
        reason = auto_reason(s, forks) or incidental(s)
        full = ((s.get("meta") or {}).get("nameWithOwner") or found.get(key, {}).get("name") or key)
        sources = found.get(key, {}).get("sources", [])
        if full.lower() in index or full.lower() == own:  # found under an old name, or this index itself
            continue
        if reason:
            state["repos"][full.lower()] = {"name": full, "decision": "excluded", "reason": reason, "checked": stamp}
            continue
        if full.lower() in records:  # the same repository found under its old and its new name
            records[full.lower()]["found_by"] += [x for x in sources if x not in records[full.lower()]["found_by"]]
            continue
        records[full.lower()] = draft(s, sources)
        state["repos"][full.lower()] = {"name": full, "decision": "review", "checked": stamp}
    records = list(records.values())
    # the strongest evidence first, then the most starred
    records.sort(key=lambda r: (-(r["goose_files"] > 0), -(r["stars"] or 0), r["repo"].lower()))

    print(f"{len(records)} to judge, {len(signals) - len(records)} excluded", flush=True)
    if a.json:
        pathlib.Path(a.json).write_text(json.dumps({"since": since, "failed": failed, "candidates": records},
                                                   indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    if records:
        pathlib.Path(a.report).write_text(report(records, since, failed, rechecked, len(queued)), encoding="utf-8")
    state["pending"] = {k: {"name": found[k]["name"], "sources": found[k]["sources"]} for k in sorted(queued)}
    if not a.dry_run:
        state["last_run"] = stamp
        state["repos"] = dict(sorted(state["repos"].items()))
        STATE.write_text(json.dumps(state, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    for f in failed:
        print(f"::warning::scout: {f}" if os.environ.get("GITHUB_ACTIONS") == "true" else f"failed: {f}")
    out = os.environ.get("GITHUB_OUTPUT")
    if out:
        with open(out, "a", encoding="utf-8") as f:
            f.write(f"count={len(records)}\nsince={since}\nfailed={len(failed)}\nqueued={len(queued)}\n")


if __name__ == "__main__":
    main()
