# How iirc works

An agent learns things in a session: a tool that fails to install on
macOS, the fix, the reason a decision went one way. When the session ends,
that knowledge is gone, or it lands in a file that costs context on every
turn. iirc keeps it as short markdown pages in the repository, in `.iirc/`.
Hooks search the pages on each prompt and each failed shell command and
name the pages that match. Each page cites the files it rests on at a
commit, so iirc can say when a page may be wrong.

This document explains why iirc works the way it does and where the code
is. Tasks and every setting are in [USAGE.md](USAGE.md). What the hooks
module draws on screen is in [UI.md](UI.md).

## In brief

Why not use Claude Code's memory? That memory is for this machine and
this person, and it lives in your home directory. iirc is for the
project. Its pages are in git, they reach every clone, and you review them
like code. Auto memory loads its index, the first 200 lines or 25KB of
`MEMORY.md`, into every session, so it stays small by design. iirc can
hold hundreds of pages, because the agent finds a page by search and a
session never loads the whole store. A page cites files at a commit, and iirc marks it suspect
when a cited file changes. See
[the comparison](#iirc-and-claude-codes-own-memory).

Can you change the recall gate? Yes. The gate is `recall_verdicts` in
`bin/iirc`. Its two distances are `RECALL`, read from `[recall]` in
`.claude/iirc.toml`. `IDENTIFIER_RE` and the five-letter head-term rule
decide what a strong term is. The test
`test_recall_verdicts_say_why_each_candidate_was_left_out` fixes the
verdicts. The rules are in [The recall gate](#the-recall-gate), and the
evidence for a change is in [What iirc records](#what-iirc-records).

## Principles

Knowledge about the project lives with the project. Pages are committed
with the code, so you can diff, review, and revert them. A page true for
every project can go to a shared repository. See [Stores](#stores).

Pages are found, not loaded, because context is a budget. A session pays
for a one-line brief and a capped line per prompt. The skill loads only
when the agent needs it. See
[A session, start to finish](#a-session-start-to-finish).

The agent writes on its own at named moments: something took more than
one attempt, a quest stage closed, a hook said a command recovered, or
you said "remember". Four rules in [the skill](../skills/iirc/SKILL.md)
keep the pages worth searching.

Trust comes from evidence, not age. A page turns suspect when a file it
cites changed or its check fails. Age adds only a glance note, and how
often a page is read never counts. The design review
[REVIEW-PASS-RECOMMENDATIONS.md](REVIEW-PASS-RECOMMENDATIONS.md) took
this from the
[agent memory systems report](https://github.com/daftdoki/research/tree/main/agent-memory-systems-and-dreaming):
frequency is the signal an injected record exploits. See
[IIRC pages](#iirc-pages).

Hooks fail open, then say so. A hook never blocks a prompt or a command.
`log_event`, `eval_event`, and `keep_prompt` never raise, and
`cmd_recall` catches every exception. A bad `.claude/iirc.toml` silences
the hooks, and the session-start brief says so. A recall killed at its
time limit is logged. See [Session start](#session-start-and-subagent-start).

You see what the agent was told. The hooks module draws each hook line
under your prompt or command. See [UI.md](UI.md).

Recall is measured so that it can be tuned. Every recall, every candidate
it weighed, and every session's numbers go to a local log. See
[What iirc records](#what-iirc-records).

## iirc and Claude Code's own memory

The Claude Code facts come from its docs on
[memory](https://code.claude.com/docs/en/memory.md) and the
[context window](https://code.claude.com/docs/en/context-window.md).

| | Auto memory | CLAUDE.md | iirc pages | `docs/` |
|---|---|---|---|---|
| Where it lives | `~/.claude/projects/<project>/memory/`, outside the repository | the repository, and each directory above the working directory | `.iirc/` in the repository, or a clone of a remote store | the repository |
| Who writes it | Claude; you through `/memory` | you; `iirc init` adds one paragraph | the agent, at named moments | you, or the agent on your request |
| In git | no; "machine-local", "not shared across machines" | yes | yes; a remote store also pushes | yes |
| Loaded at session start | the first 200 lines or 25KB of `MEMORY.md` | the whole file; the docs say "target under 200 lines" | the CLAUDE.md paragraph (428 bytes), the brief (232 bytes measured), the skill's description line (491 bytes) | nothing |
| Loaded per prompt | none | none | one recall line when pages match, at most 120 + 200 × `max_suggested` bytes (720 at the default 3; 569 measured) | none |
| How it is found | topic files read on demand with file tools | always in context | search by a hook on each prompt and failure, and by the agent | the agent opens a file something points to |
| How it goes stale | it stays "until you or Claude edits or deletes" it | the same | suspect when a cited file changed or a check fails; a glance note by age | you review it |
| Who it serves | this machine and this person | everyone on the project | the project, and every project that shares a remote store | the people on the project, and agents that read it |

Some things are the same. Auto memory also reads its topic files on
demand, so it is not loaded whole either. Both survive compaction: Claude
Code reloads CLAUDE.md and memory, and iirc's brief runs again.

Auto memory is in your home directory, and iirc is in git. Auto memory
serves one machine and one person, and iirc serves the project. An iirc
page cites files at a commit and turns suspect when they change. iirc
writes at named moments under rules, and it records every recall. So this
machine's hostname goes in auto memory, a tool's install quirk goes in
`.iirc/`, and anything you asked for or reviewed goes in `docs/`. A page
may cite a document. A document never cites a page.

## A session, start to finish

`hooks/hooks.json` registers these hooks. No hook runs a page's check.

### Session start and subagent start

`SessionStart` and `SubagentStart` run `iirc doctor --brief --hook`
(10-second timeout). At session start only, iirc pulls each remote store
within 5 seconds, reindexes in the background when pages arrived, and
logs a `start` row. The agent gets one line, 232 bytes here:

```
iirc: 81 pages, semantic via 127.0.0.1:11434. Topics: claude-code 30, plugin 20, questlog 20, decisions 16. A hook names matching pages when the creator prompts; read them. `iirc search QUERY` before an install, a fix, or a design.
```

Warnings make it longer: suspect pages, store changes not committed or
not pushed, near-duplicate pairs (0.07 apart or closer, unless the pair
has different kinds and one links the other with `[[name]]`), a start
scan past 5 seconds, and recalls that timed out in the last 7 days. After
a compaction in a session that wrote nothing, it adds:

```
Context was just compacted and this session wrote no iirc. If the summary above names a fix that took more than one attempt, write it now.
```

When `.claude/iirc.toml` does not load, the brief is this line, every
other hook stays quiet, and the line under the prompt turns red:

```
iirc: hooks off, <the error>. Every iirc hook stays quiet until it is fixed; run `iirc doctor --fix`.
```

`iirc doctor --fix` appears when only `[recall]` knobs are wrong. It
comments out each bad knob line so the default applies
(`reset_bad_knobs`). Any other error names `iirc doctor`, whose check
".claude/iirc.toml loads, so the hooks run" fails and names the line.

### Each prompt

`UserPromptSubmit` runs `iirc recall` (5-second timeout). It first removes
the blocks Claude Code adds around a prompt: system reminders, task
notifications, subagent hand-backs, and messages from other sessions. A
prompt that is nothing but those blocks is skipped as `machine`; otherwise
recall searches the person's words alone. It also skips slash commands,
prompts under 40 characters, and short answers such as "yes", and logs a
`skipped` row for each. Otherwise it searches, applies
[the gate](#the-recall-gate), and prints one line when a page passes:

```
iirc: 3 pages may apply. Read before you investigate: `iirc read recall-hook-times-out-when-ollama-unloads-the-embed-model.md` (memory recall embeds via ollama; a cold load took 13.6 s against the hook's 5 s; the…) [86% match, meaning+term] · `iirc read ollama-host-silent-hang.md` (Why the wrapper probes every candidate host with a two-second timeout and skips dead ones) [75% match, meaning+term] · `iirc read recall-ui-mod-hooks-session-append.md` (Hook lines arrive as session.append hook-context rows; a Bash call in a collapsed…) [68% match, meaning+term]
```

That line is 569 bytes and took 406 ms. It names at most `max_suggested`
pages, 3 by default. `recall_max_bytes()` caps it at
120 + 200 × `max_suggested` bytes, and `recall_line` clips each summary
to 90 characters. Entries past the cap drop whole, and their candidate
rows get the verdict `line_cut`. A recall logs a `recall` row, up to 25
`candidate` eval rows, and a prompt excerpt.

Claude Code kills a hook past its timeout, usually when the embedding
model is cold. `run_recall` writes a marker, `inflight/SESSION` in the
state directory, and removes it when it finishes. When the next recall or
the session snapshot finds the marker, `note_timeout` logs a `timeout`
row. `iirc doctor` reports the 7-day count, and the line under the prompt
shows "[N] timed out" in yellow.

### A shell command fails, recovers, and the agent stops

`PostToolUseFailure` on Bash runs `iirc recall --failure`. The query is
the command's first word (two after a launcher such as `git` or `uv`)
plus up to 8 terms from the error. The line has the same form and cap. An
error that is only an exit code gets nothing.

`PostToolUse` on Bash runs `iirc recall --success`. When a command failed
twice or more, then worked, and the session wrote no page, the agent
gets this once per command:

```
iirc: `{cmd}` failed {n} times this session before it worked. If the fix was not obvious from a file in the repository, write one `iirc write` page of kind procedure with the command that worked and its Sources. If there is nothing worth a page, say so.
```

`Stop` runs `iirc nudge --stop`. Under the same condition, once per
session, it names those commands and asks for a page per finding, or a
statement that nothing is worth a page.

### Compaction and the session's end

`PreCompact` and `SessionEnd` run `iirc stats --snapshot --hook` and tell
the agent nothing. They log any recall that timed out, then a `session`
row, then rotate the logs. The 10-second timeout is there because the
default `SessionEnd` budget is 1.5 seconds
([hooks](https://code.claude.com/docs/en/hooks.md)).

### The guard

`PreToolUse` on Bash and Read runs `scripts/guard.sh`. Claude Code asks
you before `iirc doubt --network` and `iirc approve`. A raw read of a
page file, by `cat`, `head`, `sed`, `tail`, `less`, `more`, or the Read
tool, is denied, and the reason tells the agent to use `iirc read`, which
prints the trust markers, or `iirc doctor --fix` if that fails.

## The parts and where the code is

| Part | Path | What it does |
|---|---|---|
| The command | `bin/iirc` | A Python script under `uv run --script` that wraps memoryfield-tool. It adds per-repository config, the embedding-host guard, refs and suspicion, the recall gate, and the log. It does not reimplement storage, search, or indexing. |
| The engine pin | `iirc.pin` | The memoryfield-tool commit and the embedding model. |
| Command hooks | `hooks/hooks.json` | The events above. |
| The hooks module | `hooks/register.tsx` | Draws the hook lines, the line under the prompt, and the `/iirc` cards. See [UI.md](UI.md). |
| The guard | `scripts/guard.sh` | The `PreToolUse` asks and denies. |
| The skill | `skills/iirc/SKILL.md`, `skills/iirc/references/` | When to search, when to write, the four rules, and setup. |

The development loop and the tests are in
[DEVELOPMENT.md](../DEVELOPMENT.md).

## Stores

`.claude/iirc.toml` lists the stores. Without it there is one, the
project store at `.iirc/`. Each store is one memoryfield field, and
memoryfield-tool searches them all in one call.

| Store | Where | Committed | Pushed |
|---|---|---|---|
| project (at most one) | a directory in the project repository, `.iirc` by default | yes | never |
| remote | a clone at `~/.local/share/dokidlc-iirc/stores/NAME-HASH`, HASH from the URL | yes | after every commit |

Each command that changes a store commits that store's directory, and
nothing else, under a per-store lock. A remote store's commit carries an
`IIRC-Project:` trailer and is pushed. A rejected push is rebased once
and pushed again, and a conflict waits for `iirc sync`. iirc makes no
commit during a merge or rebase and never pushes the project repository.

A page in a remote store records its project, and its file refs read
`PROJECT:path@sha`. Suspicion, checks, and `verify` act only on the
current project's pages. Search ranks them first and hides nothing.

### Adding a remote store

A remote store is a separate git repository that several projects or
machines share. Create it, then ask the agent to add it. The agent runs
`iirc stores add agent URL --default`, which writes `.claude/iirc.toml`,
clones the repository, and commits the config:

```toml
write = "agent"          # the store `iirc write` uses without --store

[stores.project]
kind = "project"
path = ".iirc"

[stores.agent]
kind = "remote"
url = "git@github.com:you/agent-iirc.git"
```

With two or more stores, each result names its store, as in
`agent/ollama-host.md`.

## IIRC pages

The agent writes pages. You rarely will. Each page is one topic, under
8KB, with frontmatter that search and the trust rules read:

```
---
title: A silent OLLAMA_HOST hangs the tool
summary: Why the wrapper probes the host with a two-second timeout
topics: [ollama, memoryfield-tool]
kind: finding
refs: [docs/research.md@61b6f00]
check: curl -s localhost:11434 >/dev/null
verified: '2026-09-04T22:42:52Z'
---
The tool hangs about 75 seconds on a host that goes silent.

## Sources

- timed against /api/embed, 2026-09-01
```

| Key | Meaning |
|---|---|
| `title` | What the page is about. |
| `summary` | One sentence, 160 characters or fewer. Search shows this line. |
| `topics` | One or two tags. `iirc topics` counts them. |
| `kind` | `environment`, `procedure`, `finding`, or `decision`. |
| `refs` | Files the page cites, each at a commit, or URLs. See [Sources](#sources). |
| `check` | A read-only command. If it fails, the page becomes suspect. |
| `verified` | When the agent last confirmed the page. |

The kind sets an age: 30 days for `environment`, 90 for `procedure`, 180
for `finding`, never for `decision`. Past it, an unconfirmed page gets a
"glance" note: look before you rely on it. Only evidence makes a page
suspect: a cited file changed, its check failed, or the agent found it
wrong.

A check written on this machine is approved when it is written. A check
that arrived with a clone runs only after the agent asks you and runs
`iirc approve`. The guard refuses a raw read of a remote store's pages by
path pattern, which is a convention, not a boundary.

Two pages that read as duplicates make search name the wrong one.
`iirc doctor` names each pair; [USAGE.md](USAGE.md) says how to merge or
link them.

`index.md` is the one page the agent does not write. Its text is yours.
iirc ends it with `<!-- iirc format 1 -->` and changes that line only when
the format changes.

## Sources

Every page ends with a `## Sources` section that says where the fact came
from. `iirc write` refuses a body without one.

A file ref is `path@sha`. The page turns suspect when the cited text
differs from the file now. A move alone is no change, and `verify`
rewrites the ref to the new path. `path#Heading@sha` cites one markdown
section, up to the next heading of its level or higher. With two headings
of the same text, the first counts.

Search never contacts a URL ref. `iirc doubt --network` sends one HEAD
request per URL, after the agent asks you and Claude Code prompts you. A
URL that answers "gone" makes the page suspect. A URL that does not
answer adds a glance note.

## How search ranks

Each query runs a semantic search and a string search, and
`hybrid_search` merges the two.

Semantic search matches meaning: "why does install fail on a mac" finds
the page about a missing wheel, though they share no words. It needs the
model `nomic-embed-text`, served by ollama here or on a host you can
reach. It is weak on exact identifiers such as "pysqlite3-binary".

String search looks for the query's important words in the name, title,
summary, and body of each page. It needs no model and no index. It finds
identifiers, not paraphrase.

Pages both searches found come first, then other semantic results,
nearest first, then pages only string search found. Each result says how
it was found:

```
pysqlite3-install-override.md: Why memoryfield-tool needs a uv overrides file ... (distance 0.226; via semantic, install, pysqlite3-binary)
```

### The recall gate

The gate, `recall_verdicts`, decides which ranked pages the recall line
names. A term in more than a third of the pages, and more than 3, is
common and counts for nothing. A strong term is a rare term with a digit,
dot, hyphen, or underscore, or a rare word of five letters or more in the
page's filename, title, or summary. A page passes on one of three rules:

| Rule | Passes when |
|---|---|
| meaning+term | semantic search found it within `both`, and it has a strong term |
| meaning | semantic search found it within `semantic_only` |
| term | only string search found it, on a rare identifier |

A plain word never passes alone. The `recall_verdicts` docstring says
why: "replayed over 68 prompts on 2026-10-08, none of the 29 plain-word
term matches was relevant." Passing pages fill up to `max_suggested`.
The two distances are knobs, set per repository:

```toml
[recall]
semantic_only = 0.28   # 0.10 to 0.60
both = 0.34            # 0.10 to 0.60, and at least semantic_only
```

A value out of range is a configuration error: commands stop, and the
hooks go quiet as [Session start](#session-start-and-subagent-start)
describes. `iirc knobs` prints the values in force. A line's `69% match`
is 100% less the distance. Every knob, with its default and range, is in
[USAGE.md](USAGE.md).

### Without ollama

Without an embedding host, only string search runs. The agent then
searches for words a page contains, not for the question.
[USAGE.md](USAGE.md) says how to switch.

### The semantic index

memoryfield-tool builds the index from the pages and keeps it in this
machine's cache directory, not the repository. It embeds each whole page
file, frontmatter and body, cut at 8192 bytes (`_embed_input` in
`memoryfield_tool/index.py`). So a narrower page moves its vector more
than a narrower summary does. `bin/iirc` updates the index after each
write and rebuilds it on a fresh clone. You can delete it at any time;
the pages are the only source of truth.

## What iirc records

iirc records what recall did, on this machine only, in
`~/.local/state/dokidlc-iirc/` (`$XDG_STATE_HOME`). Nothing here is
committed or pushed. `iirc stats` and the `/iirc` cards read it. Commits
699d710 and a16668a built it for tuning recall, and fa1ed37 added the
`timeout` rows.

| File | One row per | Holds |
|---|---|---|
| `log.jsonl` | command and hook | reads, writes, searches, verifies, failures, nudges, and the rows below |
| `eval-YYYY-MM.jsonl` | candidate page | the 25 best candidates of each recall, passed or not |
| `prompts/SESSION.jsonl` | prompt | the first 300 characters of each prompt, its hash, and its `recall_id` or skip reason |

The log rows that matter for tuning:

- `recall`: the pages named and their scores, `via` (prompt or failure),
  a `recall_id` that joins it to its candidates and excerpt, the
  transcript path, a prompt hash, and the time in `ms`.
- `skipped`: the reason (`machine`, `slash_command`, `short`,
  `numbered_answer`, `answer`), the prompt length, and its hash.
- `timeout`: a recall killed at the hook's 5-second limit
  (`RECALL_HOOK_TIMEOUT`), with the time it started.
- `start`: the conditions from `conditions()`: plugin commit, knobs,
  `max_suggested`, search mode, memoryfield-tool rev, and page count.
- `session`, at compaction and at the session's end: the same conditions
  and the session's numbers from `session_summary()`. The last one
  counts.

A `candidate` eval row has the rank, page, distance, which searches found
it, its rare and head terms, the rule that passed it, and a verdict:
`passed`, or why not (`too_far`, `needs_term`, `plain_word`,
`common_term`, `over_max`, `line_cut`).

The prompt text never goes into `log.jsonl`, because a prompt can hold a
secret. The hash finds the prompt in the transcript. The excerpts exist
because Claude Code deletes transcripts after 30 days by default
([`cleanupPeriodDays`](https://code.claude.com/docs/en/claude-directory.md)),
and judging a suggestion needs the prompt. `rotate_logs` moves
`log.jsonl` aside each month and deletes any of these files untouched for
90 days.

## Reading the records

Each number answers one question. One session is too small a sample for
most of them.

The hit rate, used over suggested, is a proxy for precision. It means
something over several sessions.

The average match of read pages against unread pages says whether the
score predicts use. When the two are close, do not move the knobs on it.

SUGGESTED, NOT READ names noise pages. A page that keeps appearing there
needs to be narrowed, split, or given a better summary.

`read_unsuggested` names pages the agent read that recall never named:
possible misses.

The verdict counts show where the gate cuts. `needs_term` pages were
close but had no strong term. `too_far` pages were past the distances.
`plain_word` and `common_term` count what the term rules refused.
`over_max` and `line_cut` say the line was full. Timeouts say recall
never reached the agent, which points at the host, not the gate.

The conditions let an analysis compare like with like: the same plugin
commit, knobs, `max_suggested`, and mode.

The records lead to three kinds of change: a fix to a noisy page, a knob
change the records support, and a code finding for the developer when the
records contradict a rule. The replay that keeps plain words out of the
gate is that kind of finding.

`iirc tune` does this work, in four steps the agent runs from
[the tune reference](../skills/iirc/references/tune.md):

1. `iirc tune gather` joins the log, the candidate rows, and the prompt
   excerpts to each session's transcript. It writes one evidence file
   per session to `~/.local/state/dokidlc-iirc/tune/`: each recall's
   prompt, the pages it suggested, the candidates worth judging, and what
   the agent did next. A script does the joining, so no tokens go to it.
2. The agent reads each page with `iirc read --for-tune`, which is not
   counted as a read by the session, and records a verdict per pair with
   `iirc tune judge`: relevant, noise, or unsure. It judges from the prompt
   and what happened next, not from the match percentage.
3. `iirc tune sweep` replays the gate over the judged pairs for a grid of
   `semantic_only` and `both` values and prints precision, recall, and
   F1 for each. Below 30 judged pairs with a distance, it proposes nothing.
4. The agent proposes page fixes and, when the sweep supports one, a knob
   change with `iirc knobs set`. Code findings go in a section for the
   developer. Nothing applies until you say yes. `iirc tune done` marks
   each session, and gather skips a session that did the judging itself.
