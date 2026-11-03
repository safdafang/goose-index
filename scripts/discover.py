"""Phase 1a: collect candidate repositories for the index from every source.

Writes discovery/raw/collected.json: {owner/repo (lowercase): {"name": ..., "sources": [...]}}.
Nothing here decides inclusion; verify.py does that by reading each repo's files.

    .venv/Scripts/python scripts/discover.py [--upstream ../upstream]
"""

import argparse
import json
import pathlib
import re
import subprocess
import sys

sys.path.insert(0, str(pathlib.Path(__file__).parent))
import ghapi  # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parent.parent
RAW = ROOT / "discovery" / "raw"
SINCE = "2026-10-01"  # Goose went public in early October 2026; nothing older is pushed for it

REPO_QUERIES = [
    "goose language", "goose lang", "goose-lang", "goose programming language",
    "goose package", "goose library", "goose bindings", "goose binding", "goose port",
    "ported to goose", "written in goose", "goose wrapper", "goose ffi", "goose extern",
    "goose module", "goose stdlib", "goose compiler", "goose lsp", "goose tree-sitter",
    "goose syntax", "goose editor", "goose plugin", "goose example", "goose examples",
    "goose tutorial", "goose benchmark", "goose game", "goose raylib", "goose sdl",
    "goose sqlite", "goose http", "goose json", "goose tls", "goose crypto",
    "goose compress", "goose zip", "goose ui", "goose gfx", "goose math", "goose test",
    "goose fmt", "goose docs", "goose wasm", "goose cli", "goose parser", "goose regex",
    "goose aardappel", "aardappel in:readme", "aardappel/goose in:readme",
    "goose in:name", "goose in:description",
    "goose-", "-goose", "goose_", "_goose", "goos in:name",
    "gander", "honk in:name", "gosling in:name", "egg in:name goose",
]
TOPICS = ["goose-lang", "goose-language", "goose-package", "goose-programming-language",
          "goose-library", "goose-programming", "goose-lang-package", "goselang", "gooselang"]
CODE_QUERIES = [
    '"import std" extension:goose',
    '"import os" extension:goose',
    '"extern fn" extension:goose',
    'namespace extension:goose',
    'from extension:goose "github.com"',
    'fn extension:goose size:<400',
    'fn extension:goose size:400..1500',
    'fn extension:goose size:1500..5000',
    'fn extension:goose size:>5000',
    'let extension:goose',
    'c_sources extension:build',
    'cmake_target extension:build',
    'c_libs extension:build',
    '"aardappel/goose" extension:md',
    '"aardappel.github.io/goose"',
    '"import std;" extension:md',
    '"goose build" "goose run" extension:md',
]
# Everything already named in GAPS.md / NOTES.md, so nothing found by hand gets lost.
SEEDS = """
kaitk/goose-http kaitk/plod kaitk/goose-tls kaitk/goose-sqlite kaitk/goose-postgres kaitk/goose-hash
kaitk/goose-compress kaitk/goose-acme kaitk/goose-ngfx shetautnetjer/goose-sqlite SorinS/gslib
SorinS/httpgoose SorinS/tlsgoose SorinS/x509goose SorinS/asn1goose SorinS/bigmongoose SorinS/ldapgoose
SorinS/sshgoose SorinS/yamlgoose jdrobertso/net clintecker/goose-date clintecker/goose-file
clintecker/goose-inflate clintecker/goose-layout clintecker/goose-sha256 clintecker/goose-tar
clintecker/goose-zip BHare1985/goose-libdeflate guillochon/goose-fft guillochon/goose-linalg
guillochon/goose-random paulosuzart/gooseneck sstadick/goosopt sstadick/goosimd sstadick/goosdoc
sstadick/goostr ZHENGSY/goose-tui ZHENGSY/goose-zed akeit0/mygoose akeit0/goose-lab Swoorup/ferrous-goose
okay-effects/okay-goose mas-bandwidth/serialize.goose Macho0x/goose-logger Macho0x/goose-ethereum
Macho0x/goose-hyperliquid Nurysso/terence elcharitas/goose_bio tacf/fastnoiselite-goose lamweilun/raygoose
Alexxzz/raylib-goose flakesonnix/goose-raylib exaroth/goose-lang.vim exaroth/coc-goose epidemicz/fresh-goose
a55uka/zed-goose RomanPro100/goose-zed-extension VPagani/zed-goose rx-bob/goosefmt rx-bob/goosetest
innomon/goose-sql-p2p aardappel/goose aardappel/goose_gfx aardappel/goose_physics aardappel/once-campfire-goose
binji/goose_gfx2d robtandy/goose.go compusophy/goose-wasm flisk-sh/codeql-goose jspaulsen/goose-py
aciru4L/barn Decryptu/goosedex calpeyser/goose-evaluations AnugunjNaman/gander badman594/glog
dantje/weld glebrossev/goose-mini-browser Grumbash/goose-mini-browser kokasikhorik-bot/GooseCraft
lazychicken/goose-commands noonien/AlchemistsSort aguspiza/raytracing-goose xvolks/brainfuck-goose
yujieteo/goosestrike yujieteo/skein bashar-al-agha/arwad appdoze/gust SAM-tak/rhat scottc/goose-roc
akari-iku/goose-playground kyambuthia/ur-goose-is-cooked subhdotsol/goose-guide
LightSpeedC/20261101-research-goose-language MDA2AV/HttpArena paulosuzart/awesome RomanPro100/goose-tree-sitter
Swoorup/ferrous-goose Tryptophan/gooseboard mohamadzoh/phonelib Miyamoto-Renya/BCI-lang
""".split()


