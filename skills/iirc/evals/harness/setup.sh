#!/bin/sh
# setup.sh [WORKSPACE] [OLD_REV]
# Builds the eval workspace: three plugin copies and the fixture repositories.
#   plugin-live      this checkout, the skill under test (condition new_skill)
#   plugin-noskill   this checkout minus skills/, so hooks and CLI stay (without_skill)
#   plugin-snapshot  this repository at OLD_REV, the baseline for an iteration (old_skill)
# Prints the export line the other scripts need.
set -eu
H=$(cd "$(dirname "$0")" && pwd)
REPO=$(cd "$H/../../../.." && pwd)
W=${1:-${TMPDIR:-/tmp}/iirc-eval-workspace}
OLD_REV=${2:-HEAD~1}
mkdir -p "$W"
for c in plugin-live plugin-noskill plugin-snapshot; do rm -rf "$W/$c"; done
git -C "$REPO" worktree list >/dev/null   # a git checkout, so plugin_commit() reads a sha
cp -R "$REPO" "$W/plugin-live"
rm -rf "$W/plugin-live/.venv" "$W/plugin-live/.pytest_cache"
cp -R "$W/plugin-live" "$W/plugin-noskill" && rm -rf "$W/plugin-noskill/skills"
git clone -q "$REPO" "$W/plugin-snapshot" && git -C "$W/plugin-snapshot" checkout -q "$OLD_REV"
export MEMORY_EVAL_WORKSPACE=$W
sh "$H/build_fixtures.sh"
echo "export MEMORY_EVAL_WORKSPACE=$W"
