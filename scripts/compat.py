"""Build-test entries against the latest Goose release.

Results: pass (goose build works), check (goose check passes, the build fails),
fail (cannot be fetched, resolved or typechecked), skip (not built).

    python scripts/compat.py install DIR
    python scripts/compat.py libs
    python scripts/compat.py run --out F [--shard 0/3] [--only id,id]
    python scripts/compat.py merge F... [--run-url URL]
"""

import argparse
import datetime
import hashlib
import json
import os
import pathlib
import platform
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import time
import tomllib
import zipfile

ROOT = pathlib.Path(__file__).resolve().parent.parent
OS = {"Linux": "linux", "Darwin": "macos", "Windows": "windows"}[platform.system()]
UPSTREAM = "aardappel/goose"
# goose ends this error with the import line to add
HINT = re.compile(r'^\s*import ([A-Za-z_]\w*) from "([^"]+)";\s*$', re.M)
ANSI = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")
CHECK_TIMEOUT, BUILD_TIMEOUT = 600, 1500
BASE = None


def entries():
    out = {}
    for p in sorted((ROOT / "packages").glob("*.toml")):
        with p.open("rb") as f:
            out[p.stem] = tomllib.load(f)
    return out


def meta():
    p = ROOT / "data" / "meta.json"
    return json.loads(p.read_text(encoding="utf-8"))["entries"] if p.exists() else {}


def asset_suffix():
    if OS == "windows":
        return "windows-x64.zip"
    if OS == "macos":
        return "macos-arm64.tar.gz" if platform.machine() in ("arm64", "aarch64") else "macos-x64.tar.gz"
    return "linux-x64.tar.gz"


def install(dest):
    dest = pathlib.Path(dest).resolve()
    dest.mkdir(parents=True, exist_ok=True)
    tag = subprocess.run(["gh", "release", "view", "-R", UPSTREAM, "--json", "tagName", "-q", ".tagName"],
                         check=True, capture_output=True, text=True).stdout.strip()
    subprocess.run(["gh", "release", "download", tag, "-R", UPSTREAM, "-p", f"*-{asset_suffix()}",
                    "-D", str(dest), "--clobber"], check=True)
    archive = next(dest.glob(f"*-{asset_suffix()}"))
    if archive.suffix == ".zip":
        with zipfile.ZipFile(archive) as z:
            z.extractall(dest)
    else:
        with tarfile.open(archive) as t:
            t.extractall(dest, filter="tar")
    exe = next(p for p in dest.rglob("goose.exe" if OS == "windows" else "goose") if p.is_file())
    exe.chmod(0o755)
    (dest / "VERSION").write_text(tag, encoding="utf-8")
    print(exe.parent)


def goose_version():
    exe = shutil.which("goose")
    if not exe:
        sys.exit("goose is not on PATH: run `compat.py install DIR` and add the directory it prints")
    v = pathlib.Path(exe).resolve().parent.parent / "VERSION"
    return exe, (v.read_text(encoding="utf-8").strip() if v.exists() else "unknown")


def libs():
    seen = []
    for e in entries().values():
        for lib in (e.get("native", {}).get("system_libs") or {}).get(OS, []):
            if lib not in seen:
                seen.append(lib)
    print("\n".join(seen))


def sh(cmd, cwd, env, timeout):
    t0 = time.time()
    try:
        r = subprocess.run(cmd, cwd=cwd, env=env, capture_output=True, text=True,
                           encoding="utf-8", errors="replace", timeout=timeout)
        out, rc = (r.stdout or "") + (r.stderr or ""), r.returncode
    except subprocess.TimeoutExpired as ex:
        out = ex.stdout or ""
        if isinstance(out, bytes):
            out = out.decode("utf-8", "replace")
        out += f"\n(timed out after {timeout}s)"
        rc = -1
    out = ANSI.sub("", out)
    return rc, (tidy(out, BASE) if BASE else out), round(time.time() - t0, 1)


def first_error(log):
    """The first real error line of a build log."""
    lines = [l.strip() for l in log.splitlines() if l.strip()]
    for pat in (r"undefined reference|unresolved external|\berror\b\s*[:A-Z]|fatal error",
                r"timed out|not found|cannot|no such", r"failed"):
        for line in lines:
            if re.search(pat, line, re.I) and not re.match(r"(building|compiling) .* failed", line):
                return line[:240]
    return lines[-1][:240] if lines else ""


def tidy(log, base):
    """Strip the runner's temporary paths from a log."""
    for b in {str(base), str(base).replace("\\", "/"), os.path.realpath(base)}:
        log = log.replace(b + "/home/pkg/", "").replace(b + "\\home\\pkg\\", "").replace(b, "")
    return re.sub(r"(/private)?/var/folders/[^ ]*?/goose-compat-[^/ ]+|[A-Z]:[\\/]Users[\\/][^ ]*?goose-compat-[^\\/ ]+", "", log)


