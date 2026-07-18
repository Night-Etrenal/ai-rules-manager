#!/bin/sh
set -eu

UPSTREAM_URL="https://github.com/OthmanAdi/planning-with-files.git"
UPSTREAM_BRANCH="master"
SNAPSHOT_REF="upstream/planning-with-files"
REMOTE_NAME="portfolio-upstream"

root="$(git rev-parse --show-toplevel)"
cd "$root"

if ! git diff --quiet || ! git diff --cached --quiet; then
  echo "Refusing upstream review: working tree or index is not clean." >&2
  exit 2
fi

if git remote get-url "$REMOTE_NAME" >/dev/null 2>&1; then
  git remote set-url "$REMOTE_NAME" "$UPSTREAM_URL"
else
  git remote add "$REMOTE_NAME" "$UPSTREAM_URL"
fi

git fetch --no-tags "$REMOTE_NAME" "$UPSTREAM_BRANCH"
git fetch --no-tags origin "$SNAPSHOT_REF:refs/remotes/origin/$SNAPSHOT_REF"

snapshot="origin/$SNAPSHOT_REF"
candidate="$REMOTE_NAME/$UPSTREAM_BRANCH"

if ! git merge-base --is-ancestor "$snapshot" "$candidate"; then
  echo "Refusing automatic review: upstream history is not a fast-forward of the stored snapshot." >&2
  echo "Inspect provenance and history manually; do not force-update the snapshot." >&2
  exit 3
fi

count="$(git rev-list --count "$snapshot..$candidate")"
if [ "$count" -eq 0 ]; then
  echo "Stored upstream snapshot is current."
  exit 0
fi

stamp="$(date -u +%Y%m%dT%H%M%SZ)"
review_branch="upstream-review/$stamp"
git branch "$review_branch" "$candidate"

changed="$(git diff --name-only "$snapshot..$candidate")"
high_risk="$(printf '%s\n' "$changed" | grep -E '^(\.github/workflows/|\.github/actions/|\.codex/|\.agents/|AGENTS\.md$|package(-lock)?\.json$|pnpm-lock\.yaml$|yarn\.lock$|pyproject\.toml$|scripts/|src/)' || true)"

printf 'upstream_new_commits=%s\n' "$count"
printf 'review_branch=%s\n' "$review_branch"
printf '%s\n' "$changed" | sed -n '1,300p'

if [ -n "$high_risk" ]; then
  echo "High-risk upstream execution, dependency, hook, workflow or source paths changed:" >&2
  printf '%s\n' "$high_risk" >&2
fi

cat <<EOF

No upstream code was executed, merged into the product branch, committed or pushed.
Review with:
  git log --oneline $snapshot..$review_branch
  git diff --stat $snapshot..$review_branch
  git diff $snapshot..$review_branch

After review:
  1. Selectively port relevant behavior into a new product feature branch with tests.
  2. Do not merge the upstream tree directly into the independent product branch.
  3. Update the remote snapshot branch only after provenance and history are accepted:
       git push origin $review_branch:refs/heads/$SNAPSHOT_REF
  4. Open a separate reviewed PR for product changes.
EOF
