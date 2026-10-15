# Using iirc

This page has how-to guides for the tasks you meet with iirc, then
reference for every `/iirc` command and every setting, in the split
[Diátaxis](https://diataxis.fr/) makes. Why iirc works the way it does
is in [HOW-IT-WORKS.md](HOW-IT-WORKS.md). You never have to run an
`iirc` command yourself. You ask in words, and the agent runs it. Where
a `/iirc` command does the same job, this page names it.

## Day to day

Mostly you do nothing. Run `/iirc run-maintenance` about once a week
while you use iirc; iirc tells you when it is due. It is the only upkeep
command you need ([Run maintenance](#run-maintenance)).

The suggestion hook names matching pages under your prompt,
and a line above the prompt sums up the session; [UI.md](UI.md)
describes the row, the line, and the cards. The row shows you the list
the agent got. When the circle on the line turns yellow or red, the line
ends with the command that clears it, such as `· run /iirc run-maintenance`
or `· run iirc doctor --fix`; ask the agent to run it, or type it after
`/iirc`. For anything else, ask in
words: "what do we know about ollama hangs?", "remember that...",
"what's out of date?". To read a page yourself, click its name, run
`/iirc reader PAGE` to open it in the reader, or `/iirc show PAGE` for a
card in the transcript; your reads do not count as the agent's.

## Tasks

### Run maintenance

Run it about once a week while you use iirc; iirc tells you when it is
due. Type `/iirc run-maintenance`, or say yes when the agent suggests
it. It is due after 7 days and at least 5 sessions since the last run
once the stores hold a page,
or sooner when a page is suspect, a store commit is not pushed, a
suggestion lookup timed out in the last 7 days and since the last run
whose embedding host checks passed,
or two pages are near-duplicates. When 10 sessions wait to be judged,
the run offers tuning, but they do not make it due. The
session-start line then says `Maintenance is due (REASONS)`, the line
under the prompt says `▲ /iirc run-maintenance · REASON`, with `+N more` for the other reasons, and
`iirc doctor` ends with `run-maintenance is due: REASONS`.

The agent runs `iirc run-maintenance`. It commits each store's loose
files under the store's path, so the run starts from a commit, and
prints that starting commit for each store with the command that undoes
the run. It then syncs the remote stores, checks the setup, embeds pages
with no vectors, and lists what is left: setup failures, checks not
approved on this machine, suspect pages, near-duplicate pairs, audit
findings, a URL-ref check when none ran in 30 days, and sessions waiting
to be judged. It changes no page's text. The agent walks you through
each item, and each change is a commit of its own, made on your yes.
The summary repeats the undo command.

`/iirc run-maintenance --unattended`, yolo mode, asks one yes at the
start, then fixes the setup, settles suspect pages, near-duplicates, and
audit findings, and runs a tuning pass when 10 sessions wait, all by the
agent's own judgement. It never approves a check command or contacts a
URL; the summary names those steps and the commands to run them later.

### Set up a machine

Install the plugin once per machine ([README](../README.md)). Then open
a session in a repository and say "set up iirc". The agent asks two
things: which embedding model this repository uses, and where it runs
on this machine.

| Where it runs | `iirc add-embedding-model MODEL HOST` | Needs |
|---|---|---|
| ollama on this machine | `local` | ollama here; doctor installs it on macOS |
| ollama on another host | the host's URL | ollama there, with the model pulled |
| an OpenAI-compatible host, such as vLLM serving qwen3-embedding | the base URL | a server that answers `POST URL/v1/embeddings` |
| this CPU, all-MiniLM-L6-v2 through onnxruntime | `cpu` | about 90 MB of model files, which the command fetches; no ollama |

The models are `qwen3-embedding-0.6b`, `nomic-embed-text`, and
`all-minilm-l6-v2`. A model has one name whatever
serves it: qwen3 0.6B is `qwen3-embedding:0.6b-fp16` or
`qwen3-embedding:0.6b` to ollama and `qwen3-embedding` to an
OpenAI-compatible server, and one repository can use it through ollama
on one machine and a server on another, with one threshold table. The
agent recommends qwen3 through ollama, and the CPU model where ollama
cannot run. `add-embedding-model` asks the host which protocol it
speaks and which build it has, and refuses a host without the model; it
never pulls one. It also compares the host's vector for a probe sentence
with the plugin's reference: under 0.995 cosine it warns that the host
serves another build, and another width it refuses.

The agent then runs `iirc set-embedding-model MODEL`, which writes
`embedding_model` to `.claude/iirc.toml` (commit it), `iirc init` if you
want pages in this repository, then `iirc doctor --fix`, which installs
memoryfield-tool and, for this machine's ollama on macOS, ollama and the
model. You see doctor's report. String search, the fallback where no
model can run, is `iirc search-mode string`. [INSTALL.md](../INSTALL.md)
has every step as a command.

The model is the repository's and the same on every machine. Where it
runs is the machine's: its list of models and hosts in
`~/.config/dokidlc-iirc/config.toml`. A repository that names no model
gets the first model on the machine's list, written to its
`.claude/iirc.toml` by the first command that needs a model. When two
listed hosts serve the model, a command on a terminal asks once which
this machine uses; `iirc prefer-embedding-host MODEL HOST` changes it.
When no listed host serves it, the session-start line says "this machine
cannot serve MODEL", search matches strings, and the agent offers four
ways out: add a host that serves it, pull it on an ollama host, switch
the repository to a model a listed host serves, or switch to the CPU
model. A switch embeds every page again, starts the thresholds at the
new model's defaults, and stops counting tuning judgments made under the
old model.

A machine set up before this list has `semantic`, `embedding`, or
`embedding_host` in its setup file; `iirc doctor` reports them, and
`iirc doctor --fix` converts them once, with a repository's
`embedding_model` that names a protocol's name such as
`qwen3-embedding:0.6b`.

### Start iirc in a repository

Say "start iirc in this repository". The agent asks, then runs
`iirc init`. It creates `.iirc/index.md`, adds the `## IIRC` section to
`CLAUDE.md`, and stages both. Commit them, together with the
`.claude/settings.json` that enables the plugin for each clone
([INSTALL.md](../INSTALL.md), steps 7 and 8). The pages persist only
when `.iirc/` is committed.

### Migrate from the memory plugin

When a repository or machine still has the memory plugin's layout, the
session-start line says so, and the line under the prompt says, in red,
`✖ iirc migrate`. Say "yes, migrate". The agent runs
`iirc migrate`, which moves the store directory, the config, the
`CLAUDE.md` section, the plugin setting, and this machine's directories
to their iirc names. It stages the changes and prints a suggested
commit. It never commits; the agent shows you the output and commits on
your word. The old memory plugin stays installed but turned off; once a
restart shows iirc running, `claude plugin uninstall memory@dokidlc
--scope project` removes it, and the migrate output names that command.

### Ask what iirc knows

Ask: "Do you remember anything about installing this on a mac?" The
agent runs `iirc search` with your question, reads the pages that fit,
and answers from them. To look yourself, type `/iirc search QUERY`,
`/iirc read PAGE`, or `/iirc show-page-topics`. A page you read this way does not
count toward the session's reads, which are the agent's.

### Tell it to remember

Say: "Remember that the NAS keeps its live firmware in
/etc/default_config." The agent searches first. If a page already holds
the fact, it runs `iirc verify` on that page and tells you. If not, it
writes a page with a title, a one-line summary, topics, a kind, and a
Sources section, and `iirc write` commits the store's directory. It
also writes at [the skill's moments](../skills/iirc/SKILL.md#when-to-write).

### Find and fix what may be out of date

Ask: "What in iirc might be out of date?" The agent runs `iirc find-suspect-pages`.
It lists the pages with evidence against them, strongest first. A page
is suspect when a file it cites changed since it cited it, or when its
check command now fails. A check that contacts the network, such as
`curl` or `gh api`, does not run here; the page gets a glance note that
says it runs with `--network`. For each one, the agent reads the page and
the diff, then verifies, rewrites, or deletes the page in the same turn.
`/iirc find-suspect-pages` prints the same list, and `/iirc find-suspect-pages --all` adds the
clean pages. Ask for a doubt pass after a `git pull`. `/iirc run-maintenance`
lists suspect pages too, and the line under the prompt names it when a page turns suspect.

Two cases need your yes. A check command that arrived with a clone is
not approved on this machine, so `find-suspect-pages` lists it and does not run it.
The agent shows you the command and asks; on yes it runs
`iirc approve-page-check PAGE`, and Claude Code asks you to approve the command too.
`find-suspect-pages` never contacts the URLs in a page's refs or runs a check that
contacts the network. To run them, the agent names the URLs and checks
`iirc find-suspect-pages --network` will contact and asks. `iirc verify PAGE --network`
runs one such check under the same rule. Each
command refuses unless a terminal answers yes or `IIRC_ALLOW_NETWORK=1`
is set, and only you set it.

### Merge near-duplicates

When two pages sit at the model's duplicate distance or closer, the
session-start line counts the pair among the reasons maintenance is due,
and the circle turns yellow with `· run /iirc run-maintenance`.
`/iirc run-maintenance` and `/iirc doctor` name each pair. Doctor also notes
similar pairs up to the model's near-duplicate distance:

| Model | Duplicate: the line turns yellow | Near-duplicate: doctor notes it |
|---|---|---|
| `nomic-embed-text` | 0.07 | 0.10 |
| `qwen3-embedding-0.6b` | 0.12 | 0.17 |
| `all-minilm-l6-v2` | 0.14 | 0.20 |

Say "merge the near-duplicate pages". When a
pair holds one finding, the agent merges the two into one page and
deletes the other. When the two hold different kinds of finding, such as
a decision and the procedure that carries it out, it links one to the
other with `[[name]]`, and the pair stops counting.

### Share pages across repositories with a remote store

A remote store is a separate git repository that several projects and
machines name. Create an empty repository, then say "add the shared
store at URL as the default". The agent runs
`iirc add-remote-store NAME URL --default`. That writes `.claude/iirc.toml`
with the project store and the new one, clones the repository, and
commits the config. The agent then writes facts that hold in any
project to the remote store; each write commits and pushes, and each
session start pulls. When the line says `not pushed`, type `/iirc sync`.
On another machine, `iirc doctor --fix` clones a missing remote store.

### Work without ollama

Say "search on this CPU". The agent runs
`iirc add-embedding-model all-minilm-l6-v2 cpu`, which fetches
all-MiniLM-L6-v2 and runs it once, so onnxruntime installs then and not
in a hook, and then `iirc set-embedding-model all-minilm-l6-v2`. Search
still matches meaning. If onnxruntime has no wheel for this machine, the
command says so and writes nothing.

Say "use string search" when nothing else can run. The agent runs
`iirc search-mode string`. Search then matches exact text only, and the
agent searches for the words a page contains
([references/search.md](../skills/iirc/references/search.md)). The suggestion hook
names a page only on a shared identifier, and the line above the prompt
shows `string search`. To go back, ask for `iirc search-mode semantic`. If ollama is only down for a while, change nothing: iirc skips a
host that does not answer a two-second probe and searches by string
until it answers.

### Audit the pages

Say "audit the pages", or type `/iirc audit-page-findability`. The agent runs
`iirc audit-page-findability`, which prints one line per page that search shows badly,
with its fix: a title over 70 characters, a summary that starts with a
date or shares no word with the title, a secret, a page that a search
for its own title does not rank first, a page that tune judged noise
far more often than relevant, and a page that names its successor but
keeps its old text. `iirc audit-page-findability PAGE` checks one page, and `--json`
prints the findings as JSON. The audit changes nothing; the agent
proposes each fix for your yes. `/iirc tune-suggestions` runs it before it judges any session.

### See exactly what the hooks told the agent

Say "turn on show_hooks". The agent adds `show_hooks = true` at the top
of `.claude/iirc.toml` and commits it. From the next hook on, each hook
also shows its raw text to you as a system message. The file is
committed, so ask for the line to be removed when you are done.

### Turn the drawn UI or the summary line off

`/iirc summary-line-visibility off` hides the summary line above the prompt on this machine,
and `/iirc summary-line-visibility on` brings it back. To draw nothing at all, ask
the agent to add `ui = false` to `.claude/iirc.toml`. That removes the
rows, the line, and the toasts for everyone who clones the repository.
The hooks still give the agent its lines, and every command still works.

## The /iirc commands

The `command.run` handler in
[`hooks/register.tsx`](../hooks/register.tsx) answers these forms.

| Command | What you see |
|---|---|
| `/iirc` | The short card: ask in words, pointers to help and status, this session's suggestion hit rate and average match, and the page count. |
| `/iirc status` | Every number: the status chip, TRUST (suspect pages), each store's uncommitted and unpushed state, the session counts, the hit rate, and SUGGESTED, NOT READ. It runs `iirc doctor --health` first. |
| `/iirc help` | The three settings with their current values, then the maintenance and look-up commands. |
| `/iirc demo`, `/iirc demo status` | The short card or the status card with sample numbers. |
| `/iirc demo doctor` | The doctor card from sample checks; it does not run doctor. |
| `/iirc summary-line-visibility` | Whether the summary line above the prompt is on or off. |
| `/iirc summary-line-visibility on`, `/iirc summary-line-visibility off` | Shows or hides that line, on this machine. |
| `/iirc max-suggested-pages` | How many pages a suggestion line names at most. |
| `/iirc max-suggested-pages N` | Sets that number, 1 to 10, on this machine. |
| `/iirc run-maintenance`, `/iirc run-maintenance --unattended` | Goes to the skill: the only upkeep command, about once a week. See [Run maintenance](#run-maintenance). |
| `/iirc doctor`, `/iirc doctor --fix` | The setup checks as a card; `--fix` installs or repairs what fails, then rebuilds the index. |
| `/iirc find-suspect-pages`, `/iirc find-suspect-pages --all` | Pages with evidence they may be wrong; `--all` lists clean pages too. |
| `/iirc sync` | Commits, pulls, and pushes every remote store. |
| `/iirc show-page-stores` | The stores, their page counts, and anything not committed or pushed. |
| `/iirc summarize-page-usage`, `/iirc summarize-page-usage --days N` | Suggestion and page use over the last 7 days, or N days. |
| `/iirc rebuild-search-index` | Rebuilds the search index. |
| `/iirc estimate-context-tokens` | Bytes and tokens of `index.md` and of a sample search. |
| `/iirc show-suggestion-thresholds` | The suggestion distances in force for the active model, from `[suggestions.MODEL-ID]`, and their ranges. |
| `/iirc show-page-topics` | Every topic with its page count. |
| `/iirc search QUERY` | Ranked pages for the query; all the words form one query. |
| `/iirc read PAGE` | One or more pages, with their trust markers. |
| `/iirc unfold-suggested-pages` | Unfolds the latest suggested-pages row, as a click on its `[+]` does. |
| `/iirc reader`, `/iirc reader PAGE` | The reader, a pane with this session's suggested, written, and suspect pages, or open on one page. A click on a page name, here or anywhere iirc draws one, opens the page in the reader's page tab. See [UI.md](UI.md#the-reader). |
| `/iirc show PAGE` | One page as a card in the transcript; your read, not the agent's. |
| `/iirc audit-page-findability` | Goes to the skill: the agent lists the pages search shows badly and proposes each fix for your yes. See [Audit the pages](#audit-the-pages). |
| `/iirc set-embedding-model` | Goes to the skill: the agent asks which embedding model and where it runs, then runs `iirc add-embedding-model` and `iirc set-embedding-model`. |
| `/iirc show-embedding-models`, `/iirc search-mode` | This machine's list of models and hosts, and its search mode. |
| `/iirc tune-suggestions` | Goes to the skill: the agent runs `audit-page-findability` and proposes each page fix, judges the recorded sessions, evaluates the thresholds, and proposes page fixes and threshold changes, each for your yes. See [Tune the thresholds on evidence](#tune-the-thresholds-on-evidence). |

The direct commands print what the `iirc` command prints. `doctor --fix`,
`sync`, and `rebuild-search-index` may run for up to ten minutes; the rest stop after
one minute. Anything else after `/iirc` goes to the skill as a request in
words. That includes the commands that need a question first:
`add-remote-store`, `set-embedding-model`, `add-embedding-model`, `remove-embedding-model`, `prefer-embedding-host`, `search-mode semantic|string`, `init`, `write`, `delete`, `approve-page-check`,
`set-suggestion-threshold`, `find-suspect-pages --network`, and `verify --network`.

### The agent's commands

These have no `/iirc` form of their own; ask in words. `iirc --help`
describes each one.

| Command | What it does |
|---|---|
| `iirc run-maintenance` | Commits each store's loose files, syncs the remote stores, embeds pages with no vectors, then lists setup failures, suspect pages, unapproved checks, near-duplicate pairs, audit findings, and sessions waiting to be judged. It changes no page's text, logs a `maintenance` row, and prints how to undo the run. |
| `iirc read-matching-pages QUERY` | Searches, then prints the full text of each matching page, as `read` does. |
| `iirc write`, `iirc verify`, `iirc delete`, `iirc approve-page-check` | Write, confirm, remove, or approve the check of a page. |
| `iirc audit-page-findability [PAGE] [--json]` | Pages that search shows badly; see [Audit the pages](#audit-the-pages). |
| `iirc init`, `iirc migrate`, `iirc max-suggested-pages N` | The repository's `.iirc/`, the move from the memory plugin, and the pages per line. |
| `iirc set-embedding-model MODEL` | Writes `embedding_model` to this repository's `.claude/iirc.toml`, for every machine. It says what a switch costs: every page is embedded again, the thresholds start at the new model's defaults, and tuning judgments made under the old model stop counting. |
| `iirc show-embedding-models` | This machine's list of embedding models and where each runs, each with the build ollama reports and its fingerprint cosine against the reference, and the entry that serves this repository marked. |
| `iirc add-embedding-model MODEL HOST` | Adds a model and where it runs to this machine's list. HOST is a URL, `local` for ollama here, or `cpu` for `all-minilm-l6-v2` on this CPU. It asks the host whether it speaks ollama or the OpenAI-compatible API and which build it has, and refuses a host without the model. It never pulls a model. |
| `iirc remove-embedding-model MODEL [HOST]` | Removes the model from this machine's list, on one host or on all. |
| `iirc prefer-embedding-host MODEL HOST` | When two listed hosts serve a model, records which one this machine uses. |
| `iirc search-mode [semantic\|string]` | This machine's search mode. Bare, it prints it; `string` is the fallback where no embedding model can run. |
| `iirc tune-suggestions gather-suggestion-data`, `record-relevance-judgments`, `evaluate-suggestion-thresholds`, `mark-session-tuned` | The tune steps. `iirc tune-suggestions evaluate-suggestion-thresholds --replay-prompts FILE...` replays judged prompts through today's search and gate. |
| `iirc suggest-pages`, `iirc record-command-success`, `iirc remind-to-write`, `iirc record-session-summary` | Hook entries: `suggest-pages` names pages for a prompt or a failed command; `record-command-success` logs a command that worked and asks for a page when it had failed twice before; `remind-to-write --at stop` asks for a page at the end of a turn; `record-session-summary --hook` logs the session's numbers before compaction and at its end. |
| `iirc summarize-session-usage [ID]`, `iirc show-compaction-instructions` | Run by the hooks module: one session's pages and searches as JSON for the line above the prompt, and the line compaction's summary keeps. The module also runs `remind-to-write --at compaction` near compaction. |

## Every setting

| Setting | Where it lives | Default | Range or values | What it changes | When to turn it |
|---|---|---|---|---|---|
| `search_mode` | `~/.config/dokidlc-iirc/config.toml`, this machine | `"semantic"` | `"semantic"`, `"string"` | Semantic and string search, or string search only. | `iirc search-mode string` where no embedding model can run. |
| `embedding_models` | the same file | none | entries of `model`, `host` (a URL, or `cpu`), `protocol` (`ollama`, `openai`, `onnx`), and `name`, the build's name | The models this machine can run and where each runs. | `iirc add-embedding-model` and `iirc remove-embedding-model` write it. |
| `embedding_preferred` | the same file | none | a model and one of its listed hosts | Which host serves a model when two listed hosts do. | `iirc prefer-embedding-host MODEL HOST`. |
| `embedding_model` | `.claude/iirc.toml`, committed, so every clone | none, which means the first model on the machine's list, written by the first command that needs a model | a model in [Suggestion thresholds per model](#suggestion-thresholds-per-model); another name is a configuration error | Which model embeds this repository's pages and queries, on every machine. | `iirc set-embedding-model MODEL`. |
| `max_suggested` | the same file | `3` | 1 to 10 | Pages one suggestion line names at most. The line's byte cap is 120 + 200 times N. | `/iirc max-suggested-pages N`, when the row brings too much or too little. |
| `[suggestions.MODEL-ID] semantic_only` | `.claude/iirc.toml`, committed, so every clone | per model, below | per model, below | The largest cosine distance for a page with no strong term (rule `meaning`). | Only on evidence from the records; `/iirc tune-suggestions` proposes a value, and the agent sets it with `iirc set-suggestion-threshold` on your yes. |
| `[suggestions.MODEL-ID] both` | `.claude/iirc.toml` | per model, below | per model, and at least `semantic_only` | The largest distance for a page backed by a strong term (rule `meaning+term`). | The same as `semantic_only`. |
| `ui` | `.claude/iirc.toml` | `true` | `true`, `false` | `false` draws no rows, no lines at the prompt, and no toasts. | When nobody who clones the repository wants the drawn UI. |
| `show_hooks` | `.claude/iirc.toml` | `false` | `true`, `false` | `true` shows each hook's raw text to the person as well. | While you debug what reached the agent. |
| `write` | `.claude/iirc.toml` | the project store, else the only store | the name of a store | The store `iirc write` uses without `--store`. | `iirc add-remote-store NAME URL --default` sets it. |
| `[stores.NAME] kind` | `.claude/iirc.toml` | required in each store table | `project` (at most one), `remote` | A directory in the repository, or a clone of a shared repository. | When you add a store. |
| `[stores.NAME] path` | `.claude/iirc.toml`, project store only | `.iirc` | a directory inside the repository, not a symlink | Where the project store lives. Outside `.iirc/`, the read guard does not cover it. | Rarely. |
| `[stores.NAME] url` | `.claude/iirc.toml`, remote store only | required | a git URL | The clone source. The clone is `~/.local/share/dokidlc-iirc/stores/NAME-HASH`. | When you add a store. |
| the summary line above the prompt | the hooks module's store, this machine | on | on, off | Shows or hides that line. | `/iirc summary-line-visibility on` or `off`. |
| `IIRC_ALLOW_NETWORK` | the environment | unset | `1` | Lets `iirc find-suspect-pages --network`, `iirc verify --network`, and `iirc approve-page-check` on a network check run with no terminal to answer yes. | Only when you want URL refs or network checks run from a session. |
| `XDG_CONFIG_HOME`, `XDG_CACHE_HOME`, `XDG_DATA_HOME`, `XDG_STATE_HOME` | the environment | `~/.config`, `~/.cache`, `~/.local/share`, `~/.local/state` | paths | Where the machine config, the index, the remote clones, and the records live. | When your machine moves them. |

Store tables, in `.claude/iirc.toml`, replace the implicit project store.
With no `[stores.NAME]` table and no `write` key, iirc uses one project
store at `.iirc/`, so a file that holds only `ui` or `show_hooks` changes
nothing else. Names are lowercase letters and digits joined by single
hyphens, at most 31 characters. Unknown top-level keys are ignored.
Some values are fixed in the code: the suggestion hook skips a prompt shorter than 40
characters, a page is at most 8192 bytes, a term in more than a tenth of
the pages is common, a search embeds at most 5 changed pages, and
records are kept 90 days.

### Suggestion thresholds per model

Each model has its own distance scale, so each has its own table in
`.claude/iirc.toml`, named after the model. Every build of a model reads
the same table, whatever serves it. The hooks read the table of the
repository's model (`embedding_model`); a threshold left out takes its
default. `iirc show-suggestion-thresholds` prints the table name and the values in force.

```toml
[suggestions.nomic-embed-text]
semantic_only = 0.28
both = 0.38

[suggestions."qwen3-embedding-0.6b"]   # quoted, because the name holds a dot
both = 0.62
```

| Model (`[suggestions.MODEL-ID]`) | `semantic_only` | `both` | Range | Cut: never farther |
|---|---|---|---|---|
| `nomic-embed-text` | 0.28 | 0.38 | 0.10 to 0.60 | 0.45 |
| `qwen3-embedding-0.6b` | 0.40 | 0.60 | 0.10 to 0.90 | 0.90 |
| `all-minilm-l6-v2` | 0.60 | 0.68 | 0.10 to 0.90 | 0.90 |

The defaults come from a replay of judged prompts
([SEARCH-QUALITY.md](SEARCH-QUALITY.md#results)). qwen3's values were
measured on its ollama build and hold for its OpenAI-compatible build,
whose vectors measured at 0.9993 cosine or closer.

### How a bad value fails

A bad `.claude/iirc.toml`, such as a threshold out of range, a
`[recall]` table under the thresholds' old name, or a store table with no
`kind`, turns the hooks off. The session-start line
reads "iirc: hooks off", then the error and the command that fixes it,
and the line under the prompt says, in red, `✖ iirc doctor --fix · hooks off, <the error>`. Every other
hook stays quiet until the file is fixed. `iirc doctor` fails the check
".claude/iirc.toml loads, so the hooks run" and names the line to
change. `iirc doctor --fix` renames each `[recall.MODEL-ID]` table to
`[suggestions.MODEL-ID]`, moves flat `[recall]` keys into
`[suggestions.nomic-embed-text]`, the only model there was then, and comments out
each bad threshold, with a note, so its default applies; a broken store table
is yours to fix.
Every other command except `doctor`, the six embedding model and search mode commands, `summarize-page-usage`,
`record-session-summary`, `summarize-session-usage`, and `max-suggested-pages` stops
with the error.

A bad `~/.config/dokidlc-iirc/config.toml` is ignored, and nothing says
so. A file that does not parse reads as empty, and a `max_suggested`
outside 1 to 10 reads as the default, 3. `iirc max-suggested-pages 11` itself
refuses with "max-suggested-pages must be 1 to 10".

## Getting good results over time

### Write pages that the suggestion hook can find

Three rules of the suggestion gate decide what a page should contain. They
are in `gate` in [`bin/iirc`](../bin/iirc).

- A page found only by text needs an identifier from the prompt: a word
  with a digit, dot, hyphen, or underscore, such as `2.1.290`,
  `nomic-embed-text`, or `session.append`. A plain word never passes
  alone.
- A term counts only when it is rare. A term in more than a tenth of the
  pages, and in more than two, counts for nothing. Term matching leaves
  out the Sources section and `[[links]]`.
- A page that semantic search finds within `both` also needs a strong
  term: a rare identifier anywhere in the page, or a rare word of five
  letters or more in the page's file name, title, or summary that is not
  one of the 1,000 most common English words.

So put the tool name, the version, the error code, or the path in the
summary. Every model embeds the whole page: nomic and qwen3 the
page file up to 8192 bytes, frontmatter and body; MiniLM the title,
summary, topics, and body in windows. A page about two things therefore
matches prompts about either. Keep one finding per page. `iirc write`
warns on a title over 70 characters, a summary that starts with a date
or "Creator decision", and a summary whose first 90 characters share no
word with the title, and refuses a page with a secret in it. The writing
rules and the four kinds are in
[the skill](../skills/iirc/SKILL.md#when-to-write); the agent follows
them.

### Read the stats and act on them

Plugin commits `699d710`, `a16668a`, and `fa1ed37` record what the
suggestion hook does. The
cards and `/iirc summarize-page-usage` show it. Each number has a response:

- TRUST is not zero on `/iirc status`: type `/iirc find-suspect-pages`, or ask the
  agent to find suspect pages.
- A page under SUGGESTED, NOT READ keeps coming back: ask the agent to
  read the page once and decide whether to narrow it, split it, or delete
  it. Narrow the page, not only the summary, because the index embeds the
  whole page.
- The suggestion hit rate on the cards is this session's suggested pages
  that were then read. It is a proxy for precision. One session holds
  too few suggestions to judge; watch it over several sessions, or read
  "read after a search or a suggestion line named it" in `/iirc summarize-page-usage`.
- The average match for read and unread pages: when the two are close,
  the score does not predict which pages get used. Do not move the
  thresholds on that alone.
- Pages read that the hook never suggested may be its misses. Ask
  the agent for `read_unsuggested` in the session's last row of
  `log.jsonl`, and check that each page carries the identifiers a prompt
  about it would use.
- Near-duplicate pairs: merge or link them, as in
  [Merge near-duplicates](#merge-near-duplicates).
- "[N] timed out" in yellow on the line: Claude Code killed `iirc suggest-pages` at
  the hook's 5 s limit. The session-start line counts the last 7 days'
  timeouts, and `iirc doctor` names the usual cause, a cold embedding
  model. iirc asks ollama to keep the model loaded for 24 hours, so the
  likely causes are no search or index in over 24 hours, another model
  loaded in its place, or a host that restarted. On a remote host, iirc's
  request overrides the operator's own keep-alive setting for iirc's model.

### Tune the thresholds on evidence

`/iirc max-suggested-pages N` gives more or fewer pages per prompt. The line's
byte cap grows with N, so each extra page allows up to 200 more bytes of
context. Change the thresholds only on evidence from the recorded
sessions.

Say "tune the suggestions", or run `/iirc tune-suggestions`. The agent follows
[the tune reference](../skills/iirc/references/tune.md): it gathers the
recorded sessions, then runs `iirc audit-page-findability`. For each flagged page it
writes two prompts of its own, checks where the page ranks, and proposes a
fix; it audits each fixed page again. Thresholds tuned while a page is
badly written bend to make up for it, so the audit comes first. The agent then
judges each suggestion against what the session needed and evaluates the
thresholds over those judgements. You see each proposal with its
evidence: a page to narrow, split, or write, or a threshold value with
the counts before and after. Nothing changes until you say yes. A
threshold change edits the active model's table in
`.claude/iirc.toml`, which you commit. The evaluation reads only
suggestions the active model made: each candidate row records its
model, and a row from another model, or from before rows recorded one,
is on another distance scale.

To measure a change to search or the gate before it lands, the agent
runs `iirc tune-suggestions evaluate-suggestion-thresholds --replay-prompts FILE...` on replay files of judged
prompts. It searches each prompt again with the current code and prints
the same counts. [HOW-IT-WORKS.md](HOW-IT-WORKS.md#the-replays) has the
file format and the session replay. Expect
the first threshold proposal only after a few sessions: the evaluation needs 30
judged pairs with a distance, and only suggestion lines since plugin commit
699d710 record distances.

### Where the records live

iirc records what the suggestion hook did on this machine only, in
`~/.local/state/dokidlc-iirc/`. Each suggestion line logs the pages it named, the
25 best candidates with the reason each passed or failed, and the first
300 characters of the prompt. Each session logs its numbers at
compaction and at session end. Nothing there is committed, and files
older than 90 days are deleted. [What iirc
records](HOW-IT-WORKS.md#what-iirc-records) has every file and field.

### Known limits of iirc summarize-page-usage

The 7-day view of `/iirc summarize-page-usage` has two known faults:

- "Written pages later verified" counts a write whose page has any
  `verify` in the window. It does not check that the verify came after
  the write.
- "Read after a search or a suggestion line named it" compares page names as
  logged. A page named `STORE/PAGE.md` in one row and `PAGE.md` in the
  other does not match.
