# dokidlc-skill-iirc

A Claude Code plugin that keeps what your agent learns in the repository, searchable by meaning.

It installs as `iirc@dokidlc`. Pages are markdown files in `.iirc/` in
the [memoryfield](https://github.com/calpaterson/memoryfield-spec) format,
so they travel with the code in git and any memoryfield tool can read
them; a shared iirc repository can hold more (see Stores and auto
commit). Three parts: the `iirc` command, which wraps
[memoryfield-tool](https://github.com/calpaterson/memoryfield-tool) with
per-repository configuration, a guard on the embedding host, and a trust
model; seven hooks that put the matching page in front of the agent as it
works; and a skill that says when to search, when to write, and what to
do with a page found wrong.

With it enabled, the agent keeps its pages on its own. Every prompt you send
is searched, and when pages match, one line names them with the command to
read each; a shell command that fails is searched with its error text. The
agent writes a page when something took more than one attempt. A page
cites files at a commit, so when a cited file changes, search marks the
page suspect and the agent reads the diff, then verifies, rewrites, or
deletes it in the same turn.

Nothing in the pages needs your approval, and nothing you asked for goes
there. The pages are what the agent learned by itself; documents you review
stay in `docs/`.

## Why another memory system?

Claude Code's own memory lives in a directory under your home, outside the
repository. It is per machine and per user, git never carries it, and it
loads its index into every session. That is the right place for facts about
the machine and about you: which host this is, where the tools are
installed, how you like to be spoken to.

This plugin is for what the agent learns about the project: a quirk of a
tool, a procedure that worked, a finding about the domain, a decision and
its reason. That knowledge belongs with the code, in git, so it reaches
every clone and can be diffed, reviewed, and rolled back like anything
else in the repository. It is found by search rather than loaded whole, so
it stays cheap as it grows. And it cites files at a commit, which is what
lets a page be marked suspect when the thing it describes changes. Age
alone is only a hint.

| Belongs in | Examples |
|---|---|
| Claude Code's memory | this machine's hostname, local paths, your tone preference, a fact true only here |
| `.iirc/` (this plugin) | the tool that fails to install on macOS and the fix, the port a service listens on and why, the trust model you chose |
| `docs/` | anything you asked for or reviewed: designs, research, decisions with their reasoning |

A page may cite a document in `docs/`. A document never cites
a page.

## Status

Experimental. In daily use on two repositories since 2026-09-05. The page
format is fixed; the wrapper's commands and hooks may change between
pinned commits.

## Prerequisites

- Claude Code 2.1.195 or later, on macOS or Linux
- [uv](https://docs.astral.sh/uv/) on PATH
- [ollama](https://ollama.com) with the `nomic-embed-text` model, on this
  machine or on a host you can reach. Without it, a string-search fallback
  still works, and finds identifiers but not paraphrase.
- A git repository. The pages persist only if `.iirc/` is committed.

## Installation

Once per machine, in Claude Code:

```
/plugin marketplace add daftdoki/dokidlc-plugins
claude plugin install iirc@dokidlc
```

A repository that used the memory plugin needs one more step. At session
start the agent offers the migration, and on your yes it runs `iirc migrate`.
The migration moves `.memory/`, `.claude/memory.toml`, the CLAUDE.md section, the `memory@dokidlc` setting, and this machine's `dokidlc-memory` directories to their iirc names.
It stages the changes and prints a suggested commit. It never commits.

Then open a session in a repository and say "set up iirc". The agent
asks whether you want semantic search or the string fallback, and where
the embedding model runs. It then runs `iirc setup`, `iirc init`, and
`iirc doctor --fix`, which installs memoryfield-tool at the pinned
commit and, for a local model on macOS, ollama and the model. You commit
what it staged. [INSTALL.md](INSTALL.md) has every step as a command you
run yourself, for a bootstrap script or a container.

## Usage

Mostly you do nothing. Each session starts with one line:

```
iirc: 59 pages, semantic via 127.0.0.1:11434. Topics: claude-code 20, questlog 17, decisions 9, plugin 8. 3 suspect: diff-pass-with-old-value-grep-finds-the-missed-copy.md, ... (cited file changed).
```

Ask a question and the agent searches. "Do you remember anything about
installing this on a mac?" runs:

```
$ iirc search "why does install fail on a mac"
pysqlite3-install-override.md: Why memoryfield-tool needs a uv overrides file on macOS and arm64 Linux (distance 0.366; via semantic, install, mac)
project-settings-do-not-install-plugins.md: Since 2.1.195 settings only enable plugins; each machine runs claude plugin install once ... (distance 0.409; via semantic, install, fail, mac)
```

Each line says how the page was found. "Remember that the NAS keeps its
live firmware in /etc/default_config" makes the agent write a page with a
title, a one-line summary, topics, a kind, and a Sources section. "What in
iirc might be out of date?" runs `iirc doubt`. The full command list
is in `iirc --help`; the rules the agent follows are in
[skills/iirc/SKILL.md](skills/iirc/SKILL.md).

## Stores and auto commit

Every change the agent makes to the pages is committed at once. `write`,
`verify`, `delete`, and `index` each commit the store's directory and
nothing else, so your own staged and unstaged work stays out of the
commit. No commit is made during a merge or rebase, and the
session-start line counts anything left uncommitted.

By default the only store is `.iirc/` in the project. A remote store is
a separate git repository that several projects or machines share: the
plugin clones it under `~/.local/share/dokidlc-iirc/stores/` and pushes
after every commit. `.claude/iirc.toml` lists the stores:

```toml
write = "agent"          # the store `iirc write` uses without --store

[stores.project]
kind = "project"
path = ".iirc"

[stores.agent]
kind = "remote"
url = "git@github.com:you/agent-iirc.git"
```

Create the remote repository, then ask the agent to add it; it runs
`iirc stores add agent URL --default`, which writes that file, clones
the repository, and commits the config. Search reads every store, and
with two or more each result names its store, as in
`agent/ollama-host.md`. A page in a remote store records which project
wrote it; its refs and check run only in that project. When a push is
rejected, the plugin rebases once; `iirc sync` finishes the job when it
cannot. The plugin never pushes the project repository itself.

## Seeing what the hooks say

The hooks tell the agent things you do not see. A hooks module in the same
plugin draws them for you:

- Under your prompt, `+ [2] pages retrieved`. Click the `+` to list
  the pages, with a yellow diamond on a page iirc suspects is stale.
- Under a failed command, the pages its error recalled, in the same form.
- Under a command that failed and then worked, a row saying the agent was
  asked to write a page.
- Under the prompt, beside Claude Code's own hint, one line with the page
  count, how many pages this session has read, and the search mode:
  `● iirc: [73] pages · [3] read · [semantic+keyword] mode`. The circle is
  green when all is well, yellow when the session-start check has a
  warning such as a suspect page, and red when iirc needs setup or
  migration. The mode is `keyword` without an embedding host. A `write`,
  `delete`, or `sync` updates the page count, and a `read` or `pull`
  updates the read count. `/iirc status off` hides the line and
  `/iirc status on` brings it back; it is on by default, and the choice
  holds on that machine.
- Warnings from the session-start check, and the nudge at stop, come as
  toasts.

Both switches live in `.claude/iirc.toml`. A file that holds only these
keys keeps the default `.iirc/` store.

```toml
ui = false          # turn the drawn rows off (default: on)
show_hooks = true   # also print the raw text each hook gives the agent (default: off)
```

`show_hooks` is for debugging: it shows exactly what reached the model.

## Caveats

- The hooks fail open. A dead embedding host is skipped after a two-second
  probe, and a search that cannot run prints nothing.
- The semantic index lives in the machine's cache directory, not the
  repository. A fresh clone rebuilds it on first use.
- A check command that arrived with a clone runs only after the agent asks
  you and runs `iirc approve`. Until then `doubt` lists it and `verify`
  refuses the page.
- URLs in a page's refs are contacted only by `iirc doubt --network`,
  which asks you first.
- A remote store's clone sits on the agent's own machine. The guard
  refuses a raw read of its pages by pattern, which is a convention, not
  a boundary.
- The page count is information. Search stays cheap as the field
  grows; near-duplicate pages make it name the wrong one. `iirc doctor`
  names each pair of pages whose embeddings are 0.10 apart or closer, and
  the session-start line counts them. The same line says when its scan
  of cited files took more than 5 seconds; the scan costs about 19 ms
  per cited file, and the hook times out at 10 seconds.
- The plugin has to be installed once per machine. `.claude/settings.json`
  can enable it for every clone, but cannot install it.

## Configuration

Your setup choices live in `~/.config/dokidlc-iirc/config.toml`; say so
and the agent runs `iirc setup` again. An `OLLAMA_HOST` exported in the
shell turns semantic search on and overrides the host. To enable the
plugin for everyone who clones the repository, add the marketplace and
the plugin to `.claude/settings.json` by hand; [INSTALL.md](INSTALL.md)
shows the two keys.

## Other docs

- [INSTALL.md](INSTALL.md): every install step as a command, with the trap each one hides.
- [docs/how-it-works.md](docs/how-it-works.md): the hooks, the stores, the page format and its keys, and how search ranks.
- [skills/iirc/SKILL.md](skills/iirc/SKILL.md): the rules the agent follows for searching, writing, and doubt.
- [skills/iirc/evals/](skills/iirc/evals/): the harness that measured the skill, and the numbers.
- [docs/review-pass-recommendations.md](docs/review-pass-recommendations.md): a review of two fields after two weeks of use, with recommendations.
- [DEVELOPMENT.md](DEVELOPMENT.md): working on the plugin itself.

## Support

File a bug or ask a question in
[GitHub issues](https://github.com/daftdoki/dokidlc-skill-iirc/issues).

## Built on memoryfields

The idea, the page format, and the search engine are Cal Paterson's: the
[article](https://calpaterson.com/memoryfields.html), the [format
specification](https://github.com/calpaterson/memoryfield-spec) (MIT),
[memoryfield-tool](https://github.com/calpaterson/memoryfield-tool)
(AGPL-3.0-or-later), and [his skill for
agents](https://github.com/calpaterson/memoryfield-skill) (MIT). The tool
is installed as published at the commit in `iirc.pin`; nothing from it is
copied here.

## License

MIT, DaftDoki. See [LICENSE](LICENSE).
