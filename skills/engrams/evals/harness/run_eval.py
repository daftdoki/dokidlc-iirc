#!/usr/bin/env python3
"""Run one engrams-skill eval headlessly in a fresh fixture copy.

    MEMORY_EVAL_WORKSPACE=... run_eval.py --iteration 1 --eval search-before-debug --condition new_skill --run 1

Conditions: new_skill (plugin-live, the checkout), old_skill (plugin-snapshot, a
chosen rev), without_skill (plugin-noskill, the checkout minus skills/). setup.sh
builds the three copies and the fixtures.

Copies the fixture, points the plugin copy at it with --plugin-dir, runs
`claude -p`, and leaves in the run directory:
  transcript.jsonl      the stream-json output
  timing.json           duration and tokens from the result event
  outputs/answer.md     the final assistant text
  outputs/transcript.md tool calls in order, for the viewer
  outputs/engrams-after/ the .engrams/ field after the run
  outputs/engrams-log.jsonl  the plugin's own log for the run
  outputs/repo.diff     what changed in the fixture
"""
import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

W = Path(os.environ.get("MEMORY_EVAL_WORKSPACE") or sys.exit("set MEMORY_EVAL_WORKSPACE; see setup.sh"))
EVALS = json.loads((Path(__file__).resolve().parent.parent / "evals.json").read_text())
PLUGIN = {"new_skill": W / "plugin-live", "without_skill": W / "plugin-noskill", "old_skill": W / "plugin-snapshot"}
WITH_SKILL_PREFIX = "The `engrams` skill for this repository is at {skill}. Read it before you start.\n\n"


def clean_path() -> str:
    return ":".join(p for p in os.environ["PATH"].split(":") if "/.claude/plugins/cache/" not in p)


def render_transcript(events: list[dict]) -> tuple[str, str]:
    lines, answer = [], ""
    for e in events:
        if e.get("type") == "assistant":
            for c in e["message"]["content"]:
                if c["type"] == "tool_use":
                    inp = c["input"]
                    show = inp.get("command") or inp.get("file_path") or inp.get("skill") or json.dumps(inp)[:200]
                    lines.append(f"- **{c['name']}** `{str(show)[:300]}`")
                elif c["type"] == "text" and c["text"].strip():
                    answer = c["text"]
                    lines.append(f"- text: {c['text'][:200].strip()!r}")
        elif e.get("type") == "user":
            for c in e["message"]["content"]:
                if isinstance(c, dict) and c.get("type") == "tool_result":
                    cc = c.get("content")
                    s = cc if isinstance(cc, str) else " ".join(x.get("text", "") for x in cc if isinstance(x, dict))
                    lines.append(f"  - result: `{s[:240].replace(chr(10), ' ')}`")
    return "\n".join(lines) + "\n", answer


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--iteration", type=int, required=True)
    ap.add_argument("--eval", required=True)
    ap.add_argument("--condition", choices=list(PLUGIN), required=True)
    ap.add_argument("--run", type=int, default=1)
    ap.add_argument("--model", default="opus")
    ap.add_argument("--timeout", type=int, default=900)
    a = ap.parse_args()

    ev = next(e for e in EVALS["evals"] if e["name"] == a.eval)
    plugin = PLUGIN[a.condition]
    run_dir = W / f"iteration-{a.iteration}" / f"eval-{ev['id']}-{ev['name']}" / a.condition / f"run-{a.run}"
    if run_dir.exists():
        sys.exit(f"{run_dir} exists; remove it first")
    repo = run_dir / "repo"
    state = run_dir / "state"
    out = run_dir / "outputs"
    shutil.copytree(W / "repos" / ev["fixture"], repo, symlinks=True)
    state.mkdir(parents=True)
    out.mkdir()

    env = dict(os.environ, PATH=f"{plugin / 'bin'}:{clean_path()}", XDG_STATE_HOME=str(state))
    env.pop("CLAUDE_PROJECT_DIR", None)
    env.pop("CLAUDECODE", None)
    # warm the field's index for this copy so the first recall hook does not time out
    subprocess.run(["engrams", "search", "warm"], cwd=repo, env=env, capture_output=True, stdin=subprocess.DEVNULL)

    prompt = ev["prompt"]
    if a.condition != "without_skill":
        prompt = WITH_SKILL_PREFIX.format(skill=plugin / "skills" / "engrams" / "SKILL.md") + prompt
    (run_dir / "prompt.txt").write_text(prompt)
    cmd = [
        "claude", "-p", "--model", a.model, "--plugin-dir", str(plugin), "--setting-sources", "project",
        "--permission-mode", "bypassPermissions", "--output-format", "stream-json", "--verbose", prompt,
    ]
    t0 = time.time()
    with open(run_dir / "transcript.jsonl", "w") as fh, open(run_dir / "stderr.txt", "w") as eh:
        try:
            proc = subprocess.run(cmd, cwd=repo, env=env, stdin=subprocess.DEVNULL, stdout=fh, stderr=eh, timeout=a.timeout)
            rc = proc.returncode
        except subprocess.TimeoutExpired:
            rc = "timeout"
    wall = time.time() - t0

    events = []
    for line in (run_dir / "transcript.jsonl").read_text().splitlines():
        try:
            events.append(json.loads(line))
        except ValueError:
            pass
    result = next((e for e in events if e.get("type") == "result"), {})
    usage = result.get("usage", {})
    total = sum(usage.get(k, 0) for k in ("input_tokens", "output_tokens", "cache_read_input_tokens", "cache_creation_input_tokens"))
    duration_ms = result.get("duration_ms", int(wall * 1000))
    (run_dir / "timing.json").write_text(json.dumps({
        "total_tokens": total, "duration_ms": duration_ms, "total_duration_seconds": round(duration_ms / 1000, 1),
        "num_turns": result.get("num_turns"), "cost_usd": result.get("total_cost_usd"), "exit": rc,
    }, indent=1) + "\n")

    md, answer = render_transcript(events)
    (out / "transcript.md").write_text(md)
    (out / "answer.md").write_text(answer + "\n")
    if (repo / ".engrams").is_dir():
        shutil.copytree(repo / ".engrams", out / "engrams-after")
    logs = list((state / "dokidlc-engrams").glob("*.jsonl")) if (state / "dokidlc-engrams").is_dir() else []
    (out / "engrams-log.jsonl").write_text("".join(p.read_text() for p in logs))
    diff = subprocess.run(["git", "status", "--short"], cwd=repo, capture_output=True, text=True).stdout
    diff += "\n" + subprocess.run(["git", "diff"], cwd=repo, capture_output=True, text=True).stdout
    (out / "repo.diff").write_text(diff)
    print(f"{a.eval} {a.condition} run-{a.run}: exit={rc} {duration_ms/1000:.0f}s {total} tokens turns={result.get('num_turns')}")


if __name__ == "__main__":
    main()
