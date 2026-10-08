# Setup, led by you

The creator never has to run a command. Hold a short conversation, then
run the commands yourself.

1. Ask, in one question: "Memory searches by meaning by default, which
   needs ollama with an embedding model on this machine or on a host you
   can reach. If ollama cannot run or be reached here, there is a string
   search fallback that matches exact text only and works less well. Which
   do you want?" Recommend semantic unless they say ollama is out of
   reach. If they ask what the difference is: semantic search finds the
   missing-wheel page from "why does install fail on a mac"; string
   search needs "pysqlite3".
2. If semantic: ask whether embeddings should come from ollama on this
   machine or from a remote host, and if remote, its address.
3. Ask whether to create `.memory/` in this repository, if it has none.

Then run, in order, showing each command first:

```
memory setup --local                or --host URL, or --substring for the fallback
memory init                         if the creator said yes to a field
memory doctor --fix                 installs the tool; for a local host on macOS also ollama and the model
```

Report what `doctor` says. It also checks that `.memory/`,
`.claude/settings.json`, and `CLAUDE.md` are tracked by git and not
ignored, because memory only persists if they are committed. `init` stages
what it creates; tell the creator what is left to commit. If `doctor` names
something only the creator can do, such as installing ollama on a remote
host, say exactly that and stop.

The host is whatever the creator named; a guess is never right. `setup`
runs once per machine: running it again overwrites their choice, so ask
before a second run.

## Showing hook lines to the creator

The hooks put lines into your context that the creator does not see: the
session brief, the pages a prompt or a failed command recalls, and the
nudges to write a page. When the creator asks to see them, add
`show_hooks = true` at the top of `.claude/memory.toml`, creating the file
if it is missing, and commit it. Each line then also appears in their
terminal. It takes effect at the next hook; no restart.
