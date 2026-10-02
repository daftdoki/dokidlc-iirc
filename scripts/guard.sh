#!/bin/sh
# memory guard. POSIX sh so it always parses. Reads PreToolUse JSON on stdin,
# for Bash and for Read.
# Asks before `memory doubt --network` (contacts every URL cited in pages) and
# `memory approve` (accepts a page's check command for this machine).
# Denies a raw read of a page file, by cat, head, sed, tail, less, or more in a
# Bash command, or by the Read tool: `memory read` prints the page with its
# trust markers and ends with the commands that fix it; a raw read loses both.
# A deny, not an ask, because the reason reaches the agent only on a deny; the
# reason names the way out when `memory read` itself is broken.
# Everything else is allowed.
input=$(cat)
cmd=$(printf '%s' "$input" | sed -n 's/.*"command":[[:space:]]*"\(.*\)".*/\1/p' | head -c 4000)
file=$(printf '%s' "$input" | sed -n 's/.*"file_path":[[:space:]]*"\([^"]*\)".*/\1/p' | head -c 1000)
case "$cmd" in
  *memory*doubt*--n*|*memory*--n*doubt*)
    printf '%s\n' '{"hookSpecificOutput":{"hookEventName":"PreToolUse","permissionDecision":"ask","permissionDecisionReason":"memory doubt --network contacts every URL cited in memory pages. Approve only if you agreed to that."}}'
    ;;
  *memory*approve*)
    printf '%s\n' '{"hookSpecificOutput":{"hookEventName":"PreToolUse","permissionDecision":"ask","permissionDecisionReason":"memory approve runs a page'"'"'s check command and approves it on this machine. Approve only if the agent showed you the command and you agreed."}}'
    ;;
esac
# a page read with a pager: cat, head, sed, tail, less, or more starts a simple command (at the
# start, or after ; & | ( or a newline) and a page path other than index.md follows it: .memory/*.md,
# or a remote store's clone, dokidlc-memory/stores/NAME-HASH/*.md
page=$(printf '%s' "$cmd" | sed -En 's/.*(^|[;&|(]|\\n)[[:space:]]*(cat|head|sed|less|more|tail)[[:space:]]+([^>;|&]*[[:space:]])?([^[:space:]|;&>]*(\.memory|dokidlc-memory\/stores\/[a-z0-9-]+)\/[a-z0-9-]+\.md).*/\4/p')
# the Read tool on a page file
if [ -z "$page" ]; then
  page=$(printf '%s' "$file" | sed -En 's/^(.*(\.memory|dokidlc-memory\/stores\/[a-z0-9-]+)\/[a-z0-9-]+\.md)$/\1/p')
fi
case "$page" in
  ""|*/index.md) ;;
  *)
    name=${page##*/}
    printf '{"hookSpecificOutput":{"hookEventName":"PreToolUse","permissionDecision":"deny","permissionDecisionReason":"%s is a memory page. Read it with: memory read %s, or memory read STORE/%s when two stores hold that name. That prints its trust markers and ends with the commands that fix it; a raw read loses both. If memory read itself fails, run: memory doctor --fix"}}\n' "$page" "$name" "$name"
    ;;
esac
exit 0
