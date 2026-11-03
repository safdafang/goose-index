"""Phase 1c: sort verified signals into automatic exclusions and a list for human review.

Automatic exclusions are only the mechanical ones (missing, empty, a fork with no
commits of its own, no Goose source and no mention of the language). Everything
with Goose evidence goes to discovery/raw/review.txt to be judged by reading it.

    .venv/Scripts/python scripts/triage.py
"""

import json
import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parent.parent
RAW = ROOT / "discovery" / "raw"

PRESSLY = re.compile(r"pressly/goose|database migration|migrations?\b.*\bgoose|goose (up|down|create)\b|\bsqlc\b", re.I)
LANG = re.compile(r"aardappel/goose|aardappel\.github\.io/goose|goose[- ]lang\b|Goose (programming )?language", re.I)
BLOCK = re.compile(r"block/goose|block\.github\.io/goose|goose (ai )?agent|codename goose|\bmcp\b|recipe|extension for goose|goose session|aaif", re.I)


def goose_sidecars(s):
    """A Goose sidecar is foo.build beside foo.goose; meson.build and the like are not."""
    goose = set(s.get("goose_paths", []))
    truncated = s.get("n_goose", 0) > len(goose)  # older signals kept only 40 paths
    return {p: kv for p, kv in (s.get("sidecars") or {}).items()
            if truncated or p[:-len(".build")] + ".goose" in goose}


def auto_reason(s, forks):
    """None when a person must decide; otherwise the reason it is excluded."""
    if s.get("error"):
        return s["error"]
    fork = s.get("fork_of_goose")
    if fork is not None:
        # signals written before forks.json had this fork carry an empty record
        fork = fork or forks.get(s["meta"]["nameWithOwner"].lower(), {})
        s["fork_of_goose"] = fork
        if not fork.get("ahead_by"):
            return "fork of aardappel/goose with no commits of its own on its default branch"
        return None
    goose_ok = any(c["goose"] for c in s.get("goose_checked", []))
    # Dockerfile.goose is pressly/goose's or the agent's image recipe, not Goose source
    real = [p for p in s.get("goose_paths", []) if not p.rsplit("/", 1)[-1].lower().startswith("dockerfile")]
    text = (s.get("readme_head") or "") + " " + ((s.get("meta") or {}).get("description") or "")
    if goose_ok or real or LANG.search(text):
        return None
    if PRESSLY.search(text) or s.get("sql_migrations", 0) > 2:
        return "name collision: uses or wraps pressly/goose (Go database migrations); no Goose source"
    if BLOCK.search(text):
        return "name collision: about block/goose (AI agent); no Goose source"
    return "no .goose files, no sidecar, README does not mention the Goose language"


def clean(text, n):
    text = re.sub(r"<[^>]+>|!\[[^\]]*\]\([^)]*\)|\[!\[.*?\]\(.*?\)\]\(.*?\)", " ", text or "")
    text = re.sub(r"\s+", " ", text)
    return text[:n]


def main():
    signals = json.loads((RAW / "signals.json").read_text(encoding="utf-8"))
    collected = json.loads((RAW / "collected.json").read_text(encoding="utf-8"))
    forks = json.loads((RAW / "forks.json").read_text(encoding="utf-8"))
    auto, review = {}, []
    for key, s in sorted(signals.items()):
        r = auto_reason(s, forks)
        if r:
            auto[key] = r
            continue
        m = s.get("meta") or {}
        checked = s.get("goose_checked", [])
        imports = sorted(set(re.findall(r'import (\w+) from "([^"]+)"', s.get("readme_head") or "")))[:4]
        side = {p: {k: (v if k.startswith(("c_libs", "dylibs", "cmake_target")) else "")
                    for k, v in sorted(kv.items())} for p, kv in goose_sidecars(s).items()}
        fork = s.get("fork_of_goose")
        lines = [
            f"### {m.get('nameWithOwner', key)}  ★{m.get('stargazerCount')}  created {str(m.get('createdAt'))[:10]}"
            f"  pushed {str(m.get('pushedAt'))[:10]}  lic {(m.get('licenseInfo') or {}).get('spdxId')}"
            f"  tags {(m.get('tags') or {}).get('totalCount')}  archived {m.get('isArchived')}",
            f"  desc: {m.get('description')}",
            f"  sources: {', '.join(collected.get(key, {}).get('sources', [])[:4])}",
        ]
        if fork is not None:
            lines.append(f"  FORK ahead {fork.get('ahead_by')}: {' | '.join(fork.get('recent_commits', [])[-8:])}")
        else:
            lines.append(f"  goose files {s.get('n_goose')} / {s.get('n_files')} files; checked "
                         + "; ".join(f"{c['path']}={'GOOSE' if c['goose'] else 'no'}({c['strong']},{c['weak']})" for c in checked)
                         + f"; c/h {s.get('c_files')} cmake {s.get('has_cmakelists')}"
                         + f" pkgjson {s.get('has_package_json')} cargo {s.get('has_cargo')} gomod {s.get('has_go_mod')}")
            if side:
                lines.append(f"  sidecars: {side}")
            if imports:
                lines.append(f"  imports in README: {imports}")
        readme = s.get("readme_head") or ""
        installs = sorted({clean(l, 140) for l in readme.splitlines()
                           if re.search(r"\b(apt(-get)? install|brew install|vcpkg|pacman -S|dnf install)\b", l)})[:4]
        plats = [clean(l, 170) for l in readme.splitlines()
                 if re.search(r"\b(windows|macos|mac os|linux)\b", l, re.I)][:4]
        if installs:
            lines.append(f"  installs: {installs}")
        if plats:
            lines.append(f"  platforms: {plats}")
        lines.append(f"  readme: {clean(readme, 600)}")
        review.append("\n".join(lines))
    (RAW / "review.txt").write_text("\n\n".join(review) + "\n", encoding="utf-8")
    (RAW / "auto_excluded.json").write_text(json.dumps(auto, indent=1, sort_keys=True), encoding="utf-8")
    counts = {}
    for r in auto.values():
        counts[r.split(":")[0]] = counts.get(r.split(":")[0], 0) + 1
    print(f"{len(signals)} inspected: {len(review)} to review, {len(auto)} auto-excluded {counts}")


if __name__ == "__main__":
    main()
