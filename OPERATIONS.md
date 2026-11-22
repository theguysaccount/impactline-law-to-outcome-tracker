# OPERATIONS

Everything runs on GitHub Actions in `theguysaccount/impactline-law-to-outcome-tracker`. No human has a job here.

- Live: https://data.impactline.org/ (since 2026-11-22). It sits beside the original and never replaces it.
- The original: https://app.impactline.org (OpenAI Sites, reached through a CNAME at SiteGround). Not touched.
- The old staging address, https://theguysaccount.github.io/impactline-law-to-outcome-tracker/, redirects to the live one.

## Automated jobs

| Workflow | When (UTC) | What it does | How it fails safely |
|---|---|---|---|
| **Refresh and deploy** `refresh.yml` | Nightly 07:17, backstop 15:47; every push to `main`; by hand | 1. `impactline.refresh`: GovInfo law ZIPs (downloaded only when their listing changes), Federal Register citations (up to 320 laws a night, each on its own schedule), USAspending fund-code totals and program traces (weekly per law), award searches (up to 140 laws a night). 2. Tests. 3. Build site and evidence packets. 4. Share cards. 5. Guard. 6. Headless-Chrome check. 7. Attest `evidence/manifest.json`. 8. Commit `data/`. 9. Deploy. 10. Check the live site. A push skips step 1. | Each source runs on its own: a failure keeps that source's last good files and is recorded in `data/status.json`; pages keep showing each record's own check date. A law ZIP that lists 10% fewer laws than last time is not trusted. Any failure in steps 2 to 6 stops before deploy, so the last good site stays live. A failed attestation is a warning, not a stop; `evidence/attestation.json` says whether the build was attested. |
| **Weekly self-test** `selftest.yml` | Wed 09:23; by hand | Tests; `refresh --check-fresh` (fails if a source has had no successful read in 3 days for laws and Federal Register, 4 for award search, 10 for fund codes and traces); live site: key pages, about 45 law pages, and each sampled evidence packet against the manifest; checks the live staged/indexed state matches the configuration. If the live build is over 60 hours old it starts **Refresh and deploy**. Keep-alive. | Read-only. A failure emails the repository owner. |
| **Weekly link check** `linkcheck.yml` | Sat 10:41; by hand | Every program-guide link and a weekly sample of GovInfo, Federal Register and USAspending links, one request a second. Results in the job summary. | Report-only. Sites that refuse automated requests are listed as "refused" and never worked around. Fails only if most GovInfo links are broken (the address pattern changed). |
| **Tests** `test.yml` | Pull requests, other branches | Tests on Python 3.9 and 3.12, build, guard, browser check. | Never deploys. |

**Keep-alive.** The nightly data commit normally keeps the schedules alive. As a backstop each scheduled run calls
`.github/scripts/keepalive.sh` (re-enables workflows GitHub paused for inactivity; empty commit after 45 quiet days).

**GitHub skips scheduled runs on this account.** Two nightly slots, per-law check dates, and the self-test's stale
check mean no run has to fire at a set time. The times in the table are the earliest a run can start, and a new or
changed schedule can take hours to start at all: on 2026-11-10 the first scheduled self-test started about eight hours
after its schedule was last pushed, and the 15:47 refresh started at 21:26. Both passed.

## What to watch
- **Actions tab → Refresh and deploy.** Red means the site was not updated; the previous site is still live. The failing
  step says why. Guard prints each problem.
- **A deploy that times out.** GitHub Pages sometimes stalls while taking in a build. The deploy job offers the same
  build a second time before failing, and the previous site stays live either way. If both attempts fail, re-run the
  failed job from the Actions tab.
- **`data/status.json`**: per source `ok`, `last_success`, `error`, `note`, and `waiting` (laws still due).
  `waiting` should fall to near zero within a week of a first fill. If it keeps growing, raise the budgets in
  `config/site.json` or run the workflow by hand with a larger budget.
- **Evidence attestation warnings.** "The evidence manifest was not attested in this run" means Sigstore or the
  attestations API was unavailable. The next run attests again.
- **Link-check summary.** Program-guide links (EPA, FHWA, NTIA, TxDOT, CARB) are other agencies' pages and will move.
  Update `config/programs.json` when one breaks.
- **New Congress.** In January of odd years the window adds a Congress automatically. Nothing to do.
- **Source drift.** If USAspending renames fund-code endpoints or the Federal Register API changes its fields, the
  affected source fails closed (keeps old data) and the weekly self-test turns red within the limits above.

## Manual levers
- **Run now:** Actions → Refresh and deploy → Run workflow. Untick "refresh" to only rebuild. Set "budget" (for example
  2000) to read every law in one run.
- **One law now:** `python3 -m impactline.refresh --law 117-58` locally, then commit `data/`.
- **Add an "also called" name:** `config/aliases.json` (only for laws whose enacted text has no short title).
- **Add a program trace:** `config/programs.json` (law, Assistance Listing number, guides). The law must carry a fund code.
- **Pacing and budgets:** `config/site.json` (`pace` seconds per host, `budget`).

## Where the site lives, and how to move it

**Standing rule: never replace, only build on top.** This site goes beside the original on a name of its own. Nothing
here points `app.impactline.org` at this site or redirects the original to it, and no step below asks for that.

Current state, checked 2026-11-22:
- `impactline.org` uses SiteGround nameservers (`ns1/ns2.siteground.net`). `app.impactline.org` is a CNAME to
  `custom-domains.chatgpt.site.` (the original, on OpenAI Sites). `www` and the apex go to Vercel (the marketing
  site). The zone also has `CNAME  data  →  theguysaccount.github.io.`
