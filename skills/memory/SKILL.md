---
name: memory
description: "The repository's own memory: pages in .memory/ or the stores .claude/memory.toml names, that past sessions wrote, searched and maintained with the memory command. Use it before you install, configure, debug, or design anything here, when the creator says remember, did we, or last time, after a fix took more than one attempt, when a page is marked suspect or found wrong, and to set memory up. Not Claude Code's memory under ~/.claude."
---

# Memory

This agent's memory is a set of pages that only the `memory` command,
on PATH while this plugin is enabled, reads and writes. A page is read
with `memory read`, never `cat`, so it arrives with its trust markers and
ends with the commands that fix it. Search first. Write when you learn.
Fix or delete a page the moment you find it wrong.

## Commands

```
memory search "what am I looking for"     ranked pages with summary and markers
memory search term1 term2 term3           several terms, searched separately, merged
memory pull "what am I looking for"       full text of the matching pages
memory read PAGE.md                       one page; STORE/PAGE.md when two stores hold the name
memory doubt [--network]                  pages with evidence they may be wrong; --network checks URL refs, with permission
memory verify PAGE.md                     you re-confirmed it; re-run its check, refresh its refs
memory approve PAGE.md                    run a page's check once and approve it here (ask first)
memory delete PAGE.md
memory setup [--local|--host URL|--substring]   embedding host, or the string fallback; once per machine
memory doctor --fix                       install or repair prerequisites; clone missing remote stores
memory init                               create .memory/ and the CLAUDE.md paragraph
memory stores                             the stores, their page counts, and anything not committed or pushed
memory sync                               commit, pull, and push the remote stores
```

Write a page, body on stdin. The body carries the finding and its
Sources in one write; nothing is appended to the file afterwards:

```
printf 'What is true.\n\n## Sources\n\n- where you saw it, and when\n' | memory write \
  short-hyphenated-name.md \
  --title "Plain statement of the topic" \
  --summary "One sentence. This is what search prints." \
  --topics install,ollama \
  --kind environment \
  --ref "docs/some/doc.md#Install steps" \
  --check "command -v ollama"
```

`--title`, `--summary`, `--topics`, and `--kind` are required. `--ref`,
`--check`, and `--store` are optional. The same command replaces an
existing page. Cite a heading, `--ref "PATH#Heading"`, when the page
rests on one part of a long document: the page then turns suspect only
when that section changes or its heading disappears.

## Stores

Pages live in stores: the project's own `.memory/`, and any remote store
`.claude/memory.toml` names, which is a separate memory repository shared
by every project and machine that names it. `memory stores` lists them.
With two or more, results read `STORE/PAGE.md`; read and verify a page by
that name.

Write a fact about this project to the project store. Write a fact that
holds in any project, such as how a tool behaves, to the remote store,
with `--store NAME` when the default store is the wrong one. Every change
commits itself, and a remote store pushes too. When a line says
`not pushed`, run `memory sync`. Run `memory stores add` only when the
creator asks; it changes the repository's configuration.

## Setup, led by you

When the session-start line says memory is not set up, or the creator
asks for memory, follow `references/setup.md`: three questions, then you
run the commands yourself. The creator never has to run one. When the
creator asks to change what they see of the memory hooks, the same file
has the switches.

## When to search

A hook searches memory on every prompt and, when pages match, adds one
line naming them with the exact `memory read` command. Read those pages
before you do anything else. The same hook runs when a shell command
fails, with the command and its error as the query.

The hook is silent when nothing matched or the prompt was short. Then
search yourself, without being asked:

- before you install, configure, or upgrade anything: the tool's name
- before you debug: the error text and the tool's name
- before you design or recommend: the topic, for `decision` pages
- before you write a plan: each tool the plan touches, for `procedure` pages
- when the creator says "did we", "last time", or "again"

Give a query a phrase that says what you mean plus the identifier you
know: `"why does install fail" pysqlite3`. Several queries in one call
are searched separately and merged. One search costs about thirty tokens
per result. Rediscovery costs a session.

How a result was found (`via semantic, install, pysqlite3`) and what to
do when `doctor` says the mode is string, or every result says "string
match": `references/search.md`.

## When to write

