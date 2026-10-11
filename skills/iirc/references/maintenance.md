# Maintenance

Follow this when the creator runs `/iirc run-maintenance` or
`/iirc run-maintenance --unattended`, or says yes after you suggested
it. `iirc run-maintenance` does the safe part on its own: it commits
each store's loose files, syncs the remote stores, embeds pages with
no vectors, and lists the rest. You then work through that list with
the creator. The run is a clean sequence of commits: each store starts
from a commit, and every change after it is a commit of its own, which
`iirc write`, `iirc delete`, and `iirc verify` already make.

The plain form asks the creator before each change. The unattended
form asks once, at the start, then runs to the end with no question.

## 1. Run it

```
iirc run-maintenance
```

Its first line names each store's starting commit; the `undo STORE:`
lines under it hold the command that reverts the run's iirc commits in
that store and leaves the creator's own commits alone. It ends with
`Left to decide:` and one line per kind of item, or with
`Nothing is left to decide.`

Tell the creator the starting commits and that the undo commands are
in the summary at the end. When nothing is left, say so, give the undo
commands, and stop.

The unattended form shows its plan before the run, in step 2. Run
`iirc run-maintenance` first all the same, since the plan names the
starting commits.

## 2. Unattended: one yes

Skip this step in the plain form.

Tell the creator in a few lines what the unattended run does without
asking:

- `iirc doctor --fix` for setup failures, which may install
  prerequisites such as memoryfield-tool or ollama
- verify, rewrite, or delete each suspect page, by your judgement of
  the page and the cited diff
- merge or link each near-duplicate pair
- apply each audit fix
- when 10 or more sessions wait, a full tuning pass by
  `references/tune.md`, with a threshold change only when the
  evaluation had enough judged pairs and the change improves its
  criterion

And what it leaves for the creator: approving a check command that
came with a clone, and contacting URL refs. Name each store's starting
commit and its undo command. Ask for one yes. On yes, run steps 3 to
9, where this yes stands in for each yes they ask for. On no, run the
plain form.

## 3. Setup failures

The report lists each failed check with its fix. Offer
`iirc doctor --fix` and run it on the creator's yes. A failure with a
fix doctor cannot apply, such as a missing `.claude/settings.json`,
goes to the creator with the fix the report names.

Done when the creator has said yes or no to each fix and doctor ran
after each yes.

## 4. Checks not approved on this machine

Each line names a page and its check command. For each one, show the
creator the exact command and ask. On yes, run
`iirc approve-page-check PAGE`; Claude Code asks them to approve the
command too. Then treat the page as any suspect page if the check
fails.

Unattended: approve nothing. Keep each command for the summary.

## 5. Suspect pages

For each suspect page, read it with `iirc read`, then read the diff of
each cited file since the cited commit. Then do one of three things,
on the creator's yes: `iirc verify PAGE` when the page still holds,
`iirc write` with the corrected text when part of it is wrong, or
`iirc delete PAGE` when it no longer holds.

Done when each suspect page is verified, rewritten, or deleted, or the
creator declined.

## 6. Near-duplicate pairs

For each pair, read both pages. When they hold one finding, merge them
into one page with `iirc write` and delete the other. When they hold
two findings of different kinds, such as a decision and the procedure
that carries it out, keep both and link one to the other with
`[[name]]`; the pair then stops counting. Each on the creator's yes.

## 7. Audit findings

Each line reads `PAGE: CHECK: what; fix`. Propose each fix with its
line and apply it on the creator's yes, with `iirc write` or
`iirc delete`. Then run `iirc audit-page-findability PAGE` on that page.

## 8. URL refs

The report offers this at most about once a month, and only when pages
cite URLs. Tell the creator which URLs `iirc find-suspect-pages --network`
will contact, from the pages' `refs`, and ask. On yes, ask them to run
it or to allow it with `IIRC_ALLOW_NETWORK=1`; the command refuses
otherwise. Treat each failing URL as a suspect page, by step 5.

Unattended: contact nothing. Keep the URLs for the summary.

## 9. Tuning

When the report says 10 or more sessions wait, offer
`/iirc tune-suggestions` and say it is long. Start it only on the
creator's word; it follows `references/tune.md`.

Unattended: run the full pass by `references/tune.md`. Commit a
threshold change to `.claude/iirc.toml` with a message that starts
`iirc: `, and give its sha in the summary: the undo lines cover the
store paths, and this file sits outside them.

## 10. Summary

End with a short summary: what changed, one line per kind of item, and
each store's undo command from step 1.

Unattended: also say, as plain words, which steps you skipped and why,
with the exact command for each, so the creator can run it later:

- approvals: `/iirc run-maintenance`, or `iirc approve-page-check PAGE`
  for each page, with its command
- URL refs: `iirc find-suspect-pages --network`, with the URLs it
  contacts

The summary is the last thing the run prints. It asks no question and
waits for nothing.