def add(found, full_name, source):
    if not full_name or "/" not in full_name:
        return
    full_name = full_name.strip().strip("/").removesuffix(".git")
    key = full_name.lower()
    e = found.setdefault(key, {"name": full_name, "sources": []})
    if source not in e["sources"]:
        e["sources"].append(source)


LINK = re.compile(r"github\.com/([A-Za-z0-9][A-Za-z0-9-]{0,38})/([A-Za-z0-9._-]{1,100})")
NOT_REPOS = {"user-attachments", "orgs", "settings", "sponsors", "features", "topics", "apps", "marketplace", "login"}


def links_in(text):
    for owner, repo in LINK.findall(text or ""):
        repo = re.sub(r"\.(git|md)$", "", repo).rstrip(".")
        if owner.lower() in NOT_REPOS or not repo:
            continue
        yield f"{owner}/{repo}"


def _searches(found, kind, queries, save):
    """Run each query once; a query already in found["_done"] is skipped, so a rerun resumes."""
    done = found.setdefault("_done", [])
    for label, q in queries:
        if label in done:
            continue
        items = ghapi.search(kind, q)
        print(f"{label}: {len(items)}", flush=True)
        for it in items:
            add(found, it["repository"]["full_name"] if kind == "code" else it["full_name"], label)
        done.append(label)
        save()


def from_repo_search(found, save):
    _searches(found, "repositories",
              [(f"repo-search:{q}", f"{q} pushed:>={SINCE}") for q in REPO_QUERIES]
              + [(f"topic:{t}", f"topic:{t}") for t in TOPICS], save)


def from_code_search(found, save):
    _searches(found, "code", [(f"code-search:{q}", q) for q in CODE_QUERIES], save)


# Code search caps a query at 1000 files, and a few big repos (the compiler, its forks,
# large packages) fill that with their own files. Excluding them and slicing by file
# size lets the small repos through.
HEAVY = ["aardappel/goose", "appdoze/gust", "kaitk/plod", "kaitk/goose-http", "SorinS/gslib",
         "elcharitas/goose_bio", "yujieteo/skein", "rx-bob/goosetest", "akeit0/goose-lab"]
BANDS = ["<150", "150..300", "300..600", "600..1000", "1000..1600", "1600..2500", "2500..4000",
         "4000..7000", "7000..12000", "12000..25000", ">25000"]


def from_deep_code_search(found, save):
    minus = " ".join(f"-repo:{r}" for r in HEAVY)
    queries = [(f"code-deep:fn size:{b}", f"fn extension:goose size:{b} {minus}") for b in BANDS]
    queries += [(f"code-deep:{t}", f"{t} extension:goose {minus}") for t in ("namespace", '"import std"', "import", "struct", "print")]
    queries += [("code-deep:goose.build", f"c_sources extension:build {minus}")]
    _searches(found, "code", queries, save)


