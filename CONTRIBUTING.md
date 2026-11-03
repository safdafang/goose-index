# Adding or fixing an entry

The index lists anything written in or for the [Goose programming language](https://github.com/aardappel/goose):
libraries, bindings, tools, editor support, programs, forks of the compiler, and guides. It links to projects;
it never hosts, mirrors or vendors their code.

## Add a project

Add one file, `packages/<id>.toml`, in a pull request. The id is the repository's owner and name, lowercased,
joined by `-`, with any other character turned into `-`: `github.com/kaitk/goose-http` becomes `kaitk-goose-http`.

```toml
id = "kaitk-goose-http"
name = "goose-http"
kind = "package"            # package | binding | tool | editor | app | fork | learning-resource
category = "networking"     # one id from schema/categories.toml
tags = ["http", "server", "websocket"]
repo = "https://github.com/kaitk/goose-http"
description = "One or two sentences, in your own words, on what it does and what sets it apart."
platforms = ["linux", "macos", "windows"]   # what the author claims; [] if the README doesn't say

[import]                    # package and binding only
name = "http"               # import http from "github.com/kaitk/goose-http@<tag>";

[native]
c = true                    # it has c_sources in a .build sidecar
cmake = false               # it has a cmake_target in a .build sidecar
system_libs.linux = ["liburing-dev"]   # apt names; macos uses Homebrew names
```

Every field is described in [schema/README.md](schema/README.md). Don't write tags, stars, dates or the
license: a bot fetches them every day into `data/meta.json`. Don't edit `README.md` or `index.json`
either. They are generated from `packages/` after your pull request merges.

### What gets in

- Any real project written in or for Goose, including small examples, as long as it has code to look at.
- Not: empty or hello-world repositories, automated mirrors, forks with no changes of their own, separate
  languages that were only inspired by Goose, and multi-language projects with only incidental Goose code.
  Projects that just share the name (the `pressly/goose` migration tool, the `block/goose` agent) are out.

### Descriptions

Write for someone choosing between alternatives. Don't paste the README or the GitHub description: the
check fails a description that shares six words in a row with the project's own.

## Checks on your pull request

- `scripts/validate.py` checks the schema, the id, duplicate repositories and the description.
- The compatibility workflow build-tests the entries you changed on Linux, macOS and Windows against the
  latest Goose release, and posts the result in the run's summary. A red build doesn't block a listing.
  It shows readers what to expect, and authors find out about it.

Run them locally with Python 3.11 or newer:

```sh
python -m pip install -r requirements.txt
python scripts/validate.py
python scripts/build.py --site _site    # README.md, index.json and the site in _site/
```

## Fix or remove an entry

Edit or delete its file. If you are the author and want your project removed, open an issue or a pull
request deleting the file. It will be removed, no questions asked.
