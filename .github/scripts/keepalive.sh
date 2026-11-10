#!/usr/bin/env bash
# GitHub pauses scheduled workflows in a public repository after 60 days without a commit.
# Run from every scheduled job: re-enable any workflow GitHub paused for inactivity, and push an
# empty commit when the default branch has been quiet for 45 days. Never fails the calling job.
set -u
git config user.name "github-actions[bot]"
git config user.email "41898282+github-actions[bot]@users.noreply.github.com"
for wf in "$@"; do
  state=$(gh api "repos/$GITHUB_REPOSITORY/actions/workflows/$wf" --jq .state 2>/dev/null || echo unknown)
  if [ "$state" = "disabled_inactivity" ]; then
    gh api -X PUT "repos/$GITHUB_REPOSITORY/actions/workflows/$wf/enable" >/dev/null \
      && echo "::warning::Re-enabled $wf (GitHub had paused it for inactivity)" \
      || echo "::warning::Could not re-enable $wf"
  fi
done
git fetch -q origin main 2>/dev/null || true
last=$(git log -1 --format=%ct origin/main 2>/dev/null || git log -1 --format=%ct)
if [ $(( $(date +%s) - last )) -gt $(( 45 * 86400 )) ]; then
  git commit -q --allow-empty -m "keep-alive: no changes in 45 days" \
    && (git push -q origin HEAD:main || echo "::warning::keep-alive push failed")
fi
exit 0
