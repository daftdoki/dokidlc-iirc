# Recommendations for `dokidlc-skill-memory`: a review pass, not a dream cycle

Written 2026-09-19 for the creator to work from separately. It applies the
findings of the [agent memory systems report](https://github.com/daftdoki/research/tree/main/agent-memory-systems-and-dreaming) in the research
repository to this plugin
at `e56235f`, using the two fields that have run it for about two weeks: `daftdoki/agent-neckbeard` (60 pages, 170 commits
read) and `daftdoki/agent-builder` (45 pages, 315 commits read), plus the
completed quest `2609020128-mf-evaluate-memoryfields-as-the-memory-syst` in
agent-builder, whose `usage-analysis.md`, `recall-questions.md` and
`verdict.md` supply the log-derived numbers cited below. Everything else was
computed from the fields and their git history; the method is in the
[appendix](#appendix-how-the-numbers-were-computed).

## Summary

The plugin already has the half of a consolidation pass that the research
found easy — the **gate** — and has it in a better form than the shipping
dream cycles, because its signals are evidence of wrongness (a cited file
changed, a check failed) rather than popularity. It deliberately lacks the
half the research found unsolved — the **writer** — because the wrapper never
calls a model. Both facts should survive whatever gets built.

What the two fields' history adds is that the consolidation pass **already
exists as a practice**: three hand-run sweeps in fifteen days, each after a
bulk change to cited files, each executed by the agent and recorded as one
commit. The recommendation is to give that practice a command, a trigger and
a cap, and to leave synthesis where it is.

In priority order:

1. **Add `memory review`, a read-only pass** that prints the field's rot
   candidates grouped by cause, and let the agent act with the existing
   `write`, `verify` and `delete`. [Section 4](#4-memory-review-the-read-only-pass).
2. **Trigger it on events, not the clock**: a burst of suspects from one
   commit, or N pages written since the last review. The three sweeps that
   already happened were all event-triggered. [Section 4.3](#43-trigger).
3. **Cap destruction per session**, with a formula that scales sub-linearly
   with field size and a creator override. The number is an open decision;
   a recommendation and the options are in [Section 5](#5-the-blast-radius-cap-an-open-decision).
4. **Close the coverage gap**: 45% of neckbeard's pages carry neither a ref
   nor a check, so no signal can ever flag them. The review pass should name
   them; the skill should ask for one or the other at write time. [Section 3.3](#33-suspicion-coverage).
5. **Ship the "over N pages" session-start line** that the first usage
   review proposed and that never landed. Neckbeard is past 50; agent-builder is at 45.
6. **Do not add** a model call to the wrapper, automatic merging, or decay
   tiers. The evidence is in [Section 6](#6-what-not-to-build-and-why).

## 1. What the research says that applies here

The full argument is in the [report](https://github.com/daftdoki/research/tree/main/agent-memory-systems-and-dreaming), with its sources tagged by
whether the primary document was read. The parts that bear on this plugin:

| Finding | Source | Consequence for the plugin |
|---|---|---|
| Selection is not synthesis. A scorer that decides *which* entries survive, with no step deciding *what* they say, promotes verbatim noise. | OpenClaw issue #67363; Auto-Dreamer Appendix I, where a baseline's "consolidation step fires nine times but retires no active entries" and its bank holds 49 paraphrases of one instruction | Any pass the wrapper runs must be read-only. The writer is the agent, in a session, with the diff visible. |
| Updating is the worst-measured memory operation: best 65% correct, four of six production systems under 26%. | HaluMem (arXiv 2511.03506) | Never put a rewrite step in an unattended pass. `write --force` is a full replacement; count it as destruction in the cap. |
| Consolidation's demonstrated win is compression at equal accuracy; its effect on recall is inside the noise everywhere it was measured except the trained-on domain. | Auto-Dreamer Table 1, Appendix H bootstrap CIs, Appendix I case study (48/96 both, 24.5x smaller bank) | Expect a review pass to make the field smaller and cleaner, not to make recall better. Measure it that way. |
| The four shipping dream cycles disagree on trigger; only one is nightly. Letta fires on step count or a compaction event. | First-party docs: OpenClaw, Anthropic Managed Agents Dreams, Letta, OpenAI | Trigger on work done and on churn events, not on a schedule. |
| Copy-on-write removes the update problem instead of managing it. Anthropic's Dreams never modifies the input store; a human adopts or discards the output. | Anthropic Managed Agents Dreams docs | Git is already this. A review on a branch, merged by the creator, is the same design at zero cost. |
| A bounded loss per sweep is the one safety control every careful implementation has. | OpenClaw `maxPriorEntryLossFraction` 0.25; Letta backup-before-reorganise; Anthropic zero-by-construction | Add a per-session cap. |
| Frequency is the signal a poisoning attack exploits; injection succeeds 98.2% of the time and consolidation launders provenance. | MINJA (arXiv 2503.03704) | Recall counts are a display signal, never a promotion signal. Cloned pages' origin must be visible in the review. |
| Below ~150 conversations a full-context control arm wins on accuracy. | ConvoMem (arXiv 2511.10523) | The plugin's recall test (10/10 from memory alone) is the right kind of measurement. Keep running it as the field grows. |

## 2. What the fields' history shows

### 2.1 The day-two reset

Neckbeard's field was created on 2026-09-04 by importing 80 pages from the
old harness memory in seven batches (commits `4fe8083` through `11fafb5`).
The plugin log records that import as 155 writes over 78 pages, "several
pages written six times each." On 2026-09-05 the creator deliberately reset
the agent (commit `2dc8ee2`, "Reset the agent: wipe acquired memory and old
docs"): 79 deletions plus a re-initialised `index.md`, so that the trial
would run on what the agent learned in use rather than on what was carried
over. Every one of the 60 pages in the field today was written after that
reset, after a failure or a decision.

Two things follow, and one thing does not.

- The field that exists is a clean sample of in-use learning, and the
  recall test scored 10/10 on pages of that origin. That is the evidence for
  the plugin's own rule that memory holds what was learned, not what was
  built.
- The import is a measured example of what a bulk write pass looks like on
  this system: 155 writes for 78 pages, with rewrites of the same page up to
  six times in one session. Whatever a review pass costs, that is the shape
  to compare it against.
- The reset is **not** a judgement on the imported pages' quality. Nothing
  in the history says they were wrong; they were set aside on purpose. The
  argument against an automated writer rests on the research in Section 1,
  not on this event.

### 2.2 The sweeps that already happened

Edits to `.memory/` by day, split into frontmatter-only changes (a `verify`:
`verified` timestamp and refreshed refs) and body edits:

| Day | neckbeard A / M / D | of which M frontmatter-only | agent-builder A / M / D | of which M frontmatter-only |
|---|---|---|---|---|
| 09-01 | — | — | 9 / 9 / — | — |
| 09-04 | 80 / 21 / — | — | 8 / 39 / — | — |
| 09-05 | 30 / 13 / 79 | — | 12 / 17 / 1 | — |
| 09-06 | 3 / 3 / — | 0 of 2 | 1 / 3 / — | 1 of 3 |
| 09-07 | 7 / 2 / — | 0 of 2 | — | — |
| 09-11 | 13 / 30 / — | **16 of 30** | 10 / 11 / 1 | 0 of 11 |
| 09-12 | 2 / 12 / — | 0 of 12 | 2 / 3 / — | 0 of 3 |
| 09-13 | 5 / 17 / 1 | 2 of 17 | 5 / 9 / 3 | 3 of 9 |
| 09-19 | 1 / 24 / — | **17 of 24** | 5 / 52 / 1 | **29 of 52** |

Three sweeps stand out: neckbeard 09-11 and 09-19, and agent-builder 09-19,
whose commit reads *"Memory: suspect pass after the format 7 move; 13
verified, 5 rewritten, 1 deleted."* Each followed a bulk change to files the
pages cite — a questlog format bump, the quest-directory move, the chezmoi
rebuild. None ran on a schedule. This is Letta's compaction-event trigger,
arrived at independently, and it is the trigger `memory review` should
formalise.

### 2.3 Deletes are rare and small

Deletions across all of history: neckbeard 2 (excluding the reset),
agent-builder 5, the largest single commit removing 3
(`260a8ae`, "three stale pages deleted" after a grammar change). The reset
was the creator's own decision, not a sweep. This matters for the cap in Section 5: any floor
of three or more never bites in normal use; the cap exists for the
migration-scale session.

### 2.4 Growth

Neckbeard: 98 writes over 62 pages after the reset, in 24 logged sessions
across 7 active days — roughly four new pages per active day. At that rate
the field passes 150 pages within two months of use. Agent-builder writes in
33% of sessions (the questlog stage files already hold the record) against
neckbeard's 71%.

## 3. What a review pass would find today

All figures computed 2026-09-19 from the fields on disk and their history.

### 3.1 Scale

| | neckbeard | agent-builder |
|---|---|---|
| Pages (without `index.md`) | 60 | 45 |
| On disk | 256 KB | 192 KB |
| Kinds | 33 finding, 13 procedure, 11 decision, 3 environment | 25 finding, 10 procedure, 7 decision, 3 environment |
| Pages ever verified | 21 | 21 |
| Largest body | 5,076 B (`claude-session-name-and-color`) | 4,312 B (`project-settings-do-not-install-plugins`) |
| Pages over 3,000 B body | 4 | 1 |

### 3.2 Retrieval and cost, from the quest's log analysis

| | neckbeard | agent-builder |
|---|---|---|
| Sessions logged (09-05 to 09-19) | 24 | 39 |
| Recall lines on prompts, with a hit | 145 of 189 (77%) | 203 of 262 (77%) |
| Recall lines on failures, with a hit | 61 of 97 (63%) | 165 of 229 (72%) |
| Agent-run searches, with a hit | 72 of 81 | 90 of 90 |
| Page reads; of those, a page recall had named | 27; 22 | 75; 62 |
| Distinct pages recall named; never read in any session | 76; **56** | 43; 15 |
| Verify / delete / doubt commands | 39 / 2 / 20 | 10 / 5 / 12 |
| Recall output per session | ~13,991 chars (~3,500 tokens) | ~18,728 chars (~4,700 tokens) |
| Recall questions from memory alone | — | 10 of 10 right |

The "named, never read" row is the closest thing the log has to a dead-page
signal, and the analysis is right that it cannot separate "the summary
sufficed" from "the line was ignored." It is advisory input to a review, not
a deletion signal.

### 3.3 Suspicion coverage

The wrapper's `suspicion()` has two signals that can mark a page `suspect`:
a ref whose file changed, and a check that failed. A page with neither can
only ever be caught by the agent finding it wrong in use.

| | neckbeard | agent-builder |
|---|---|---|
| Pages with a ref | 23 | 33 |
| Pages with a check | 15 | 7 |
| Pages with **neither** | **27 (45%)** | 9 (20%) |
| Suspect now (ref changed) | 1 | 0 |
| Age-based `glance` ever fired | 0 | 0 |

Verification by kind in neckbeard: environment 1 of 3, procedure **2 of 13**,
finding 10 of 33, decision 8 of 11. Procedures — `ssh`, `brew`, `chezmoi`
command blocks, the kind most likely to rot — are the least verified, and
the `procedure` glance age of 90 days has not yet elapsed for any page.

The verdict's finding about noise still holds and is already scheduled: 14
of 15 agent-builder suspects on 09-19 cited a quest stage file the questlog
rewrites on every pass. Chores `2609191914-jw` (fire on cited content) and
`2609191859-g7` (follow renames) fix the signal; `2609050444-hm` adds
`verify --suspect`. `memory review` should assume those land and build on
them, not duplicate them. Agent-builder's 0 suspects today is the result of
the 09-19 sweep, not of the signal being fixed.

### 3.4 Rot modes observed, with examples

**Accreting hub pages.** `decision-dotfiles-rebuilt-on-chezmoi` (2,826 B,
kind `decision`, so it never glances) has absorbed dated updates since its
creation — "On 2026-09-19 the same bootstrap put the creator's Mac mini on
it…" — and its second paragraph now restates `dotfiles-bare-repo-layout` and
`dotfiles-bootstrap-from-gist`. It is also neckbeard's one live suspect.
Hub pages that take news are the duplication vector in this field; a lexical
scan for near-duplicate *pairs* found essentially none (two pairs above 0.22
Jaccard, both decision pages sharing boilerplate).

**Multi-finding pages.** Pages whose title joins unrelated findings with a
semicolon or "and", or whose body carries an "Also:" tail off the title:

| neckbeard | agent-builder |
|---|---|
| `apt-repository-gpg-and-pipx-module-traps` — "apt_repository needs gpg; pipx module needs pipx 1.7" | `uv-ansi-python-314-and-slim-images` — three findings |
| `pipx-ansible-and-acl-for-become-user` | `index-md-outranks-pages-and-catalog-drops-fields` — "Also, catalog --json…" |
| `dotfiles-submodule-and-git-traps` — "…and two git gotchas" | |
| `molecule-group-vars-link-and-sshd-validate` | |
| `claude-session-name-and-color` — three findings, 5,076 B | |
| `artis3n-tailscale-use-the-collection` — "Also: Molecule galaxy dependency…" | |

Honest counterpoint: `uv-ansi-python-314-and-slim-images` answered recall
questions 9 *and* 10. Packing did not hurt retrieval. It breaks skill rule 2
— one wrong finding cannot be deleted without losing the right ones — so
these are split candidates, not errors.

**Sources hygiene.** Neckbeard: 5 pages with no `## Sources` section
(`brew-bundle-applies-whole-brewfile`, `dotfiles-submodule-and-git-traps`,
`questlog-guard-traps`, `refer-to-the-creator-as-the-user`,
`workspace-dir-for-other-repos`) and 13 whose Sources carry no date.
Agent-builder: 0 and 7. `validate_page` only warns on a missing Sources
section; the verdict left neckbeard's five "for its own maintenance."

**Links.** Neckbeard pages carry 18 `[[wikilinks]]` across 12 pages; none
dangle (two apparent misses are code in backticks). Backlog chore
`2609050220-vv` makes links first-class; a review should list a page whose
linked page is suspect or gone, as that chore already proposes.

## 4. `memory review`: the read-only pass

### 4.1 Contract

- Reads the field, the git history, and the local log. Writes nothing.
  Never runs a `check` (that stays in `doubt`, `verify`, `approve`).
- Prints sections in a fixed order, each a list of pages with the reason and
  the command that acts on it. Empty sections are omitted.
- Logs one `review` event with the counts, so `memory stats` can report
  sweep frequency and size.
- The agent acts with the existing commands. The skill gains one paragraph
  saying when to run review and that a review session's changes go in one
  commit (or on a branch, Section 4.4).

### 4.2 Sections, and where each comes from in `bin/memory`

| Section | Rule | Data already in the wrapper |
|---|---|---|
| **Suspect, by cause** | Every page `suspicion()` marks suspect, grouped by the commit that changed the cited file, so "8 pages from one commit" reads as one event | `suspicion()`, `ref_changed()`; after chore `jw`, content-vs-churn |
| **Unwatched** | No ref, no check. Ask: add a ref or check, or state that the page is unverifiable and why | `page_frontmatter()` |
| **Accreting** | Body grew across ≥3 commits since creation, or a `decision` page over ~2.5 KB, or a page that links to ≥2 others it also restates | `git log --follow -- PAGE`, `parse_page()`, wikilink scan |
| **Multi-finding** | Title contains `;`, or joins clauses with ", and", or body has an `Also:` / `Also,` paragraph | `parse_page()` |
| **Hygiene** | No Sources section; Sources with no date; body over the 8 KB soft limit | `validate_page()` rules, reused |
| **Never read** (this machine) | Recall named the page ≥N times across sessions and no `read` or `pull` followed, in this machine's log | `read_log()`; the `pages` field on `recall`, `read`, `pull` rows |
| **Origin** | For each page above, the author of its first commit, so the agent knows when it is editing a cloned page | `git log --diff-filter=A --format=%an -- PAGE` |

The "Never read" section is the only one that uses the log, and the log is
per machine; the section must say so in its heading. It is the reason the
pass is advisory and the reason no section may delete.

### 4.3 Trigger

The SessionStart hook already runs `doctor --brief`, which runs the ref
check. Add one clause to its line when either holds:

- **Burst:** ≥5 pages suspect, or ≥3 made suspect by one commit —
  "12 suspect, 8 from one commit: `memory review`". This is the pattern of
  all three sweeps that already happened.
- **Accumulation:** ≥15 pages written since the last `review` event in the
  log, or the field over 50 pages with no review event at all. This is the
  "over 50 pages, the session-start line says so" item from the 2026-09-04
  usage review, which was accepted and never shipped.

Neither is a clock. A field that is not being written to is not reviewed.

### 4.4 Copy-on-write, for free

A review session that will delete or rewrite more than a handful of pages
should run on a branch — `memory/review-YYYY-MM-DD` — and the creator merges
the diff. That is Anthropic's Dreams design (a separate output store the
human adopts or discards) with git as the store. Nothing new needs building;
the skill paragraph says when to branch, and the cap in Section 5 is the
threshold.

### 4.5 What it must not do

- No model call. The wrapper stays deterministic.
- No merge. Merging two pages destroys per-finding deletability, the
  property skill rule 2 exists to protect. Splitting is the operation this
  field needs more often than merging.
- No deletion on the log's evidence. "Never read on this machine" is not
  "never read."
- No `check` execution. A cloned page's check is remote code; `doubt` and
  `approve` already handle that boundary.

### 4.6 Measuring it

Before: the recall questions (10 of 10 today), `memory cost`, page count and
bytes. After a review: the same, plus the `review` event's counts. The
research's expectation is that the field gets smaller and cleaner and recall
stays flat; if recall drops, the pass removed something load-bearing and the
branch shows what.

## 5. The blast-radius cap: an open decision

**Purpose.** Bound how much one session can destroy before a human looks.
Git is the backstop, so this is about review load and about a bad session
not silently gutting the field, not about data loss.

**What counts.** A `delete`, and a `write --force` that replaces a page this
session did not create (a full rewrite is a delete plus a write). `verify`
does not count. `memory review` is read-only and never counts.

**Observed load.** Two weeks of use produced 2 and 5 deletes in total; the
largest single sweep rewrote 5 and deleted 1. The only larger event was the
creator's deliberate 79-page reset, which is the case the override exists
for.

**Why a fixed fraction is wrong here.** The creator's note: the field grows,
and a percentage grows with it. OpenClaw's 25% of 60 pages is 15; of 300 it
is 75, which is not a diff anyone reviews in one sitting. A fixed count fails
the other way: 5 is fine at 60 pages and blocks every legitimate
post-migration cleanup at 300.

**Options.**

| Rule | at 20 pages | at 60 | at 150 | at 300 | at 1,000 | Notes |
|---|---|---|---|---|---|---|
| A. Fixed 25% (OpenClaw) | 5 | 15 | 38 | 75 | 250 | review load unbounded |
| B. Fixed 5 | 5 | 5 | 5 | 5 | 5 | blocks legitimate cleanups at scale |
| C. max(3, 10%), ceiling 15 | 3 | 6 | 15 | 15 | 15 | simple; ceiling is arbitrary |
| **D. ceil(√N), floor 3** | 5 | 8 | 13 | 18 | 32 | grows with the field, slower than it |
| E. No cap inside a review on a branch; 2 outside | — | — | — | — | — | moves the decision to "did you branch" |

**Recommendation.** D, `ceil(√N)` with a floor of 3, as the default; E's
branch rule layered on top, so a session that has branched for a review is
exempt because the merge is the review. Override by the creator only,
through the same shape as `MEMORY_ALLOW_NETWORK`: `MEMORY_ALLOW_DESTROY=N`,
which the PreToolUse guard prompts for. At today's sizes D gives 8 and 7,
above anything a normal session has done and below what a person reviews in
one diff. The number is not load-bearing until a field passes ~150 pages;
record the rule, ship D, and revisit with the first review event that hits
it.

## 6. What not to build, and why

| Don't | Because |
|---|---|
| A model call in the wrapper (scoring, summarising, merging) | HaluMem: the update operation is the least reliable one measured (best 65%). Auto-Dreamer's LightMem case and OpenClaw #67363: a pass that writes without a human in the loop packs and duplicates. DEVELOPMENT.md's "never reimplements storage, search, or indexing" should add "or synthesis." |
| Automatic merging of overlapping pages | Skill rule 2. And the field's duplication problem is hub pages accreting, not pairs; the fix is splitting. |
| Decay tiers or time-based deletion | Design decision 4, and the research: no evidence that age-based forgetting helps; `decision` never aging is right. Age stays a glance. |
| Promotion by recall frequency | MINJA: frequency is what an injected record optimises for. Recall counts are display, never trust. |
| Calling it "dream" | The report's finding that the metaphor invites phases you do not need. `review` sits beside `doubt` and `verify` in the plugin's own vocabulary. |

## 7. Relation to open work

| Existing item | Relation |
|---|---|
| `2609191914-jw` refs fire on cited content | Prerequisite for the "Suspect, by cause" section to be signal rather than churn |
| `2609191859-g7` refs follow a renamed file | Same |
| `2609050444-hm` `verify` several pages, `--suspect` | The action the "Suspect" section hands to the agent |
| `2609050220-vv` pages reference other pages | Supplies the link scan for "Accreting" and a "linked page suspect or gone" line |
| `2609050313-wg` hook cost | `review` is not a hook; the trigger clause rides on the existing `doctor --brief` ref check and adds one log read |
| Usage review 1, "over 50 pages the session-start line says so" | Accepted 2026-09-04, never shipped; it is trigger 4.3 (b) |

## Appendix: how the numbers were computed

Fields read from `/home/user/agent-neckbeard/.memory` at commit `5f4ea45` and
`/home/user/agent-builder/.memory` at `ca6edfc` on 2026-09-19, history
fetched to depth 1000.

- **Ops per day:** `git log --date=short --name-status -- .memory/`, counting
  A/M/D per day.
- **Frontmatter-only vs body edits:** for each M, the diff minus lines
  matching `^[+-](verified|updated|refs|- path@sha|uuid|created)`; zero
  remaining lines means a verify.
- **Suspicion coverage:** frontmatter parsed per page; `refs` entries of the
  form `path@sha` or a URL; `check:` present or not.
- **Suspect now:** the wrapper's own rule, `git log --oneline sha..HEAD --
  path` non-empty, run per ref.
- **Multi-finding:** title contains `;`, or `, and`, or "and … traps|gotchas";
  or body has a paragraph starting `Also:`/`Also,`. The heuristic over-flags
  pages whose summary uses semicolons as style; the lists in 3.4 are the
  pages read and judged by hand.
- **Near-duplicate pairs:** Jaccard over content words (stopwords removed,
  three letters or more) of title + summary + body, pairs ≥ 0.22.
- **Wikilinks:** `\[\[([^\]|#]+)` over bodies, resolved against page names.
- **Sources:** presence of `## Sources`; a date is any `20\d\d-\d\d-\d\d` after
  it.
- **Log-derived figures** (sessions, recall hits, reads, cost) are quoted
  from `usage-analysis.md` and `verdict.md` in the agent-builder quest; the
  log itself is per machine and was not available here.
