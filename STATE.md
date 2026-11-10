# STATE (2026-11-10)

**Staged copy:** https://theguysaccount.github.io/impactline-law-to-outcome-tracker/ (noindex; the original at
app.impactline.org is live and unchanged).

## Works
- 774 public laws (117th to 119th Congress, through P.L. 119-138) read from GovInfo bulk data, with no API key.
- One page per law: identity from the law's own file, the seven-step record, Federal Register documents that cite it,
  spending Treasury tags to it (20 laws), or awards that name it (keyword candidates), each with source and check date.
- Three program traces (Clean School Bus, Bridge Formula, Middle Mile) joined by fund code and Assistance Listing.
- Evidence packet per law (canonical JSON), a manifest of SHA-256 digests attested by GitHub on every build, and an
  in-browser check. CSV/JSON mirror. Atom feeds (new laws; per-law Federal Register documents).
- Nightly refresh within a request budget, weekly self-test and link check, keep-alive. 40 tests.

## What the original has that this copy does not
- Live per-request search of Regulations.gov, AI extraction of implementation steps (never configured), the
  interactive state/program selector, and ECDSA-signed exports from a server-held key. All need a server or a secret.
- The original's law list came from the Congress.gov API (needs a key; the demo quota ran out in testing). This copy
  reads GovInfo instead, which is keyless and was 14 laws ahead of the live original on 2026-11-10.

## Reused from the original
- The product contract and wording discipline (candidates never set completion; no fraud or completion claims).
- The seven stages, the three pilot programs and their official guides (`lib/impactline/programs.ts`).
- Brand: logo mark, Inter and Instrument Serif (recovered from the live site), palette, share image.
- Popular law titles from the original's 2026-09-12 Congress.gov import (`data/congress-titles.json`).

## Not done
- No analytics. No custom domain (cutover is Jack's call: OPERATIONS.md). No paid alerts or API (slot is off).
