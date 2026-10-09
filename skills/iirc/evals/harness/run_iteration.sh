#!/bin/sh
# run_iteration.sh N "cond1 cond2" [runs] : every eval x condition x run, four at a time.
# Iteration directories land in $MEMORY_EVAL_WORKSPACE. Grade with grade.py, then aggregate with
# skill-creator's scripts.aggregate_benchmark and view with its eval-viewer/generate_review.py.
H=$(cd "$(dirname "$0")" && pwd)
: "${MEMORY_EVAL_WORKSPACE:?run setup.sh}"
N=$1; CONDS=${2:-"new_skill old_skill"}; RUNS=${3:-2}
python3 -c "import json;[print(e['name']) for e in json.load(open('$H/../evals.json'))['evals']]" | while read ev; do
  for cond in $CONDS; do
    for r in $(seq 1 $RUNS); do echo "$ev $cond $r"; done
  done
done | xargs -P 4 -L 1 sh -c 'python3 "$0/run_eval.py" --iteration "$1" --eval "$2" --condition "$3" --run "$4"' "$H" "$N"
echo "iteration $N done"
