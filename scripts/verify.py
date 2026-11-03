"""Phase 1b: read each candidate's files and record evidence of Goose.

Reads discovery/raw/collected.json, writes discovery/raw/signals.json. Each repo gets:
metadata (GraphQL), its file tree, the first lines of up to two .goose files
checked for Goose syntax, every sidecar's keys, and the GitHub links in its
README. --snowball adds those README links as new candidates and repeats.

    .venv/Scripts/python scripts/verify.py [--snowball 2]
"""

import argparse
import base64
import concurrent.futures as cf
import json
import pathlib
import re
import sys

sys.path.insert(0, str(pathlib.Path(__file__).parent))
import ghapi  # noqa: E402
from discover import add, links_in  # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parent.parent
RAW = ROOT / "discovery" / "raw"

FIELDS = """
  nameWithOwner url description homepageUrl isFork isArchived isMirror stargazerCount
  createdAt pushedAt parent { nameWithOwner }
  licenseInfo { spdxId }
  repositoryTopics(first: 20) { nodes { topic { name } } }
  defaultBranchRef { name target { ... on Commit { committedDate } } }
  tags: refs(refPrefix: "refs/tags/", first: 100, orderBy: {field: TAG_COMMIT_DATE, direction: DESC}) {
    totalCount nodes { name } }
  releases(first: 1, orderBy: {field: CREATED_AT, direction: DESC}) { nodes { tagName isPrerelease } }
  top: object(expression: "HEAD:") { ... on Tree { entries { name type } } }
"""

# Goose syntax: one strong line form, or two weaker ones. Checked on file content, never on names.
STRONG = [re.compile(p, re.M) for p in (
    r'^\s*import [A-Za-z_][\w.]*( from "[^"]+")?;\s*$',
    r'^\s*namespace [A-Za-z_]\w*;\s*$',
    r'\b(u8|i64|i32|u32|f64|f32)\[(>?\.\.|:)\]',
    r'^\s*(extern|export|inline|recursive|thread_fn|simd|checkfree)\s+fn\b',
)]
WEAK = [re.compile(p, re.M) for p in (
    r'^\s*fn \w+(<[^>]*>)?\([^)]*\)( -> [^{]+)? \{',
    r'^\s*(let|var) \w+(: [^=]+)? = ',
    r'\b(guard|match|each_\w+|push\(|print\()',
    r'->\s*(i64|u8|bool|f64)\b',
)]


def goose_score(text):
    strong = sum(1 for p in STRONG if p.search(text))
    weak = sum(1 for p in WEAK if p.search(text))
    return strong, weak


def is_goose(text):
    s, w = goose_score(text)
    return s >= 2 or (s >= 1 and w >= 2)


def sidecar_keys(text):
    # values may be lists spread over several lines: `c_sources = [\n "a.c",\n "b.c"\n];`
    keys = {}
    body = re.sub(r"//[^\n]*", "", text)
    for stmt in body.split(";"):
        m = re.match(r"\s*([a-z_]+)\s*=\s*(.*)", stmt, re.S)
        if m:
            keys[m.group(1)] = re.sub(r"\s+", " ", m.group(2)).strip()
    return keys


def fetch_meta(names):
    parts = []
    for i, n in enumerate(names):
        owner, repo = n.split("/", 1)
        parts.append(f'r{i}: repository(owner: {json.dumps(owner)}, name: {json.dumps(repo)}) {{ {FIELDS} }}')
    q = "query {" + "\n".join(parts) + "}"
    try:
        res = ghapi.graphql(q, partial=True)
    except RuntimeError:
        return {n: FAILED for n in names}
    data = res.get("data") or {}
    # only a NOT_FOUND error on that alias means the repository is gone; anything
    # else leaves it FAILED, to be inspected again on the next run
    missing = {e["path"][0] for e in res.get("errors", []) if e.get("type") == "NOT_FOUND" and e.get("path")}
    return {n: data.get(f"r{i}") if data.get(f"r{i}") is not None or f"r{i}" in missing else FAILED
            for i, n in enumerate(names)}


FAILED = "FAILED"


def raw_file(full, path, ref):
    res = ghapi.rest(f"repos/{full}/contents/{path}", {"ref": ref})
    if not res or isinstance(res, list) or res.get("encoding") != "base64":
        return None
    return base64.b64decode(res["content"]).decode("utf-8", "replace")


def readme(full):
    res = ghapi.rest(f"repos/{full}/readme")
    if not res or res.get("encoding") != "base64":
        return ""
    return base64.b64decode(res["content"]).decode("utf-8", "replace")


