# Skill benchmark: memory

Iteration 3: the CLI change (commit 4448e9b: write refuses a body without Sources, the guard stops cat on a page) with the rewritten skill and with no skill at all. Evals 2 and 5 only.

**Model**: claude-opus-5
**Date**: 2026-09-20T23:22:00Z
**Evals**: 2, 5 (2 runs each per configuration)

## Summary

| Metric | New Skill | Without Skill | Delta |
|--------|------------|---------------|-------|
| Pass Rate | 100% ± 0% | 100% ± 0% | +0.00 |
| Time | 55.5s ± 32.1s | 36.8s ± 13.7s | +18.8s |
| Tokens | 201311 ± 61431 | 154793 ± 28236 | +46518 |

## Notes

- Iteration 3 changes the CLI and the guard, not the skill: `memory write` refuses a body without a Sources section and its --help shows the stdin shape; the PreToolUse guard denies cat, head, sed, tail, less, and more on a page file and names `memory read`. Only evals 2 and 5 were rerun, the two where the old baseline missed.
- Without any skill loaded, both evals now pass every assertion: 4 of 4 runs, 36 of 36 assertions. In iteration 1 the same condition scored 9/10 and 9/10 on eval 2 (Sources appended with cat >>) and 5/8 and 4/8 on eval 5 (page read with cat, no verify).
- The Sources refusal never fired: all four eval-2 agents read `memory write --help`, saw the shape in the epilog, and wrote Sources in the same write.
- The cat guard fired in both no-skill eval-5 runs (and in neither with-skill run). Each agent read the denial, re-ran with `memory read`, and then verified the page. The first guard draft anchored at the start of the command and missed a cat after a semicolon; the shipped one matches after ; & | ( or a newline.
- The with-skill runs stay at 100%; the skill body and the scripted halves are now redundant on these two evals, which is the intent: the CLI carries the rule for a session that never loaded the skill, the skill carries the reason for one that did.
- Grader change this iteration: a call the guard denied never ran, so it is dropped before grading. Iterations 1 and 2 had no denials and regrade identically.
- After this iteration the guard's deny became an ask, so the creator can let a raw read through when `memory read` itself cannot run, and a heredoc that happens to contain `; cat .memory/x.md` costs a click instead of a refusal.
