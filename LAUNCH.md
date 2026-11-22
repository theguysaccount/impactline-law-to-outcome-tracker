# LAUNCH

This site is **live** at https://data.impactline.org/ since 2026-11-22, beside the original at app.impactline.org,
which is unchanged. Nothing has been posted, sent or submitted anywhere by hand.

## What is live
- https://data.impactline.org/ with a sitemap, an open robots.txt and IndexNow pings after each change.
- The home page, the law lists, how evidence works and about are `noindex`: the original serves its own, and each
  of these points to it. Law pages, the spending and Federal Register lists, program traces and data are indexable.
- https://theguysaccount.github.io/impactline-law-to-outcome-tracker/ redirects to the live address.

## How it went live
A DNS record for `data.impactline.org` and the Pages custom domain. The steps, and how to move the site or take it
out of search, are in OPERATIONS.md under "Where the site lives".

## The search surfaces
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
