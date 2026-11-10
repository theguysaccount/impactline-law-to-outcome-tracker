# PRODUCT

**ImpactLine, static edition.** The public delivery record: one page per enacted law that follows it into the Federal
Register and federal spending records, and leaves the gaps visible.

## The user
People whose job is to answer "where did the money from this law go, and what evidence exists": state auditors and
inspectors general, investigative reporters, legislative staff, watchdog researchers, grant-compliance consultants.

## The painful job
Stitching together GovInfo, the Federal Register and USAspending by hand for one law, then explaining to an editor or a
committee which links are official and which are guesses.

## The promise
Open a law and see, in one minute: the agency documents that cite it, any spending the Treasury itself ties to it, and a
plain statement of what the public record cannot show. Every figure has a source link and a check date. Download the
same record as a packet whose digest is attested.

## The wedge
The 20 laws whose spending Treasury tags by law (infrastructure, COVID relief, emergency and disaster supplementals) are
the ones reporters ask about, and they are the ones where the money trail is official. Lead with those and with the three
program traces. Every other law gets an honest page instead of a blank.

## Why now
Infrastructure and relief money is still being obligated and paid out years after enactment, and delivery is being
questioned. The federal sources are all open and keyless, so the record can be kept current by a scheduled job.

## The one activation metric
Evidence-packet downloads and outbound clicks to an official source, per visitor (did the visitor take the record
somewhere?). Countable once `GOATCOUNTER_URL` is set (OPERATIONS.md, key 3).

## First revenue event
Email alerts and API access for followed laws, on separate hosting (GitHub Pages is non-commercial). One marked slot,
off until `ALERTS_URL` is set. Grants from transparency funders are the more realistic path.

## What v1 deliberately does not do
- No conclusions: nothing about fraud, waste, delay, compliance or success, and no scores.
- No summing of keyword matches. No "this law's spending" unless Treasury tagged it.
- No AI summaries or extraction. No state, local or outcome data. No accounts.
