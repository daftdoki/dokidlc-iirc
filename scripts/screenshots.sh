#!/bin/sh
# Capture the iirc screens with vhs into docs/images/, for UI.md and the README.
#
#   scripts/screenshots.sh [REPO]
#
# REPO is a repository that runs this plugin and has pages in .iirc/ (default: the
# current directory). The cards use sample numbers (/iirc demo); the pane uses
# sample numbers over REPO's real pages (/iirc reader demo). Needs vhs (brew install
# vhs) and uv. Claude Code starts in REPO as you, logged in; one prompt is sent so
# the suggested-pages row appears, then interrupted.
#
# The pane is captured twice: docked beside the transcript (a wide terminal in
# fullscreen) and inline above the prompt (under 110 columns).
set -eu

here=$(cd "$(dirname "$0")/.." && pwd)
repo=$(cd "${1:-.}" && pwd)
out=$here/docs/images
# the smallest page, so its card fits on one screen
page=${IIRC_SHOT_PAGE:-$(ls -S "$repo/.iirc" | grep -v '^index.md$' | grep '\.md$' | tail -1)}
prompt=${IIRC_SHOT_PROMPT:-"why does the recall hook time out when ollama unloads the embed model?"}
work=$(mktemp -d)
trap 'rm -rf "$work"' EXIT
mkdir -p "$out"
command -v vhs >/dev/null || { echo "screenshots: vhs is not installed (brew install vhs)" >&2; exit 1; }

# a tape: start Claude Code in REPO at WIDTH pixels, then the steps given on stdin
tape() {
  name=$1 width=$2 height=$3
  {
    echo "Output $name.gif"
    echo 'Set Shell zsh'
    echo 'Set FontSize 16'
    echo "Set Width $width"
    echo "Set Height $height"
    echo 'Set TypingSpeed 15ms'
    echo 'Hide'
    # unset the marker a parent Claude Code session leaves, so this one keeps its transcript; no shell commands, so the
    # recorded session's agent cannot reach git, ssh, or anything that asks 1Password
    echo "Type \"cd $repo && env -u CLAUDE_CODE_CHILD_SESSION IIRC_RECORDING=1 claude --disallowedTools Bash\""
    echo 'Enter'
    echo 'Sleep 8s'
    echo 'Show'
    cat
    echo 'Hide'
    echo 'Ctrl+C'
    echo 'Ctrl+C'
    echo 'Sleep 1s'
  } > "$work/$name.tape"
  (cd "$work" && vhs "$name.tape" >/dev/null)
}

# one command after a clear screen, then a capture
shot() {
  printf 'Type "/clear"\nEnter\nSleep 2s\nType "%s"\nSleep 500ms\nEnter\nSleep %s\nScreenshot %s.png\n' "$1" "$2" "$3"
}

# wide: the cards, the row under a prompt, and the pane docked
{
  shot '/iirc demo' 4s card-home
  shot '/iirc demo status' 4s card-status
  shot '/iirc help' 4s card-help
  shot '/iirc doctor' 10s card-doctor
  shot "/iirc show $page" 4s card-page
  printf 'Type "/clear"\nEnter\nSleep 2s\nType "%s"\nEnter\nSleep 5s\nEscape\nSleep 2s\nScreenshot prompt-row.png\nType "/iirc open"\nEnter\nSleep 3s\nScreenshot prompt-row-open.png\n' "$prompt"
  shot '/iirc reader demo' 4s pane-docked-session
  printf 'Enter\nSleep 3s\nScreenshot pane-docked-page.png\nEscape\nSleep 1s\nScreenshot pane-docked-keys-off.png\nType "q"\nSleep 500ms\nCtrl+U\n'
} | tape wide 1600 1300

# narrow: the pane inline above the prompt
{
  shot '/iirc reader demo' 4s pane-inline-session
  printf 'Enter\nSleep 3s\nScreenshot pane-inline-page.png\n'
} | tape narrow 1000 1000

# the cards cropped to their frames; the row and the pane kept whole, as they sit on screen
for card in home status help doctor page; do
  uv run --quiet "$here/scripts/crop-card.py" "$work/card-$card.png" "$out/iirc-card-$card.png"
done
for shot in prompt-row prompt-row-open pane-docked-session pane-docked-page pane-docked-keys-off pane-inline-session pane-inline-page; do
  cp "$work/$shot.png" "$out/iirc-$shot.png"
  echo "$out/iirc-$shot.png"
done
