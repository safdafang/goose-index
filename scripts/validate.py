"""Validate packages/*.toml and data/meta.json.

    python scripts/validate.py                 every check is an error
    python scripts/validate.py --strict a,b    checks against fetched GitHub data fail only a and b
    python scripts/validate.py --strict ''     ...fail nothing: they are reported as warnings

Some checks compare an entry with what its repository says today: a description that shares
six words in a row with the repository's own, or a repository that moved onto the address of
another entry. Those can turn red without anyone touching this repository, for instance when an
author copies our description into their GitHub "About". The daily build passes --strict '' so
that such a change cannot stop the index from updating, and a pull request passes the entries it
changes, so that it is judged on its own entries only.
"""

import argparse
import json
import os
import pathlib
import re
import sys
import tomllib

import jsonschema

sys.path.insert(0, str(pathlib.Path(__file__).parent))
from entries import ROOT, load_entries  # noqa: E402

RUN = 6  # words in a row that count as copying


def shingles(text, n=RUN):
    words = re.findall(r"[a-z0-9]+", (text or "").lower())
    return {" ".join(words[i:i + n]) for i in range(len(words) - n + 1)}


def main():
    ap = argparse.ArgumentParser(description="Validate packages/*.toml and data/meta.json.")
    ap.add_argument("--strict", metavar="IDS", default=None,
                    help="comma-separated entry ids whose checks against fetched GitHub data are errors; for "
                         "the rest they are warnings. Omitted: every entry. '': none.")
    a = ap.parse_args()
    strict = None if a.strict is None else {i.strip() for i in a.strict.split(",") if i.strip()}
    errors, warnings, downgraded = [], [], []

    def fetched_problem(stems, msg):
        """A problem that comes from GitHub's data rather than from the entry files."""
        if strict is None or strict & set(stems):
            errors.append(msg)
        else:
            downgraded.append(msg)

    entry_schema = json.loads((ROOT / "schema" / "entry.schema.json").read_text(encoding="utf-8"))
    validator = jsonschema.Draft202012Validator(entry_schema)

    with (ROOT / "schema" / "categories.toml").open("rb") as f:
        cat_ids = [c["id"] for c in tomllib.load(f)["category"]]
    enum = entry_schema["properties"]["category"]["enum"]
    if sorted(cat_ids) != sorted(enum):
        errors.append(f"schema/categories.toml and the schema's category enum differ: "
                      f"{sorted(set(cat_ids) ^ set(enum))}")

    meta = {}
    meta_path = ROOT / "data" / "meta.json"
    if meta_path.exists():
        doc = json.loads(meta_path.read_text(encoding="utf-8"))
        meta_schema = json.loads((ROOT / "schema" / "meta.schema.json").read_text(encoding="utf-8"))
        for e in jsonschema.Draft202012Validator(meta_schema).iter_errors(doc):
            errors.append(f"data/meta.json: {'/'.join(map(str, e.absolute_path))}: {e.message}")
        meta = doc.get("entries", {})

    entries = load_entries()
    repos = {}
    for stem, (path, e) in entries.items():
        rel = path.relative_to(ROOT).as_posix()
        for err in sorted(validator.iter_errors(e), key=lambda x: list(x.absolute_path)):
            where = "/".join(map(str, err.absolute_path)) or "(top)"
            errors.append(f"{rel}: {where}: {err.message}")
        if e.get("id") != stem:
            errors.append(f"{rel}: id {e.get('id')!r} must equal the file name {stem!r}")
        m = meta.get(stem)
        moved = (m or {}).get("canonical_repo")
        # a renamed repository answers at both addresses, so both count as taken; two entry files
        # naming one repository is their own mistake, a rename onto another entry's address is not
        for repo, fetched in (((e.get("repo") or "").lower(), False), ((moved or "").lower(), True)):
            if not repo:
                continue
            if repo in repos:
                other_rel, other_stem, other_fetched = repos[repo]
                msg = f"{rel}: repo {repo} is also {other_rel}"
                if fetched or other_fetched:
                    fetched_problem((stem, other_stem), msg)
                else:
                    errors.append(msg)
            repos[repo] = (rel, stem, fetched)
        if moved:
            warnings.append(f"{rel}: the repository moved to {moved}: update repo (the index already links there)")
        if m:
            copied = shingles(e.get("description")) & shingles(m.get("upstream_description"))
            if copied:
                fetched_problem((stem,), f"{rel}: description shares six words in a row with the repository's "
                                         f"GitHub description: {sorted(copied)[0]!r}...")
            if m.get("replaced_by"):
                warnings.append(f"{rel}: a different repository now answers at this address (deleted and "
                                f"recreated, or the name was taken over). It is shown as unavailable; after "
                                f"checking it, delete this entry's record from data/meta.json to accept it")
            elif not m.get("exists"):
                warnings.append(f"{rel}: repository not found")
            elif m.get("license") == "none" and "license_override" not in e:
                warnings.append(f"{rel}: no license (flagged on the site)")
        elif meta and e.get("repo"):
            warnings.append(f"{rel}: no fetched metadata yet (run scripts/fetch_meta.py)")

    for w in warnings:
        print(f"warning: {w}")
    in_actions = os.environ.get("GITHUB_ACTIONS") == "true"
    for w in downgraded:
        # these would fail a strict run: put them in the run's summary, where they get read
        print(f"::warning::{w}" if in_actions else f"warning: {w} (an error for entries passed to --strict)")
    for err in errors:
        print(f"error: {err}")
    print(f"{len(entries)} entries, {len(errors)} errors, {len(warnings) + len(downgraded)} warnings")
    sys.exit(1 if errors else 0)


if __name__ == "__main__":
    main()
