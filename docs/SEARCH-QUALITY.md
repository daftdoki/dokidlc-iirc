# Search quality: findings and plan

What iirc suggests to the agent, how often it is right, and what to change.
Written 2026-10-09 from one tune run and ten research reports, then
revised after an independent review. The creator asked for: a page audit
that `tune` runs, better pages from the moment they are written, a review
of what the model sees, a comparison of embedding models, a middle tier
that needs no ollama, and a view on a port to Go or Rust.

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
core. On the same efficiency core, today's `iirc search` takes 4.6 to
6.2 s, past the hook's 5-second limit. It needs 125 MB of wheels for
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

## Decisions for the creator

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
