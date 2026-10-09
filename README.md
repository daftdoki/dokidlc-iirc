# iirc

A Claude Code plugin that keeps what your agent learns in the repository, searchable by meaning.

The name is "if I recall correctly". It installs as `iirc@dokidlc`; the
repository is `dokidlc-skill-iirc`, prefixed for the dokidlc marketplace.
Pages are markdown files in `.iirc/` in the
[memoryfield](https://github.com/calpaterson/memoryfield-spec) format, so
they travel with the code in git and any memoryfield tool can read them; a
shared iirc repository can hold more. Four parts work together:

- The `iirc` command wraps
  [memoryfield-tool](https://github.com/calpaterson/memoryfield-tool) with
  per-repository configuration, a guard on the embedding host, and a trust
  model.
- Hooks search the pages on every prompt and every failed shell command,
  and name the matches to the agent with how well each matched.
- A skill tells the agent when to search, when to write, and what to do
  with a page found wrong.
- A hooks module draws what the hooks told the agent, so you see it too.

The agent keeps its pages on its own. It writes one when something took
more than one attempt. A page cites files at a commit, so when a cited file
changes, search marks the page suspect and the agent reads the diff, then
verifies, rewrites, or deletes it in the same turn.

Nothing in the pages needs your approval, and nothing you asked for goes
there. The pages are what the agent learned by itself; documents you review
stay in `docs/`.

![A prompt with three suggested pages listed under it, each with its match score, and the iirc line under the prompt with its page, used, read, and write counts](docs/images/iirc-ui.png)

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
format is fixed; the wrapper's commands, hooks, and drawn rows may change
between pinned commits.

## Prerequisites

- Claude Code 2.1.195 or later, on macOS or Linux. The drawn rows are
  tested on 2.1.295.
- [uv](https://docs.astral.sh/uv/) on PATH
- [ollama](https://ollama.com) with the `nomic-embed-text` model, on this
  machine or on a host you can reach. Without it, a string-search fallback
  still works, and finds identifiers but not paraphrase.
- A git repository. The pages persist only if `.iirc/` is committed.

## Installation

Once per machine, in Claude Code:

```
/plugin marketplace add daftdoki/dokidlc-plugins
/plugin install iirc@dokidlc
```

Then open a session in a repository and say "set up iirc". The agent
asks whether you want semantic search or the string fallback, and where
the embedding model runs. It then runs `iirc setup`, `iirc init`, and
`iirc doctor --fix`, which installs memoryfield-tool at the pinned
commit and, for a local model on macOS, ollama and the model. You commit
what it staged. [INSTALL.md](INSTALL.md) has every step as a command you
run yourself, for a bootstrap script or a container.

A repository that used the memory plugin needs one more step. At session
start the agent offers the migration, and on your yes it runs
`iirc migrate`. That moves `.memory/`, `.claude/memory.toml`, the CLAUDE.md
section, the `memory@dokidlc` setting, and this machine's `dokidlc-memory`
directories to their iirc names. It stages the changes and prints a
suggested commit; it never commits.

## Usage

Mostly you do nothing. Each session starts with one line for the agent:

```
iirc: 76 pages, semantic via 127.0.0.1:11434. Topics: claude-code 26, questlog 20, decisions 16, plugin 16.
```

Send a prompt and, when pages match, a row appears under it. Click it to
list the pages:

```
[+] iirc: [3] pages suggested
● iirc: [76] pages · [2/5] used · [12] reads · [4] writes
```

The second line sits under the prompt for the whole session. Its circle is
green when all is well; yellow or red, it ends with the command that
fixes it, such as `· run iirc doubt`.
A plain `/iirc` draws a card with the status, the counts, the hit rate,
and the settings.
[docs/ui.md](docs/ui.md) explains every part.

Ask a question and the agent searches. "Do you remember anything about
installing this on a mac?" runs:

```
$ iirc search "why does install fail on a mac"
pysqlite3-install-override.md: Why memoryfield-tool needs a uv overrides file on macOS and arm64 Linux (distance 0.366; via semantic, install, mac)
```

"Remember that the NAS keeps its live firmware in /etc/default_config"
makes the agent write a page with a title, a one-line summary, topics, a
kind, and a Sources section. "What in iirc might be out of date?" runs
`iirc doubt`. The full command list is in `iirc --help`; the rules the
agent follows are in [skills/iirc/SKILL.md](skills/iirc/SKILL.md).

## Caveats

- The hooks fail open. A dead embedding host is skipped after a two-second
  probe, and a search that cannot run prints nothing.
- Every change the agent makes to the pages is committed at once, the
  store's directory and nothing else, so your own staged work stays out.
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
- Two pages that read as duplicates make search name the wrong one.
  `iirc doctor` names each pair; merge them, or link one to the other with
  `[[name]]` when they hold different kinds of finding.
- The plugin has to be installed once per machine. `.claude/settings.json`
  can enable it for every clone, but cannot install it.

## Configuration

| Setting | Where | Changed by |
|---|---|---|
| search mode and embedding host | `~/.config/dokidlc-iirc/config.toml` | asking the agent to run `iirc setup` again |
| pages suggested per prompt, 3 by default | the same file, `max_suggested` | `/iirc max-suggested N` |
| the line under the prompt | the plugin's store, per machine | `/iirc status on` or `off` |
| the drawn rows; the raw hook text | `.claude/iirc.toml`, `ui` and `show_hooks` | editing the file |
| the stores | `.claude/iirc.toml` | `iirc stores add`, see [how-it-works.md](docs/how-it-works.md#adding-a-remote-store) |

An `OLLAMA_HOST` exported in the shell turns semantic search on and
overrides the host. To enable the plugin for everyone who clones the
repository, add the marketplace and the plugin to `.claude/settings.json`
by hand; [INSTALL.md](INSTALL.md) shows the two keys.

## Other docs

- [INSTALL.md](INSTALL.md): every install step as a command, with the trap each one hides.
- [docs/ui.md](docs/ui.md): what the plugin draws under your prompt and commands, and every part of the line under the prompt.
- [docs/how-it-works.md](docs/how-it-works.md): the hooks, the stores and how to add a remote one, the page format and its keys, and how search ranks.
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
