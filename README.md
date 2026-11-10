# ImpactLine (static edition)

**Staged copy:** https://theguysaccount.github.io/impactline-law-to-outcome-tracker/ (not indexed).
**Live original:** https://app.impactline.org (unchanged; the cutover is a separate decision, see [OPERATIONS.md](OPERATIONS.md)).

The public delivery record. One page per enacted U.S. public law that follows the law into the Federal Register and
federal spending records, labels every link as an official record or a candidate match, and leaves the gaps visible.
ImpactLine does not declare fraud, waste or success.

No server, no API keys, no dependencies: Python's standard library reads three public sources and writes a static site.

## Sources

| What | Source | Key |
|---|---|---|
| Public laws: number, approval date, citation, bill, titles | [GovInfo bulk data](https://www.govinfo.gov/bulkdata/PLAW) (U.S. Government Publishing Office) | none |
| Documents that cite a law by number | [Federal Register API](https://www.federalregister.gov/reader-aids/developer-resources/rest-api) | none |
| Funds Treasury tags to a law; awards; program traces | [USAspending.gov API](https://api.usaspending.gov/) | none |

## Layout

| Path | What it is |
|---|---|
| `impactline/laws.py` | Reads each Congress's public-law ZIP when it changes and parses every law's own file |
| `impactline/fedreg.py` | Federal Register documents citing each law (three citation styles), on a rolling schedule |
| `impactline/spending.py` | Official by-law totals (fund codes), program traces, and keyword candidates kept apart |
| `impactline/refresh.py` | Runs the sources independently within a nightly budget; `data/status.json` |
| `impactline/evidence.py` | The seven-step record, canonical-JSON evidence packets and the digest manifest |
| `impactline/build.py`, `og.py` | The static site, CSV/JSON mirror, feeds, share cards |
| `impactline/guard.py`, `e2e.py`, `selftest.py`, `linkcheck.py` | Pre-deploy checks, browser check, live check, weekly link sample |
| `config/site.json` | Base URL default, staged/indexable flag, request pacing and budgets |
| `config/programs.json`, `config/aliases.json` | The three pilot traces; "also called" names for laws with no short title |
| `data/` | Laws, per-law Federal Register and spending records, check dates. Committed by the nightly job |

## Run it

```sh
python3 -m unittest discover -s tests -t .      # tests (Python 3.9+; no installs)
python3 -m impactline.refresh                    # read the sources within the nightly budget
python3 -m impactline.refresh --law 117-58       # one law now
python3 -m impactline.build --site _site         # build the site and the evidence packets
python3 -m impactline.og --site _site            # share cards (needs Chrome; falls back to the default card)
python3 -m impactline.guard _site                # the checks every deploy must pass
python3 -m impactline.e2e _site                  # list filter and packet verification in headless Chrome
python3 -m impactline.selftest                   # check the live site
```

To preview locally, serve a folder that contains `_site` under the name `impactline-law-to-outcome-tracker`, or build
with `SITE_URL=http://localhost:8000`.

## Verify an evidence packet

```sh
curl -sO https://theguysaccount.github.io/impactline-law-to-outcome-tracker/evidence/manifest.json
gh attestation verify manifest.json --repo theguysaccount/impactline-law-to-outcome-tracker
curl -s https://theguysaccount.github.io/impactline-law-to-outcome-tracker/evidence/117-58.json | shasum -a 256
```

The attestation shows the manifest came from this repository's workflow. It does not make the federal data correct.

## Licence

Code: MIT. Compiled data: CC0 1.0 (the underlying federal data is public domain). Fonts: SIL OFL 1.1.
More: [PRODUCT.md](PRODUCT.md), [DECISIONS.md](DECISIONS.md), [STATE.md](STATE.md), [LAUNCH.md](LAUNCH.md).
