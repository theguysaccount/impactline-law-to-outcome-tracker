#!/usr/bin/env bash
# Find the address this site is served at and export it as SITE_URL for the rest of the job.
#
# One setting moves the site: the custom domain in the repository's GitHub Pages settings. With a
# custom domain the address is https://<that domain>; without one it is the github.io project
# address. The repository variable SITE_URL, when set, is used instead (for an address GitHub
# cannot know, such as a proxy in front of Pages).
#
# Fails when GitHub cannot be asked. Building for a guessed address would publish pages whose
# links and stylesheet point somewhere else, so the last good site stays up instead.
set -euo pipefail

url="${SITE_URL_VARIABLE:-}"
if [ -z "$url" ]; then
  ok=""
  for attempt in 1 2 3; do
    if cname=$(gh api "repos/${GITHUB_REPOSITORY}/pages" --jq '.cname // ""'); then
      ok=1
      break
    fi
    sleep $((attempt * 5))
  done
  if [ -z "$ok" ]; then
    echo "::error::Could not read the GitHub Pages settings, so the site's address is unknown. Nothing was built."
    exit 1
  fi
  if [ -n "$cname" ]; then
    url="https://${cname}"
  else
    url="https://${GITHUB_REPOSITORY_OWNER}.github.io/${GITHUB_REPOSITORY#*/}"
  fi
fi
url="${url%/}"
echo "Site address: ${url}"
echo "SITE_URL=${url}" >> "$GITHUB_ENV"
