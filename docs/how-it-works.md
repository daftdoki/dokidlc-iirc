# How memory works

The hooks the plugin registers, the shape of a page, and how search ranks.
The README says what the plugin does and how to get it running; this is
the reference behind it.

## Hooks

The plugin registers these hooks. All of them fail open. None runs a
page's check command.

| When | What the agent sees |
|---|---|
| Session start, and each subagent start | One line: page count, search mode, top topics, any page whose cited file changed, memory changes not committed or not pushed, the count of near-duplicate pairs that `memory doctor` names, and the scan time when it passed 3 seconds. At session start only, each remote store is fast-forwarded within five seconds, and a background reindex starts when pages arrived. After a compaction, a reminder to write if the session has written nothing. |
| Every prompt you send | If pages match, one line naming up to three with the `memory read` command for each. Short prompts, one-word answers, and slash commands are skipped. At most 400 bytes. |
| A shell command fails | The same line, searched with the error text. Silent when the error says nothing but an exit code. |
| A shell command works after failing twice | A reminder to write the fix as a procedure page, once per command. |
| The agent is about to stop | Once per session, only when a command failed twice then worked and nothing was written: write it, or say there is nothing worth a page. |
| The agent runs `memory doubt --network` or `memory approve` | Claude Code asks you to approve it. |
| The agent opens a page file raw, with `cat`, `head`, `sed`, `tail`, `less`, or `more`, or with the Read tool | The call is refused and the agent is told to use `memory read`, which prints the page with its trust markers and the commands that fix it, and to run `memory doctor --fix` if that command itself fails. |

## Stores

`.claude/memory.toml` lists the stores; without it there is one, the
project store at `.memory/`. A store is one memoryfield field, so
memoryfield-tool searches them all in one call.

| Store | Where | Committed | Pushed |
|---|---|---|---|
| project (at most one) | a directory in the project repository, `.memory` by default | yes | never |
| remote | a clone at `~/.local/share/dokidlc-memory/stores/NAME-HASH`, HASH from the URL | yes | after every commit |

Each command that changes a store commits that store's whole directory
with a pathspec commit, `memory: write NAME` and so on, under a per-store
lock so two sessions on one machine never collide in git. A commit to a
remote store carries a `Memory-Project:` trailer and is pushed; a
rejected push is rebased once and pushed again, and a conflict leaves the
local commit for `memory sync`. A page written to a remote store gets
`project:` in its frontmatter, the project's `origin` normalized to
`host/owner/repo`, and its file refs read `PROJECT:path@sha`. Suspicion,
checks, and `verify` act only on pages of the current project. Search
ranks the current project's pages first and hides nothing.

## Memory pages

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
The tool hangs about 75 seconds on a host that accepts a connection and
goes silent, because the client has no timeout.

## Sources

- timed against /api/embed, 2026-09-01
```

| Key | Meaning |
|---|---|
| `title` | What the page is about. |
| `summary` | One sentence, 160 characters or fewer. Search shows this line. |
| `topics` | One or two tags. They make the topic list in `index.md`. |
| `kind` | `environment`, `procedure`, `finding`, or `decision`. Says how fast the page can go stale. |
| `refs` | Files this page cites, each at a commit, or URLs. The page becomes suspect when the cited text differs from the file now; a move alone is no change, and `verify` rewrites the ref to the new path. `PATH#Heading@SHA` cites one markdown section, up to the next heading of its level or higher, so edits elsewhere in the file do not count; with two headings of the same text, the first counts. URLs are checked only when you allow it. |
| `check` | A read-only command. If it fails, the page becomes suspect. A check runs on a machine only after that machine approved it. |
| `verified` | When the agent last confirmed the page is still true. |

Every page ends with a Sources section. It says where the fact came from,
so a later session can check it. `memory write` refuses a body without
one.

A check written on this machine is approved here when it is written. A
check that arrived with a clone runs only after the agent asks you and
runs `memory approve` for that page, so a page from someone else cannot
run a command on your machine unasked.

URLs in `refs` are never contacted by search. The agent checks them only
when you say it may. It asks first, and Claude Code prompts you to
approve the command. A URL that answers "gone" makes the page suspect. A
URL that does not answer adds a glance note.

The kind sets an age. An `environment` page is old after 30 days, a
`procedure` after 90, a `finding` after 180. A `decision` never gets
old. When a page is older than that and nobody has confirmed it, search
adds a "glance" note next to it. The note means "this might be out of
date, look before you rely on it". The note is only a nudge. A page
becomes suspect only when a file it cites changed, its check command
failed, or the agent found it to be wrong.

`index.md` is the one page the agent does not write: its top half is
yours, its bottom half is a generated topic list.

## How search ranks

Each query runs a string and a semantic search and the wrapper merges the
results.

Semantic search matches meaning. The query "why does install fail on a
mac" finds the page about a missing wheel. The two share no words.
Semantic search needs an embedding model, `nomic-embed-text`. Ollama
serves the model on this machine or on a host you can reach. Semantic
search is weak on exact identifiers such as "pysqlite3-binary" or
"I113".

String search matches exact text. The wrapper takes the important words
from your query. It looks for them in the name, title, summary, and body
of each page. String search needs no model and no index. It finds
identifiers. It does not find paraphrase.

The wrapper merges the two result lists. Pages that both searches found
come first. Then come the other semantic results, nearest first. Then
come the pages that only string search found. Each line shows which
search found the page:

```
pysqlite3-install-override.md: Why memoryfield-tool needs a uv overrides file ... (distance 0.226; via semantic, install, pysqlite3-binary)
```

Semantic search answers questions. String search finds identifiers. A
page that both searches found is the page to trust.

### Without ollama

Some machines cannot run or reach ollama. On such a machine, tell the
agent to use string search. Then only string search runs. The agent
searches for the words a page contains, not for the question. It tells
you when it finds nothing. Memory works, but not as well.

### The semantic index

Semantic search reads an index. memoryfield-tool builds the index from the
pages and keeps it in the cache directory of the machine. The index is not
in the repository. The wrapper updates the index after each write. On a
fresh clone, the wrapper builds the index again. You can delete the index
at any time and lose nothing. The pages in `.memory/` are the only source
of truth.