def result(status, ref, stage, log="", **extra):
    r = {"status": status, "ref": ref, "stage": stage}
    if log:
        r["detail"] = first_error(log)
        r["log"] = log[-3000:]
    r.update(extra)
    return r


def plan(e, m):
    """What to do with an entry: ('skip', reason) | ('probe', ref) | ('program', ref)."""
    c = e.get("compat") or {}
    if c.get("skip"):
        return "skip", c["skip"]
    if not e.get("repo"):
        return "skip", "not a repository"
    if not m or not m.get("exists"):
        return "skip", "the repository is unavailable"
    ref = m.get("latest_tag") or m.get("default_branch")
    if e["kind"] in ("package", "binding"):
        if (e.get("import") or {}).get("subdir"):
            return "skip", "the package lives in a subdirectory, which Goose cannot import by URL yet"
        return "probe", ref
    if e["kind"] in ("app", "tool") or c.get("entry"):
        return "program", ref
    kind = e["kind"].replace("-", " ")
    return "skip", f"{'an' if kind[0] in 'aeiou' else 'a'} {kind} is not built"


def run_probe(e, ref, work, env, exe):
    imp = e["import"]
    source = (imp.get("path") or e["repo"].removeprefix("https://")) + "@" + ref
    lines = [f'import {imp["name"]} from "{source}";']
    added = []
    work.mkdir(parents=True, exist_ok=True)
    probe = work / "probe.goose"
    for _ in range(12):
        probe.write_text("\n".join(lines) + "\n\nfn main() {}\n", encoding="utf-8")
        rc, log, secs = sh([exe, "check", "probe.goose"], work, env, CHECK_TIMEOUT)
        if rc == 0:
            break
        new = [(n, s) for n, s in HINT.findall(log) if (n, s) not in added and n != imp["name"]]
        if not new:
            return result("fail", ref, "check", log, requires=req(added))
        for n, s in new:
            added.append((n, s))
            lines.append(f'import {n} from "{s}";')
    else:
        return result("fail", ref, "check", log, requires=req(added))
    out = work / ("probe.exe" if OS == "windows" else "probe")
    rc, log, secs = sh([exe, "build", "-o", str(out), "probe.goose"], work, env, BUILD_TIMEOUT)
    if rc == 0:
        return result("pass", ref, "build", requires=req(added), seconds=secs)
    return result("check", ref, "build", log, requires=req(added))


def req(added):
    return [{"name": n, "source": s} for n, s in added]


NOT_ENTRY = re.compile(r"(^|[/_.-])(tests?|examples?|samples?|bench(mark)?s?|spike|experiments?|conformance|"
                       r"results|vendor|third_party|deps|docs?|fixtures?|scratch|tools?)([/_.-]|$)", re.I)


def find_entry(repo_dir, e):
    """The program's root .goose file with `fn main`, or None when it is ambiguous."""
    words = set(re.split(r"[^a-z0-9]+", e["repo"].rsplit("/", 1)[-1].lower())) - {"goose", ""}
    cands = []
    for p in repo_dir.rglob("*.goose"):
        rel = p.relative_to(repo_dir).as_posix()
        if rel.count("/") > 2 or NOT_ENTRY.search(rel) or rel.startswith("."):
            continue
        try:
            text = p.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        if re.search(r"^\s*(export\s+)?fn main\s*\(", text, re.M):
            cands.append(p)
    if len(cands) <= 1:
        return cands[0] if cands else None

    def rank(p):
        stem = p.stem.lower()
        return (0 if stem in words or stem.replace("_", "-") in e["repo"].lower() else
                1 if stem in ("main", "app") else 2,
                p.relative_to(repo_dir).as_posix().count("/"))
    cands.sort(key=rank)
    return cands[0] if rank(cands[0]) != rank(cands[1]) else None


def run_program(e, ref, work, env, exe):
    repo_dir = work / "repo"
    work.mkdir(parents=True, exist_ok=True)
    rc, log, _ = sh(["git", "clone", "--depth", "1", "--branch", ref, "--recurse-submodules",
                     "--shallow-submodules", e["repo"] + ".git", str(repo_dir)], work, env, 600)
    if rc != 0:
        return result("fail", ref, "clone", log)
    entry = (e.get("compat") or {}).get("entry")
    path = repo_dir / entry if entry else find_entry(repo_dir, e)
    if not path or not path.exists():
        return result("skip", ref, "entry", reason="no single program file with `fn main` was found "
                                                   "(a library, a WebAssembly module, or several programs); "
                                                   "compat.entry in the entry file can name one")
    rel = path.relative_to(repo_dir).as_posix()
    rc, log, _ = sh([exe, "check", path.name], path.parent, env, CHECK_TIMEOUT)
    if rc != 0:
        return result("fail", ref, "check", log, entry=rel)
    out = work / ("out.exe" if OS == "windows" else "out")
    rc, log, secs = sh([exe, "build", "-o", str(out), path.name], path.parent, env, BUILD_TIMEOUT)
    if rc == 0:
        return result("pass", ref, "build", entry=rel, seconds=secs)
    return result("check", ref, "build", log, entry=rel)


