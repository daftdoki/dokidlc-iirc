# Skill benchmark: memory

Iteration 2: the rewritten skill (commit 74cb05d) against the skill at e56235f. Five evals.

**Model**: claude-opus-5
**Date**: 2026-09-20T22:52:57Z
**Evals**: 1, 2, 3, 4, 5 (2 runs each per configuration)

## Summary

| Metric | New Skill | Old Skill | Delta |
|--------|------------|---------------|-------|
| Pass Rate | 100% ± 0% | 93% ± 12% | +0.07 |
| Time | 42.2s ± 31.2s | 39.6s ± 23.0s | +2.6s |
| Tokens | 159222 ± 77762 | 165506 ± 69428 | -6284 |

## Notes

- New skill: 50 of 50 assertions across ten runs. Old skill: 44 of 50 in this batch. The same old skill scored 39 of 39 on the same prompts in iteration 1, so a two-run sample moves by several points on its own; the direction is consistent, the size is not settled.
- Old-skill misses this batch: one eval-1 run never consulted memory before the fix and read the page with cat; one eval-5 run read the page with cat; one eval-2 run ran sync.py before searching; one eval-3 healthcheck.sh mentions 8080 in a comment. The new skill's opening line names `memory read`, never `cat`, and no new-skill run cat'd a page in either iteration.
- Eval 5 (prompt under the recall hook's 40-character floor) is the discriminating eval for the search section. Iteration 1 baseline without any skill: 0.56 pass, no verify, pages read with cat. With either skill version: every run searched with the error text, read with memory read, verified.
- The reference files were never read in any new-skill run. Setup and string mode did not come up, which is the branch test disclosure is for.
- Cost per run is dominated by turn count, not the skill body. Per-eval token deltas new minus old: eval-1 -15k, eval-2 +37k (one new-skill run took 12 turns), eval-3 -46k, eval-4 +10k, eval-5 -16k. The body shrink is about 2.5k tokens per read and is inside that noise at n=2.
- Four eval-2 runs in the first batch died with SIGTERM at about 30 seconds while another session's headless runs were on the machine; they were rerun alone and completed. An orphaned fixture dev server on port 9090 made the 'exits non-zero when nothing listens' assertion fail until it was stopped; the grader now runs with the port free.
