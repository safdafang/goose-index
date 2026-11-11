"""Read packages/*.toml and data/meta.json. Standard library only, so every script can use it."""

import json
import pathlib
import tomllib

ROOT = pathlib.Path(__file__).resolve().parent.parent


def load_entries():
    """{id: (path, entry)} for every packages/<id>.toml, in id order."""
    entries = {}
    for p in sorted((ROOT / "packages").glob("*.toml")):
        with p.open("rb") as f:
            entries[p.stem] = (p, tomllib.load(f))
    return entries


def load_meta():
    """The fetched facts by entry id; empty before the first fetch."""
    p = ROOT / "data" / "meta.json"
    return json.loads(p.read_text(encoding="utf-8"))["entries"] if p.exists() else {}