def shard_of(id_, n):
    return int(hashlib.sha1(id_.encode()).hexdigest(), 16) % n


def run(out_path, shard, only):
    exe, version = goose_version()
    k, n = (int(x) for x in shard.split("/"))
    ids = {i.strip() for i in only.split(",") if i.strip()} if only else None
    es, ms = entries(), meta()
    todo = [i for i in es if (ids is None or i in ids) and shard_of(i, n) == k]
    global BASE
    base = BASE = pathlib.Path(tempfile.mkdtemp(prefix="goose-compat-"))
    env = dict(os.environ, GOOSE_HOME=str(base / "home"))
    results = {}
    for num, id_ in enumerate(todo, 1):
        e, m = es[id_], ms.get(id_)
        what, arg = plan(e, m)
        t0 = time.time()
        try:
            if what == "skip":
                results[id_] = {"status": "skip", "reason": arg}
            elif what == "probe":
                results[id_] = run_probe(e, arg, base / id_, env, exe)
            else:
                results[id_] = run_program(e, arg, base / id_, env, exe)
        except Exception as ex:
            results[id_] = {"status": "fail", "stage": "runner", "detail": f"runner error: {ex}"[:240]}
        r = results[id_]
        print(f"[{num}/{len(todo)}] {id_}: {r['status']} {r.get('detail') or r.get('reason') or ''}"[:300]
              + f" ({time.time() - t0:.0f}s)", flush=True)
        shutil.rmtree(base / id_, ignore_errors=True)
    doc = {"os": OS, "goose": version, "shard": shard, "results": results}
    pathlib.Path(out_path).write_text(json.dumps(doc, indent=1), encoding="utf-8")


def merge(files, run_url):
    path = ROOT / "data" / "compat.json"
    doc = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {"version": 1, "results": {}}
    known = set(entries())
    tested = set()
    for f in files:
        part = json.loads(pathlib.Path(f).read_text(encoding="utf-8"))
        doc["goose"] = part["goose"]
        for id_, r in part["results"].items():
            doc["results"].setdefault(id_, {})[part["os"]] = r
            tested.add(id_)
    doc["results"] = {k: v for k, v in sorted(doc["results"].items()) if k in known}
    doc["ran_at"] = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    if run_url:
        doc["run_url"] = run_url
    path.parent.mkdir(exist_ok=True)
    path.write_text(json.dumps(doc, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    summary(doc, tested)


def summary(doc, tested):
    icon = {"pass": "✅", "check": "🟡", "fail": "❌", "skip": "➖"}
    rows = ["| Entry | Linux | macOS | Windows | Detail |", "|---|---|---|---|---|"]
    counts = {}
    for id_ in sorted(tested):
        r = doc["results"][id_]
        cells, detail = [], ""
        for o in ("linux", "macos", "windows"):
            s = (r.get(o) or {}).get("status")
            counts[(o, s)] = counts.get((o, s), 0) + 1
            cells.append(icon.get(s, " "))
            detail = detail or (r.get(o) or {}).get("detail") or (r.get(o) or {}).get("reason") or ""
        rows.append(f"| {id_} | " + " | ".join(cells) + f" | {detail[:120].replace('|', '/')} |")
    head = [f"## Compatibility with Goose {doc.get('goose')}", ""]
    for o in ("linux", "macos", "windows"):
        head.append(f"- {o}: " + ", ".join(f"{icon[s]} {counts.get((o, s), 0)}" for s in icon))
    text = "\n".join(head + [""] + rows) + "\n"
    print(text)
    if os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(os.environ["GITHUB_STEP_SUMMARY"], "a", encoding="utf-8") as f:
            f.write(text)


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("install").add_argument("dir")
    sub.add_parser("libs")
    r = sub.add_parser("run")
    r.add_argument("--out", required=True)
    r.add_argument("--shard", default="0/1")
    r.add_argument("--only", default="")
    m = sub.add_parser("merge")
    m.add_argument("files", nargs="+")
    m.add_argument("--run-url", default="")
    a = ap.parse_args()
    if a.cmd == "install":
        install(a.dir)
    elif a.cmd == "libs":
        libs()
    elif a.cmd == "run":
        run(a.out, a.shard, a.only)
    else:
        merge(a.files, a.run_url)


if __name__ == "__main__":
    main()
