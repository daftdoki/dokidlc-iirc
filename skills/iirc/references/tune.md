# Tuning recall

Follow this when the creator says tune, or runs `/iirc tune`. Tuning
judges what recall suggested against what the session needed, then
proposes page fixes and, when the numbers allow, knob changes. The
creator decides every change. Plugin code is out of scope: a finding
that needs a code change goes in the report for the plugin's developer.

## 1. Gather

```
iirc tune gather [--days N] [--session ID]
```

It writes one evidence file per session to the path it prints and
skips sessions already tuned. Done when it has printed its files, or
said there is no session to gather; in that case tell the creator and
stop.

## 2. Judge

Read each evidence file in full. Its first line holds the session and
its conditions; each later line is one recall. A file can run to
hundreds of kilobytes, so read twenty lines at a time with
`sed -n '2,21p' FILE`, which never cuts a long line. Each recall holds
the prompt (or, for `via: failure`, the failed command, its error, and
the subagent that ran it), the suggested pages, the candidates worth
judging with their distance and `verdict`, and the outcome:
`read_turns_later` per suggested page, `next_tools`, `searches`, and
`read_unsuggested`.

Judge every page in `candidates` and every page in `read_unsuggested`.
Read each page with `iirc read` before you judge it. Label one pair at
a time:

- `relevant`: the page would have helped with that prompt. Decide from
  the prompt and from what the agent did next, not from the score.
- `noise`: the page has nothing the agent needed for that prompt.
- `unsure`: the evidence cannot decide it. The prompt is missing, or it
  depends on context the file does not hold.

The match percentage does not separate relevant from noise: in a
68-prompt replay both ranged 66 to 74 percent. Judge the content.

Record the labels, one JSON object per line. The recall key is
`recall_id` when the entry has one, else `ts`:

```
printf '%s\n' \
  '{"session": "S", "recall_id": "R", "page": "name.md", "label": "noise", "note": "why, in one sentence"}' \
  | iirc tune judge
```

It records all lines or none, and names each bad line. A later judgment
of the same session, recall, and page replaces the earlier one. Done
when every marked candidate and every unsuggested read page in every
file has a recorded label.

## 3. Sweep

```
iirc tune sweep
```

It prints the gate's counts on the judged pairs for the current knobs
and for a grid of others, with the criterion it ranks by. When it says
there are too few judged pairs, propose no knob change.

## 4. Propose

Present the proposals to the creator. Give each one its evidence: the
prompt excerpt, the page, the distance, and what the agent did.

Page fixes:

- A page often suggested and judged noise: narrow its summary, split
  it, merge it into the page it competes with, or delete it.
- A relevant page that recall refused or never found: add the missing
  identifier to its summary.
- A prompt where the agent investigated and recall found nothing: write
  a page with what the investigation established.

Knob changes: only when the sweep had enough judged pairs and the change
improves its criterion. Name the command, such as
`iirc knobs set semantic_only 0.30`, and the counts before and after.

For the plugin's developer, under a heading that says so: each pattern
that only a code change fixes, with its counts and the session ids.
Leave prompt text out of this section; it may hold private material.

Done when every proposal is in front of the creator with its evidence.

## 5. Apply

Apply each change only on the creator's yes: page fixes with
`iirc write` and `iirc delete`, knob changes with `iirc knobs set`.
`knobs set` edits `.claude/iirc.toml`; show the creator the diff and
commit it on their word.

Then mark each session you judged:

```
iirc tune done SESSION
```

Done when every gathered session is marked.
