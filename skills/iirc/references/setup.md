# Setup, led by you

The creator never has to run a command. Hold a short conversation, then
run the commands yourself.

1. Ask, in one question: "IIRC searches by meaning, which needs an
   embedding model. It can run in ollama on this machine or on a host
   you name, on an OpenAI-compatible host, or on this CPU with no ollama.
   Where none of these can run, a string search fallback matches exact
   text only and works less well. Which do you want?" Recommend ollama
   with qwen3-embedding:0.6b when ollama runs here or on a host they
   name, and this CPU otherwise. If they ask what the difference is:
   semantic search finds the missing-wheel page from "why does install
   fail on a mac"; string search needs "pysqlite3".
2. For ollama on a remote host or an OpenAI-compatible host, ask its
   address.
3. Ask whether to create `.iirc/` in this repository, if it has none.

Then run, in order, showing each command first:

```
iirc set-search-backend --local          ollama here; --host URL for a remote one; qwen3-embedding:0.6b unless --model names nomic-embed-text or embeddinggemma
iirc set-search-backend --openai URL     or: an OpenAI-compatible host serving qwen3-embedding
iirc set-search-backend --cpu            or: all-MiniLM-L6-v2 on this CPU; fetches about 90 MB and installs onnxruntime once
iirc set-search-backend --substring      or: the string fallback
iirc init                   if the creator said yes to a field
iirc doctor --fix           installs the tool; for a local host on macOS also ollama and the model
```

Every ollama embed request asks ollama to keep the model loaded for 24
hours, so an ollama install needs no `OLLAMA_KEEP_ALIVE` setting. On a
remote host, this request overrides the operator's keep-alive setting for
iirc's model. The model still loads cold after more than 24 hours with
no search or index.

If `--cpu` fails because onnxruntime has no wheel for this machine, it
writes nothing; offer the string fallback. A model change starts a
vector store of its own: every page is embedded again, by the next
`iirc rebuild-search-index` or in the background by the first search. The suggestion thresholds
are per model, in `[suggestions.MODEL-ID]` of `.claude/iirc.toml`, so a new
model starts at its own defaults and a table tuned for another model
stays as it was.

Report what `doctor` says. It also checks that `.iirc/`,
`.claude/settings.json`, and `CLAUDE.md` are tracked by git and not
ignored, because iirc only persists if they are committed. `init` stages
what it creates; tell the creator what is left to commit. If `doctor` names
something only the creator can do, such as installing ollama on a remote
host, say exactly that and stop.

The host is whatever the creator named; a guess is never right. `set-search-backend`
runs once per machine: running it again overwrites their choice, so ask
before a second run.

## What the creator sees of the hooks

By default the plugin draws the hook lines for the creator: suggested pages
under the prompt or failed command, a row when a command failed and then
worked, and a colored line under the prompt with the page count and the
pages this session read and wrote. The creator turns that line on or off
by typing `/iirc summary-line-visibility on` or `/iirc summary-line-visibility off`; it is on by
default and the choice holds on that machine. In `.claude/iirc.toml`,
`ui = false` turns all of it off, and `show_hooks = true` also prints the raw
text you receive, for debugging. Add the key the creator asks for at the
top of the file, creating it if it is missing, and commit it. It takes
effect at the next hook; no restart.
