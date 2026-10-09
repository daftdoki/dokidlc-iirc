# Setup, led by you

The creator never has to run a command. Hold a short conversation, then
run the commands yourself.

1. Ask, in one question: "IIRC searches by meaning by default, which
   needs ollama with an embedding model on this machine or on a host you
   can reach. If ollama cannot run or be reached here, there is a string
   search fallback that matches exact text only and works less well. Which
   do you want?" Recommend semantic unless they say ollama is out of
   reach. If they ask what the difference is: semantic search finds the
   missing-wheel page from "why does install fail on a mac"; string
   search needs "pysqlite3".
2. If semantic: ask whether embeddings should come from ollama on this
   machine or from a remote host, and if remote, its address.
3. Ask whether to create `.iirc/` in this repository, if it has none.

Then run, in order, showing each command first:

```
iirc setup --local                or --host URL, or --substring for the fallback
iirc init                         if the creator said yes to a field
iirc doctor --fix                 installs the tool; for a local host on macOS also ollama and the model
```

Report what `doctor` says. It also checks that `.iirc/`,
`.claude/settings.json`, and `CLAUDE.md` are tracked by git and not
ignored, because iirc only persists if they are committed. `init` stages
what it creates; tell the creator what is left to commit. If `doctor` names
something only the creator can do, such as installing ollama on a remote
host, say exactly that and stop.

The host is whatever the creator named; a guess is never right. `setup`
runs once per machine: running it again overwrites their choice, so ask
before a second run.

## What the creator sees of the hooks

By default the plugin draws the hook lines for the creator: recalled pages
under the prompt or failed command, a row when a command failed and then
worked, and a colored line under the prompt with the page count and the
pages this session read and wrote. The creator turns that line on or off
by typing `/iirc status-line on` or `/iirc status-line off`; it is on by
default and the choice holds on that machine. In `.claude/iirc.toml`,
`ui = false` turns all of it off, and `show_hooks = true` also prints the raw
text you receive, for debugging. Add the key the creator asks for at the
top of the file, creating it if it is missing, and commit it. It takes
effect at the next hook; no restart.
