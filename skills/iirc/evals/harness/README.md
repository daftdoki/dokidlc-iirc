# Eval harness for the iirc skill

Measures what the skill body changes in agent behavior, against a baseline
that keeps the hooks and the CLI. Every run is a headless `claude -p` in a
fresh copy of a fixture repository, with the plugin loaded from a copy
through `--plugin-dir`, so hooks fire against the fixture's own `.iirc/`
and nothing touches a real field. Built with skill-creator on 2026-09-20.

## Run it

```
sh skills/iirc/evals/harness/setup.sh            # workspace under $TMPDIR, baseline at HEAD~1
export MEMORY_EVAL_WORKSPACE=...                   # the line setup.sh prints
sh skills/iirc/evals/harness/run_iteration.sh 1 "new_skill old_skill" 2
python3 skills/iirc/evals/harness/grade.py $MEMORY_EVAL_WORKSPACE/iteration-1/eval-*/*/run-*
```

Then, from the skill-creator plugin directory:

```
python3 -m scripts.aggregate_benchmark $MEMORY_EVAL_WORKSPACE/iteration-1 --skill-name iirc
python3 eval-viewer/generate_review.py $MEMORY_EVAL_WORKSPACE/iteration-1 --skill-name iirc \
  --benchmark $MEMORY_EVAL_WORKSPACE/iteration-1/benchmark.json
```

One run takes 15 to 120 seconds on opus and costs $0.10 to $0.50. Four run
at a time. Grade with port 9090 free: eval 3 runs the script the agent
wrote, and an agent sometimes leaves the fixture's dev server up.

## What is where

- `../evals.json`: the five prompts, each with its fixture and assertions.
  The assertion texts are copied from `grade.py`; when one changes, change
  both.
- `build_fixtures.sh`: the three fixture repositories (`ledger`, `syncproj`,
  `devserver`), each a git repo with pages written through the plugin copy
  so they carry real refs and commit stamps. `devserver` has one suspect
  page on purpose.
- `run_eval.py`: one run. Copies the fixture, strips every
  `~/.claude/plugins/cache/` entry from PATH (the parent shell leaks them),
  gives the run its own `XDG_STATE_HOME`, closes stdin, and saves the
  transcript, timing, the field after the run, the plugin's log, and the
  repo diff under `outputs/`.
- `grade.py`: every assertion reads the transcript, the log, or the field.
  A call the guard refused never ran and is dropped before grading.
- `run_iteration.sh`: every eval for the given conditions, four at a time.
- `../benchmarks/`: the numbers and notes from each iteration so far.

## Conditions

- `new_skill`: `plugin-live`, this checkout.
- `old_skill`: `plugin-snapshot`, the repository at the rev `setup.sh` was
  given. The baseline when improving the skill.
- `without_skill`: `plugin-noskill`, this checkout with `skills/` removed.
  Hooks, CLI, and the `CLAUDE.md` paragraph stay, so the delta is the body.

The with-skill prompt names the SKILL.md path, because a headless session
does not fire the Skill tool on its own. That measures the body, not
triggering; skill-creator's description loop measures triggering.

## Evals

1. `search-before-debug`, ledger: tests fail with a misleading error and a
   page holds the fix. The recall hook names the page.
2. `write-after-learning`, syncproj: a script fails twice for two reasons
   not in any page. Grades the shape of what gets written.
3. `suspect-page-same-turn`, devserver: the page that holds the answer
   cites a file that changed since. Grades the diff read and the rewrite.
4. `remember-a-fact-a-file-holds`, ledger: "remember" a fact a page already
   holds. Grades that no second page appears.
5. `search-when-hook-is-silent`, ledger: the same failure as eval 1 with a
   prompt under the recall hook's 40-character floor, so the agent has to
   search on its own. The eval that separates the skill body from the hook.
