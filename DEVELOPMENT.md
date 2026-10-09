# Developing iirc

## Layout

```
.claude-plugin/plugin.json   manifest; no version field, the commit is the version
bin/iirc                   the command; Python under uv run --script, PyYAML inline
iirc.pin                   memoryfield-tool commit and the embedding model
skills/iirc/SKILL.md       the agent's rules
hooks/hooks.json             SessionStart and SubagentStart: doctor --brief --hook; UserPromptSubmit and PostToolUse(Failure): recall; Stop: nudge; PreToolUse (Bash, Read): guard
tests/                       pytest; nothing needs ollama or memoryfield-tool
```

`bin/iirc` is a thin layer over memoryfield-tool, used as published at the
commit in `iirc.pin`. It generates the tool's per-machine config from the
repository location, guards the embedding host with a two-second probe,
reindexes synchronously after writes, filters `index.md` from results, and
computes suspicion. It never reimplements storage, search, or indexing.

## Run it from a checkout

```
claude --plugin-dir /path/to/dokidlc-iirc
```

Outside a session:

```
CLAUDE_PROJECT_DIR=/path/to/repo OLLAMA_HOST=127.0.0.1:11434 bin/iirc search "query"
```

## Search

`hybrid_search()` fuses `search_json()` (the tool's semantic search) with
`string_search()` (a local exact-text loop over name, title, summary, and
body). Ranking: both paths, then semantic by distance, then string-only
by term count with title hits ahead of body hits. In string mode only the
local loop runs and the tool is never called for search.

## Search mode and embedding host

Semantic search is on unless `semantic = false` in the setup file.
`OLLAMA_HOST` exported always means semantic. In string mode the wrapper points the tool at
a closed port so its client fails at once and falls back, and it skips
reindexing. The host, when semantic is on, is resolved in this order: `OLLAMA_HOST` in the environment, then
`embedding_host` in `~/.config/dokidlc-iirc/config.toml` (written by
`iirc setup`; `XDG_CONFIG_HOME` is honoured), then `127.0.0.1:11434`.
`doctor` names the source. `doctor --fix` installs ollama only for a local
host.

## Tests

```
uv run --quiet pytest
claude plugin validate .
claude plugin test .        # hooks/register.test.ts, the drawn rows
```

CI runs both on ubuntu and macos.

## The tool pin

memoryfield-tool is installed from a git commit because its PyPI release
lags main, and with an overrides file that drops `pysqlite3-binary`, which
ships only Linux x86_64 wheels while the tool falls back to stdlib sqlite3.
`iirc doctor --fix` does both. Every command that runs the tool checks its
installed commit against the pin first and refuses a mismatch with the fix
named. To bump: change `tool_rev` in
`iirc.pin`, run `iirc doctor --fix`, run the tests, commit.

## Format and compatibility

The generated half of `.iirc/index.md` carries `iirc format N` and the
plugin commit. `FORMAT` in `bin/iirc` is what the code understands. Older
data is migrated by regenerating the index; newer data is refused with
exit 2. Bump `FORMAT` only with a migration.

`iirc migrate` (`cmd_migrate`, `old_layout`) moves a repository and a
machine from the memory plugin's names. `doctor --brief` prints
`MIGRATION_LINE` while `old_layout()` finds anything, and `register.tsx`
shows it as a red `● iirc: needs migration` under the prompt. Remove both
once no repository uses the old layout.

## Release

Commit to main, let CI pass, then change the `sha` for `iirc` in
`dokidlc-plugins/.claude-plugin/marketplace.json`.

## Hook channels

Only SessionStart and UserPromptSubmit inject plain stdout. SubagentStart,
PostToolUse, PostToolUseFailure, and Stop need
`hookSpecificOutput.additionalContext`; PreCompact has no context channel
at all, so the compaction reminder rides on SessionStart with
`source: compact`. `doctor --brief --hook` reads `hook_event_name` from
stdin to pick the framing; without `--hook` the command never touches
stdin, because a script that inherits an open pipe would otherwise wait
for an EOF that never comes. Host probes are cached in the state dir for ten
minutes so a dead host costs one probe, not one per prompt.

## Tuning files

`iirc tune gather` writes `tune/SESSION.json` in the state dir, one per
session, from the log, the `eval-*.jsonl` candidate rows, the
`prompts/SESSION.jsonl` excerpts, and the transcript when Claude Code
still keeps it. A recall logged before `recall_id` existed joins its
prompt by time, so its prompt can be the wrong one when prompts queue.
`iirc tune judge` appends to `tune/judgments.jsonl`; the last line for a
session, recall, and page wins. `iirc tune done` logs a `tuned` row whose
`tuned` field names the session, so the row's own `session` stays the
one that tuned. `gate()` is the one gate that both recall and `iirc tune
sweep` call.

## Approved checks

`write` and `approve` record the sha256 of a page's check in
`~/.local/state/dokidlc-iirc/checks.json`. `doubt` runs only approved
checks and lists the rest; `verify` refuses a page whose check is not
approved or not read-only in form. Only `approve` and `write` grant
approval, because those are the two places the creator was asked or the
command came from this machine's own agent. The PreToolUse guard asks for
`iirc approve` and `iirc doubt --network`, and the wrapper refuses
`--network` off a terminal unless `IIRC_ALLOW_NETWORK=1` is set. The
same guard, registered for Bash and for Read, denies a raw read of a
page file, by `cat`, `head`, `sed`, `tail`, `less`, or `more` in a command
or by the Read tool, and names `iirc read` in the reason, because a page
read raw arrives without its trust markers and the fix commands at its
end. It denies rather than asks because the reason reaches the agent only
on a deny; an ask the creator refuses shows the agent nothing, and a
reviewer subagent on 2026-09-21 retried the cat and then used Read. The
reason ends with the way out when `iirc read` itself is broken:
`iirc doctor --fix`.

The wrapper never writes through a symlink: `regenerate_index` and `init`
refuse one, so a cloned repository cannot point `.iirc/index.md` or
`CLAUDE.md` at another file.

`/iirc demo` draws the `/iirc` card with sample numbers (142 pages, a 74%
hit rate) and reads nothing. Use it for the README screenshot, so the image
shows the design rather than one session's counts.