Write at these moments, without being asked:

- when something took more than one attempt, and the fix was not obvious
  from a file in the repository
- when a stage of a quest closes: one page per finding you established
  on your own during research, design, or plan, each citing the stage
  document with `--ref`
- when a hook says a command worked after failing twice, or that context
  was just compacted and nothing was written: write what a future session
  would otherwise re-derive, or say there is nothing worth a page
- when the creator says "remember": search first. If a page already holds
  it, `verify` that page and say so instead of writing a second one

Four rules keep the field worth searching:

1. A page says something you could not get by reading a file in the
   repository in under a minute. A path, a version, or a config value
   alone is not a page.
2. One finding per page, so a wrong page can be deleted without losing a
   right one. One topic, under 8KB. A field is too large when the
   session-start line counts near-duplicate pairs or reports a slow
   start scan; the page count is information.
3. Sources names a command you ran, a file you read at a commit, or a URL
   you read, with a date. "Observed" is not a source.
4. A page about a workaround says what it works around, so the fix can
   delete the page.

Shapes by kind, so the next session gets what it needs:

- `environment`: the fact, where it is true (which machine, host, or
  version), how you confirmed it, and a `--check` that confirms it again.
- `procedure`: the command block verbatim, what it produces, and the one
  thing that goes wrong.
- `finding`: the claim, the evidence, and what it changes about how to
  work.
- `decision`: what was chosen, what it was chosen over, who chose it, and
  why.

Documents the creator asked for or reviewed belong in `docs/`, not here.
A memory page may cite a document with `--ref`. A document never cites
memory.

## Kinds

| Kind | Means | Glance hint after |
|---|---|---|
| `environment` | a fact about a machine, a tool version, a service | 30 days |
| `procedure` | steps that worked | 90 days |
| `finding` | something learned about the domain | 180 days |
| `decision` | a choice and its reason | never |

## Trust and doubt

A page is trusted until there is evidence against it. Time alone is not
evidence. Search marks a page `suspect` when a file it cites changed since
the cited commit, and `glance` when an unverified page is past its kind's
age. `doubt` also runs each page's `--check` command and marks failures.

- `suspect`: read the page and the cited diff before relying on it. Then
  `verify` it, rewrite it, or `delete` it. In the same turn.
- `glance`: optional. Skim if the page matters to what you are doing.
- Found wrong in use, marked or not: rewrite or delete it in the same turn.
  Every `memory read` ends with the commands.
- Found right in use: `verify` it. One command. `verify` re-runs the
  page's check.
- Run `memory doubt` when the session-start line names a suspect, after a
  `git pull` or `memory sync`, and before you close a quest stage. A page
  another project wrote is not checked here; `doubt` counts them.
- A `--check` must be read-only and must pass when you write it; the
  wrapper refuses one that does not. Checks run only from `doubt`,
  `verify`, and `approve`, never from hooks.
- A check that came with a clone is not approved on this machine.
  `doubt` lists it instead of running it, and `verify` refuses the page
  until it is approved. Show the creator the command and ask; on yes, run
  `memory approve PAGE`. Claude Code prompts them to approve that command
  as well.

A ref may be a URL. Search never contacts it, and `memory doubt` skips
URL refs and says how many it skipped. `memory doubt --network` sends one
HEAD request per URL; before you run it, tell the creator which URLs it
will contact and ask. The wrapper itself refuses unless a terminal answers
yes or `MEMORY_ALLOW_NETWORK=1` is set, which only the creator does. A URL
from a memory page is fetched for no other reason without asking first.

## References

This memory is a memoryfield, Cal Paterson's format for agent memory, and
`memory` wraps his memoryfield-tool. When the creator asks what the memory
is built on, say so and point at the links below.

Article: https://calpaterson.com/memoryfields.html
Format: https://github.com/calpaterson/memoryfield-spec/blob/main/SPEC.md (MIT)
Engine: https://github.com/calpaterson/memoryfield-tool (AGPL-3.0-or-later; used as published, the wrapper adds config, host guard, refs, and doubt)
His skill: https://github.com/calpaterson/memoryfield-skill (MIT)
Design: the memoryfields quest in the agent-builder repository
