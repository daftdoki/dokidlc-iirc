# Setup, led by you

The creator never has to run a command. Hold a short conversation, then
run the commands yourself.

The model belongs to the repository: `embedding_model` in
`.claude/iirc.toml`, committed, the same on every machine. Where it runs
belongs to the machine: its list of embedding models in
`~/.config/dokidlc-iirc/config.toml`, each one a model and a host.

1. Ask which model, in one question: "IIRC searches by meaning, which
   needs an embedding model. I recommend qwen3-embedding-0.6b through
   ollama. Without ollama, all-minilm-l6-v2 runs on this CPU. Where
   neither can run, string search matches exact text only and works less
   well. Which do you want?" If they ask what the difference is: semantic
   search finds the missing-wheel page from "why does install fail on a
   mac"; string search needs "pysqlite3". The models are
   `nomic-embed-text`, `qwen3-embedding-0.6b`, and `all-minilm-l6-v2`.
2. Ask where it runs on this machine: ollama here (`local`), the URL of
   an ollama or OpenAI-compatible host, or this CPU (`cpu`, MiniLM only).
   The host is whatever the creator named; a guess is never right.
3. Ask whether to create `.iirc/` in this repository, if it has none.

Then run, in order, showing each command first:

```
iirc add-embedding-model MODEL HOST   HOST: local, a URL, or cpu; finds ollama or OpenAI-compatible, refuses a host without the model
iirc set-embedding-model MODEL        this repository's model; commit .claude/iirc.toml
iirc search-mode string               instead of the two above, for the string fallback
iirc init                             if the creator said yes to a field
iirc doctor --fix                     installs the tool; for this machine's ollama on macOS also ollama and the model
```

`add-embedding-model` never pulls. When it refuses a host without the
model, it prints the pull command: run it on this machine's ollama on the
creator's yes; for another host, hand the creator the command, because a
pull there is theirs to approve. It also prints the fingerprint: the
host's vector for a probe sentence against the plugin's reference. A
warning under 0.995 means the host serves another build or model under
the name; tell the creator. Another width is refused.

When two listed hosts serve the repository's model, a command run on a
terminal asks which one this machine uses. The session-start line says
so when no one has chosen; ask the creator and run
`iirc prefer-embedding-host MODEL HOST`. `iirc show-embedding-models`
lists the machine's entries and marks the one in use.

Every ollama embed request asks ollama to keep the model loaded for 24
hours, so an ollama install needs no `OLLAMA_KEEP_ALIVE` setting. On a
remote host, this request overrides the operator's keep-alive setting for
iirc's model. The model still loads cold after more than 24 hours with
no search or index.

If `add-embedding-model ... cpu` fails because onnxruntime has no wheel
for this machine, it writes nothing; offer the string fallback.

Report what `doctor` says. It also checks that `.iirc/`,
`.claude/settings.json`, and `CLAUDE.md` are tracked by git and not
ignored, because iirc only persists if they are committed. `init` stages
what it creates; tell the creator what is left to commit. If `doctor` names
something only the creator can do, such as installing ollama on a remote
host, say exactly that and stop.

When doctor or the session-start line says the settings have the old
shape (`semantic`, `embedding`, or `embedding_host` in the setup file, or
a protocol's name such as `qwen3-embedding:0.6b` in `embedding_model`),
run `iirc doctor --fix`; it converts them once. Commit
`.claude/iirc.toml` if it changed.

## When this machine cannot serve the repository's model

The session-start line and doctor say "this machine cannot serve MODEL",
and search matches strings until it is fixed. Offer the creator these
four ways out, and run the one they choose:

1. Add a host that serves it: `iirc add-embedding-model MODEL URL`.
2. Load it on an ollama host: `iirc doctor --fix` installs ollama and
   pulls the model on this machine once it is listed with
   `iirc add-embedding-model MODEL local`; on another host, give the
   creator `OLLAMA_HOST=URL ollama pull NAME` to run with their approval,
   then add it.
3. Switch this repository to a model a listed host serves:
   `iirc set-embedding-model MODEL`, after `iirc show-embedding-models`.
4. Switch to the CPU model: `iirc add-embedding-model all-minilm-l6-v2 cpu`,
   then `iirc set-embedding-model all-minilm-l6-v2`.

Before a switch (3 or 4), state its costs: every page is embedded again,
the suggestion thresholds start at the new model's defaults (they live per
model in `[suggestions.MODEL-ID]` of `.claude/iirc.toml`), and tuning
judgments made under the old model stop counting. The switch changes the
model for every machine that uses this repository, so commit
`.claude/iirc.toml` only on the creator's yes.

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
