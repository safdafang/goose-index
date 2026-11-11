# The data model

The index is a directory of small hand-written files plus one file a script writes.

| Where | Written by | Holds |
|---|---|---|
| `packages/<id>.toml` | people, through pull requests | what an entry is: kind, category, description, import name, native needs, platforms |
| `data/meta.json` | `scripts/fetch_meta.py`, on a schedule | what changes by itself: latest tag, default branch, last commit, stars, archived, detected license |
| `data/compat.json` | `scripts/compat.py`, weekly in CI | build-test results per entry and OS, and the requirements the compiler asked for |
| `schema/entry.schema.json` | maintainers | the rules for an entry file |
| `schema/meta.schema.json` | maintainers | the rules for `data/meta.json` |
| `schema/categories.toml` | maintainers | the categories, their titles and their order |

Every output (README.md, the site, `index.json`) is generated from `packages/` and
`data/` together by `scripts/build.py`. Nothing generated is edited by hand.

**Why two sources.** Stars and tags change daily. If they lived in each entry file,
every refresh would touch every file and conflict with open pull requests, and a
contributor could type in a tag that doesn't exist. Keeping them in one bot-written
file means an entry's TOML changes only when a person changes what the entry *is*.

## An entry

```toml
id = "kaitk-goose-sqlite"          # = file name; lowercase owner-repo; never changes
name = "goose-sqlite"
kind = "binding"                   # package | binding | tool | editor | app | fork | learning-resource
category = "databases"             # one id from schema/categories.toml
tags = ["sqlite", "sql", "embedded"]
repo = "https://github.com/kaitk/goose-sqlite"
description = "SQLite for Goose programs over a vendored amalgamation, with prepared statements and typed column reads."
platforms = ["linux", "macos"]     # what the author claims; [] when unstated

[import]                           # package and binding only
name = "sqlite"                    # import sqlite from "github.com/kaitk/goose-sqlite@<latest tag>";

[native]
c = true                           # c_sources in a .build sidecar
cmake = false                      # cmake_target in a .build sidecar
system_libs.linux = []             # apt package names
system_libs.macos = []             # Homebrew formula names
system_libs.windows = []
```

### Fields

| Field | Required | Notes |
|---|---|---|
| `id` | yes | `owner-repo`, lowercased, runs of other characters become `-`. Stable: `index.json` consumers key on it. |
| `name` | yes | Display name. |
| `kind` | yes | See below. |
| `category` | yes | Exactly one, from `categories.toml`. |
| `tags` | yes | Up to 10 lowercase keywords. May be empty. |
| `repo` | yes, except a `learning-resource` with `url` | https URL of the git repository, no `.git`. |
| `url` | no | For a learning resource that is not a repository. |
| `description` | yes | 20–320 characters, one or two sentences, **in the index's own words**. |
| `import.name` | for `package`, `binding` | The name in `import <name> from "…"`. |
| `import.path` | no | Only when the import string is not `github.com/<owner>/<repo>`. |
| `import.modules` | no | Submodules users import by name, such as `net.http`. |
| `import.subdir` | no | The package's folder when it is not the repository root. Goose can't fetch such a package by URL yet (upstream `docs/design/packages.md` §11), so the site shows copy instructions instead of an import line. |
| `native.c`, `native.cmake` | yes | From the project's `.build` sidecars (`c_sources`, `cmake_target`). |
| `native.system_libs.<os>` | no | Packages the machine needs, as apt, Homebrew and vcpkg name them. The compatibility runner installs these. |
| `native.tools` | no | Programs the build runs besides git, cmake and a C compiler. |
| `platforms` | yes | Subset of `linux`, `macos`, `windows` that the author claims. `[]` means unstated, not "none". |
| `license_override` | no | Only when GitHub's detection is wrong and the project states a license elsewhere. |
| `upstream_fork` | for `fork` | What the fork adds. |
| `compat.skip` | no | Why the compatibility runner should not build it. |
| `compat.entry` | no | File to check, when it is not `<import.name>.goose` at the root. |

