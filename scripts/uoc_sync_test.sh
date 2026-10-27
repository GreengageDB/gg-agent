#!/bin/bash
# Bring review fixes from the unit PR branches into the test branch.
#
# usage: uoc_sync_test.sh [-n] PREFIX [REMOTE]
#   PREFIX  branch prefix, e.g. sync-15x-b2 (branches <prefix>-base,
#           <prefix>-test, <prefix>-uoc1..N)
#   REMOTE  default origin
#   -n      do everything except the push
#
# The test branch and every unit branch share the merge commit as their
# common ancestor, so merging a unit branch brings in only the commits made
# on it after it was cut (a unit's own change is already on both sides).
# The base branch is merged too, so unit PRs merged into it come along.
# All branches not yet contained in the test branch go in as one octopus
# merge; if it does not merge cleanly, they are merged one by one and a
# branch that conflicts is left out (the next run retries it), so the rest
# still reach the test branch.  The exit status is 1 when the base branch is
# left out.  The work happens in a temporary worktree, so the current checkout
# is not touched; the push is a plain fast-forward of the test branch, which
# re-runs CI on its PR.  Unlike sync-uoc-test.yml, it does not comment on PRs.
set -euo pipefail

push=1
if [ "${1:-}" = "-n" ]; then push=0; shift; fi
if [ $# -lt 1 ]; then sed -n '2,/^set -e/p' "$0" | sed '$d'; exit 2; fi
prefix=$1
remote=${2:-origin}
test=$prefix-test
base=$prefix-base

git fetch -q "$remote" "+refs/heads/$prefix-*:refs/remotes/$remote/$prefix-*"

branches=()
# only <prefix>-uoc<N>, not other branches that share the prefix
units=$(git for-each-ref --format='%(refname:short)' "refs/remotes/$remote/$prefix-uoc*" \
            | grep -E "^$remote/$prefix-uoc[0-9]+$" | sort -V || true)
for ref in $units "$remote/$base"; do
    if ! git merge-base --is-ancestor "$ref" "$remote/$test"; then
        branches+=("$ref")
    fi
done
if [ ${#branches[@]} -eq 0 ]; then
    echo "$test already contains every unit branch and $base"
    exit 0
fi
echo "to merge into $test: ${branches[*]#$remote/}"

wt=$(mktemp -d)
trap 'git worktree remove --force "$wt" >/dev/null 2>&1 || rm -rf "$wt"' EXIT
git worktree add -q --detach "$wt" "$remote/$test"

msg="Merge review fixes into $test

$(for b in "${branches[@]}"; do echo "- ${b#$remote/}: $(git log -1 --format=%s "$b")"; done)"

skipped=() failed=0
if ! git -C "$wt" merge -q --no-ff --no-edit -m "$msg" "${branches[@]}" >/dev/null 2>&1; then
    git -C "$wt" merge --abort >/dev/null 2>&1 || git -C "$wt" reset -q --hard
    for b in "${branches[@]}"; do
        m="Merge ${b#$remote/} into $test"$'\n\n'"- ${b#$remote/}: $(git log -1 --format=%s "$b")"
        git -C "$wt" merge -q --no-ff --no-edit -m "$m" "$b" >/dev/null 2>&1 && continue
        echo "conflict when merging ${b#$remote/} into $test, left out:" >&2
        git -C "$wt" diff --name-only --diff-filter=U | sed 's/^/  /' >&2
        git -C "$wt" merge --abort >/dev/null 2>&1 || git -C "$wt" reset -q --hard
        skipped+=("${b#$remote/}")
        [ "$b" != "$remote/$base" ] || failed=1
    done
fi

new=$(git -C "$wt" rev-parse HEAD)
if [ "$(git rev-parse "$new^{tree}")" = "$(git rev-parse "$remote/$test^{tree}")" ]; then
    echo "the tree of $test does not change, not pushing"
else
    git --no-pager diff --stat "$remote/$test" "$new"
    if [ $push -eq 1 ]; then
        git push "$remote" "$new:refs/heads/$test"
    else
        echo "not pushed (-n): $new"
    fi
fi
if [ ${#skipped[@]} -gt 0 ]; then
    echo "left out of $test, merge by hand: ${skipped[*]}" >&2
fi
exit $failed
