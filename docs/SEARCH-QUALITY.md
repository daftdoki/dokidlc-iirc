# Search quality: findings, plan, and results

What iirc suggests to the agent, how often it is right, and what to change.
Written 2026-10-09 from one tune run and ten research reports, then
revised after an independent review. The creator asked for: a page audit
that `tune` runs, better pages from the moment they are written, a review
of what the model sees, a comparison of embedding models, a middle tier
that needs no ollama, and a view on a port to Go or Rust. Phases 1 and 2
are built; [Results](#results) has what they measured.

## What we measured

Two judged sets. Agent-builder: 98 prompts and 1,164 pooled pairs (the
top pages of nomic, Qwen3-Embedding-0.6B, and EmbeddingGemma, plus the
pages the agent read). Neckbeard: 79 prompts and 443 pooled pairs. A
blind second judge agreed with the first labels at kappa 0.55 and was
stricter, so the model and reranker numbers use a strict bar: a page is
relevant when the agent's work on that prompt depended on a fact or
procedure in it. The suggestion-flow numbers come from the earlier, soft
labels and say so. Differences smaller than about 0.06 are inside the
noise of sets this size. MiniLM was in no judging pool, so its numbers
are on the soft labels.

## Findings

**Most prompts have no relevant page.** Under the strict bar, 31 of 74
human prompts in agent-builder have one. Recall still speaks on most of
the others, so silence is the right answer more often than any page.

**Precision is low, and the gate causes most of it.** In the
agent-builder session about 9% of suggested pages were relevant (54
judged suggestions, soft labels). Neckbeard's live hook did better, 21%
to 41%. Of 69 judged noise passes in agent-builder, 64 passed as
`meaning+term`: the "strong term" that widens the distance from 0.28 to
0.34 is often a plain word such as under, without, or model. A strong
term appears in 54% of relevant pairs and 49% of noise pairs, so it does
not separate them. All 18 term-only passes matched an identifier in a
page's Sources section, such as `dokidlc-iirc` or a session id in a
scratch path.

**Ranking lets common words decide.** A semantic hit that also contains a
common word such as "agent" ranks above a much closer hit with no string
match, because the ranking counts every matched term, common or rare.

**Machine prompts drew a large share of the noise.** Subagent hand-backs,
task notifications, and session messages reached the prompt hook, and
recall searched their wrapper text: 13 of 54 prompt recalls, and 21 of 47
noise labels in one judged batch. Fixed in 5e6d7e9: recall removes those
blocks and skips a prompt with nothing left.

**Repeats waste most of the line.** 77% of suggestions named a page
already suggested earlier in the same session.

**The model chooses well; the line asks too much.** The model acted on
none of 33 noise suggestions. The instruction "Read before you
investigate" asks for reads that a line this imprecise does not deserve.
Snippet length did not change read rates. Two relevant pages lost their
point to the 90-character cut, and three relevant summaries spent 28 of
their 90 characters on "Creator decision 2026-MM-DD:". The sample is
small; treat this as a reason, not a measurement.

**`iirc read` leads with metadata and drops trust markers.** It prints
uuid and timestamps before the body, leaves `NAME` literal in its
footer, and never prints suspect or glance markers, though the skill and
the guard say it does.

**Page edits barely move distance.** Ten pages, six levers: every lever
moved distance by 0.02 or less. Adding text (identifiers in the summary,
an "Asked as:" line) pushed relevant prompts away. A body trimmed to the
finding pushed noise away slightly more than relevant. Long pages sit
near more prompts, but they are near more relevant prompts too: length
predicts how often a page is noise, not the share, and in neckbeard
precision rises with page size. Two kinds of page are noise magnets in
neckbeard: short generic rule pages, and superseded pages that keep
their old text. Page rules help at the margin; the gate and the model
matter more.

**The embedding model is weak.** nomic-embed-text separates relevant
from noise pairs at chance in agent-builder (pair AUC 0.505) and weakly
in neckbeard (0.586). Qwen3-Embedding-0.6B separates relevant pages from
the rest of the store better in both sets (agent-builder 0.874 against
0.760, interval +0.04 to +0.19; neckbeard 0.92 against 0.86, interval
clears zero). Its ranking gain (MRR) does not hold under strict labels.
EmbeddingGemma, bge-m3, and snowflake-arctic-embed2 are in the same band
in neckbeard. No embedder gives a usable stay-quiet signal. Qwen3-0.6B
is Apache-2.0, embeds a prompt in about 10 ms, and frame already serves
it (43 ms from Nyx). memoryfield-tool hardcodes nomic and its prefixes,
so a switch needs engine changes and a new index.

**A middle tier without ollama works.** all-MiniLM-L6-v2 run in-process
through onnxruntime, with pages cut into 200-token windows, ranks better
than nomic through ollama on the soft labels (MRR interval +0.06 to
+0.21; this may shrink under strict labels, as Qwen3's did). As a fresh
process, the way the hook runs, it starts in 112 ms on a performance core
on a quiet machine (139 ms under load) and 370 to 520 ms on an efficiency
core. Under the same efficiency-core proxy (`taskpolicy -b`), the
recall hook takes 3.0 to 3.1 s today, against 0.51 s on a performance
core: inside the 5-second limit, with little room for a slower machine
or a cold ollama load. `iirc search` takes 5.8 to 7.3 s there, but the
hook does not run it. It needs 125 MB of wheels for
macOS and Linux, a 23 MB model, and no compiler; all Apache-2.0 or MIT.
A smaller fallback (potion-base-8M static embeddings with BM25) needs no
onnxruntime: numpy, tokenizers, safetensors, and PyStemmer.

**A reranker reorders and may help silence, but not yet.**
bge-reranker-v2-m3 over Qwen3's top 10 raises the share of human prompts
whose first page is relevant from 0.32 to 0.48 (interval touches zero).
Its top score separates prompts with a relevant page from those without
at AUC 0.72 against 0.56 for cosine, in agent-builder; in neckbeard the
gain is inside the noise, and the two rerankers swap order on soft
labels. At 80% recall it still speaks on half the prompts with no
relevant page. It cannot load inside the 5-second hook (5 to 10 s cold);
it needs a resident daemon, which ollama cannot host.

**A port is not needed for speed.** Recall takes 0.5 s; 0.31 s of it is
the memoryfield-tool subprocess. A 30-line Python prototype does the
semantic half in-process in 0.07 s; Go does it in 21 ms. The slowest
hook is `doctor --brief` at 2 s, from 195 git subprocesses, which Python
can batch. The strongest speed case for a binary is the hook after every
Bash call (0.12 s, 1,226 calls in one day). Go beats Rust here: five
targets from one Mac without a C toolchain, and its YAML library
round-trips all 88 pages byte for byte. A port of memoryfield-tool from
its source is a translation and must stay AGPL-3.0-or-later; a
clean-room build from the MIT spec could take any license, but this
project has read the tool's source. Cal Paterson has said nothing about
ports; he invites tools built from the spec and dislikes his own
four-package-manager install. His one outside PR (an alternative
embedding model) has waited five weeks.

## Plan

Each phase ships on its own and is measured before the next starts.
`iirc tune` stays the entry point for optimizing.

### Phase 1: measure, then fix the line, the gate, read, and write

Measurement comes first, because the gate changes alter the inputs that
`iirc tune sweep` replays.

1. **Replay harness.** `iirc tune sweep --replay` recomputes the string
   side of each judged pair from the full prompt (recovered from the
   transcript), with the current code, instead of the term lists logged
   at recall time. It reads the pooled judged sets as well as the tune
   judgments. Every gate change below is measured with it. A second
   harness replays prompts into fresh sessions with variant recall lines
   and counts reads of relevant and noise pages, for the line changes,
   which the judged sets cannot measure.

Gate and ranking, then a retune:

2. Rank by rare matched terms, not by every matched term (`hits` counts
   common words today). Update `test_string_search_and_hybrid_ranking`.
3. Term matching ignores the Sources section and `[[links]]`.
4. A strong term needs more than rarity in the store: weight terms by
   inverse page frequency, and drop a short list of plain English words.
   Expect a small effect; the report shows no list separates relevant
   from noise on its own.
5. Failure recalls require `meaning+term` and suggest one page at most,
   inside `gate()`, so the sweep and the hook agree.
6. Retune `semantic_only` and `both` with the replay sweep.

The recall line, each measured with the session replay:

7. Suggest a page at most once per session, unless it was neither read
   nor suggested in the last 10 recalls.
8. Change the instruction to "Read a page whose summary bears on this
   task; skip the rest." Change `RECALL_RE` in hooks/register.tsx and its
   test fixture in the same commit, or the suggestion rows stop drawing.
   Same wording in the CLAUDE.md paragraph `iirc init` writes, and in
   SKILL.md.
9. Drop the percentage from the printed line; keep `term match` as a
   warning on weak hits. The log keeps the distance as a number, and the
   session summary and the status card read it from there.
10. Try two pages instead of three, and the previous prompt added to a
    short follow-up's query; keep each only if the replay shows a gain.

Read:

11. `iirc read` prints `NAME.md: TITLE`, any suspect or glance line, the
    body, then refs and verified. No uuid or timestamps. The footer names
    the page.

Write (`iirc write` checks; the skill carries the reasons):

12. Refuse a secret pattern (tokens, keys) anywhere in the page.
13. Warn on: a summary that starts with a date or "Creator decision"; a
    title over 70 characters; a summary whose first 90 characters do not
    hold a word of the title.
14. Skill rules added: write in the words a future prompt or error will
    use; quote error text exactly; search before every write and replace
    instead of adding; a page that reverses another says which, and the
    old text is rewritten or deleted; say where the fact holds.

Audit:

15. New command `iirc audit [PAGE]`. Script checks per page: the write
    checks above; a search for the page's own title ranks it first;
    hubness (how many pages and judged prompts fall within the gate of
    this page), reported with its relevant share, not as a fault alone;
    tune history (noise against relevant judgments); a superseded page
    that keeps its old text. One line per finding, with the fix.
16. `iirc tune` runs `iirc audit` after the sweep. The tune reference
    adds an agent step: for each flagged page, write two realistic
    prompts without the title's words, check the page ranks in the top
    three, and propose a rewrite, split, merge, or delete. The creator
    approves each change, as today.

Speed:

17. `doctor --brief` batches its git calls (195 subprocesses today).

Tune fixes from the first run:

18. `read_unsuggested` counts only reads made for guidance: drop reads
    by verify, write, and doctor loops, and reads before the recall.
19. `tune judge` stops marking the judging session as tuned for good.
20. Normalize page names with and without `.md`; fix the gather join
    that attached a recall to the wrong hand-back; keep the failed
    command and its error in the evidence.
21. Recordings mark their sessions (an environment variable the start
    row records), and gather skips them.
22. Tests stop leaking `test-*` directories into memoryfield-tool's
    cache.

Not in the plan, against the evidence: a size limit on page bodies, and
a warning when Sources outweigh the body. Long pages are near more
relevant prompts too, and removing Sources moved nothing measurable.
Also out until measured: treating a page at 0.35 to 0.45 that holds the
prompt's identifier as a pass (production shows no term-only pass that
was relevant).

### Phase 2: embeddings in the wrapper, and a model choice

23. The wrapper embeds and searches in-process, reading page vectors it
    stores beside the index; memoryfield-tool keeps read, write, and
    validate. This removes the 0.31 s subprocess and frees the model
    choice from the engine. Also change: the tool's `write` starts a
    nomic reindex in the background, which must stop when nomic is not
    the model; `near_duplicates` assumes 768 dimensions; doctor and setup
    check the pinned model name.
24. Knobs per model. The config loader refuses unknown keys today, and a
    config error turns every hook off, so the loader, the knob ranges
    (0.10 to 0.60), and the sweep grid (0.20 to 0.46) change first.
    MiniLM's useful distances sit near 0.5 to 0.7.
25. `iirc setup` offers: ollama (nomic, Qwen3-0.6B, EmbeddingGemma), an
    OpenAI-compatible host (frame's `svc:llm`), the CPU tier
    (MiniLM-ONNX, windows), and substring.
26. Before choosing a default, a pooling round judges the top pages of
    each candidate model, MiniLM included, with the strict bar. Then:
    Qwen3-0.6B where ollama or a host is available, MiniLM-ONNX
    otherwise, substring last, unless that round says otherwise.

### Phase 3 and later, each on the creator's word

- A resident reranker as a stay-quiet signal, once phase 1 and 2
  numbers show what is left. The evidence today is one set.
- A Go binary for the hook path, after writing to Cal Paterson and
  choosing a license path.

## Results

Phases 1 and 2 were built on 2026-10-09 as quest 2610100115-p5 in
agent-builder, whose `plan.md` records each step's measurement under
"Deviations from plan". A count below is relevant passes, noise passes,
and relevant pairs refused, from `iirc tune sweep --replay` on the strict
labels. Agent-builder has 1,131 judged pairs (60 relevant) from 98
prompts; neckbeard has 437 pairs (77 relevant) from 79 prompts.

**The gate passes more relevant pages and fewer noise pages.**

| Replay | Agent-builder | Neckbeard |
|---|---|---|
| Baseline, 0.28/0.34 | 13, 74, 47 (P 0.15, R 0.22, F1 0.18) | 29, 55, 48 (P 0.35, R 0.38, F1 0.36) |
| Sources and links left out (item 3) | 16, 84, 44 (F1 0.20) | 28, 55, 49 (F1 0.35) |
| Rarity by share and common words (item 4) | 13, 54, 47 (P 0.19, F1 0.20) | 23, 26, 54 (P 0.47, F1 0.37) |
| Items 2 to 5 together, old knobs | 13, 53 (P 0.20, F1 0.21) | 24, 27 (P 0.47, F1 0.37) |
| Retuned, RARE_SHARE 0.10, 0.28/0.38 (item 6) | 19, 71, 41 (P 0.21, R 0.32, F1 0.25) | 31, 41, 46 (P 0.43, R 0.40, F1 0.42) |

Item 2 changed no replay count, because the gate does not read the rank
and the replay has no cap; with a cap of 3, 2 of 98 prompts got a
different top three, all of it noise. Item 5 has no measurement: neither
set holds a failure recall. For item 6, 21 grid points passed the bar, which compares against the
baseline row (13, 74 on agent-builder): no fewer relevant passes, fewer
noise passes, and no relevant pass lost on neckbeard. Of these, RARE_SHARE 0.10, `semantic_only` 0.28, and
`both` 0.38 had the best agent-builder F1.

**The line keeps its percentage and its length.** Each session replay
ran 40 human prompts, seed 1, Sonnet, at most 8 turns, with the passed
pages fixed in a file. The baseline run of the old line read 10
relevant, 16 noise, and 5 unlabelled pages over 40 runs ($4.92). Two
later runs compared the variants on the same passed pages:

| Line | Relevant reads | Noise reads | Landed |
|---|---|---|---|
| "Read before you investigate" | 11 | 24 | |
| "Read a page whose summary bears on this task; skip the rest" (item 8) | 13 | 18 | yes |
| the same, without the percentage (item 9) | 9 | 20 | no |
| current line, second run | 14 | 21 | |
| two pages (item 10) | 9 | 28 | no |
| the previous prompt added to a prompt under 80 characters (item 10) | 10 | 23 | no |

The two runs cost $12.25 and $10.45. On 28 prompts whose line was the
same in two variants, reads differed by 13 against 9 relevant pages, so
a difference of a few reads over 40 prompts is inside run-to-run
variation. Each gate held the line to its current form when unsure.
After item 9 failed its bar, the creator chose to keep the percentage.

**Once per session, by the creator's choice.** A log replay
(`line-replay.py --repeats`, 123 sessions, 2,720 recalls, 5,256
suggestions) measured item 7's rule: it left out 51.1% of suggestions and
lost 158 later reads over 49 session-page pairs, 12 with a plain cost.
Read-only lost none but left out only 18.6%. The creator chose to name a
page once per session, with the record reset when the context is
compacted: "Anything more than one is a waste of context." That rule
leaves out 70.1% of 5,258 suggestions, with at most 206 lost reads over
55 session-page pairs, 15 with a plain cost. With the 10-recall check,
recall on agent-builder went from a median 474 ms to 509 ms.

**Speed.** `doctor --brief` on agent-builder went from 216 git calls in
2.63 to 2.80 s to 39 calls in 0.73 to 0.74 s (item 17). Search in the
wrapper (item 23) matched memoryfield-tool's distances to 1.1e-6 over
777 page-query pairs, left both replays byte-identical, and cut recall
on agent-builder from a median 0.564 s to 0.251 s. `iirc index` embeds
95 pages in 2.3 s.

**The audit's first run** on agent-builder found 79 findings in 95
pages: 48 title, 14 summary, 17 hub, and none of own-title, superseded,
or secret. It took about 40 s before item 23.

**The models nearly tie at the gate.** The pooling round (item 26)
listed each model's top three unlabelled pages per replay prompt: 674
pairs. A stratified half, 345 pairs, was judged with the strict bar. It
added no relevant pair: all 18 pairs judged relevant were pages written
after their prompt, so they were set to unsure. The chosen defaults are
the best agent-builder F1 that loses no relevant pass on neckbeard
against the model's own earlier defaults:

| Model | `semantic_only` / `both` | Agent-builder F1 | Neckbeard F1 |
|---|---|---|---|
| nomic-embed-text | 0.28 / 0.38, unchanged | 0.24 | 0.35 |
| qwen3-embedding:0.6b | 0.40 / 0.60 | 0.24 | 0.40 |
| embeddinggemma | 0.40 / 0.68 | 0.25 | 0.36 |
| all-minilm-l6-v2 | 0.60 / 0.68 | 0.28 | 0.36 |

No point passed the item 6 bar for any model, because qwen3 and gemma
pass almost no noise at nomic's knobs. The store-ranking gap the model
research measured does not carry over to a gate at a fixed distance.
The OpenAI-compatible qwen3-embedding takes the local qwen3's values,
unmeasured. Each model's near-duplicate line flags agent-builder's one
closest page pair, as nomic's 0.10 does (qwen3 0.17, gemma 0.14, MiniLM
0.20); its duplicate line is 0.7 of that, a choice, not a measurement.

**What was built, changed, or dropped.** The numbers are the plan items
above.

| Item | Outcome |
|---|---|
| 1 | Built: `tune sweep --replay`, `scripts/replay-files.py`, and the session replay `scripts/line-replay.py`. |
| 2, 3 | Built. |
| 4 | Changed: rarity is a share of pages (`RARE_SHARE` 0.10), not a weight. The first word list, first20hours google-10000-english, permits only educational and personal use, so the list is the 1,000 top English words of wordfreq 3.1.1, CC-BY-SA 4.0, with a `NOTICE` file and `scripts/common-words.py` to rebuild it. |
| 5 | Changed: `meaning+term` is required on a failure only with semantic search on; string-only search keeps the `term` rule. The one-page cap holds in both. New verdict `failure_needs_both`. |
| 6 | Built: `both` 0.34 to 0.38. |
| 7 | Changed: once per session, reset at compaction, instead of the 10-recall window. Verdict `repeat`. |
| 8 | Built. |
| 9 | Dropped by the creator after the replay; the line and the row keep the percentage. |
| 10 | Dropped: neither experiment passed its bar. |
| 11 | Built; `iirc pull` prints pages the same way. |
| 12 | Built; each secret pattern starts at a word, so `task-...` never matches `sk-`. |
| 13, 14, 16 | Built. |
| 15 | Changed: `hub` rests on tune judgments only, because page-to-page distances are not on the prompt-to-page scale (for each page, 82 to 94 of 95 pages fell within 0.38); `superseded` matches only the link form or the frontmatter key. |
| 17 to 22 | Built. |
| 23 | Built, with an addition: a search that finds pages without vectors starts one background `iirc index`, at most every ten minutes per store. A search embeds at most 5 changed pages. |
| 24 | Built: `[recall.MODEL-ID]`, a quoted name for a model with a dot, and `doctor --fix` moving a flat `[recall]` table. |
| 25 | Built; MiniLM runs the fp32 model, not the 23 MB int8 one, so every machine computes the same vectors. |
| 26 | Built: setup offers qwen3-embedding:0.6b where ollama or a host answers, MiniLM otherwise, substring last. A machine with no model in its setup file keeps nomic. |
| Phase 3 | Not started: ideas 2610100122-x9 (reranker) and 2610100122-zj (native binary). |

## Decisions for the creator

Decisions 1 and 2 are taken: phase 1 was built with the changes in
[Results](#results), and phase 2 moved search into the wrapper.

1. Approve phase 1 as written, or change items.
2. Phase 2 moves search out of memoryfield-tool into the wrapper. The
   alternative is a change upstream, which waits on Cal. Which?
3. Write to Cal Paterson now (an issue on the spec repo, or email) about
   model choice and a compatible Go implementation?
4. For a later port: keep calling the AGPL tool, port it under AGPL,
   build clean-room from the spec, or ask Cal first.
5. Cleanup: the six pulled ollama models (about 5.2 GB), the two
   rerankers in `~/.cache/huggingface` (3.3 GB), and the research
   downloads in the session scratchpad (about 7 GB). Remove now, or keep
   for the phase 2 pooling round?
6. The research reports live in this session's scratchpad, which does
   not last. Keep a copy, and where? They quote prompts, so a public
   repository needs a privacy pass first.

## Sources

The research reports, scripts, and judged data are in the agent-builder
session scratchpad (`pageopt/`), session b4dd91da, 2026-10-09:
mechanics, experiments, retrieval research, memory practice, the
suggest and read flow, models, CPU tier, port, reranker, other
repositories, and label agreement. The tune judgments are in
`~/.local/state/dokidlc-iirc/tune/judgments.jsonl`.
