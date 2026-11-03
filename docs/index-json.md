# `index.json`

The whole index in one file, for package managers, editors and scripts.

- **Where:** `https://safdafang.github.io/goose-index/index.json` (served by GitHub Pages), or
  `https://raw.githubusercontent.com/safdafang/goose-index/main/index.json`. Both are the same file.
- **How often:** regenerated daily, after the facts in `data/meta.json` are refreshed, and after every merged
  change and every build test.
- **Schema:** [`schema/index.schema.json`](../schema/index.schema.json) (JSON Schema 2020-12). The build fails if the
  file does not match it.

## Versioning

`"format": "goose-index"` identifies the file and `"version"` is an integer, now `1`.

- New fields may appear at any time **without** a version change. Ignore fields you don't know.
- `version` goes up only for a change that could break a reader: a field removed or renamed, or a meaning or
  type changed. The old version is then kept at `index.v1.json` for at least six months.
- Entry `id`s are stable: an id is never reused for a different project. When a project moves, its entry keeps
  its id and `repo` changes.

## Top level

| Field | Type | Meaning |
|---|---|---|
| `format` | `"goose-index"` | |
| `version` | integer | See above. |
| `generated_at` | ISO time | When the data last changed: the later of the metadata fetch and the build test. |
| `meta_fetched_at` | ISO time | When tags, stars, dates and licenses were fetched from GitHub. |
| `compat` | object or null | The last build test: `goose` (release tested, e.g. `v2026.3`), `ran_at`, `run_url`. |
| `site`, `source` | URL | The index's site and its repository. |
| `categories` | array | `{id, title, scope, count}`, in display order. |
| `entries` | array | See below, sorted by category, then kind, then name. |

## An entry

```json
{
  "id": "kaitk-goose-http",
  "name": "goose-http",
  "kind": "package",
  "category": "networking",
  "tags": ["http", "server", "websocket"],
  "description": "The most complete HTTP server stack for Goose: …",
  "repo": "https://github.com/kaitk/goose-http",
  "url": "https://github.com/kaitk/goose-http",
  "page": "https://safdafang.github.io/goose-index/p/kaitk-goose-http/",
  "available": true,
  "archived": false,
  "latest_tag": "v0.5.16", "tag_count": 35, "default_branch": "main",
  "last_commit": "2026-10-30T09:12:44Z", "created": "2026-10-10T11:02:10Z", "stars": 18,
  "license": "Apache-2.0", "license_source": "github",
  "platforms": ["linux", "macos", "windows"],
  "native": { "c": true, "cmake": false,
              "system_libs": { "linux": ["liburing-dev"], "macos": [], "windows": [] }, "tools": [] },
  "upstream_fork": null,
  "import": { "name": "http", "source": "github.com/kaitk/goose-http", "ref": "v0.5.16", "pinned": true,
              "line": "import http from \"github.com/kaitk/goose-http@v0.5.16\";",
              "modules": [], "subdir": null },
  "compat": { "linux": { "status": "pass", "ref": "v0.5.16", "stage": "build" },
              "windows": { "status": "check", "ref": "v0.5.16", "stage": "build", "detail": "…" } },
  "requires": [ { "name": "hash", "source": "github.com/kaitk/goose-hash@v0.0.4" } ]
}
```

| Field | Meaning |
|---|---|
| `kind` | `package` and `binding` are importable (they have `import`); `tool`, `editor`, `app`, `fork`, `learning-resource` are not. |
| `repo` | The git repository, or `null` for an article (then `url` is the article). |
| `available` | `false` when the repository has been deleted or made private since it was listed. |
| `license` | An SPDX id, `"other"` when GitHub can't name the license, `"none"` when the repository has no license file. `none` means nobody may legally reuse the code; show it. |
| `platforms` | What the author claims. `[]` means the author doesn't say, not "none". What actually builds is in `compat`. |
| `native.system_libs` | What the machine must have installed, by package-manager name: apt for `linux`, Homebrew for `macos`. |
| `import.line` | Ready to paste into a program's root file. `null` when the package lives in a subdirectory (`import.subdir`), which Goose can't fetch by URL yet. |
| `import.pinned` | `false` when the project has no tags and `ref` is a branch, which moves. |
| `compat.<os>.status` | `pass`: built and linked. `check`: typechecked, but the C or native build failed. `fail`: could not be fetched, resolved or typechecked. `skip`: not built, with `reason`. A missing OS means not tested. |
| `requires` | The packages the build test had to declare in the root file before this one compiled, in the form the compiler printed them. Goose libraries state their requirements in their own import lines, so this is what a package manager would have to add. |

## Example: find a package to import

```sh
curl -s https://safdafang.github.io/goose-index/index.json |
  jq -r '.entries[] | select(.import and .import.line and (.tags | index("json"))) | .import.line'
```
