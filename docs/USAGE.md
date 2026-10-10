# Using iirc

This page has how-to guides for the tasks you meet with iirc, then
reference for every `/iirc` command and every setting, in the split
[Diátaxis](https://diataxis.fr/) makes. Why iirc works the way it does
is in [HOW-IT-WORKS.md](HOW-IT-WORKS.md). You never have to run an
`iirc` command yourself. You ask in words, and the agent runs it. Where
a `/iirc` command does the same job, this page names it.

## Day to day

Mostly you do nothing. Recall names matching pages under your prompt,
and a line under the prompt sums up the session; [UI.md](UI.md)
describes the row, the line, and the cards. The row shows you the list
the agent got. When the circle on the line turns yellow or red, the line
ends with the command that clears it, such as `· run iirc doubt`; ask
the agent to run it, or type it after `/iirc`. For anything else, ask in
words: "what do we know about ollama hangs?", "remember that...",
"what's out of date?". To read a page yourself, click its name, run
`/iirc reader PAGE` to open it in the reader, or `/iirc show PAGE` for a
card in the transcript; your reads do not count as the agent's.

## Tasks

### Set up a machine

Install the plugin once per machine ([README](../README.md)). Then open
a session in a repository and say "set up iirc". The agent asks where
embeddings come from, and offers five choices:

| Choice | `iirc setup` flag | Needs |
|---|---|---|
| ollama on this machine | `--local` | ollama here; doctor installs it on macOS |
| ollama on another host | `--host URL` | ollama on that host |
| an OpenAI-compatible host, such as vLLM serving qwen3-embedding | `--openai URL` | a server that answers `POST URL/v1/embeddings` |
| this CPU, all-MiniLM-L6-v2 through onnxruntime | `--cpu` | about 90 MB of model files, which setup fetches; no ollama |
| string search | `--substring` | nothing; it matches exact text only |

With ollama, `--model` picks `qwen3-embedding:0.6b` (the default),
`nomic-embed-text`, or `embeddinggemma`. The agent recommends ollama,
here or on the host this machine already names, when one answers, and
this CPU otherwise. String search is the last choice. The agent then
runs `iirc setup`, `iirc init` if you want pages in this repository, then
`iirc doctor --fix`, which installs memoryfield-tool and, for a local
host on macOS, ollama and the model. You see doctor's report.
[INSTALL.md](../INSTALL.md) has every step as a command.

A machine set up before the model choice keeps nomic until setup runs
again. A new model embeds every page again: the next `iirc index` does
it, or the first search that finds the pages missing starts it in the
background.

### Start iirc in a repository

Say "start iirc in this repository". The agent asks, then runs
`iirc init`. It creates `.iirc/index.md`, adds the `## IIRC` section to
`CLAUDE.md`, and stages both. Commit them, together with the
`.claude/settings.json` that enables the plugin for each clone
([INSTALL.md](../INSTALL.md), steps 7 and 8). The pages persist only
when `.iirc/` is committed.

### Migrate from the memory plugin

When a repository or machine still has the memory plugin's layout, the
session-start line says so, and the line under the prompt turns red
with "needs migration". Say "yes, migrate". The agent runs
`iirc migrate`, which moves the store directory, the config, the
`CLAUDE.md` section, the plugin setting, and this machine's directories
to their iirc names. It stages the changes and prints a suggested
commit. It never commits; the agent shows you the output and commits on
your word.

### Ask what iirc knows

Ask: "Do you remember anything about installing this on a mac?" The
agent runs `iirc search` with your question, reads the pages that fit,
and answers from them. To look yourself, type `/iirc search QUERY`,
`/iirc read PAGE`, or `/iirc topics`. A page you read this way does not
count toward the session's reads, which are the agent's.

### Tell it to remember

Say: "Remember that the NAS keeps its live firmware in
/etc/default_config." The agent searches first. If a page already holds
the fact, it runs `iirc verify` on that page and tells you. If not, it
writes a page with a title, a one-line summary, topics, a kind, and a
Sources section, and `iirc write` commits the store's directory. It
also writes at [the skill's moments](../skills/iirc/SKILL.md#when-to-write).

### Find and fix what may be out of date

Ask: "What in iirc might be out of date?" The agent runs `iirc doubt`.
It lists the pages with evidence against them, strongest first. A page
is suspect when a file it cites changed since it cited it, or when its
check command now fails. For each one, the agent reads the page and
the diff, then verifies, rewrites, or deletes the page in the same turn.
`/iirc doubt` prints the same list, and `/iirc doubt --all` adds the
clean pages. Ask for a doubt pass after a `git pull` and when the line
under the prompt says `· run iirc doubt`.

Two cases need your yes. A check command that arrived with a clone is
not approved on this machine, so `doubt` lists it and does not run it.
The agent shows you the command and asks; on yes it runs
`iirc approve PAGE`, and Claude Code asks you to approve the command too.
`doubt` never contacts the URLs in a page's refs. To check them, the
agent names the URLs `iirc doubt --network` will contact and asks. The
command refuses unless a terminal answers yes or `IIRC_ALLOW_NETWORK=1`
is set, and only you set it.

### Merge near-duplicates

When two pages sit at the model's duplicate distance or closer, the
session-start line counts the pair and the circle turns yellow with
`· run iirc doctor`. `/iirc doctor` names each pair, and also notes
similar pairs up to the model's near-duplicate distance:

| Model | Duplicate: the line turns yellow | Near-duplicate: doctor notes it |
|---|---|---|
| `nomic-embed-text` | 0.07 | 0.10 |
| `qwen3-embedding:0.6b`, `qwen3-embedding` | 0.12 | 0.17 |
| `embeddinggemma` | 0.10 | 0.14 |
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
`iirc stores add NAME URL --default`. That writes `.claude/iirc.toml`
with the project store and the new one, clones the repository, and
commits the config. The agent then writes facts that hold in any
project to the remote store; each write commits and pushes, and each
session start pulls. When the line says `not pushed`, type `/iirc sync`.
On another machine, `iirc doctor --fix` clones a missing remote store.

### Work without ollama

Say "search on this CPU". The agent runs `iirc setup --cpu`, which
fetches all-MiniLM-L6-v2 and runs it once, so onnxruntime installs then
and not in a hook. Search still matches meaning. If onnxruntime has no
wheel for this machine, setup says so and writes nothing.

Say "use string search" when nothing else can run. The agent runs
`iirc setup --substring`. Search then matches exact text only, and the
agent searches for the words a page contains
([references/search.md](../skills/iirc/references/search.md)). Recall
names a page only on a shared identifier, and the line under the prompt
shows `[keyword] mode`. To go back, ask for `iirc setup` with another
choice. If ollama is only down for a while, change nothing: iirc skips a
host that does not answer a two-second probe and searches by string
until it answers.

### Audit the pages

Say "audit the pages", or type `/iirc audit`. The agent runs
`iirc audit`, which prints one line per page that search shows badly,
with its fix: a title over 70 characters, a summary that starts with a
date or shares no word with the title, a secret, a page that a search
for its own title does not rank first, a page that tune judged noise
far more often than relevant, and a page that names its successor but
keeps its old text. `iirc audit PAGE` checks one page, and `--json`
prints the findings as JSON. The audit changes nothing; the agent
proposes each fix for your yes. `/iirc tune` runs it after the sweep.

### See exactly what the hooks told the agent

Say "turn on show_hooks". The agent adds `show_hooks = true` at the top
of `.claude/iirc.toml` and commits it. From the next hook on, each hook
also shows its raw text to you as a system message. The file is
committed, so ask for the line to be removed when you are done.

### Turn the drawn UI or the line under the prompt off

`/iirc status-line off` hides the line under the prompt on this machine,
and `/iirc status-line on` brings it back. To draw nothing at all, ask
the agent to add `ui = false` to `.claude/iirc.toml`. That removes the
rows, the line, and the toasts for everyone who clones the repository.
The hooks still give the agent its lines, and every command still works.

## The /iirc commands

The `command.run` handler in
[`hooks/register.tsx`](../hooks/register.tsx) answers these forms.

| Command | What you see |
|---|---|
| `/iirc` | The short card: ask in words, pointers to help and status, this session's recall hit rate and average match, and the page count. |
| `/iirc status` | Every number: the status chip, TRUST (suspect pages), each store's uncommitted and unpushed state, the session counts, the hit rate, and SUGGESTED, NOT READ. It runs `iirc doctor --health` first. |
| `/iirc help` | The two settings with their current values, the commands `/iirc` runs directly, and under WITH CLAUDE the ones that go to the skill. |
| `/iirc demo`, `/iirc demo status` | The short card or the status card with sample numbers. |
| `/iirc status-line` | Whether the line under the prompt is on or off. |
| `/iirc status-line on`, `/iirc status-line off` | Shows or hides that line, on this machine. |
| `/iirc max-suggested` | How many pages recall suggests at most. |
| `/iirc max-suggested N` | Sets that number, 1 to 10, on this machine. |
| `/iirc doctor`, `/iirc doctor --fix` | The setup checks as a card; `--fix` installs or repairs what fails. |
| `/iirc doubt`, `/iirc doubt --all` | Pages with evidence they may be wrong; `--all` lists clean pages too. |
| `/iirc sync` | Commits, pulls, and pushes every remote store. |
| `/iirc stores` | The stores, their page counts, and anything not committed or pushed. |
| `/iirc stats`, `/iirc stats --days N` | Recall and page use over the last 7 days, or N days. |
| `/iirc index` | Rebuilds the search index. |
| `/iirc cost` | Bytes and tokens of `index.md` and of a sample search. |
| `/iirc knobs` | The recall distances in force for this machine's model, from `[recall.MODEL-ID]`, and their ranges. |
| `/iirc topics` | Every topic with its page count. |
| `/iirc search QUERY` | Ranked pages for the query; all the words form one query. |
| `/iirc read PAGE` | One or more pages, with their trust markers. |
| `/iirc open` | Unfolds the latest suggested-pages row, as a click on its `[+]` does. |
| `/iirc reader`, `/iirc reader PAGE` | The reader, a pane with this session's suggested, written, and suspect pages, or open on one page. A click on a page name, here or anywhere iirc draws one, opens the page in the reader's page tab. See [UI.md](UI.md#the-reader). |
| `/iirc show PAGE` | One page as a card in the transcript; your read, not the agent's. |
| `/iirc audit` | Goes to the skill: the agent lists the pages search shows badly and proposes each fix for your yes. See [Audit the pages](#audit-the-pages). |
| `/iirc setup` | Goes to the skill: the agent asks which embedding model and where it runs, or substring search, then runs `iirc setup`. |
| `/iirc tune` | Goes to the skill: the agent judges the recorded sessions and proposes page fixes and knob changes, each for your yes. See [Turn the knobs on evidence](#turn-the-knobs-on-evidence). |

The direct commands print what the `iirc` command prints. `doctor --fix`,
`sync`, and `index` may run for up to ten minutes; the rest stop after
one minute. Anything else after `/iirc` goes to the skill as a request in
words. That includes the commands that need a question first:
`stores add`, `setup`, `init`, `write`, `delete`, `approve`,
`knobs set`, and `doubt --network`.

### The agent's commands

These have no `/iirc` form of their own; ask in words. `iirc --help`
describes each one.

| Command | What it does |
|---|---|
| `iirc pull QUERY` | Searches, then prints the full text of each matching page, as `read` does. |
| `iirc write`, `iirc verify`, `iirc delete`, `iirc approve` | Write, confirm, remove, or approve the check of a page. |
| `iirc audit [PAGE] [--json]` | Pages that search shows badly; see [Audit the pages](#audit-the-pages). |
| `iirc setup`, `iirc init`, `iirc migrate`, `iirc max-suggested N` | Machine setup, the repository's `.iirc/`, the move from the memory plugin, and the pages per line. |
| `iirc tune gather`, `judge`, `sweep`, `done` | The tune steps. `iirc tune sweep --replay FILE...` replays judged prompts through today's search and gate. |
| `iirc recall`, `iirc nudge` | Hook entries: `recall` names pages for a prompt or a failed command; `nudge --stop` asks for a page at the end of a turn, and the hooks module runs `nudge --compact` near compaction and `nudge --summary` as it runs. |

## Every setting

| Setting | Where it lives | Default | Range or values | What it changes | When to turn it |
|---|---|---|---|---|---|
| `semantic` | `~/.config/dokidlc-iirc/config.toml`, this machine | `true` | `true`, `false` | Semantic and string search, or string search only. | Ask the agent to run `iirc setup` again; it writes the file. |
| `[embedding]` `backend`, `model`, `url` | the same file | none, which means nomic through ollama | `ollama`, `openai`, or `onnx`; a model in [Recall knobs per model](#recall-knobs-per-model); `url` for `openai` only | Which model embeds pages and queries, and where it runs. | `iirc setup` writes it. |
| `embedding_host` | the same file | none, then `127.0.0.1:11434` | `host:port` or `http://host:port` | Where ollama embeddings come from. A host that does not answer a 2 s probe is skipped. | When ollama moves to another host: `iirc setup --host URL`. |
| `max_suggested` | the same file | `3` | 1 to 10 | Pages one recall line names at most. The line's byte cap is 120 + 200 times N. | `/iirc max-suggested N`, when the row brings too much or too little. |
| `OLLAMA_HOST` | the environment | unset | host or URL | Turns semantic search on whatever setup chose, and is the first host tried. A host that does not answer loses to one that does. | Rarely. Prefer `iirc setup`, which warns when this is exported. |
| `[recall.MODEL-ID] semantic_only` | `.claude/iirc.toml`, committed, so every clone | per model, below | per model, below | The largest cosine distance for a page with no strong term (rule `meaning`). | Only on evidence from the records; `/iirc tune` proposes a value, and the agent sets it with `iirc knobs set` on your yes. |
| `[recall.MODEL-ID] both` | `.claude/iirc.toml` | per model, below | per model, and at least `semantic_only` | The largest distance for a page backed by a strong term (rule `meaning+term`). | The same as `semantic_only`. |
| `ui` | `.claude/iirc.toml` | `true` | `true`, `false` | `false` draws no rows, no line under the prompt, and no toasts. | When nobody who clones the repository wants the drawn UI. |
| `show_hooks` | `.claude/iirc.toml` | `false` | `true`, `false` | `true` shows each hook's raw text to the person as well. | While you debug what reached the agent. |
| `write` | `.claude/iirc.toml` | the project store, else the only store | the name of a store | The store `iirc write` uses without `--store`. | `iirc stores add NAME URL --default` sets it. |
| `[stores.NAME] kind` | `.claude/iirc.toml` | required in each store table | `project` (at most one), `remote` | A directory in the repository, or a clone of a shared repository. | When you add a store. |
| `[stores.NAME] path` | `.claude/iirc.toml`, project store only | `.iirc` | a directory inside the repository, not a symlink | Where the project store lives. Outside `.iirc/`, the read guard does not cover it. | Rarely. |
| `[stores.NAME] url` | `.claude/iirc.toml`, remote store only | required | a git URL | The clone source. The clone is `~/.local/share/dokidlc-iirc/stores/NAME-HASH`. | When you add a store. |
| the line under the prompt | the hooks module's store, this machine | on | on, off | Shows or hides that line. | `/iirc status-line on` or `off`. |
| `IIRC_ALLOW_NETWORK` | the environment | unset | `1` | Lets `iirc doubt --network` run with no terminal to answer yes. | Only when you want URL refs checked from a session. |
| `XDG_CONFIG_HOME`, `XDG_CACHE_HOME`, `XDG_DATA_HOME`, `XDG_STATE_HOME` | the environment | `~/.config`, `~/.cache`, `~/.local/share`, `~/.local/state` | paths | Where the machine config, the index, the remote clones, and the records live. | When your machine moves them. |

Store tables, in `.claude/iirc.toml`, replace the implicit project store.
With no `[stores.NAME]` table and no `write` key, iirc uses one project
store at `.iirc/`, so a file that holds only `ui` or `show_hooks` changes
nothing else. Names are lowercase letters and digits joined by single
hyphens, at most 31 characters. Unknown top-level keys are ignored.
Some values are fixed in the code: recall skips a prompt shorter than 40
characters, a page is at most 8192 bytes, a term in more than a tenth of
the pages is common, a search embeds at most 5 changed pages, and
records are kept 90 days.

### Recall knobs per model

Each model has its own distance scale, so each has its own table in
`.claude/iirc.toml`, named after the model with `:` changed to `-`. The
hooks read the table of this machine's model; a knob left out takes its
default. `iirc knobs` prints the table name and the values in force.

```toml
[recall.nomic-embed-text]
semantic_only = 0.28
both = 0.38

[recall."qwen3-embedding-0.6b"]   # quoted, because the name holds a dot
both = 0.62
```

| Model (`[recall.MODEL-ID]`) | `semantic_only` | `both` | Range | Cut: never farther |
|---|---|---|---|---|
| `nomic-embed-text` | 0.28 | 0.38 | 0.10 to 0.60 | 0.45 |
| `qwen3-embedding-0.6b` | 0.40 | 0.60 | 0.10 to 0.90 | 0.90 |
| `embeddinggemma` | 0.40 | 0.68 | 0.10 to 0.90 | 0.90 |
| `qwen3-embedding` (OpenAI-compatible) | 0.40 | 0.60 | 0.10 to 0.90 | 0.90 |
| `all-minilm-l6-v2` | 0.60 | 0.68 | 0.10 to 0.90 | 0.90 |

The defaults come from a replay of judged prompts
([SEARCH-QUALITY.md](SEARCH-QUALITY.md#results)). The OpenAI-compatible
`qwen3-embedding` takes the ollama qwen3's values without a measurement
of its own.

### How a bad value fails

A bad `.claude/iirc.toml`, such as a recall knob out of range, a flat
`[recall]` table from before the model tables, or a store table with no
`kind`, turns the hooks off. The session-start line
reads "iirc: hooks off", then the error and the command that fixes it,
and the line under the prompt turns red with "hooks off". Every other
hook stays quiet until the file is fixed. `iirc doctor` fails the check
".claude/iirc.toml loads, so the hooks run" and names the line to
change. `iirc doctor --fix` moves flat `[recall]` knobs into
`[recall.nomic-embed-text]`, the only model there was, and comments out
each bad knob, with a note, so its default applies; a broken store table
is yours to fix.
Every other command except `setup`, `stats`, and `max-suggested` stops
with the error.

A bad `~/.config/dokidlc-iirc/config.toml` is ignored, and nothing says
so. A file that does not parse reads as empty, and a `max_suggested`
outside 1 to 10 reads as the default, 3. `iirc max-suggested 11` itself
refuses with "max-suggested must be 1 to 10".

## Getting good results over time

### Write pages that recall can find

Three rules of the recall gate decide what a page should contain. They
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
summary. Every model embeds the whole page: nomic, qwen3, and gemma the
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

Plugin commits `699d710`, `a16668a`, and `fa1ed37` record what recall
does. The
cards and `/iirc stats` show it. Each number has a response:

- TRUST is not zero on `/iirc status`: type `/iirc doubt`, or ask the
  agent for a doubt pass.
- A page under SUGGESTED, NOT READ keeps coming back: ask the agent to
  read the page once and decide whether to narrow it, split it, or delete
  it. Narrow the page, not only the summary, because the index embeds the
  whole page.
- The recall hit rate on the cards is this session's suggested pages
  that were then read. It is a proxy for precision. One session holds
  too few suggestions to judge; watch it over several sessions, or read
  "read after a search or recall named it" in `/iirc stats`.
- The average match for read and unread pages: when the two are close,
  the score does not predict which pages get used. Do not move the
  recall knobs on that alone.
- Pages read that recall never suggested may be recall's misses. Ask
  the agent for `read_unsuggested` in the session's last row of
  `log.jsonl`, and check that each page carries the identifiers a prompt
  about it would use.
- Near-duplicate pairs: merge or link them, as in
  [Merge near-duplicates](#merge-near-duplicates).
- "[N] timed out" in yellow on the line: Claude Code killed a recall at
  the hook's 5 s limit. The session-start line counts the last 7 days'
  timeouts, and `iirc doctor` names the usual cause, a cold embedding
  model. `OLLAMA_KEEP_ALIVE=24h` keeps ollama's model loaded.

### Turn the knobs on evidence

`/iirc max-suggested N` gives more or fewer pages per prompt. The line's
byte cap grows with N, so each extra page allows up to 200 more bytes of
context. Change the recall knobs only on evidence from the recorded
sessions.

Say "tune recall", or run `/iirc tune`. The agent follows
[the tune reference](../skills/iirc/references/tune.md): it gathers the
recorded sessions, judges each suggestion against what the session
needed, and sweeps the knobs over those judgements. You then see each
proposal with its evidence: a page to narrow, split, or write, or a knob
value with the counts before and after. The sweep ends with
`iirc audit`, and for each flagged page the agent writes two prompts of
its own and checks where the page ranks. Nothing changes until you say
yes. A knob change edits this machine's model table in
`.claude/iirc.toml`, which you commit.

To measure a change to search or the gate before it lands, the agent
runs `iirc tune sweep --replay FILE...` on replay files of judged
prompts. It searches each prompt again with the current code and prints
the same counts. [HOW-IT-WORKS.md](HOW-IT-WORKS.md#the-replays) has the
file format and the session replay. Expect
the first knob proposal only after a few sessions: the sweep needs 30
judged pairs with a distance, and only recalls since plugin commit
699d710 record distances.

### Where the records live

iirc records what recall did on this machine only, in
`~/.local/state/dokidlc-iirc/`. Each recall logs the pages it named, the
25 best candidates with the reason each passed or failed, and the first
300 characters of the prompt. Each session logs its numbers at
compaction and at session end. Nothing there is committed, and files
older than 90 days are deleted. [What iirc
records](HOW-IT-WORKS.md#what-iirc-records) has every file and field.

### Known limits of iirc stats

The 7-day view of `/iirc stats` has two known faults:

- "Written pages later verified" counts a write whose page has any
  `verify` in the window. It does not check that the verify came after
  the write.
- "Read after a search or recall named it" compares page names as
  logged. A page named `STORE/PAGE.md` in one row and `PAGE.md` in the
  other does not match.