### Kinds

| Kind | Means | Import line |
|---|---|---|
| `package` | A Goose library, mostly or entirely in Goose. | yes |
| `binding` | A Goose library whose real work is done by a library in another language (SQLite, raylib, OpenSSL, Rust crates). | yes |
| `tool` | A program for Goose developers: package manager, doc generator, test runner, formatter, linter. | no |
| `editor` | Editor or IDE support. | no |
| `app` | A program written in Goose for its own sake. | no |
| `fork` | A fork of `aardappel/goose`, or a compiler or language derived from it. | no |
| `learning-resource` | Guides, tutorials, articles, notes, starters, example collections. | no |

### The import line

Built, never stored:

```
import <import.name> from "<import.path or github.com/owner/repo>@<latest_tag>";
```

With no tag yet, the line pins the default branch and the site says the package is
untagged. Goose's own design doc warns that branch refs move; the site says so too.

### Descriptions

Write what the project does and what sets it apart, for someone choosing between
alternatives, in your own words. Don't paste the README or the GitHub description.
`scripts/validate.py` fails an entry that shares six words in a row with the project's
GitHub description (from `data/meta.json`).

### Licenses

The license comes from GitHub's detection in `data/meta.json`: an SPDX id, `other` when
GitHub can't name it, or `none` when there is no license file. The site flags `none`:
without a license, nobody may legally reuse the code, whatever the README implies. Use
`license_override` only when the project really does state a license that GitHub misses.

## `data/meta.json`

```json
{ "version": 1, "fetched_at": "2026-11-02T21:00:00Z",
  "entries": { "kaitk-goose-sqlite": {
      "exists": true, "repo_id": "R_kgDOExample", "default_branch": "main",
      "latest_tag": "v0.3.1", "latest_tag_commit": "3f1c9a7e0b5d4c2a8e6f1b0d9c7a5e3f2b4d6c8a", "tag_count": 9,
      "last_commit": "2026-10-30T12:00:00Z", "created": "2026-10-19T08:00:00Z",
      "stars": 0, "archived": false, "license": "Apache-2.0",
      "upstream_description": "SQLite bindings for Goose, over the vendored amalgamation" } } }
```

`exists: false` means the repository is gone or private. The site shows the entry as
unavailable rather than dropping it silently, so a maintainer can decide.

`latest_tag` is the highest release version among the tags, not the most recently
created one, and `latest_tag_commit` is the commit it named when fetched.

`repo_id` is GitHub's id of the repository, recorded the first time it is fetched. It
follows the repository through renames and transfers:

- A renamed or moved repository gets `canonical_repo`. The index links and imports from
  the new address at once, and `validate.py` warns until the entry's `repo` is updated.
- If the address later answers with a *different* id (the repository was deleted and
  recreated, or someone else took the name), the record becomes `exists: false` with
  `replaced_by`, and the entry is shown as unavailable with no import line. After
  checking the new repository, delete that entry's record from `data/meta.json`: the
  next fetch records the new id. This is the one hand edit the file allows.

## Checking

```sh
python scripts/fetch_meta.py          # refresh data/meta.json (needs the GitHub CLI, logged in)
python scripts/fetch_meta.py --only a,b   # only these entries
python scripts/validate.py            # schema + cross-file rules; exit 1 on errors
python scripts/build.py --site _site  # README.md, index.json, and the site
```

## Requirements are not a field

A Goose library states what it needs in its own source, with the same
`import other from "…";` line a program uses, and the compiler reports any that the
program's root file does not declare, naming the line to add. So the index does not
ask authors to repeat their dependencies: the build test (`scripts/compat.py`) adds
the lines the compiler asks for and records them as the entry's `requires`.
System libraries are different: nothing in a package says that it needs `libsqlite3`,
so those are declared in `native.system_libs`.
