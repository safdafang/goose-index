# Discovery

How the first version of the index was assembled, and how to look for new projects.

`candidates.csv` is the record: every repository considered, whether it was included, why, the evidence
read from its files, and how it was found. Columns: `url, decision, why, evidence, found_by`.

## The pipeline

1. **`scripts/discover.py`** collects candidates into `discovery/raw/collected.json` from:
   - GitHub repository search (names, descriptions, READMEs mentioning `aardappel/goose`) and topic search;
   - GitHub code search for Goose syntax in `.goose` files, rerun with size bands and with the biggest
     repositories excluded, because code search stops at 1,000 files per query;
   - every fork of `aardappel/goose`, with how many commits each is ahead;
   - the upstream issues, comments, pull requests, discussions and docs, for every GitHub link in them;
   - a hand-made seed list.
2. **`scripts/verify.py`** reads each candidate: metadata, file tree, the first `.goose` files (scored for
   Goose syntax, never judged by name), every `.build` sidecar, and the README's links. `--snowball N`
   follows the links in the READMEs of verified Goose projects for N rounds.
3. **`scripts/triage.py`** drops the mechanical cases (gone, empty, forks with no commits of their own, no
   Goose source and no mention of the language) and writes the rest to `raw/review.txt` for a person.
4. Each remaining candidate was read and decided by hand. Included ones became `packages/<id>.toml`.

The first run, on 2026-11-03, considered 3,234 candidates and included 154. Most exclusions were name
collisions: 199 repositories using the `pressly/goose` migration tool and 256 about the `block/goose` agent.

`discovery/raw/` holds the intermediate files. It is not committed: it is large and fully reproducible.
All scripts need the GitHub CLI (`gh`), logged in.

## Looking for new projects

Run steps 1–3 again. `raw/review.txt` then lists every candidate with Goose evidence. Anything in it that
is in neither `packages/` nor `candidates.csv` is new.