def inspect(full, meta, forks):
    if meta == FAILED:
        return {"meta": None, "error": "inspect failed: metadata query did not complete"}
    sig = {"meta": meta}
    if meta is None:
        sig["error"] = "not found (deleted, private or renamed away)"
        return sig
    full = meta["nameWithOwner"]
    br = (meta.get("defaultBranchRef") or {}).get("name")
    if not br:
        sig["error"] = "empty repository"
        return sig
    text = readme(full)
    sig["readme_head"] = text[:6000]
    sig["readme_links"] = sorted(set(links_in(text)))
    sig["readme_mentions_goose_lang"] = bool(re.search(
        r"aardappel/goose|aardappel\.github\.io/goose|Goose (programming )?language|goose-lang|\.goose\b", text, re.I))
    if full.lower() in forks or (meta.get("parent") or {}).get("nameWithOwner", "").lower() == "aardappel/goose":
        sig["fork_of_goose"] = forks.get(full.lower(), {})
        return sig  # a compiler checkout; its tree says nothing about a package
    tree = ghapi.rest(f"repos/{full}/git/trees/{br}", {"recursive": "1"}) or {}
    paths = [t["path"] for t in tree.get("tree", []) if t["type"] == "blob"]
    sig["truncated_tree"] = tree.get("truncated", False)
    sig["n_files"] = len(paths)
    goose = [p for p in paths if p.endswith(".goose")]
    builds = [p for p in paths if p.endswith(".build")]
    sig["n_goose"] = len(goose)
    sig["goose_paths"] = goose
    sig["c_files"] = sum(1 for p in paths if p.endswith((".c", ".h")))
    sig["has_cmakelists"] = any(p.endswith("CMakeLists.txt") for p in paths)
    sig["has_package_json"] = "package.json" in paths
    sig["has_cargo"] = "Cargo.toml" in paths
    sig["has_go_mod"] = "go.mod" in paths
    sig["sql_migrations"] = sum(1 for p in paths if p.endswith(".sql"))
    # the shortest paths first: the package entry file is usually at the root
    checked = []
    for p in sorted(goose, key=lambda p: (p.count("/"), len(p)))[:2]:
        body = raw_file(full, p, br) or ""
        s, w = goose_score(body)
        checked.append({"path": p, "strong": s, "weak": w, "goose": is_goose(body), "head": body[:400]})
    sig["goose_checked"] = checked
    sig["sidecars"] = {}
    for p in sorted(builds, key=lambda p: (p.count("/"), len(p)))[:6]:
        body = raw_file(full, p, br) or ""
        sig["sidecars"][p] = sidecar_keys(body)
    return sig


def run(names, forks):
    out = {}
    batches = [names[i:i + 25] for i in range(0, len(names), 25)]
    metas = {}
    for b in batches:
        metas.update(fetch_meta(b))
    with cf.ThreadPoolExecutor(6) as ex:
        futs = {ex.submit(inspect, n, metas.get(n), forks): n for n in names}
        for i, f in enumerate(cf.as_completed(futs)):
            n = futs[f]
            try:
                out[n] = f.result()
            except Exception as e:  # keep going; record the failure as evidence
                out[n] = {"meta": metas.get(n), "error": f"inspect failed: {e}"}
            if i % 25 == 0:
                print(f"  {i}/{len(names)}", flush=True)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--snowball", type=int, default=0, help="rounds of following README links")
    ap.add_argument("--retry-missing", action="store_true",
                    help="inspect again repos recorded as not found (an older run's failures were recorded so)")
    ap.add_argument("--refresh-sidecars", action="store_true",
                    help="re-read and re-parse the .build files of repos already inspected")
    a = ap.parse_args()
    if a.refresh_sidecars:
        refresh_sidecars()
        return
    collected = json.loads((RAW / "collected.json").read_text(encoding="utf-8"))
    sig_path = RAW / "signals.json"
    signals = json.loads(sig_path.read_text(encoding="utf-8")) if sig_path.exists() else {}
    forks_path = RAW / "forks.json"
    forks = json.loads(forks_path.read_text(encoding="utf-8")) if forks_path.exists() else {}
    for rnd in range(a.snowball + 1):
        # network failures are not evidence: inspect those again
        retry = ("inspect failed", "not found") if a.retry_missing else ("inspect failed",)
        todo = [e["name"] for k, e in collected.items() if not k.startswith("_")
                and (k not in signals or signals[k].get("error", "").startswith(retry))]
        print(f"round {rnd}: {len(todo)} to inspect", flush=True)
        if todo:
            res = run(todo, forks)
            for n, s in res.items():
                signals[n.lower()] = s
            sig_path.write_text(json.dumps(signals, indent=1, sort_keys=True), encoding="utf-8")
        if rnd == a.snowball:
            break
        new = 0
        for k, s in list(signals.items()):
            # follow links only from repos whose own source is verified Goose: a README
            # that merely mentions Goose (an awesome list, a raylib bindings table) links
            # to hundreds of unrelated projects
            if any(c["goose"] for c in s.get("goose_checked", [])):
                for link in s.get("readme_links", []):
                    if link.lower() not in collected:
                        new += 1
                    add(collected, link, f"readme-of:{s['meta']['nameWithOwner']}")
        (RAW / "collected.json").write_text(json.dumps(collected, indent=1, sort_keys=True), encoding="utf-8")
        print(f"round {rnd}: {new} new links from Goose READMEs", flush=True)
        if not new:
            break


def refresh_sidecars():
    sig_path = RAW / "signals.json"
    signals = json.loads(sig_path.read_text(encoding="utf-8"))

    def goose_side(s):
        # only foo.build beside foo.goose is a Goose sidecar; meson.build and moz.build are not
        goose = set(s.get("goose_paths", []))
        truncated = s.get("n_goose", 0) > len(goose)
        return [p for p in s.get("sidecars") or {} if truncated or p[:-len(".build")] + ".goose" in goose]

    def one(item):
        key, s = item
        m = s.get("meta") or {}
        br = (m.get("defaultBranchRef") or {}).get("name")
        side = dict(s["sidecars"])
        side.update({p: sidecar_keys(raw_file(m["nameWithOwner"], p, br) or "") for p in goose_side(s)})
        return key, side

    todo = [(k, s) for k, s in signals.items() if goose_side(s)]
    with cf.ThreadPoolExecutor(6) as ex:
        for key, side in ex.map(one, todo):
            signals[key]["sidecars"] = side
    sig_path.write_text(json.dumps(signals, indent=1, sort_keys=True), encoding="utf-8")
    print(f"re-read the sidecars of {len(todo)} repos")


if __name__ == "__main__":
    main()