def from_forks(found):
    forks = ghapi.paginate("repos/aardappel/goose/forks", {"sort": "newest"})
    print(f"forks: {len(forks)}")
    detail = {}
    for f in forks:
        owner, br = f["owner"]["login"], f["default_branch"]
        cmp = ghapi.rest(f"repos/aardappel/goose/compare/master...{owner}:{br}")
        ahead = cmp["ahead_by"] if cmp else None
        subjects = [c["commit"]["message"].split("\n")[0] for c in (cmp or {}).get("commits", [])][-15:]
        detail[f["full_name"].lower()] = {"ahead_by": ahead, "default_branch": br, "recent_commits": subjects}
        add(found, f["full_name"], "fork-of-aardappel/goose")
    (RAW / "forks.json").write_text(json.dumps(detail, indent=1), encoding="utf-8")


DISCUSSIONS = """query($cursor: String) { repository(owner: "aardappel", name: "goose") {
  discussions(first: 50, after: $cursor) { pageInfo { hasNextPage endCursor }
    nodes { number body comments(first: 50) { nodes { body replies(first: 50) { nodes { body } } } } } } } }"""


def from_upstream_tracker(found):
    texts = []
    for it in ghapi.paginate("repos/aardappel/goose/issues", {"state": "all"}):
        kind = "pr" if "pull_request" in it else "issue"
        texts.append((f"upstream-{kind}#{it['number']}", it.get("body") or ""))
    for c in ghapi.paginate("repos/aardappel/goose/issues/comments"):
        num = c["issue_url"].rsplit("/", 1)[-1]
        texts.append((f"upstream-comment#{num}", c.get("body") or ""))
    for c in ghapi.paginate("repos/aardappel/goose/pulls/comments"):
        num = c["pull_request_url"].rsplit("/", 1)[-1]
        texts.append((f"upstream-review#{num}", c.get("body") or ""))
    cursor = None
    while True:
        res = ghapi.graphql(DISCUSSIONS, **({"cursor": cursor} if cursor else {}))
        d = res["data"]["repository"]["discussions"]
        for n in d["nodes"]:
            src = f"upstream-discussion#{n['number']}"
            texts.append((src, n["body"]))
            for c in n["comments"]["nodes"]:
                texts.append((src, c["body"]))
                for r in c["replies"]["nodes"]:
                    texts.append((src, r["body"]))
        if not d["pageInfo"]["hasNextPage"]:
            break
        cursor = d["pageInfo"]["endCursor"]
    print(f"upstream texts: {len(texts)}")
    for src, text in texts:
        for repo in links_in(text):
            add(found, repo, src)


def from_upstream_docs(found, upstream):
    if not upstream.exists():
        print(f"no upstream clone at {upstream}, skipping docs")
        return
    out = subprocess.run(["git", "-C", str(upstream), "grep", "-h", "-o", "-E", r"github\.com/[A-Za-z0-9._/-]+",
                          "--", "docs", "README.md", "vscode", "tree-sitter", "src/blessed.txt"],
                         capture_output=True, text=True, encoding="utf-8").stdout
    for repo in links_in(out):
        add(found, repo, "upstream-docs")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--upstream", default=str(ROOT.parent / "upstream"))
    ap.add_argument("--only", help="comma list of: seeds,repos,code,deep,forks,tracker,docs")
    ap.add_argument("--out", default="collected.json", help="file under discovery/raw to add to")
    a = ap.parse_args()
    RAW.mkdir(parents=True, exist_ok=True)
    out = RAW / a.out
    found = json.loads(out.read_text(encoding="utf-8")) if out.exists() else {}
    steps = (a.only or "seeds,docs,tracker,forks,repos,code").split(",")

    def save():
        out.write_text(json.dumps(found, indent=1, sort_keys=True), encoding="utf-8")

    for step in steps:
        if step == "seeds":
            for s in SEEDS:
                add(found, s, "seed:GAPS.md")
        elif step == "docs":
            from_upstream_docs(found, pathlib.Path(a.upstream))
        elif step == "tracker":
            from_upstream_tracker(found)
        elif step == "forks":
            from_forks(found)
        elif step == "repos":
            from_repo_search(found, save)
        elif step == "code":
            from_code_search(found, save)
        elif step == "deep":
            from_deep_code_search(found, save)
        save()
        print(f"after {step}: {len(found) - 1} candidates")


if __name__ == "__main__":
    main()
