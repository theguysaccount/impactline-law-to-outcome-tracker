# OPERATIONS

Everything runs on GitHub Actions in `theguysaccount/impactline-law-to-outcome-tracker`. No human has a job here.

- Staged copy: https://theguysaccount.github.io/impactline-law-to-outcome-tracker/ (noindex).
- Live original: https://app.impactline.org (OpenAI Sites, reached through a CNAME at SiteGround). Not touched.

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

## Cutover: replacing the live original (Jack decides)

Current state, checked 2026-11-10: `impactline.org` uses SiteGround nameservers. `app.impactline.org` is a CNAME to
`custom-domains.chatgpt.site.` (OpenAI Sites). `www` and the apex go to Vercel (the marketing site) and are not part
of this.

1. **DNS** (SiteGround → Site Tools → Domain → DNS Zone Editor, zone `impactline.org`):
   change the existing record
   `CNAME  app  →  custom-domains.chatgpt.site.`
   to
   `CNAME  app  →  theguysaccount.github.io.`
   Leave the two `TXT` verification records for `app` in place until you are sure you will not roll back.
   (To keep the original running and add this site beside it, create `CNAME laws → theguysaccount.github.io.` instead
   and use `laws.impactline.org` below.)
2. **GitHub Pages:** repository Settings → Pages → Custom domain → `app.impactline.org` → Save. Wait for the
   certificate, then tick "Enforce HTTPS".
   CLI: `gh api -X PUT repos/theguysaccount/impactline-law-to-outcome-tracker/pages -f cname=app.impactline.org`
3. **The base-URL setting:**
   `gh variable set SITE_URL --body "https://app.impactline.org" -R theguysaccount/impactline-law-to-outcome-tracker`
4. **The indexing setting** (only if the site should appear in search; the original is `noindex` today):
   `gh variable set SITE_INDEXABLE --body true -R theguysaccount/impactline-law-to-outcome-tracker`
5. Actions → Refresh and deploy → Run workflow (refresh unticked). Canonical links, sitemap, robots.txt, feeds,
   packet links and IndexNow all follow the two settings. The weekly self-test checks the live state matches.
6. **Roll back:** restore the CNAME to `custom-domains.chatgpt.site.`, clear the Pages custom domain, delete the two
   variables, run the workflow.

Also update the share image text if the domain changes (`static/og-default.png` shows `app.impactline.org`).

## Keys Jack can turn later

1. **Custom domain / cutover.** Above.
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
6. **Search Console** after cutover: verify `impactline.org` with a DNS TXT record and submit `/sitemap.xml`.

## Costs
$0. Public repository, GitHub-hosted runners (about 5 minutes a night), GitHub Pages, no keys.