- This repository's Pages custom domain is `data.impactline.org`. The certificate is approved and HTTPS is enforced.
- The repository variable `SITE_URL=https://data.impactline.org` is set. It is now optional (see below) and not wrong.
  `SITE_INDEXABLE` is not set.

**One setting moves the site: the Pages custom domain.** Every workflow run asks GitHub which address the site is
served at (`.github/scripts/site-url.sh`) and builds each link, canonical, feed, packet link, robots.txt and the
sitemap for it. The repository variable `SITE_URL` is used instead when it is set, so it must never disagree with the
Pages setting: delete it, or change both in one sitting.

To move the site to another name, say `<name>.impactline.org`:

1. **DNS**, in the original domain's zone (SiteGround → Site Tools → Domain → DNS Zone Editor, zone `impactline.org`): add
   `CNAME  <name>  →  theguysaccount.github.io.`
   Change nothing else, and never the `app` record. This Mac's resolver caches, so check from outside it:
   `curl -s "https://dns.google/resolve?name=<name>.impactline.org&type=CNAME"`
2. **Pages custom domain:**
   `gh api -X PUT repos/theguysaccount/impactline-law-to-outcome-tracker/pages -f cname=<name>.impactline.org`
3. **Wait for the certificate, then enforce HTTPS.** Repeat the first command until it prints `approved`:
   `gh api repos/theguysaccount/impactline-law-to-outcome-tracker/pages --jq .https_certificate.state`
   `gh api -X PUT repos/theguysaccount/impactline-law-to-outcome-tracker/pages -F https_enforced=true`
4. **Remove the override**, so the address comes from the Pages setting:
   `gh variable delete SITE_URL -R theguysaccount/impactline-law-to-outcome-tracker`
5. **Rebuild for the new address:**
   `gh workflow run "Refresh and deploy" -R theguysaccount/impactline-law-to-outcome-tracker -f refresh=false`
   From step 2 until this run finishes, the new name serves the old build, whose stylesheet and links still point
   at the old address. Do steps 2 to 5 in one sitting.
6. **Check:**
   `gh workflow run "Weekly self-test" -R theguysaccount/impactline-law-to-outcome-tracker`
   It fails if the live pages, robots.txt or sitemap are not what this repository is configured for.

To go back to the github.io address: clear the custom domain with
`gh api -X PUT repos/theguysaccount/impactline-law-to-outcome-tracker/pages --input - <<< '{"cname":null}'`, delete the `SITE_URL` variable, run step 5, then
remove the DNS record. At a github.io address the site is staged again.

## What search engines may index

- **Staged at a github.io address, live at its own.** Staged means every page is `noindex`, robots.txt disallows
  everything, there is no sitemap and IndexNow is skipped. `"indexable": "auto"` in `config/site.json` is that rule,
  so the site has been indexable since it moved to `data.impactline.org`.
- **To take it out of search again** (the original app is itself `noindex`, so this is a fair choice):
  `gh variable set SITE_INDEXABLE --body false -R theguysaccount/impactline-law-to-outcome-tracker`, then step 5. `true` makes a github.io address indexable.
- **Pages the original already serves stay `noindex` when the site is live.** They also stay out of the sitemap and
  are never sent to IndexNow, and each shows a line that points to the original. They are listed in
  `config/site.json` under `duplicates_of_original`. Today: the home page, the law lists (`/laws/` and one per
  Congress), how evidence works, and about. The original is one page that lists the enacted laws, shows the law you
  pick and explains its evidence rules; it has no address per law.
- **Indexable because only this site has them:** one page per law, the spending and Federal Register lists, the
  program traces, and the data and packet downloads.
- **When the original starts serving something this site indexes**, such as an address per law, add that path to
  `duplicates_of_original` and push. A key ending in `*` covers every path under it. The guard refuses a live build
  in which a listed duplicate is indexable or in the sitemap, or an indexable page is missing from the sitemap.
- The default share image (`static/og-default.png`) prints `app.impactline.org`, the original's address. Pages with
  their own card do not use it.

## Keys Jack can turn later

1. **Another name for the site.** Above.
2. **Money: alerts and API.** One marked slot ("Paid service") on every law page, off until
   `gh variable set ALERTS_URL --body "https://<service>" -R theguysaccount/impactline-law-to-outcome-tracker`.
   GitHub Pages is non-commercial, so the paid service itself (Stripe, email delivery, API keys) must live on other
   hosting. The per-law Atom feeds and `evidence/<id>.json` files are the data such a service would read.
3. **Analytics.** `gh variable set GOATCOUNTER_URL --body "https://<code>.goatcounter.com/count" -R …` after creating a
   GoatCounter site (needs an account).
4. **Fresher law list.** GovInfo publishes a law's file days to weeks after approval. A Congress.gov API key
   (free, needs sign-up at api.data.gov) could list laws on the day they are approved. Not built: it would add a secret
   for a small gain. If wanted, add a `CONGRESS_API_KEY` secret and a source that only adds law numbers and dates
   ahead of GovInfo.
5. **Regulations.gov dockets and AI step extraction** (in the original, never configured): both need keys and a
   server-side budget. A scheduled Claude routine could draft "implementation steps" for the 20 tagged laws into
   `content/` as reviewed, quoted extracts; nothing here depends on it.
6. **Search Console:** verify `data.impactline.org` (or the whole domain, with a DNS TXT record) and submit
   `https://data.impactline.org/sitemap.xml`. Needs a Google account, so it is a human step.

## Costs
$0. Public repository, GitHub-hosted runners (about 5 minutes a night), GitHub Pages, no keys.
