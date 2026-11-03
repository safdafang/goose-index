"""Validate every packages/<id>.toml, and data/meta.json when present.

Checks the JSON Schema, then what a schema cannot: the file name is the id, no
two entries share a repository, the category list matches schema/categories.toml,
and a description shares no run of six words with the project's own description.

    .venv/Scripts/python scripts/validate.py      exit 1 on any error
"""

import json
import pathlib
import re
import sys
import tomllib

import jsonschema

ROOT = pathlib.Path(__file__).resolve().parent.parent
RUN = 6  # words in a row that count as copying


def load_entries():
    entries = {}
    for p in sorted((ROOT / "packages").glob("*.toml")):
        with p.open("rb") as f:
            entries[p.stem] = (p, tomllib.load(f))
    return entries


def shingles(text, n=RUN):
    words = re.findall(r"[a-z0-9]+", (text or "").lower())
    return {" ".join(words[i:i + n]) for i in range(len(words) - n + 1)}


def main():
    errors, warnings = [], []
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
        repo = (e.get("repo") or "").lower()
        if repo:
            if repo in repos:
                errors.append(f"{rel}: repo {repo} is also {repos[repo]}")
            repos[repo] = rel
        m = meta.get(stem)
        if m:
            copied = shingles(e.get("description")) & shingles(m.get("upstream_description"))
            if copied:
                errors.append(f"{rel}: description copies the project's own words: {sorted(copied)[0]!r}...")
            if not m.get("exists"):
                warnings.append(f"{rel}: repository not found")
            elif m.get("license") == "none" and "license_override" not in e:
                warnings.append(f"{rel}: no license (flagged on the site)")
        elif meta and e.get("repo"):  # an article with only a url has nothing to fetch
            warnings.append(f"{rel}: no fetched metadata yet (run scripts/fetch_meta.py)")

    for w in warnings:
        print(f"warning: {w}")
    for err in errors:
        print(f"error: {err}")
    print(f"{len(entries)} entries, {len(errors)} errors, {len(warnings)} warnings")
    sys.exit(1 if errors else 0)


if __name__ == "__main__":
    main()
