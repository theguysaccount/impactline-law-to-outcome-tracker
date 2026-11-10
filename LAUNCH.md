# LAUNCH

This build is **staged**. It is public at its GitHub Pages address so it can be reviewed, but it tells search engines
to stay away, because app.impactline.org is live. Nothing has been posted, sent or submitted anywhere.

## What is live
- https://theguysaccount.github.io/impactline-law-to-outcome-tracker/ (noindex, robots.txt disallows crawling, no sitemap).
- The IndexNow key file is published but nothing is submitted while the site is staged.

## Going live (Jack's decision)
The exact DNS record and the two settings are in OPERATIONS.md under "Cutover". In short: point `app.impactline.org`
(or a new name) at GitHub Pages, set `SITE_URL`, and set `SITE_INDEXABLE=true` only if the site should be in search.

## Once indexed: the search surfaces
| Query pattern | Page |
|---|---|
| "[law name] implementation", "[law name] federal register" | `/laws/<congress>-<number>/` |
| "where did [law] money go", "[law] spending" | `/laws/<id>/#money`, `/spending/` |
| "Public Law 117-58" (and every other number) | `/laws/<id>/` |
| "Clean School Bus Program awards", "middle mile broadband grants" | `/programs/<slug>/` |
| "laws passed by the 119th Congress" | `/congress/119/`, `/laws/` |

Every law page is a real record, not a stub: identity, the seven steps, and either a trail or a plain statement that
none was found, with sources. `Legislation` and `Dataset` structured data, per-law feeds and an open JSON/CSV mirror
are in place for search and for AI answer engines that cite sources.

## Loops built into the product
- **Evidence packets** with an attested manifest: a reporter or auditor can cite a file whose origin can be checked.
- **Per-law Atom feeds**: follow a law and get new Federal Register documents in any feed reader. This is the free
  version of "alerts".
- **Open mirror**: `data/laws.csv`, `data/laws.json`, `evidence/<id>.json`.

## The cheapest test (for a human; nothing here has been sent)
The evaluator's test was to send one complete trace to ten infrastructure reporters and count replies. The strongest
candidates to send are the three program traces and the Infrastructure Investment and Jobs Act page. Draft note:

> ImpactLine keeps a public record for every federal law since 2021: which agency documents cite it and what spending
> Treasury ties to it by law. Here is the record for the Clean School Bus Program, joined by official identifiers, with
> the gaps marked. Is this useful for your reporting, and what is missing?

## Custom domain
See OPERATIONS.md. `impactline.org` uses SiteGround DNS; `legibleslation.com` is listed as a redirect and does not
resolve today.
