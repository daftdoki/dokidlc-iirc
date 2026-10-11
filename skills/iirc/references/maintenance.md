# Maintenance

Follow this when the creator runs `/iirc run-maintenance` or
`/iirc run-maintenance --unattended`, or says yes after you suggested
it. `iirc run-maintenance` does the safe part on its own, before any
yes in either mode: it commits each store's loose files, pulls and
pushes each remote store, and runs the page checks already approved on
this machine. It changes no page's text and lists the rest; you then
work through that list. Make each change with
`iirc write`, `iirc delete`, or `iirc verify`, so each change is a
commit of its own.

The plain form asks the creator before each change. The unattended
form asks once, before anything runs, then runs to the end with no
question.

## 1. Unattended: one yes first

Skip this step in the plain form.

Before you run anything, tell the creator in a few lines what the
unattended run does without asking:

- `iirc run-maintenance` itself: commit each store's loose files, pull
  and push each remote store, and run the page checks already approved
  on this machine
- `iirc doctor --fix` for setup failures, which may install
  prerequisites such as memoryfield-tool or ollama
- verify, rewrite, or delete each suspect page, by your judgement of
  the page and the cited diff
- merge or link each near-duplicate pair
- apply each audit fix
- a full tuning pass by `references/tune.md` when the report offers
  tuning, with a threshold change only when tune.md allows one

What it leaves for the creator: approving a check command that came
with a clone, and contacting URL refs. Each store gets a starting
commit and an undo command, which you name once the run starts.

Ask for one yes. On yes, run steps 2 to 9, and let this yes stand for
each yes they name. On no, run the plain form.

## 2. Run it

```
iirc run-maintenance
```

Its first line names each store's starting commit, and the
`undo STORE:` lines under it hold the command that reverts the run's
iirc commits in that store. Tell the creator the starting commits now.
The report ends with `Left to decide:` and one line per kind of item,
or with `Nothing is left to decide.`; when nothing is left, go to step
9.

## 3. Setup failures

Offer `iirc doctor --fix` for the failed checks, and run it on the
creator's yes. A failure doctor cannot fix, such as a missing
`.claude/settings.json`, goes to the creator with the fix the report
names.

## 4. Checks not approved on this machine

For each page the report names, show the creator the exact check
command and ask. On yes, run `iirc approve-page-check PAGE`; Claude Code
asks them to approve the command too. A check that then fails makes
the page suspect: handle it in step 5.

Unattended: approve nothing. Keep each page and command for the
summary.

## 5. Suspect pages

For each suspect page, read it with `iirc read` and read the diff of
each cited file since the cited commit. Then, on the creator's yes:
`iirc verify PAGE` when the page still holds, `iirc write` with the
corrected text when part of it is wrong, or `iirc delete PAGE` when it
no longer holds.

Done when each suspect page is verified, rewritten, or deleted, or the
creator declined.

## 6. Near-duplicate pairs

For each pair, read both pages and apply rule 2 of "When to write" in
SKILL.md: merge or link. Each on the creator's yes.

## 7. Audit findings

Each line reads `PAGE: CHECK: what; fix`. Propose each fix with its
line and apply it on the creator's yes. Then run
`iirc audit-page-findability PAGE` on that page.

## 8. Offers: URL refs and tuning

When the report offers a URL check, tell the creator which URLs
`iirc find-suspect-pages --network` will contact, from the pages'
`refs`, and ask. On yes, ask them to run it or to allow it with
`IIRC_ALLOW_NETWORK=1`. Treat each failing URL as a suspect page, by
step 5. Unattended: contact nothing, and keep the URLs for the summary.

When the report offers tuning, offer `/iirc tune-suggestions` and say
it is long. Start it only on the creator's word. Unattended: run the
full pass by `references/tune.md`, and commit a threshold change to
`.claude/iirc.toml` with a message that starts `iirc: `. That file is
outside the store paths, so give its sha in the summary.

## 9. Summary

End with a short summary: what changed, one line per kind of item, and
each store's undo command from step 2.

Unattended: also name each step you skipped, why, and the exact command
to run it later:

- approvals: `/iirc run-maintenance`, or `iirc approve-page-check PAGE`
  for each page, with its command
- URL refs: `iirc find-suspect-pages --network`, with the URLs it
  contacts

The summary is plain text, the last thing the run prints; the creator
reads it whenever they return.
