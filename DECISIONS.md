# DECISIONS

## 2026-11-22: beside the original, never in its place
- Jack's standing rule is "never replace, only build on top", so there is no cutover. The site went live at
  `data.impactline.org` on 2026-11-22, and `app.impactline.org` is untouched.
- **Staged at a github.io address, live at its own.** The first build (2026-11-10) was staged because the original is
  live: `noindex` on every page, robots.txt disallowing everything, no sitemap, no IndexNow. That is still what a
  github.io address gets. At its own address the site is indexable, except the pages the original already serves.
- **What counts as a duplicate.** The original is one page: the list of enacted laws, the law you pick, and how
  evidence works. So the home page, `/laws/`, the per-Congress lists, the method page and the about page here stay
  `noindex` and point to the original. The original has no address per law, so the 778 law pages, the spending and
  Federal Register lists, the program traces and the downloads are this site's own and are indexed.
- **The original is itself `noindex, nofollow`.** Indexing this site therefore takes nothing from the original, but it
  does put ImpactLine pages in search for the first time. `SITE_INDEXABLE=false` reverses that in one step (OPERATIONS.md).
- **The address is read from the Pages settings** on every run, so the custom domain is the one setting that moves the
  site. A build for the wrong address would publish pages whose stylesheet and links point elsewhere, so a run
  that cannot read the setting stops before building.
- **The browser check's search expectation is now exact.** It accepted "1 to 12 rows" for a search on a law number,
  which would have failed the day the sampled law had a short number (118-2 also matches 118-20 and 118-200). It now
  applies the list's own rule to the rows on the page.

## 2026-11-10: sources
- **Laws from GovInfo bulk data, not Congress.gov.** The original used the Congress.gov API, which needs a key (its
  demo quota was exhausted in testing) and reports "latest action" dates that needed a recovery step for enactment
  dates. GovInfo's bulk files need no key and carry each law's approval date, citation and text. Checked against the
  original's 701-law snapshot: every law present, every approval date equal, except one GovInfo file (P.L. 118-53)
  whose metadata date is a placeholder. The parser detects dates outside a Congress's term and takes the date from
  the printed running head instead (2024-05-07, matching the original).
- **Popular titles.** 22 laws have no short title in their text and none in the old import; they show their official
  title. Three well-known laws with no enacted short title carry an "also called" name from `config/aliases.json`
  (Inflation Reduction Act of 2022, One Big Beautiful Bill Act, Uyghur Forced Labor Prevention Act), shown as such.
- **Federal Register by citation only.** Documents are matched on the public-law number written three ways. Matching
  on a law's name was rejected: names are reused across years and would mix laws.
- **Money: two tiers that never mix.**
  1. *Tagged by law.* USAspending's Disaster Emergency Fund Codes name the law that provided the funds. For the 20
     laws in the window with their own code, budget authority, obligations and outlays are official figures. A code
     shared by several laws (code O) is credited to none of them.
  2. *Named in an award.* For other laws the only automatic signal is an award description that cites the law.
     These are shown as counts and examples, never summed, never called the law's spending. This is the original's
     rule ("keyword matches stay candidates") and the answer to its one recorded misattribution.
  A law's name is searched only if it is distinctive and unique in the list; generic and shared names are skipped.
- **Program traces by two official identifiers.** The original's pilots used keyword search and caught an award from
  a different law in the results. Here an award appears only if it carries both the law's fund code and the program's
  Assistance Listing number (66.045, 20.263, 11.033, each confirmed against USAspending's own listing names).

## 2026-11-10: signing
- The original signs exports with an ECDSA key held by its host. A static site has no place for a private key, and
  copying the original's key was out of the question. Instead every build writes canonical-JSON packets and a manifest
  of their SHA-256 digests, and the workflow asks GitHub to attest the manifest (Sigstore, bound to this repository's
  workflow identity). No secret exists to leak or rotate. `gh attestation verify` checks it; each law page checks its
  own packet against the manifest in the browser.
- Packets contain data and check dates but no build time, so a packet's digest changes only when its data does.

## 2026-11-10: operations
- Nightly budget instead of a full sweep: 320 Federal Register reads and 140 award searches a night, chosen by each
  law's own check date (young or busy laws daily, quiet laws every one to four weeks). Polite to the sources and
  finishes in minutes.
- Check dates live in one small file (`data/checked.json`) so a quiet night changes one file, not 774.
- USAspending's keyword search is loose: it reads fields other than the description, and "Public Law 118-21" also
  returns awards citing Public Law 118-210. So every candidate's description is read and must contain the exact
  citation or name. `returned` keeps what the search reported; `counts` are the verified ones. When a phrase returns
  more than 500 awards of a kind, only the 500 largest are read and the page says "at least".
- A source that fails keeps its last good files. A law file that suddenly lists 10% fewer laws is not trusted.
- Stack change from Next.js on a Worker to Python's standard library plus static files: the brief is a site that runs
  with no server and no keys, and every dynamic route in the original needs one or the other.

## Questions left for Jack (none blocks the site)
1. Answered 2026-11-22: a new name beside the original, `data.impactline.org`. The original is never replaced.
2. The site is indexable at its own address, and the original app is not. If ImpactLine should stay out of search
   for now, set `SITE_INDEXABLE=false` (OPERATIONS.md).
3. Is the merge with America V2 (AuditLine) wanted? The two static sites share a contract and a build pattern, but no common key yet.
