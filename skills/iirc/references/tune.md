# Tuning suggestions

Follow this when the creator says tune, or runs `/iirc tune-suggestions`.
Tuning fixes the pages search shows badly, judges what the suggestion
hook suggested against what the session needed, then proposes page fixes
and, when the numbers allow, threshold changes. The creator decides
every change. Plugin code is out of scope: a finding that needs a code
change goes in the report for the plugin's developer.

## 1. Gather

```
iirc tune-suggestions gather-suggestion-data [--days N] [--session ID]
```

It writes one evidence file per session to the path it prints and
skips sessions already tuned. Done when it has printed its files, or
said there is no session to gather; in that case tell the creator and
stop.

## 2. Audit

Fix the pages before you judge them. Thresholds tuned while a page is
badly written bend to make up for that page.

```
iirc audit-page-findability
```

It prints one line per finding, `PAGE: CHECK: what; fix`, then a count.
The pages named there are the flagged pages. No threshold fixes a
flagged page; its text has to change. For each flagged page:

1. Write two prompts a future session would plausibly type when it needs
   this page, using none of the title's words.
2. Run `iirc search "PROMPT"` for each, and note the page's rank.
3. Choose one fix: rewrite, split, merge, or delete. A page in the top
   three for both prompts takes the fix its audit line names. A page outside
   the top three needs a rewrite in the words of the prompts, by the
   "Write for the search" rules in SKILL.md. A page that holds two
   findings needs a split, one that repeats another page needs a merge,
   and one whose fact no longer holds needs a delete.
4. Propose the fix to the creator with the audit line, the two prompts,
   and their ranks. On their yes, apply it with `iirc write` or
   `iirc delete`, then run `iirc audit-page-findability PAGE` on that page.

Done when every flagged page has a fix the creator accepted or declined,
and each accepted fix has passed its own `iirc audit-page-findability PAGE`.

## 3. Judge

Read each evidence file in full. Its first line holds the session and
its conditions; each later line is one suggestion line. A file can run to
hundreds of kilobytes, so read twenty lines at a time with
`sed -n '2,21p' FILE`, which never cuts a long line. Each entry holds
the prompt (or, for `via: failure`, the failed command, its error, and
the subagent that ran it), the candidates to judge with their distance
and `verdict`, and the outcome:
`read_turns_later` per suggested page, `next_tools`, `searches`, and
`read_unsuggested`.

Judge every page in `candidates` and every page in `read_unsuggested`.
Read each page with `iirc read --for-tune PAGE` before you judge it; a
plain `iirc read` counts as this session's own use of the page. Label
one pair at a time:

- `relevant`: the page would have helped with that prompt. Decide from
  the prompt and from what the agent did next, not from the score.
- `noise`: the page has nothing the agent needed for that prompt.
- `unsure`: the evidence cannot decide it. The prompt is missing, or it
  depends on context the file does not hold.

The match percentage does not separate relevant from noise: in a
68-prompt replay both ranged 66 to 74 percent. Judge the content.

Record the labels, one JSON object per line. The entry's key is
`recall_id` when the entry has one, else `ts`:

```
printf '%s\n' \
  '{"session": "S", "recall_id": "R", "page": "name.md", "label": "noise", "note": "why, in one sentence"}' \
  | iirc tune-suggestions record-relevance-judgments
```

It records all lines or none, and names each bad line, including a page
the entry does not list. A later judgment of the same session, entry,
and page replaces the earlier one. Done when every page in
`candidates` and `read_unsuggested` in every file has a recorded label.

## 4. Evaluate the thresholds

```
iirc tune-suggestions evaluate-suggestion-thresholds
```

It prints the gate's counts on the judged pairs for the current
thresholds and for a grid of others, with the criterion it ranks by.
When it says there are too few judged pairs, propose no threshold change.

## 5. Propose

Present the proposals to the creator. Give each one its evidence: the
prompt excerpt, the page, the distance, and what the agent did.

Page fixes:

- A page often suggested and judged noise: narrow the page. Semantic
  search embeds the whole page file, frontmatter and body, so a summary
  edit alone moves its distance little. Split off the part that matches
  the unrelated prompts into its own page, cut it, merge the page into
  the one it competes with, or delete it.
- A relevant page that the gate refused or search never found: add the
  missing identifier to its summary.
- A prompt where the agent investigated and no page was suggested: write
  a page with what the investigation established.

Threshold changes: only when the evaluation had enough judged pairs and
the change improves its criterion. Name the command, such as
`iirc set-suggestion-threshold semantic_only 0.30`, and the counts before
and after. The thresholds belong to the embedding model the evaluation
ran with: `iirc show-suggestion-thresholds` prints its table, such as
`[suggestions.nomic-embed-text]`, and its range.

For the plugin's developer, under a heading that says so: each pattern
that only a code change fixes, with its counts and the session ids.
Leave prompt text out of this section; it may hold private material.

Done when every proposal is in front of the creator with its evidence.

## 6. Apply

Apply each change only on the creator's yes: page fixes with
`iirc write` and `iirc delete`, threshold changes with
`iirc set-suggestion-threshold`. It edits the active model's
`[suggestions.MODEL-ID]` table in `.claude/iirc.toml`; show the creator
the diff and commit it on their word.

Then mark each session you judged:

```
iirc tune-suggestions mark-session-tuned SESSION
```

Done when every gathered session is marked.
