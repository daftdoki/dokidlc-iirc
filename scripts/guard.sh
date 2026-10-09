#!/bin/sh
# engrams guard. POSIX sh so it always parses. Reads PreToolUse JSON on stdin,
# for Bash and for Read.
# Asks before `engrams doubt --network` (contacts every URL cited in pages) and
# `engrams approve` (accepts a page's check command for this machine).
# Denies a raw read of a page file, by cat, head, sed, tail, less, or more in a
# Bash command, or by the Read tool: `engrams read` prints the page with its
# trust markers and ends with the commands that fix it; a raw read loses both.
# A deny, not an ask, because the reason reaches the agent only on a deny; the
# reason names the way out when `engrams read` itself is broken.
# Everything else is allowed.
input=$(cat)
cmd=$(printf '%s' "$input" | sed -n 's/.*"command":[[:space:]]*"\(.*\)".*/\1/p' | head -c 4000)
file=$(printf '%s' "$input" | sed -n 's/.*"file_path":[[:space:]]*"\([^"]*\)".*/\1/p' | head -c 1000)
case "$cmd" in
  *engrams*doubt*--n*|*engrams*--n*doubt*)
    printf '%s\n' '{"hookSpecificOutput":{"hookEventName":"PreToolUse","permissionDecision":"ask","permissionDecisionReason":"engrams doubt --network contacts every URL cited in the pages. Approve only if you agreed to that."}}'
    ;;
  *engrams*approve*)
    printf '%s\n' '{"hookSpecificOutput":{"hookEventName":"PreToolUse","permissionDecision":"ask","permissionDecisionReason":"engrams approve runs a page'"'"'s check command and approves it on this machine. Approve only if the agent showed you the command and you agreed."}}'
    ;;
esac
# a page read with a pager: cat, head, sed, tail, less, or more starts a simple command (at the
# start, or after ; & | ( or a newline) and a page path other than index.md follows it: .engrams/*.md,
# or a remote store's clone, dokidlc-engrams/stores/NAME-HASH/*.md
page=$(printf '%s' "$cmd" | sed -En 's/.*(^|[;&|(]|\\n)[[:space:]]*(cat|head|sed|less|more|tail)[[:space:]]+([^>;|&]*[[:space:]])?([^[:space:]|;&>]*(\.engrams|dokidlc-engrams\/stores\/[a-z0-9-]+)\/[a-z0-9-]+\.md).*/\4/p')
# the Read tool on a page file
if [ -z "$page" ]; then
  page=$(printf '%s' "$file" | sed -En 's/^(.*(\.engrams|dokidlc-engrams\/stores\/[a-z0-9-]+)\/[a-z0-9-]+\.md)$/\1/p')
fi
case "$page" in
  ""|*/index.md) ;;
  *)
    name=${page##*/}
    printf '{"hookSpecificOutput":{"hookEventName":"PreToolUse","permissionDecision":"deny","permissionDecisionReason":"%s is an engram page. Read it with: engrams read %s, or engrams read STORE/%s when two stores hold that name. That prints its trust markers and ends with the commands that fix it; a raw read loses both. If engrams read itself fails, run: engrams doctor --fix"}}\n' "$page" "$name" "$name"
    ;;
esac
exit 0
